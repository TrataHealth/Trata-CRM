"""ABDM Milestone 1 — ABHA creation (Aadhaar OTP) and verification, via an India-based egress proxy."""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

log = logging.getLogger("abdm")
GW = os.environ["ABDM_GATEWAY_URL"]
ABHA = os.environ["ABDM_ABHA_URL"]
CM_ID = os.environ["ABDM_CM_ID"]
HIECM = os.environ["ABDM_HIECM_URL"]
HIP_ID = os.environ["ABDM_HIP_ID"]
X_TOKEN_TTL = 25 * 60
CONSENT_TEXT = (
    "I, the patient, voluntarily share my Aadhaar number and demographic information with the National Health "
    "Authority (NHA) to create my Ayushman Bharat Health Account (ABHA). I authorise NHA to use my Aadhaar for "
    "authentication with UIDAI. I understand that my ABHA can be used to share and access my health records with "
    "my consent, and that I may deactivate it at any time.")

_cache: Dict[str, Any] = {"tok": None, "tok_exp": 0.0, "key": None, "key_exp": 0.0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(proxy=os.environ["ABDM_PROXY_URL"], timeout=40)


def _err(r: httpx.Response) -> HTTPException:
    try:
        j = r.json()
    except ValueError:
        j = {}
    e = j.get("error") if isinstance(j.get("error"), dict) else j
    msg = (e.get("message") or e.get("description") or j.get("message") or r.text[:200]) if isinstance(e, dict) else str(e)
    if isinstance(e, dict) and not (e.get("message") or e.get("description")):
        msg = "; ".join(f"{v}" for k, v in e.items() if k not in ("timestamp", "code") and isinstance(v, str)) or msg
    if isinstance(msg, str) and msg.startswith("{"):
        try:
            import json as _json
            msg = "; ".join(str(v) for k, v in _json.loads(msg).items() if k != "timestamp")
        except ValueError:
            pass
    log.warning("ABDM %s %s -> %s %s", r.request.method, r.request.url.path, r.status_code, str(msg)[:200])
    code = 502 if r.status_code >= 500 or r.status_code in (401, 403) else 400
    return HTTPException(status_code=code, detail=f"ABDM: {msg}")


async def gateway_token() -> str:
    if _cache["tok"] and _cache["tok_exp"] > time.time():
        return _cache["tok"]
    async with _client() as c:
        try:
            r = await c.post(f"{GW}/sessions", headers={"X-CM-ID": CM_ID, "REQUEST-ID": str(uuid.uuid4()), "TIMESTAMP": _ts()},
                             json={"clientId": os.environ["ABDM_CLIENT_ID"], "clientSecret": os.environ["ABDM_CLIENT_SECRET"],
                                   "grantType": "client_credentials"})
        except httpx.HTTPError as ex:
            raise HTTPException(status_code=502, detail=f"ABDM unreachable via India proxy: {type(ex).__name__}")
    if r.status_code >= 300:
        raise _err(r)
    j = r.json()
    _cache.update(tok=j["accessToken"], tok_exp=time.time() + int(j.get("expiresIn") or 600) - 60)
    return _cache["tok"]


async def call(method: str, path: str, *, json: Any = None, headers: Optional[Dict[str, str]] = None,
               raw: bool = False) -> Any:
    h = {"Authorization": f"Bearer {await gateway_token()}", "REQUEST-ID": str(uuid.uuid4()), "TIMESTAMP": _ts()}
    h.update(headers or {})
    async with _client() as c:
        try:
            r = await c.request(method, f"{ABHA}{path}", headers=h, json=json)
        except httpx.HTTPError as ex:
            raise HTTPException(status_code=502, detail=f"ABDM unreachable via India proxy: {type(ex).__name__}")
    if r.status_code == 401:
        _cache["tok"] = None
    if r.status_code >= 300:
        raise _err(r)
    return r if raw else (r.json() if r.content else {})


async def hiecm_post(path: str, body: Dict[str, Any], headers: Optional[Dict[str, str]] = None, url: Optional[str] = None,
                     retries: int = 2) -> httpx.Response:
    """Gateway (HIE-CM) call stamped with our HIP/HIU id so async callbacks route back via the Trata gateway."""
    last: Optional[httpx.Response] = None
    for attempt in range(retries + 1):
        h = {"Authorization": f"Bearer {await gateway_token()}", "REQUEST-ID": str(uuid.uuid4()), "TIMESTAMP": _ts(),
             "X-CM-ID": CM_ID, "X-HIP-ID": HIP_ID, "X-HIU-ID": os.environ["ABDM_HIU_ID"], **(headers or {})}
        async with _client() as c:
            try:
                last = await c.post(url or f"{HIECM}{path}", headers=h, json=body)
            except httpx.HTTPError as ex:
                log.warning("ABDM %s unreachable: %s", path, type(ex).__name__)
                last = None
        if last is not None and last.status_code == 401:
            _cache["tok"] = None
        if last is not None and last.status_code < 500 and last.status_code != 401:
            break
        await asyncio.sleep(1.5 * (attempt + 1))
    if last is None:
        raise HTTPException(status_code=502, detail="ABDM unreachable via India proxy")
    if last.status_code >= 300:
        log.warning("ABDM POST %s -> %s %s", path or url, last.status_code, last.text[:300])
    return last


async def encrypt(value: str) -> str:
    if not _cache["key"] or _cache["key_exp"] < time.time():
        cert = await call("GET", "/profile/public/certificate")
        _cache.update(key=serialization.load_der_public_key(base64.b64decode(cert["publicKey"])), key_exp=time.time() + 6 * 3600)
    ct = _cache["key"].encrypt(value.encode(), padding.OAEP(mgf=padding.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
    return base64.b64encode(ct).decode()


def fmt_abha(n: str) -> str:
    d = re.sub(r"\D", "", n or "")
    if len(d) != 14:
        raise HTTPException(status_code=400, detail="ABHA number must have 14 digits")
    return f"{d[:2]}-{d[2:6]}-{d[6:10]}-{d[10:]}"


def _mask(m: Optional[str]) -> Optional[str]:
    d = re.sub(r"\D", "", m or "")
    return f"XXXXXX{d[-4:]}" if len(d) >= 4 else m


# ---------- Models ----------
class EnrolOtp(BaseModel):
    aadhaar: str = Field(..., pattern=r"^\d{12}$")
    consent: bool
    patient_phone: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")


class EnrolVerify(BaseModel):
    txn_id: str
    otp: str = Field(..., pattern=r"^\d{6}$")
    mobile: str = Field(..., pattern=r"^[6-9]\d{9}$")


class TxnOtp(BaseModel):
    txn_id: str
    otp: str = Field(..., pattern=r"^\d{6}$")


class MobileOtp(BaseModel):
    txn_id: str
    mobile: str = Field(..., pattern=r"^[6-9]\d{9}$")


class AddressBody(BaseModel):
    txn_id: str
    address: str = Field(..., pattern=r"^[a-zA-Z0-9._]{8,18}$")


class VerifyOtp(BaseModel):
    method: Literal["abha-number", "abha-address", "mobile", "aadhaar"]
    identifier: str = Field(..., min_length=3, max_length=60)
    otp_via: Literal["abdm", "aadhaar"] = "abdm"
    patient_phone: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")


class SelectBody(BaseModel):
    txn_id: str
    abha_number: str


class QrBody(BaseModel):
    qr: str = Field(..., min_length=10, max_length=4000)
    patient_user_id: Optional[str] = None
    patient_phone: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")


class AttachBody(BaseModel):
    record_id: str
    patient_user_id: str


def parse_abha_qr(raw: str) -> Dict[str, Any]:
    import json as _json
    try:
        q = _json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="This QR is not an ABHA card QR")
    if not isinstance(q, dict):
        raise HTTPException(status_code=400, detail="This QR is not an ABHA card QR")
    num = q.get("hidn") or q.get("abhaNumber") or q.get("ABHANumber") or q.get("healthIdNumber")
    if not num:
        raise HTTPException(status_code=400, detail="No ABHA number in this QR")
    dob = q.get("dob") or q.get("dateOfBirth") or ""
    m = re.match(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})", dob)
    return {"ABHANumber": fmt_abha(num), "abhaAddress": q.get("phr") or q.get("hid") or q.get("abhaAddress"),
            "name": q.get("name"), "gender": q.get("gender") or q.get("gen"),
            "dateOfBirth": f"{int(m[1]):02d}-{int(m[2]):02d}-{m[3]}" if m else dob or None,
            "mobile": q.get("mobile") or q.get("mob"), "stateName": q.get("state name") or q.get("stateName"),
            "districtName": q.get("district_name") or q.get("districtName"), "address": q.get("address")}


class LinkBody(BaseModel):
    patient_phone: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")
    patient_user_id: Optional[str] = None
    note: Optional[str] = Field(None, max_length=200)


async def resolve_patient(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    import supabase_db as sb
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT id::text FROM public.users WHERE phone = ANY($1::text[]) AND coalesce(role,'patient') IN ('patient','user','customer') "
                                   "ORDER BY created_at LIMIT 1", [phone, f"+91{phone}", f"91{phone}"])


def create_abdm_router(db, get_current_user, is_provider, is_internal, on_linked=None) -> APIRouter:
    r = APIRouter(prefix="/api/abdm")
    idx = {"done": False}

    async def ensure_indexes():
        if not idx["done"]:
            await db.abdm_txns.create_index("expires_at", expireAfterSeconds=0)
            await db.abha_records.create_index([("owner", 1), ("abha_number", 1)], unique=True)
            idx["done"] = True

    def owner_of(c) -> str:
        if c.get("role") == "sales_rep" and not c.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="ABHA tools are for providers and Trata admin staff")
        if is_provider(c):
            return c.get("supabase_user_id") or c["id"]
        if is_internal(c):
            return "trata"
        raise HTTPException(status_code=403, detail="ABHA tools are for providers and Trata staff")

    def actor(c) -> Dict[str, Any]:
        return {"id": c.get("id"), "name": c.get("name") or c.get("phone"), "owner": owner_of(c),
                "provider_type": c.get("provider_type")}

    async def audit(c, action: str, ok: bool = True, **extra):
        await db.abdm_audit.insert_one({"id": str(uuid.uuid4()), "action": action, "ok": ok, "by": actor(c), "at": _now(), **extra})

    async def get_txn(txn_id: str, c, kind: Optional[str] = None) -> Dict[str, Any]:
        t = await db.abdm_txns.find_one({"id": txn_id}, {"_id": 0})
        if not t or t["owner"] != owner_of(c) or (kind and t["kind"] != kind):
            raise HTTPException(status_code=404, detail="Session not found — start again")
        return t

    async def set_txn(txn_id: str, **fields):
        await db.abdm_txns.update_one({"id": txn_id}, {"$set": {**fields, "updated_at": _now()}})

    async def save_record(c, p: Dict[str, Any], via: str, txn: Dict[str, Any]) -> Dict[str, Any]:
        num = p.get("ABHANumber") or p.get("abhaNumber") or p.get("healthIdNumber")
        if not num:
            raise HTTPException(status_code=502, detail="ABDM did not return an ABHA number")
        addr = p.get("preferredAbhaAddress") or p.get("abhaAddress") or next(iter(p.get("phrAddress") or []), None)
        name = p.get("name") or p.get("fullName") or " ".join(filter(None, [p.get("firstName"), p.get("middleName"), p.get("lastName")]))
        dob = p.get("dateOfBirth") or p.get("dob") or "-".join(filter(None, [p.get("dayOfBirth"), p.get("monthOfBirth"), p.get("yearOfBirth")]))
        owner = owner_of(c)
        doc: Dict[str, Any] = {"abha_number": num, "abha_address": addr, "name": name.strip() or None, "gender": p.get("gender"),
               "dob": dob or None, "mobile_masked": _mask(p.get("mobile")), "state": p.get("stateName"),
               "district": p.get("districtName"), "kyc_verified": p.get("kycVerified") if p.get("kycVerified") is not None else p.get("kycStatus") == "VERIFIED",
               "abha_status": p.get("abhaStatus") or p.get("status"), "photo": p.get("photo") or p.get("profilePhoto"),
               "last_verified_via": via, "last_verified_at": _now(), "last_txn_id": txn["id"], "updated_at": _now()}
        if txn.get("patient_phone"):
            doc["patient_phone"] = txn["patient_phone"]
        ins: Dict[str, Any] = {}
        if via == "qr_scan":
            for k in ("kyc_verified", "last_verified_via", "last_verified_at", "last_txn_id"):
                doc.pop(k, None)
            doc = {k: v for k, v in doc.items() if v is not None}
            doc["qr_scanned_at"] = _now()
            ins = {"kyc_verified": False, "last_verified_via": "qr_scan (not OTP-verified)"}
        pid = txn.get("patient_user_id") or await resolve_patient(txn.get("patient_phone"))
        existing = await db.abha_records.find_one({"owner": owner_of(c), "abha_number": num}, {"patient_user_id": 1})
        if pid and not (via == "qr_scan" and existing and existing.get("patient_user_id")):
            doc["patient_user_id"] = pid
        if p.get("yearOfBirth") or re.search(r"(\d{4})", doc.get("dob") or ""):
            doc["year_of_birth"] = int(p.get("yearOfBirth") or re.search(r"(\d{4})", doc["dob"])[1])
        await db.abha_records.update_one({"owner": owner, "abha_number": num},
                                         {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "owner": owner, "created_by": actor(c),
                                                                       "created_at": _now(), "created_via": via, **ins}}, upsert=True)
        rec = await db.abha_records.find_one({"owner": owner, "abha_number": num}, {"_id": 0})
        await set_txn(txn["id"], record_id=rec["id"])
        if rec.get("patient_user_id") and on_linked:
            on_linked(rec)
        return rec

    async def profile_for(t: Dict[str, Any]) -> Dict[str, Any]:
        path = "/phr/web/login/profile/abha-profile" if t.get("phr") else "/profile/account"
        return await call("GET", path, headers={"X-token": f"Bearer {t['x_token']}"})

    def public(rec: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in rec.items() if k not in ("owner", "last_txn_id")}

    # ---------- Status ----------
    @r.get("/status")
    async def status(current=Depends(get_current_user)):
        owner_of(current)
        t0 = time.time()
        try:
            await gateway_token()
            await encrypt("ping")
            return {"connected": True, "environment": "sandbox" if CM_ID == "sbx" else "production", "latency_ms": int((time.time() - t0) * 1000),
                    "client_id": os.environ["ABDM_CLIENT_ID"], "consent_text": CONSENT_TEXT}
        except HTTPException as ex:
            return {"connected": False, "error": ex.detail, "environment": "sandbox" if CM_ID == "sbx" else "production",
                    "consent_text": CONSENT_TEXT}

    # ---------- Create ABHA (Aadhaar OTP) ----------
    @r.post("/enrol/otp")
    async def enrol_otp(body: EnrolOtp, current=Depends(get_current_user)):
        owner = owner_of(current)
        if not body.consent:
            raise HTTPException(status_code=400, detail="Patient consent is required to create an ABHA")
        out = await call("POST", "/enrollment/request/otp", json={
            "txnId": "", "scope": ["abha-enrol"], "loginHint": "aadhaar", "loginId": await encrypt(body.aadhaar), "otpSystem": "aadhaar"})
        tid = out["txnId"]
        await ensure_indexes()
        await db.abdm_txns.insert_one({"id": tid, "abdm_txn": tid, "kind": "enrol", "expires_at": datetime.now(timezone.utc) + timedelta(hours=2), "owner": owner, "step": "aadhaar_otp_sent",
                                       "patient_phone": body.patient_phone, "consent_at": _now(), "created_at": _now()})
        await audit(current, "enrol_otp", txn=tid)
        return {"txn_id": tid, "message": out.get("message")}

    @r.post("/enrol/verify")
    async def enrol_verify(body: EnrolVerify, current=Depends(get_current_user)):
        t = await get_txn(body.txn_id, current, "enrol")
        out = await call("POST", "/enrollment/enrol/byAadhaar", json={
            "authData": {"authMethods": ["otp"], "otp": {"txnId": t["abdm_txn"], "otpValue": await encrypt(body.otp), "mobile": body.mobile}},
            "consent": {"code": "abha-enrollment", "version": "1.4"}})
        p = out.get("ABHAProfile") or {}
        tok = (out.get("tokens") or {}).get("token")
        same_mobile = re.sub(r"\D", "", p.get("mobile") or "")[-10:] == body.mobile
        await set_txn(t["id"], abdm_txn=out.get("txnId") or t["abdm_txn"], x_token=tok, x_exp=time.time() + X_TOKEN_TTL,
                      step="mobile_pending" if not same_mobile else "address_pending")
        rec = await save_record(current, p, "aadhaar_otp_enrol", t)
        await audit(current, "enrol_verify", txn=t["id"], is_new=out.get("isNew"))
        return {"txn_id": t["id"], "is_new": out.get("isNew"), "message": out.get("message"),
                "needs_mobile_verify": not same_mobile, "has_address": bool(p.get("phrAddress")), "record": public(rec)}

    @r.post("/enrol/mobile-otp")
    async def enrol_mobile_otp(body: MobileOtp, current=Depends(get_current_user)):
        t = await get_txn(body.txn_id, current, "enrol")
        out = await call("POST", "/enrollment/request/otp", json={
            "txnId": t["abdm_txn"], "scope": ["abha-enrol", "mobile-verify"], "loginHint": "mobile",
            "loginId": await encrypt(body.mobile), "otpSystem": "abdm"})
        await set_txn(t["id"], abdm_txn=out.get("txnId") or t["abdm_txn"])
        return {"txn_id": t["id"], "message": out.get("message")}

    @r.post("/enrol/mobile-verify")
    async def enrol_mobile_verify(body: TxnOtp, current=Depends(get_current_user)):
        t = await get_txn(body.txn_id, current, "enrol")
        out = await call("POST", "/enrollment/auth/byAbdm", json={
            "scope": ["abha-enrol", "mobile-verify"],
            "authData": {"authMethods": ["otp"], "otp": {"txnId": t["abdm_txn"], "otpValue": await encrypt(body.otp)}}})
        if (out.get("authResult") or "").lower() != "success":
            raise HTTPException(status_code=400, detail=f"ABDM: {out.get('message') or 'Mobile OTP verification failed'}")
        await set_txn(t["id"], abdm_txn=out.get("txnId") or t["abdm_txn"], step="address_pending")
        if t.get("record_id"):
            await db.abha_records.update_one({"id": t["record_id"]}, {"$set": {"mobile_verified_at": _now()}})
        return {"txn_id": t["id"], "message": out.get("message")}

    @r.get("/enrol/{txn_id}/suggestions")
    async def enrol_suggestions(txn_id: str, current=Depends(get_current_user)):
        t = await get_txn(txn_id, current, "enrol")
        out = await call("GET", "/enrollment/enrol/suggestion", headers={"Transaction_Id": t["abdm_txn"]})
        return {"suggestions": out.get("abhaAddressList") or []}

    @r.post("/enrol/address")
    async def enrol_address(body: AddressBody, current=Depends(get_current_user)):
        t = await get_txn(body.txn_id, current, "enrol")
        if not t.get("record_id"):
            raise HTTPException(status_code=400, detail="Verify the Aadhaar OTP first")
        out = await call("POST", "/enrollment/enrol/abha-address",
                         json={"txnId": t["abdm_txn"], "abhaAddress": body.address, "preferred": 1})
        addr = out.get("preferredAbhaAddress") or f"{body.address}@sbx"
        await set_txn(t["id"], step="done")
        await db.abha_records.update_one({"id": t["record_id"]}, {"$set": {"abha_address": addr, "updated_at": _now()}})
        await audit(current, "enrol_address", txn=t["id"])
        return {"abha_address": addr, "record": public(await db.abha_records.find_one({"id": t["record_id"]}, {"_id": 0}))}

    # ---------- Verify existing ABHA ----------
    @r.post("/verify/otp")
    async def verify_otp(body: VerifyOtp, current=Depends(get_current_user)):
        owner = owner_of(current)
        ident = body.identifier.strip()
        via = "aadhaar" if body.method == "aadhaar" else body.otp_via
        if body.method == "abha-number":
            ident = fmt_abha(ident)
        elif body.method == "mobile":
            if not re.fullmatch(r"[6-9]\d{9}", ident):
                raise HTTPException(status_code=400, detail="Enter a valid 10-digit mobile number")
            via = "abdm"
        elif body.method == "aadhaar" and not re.fullmatch(r"\d{12}", ident):
            raise HTTPException(status_code=400, detail="Aadhaar must have 12 digits")
        elif body.method == "abha-address":
            ident = ident if "@" in ident else f"{ident}@{'sbx' if CM_ID == 'sbx' else 'abdm'}"
        verify = "aadhaar-verify" if via == "aadhaar" else "mobile-verify"
        phr = body.method == "abha-address"
        scope = ["abha-address-login" if phr else "abha-login", verify]
        path = "/phr/web/login/abha/request/otp" if phr else "/profile/login/request/otp"
        out = await call("POST", path, json={"scope": scope, "loginHint": body.method, "loginId": await encrypt(ident), "otpSystem": via})
        tid = out["txnId"]
        await ensure_indexes()
        await db.abdm_txns.insert_one({"id": tid, "abdm_txn": tid, "kind": "verify", "expires_at": datetime.now(timezone.utc) + timedelta(hours=2), "owner": owner, "scope": scope, "phr": phr,
                                       "method": body.method, "patient_phone": body.patient_phone, "created_at": _now()})
        await audit(current, "verify_otp", txn=tid, method=body.method)
        return {"txn_id": tid, "message": out.get("message")}

    @r.post("/verify/confirm")
    async def verify_confirm(body: TxnOtp, current=Depends(get_current_user)):
        t = await get_txn(body.txn_id, current, "verify")
        path = "/phr/web/login/abha/verify" if t["phr"] else "/profile/login/verify"
        out = await call("POST", path, json={"scope": t["scope"], "authData": {"authMethods": ["otp"], "otp": {
            "txnId": t["abdm_txn"], "otpValue": await encrypt(body.otp)}}})
        if (out.get("authResult") or "").lower() != "success":
            await audit(current, "verify_confirm", ok=False, txn=t["id"])
            raise HTTPException(status_code=400, detail=f"ABDM: {out.get('message') or 'OTP verification failed'}")
        token = (out.get("tokens") or {}).get("token") or out.get("token")
        accounts: List[Dict[str, Any]] = out.get("accounts") or out.get("users") or []
        if t["method"] == "mobile":
            await set_txn(t["id"], abdm_txn=out.get("txnId") or t["abdm_txn"], t_token=token)
            if len(accounts) != 1:
                return {"txn_id": t["id"], "select": [{"abha_number": a.get("ABHANumber"), "name": a.get("name"),
                                                        "abha_address": a.get("preferredAbhaAddress"), "status": a.get("status")} for a in accounts]}
            return await _select(current, {**t, "t_token": token, "abdm_txn": out.get("txnId") or t["abdm_txn"]}, accounts[0]["ABHANumber"])
        await set_txn(t["id"], x_token=token, x_exp=time.time() + X_TOKEN_TTL)
        t["x_token"] = token
        try:
            prof = await profile_for(t)
        except HTTPException:
            if not accounts:
                raise
            prof = accounts[0]
        rec = await save_record(current, prof, f"{t['method']}_otp", t)
        await db.abha_records.update_one({"id": rec["id"]}, {"$set": {"card_txn_id": t["id"]}})
        await audit(current, "verify_confirm", txn=t["id"])
        return {"txn_id": t["id"], "record": public(rec)}

    async def _select(current, t: Dict[str, Any], abha_number: str):
        out = await call("POST", "/profile/login/verify/user", headers={"T-token": f"Bearer {t['t_token']}"},
                         json={"ABHANumber": abha_number, "txnId": t["abdm_txn"]})
        await set_txn(t["id"], x_token=out["token"], x_exp=time.time() + X_TOKEN_TTL)
        t["x_token"] = out["token"]
        rec = await save_record(current, await profile_for(t), "mobile_otp", t)
        await db.abha_records.update_one({"id": rec["id"]}, {"$set": {"card_txn_id": t["id"]}})
        await audit(current, "verify_confirm", txn=t["id"])
        return {"txn_id": t["id"], "record": public(rec)}

    @r.post("/verify/select")
    async def verify_select(body: SelectBody, current=Depends(get_current_user)):
        t = await get_txn(body.txn_id, current, "verify")
        if not t.get("t_token"):
            raise HTTPException(status_code=400, detail="Verify the OTP first")
        return await _select(current, t, body.abha_number)

    # ---------- Records ----------
    @r.get("/records")
    async def records(q: Optional[str] = None, current=Depends(get_current_user)):
        owner = owner_of(current)
        f: Dict[str, Any] = {} if owner == "trata" and current.get("is_master_admin") else {"owner": owner}
        if q:
            rx = {"$regex": re.escape(q.strip()), "$options": "i"}
            f["$or"] = [{"name": rx}, {"abha_number": rx}, {"abha_address": rx}, {"patient_phone": rx}]
        rows = await db.abha_records.find(f, {"_id": 0, "photo": 0}).sort("updated_at", -1).to_list(500)
        tids = [x.get("card_txn_id") or x.get("last_txn_id") for x in rows]
        live = {t["id"] async for t in db.abdm_txns.find({"id": {"$in": tids}, "x_exp": {"$gt": time.time()}}, {"_id": 0, "id": 1})}
        return {"records": [public(x) | {"card_available": (x.get("card_txn_id") or x.get("last_txn_id")) in live} for x in rows]}

    @r.patch("/records/{rid}")
    async def link_record(rid: str, body: LinkBody, current=Depends(get_current_user)):
        rec = await db.abha_records.find_one({"id": rid}, {"_id": 0})
        if not rec or (rec["owner"] != owner_of(current) and not current.get("is_master_admin")):
            raise HTTPException(status_code=404, detail="ABHA record not found")
        upd = body.model_dump(exclude_none=True)
        if body.patient_phone and not body.patient_user_id:
            upd["patient_user_id"] = await resolve_patient(body.patient_phone)
        await db.abha_records.update_one({"id": rid}, {"$set": {**upd, "updated_at": _now()}})
        rec = await db.abha_records.find_one({"id": rid}, {"_id": 0})
        if rec.get("patient_user_id") and on_linked:
            on_linked(rec)
        return public(rec)

    @r.post("/records/from-qr")
    async def from_qr(body: QrBody, current=Depends(get_current_user)):
        owner_of(current)
        prof = parse_abha_qr(body.qr)
        txn = {"id": f"qr-{uuid.uuid4()}", "patient_phone": body.patient_phone, "patient_user_id": body.patient_user_id}
        await ensure_indexes()
        rec = await save_record(current, {**prof, "kycVerified": False}, "qr_scan", txn)
        await audit(current, "qr_scan", record=rec["id"])
        return {"record": public(rec), "profile": {k: prof.get(k) for k in ("name", "gender", "dateOfBirth", "mobile", "address")}}

    @r.post("/patients/attach")
    async def attach(body: AttachBody, current=Depends(get_current_user)):
        rec = await db.abha_records.find_one({"id": body.record_id}, {"_id": 0})
        if not rec or (rec["owner"] != owner_of(current) and not current.get("is_master_admin")):
            raise HTTPException(status_code=404, detail="ABHA record not found")
        await db.abha_records.update_one({"id": rec["id"]}, {"$set": {"patient_user_id": body.patient_user_id, "updated_at": _now()}})
        rec["patient_user_id"] = body.patient_user_id
        if on_linked:
            on_linked(rec)
        await audit(current, "attach_patient", record=rec["id"])
        return public(rec)

    @r.post("/patients/lookup")
    async def lookup(body: Dict[str, List[str]], current=Depends(get_current_user)):
        owner_of(current)
        ids = [str(x) for x in (body.get("user_ids") or [])][:200]
        out: Dict[str, Any] = {}
        f: Dict[str, Any] = {"patient_user_id": {"$in": ids}}
        if is_provider(current):
            me = current.get("supabase_user_id") or current["id"]
            seen = await db.abdm_care_contexts.distinct("patient_user_id", {"provider_user_id": me, "patient_user_id": {"$in": ids}})
            f["$or"] = [{"owner": me}, {"patient_user_id": {"$in": seen}}, {"created_by.owner": me}]
        async for x in db.abha_records.find(f, {"_id": 0, "photo": 0}).sort("updated_at", 1):
            out[x["patient_user_id"]] = {k: x.get(k) for k in ("id", "abha_number", "abha_address", "name", "kyc_verified", "last_verified_via", "last_verified_at")}
        return {"abha": out}

    @r.get("/records/{rid}/card")
    async def card(rid: str, fmt: Literal["png", "pdf"] = Query("png", alias="format"), current=Depends(get_current_user)):
        rec = await db.abha_records.find_one({"id": rid}, {"_id": 0})
        if not rec or (rec["owner"] != owner_of(current) and not current.get("is_master_admin")):
            raise HTTPException(status_code=404, detail="ABHA record not found")
        t = await db.abdm_txns.find_one({"id": rec.get("card_txn_id") or rec.get("last_txn_id")}, {"_id": 0})
        if not t or not t.get("x_token") or t.get("x_exp", 0) < time.time():
            raise HTTPException(status_code=409, detail="ABHA session expired — verify the patient's ABHA again to download the card")
        if t.get("phr"):
            path = "/phr/web/login/profile/abha/phr-card"
        else:
            path = "/profile/account/abha-card" if fmt == "png" else "/profile/account/download-abha-card"
        res = await call("GET", path, headers={"X-token": f"Bearer {t['x_token']}"}, raw=True)
        await audit(current, "card_download", record=rid)
        ctype = res.headers.get("content-type", "image/png" if fmt == "png" else "application/pdf").split(";")[0]
        ext = "pdf" if "pdf" in ctype else "png"
        return Response(content=res.content, media_type=ctype,
                        headers={"Content-Disposition": f'attachment; filename="ABHA-{rec["abha_number"]}.{ext}"'})

    return r
