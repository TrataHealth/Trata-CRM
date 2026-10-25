"""ABDM Scan & Share (facility side): patient scans a hospital's QR, ABDM pushes the profile, we save it and return a token."""
from __future__ import annotations

import json
import logging
import os
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pymongo import ReturnDocument

import abdm
import supabase_db as sb

log = logging.getLogger("abdm.share")
HIP_ID = os.environ["ABDM_HIP_ID"]
QR_BASE = os.environ["ABDM_SHARE_QR_BASE"]
IST = timezone(timedelta(hours=5, minutes=30))
SEX = {"M": "male", "F": "female", "O": "other", "T": "other"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_ist():
    n = datetime.now(IST)
    end = (n + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return n.date().isoformat(), max(60, int((end - n).total_seconds()))


def _digits(s: Optional[str]) -> str:
    return "".join(ch for ch in str(s or "") if ch.isdigit())


def _addr_text(a: Any) -> Optional[str]:
    if not isinstance(a, dict):
        return a or None
    return ", ".join(str(a[k]) for k in ("line", "district", "state", "pincode") if a.get(k)) or None


async def _upsert_hospital_patient(hospital_uid: str, p: Dict[str, Any], abha_no: Optional[str], patient_id: Optional[str]) -> Optional[str]:
    """Add or match the patient in the hospital's roster (public.hospital_patients, same table the Provider app reads)."""
    phone10 = _digits(p.get("phoneNumber"))[-10:]
    phone = f"+91{phone10}" if phone10 else None
    yob = int(p["yearOfBirth"]) if _digits(p.get("yearOfBirth")) else None
    age = datetime.now(IST).year - yob if yob else None
    sex = SEX.get(str(p.get("gender") or "").upper()[:1])
    addr, name = _addr_text(p.get("address")), p.get("name")
    kyc = json.dumps({k: p.get(k) for k in ("name", "gender", "address", "abhaNumber", "abhaAddress", "phoneNumber",
                                            "yearOfBirth", "monthOfBirth", "dayOfBirth")} | {"source": "scan_share"})
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        row_id = await conn.fetchval("""
            SELECT id FROM public.hospital_patients
             WHERE hospital_id = $1 AND (($2::text IS NOT NULL AND abha_number = $2) OR abha_address = $3
                   OR ($4::text IS NOT NULL AND phone = $4 AND lower(coalesce(name, '')) = lower(coalesce($5, ''))))
             ORDER BY created_at DESC LIMIT 1""", hospital_uid, abha_no, p.get("abhaAddress"), phone, name)
        if row_id:
            await conn.execute("""
                UPDATE public.hospital_patients SET abha_number = coalesce($2, abha_number), abha_address = $3,
                       abha_verified_at = now(), abha_kyc = $4::jsonb, updated_at = now(),
                       name = coalesce(name, $5), age = coalesce(age, $6), sex = coalesce(sex, $7), phone = coalesce(phone, $8),
                       address = coalesce(address, $9), patient_id = coalesce(patient_id, $10)
                 WHERE id = $1""", row_id, abha_no, p.get("abhaAddress"), kyc, name, age, sex, phone, addr, patient_id)
            return row_id
        row_id = str(uuid.uuid4())
        await conn.execute("""
            INSERT INTO public.hospital_patients (id, hospital_id, patient_id, admission_date, status, name, age, sex, phone, address,
                   abha_number, abha_address, abha_verified_at, abha_kyc, created_at, updated_at)
            VALUES ($1, $2, $3, now(), 'registered', $4, $5, $6, $7, $8, $9, $10, now(), $11::jsonb, now(), now())""",
                           row_id, hospital_uid, patient_id, name, age, sex, phone, addr, abha_no, p.get("abhaAddress"), kyc)
        return row_id


def register(cb: APIRouter, api: APIRouter, db, inbound, resp, respond, on_linked, spawn,
             get_current_user, is_provider, is_internal):
    async def counter_for(hospital_uid: str, name: Optional[str]) -> Dict[str, Any]:
        c = await db.abdm_share_counters.find_one({"hospital_user_id": hospital_uid}, {"_id": 0})
        if c:
            return c
        await db.abdm_share_counters.create_index("code", unique=True)
        for _ in range(5):
            code = "TH" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
            doc = {"code": code, "hospital_user_id": hospital_uid, "hospital_name": name, "created_at": _now()}
            try:
                await db.abdm_share_counters.insert_one(dict(doc))
                return doc
            except Exception:  # noqa: BLE001 — code collision, retry
                continue
        raise HTTPException(status_code=500, detail="Could not create a QR code, please retry")

    async def save(counter: Dict[str, Any], p: Dict[str, Any]) -> Dict[str, Any]:
        uid = counter["hospital_user_id"]
        num = _digits(p.get("abhaNumber"))
        abha_no = abdm.fmt_abha(num) if len(num) == 14 else None
        phone10 = _digits(p.get("phoneNumber"))[-10:]
        patient_id = await abdm.resolve_patient(phone10) if phone10 else None
        out: Dict[str, Any] = {"patient_user_id": patient_id}
        if abha_no:
            dob = "-".join(x for x in (p.get("dayOfBirth"), p.get("monthOfBirth"), p.get("yearOfBirth")) if x)
            doc = {k: v for k, v in {"abha_address": p.get("abhaAddress"), "name": p.get("name"), "gender": p.get("gender"),
                                     "dob": dob or None, "year_of_birth": int(p["yearOfBirth"]) if _digits(p.get("yearOfBirth")) else None,
                                     "mobile_masked": abdm._mask(p.get("phoneNumber")), "state": (p.get("address") or {}).get("state"),
                                     "district": (p.get("address") or {}).get("district"), "patient_phone": phone10 or None,
                                     "patient_user_id": patient_id, "last_shared_via": "scan_share", "last_shared_at": _now(),
                                     "updated_at": _now()}.items() if v is not None}
            await db.abha_records.update_one({"owner": uid, "abha_number": abha_no}, {"$set": doc, "$setOnInsert": {
                "id": str(uuid.uuid4()), "owner": uid, "created_at": _now(), "created_via": "scan_share", "kyc_verified": False,
                "last_verified_via": "scan_share (ABDM app)", "created_by": {"id": "abdm", "name": "ABDM Scan & Share", "owner": uid}}}, upsert=True)
            rec = await db.abha_records.find_one({"owner": uid, "abha_number": abha_no}, {"_id": 0, "photo": 0})
            out["record_id"] = rec["id"]
            if rec.get("patient_user_id"):
                on_linked(rec)
        out["hospital_patient_id"] = await _upsert_hospital_patient(uid, p, abha_no, patient_id)
        return out

    async def process(b: Dict[str, Any], rid: Optional[str]):
        meta, p = b.get("metaData") or {}, ((b.get("profile") or {}).get("patient") or {})
        ctx, addr = meta.get("context"), p.get("abhaAddress")
        counter = await db.abdm_share_counters.find_one({"code": ctx}, {"_id": 0}) if ctx else None
        if not counter or (meta.get("hipId") and meta["hipId"] != HIP_ID) or not addr:
            await respond("/patient-share/v3/on-share", {"error": {"code": "ABDM-1017", "message": "Unknown counter or missing ABHA address"},
                                                         "response": {"requestId": rid}})
            return
        day, expiry = _today_ist()
        prev = await db.abdm_profile_shares.find_one({"counter": ctx, "abha_address": addr, "date": day}, {"_id": 0})
        if prev:
            token = prev["token"]
        else:
            seq = await db.abdm_share_seq.find_one_and_update({"_id": f"{ctx}:{day}"}, {"$inc": {"n": 1}}, upsert=True,
                                                              return_document=ReturnDocument.AFTER)
            token = str(seq["n"])
        try:
            saved, err = await save(counter, p), None
        except Exception as ex:  # noqa: BLE001 — token must still go back to the patient within 30s
            log.exception("scan-share save failed")
            saved, err = {}, f"{type(ex).__name__}: {str(ex)[:150]}"
        ok = await respond("/patient-share/v3/on-share", {
            "acknowledgement": {"status": "SUCCESS", "abhaAddress": addr, "profile": {"context": ctx, "tokenNumber": token, "expiry": str(expiry)}},
            "response": {"requestId": rid}})
        phone10 = _digits(p.get("phoneNumber"))[-10:]
        doc = {"counter": ctx, "hospital_user_id": counter["hospital_user_id"], "hospital_name": counter.get("hospital_name"),
               "date": day, "abha_address": addr, "abha_number": abdm.fmt_abha(_digits(p["abhaNumber"])) if len(_digits(p.get("abhaNumber"))) == 14 else None,
               "name": p.get("name"), "gender": p.get("gender"), "year_of_birth": p.get("yearOfBirth"),
               "phone_masked": abdm._mask(phone10) if phone10 else None, "address": _addr_text(p.get("address")),
               "token": token, "request_id": rid, "on_share_ok": ok, "save_error": err, "last_shared_at": _now(), **saved}
        await db.abdm_profile_shares.update_one({"counter": ctx, "abha_address": addr, "date": day},
                                                {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _now()},
                                                 "$inc": {"share_count": 1}}, upsert=True)

    @cb.post("/hip/patient/share")
    async def patient_share(request: Request):
        b = await inbound(request, "patient-share")
        spawn(process(b, request.headers.get("request-id")))
        return resp(200)

    def hospital_uid(c) -> str:
        if not is_provider(c) or c.get("provider_type") != "hospital":
            raise HTTPException(status_code=403, detail="Scan & Share QR is for hospitals")
        return c.get("supabase_user_id") or c["id"]

    @api.get("/share/qr")
    async def share_qr(current=Depends(get_current_user)):
        uid = hospital_uid(current)
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            name = await conn.fetchval("SELECT name FROM public.hospital_profiles WHERE user_id::text = $1 LIMIT 1", uid)
        c = await counter_for(uid, name or current.get("organization_name") or current.get("name"))
        if name and c.get("hospital_name") != name:
            await db.abdm_share_counters.update_one({"code": c["code"]}, {"$set": {"hospital_name": name}})
            c["hospital_name"] = name
        return {"code": c["code"], "hip_id": HIP_ID, "hospital_name": c.get("hospital_name"),
                "qr_url": f"{QR_BASE}?hip-id={HIP_ID}&counter-id={c['code']}"}

    @api.get("/share/profiles")
    async def shares(date: Optional[str] = None, current=Depends(get_current_user)):
        f: Dict[str, Any] = {"date": date or _today_ist()[0]}
        if is_provider(current):
            f["hospital_user_id"] = hospital_uid(current)
        elif not is_internal(current) or (current.get("role") == "sales_rep" and not current.get("is_master_admin")):
            raise HTTPException(status_code=403, detail="Not allowed")
        rows = await db.abdm_profile_shares.find(f, {"_id": 0}).sort("last_shared_at", -1).to_list(500)
        return {"date": f["date"], "profiles": rows}

    return {"process": process, "counter_for": counter_for}
