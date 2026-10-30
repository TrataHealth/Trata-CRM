"""ABDM Milestone 2 — CRM as HIP (facility ABDM_HIP_ID) behind the Trata Option-B callback gateway.

Outbound: HIP-initiated linking (link token -> care-context link), on-discover/on-init/on-confirm, consent on-notify,
health-information on-request + encrypted push + notify. Inbound: /api/v3/... callbacks forwarded by api.tratahealth.com.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import httpx
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from abdm_ecdh import encrypt as fidelius_encrypt, generate_key_material
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import abdm
import abdm_fhir
import abdm_share
import supabase_db as sb

log = logging.getLogger("abdm.hip")
HIP_ID = os.environ["ABDM_HIP_ID"]
HIU_ID = os.environ["ABDM_HIU_ID"]
CALLBACK_BASE = os.environ["ABDM_CALLBACK_BASE"]
HI_LABEL = {"DischargeSummary": "Discharge summary", "DiagnosticReport": "Lab / diagnostic report",
            "OPConsultation": "OPD consultation", "Prescription": "Prescription", "Invoice": "Bill"}
_BG: set = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _spawn(coro):
    t = asyncio.create_task(coro)
    _BG.add(t)
    t.add_done_callback(_BG.discard)


def _iso(v) -> Optional[str]:
    return v.isoformat() if isinstance(v, datetime) else (str(v) if v else None)


def _abha_int(n: str):
    d = "".join(ch for ch in (n or "") if ch.isdigit())
    return int(d) if d else None


# ---------- Record collection from the shared Supabase ----------
async def collect_records(patient_user_id: str) -> List[Dict[str, Any]]:
    pool = await sb.get_pool()
    out: List[Dict[str, Any]] = []
    async with pool.acquire() as conn:
        for r in await conn.fetch("""
            SELECT ds.id::text AS id, ds.final_diagnosis, ds.admission_diagnosis, ds.treatment_given, ds.condition_at_discharge,
                   ds.follow_up_instructions, ds.total_bill_amount, ds.bill_status, ds.prepared_by_name, ds.discharge_time,
                   pa.admission_time, pa.admission_number, pa.hospital_id::text AS hospital_id, hp.name AS hospital_name
              FROM public.discharge_summaries ds JOIN public.patient_admissions pa ON pa.id = ds.admission_id
              LEFT JOIN public.hospital_profiles hp ON hp.user_id::text = pa.hospital_id::text OR hp.id::text = pa.hospital_id::text
             WHERE pa.patient_id::text = $1""", patient_user_id):
            when = r["discharge_time"] or r["admission_time"]
            base = {"provider_user_id": r["hospital_id"], "provider_name": r["hospital_name"], "record_date": _iso(when)}
            out.append({**base, "reference": f"DS-{r['id']}", "hi_type": "DischargeSummary",
                        "display": f"Discharge summary · {r['hospital_name'] or 'Hospital'} · {(_iso(when) or '')[:10]}",
                        "record": {"final_diagnosis": r["final_diagnosis"], "admission_diagnosis": r["admission_diagnosis"],
                                   "treatment_given": r["treatment_given"], "condition_at_discharge": r["condition_at_discharge"],
                                   "follow_up_instructions": r["follow_up_instructions"], "doctor": r["prepared_by_name"],
                                   "start": _iso(r["admission_time"])}})
            if float(r["total_bill_amount"] or 0) > 0:
                out.append({**base, "reference": f"INV-DS-{r['id']}", "hi_type": "Invoice",
                            "display": f"Hospital bill · {r['admission_number'] or ''} · {(_iso(when) or '')[:10]}",
                            "record": {"amount": float(r["total_bill_amount"]), "description": f"In-patient bill {r['admission_number'] or ''}",
                                       "paid": (r["bill_status"] or "").lower() in ("paid", "settled")}})
        for r in await conn.fetch("""
            SELECT c.id::text AS id, c.booking_ref, c.doctor_name, c.doctor_specialty, c.reason, c.outcome_notes, c.fee, c.status,
                   c.preferred_date, c.created_at, c.updated_at, c.hospital_id::text AS hospital_id, c.hospital_name,
                   hp.user_id::text AS hospital_user_id
              FROM public.consultation_bookings c LEFT JOIN public.hospital_profiles hp ON hp.id::text = c.hospital_id::text
             WHERE c.patient_id::text = $1 AND (upper(c.status) = 'COMPLETED' OR c.outcome_notes IS NOT NULL)""", patient_user_id):
            when = r["updated_at"] or r["created_at"]
            base = {"provider_user_id": r["hospital_user_id"] or r["hospital_id"], "provider_name": r["hospital_name"], "record_date": _iso(when)}
            out.append({**base, "reference": f"OPD-{r['id']}", "hi_type": "OPConsultation",
                        "display": f"OPD · Dr {r['doctor_name'] or ''} · {(_iso(when) or '')[:10]}",
                        "record": {"reason": r["reason"], "outcome_notes": r["outcome_notes"],
                                   "doctor": f"Dr {r['doctor_name']}" if r["doctor_name"] else None}})
            if float(r["fee"] or 0) > 0:
                out.append({**base, "reference": f"INV-OPD-{r['id']}", "hi_type": "Invoice",
                            "display": f"Consultation bill · {r['booking_ref'] or ''}",
                            "record": {"amount": float(r["fee"]), "description": f"Consultation fee — Dr {r['doctor_name'] or ''}"}})
        for tbl, prof, fk, items, label in (("path_lab_bookings", "path_lab_profiles", "path_lab_profile_id", "tests", "Lab report"),
                                            ("diagnostic_bookings", "diagnostic_centre_profiles", "diagnostic_centre_profile_id", "scans", "Imaging report")):
            for r in await conn.fetch(f"""
                SELECT b.id::text AS id, b.booking_ref, b.{items}::text AS items, b.report_url, b.status, b.payment_status,
                       b.total_amount, b.scheduled_for, b.updated_at, p.user_id::text AS provider_user_id, p.name AS provider_name
                  FROM public.{tbl} b LEFT JOIN public.{prof} p ON p.id = b.{fk}
                 WHERE b.patient_id::text = $1 AND (b.report_url IS NOT NULL OR b.results_data IS NOT NULL
                       OR lower(b.status::text) IN ('completed', 'report_ready', 'reported', 'delivered')
                       OR lower(coalesce(b.payment_status::text, '')) IN ('paid', 'captured'))""", patient_user_id):
                try:
                    names = [i.get("name") or " ".join(filter(None, [i.get("modality"), i.get("body_part")])) for i in json.loads(r["items"] or "[]") if isinstance(i, dict)]
                except ValueError:
                    names = []
                when = r["updated_at"] or r["scheduled_for"]
                base = {"provider_user_id": r["provider_user_id"], "provider_name": r["provider_name"], "record_date": _iso(when)}
                if r["report_url"] or (r["status"] or "").lower() in ("completed", "report_ready", "reported", "delivered"):
                    out.append({**base, "reference": f"DR-{r['id']}", "hi_type": "DiagnosticReport",
                                "display": f"{label} · {r['provider_name'] or ''} · {(_iso(when) or '')[:10]}",
                                "record": {"title": label, "tests": [n for n in names if n] or None, "report_url": r["report_url"]}})
                if (r["payment_status"] or "").lower() in ("paid", "captured") and float(r["total_amount"] or 0) > 0:
                    out.append({**base, "reference": f"INV-DR-{r['id']}", "hi_type": "Invoice",
                                "display": f"{label.split()[0]} bill · {r['booking_ref'] or ''}",
                                "record": {"amount": float(r["total_amount"]), "description": f"{label} — {', '.join(names)[:120]}"}})
        for r in await conn.fetch("""
            SELECT id::text AS id, doctor_name, items::text AS items, notes, created_at, hospital_id::text AS hospital_id
              FROM public.prescriptions WHERE patient_id::text = $1""", patient_user_id):
            try:
                lines = [i.get("line") or i.get("name") or json.dumps(i) for i in json.loads(r["items"] or "[]") if isinstance(i, dict)]
            except ValueError:
                lines = []
            out.append({"provider_user_id": r["hospital_id"], "provider_name": None, "record_date": _iso(r["created_at"]),
                        "reference": f"RX-{r['id']}", "hi_type": "Prescription",
                        "display": f"Prescription · Dr {r['doctor_name'] or ''} · {(_iso(r['created_at']) or '')[:10]}",
                        "record": {"items": lines or ([r["notes"]] if r["notes"] else None), "doctor": f"Dr {r['doctor_name']}" if r["doctor_name"] else None}})
    return out


class SyncBody(BaseModel):
    patient_user_id: Optional[str] = None


def create_hip_router(db, get_current_user, is_provider, is_internal) -> Dict[str, Any]:
    api = APIRouter(prefix="/api/abdm")
    cb = APIRouter(prefix="/api/v3")

    # ---------- linking engine ----------
    async def sync_patient(rec: Dict[str, Any]) -> Dict[str, int]:
        pid = rec.get("patient_user_id")
        if not pid:
            return {"found": 0, "new": 0}
        found = await collect_records(pid)
        new = 0
        for x in found:
            res = await db.abdm_care_contexts.update_one(
                {"reference": x["reference"]},
                {"$set": {**x, "patient_user_id": pid, "abha_number": rec["abha_number"], "abha_address": rec.get("abha_address"),
                          "patient_name": rec.get("name"), "updated_at": _now()},
                 "$setOnInsert": {"id": str(uuid.uuid4()), "status": "new", "created_at": _now(), "attempts": 0}}, upsert=True)
            new += 1 if res.upserted_id else 0
        if rec.get("abha_address"):
            _spawn(link_pending(rec))
        return {"found": len(found), "new": new}

    async def link_token_for(rec: Dict[str, Any]) -> Optional[str]:
        t = await db.abdm_link_tokens.find_one({"abha_address": rec["abha_address"]}, {"_id": 0})
        if t and t.get("token") and t.get("expires_at", "") > _now():
            return t["token"]
        if t and t.get("status") == "requested" and t.get("requested_at", "") > (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat():
            return None
        body = {"abhaNumber": _abha_int(rec["abha_number"]), "abhaAddress": rec["abha_address"], "name": rec.get("name"),
                "gender": (rec.get("gender") or "O")[:1].upper(), "yearOfBirth": rec.get("year_of_birth")}
        rid = str(uuid.uuid4())
        try:
            r = await abdm.hiecm_post("/v3/token/generate-token", body, {"REQUEST-ID": rid})
        except HTTPException as ex:
            await db.abdm_link_tokens.update_one({"abha_address": rec["abha_address"]}, {"$set": {
                "status": "failed", "requested_at": _now(), "error": str(ex.detail)}}, upsert=True)
            return None
        await db.abdm_link_tokens.update_one({"abha_address": rec["abha_address"]}, {"$set": {
            "abha_address": rec["abha_address"], "status": "requested" if r.status_code < 300 else "failed", "request_id": rid,
            "requested_at": _now(), "error": None if r.status_code < 300 else r.text[:300]}}, upsert=True)
        return None

    async def link_pending(rec: Dict[str, Any]):
        ccs = await db.abdm_care_contexts.find({"abha_address": rec["abha_address"], "status": {"$in": ["new", "failed"]},
                                                "attempts": {"$lt": 5}}, {"_id": 0}).to_list(200)
        if not ccs:
            return
        token = await link_token_for(rec)
        if not token:
            await db.abdm_care_contexts.update_many({"reference": {"$in": [c["reference"] for c in ccs]}, "status": "new"},
                                                    {"$set": {"status_note": "Waiting for ABDM link token"}})
            return
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for c in ccs:
            groups.setdefault(c["hi_type"], []).append(c)
        for hi, items in groups.items():
            rid = str(uuid.uuid4())
            body = {"abhaNumber": _abha_int(rec["abha_number"]), "abhaAddress": rec["abha_address"], "patient": [{
                "referenceNumber": rec["patient_user_id"], "display": rec.get("name") or "Patient",
                "careContexts": [{"referenceNumber": c["reference"], "display": c["display"]} for c in items],
                "hiType": hi, "count": len(items)}]}
            try:
                r = await abdm.hiecm_post("/hip/v3/link/carecontext", body, {"REQUEST-ID": rid, "X-LINK-TOKEN": token})
            except HTTPException as ex:
                await db.abdm_care_contexts.update_many({"reference": {"$in": [c["reference"] for c in items]}}, {
                    "$set": {"status": "failed", "status_note": str(ex.detail)}, "$inc": {"attempts": 1}})
                continue
            ok = r.status_code < 300
            if not ok and r.status_code in (400, 401) and "token" in r.text.lower():
                await db.abdm_link_tokens.delete_one({"abha_address": rec["abha_address"]})
            await db.abdm_care_contexts.update_many({"reference": {"$in": [c["reference"] for c in items]}}, {
                "$set": {"status": "link_requested" if ok else "failed", "link_request_id": rid, "linked_via": "hip_initiated",
                         "status_note": None if ok else f"ABDM {r.status_code}: {r.text[:200]}", "updated_at": _now()},
                "$inc": {"attempts": 1}})

    async def sync_all() -> Dict[str, int]:
        n = tot = 0
        async for rec in db.abha_records.find({"patient_user_id": {"$nin": [None, ""]}}, {"_id": 0, "photo": 0}):
            try:
                tot += (await sync_patient(rec))["new"]
                n += 1
            except Exception as ex:  # noqa: BLE001 — one bad patient must not stop the sweep
                log.warning("ABDM sync failed for %s: %s", rec.get("id"), ex)
        return {"patients": n, "new_records": tot}

    def on_linked(rec: Dict[str, Any]):
        _spawn(sync_patient(rec))

    async def on_discharge(admission_id: str):
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            pid = await conn.fetchval("SELECT patient_id::text FROM public.patient_admissions WHERE id=$1", admission_id)
        rec = pid and await db.abha_records.find_one({"patient_user_id": pid}, {"_id": 0, "photo": 0})
        if rec:
            await sync_patient(rec)

    # ---------- inbound callbacks ----------
    jwks: Dict[str, Any] = {"keys": None, "at": 0.0}

    async def gateway_keys(force: bool = False):
        import time as _t
        if jwks["keys"] and not force and jwks["at"] > _t.time() - 300:
            return jwks["keys"]
        saved = await db.abdm_meta.find_one({"_id": "gateway_jwks"})
        if saved and not force and saved.get("at", 0) > _t.time() - 6 * 3600:
            jwks.update(keys=saved["keys"], at=_t.time())
            return jwks["keys"]
        try:
            tok = await abdm.gateway_token()
        except HTTPException:
            if saved:
                return saved["keys"]
            raise HTTPException(status_code=503, detail="Cannot verify ABDM callback right now (gateway keys unavailable)")
        async with abdm._client() as c:
            for url in (f"{abdm.GW}/certs", f"{abdm.HIECM}/gateway/v3/certs"):
                try:
                    r = await c.get(url, headers={"Authorization": f"Bearer {tok}", "REQUEST-ID": str(uuid.uuid4()), "TIMESTAMP": abdm._ts(), "X-CM-ID": abdm.CM_ID})
                except httpx.HTTPError:
                    continue
                if r.status_code < 300 and (r.json() or {}).get("keys"):
                    jwks.update(keys=r.json()["keys"], at=_t.time())
                    await db.abdm_meta.update_one({"_id": "gateway_jwks"}, {"$set": {"keys": jwks["keys"], "at": jwks["at"]}}, upsert=True)
                    return jwks["keys"]
        if saved:
            return saved["keys"]
        raise HTTPException(status_code=503, detail="Cannot verify ABDM callback right now (gateway keys unavailable)")

    async def verify_gateway_jwt(token: str):
        import jwt as pyjwt
        try:
            kid = pyjwt.get_unverified_header(token).get("kid")
        except pyjwt.PyJWTError:
            raise HTTPException(status_code=401, detail="Invalid Authorization token")
        for force in (False, True):
            try:
                keys = await asyncio.wait_for(gateway_keys(force), timeout=2.5)
            except (HTTPException, asyncio.TimeoutError):
                _spawn(gateway_keys(True))
                if force or not jwks["keys"]:
                    raise HTTPException(status_code=401 if jwks["keys"] else 503, detail="ABDM token signed by unknown key")
                continue
            key = next((k for k in keys if not kid or k.get("kid") == kid), None)
            if key:
                try:
                    pyjwt.decode(token, pyjwt.PyJWK(key).key, algorithms=["RS256", "RS512", "PS256"], options={"verify_aud": False})
                    return
                except pyjwt.PyJWTError as ex:
                    raise HTTPException(status_code=401, detail=f"ABDM token rejected: {type(ex).__name__}")
        raise HTTPException(status_code=401, detail="ABDM token signed by unknown key")
    async def inbound(request: Request, kind: str) -> Dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            body = {}
        h = request.headers
        target = h.get("x-hip-id") or h.get("x-hiu-id")
        auth = h.get("authorization") or ""
        if not auth.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing Authorization")
        await verify_gateway_jwt(auth[7:])
        if target and target not in (HIP_ID, HIU_ID):
            raise HTTPException(status_code=400, detail="Callback is for another facility")
        safe = json.loads(json.dumps(body, default=str))
        if isinstance(safe.get("hiRequest"), dict):
            safe["hiRequest"].pop("keyMaterial", None)
        await db.abdm_callbacks.insert_one({"id": str(uuid.uuid4()), "kind": kind, "path": request.url.path,
                                            "request_id": h.get("request-id"), "target": target, "at": _now(),
                                            "expires_at": datetime.now(timezone.utc) + timedelta(days=14), "body": safe})
        return body

    def resp(code: int):
        return JSONResponse(status_code=code, content={"ack": True})

    @cb.post("/hip/token/on-generate-token")
    async def on_generate_token(request: Request):
        b = await inbound(request, "on-generate-token")
        rid = (b.get("response") or {}).get("requestId")
        t = await db.abdm_link_tokens.find_one({"request_id": rid}) if rid else None
        addr = b.get("abhaAddress") or (t or {}).get("abha_address")
        if addr:
            if b.get("linkToken"):
                await db.abdm_link_tokens.update_one({"abha_address": addr}, {"$set": {
                    "token": b["linkToken"], "status": "ready", "expires_at": (datetime.now(timezone.utc) + timedelta(days=180)).isoformat(),
                    "received_at": _now(), "error": None}}, upsert=True)
                rec = await db.abha_records.find_one({"abha_address": addr, "patient_user_id": {"$nin": [None, ""]}}, {"_id": 0, "photo": 0})
                if rec:
                    _spawn(link_pending(rec))
            else:
                await db.abdm_link_tokens.update_one({"abha_address": addr}, {"$set": {"status": "failed", "error": json.dumps(b.get("error"))[:300]}})
        return resp(200)

    @cb.post("/link/on_carecontext")
    async def on_carecontext(request: Request):
        b = await inbound(request, "on-carecontext")
        rid = (b.get("response") or {}).get("requestId")
        if rid:
            err = b.get("error")
            await db.abdm_care_contexts.update_many({"link_request_id": rid}, {"$set": {
                "status": "failed" if err else "linked", "status_note": json.dumps(err)[:200] if err else None,
                "linked_at": None if err else _now()}})
        return resp(200)

    async def respond(path: str, body: Dict[str, Any]) -> bool:
        try:
            r = await abdm.hiecm_post(path, body)
            status, err = r.status_code, (r.text[:300] if r.status_code >= 300 else None)
        except HTTPException as ex:
            status, err = 0, str(ex.detail)
        await db.abdm_callbacks.insert_one({"id": str(uuid.uuid4()), "kind": "outbound", "path": path, "status": status,
                                            "at": _now(), "expires_at": datetime.now(timezone.utc) + timedelta(days=14), "error": err})
        return 0 < status < 300

    async def push_data(url: str, body: Dict[str, Any]) -> int:
        if "abdm.gov.in" in url:
            return (await abdm.hiecm_post("", body, url=url)).status_code
        if not url.startswith("https://"):
            return 0
        async with httpx.AsyncClient(timeout=40) as c:
            try:
                r = await c.post(url, json=body, headers={"Content-Type": "application/json", "REQUEST-ID": str(uuid.uuid4()),
                                                          "TIMESTAMP": abdm._ts()})
                return r.status_code
            except httpx.HTTPError:
                return 0

    async def match_patient(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        ids = [i.get("value") for i in (p.get("verifiedIdentifiers") or []) if i.get("value")] + [p.get("id")]
        ors = [{"abha_address": v} for v in ids if v and "@" in v] + [{"abha_number": abdm.fmt_abha(v)} for v in ids
                                                                       if v and len("".join(c for c in v if c.isdigit())) == 14]
        if not ors:
            return None
        return await db.abha_records.find_one({"$or": ors, "patient_user_id": {"$nin": [None, ""]}}, {"_id": 0, "photo": 0})

    def grouped(rec: Dict[str, Any], ccs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        g: Dict[str, List[Dict[str, Any]]] = {}
        for c in ccs:
            g.setdefault(c["hi_type"], []).append({"referenceNumber": c["reference"], "display": c["display"]})
        return [{"referenceNumber": rec["patient_user_id"], "display": rec.get("name") or "Patient", "careContexts": v,
                 "hiType": k, "count": len(v)} for k, v in g.items()]

    async def do_discover(b: Dict[str, Any], rid: str):
        rec = await match_patient(b.get("patient") or {})
        out: Dict[str, Any] = {"transactionId": b.get("transactionId"), "response": {"requestId": rid}}
        if rec:
            await sync_patient(rec)
            ccs = await db.abdm_care_contexts.find({"patient_user_id": rec["patient_user_id"], "status": {"$ne": "linked"}}, {"_id": 0}).to_list(200)
            if ccs:
                out.update(patient=grouped(rec, ccs), matchedBy=["ABHA_ADDRESS" if rec.get("abha_address") else "ABHA_NUMBER"])
        if "patient" not in out:
            out["error"] = {"code": "ABDM-1010", "message": "No matching records found at Trata Health"}
        await respond("/user-initiated-linking/v3/patient/care-context/on-discover", out)

    @cb.post("/hip/patient/care-context/discover")
    async def discover(request: Request):
        b = await inbound(request, "discover")
        _spawn(do_discover(b, request.headers.get("request-id")))
        return resp(202)

    async def do_init(b: Dict[str, Any], rid: str):
        pats = b.get("patient") or []
        refs = [c.get("referenceNumber") for p in pats for c in (p.get("careContexts") or [])]
        addr = b.get("abhaAddress")
        ccs = await db.abdm_care_contexts.find({"reference": {"$in": refs}, "abha_address": addr}, {"_id": 0}).to_list(200) if addr else []
        out: Dict[str, Any] = {"transactionId": b.get("transactionId"), "response": {"requestId": rid}}
        if not ccs or len({c["patient_user_id"] for c in ccs}) != 1:
            out["error"] = {"code": "ABDM-1010", "message": "Care contexts not found"}
        else:
            rec = await db.abha_records.find_one({"patient_user_id": ccs[0]["patient_user_id"]}, {"_id": 0, "photo": 0}) or {}
            otp, ref = f"{secrets.randbelow(10 ** 6):06d}", str(uuid.uuid4())
            exp = datetime.now(timezone.utc) + timedelta(minutes=10)
            await db.abdm_link_requests.insert_one({
                "id": ref, "transaction_id": b.get("transactionId"), "abha_address": b.get("abhaAddress"), "references": [c["reference"] for c in ccs],
                "patient_user_id": ccs[0]["patient_user_id"], "patient_name": rec.get("name"), "patient_phone": rec.get("patient_phone"),
                "otp_hash": hashlib.sha256(otp.encode()).hexdigest(), "otp_display": otp, "attempts": 0, "status": "otp_sent",
                "expires_at": exp, "created_at": _now()})
            out["link"] = {"referenceNumber": ref, "authenticationType": "DIRECT", "meta": {
                "communicationMedium": "MOBILE", "communicationHint": abdm._mask(rec.get("patient_phone")) or "registered mobile",
                "communicationExpiry": exp.isoformat(timespec="milliseconds").replace("+00:00", "Z")}}
        await respond("/user-initiated-linking/v3/link/care-context/on-init", out)

    @cb.post("/hip/link/care-context/init")
    async def link_init(request: Request):
        b = await inbound(request, "link-init")
        _spawn(do_init(b, request.headers.get("request-id")))
        return resp(202)

    async def do_confirm(b: Dict[str, Any], rid: str):
        c = b.get("confirmation") or {}
        lr = await db.abdm_link_requests.find_one({"id": c.get("linkRefNumber")}, {"_id": 0})
        out: Dict[str, Any] = {"response": {"requestId": rid}}
        good = bool(lr) and lr["status"] == "otp_sent" and lr["attempts"] < 5 and \
            lr["expires_at"].replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) and \
            hmac.compare_digest(lr["otp_hash"], hashlib.sha256(str(c.get("token") or "").encode()).hexdigest())
        if not good:
            if lr:
                await db.abdm_link_requests.update_one({"id": lr["id"]}, {"$inc": {"attempts": 1}})
            out["error"] = {"code": "ABDM-1036", "message": "Invalid or expired OTP"}
        else:
            await db.abdm_link_requests.update_one({"id": lr["id"]}, {"$set": {"status": "linked", "linked_at": _now()}, "$unset": {"otp_display": ""}})
            await db.abdm_care_contexts.update_many({"reference": {"$in": lr["references"]}}, {"$set": {
                "status": "linked", "linked_via": "patient_initiated", "linked_at": _now()}})
            rec = await db.abha_records.find_one({"patient_user_id": lr["patient_user_id"]}, {"_id": 0, "photo": 0}) or {"patient_user_id": lr["patient_user_id"]}
            ccs = await db.abdm_care_contexts.find({"reference": {"$in": lr["references"]}}, {"_id": 0}).to_list(200)
            out["patient"] = grouped(rec, ccs)
        await respond("/user-initiated-linking/v3/link/care-context/on-confirm", out)

    @cb.post("/hip/link/care-context/confirm")
    async def link_confirm(request: Request):
        b = await inbound(request, "link-confirm")
        _spawn(do_confirm(b, request.headers.get("request-id")))
        return resp(200)

    @cb.post("/consent/request/hip/notify")
    async def consent_notify(request: Request):
        b = await inbound(request, "consent-notify")
        n = b.get("notification") or {}
        d = n.get("consentDetail") or {}
        cid = d.get("consentId") or n.get("consentId")
        if cid:
            await db.abdm_consents.update_one({"consent_id": cid}, {"$set": {
                "consent_id": cid, "status": n.get("status"), "patient": (d.get("patient") or {}).get("id"),
                "care_contexts": [x.get("careContextReference") for x in d.get("careContexts") or []],
                "hi_types": d.get("hiTypes"), "purpose": (d.get("purpose") or {}).get("text") or (d.get("purpose") or {}).get("code"),
                "permission": d.get("permission"), "hiu": (d.get("hiu") or {}).get("id"), "requester": (d.get("requester") or {}).get("name"),
                "updated_at": _now()}, "$setOnInsert": {"created_at": _now()}}, upsert=True)
        _spawn(respond("/consent/v3/request/hip/on-notify", {"acknowledgement": {"status": "ok", "consentId": cid},
                                                              "response": {"requestId": request.headers.get("request-id")}}))
        return resp(200)

    def consent_allows(consent: Dict[str, Any], c: Dict[str, Any], rng: Dict[str, Any]) -> bool:
        d = (c.get("record_date") or "")[:10]
        prng = (consent.get("permission") or {}).get("dateRange") or {}
        for r in (rng, prng):
            if r.get("from") and d < r["from"][:10]:
                return False
            if r.get("to") and d > r["to"][:10]:
                return False
        if consent.get("hi_types") and c["hi_type"] not in consent["hi_types"]:
            return False
        pat = consent.get("patient")
        return not pat or pat in (c.get("abha_address"), c.get("abha_number"))

    async def do_hi_request(b: Dict[str, Any], rid: str):
        hr = b.get("hiRequest") or {}
        tx = b.get("transactionId")
        cid = (hr.get("consent") or {}).get("id")
        consent = await db.abdm_consents.find_one({"consent_id": cid}, {"_id": 0}) if cid else None
        perm = (consent or {}).get("permission") or {}
        live = bool(consent) and (consent.get("status") or "").upper() == "GRANTED" and \
            (not perm.get("dataEraseAt") or perm["dataEraseAt"] > _now()[:19])
        await respond("/data-flow/v3/health-information/hip/on-request", {
            "hiRequest": {"transactionId": tx, "sessionStatus": "ACKNOWLEDGED" if live else "FAILED"},
            "response": {"requestId": rid}, **({} if live else {"error": {"code": "ABDM-1428", "message": "Consent not found or not granted"}})})
        if not live:
            return
        ccs = [c for c in await db.abdm_care_contexts.find({"reference": {"$in": consent.get("care_contexts") or []}}, {"_id": 0}).to_list(500)
               if consent_allows(consent, c, hr.get("dateRange") or {})]
        km = hr.get("keyMaterial") or {}
        mine = generate_key_material()
        entries, statuses = [], []
        for c in ccs:
            try:
                rec = await db.abha_records.find_one({"patient_user_id": c["patient_user_id"]}, {"_id": 0, "photo": 0}) or {}
                bundle = json.dumps(abdm_fhir.build_bundle(c, rec, {"name": c.get("provider_name"), "hip_id": HIP_ID}), separators=(",", ":"))
                enc = fidelius_encrypt(bundle, mine.nonce, km["nonce"], mine.private_key, km["dhPublicKey"]["keyValue"])
                entries.append({"content": enc.encrypted_data, "media": "application/fhir+json",
                                "checksum": hashlib.md5(bundle.encode()).hexdigest(), "careContextReference": c["reference"]})
                statuses.append({"careContextReference": c["reference"], "hiStatus": "DELIVERED", "description": "Delivered"})
            except Exception as ex:  # noqa: BLE001 — record per-context failure, keep going
                log.warning("FHIR/encrypt failed for %s: %s", c.get("reference"), ex)
                statuses.append({"careContextReference": c["reference"], "hiStatus": "ERRORED", "description": str(ex)[:100]})
        push = {"pageNumber": 1, "pageCount": 1, "transactionId": tx, "entries": entries, "keyMaterial": {
            "cryptoAlg": "ECDH", "curve": "Curve25519", "dhPublicKey": {
                "expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "parameters": "Curve25519/32byte random key", "keyValue": mine.x509_public_key}, "nonce": mine.nonce}}
        ok = False
        if entries and hr.get("dataPushUrl"):
            code = await push_data(hr["dataPushUrl"], push)
            ok = 0 < code < 300
            if not ok:
                statuses = [{**s, "hiStatus": "ERRORED", "description": f"Push failed {code}"} for s in statuses]
        await db.abdm_transfers.insert_one({"id": str(uuid.uuid4()), "transaction_id": tx, "consent_id": cid, "at": _now(),
                                            "references": [c["reference"] for c in ccs], "pushed": ok, "statuses": statuses,
                                            "hiu": consent.get("hiu")})
        await db.abdm_care_contexts.update_many({"reference": {"$in": [s["careContextReference"] for s in statuses if s["hiStatus"] == "DELIVERED"]}},
                                                {"$set": {"last_shared_at": _now()}, "$inc": {"share_count": 1 if ok else 0}})
        await respond("/data-flow/v3/health-information/notify", {"notification": {
            "consentId": cid, "transactionId": tx, "doneAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "notifier": {"type": "HIP", "id": HIP_ID},
            "statusNotification": {"sessionStatus": "TRANSFERRED" if ok else "FAILED", "hipId": HIP_ID, "statusResponses": statuses}}})

    @cb.post("/hip/health-information/request")
    async def hi_request(request: Request):
        b = await inbound(request, "hi-request")
        _spawn(do_hi_request(b, request.headers.get("request-id")))
        return resp(202)

    for path, code in (("/hiu/consent/request/on-init", 200), ("/hiu/consent/on-notify", 200), ("/hiu/consent/on-fetch", 200),
                       ("/hiu/health-information/on-request", 200), ("/hiu/health-information/transfer", 202)):
        async def _hiu(request: Request, _p=path, _c=code):
            await inbound(request, "hiu" + _p.replace("/", "-"))
            return resp(_c)
        cb.add_api_route(path, _hiu, methods=["POST"], name=f"hiu{path.replace('/', '_')}")

    abdm_share.register(cb, api, db, inbound, resp, respond, on_linked, _spawn, get_current_user, is_provider, is_internal)

    @cb.post("/{rest:path}")
    async def other_callback(rest: str, request: Request):
        await inbound(request, f"other:{rest}")
        return resp(202)

    # ---------- CRM UI ----------
    def scope(c) -> Dict[str, Any]:
        if c.get("role") == "sales_rep" and not c.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Not allowed")
        if is_provider(c):
            return {"provider_user_id": c.get("supabase_user_id") or c["id"]}
        if is_internal(c):
            return {}
        raise HTTPException(status_code=403, detail="Not allowed")

    @api.get("/care-contexts")
    async def care_contexts(patient_user_id: Optional[str] = None, current=Depends(get_current_user)):
        f = scope(current)
        if patient_user_id:
            f["patient_user_id"] = patient_user_id
        rows = await db.abdm_care_contexts.find(f, {"_id": 0, "record": 0}).sort("record_date", -1).to_list(500)
        counts: Dict[str, int] = {}
        for x in rows:
            counts[x["status"]] = counts.get(x["status"], 0) + 1
        return {"care_contexts": rows, "counts": counts, "hip_id": HIP_ID}

    @api.post("/care-contexts/sync")
    async def sync(body: SyncBody, current=Depends(get_current_user)):
        scope(current)
        if body.patient_user_id:
            rec = await db.abha_records.find_one({"patient_user_id": body.patient_user_id}, {"_id": 0, "photo": 0})
            if not rec:
                raise HTTPException(status_code=404, detail="This patient has no ABHA linked yet")
            return await sync_patient(rec)
        if not is_internal(current):
            raise HTTPException(status_code=403, detail="Only Trata staff can sync everyone")
        return await sync_all()

    @api.get("/consents")
    async def consents(current=Depends(get_current_user)):
        scope(current)
        rows = await db.abdm_consents.find({}, {"_id": 0}).sort("updated_at", -1).to_list(200)
        if is_provider(current):
            mine = {c["reference"] async for c in db.abdm_care_contexts.find(scope(current), {"reference": 1})}
            rows = [r for r in rows if set(r.get("care_contexts") or []) & mine]
        return {"consents": rows}

    @api.get("/link-requests")
    async def link_requests(current=Depends(get_current_user)):
        f = scope(current)
        q: Dict[str, Any] = {"status": "otp_sent", "expires_at": {"$gt": datetime.now(timezone.utc)}}
        rows = await db.abdm_link_requests.find(q, {"_id": 0, "otp_hash": 0}).sort("created_at", -1).to_list(50)
        if f:
            mine = {c["reference"] async for c in db.abdm_care_contexts.find(f, {"reference": 1})}
            rows = [r for r in rows if r["references"] and set(r["references"]) <= mine]
        return {"link_requests": [{**r, "expires_at": r["expires_at"].isoformat()} for r in rows]}

    @api.get("/callbacks")
    async def callbacks(current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        rows = await db.abdm_callbacks.find({}, {"_id": 0, "body": 0}).sort("at", -1).to_list(100)
        return {"callbacks": [{**r, "expires_at": _iso(r.get("expires_at"))} for r in rows], "hip_id": HIP_ID, "callback_base": CALLBACK_BASE}

    @api.post("/cron/sync")
    async def cron_sync(request: Request):
        # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
        auth, secret = request.headers.get("authorization") or "", os.environ.get("WEBHOOK_CRON_SECRET") or ""
        if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        _spawn(sync_all())
        return {"accepted": True}

    async def ensure_indexes():
        await db.abdm_care_contexts.create_index("reference", unique=True)
        await db.abdm_care_contexts.create_index("patient_user_id")
        await db.abdm_callbacks.create_index("expires_at", expireAfterSeconds=0)
        await db.abdm_link_requests.create_index("expires_at", expireAfterSeconds=24 * 3600)
        await db.abdm_consents.create_index("consent_id", unique=True)
        _spawn(gateway_keys(False))

    return {"api": api, "callbacks": cb, "on_linked": on_linked, "on_discharge": on_discharge, "sync_all": sync_all,
            "ensure_indexes": ensure_indexes}
