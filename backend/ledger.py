"""Provider Ledger & monthly invoicing (Master Admin + provider console).

Auto services are read live from the shared Supabase tables (ledger_sb).
CRM-owned billing data lives in Mongo: ledger_services (manual / AI-filled
extended services), ledger_files (proof docs in object storage),
ledger_promotions (flat marketing fees), billing_profiles, ledger_settings,
ledger_invoices."""
from __future__ import annotations

import asyncio
import html as _html
import io
import logging
import os
import re
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import requests
from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel, Field

import ledger_sb as lsb
import supabase_db as sb

logger = logging.getLogger("ledger")

APP_NAME = "trata-crm"
STORAGE_URL = ((os.environ.get("INTEGRATION_PROXY_URL") or "").strip()
               or "https://integrations.emergentagent.com").rstrip("/") + "/objstore/api/v1/storage"
EMERGENT_KEY = os.environ.get("EMERGENT_LLM_KEY")
MAX_FILE = 15 * 1024 * 1024
ALLOWED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
GST_PCT = 18.0
BILLABLE_STATUSES = {"completed", "complete", "discharged", "delivered", "fulfilled", "closed", "done",
                     "report_ready", "report_generated", "results_uploaded", "report_uploaded"}
STATE_CODES = {"01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand",
               "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "11": "Sikkim",
               "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur", "15": "Mizoram", "16": "Tripura",
               "17": "Meghalaya", "18": "Assam", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
               "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "26": "Dadra and Nagar Haveli and Daman and Diu",
               "27": "Maharashtra", "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
               "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh"}


def state_code(state: Optional[str], gstin: Optional[str]) -> Optional[str]:
    g = (gstin or "").strip()
    if len(g) >= 2 and g[:2] in STATE_CODES:
        return g[:2]
    n = (state or "").strip().lower()
    return next((c for c, name in STATE_CODES.items() if name.lower() == n), None)


def _billable(s: Dict[str, Any]) -> bool:
    return s["amount"] > 0 and (s.get("status") or "").strip().lower() in BILLABLE_STATUSES


def _phone10(p) -> str:
    d = re.sub(r"\D", "", str(p or ""))
    return d[-10:] if len(d) >= 10 else ""


def assign_groups(svcs: List[Dict[str, Any]]) -> None:
    """Group key per patient: patient_id, merged across ids sharing the same phone."""
    by_phone: Dict[str, str] = {}
    for x in sorted(svcs, key=lambda x: x.get("date") or ""):
        base = x.get("patient_id") or f"phone:{_phone10(x.get('patient_phone')) or 'unknown'}"
        ph = _phone10(x.get("patient_phone"))
        x["pkey"] = by_phone.setdefault(ph, base) if ph else base
        x["billable"] = _billable(x)


SERVICE_CATEGORIES = ["surgery", "procedure", "icu_stay", "room_charges", "implant", "diagnostics",
                      "pharmacy", "consultation", "ambulance", "lab_test", "other"]
_storage_key: Optional[str] = None


# ── Object storage ──────────────────────────────────────────────────────────
def _init_storage(force: bool = False) -> str:
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    r = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": EMERGENT_KEY}, timeout=30)
    r.raise_for_status()
    _storage_key = r.json()["storage_key"]
    return _storage_key


def _put(path: str, data: bytes, ctype: str) -> dict:
    for attempt in (0, 1):
        r = requests.put(f"{STORAGE_URL}/objects/{path}", data=data, timeout=120,
                         headers={"X-Storage-Key": _init_storage(force=bool(attempt)), "Content-Type": ctype})
        if r.status_code == 404 and not attempt:
            continue
        r.raise_for_status()
        return r.json()


def _get(path: str) -> bytes:
    for attempt in (0, 1):
        r = requests.get(f"{STORAGE_URL}/objects/{path}", timeout=60,
                         headers={"X-Storage-Key": _init_storage(force=bool(attempt))})
        if r.status_code == 404 and not attempt:
            continue
        r.raise_for_status()
        return r.content


# ── Models ──────────────────────────────────────────────────────────────────
class ServiceBody(BaseModel):
    patient_id: str
    patient_name: Optional[str] = None
    category: str
    title: str
    service_date: str
    amount: float = Field(ge=0)
    notes: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    linked_service_key: Optional[str] = None
    proof_file_ids: List[str]
    source: str = "manual"  # manual | ai
    ai_extracted: Optional[Dict[str, Any]] = None


class ReviewBody(BaseModel):
    action: str  # approve | reject
    reason: Optional[str] = None
    amount: Optional[float] = None


class PromoBody(BaseModel):
    title: str
    description: Optional[str] = None
    amount: float = Field(gt=0)
    charge_date: str
    channel: Optional[str] = "in_app"


class BillingProfileBody(BaseModel):
    fee_pct: float = Field(ge=0, le=100)
    category_fee_pct: Dict[str, float] = {}
    legal_name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    billing_address: Optional[str] = None
    state: Optional[str] = None
    billing_email: Optional[str] = None


class SettingsBody(BaseModel):
    legal_name: str
    address: str
    state: str
    gstin: Optional[str] = None
    pan: Optional[str] = None
    cin: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    bank_name: Optional[str] = None
    account_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc: Optional[str] = None
    upi_id: Optional[str] = None
    default_sac: Optional[str] = None
    invoice_prefix: str = "TH"
    payment_terms_days: int = 15
    terms: Optional[str] = None


class InvoiceBody(BaseModel):
    month: str  # YYYY-MM
    sac_code: str
    notes: Optional[str] = None
    due_days: Optional[int] = None


DEFAULT_SETTINGS = {
    "id": "trata", "legal_name": "Trata Health Pvt. Ltd.", "address": "", "state": "",
    "gstin": "", "pan": "", "cin": "", "email": "billing@tratahealth.com", "phone": "",
    "bank_name": "", "account_name": "", "account_number": "", "ifsc": "", "upi_id": "",
    "default_sac": "998599", "invoice_prefix": "TH", "payment_terms_days": 15,
    "terms": "Fees are computed on services delivered to patients referred via the Trata Health Patient App. "
             "Please raise any dispute within 7 days of the invoice date.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month_ok(m: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", m or ""))


def _r2(x) -> float:
    return round(float(x or 0) + 1e-9, 2)


def _inr_words(n: float) -> str:
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
            "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def two(x):
        return ones[x] if x < 20 else (tens[x // 10] + (" " + ones[x % 10] if x % 10 else ""))

    def three(x):
        h, r = divmod(x, 100)
        return ((ones[h] + " Hundred" + (" " if r else "")) if h else "") + (two(r) if r else "")

    rupees, paise = int(n), int(round((n - int(n)) * 100))
    parts, x = [], rupees
    for label, div in (("Crore", 10 ** 7), ("Lakh", 10 ** 5), ("Thousand", 10 ** 3)):
        q, x = divmod(x, div)
        if q:
            parts.append(f"{three(q) if q < 1000 else _inr_words(q).replace('Rupees ', '').replace(' Only', '')} {label}")
    if x:
        parts.append(three(x))
    s = "Rupees " + (" ".join(parts) or "Zero")
    if paise:
        s += f" and {two(paise)} Paise"
    return s + " Only"


def create_ledger_router(db, get_current_user: Callable, get_current_user_from_query: Callable,
                         is_provider: Callable, llm_key: str, parse_ai_json: Callable) -> APIRouter:
    r = APIRouter(prefix="/api")
    _cache: Dict[str, Any] = {}

    @r.on_event("startup")
    async def _indexes():
        await db.ledger_invoices.update_many({"active": {"$exists": False}, "status": {"$ne": "void"}}, {"$set": {"active": True}})
        await db.ledger_invoices.create_index([("provider_user_id", 1), ("month", 1)], unique=True,
                                              partialFilterExpression={"active": True}, name="one_active_invoice_per_month")

    def is_admin(c) -> bool:
        return bool(c.get("is_master_admin") or c.get("role") == "admin")

    def require_admin(c):
        if not is_admin(c):
            raise HTTPException(status_code=403, detail="Master admin access only")

    def prov_uid(c) -> str:
        if not is_provider(c):
            raise HTTPException(status_code=403, detail="Provider access only")
        return c.get("supabase_user_id") or c["id"]

    def actor(c) -> Dict[str, Any]:
        return {"id": c.get("id"), "name": c.get("name") or c.get("phone"),
                "role": "master_admin" if is_admin(c) else "provider"}

    async def settings() -> Dict[str, Any]:
        s = await db.ledger_settings.find_one({"id": "trata"}, {"_id": 0})
        return {**DEFAULT_SETTINGS, **(s or {})}

    async def billing_profile(uid: str) -> Dict[str, Any]:
        bp = await db.billing_profiles.find_one({"provider_user_id": uid}, {"_id": 0})
        return bp or {"provider_user_id": uid, "fee_pct": 10.0, "category_fee_pct": {}}

    async def auto_services(uid: str, fresh: bool = False) -> Dict[str, Any]:
        hit = _cache.get(uid)
        if hit and not fresh and time.time() - hit[0] < 60:
            return hit[1]
        data = await lsb.fetch_provider_services(uid)
        assign_groups(data.get("services", []))
        _cache[uid] = (time.time(), data)
        return data

    def patient_key(s) -> str:
        return s["pkey"]

    def fee_for(bp, category: str) -> float:
        return float((bp.get("category_fee_pct") or {}).get(category, bp.get("fee_pct", 10.0)))

    async def provider_detail(uid: str, include_internal: bool) -> Dict[str, Any]:
        data = await auto_services(uid, fresh=True)
        if not data:
            raise HTTPException(status_code=404, detail="Provider not found")
        manual = await db.ledger_services.find(
            {"provider_user_id": uid, "is_deleted": {"$ne": True}}, {"_id": 0}).sort("service_date", -1).to_list(2000)
        invoiced = await invoiced_keys(uid)
        patients: Dict[str, Dict[str, Any]] = {}
        for s in data["services"]:
            k = patient_key(s)
            p = patients.setdefault(k, {"key": k, "patient_id": s.get("patient_id"), "name": s.get("patient_name"),
                                        "phone": s.get("patient_phone"), "services": [], "first_seen": s["date"]})
            p["name"] = p["name"] or s.get("patient_name")
            p["first_seen"] = min(filter(None, [p["first_seen"], s["date"]]), default=None)
            p["services"].append({**s, "invoice_id": invoiced.get(s["key"])})
        for m in manual:
            k = m["patient_id"]
            p = patients.get(k)
            if not p:
                continue
            p["services"].append({
                "key": f"manual:{m['id']}", "kind": "manual", "ref_id": m["id"], "source": m["source"],
                "patient_id": k, "date": m["service_date"], "title": m["title"], "category": m["category"],
                "amount": m["amount"], "status": m["status"], "notes": m.get("notes"),
                "line_items": m.get("line_items") or [], "proofs": m.get("proofs") or [],
                "created_by": m.get("created_by"), "reviewed_by": m.get("reviewed_by"),
                "review_reason": m.get("review_reason"), "invoice_id": m.get("invoice_id"),
                "linked_service_key": m.get("linked_service_key"), "ai_extracted": m.get("ai_extracted"),
                "billable": m["status"] == "approved",
            })
        plist = []
        for p in patients.values():
            p["services"].sort(key=lambda s: s.get("date") or "", reverse=True)
            p["total_amount"] = _r2(sum(s["amount"] for s in p["services"]
                                        if (s["kind"] != "manual" and s.get("billable")) or s["status"] == "approved"))
            p["pending_review"] = sum(1 for s in p["services"] if s["kind"] == "manual" and s["status"] == "pending_review")
            plist.append(p)
        plist.sort(key=lambda p: max((s.get("date") or "" for s in p["services"]), default=""), reverse=True)
        prov = next((x for x in await lsb.list_providers() if x["id"] == uid), None) or {"id": uid}
        out = {"provider": {**prov, "vertical": data["vertical"]}, "patients": plist,
               "categories": SERVICE_CATEGORIES}
        if include_internal:
            out["billing_profile"] = await billing_profile(uid)
            out["promotions"] = await db.ledger_promotions.find(
                {"provider_user_id": uid, "is_deleted": {"$ne": True}}, {"_id": 0}).sort("charge_date", -1).to_list(500)
            out["invoices"] = await db.ledger_invoices.find(
                {"provider_user_id": uid}, {"_id": 0, "lines": 0}).sort("created_at", -1).to_list(200)
        else:
            out["invoices"] = await db.ledger_invoices.find(
                {"provider_user_id": uid, "status": {"$in": ["shared", "paid"]}},
                {"_id": 0, "lines": 0}).sort("created_at", -1).to_list(200)
        return out

    async def invoiced_keys(uid: str) -> Dict[str, str]:
        out: Dict[str, str] = {}
        async for inv in db.ledger_invoices.find({"provider_user_id": uid, "status": {"$ne": "void"}},
                                                 {"_id": 0, "id": 1, "lines.key": 1}):
            for ln in inv.get("lines", []):
                out[ln["key"]] = inv["id"]
        return out

    # ── Providers ───────────────────────────────────────────────────────────
    @r.get("/ledger/providers")
    async def ledger_providers(month: Optional[str] = None, fresh: bool = False, current=Depends(get_current_user)):
        require_admin(current)
        if fresh:
            _cache.pop("__all__", None)
        month = month if _month_ok(month or "") else datetime.now(timezone.utc).strftime("%Y-%m")
        hit = _cache.get("__all__")
        if hit and time.time() - hit[0] < 45:
            provs, allsv = [dict(p) for p in hit[1][0]], hit[1][1]
        else:
            provs, allsv = await asyncio.gather(lsb.list_providers(), lsb.fetch_all_provider_services())
            for v in allsv.values():
                assign_groups(v)
            _cache["__all__"] = (time.time(), ([dict(p) for p in provs], allsv))
        for p in provs:
            svcs = allsv.get(p["id"], [])
            p["patients"] = len({patient_key(x) for x in svcs})
            p["auto_services"] = len(svcs)
            p["month_auto_amount"] = _r2(sum(x["amount"] for x in svcs if x["billable"] and (x["date"] or "").startswith(month)))
        man = {}
        async for m in db.ledger_services.find({"is_deleted": {"$ne": True}},
                                               {"_id": 0, "provider_user_id": 1, "status": 1, "amount": 1, "service_date": 1}):
            x = man.setdefault(m["provider_user_id"], {"pending": 0, "month_manual": 0.0, "manual": 0})
            x["manual"] += 1
            if m["status"] == "pending_review":
                x["pending"] += 1
            if m["status"] == "approved" and (m.get("service_date") or "").startswith(month):
                x["month_manual"] += m["amount"]
        promo = {}
        async for pm in db.ledger_promotions.find({"is_deleted": {"$ne": True}, "charge_date": {"$regex": f"^{month}"}},
                                                  {"_id": 0, "provider_user_id": 1, "amount": 1}):
            promo[pm["provider_user_id"]] = promo.get(pm["provider_user_id"], 0) + pm["amount"]
        inv = {}
        async for i in db.ledger_invoices.find({"month": month, "status": {"$ne": "void"}},
                                               {"_id": 0, "provider_user_id": 1, "number": 1, "status": 1, "grand_total": 1, "id": 1}):
            inv[i["provider_user_id"]] = i
        for p in provs:
            mm = man.get(p["id"], {})
            p["pending_review"] = mm.get("pending", 0)
            p["manual_services"] = mm.get("manual", 0)
            p["month_manual_amount"] = _r2(mm.get("month_manual", 0))
            p["month_promotions"] = _r2(promo.get(p["id"], 0))
            p["month_billable"] = _r2(p["month_auto_amount"] + p["month_manual_amount"])
            p["month_invoice"] = inv.get(p["id"])
        provs.sort(key=lambda p: (-p["patients"], -(p["month_billable"])))
        return {"month": month, "providers": provs,
                "totals": {"providers": len(provs), "patients": sum(p["patients"] for p in provs),
                           "pending_review": sum(p["pending_review"] for p in provs),
                           "month_billable": _r2(sum(p["month_billable"] for p in provs))}}

    @r.get("/ledger/providers/{uid}")
    async def ledger_provider(uid: str, current=Depends(get_current_user)):
        require_admin(current)
        return await provider_detail(uid, include_internal=True)

    @r.get("/provider/ledger")
    async def my_ledger(current=Depends(get_current_user)):
        return await provider_detail(prov_uid(current), include_internal=False)

    # ── Files ───────────────────────────────────────────────────────────────
    async def _upload(uid: str, file: UploadFile, current) -> Dict[str, Any]:
        data = await file.read()
        ctype = (file.content_type or "").lower()
        if ctype not in ALLOWED_MIME:
            raise HTTPException(status_code=400, detail="Only PDF, JPG, PNG or WEBP files are allowed")
        if not data or len(data) > MAX_FILE:
            raise HTTPException(status_code=400, detail="File must be between 1 byte and 15 MB")
        ext = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}[ctype]
        path = f"{APP_NAME}/ledger/{uid}/{uuid.uuid4()}.{ext}"
        try:
            res = await asyncio.to_thread(_put, path, data, ctype)
        except Exception as e:
            logger.error(f"ledger upload failed: {e}")
            raise HTTPException(status_code=502, detail="File storage unavailable, please retry")
        doc = {"id": str(uuid.uuid4()), "provider_user_id": uid, "storage_path": res["path"],
               "filename": file.filename, "content_type": ctype, "size": res.get("size", len(data)),
               "uploaded_by": actor(current), "is_deleted": False, "created_at": _now()}
        await db.ledger_files.insert_one(dict(doc))
        return {k: doc[k] for k in ("id", "filename", "content_type", "size", "created_at")}

    @r.post("/ledger/providers/{uid}/files")
    async def admin_upload(uid: str, file: UploadFile = File(...), current=Depends(get_current_user)):
        require_admin(current)
        return await _upload(uid, file, current)

    @r.post("/provider/ledger/files")
    async def provider_upload(file: UploadFile = File(...), current=Depends(get_current_user)):
        return await _upload(prov_uid(current), file, current)

    async def _file_for(fid: str, current) -> Dict[str, Any]:
        f = await db.ledger_files.find_one({"id": fid, "is_deleted": False}, {"_id": 0})
        if not f:
            raise HTTPException(status_code=404, detail="File not found")
        if not is_admin(current) and prov_uid(current) != f["provider_user_id"]:
            raise HTTPException(status_code=403, detail="Not your file")
        return f

    @r.get("/ledger/files/{fid}")
    async def download_file(fid: str, authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)):
        current = await (get_current_user(authorization) if authorization else get_current_user_from_query(token))
        f = await _file_for(fid, current)
        data = await asyncio.to_thread(_get, f["storage_path"])
        return Response(content=data, media_type=f["content_type"],
                        headers={"Content-Disposition": f'inline; filename="{f["filename"] or fid}"'})

    @r.post("/ledger/ai-extract/{fid}")
    async def ai_extract(fid: str, current=Depends(get_current_user)):
        f = await _file_for(fid, current)
        data = await asyncio.to_thread(_get, f["storage_path"])
        from emergentintegrations.llm.chat import FileContentWithMimeType, LlmChat, UserMessage
        suffix = "." + f["storage_path"].rsplit(".", 1)[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            path = tmp.name
        prompt = (
            "You read Indian hospital/clinic bills, discharge summaries, OT notes and lab invoices. "
            "Extract ONE billable service record. Respond with ONLY a JSON object, no prose:\n"
            '{"patient_name": "", "service_date": "YYYY-MM-DD", "category": one of '
            f"{SERVICE_CATEGORIES}, "
            '"title": "<short service name e.g. Laparoscopic appendectomy>", "amount": <total billed number, INR>, '
            '"line_items": [{"description": "", "amount": <number>}], "hospital_name": "", "doctor_name": "", '
            '"bill_number": "", "notes": "<one-line summary>", "confidence": <0-1>}\n'
            "Omit keys you cannot read with certainty. Never invent values."
        )
        try:
            chat = LlmChat(api_key=llm_key, session_id=f"ledger-ai-{fid}",
                           system_message="You are a precise medical billing data-extraction assistant.") \
                .with_model("gemini", "gemini-2.5-flash")
            reply = await chat.send_message(UserMessage(
                text=prompt, file_contents=[FileContentWithMimeType(file_path=path, mime_type=f["content_type"])]))
            parsed = parse_ai_json(str(reply))
            if not isinstance(parsed, dict):
                parsed = {}
        except Exception as e:
            logger.error(f"ledger ai extract failed: {e}")
            raise HTTPException(status_code=502, detail="AI extraction failed — please fill the form manually")
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if parsed.get("category") not in SERVICE_CATEGORIES:
            parsed["category"] = "other"
        try:
            parsed["amount"] = _r2(parsed.get("amount"))
        except (TypeError, ValueError):
            parsed.pop("amount", None)
        items = parsed.get("line_items") if isinstance(parsed.get("line_items"), list) else []
        parsed["line_items"] = [{"description": str(i.get("description", ""))[:200], "amount": _r2(i.get("amount"))}
                                for i in items if isinstance(i, dict)][:50]
        return {"file_id": fid, "extracted": parsed, "model": "gemini-2.5-flash"}

    # ── Manual services ─────────────────────────────────────────────────────
    async def _create_service(uid: str, body: ServiceBody, current) -> Dict[str, Any]:
        if body.category not in SERVICE_CATEGORIES:
            raise HTTPException(status_code=400, detail="Unknown category")
        if not body.proof_file_ids:
            raise HTTPException(status_code=400, detail="At least one proof document is required")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.service_date):
            raise HTTPException(status_code=400, detail="service_date must be YYYY-MM-DD")
        files = await db.ledger_files.find({"id": {"$in": body.proof_file_ids}, "provider_user_id": uid,
                                            "is_deleted": False}, {"_id": 0}).to_list(50)
        if len(files) != len(set(body.proof_file_ids)):
            raise HTTPException(status_code=400, detail="One or more proof documents are invalid")
        data = await auto_services(uid)
        served = {patient_key(s): s for s in data.get("services", [])}
        if body.patient_id not in served:
            raise HTTPException(status_code=400, detail="Patient has no Patient-App booking or SOS with this provider")
        admin = is_admin(current)
        doc = {
            "id": str(uuid.uuid4()), "provider_user_id": uid, "patient_id": body.patient_id,
            "patient_name": body.patient_name or served[body.patient_id].get("patient_name"),
            "patient_phone": served[body.patient_id].get("patient_phone"),
            "category": body.category, "title": body.title.strip(), "service_date": body.service_date,
            "amount": _r2(body.amount), "notes": body.notes, "line_items": body.line_items or [],
            "linked_service_key": body.linked_service_key,
            "proofs": [{k: f[k] for k in ("id", "filename", "content_type", "size")} for f in files],
            "source": "ai" if body.source == "ai" else "manual", "ai_extracted": body.ai_extracted,
            "status": "approved" if admin else "pending_review",
            "created_by": actor(current), "created_at": _now(), "updated_at": _now(),
            "reviewed_by": actor(current) if admin else None, "reviewed_at": _now() if admin else None,
            "invoice_id": None, "is_deleted": False,
        }
        await db.ledger_services.insert_one(dict(doc))
        return doc

    @r.post("/ledger/providers/{uid}/services")
    async def admin_add_service(uid: str, body: ServiceBody, current=Depends(get_current_user)):
        require_admin(current)
        return await _create_service(uid, body, current)

    @r.post("/provider/ledger/services")
    async def provider_add_service(body: ServiceBody, current=Depends(get_current_user)):
        return await _create_service(prov_uid(current), body, current)

    @r.get("/ledger/review-queue")
    async def review_queue(current=Depends(get_current_user)):
        require_admin(current)
        items = await db.ledger_services.find({"status": "pending_review", "is_deleted": {"$ne": True}},
                                              {"_id": 0}).sort("created_at", 1).to_list(500)
        names = {p["id"]: p["display_name"] for p in await lsb.list_providers()}
        for i in items:
            i["provider_name"] = names.get(i["provider_user_id"])
        return {"items": items}

    @r.post("/ledger/services/{sid}/review")
    async def review_service(sid: str, body: ReviewBody, current=Depends(get_current_user)):
        require_admin(current)
        if body.action not in ("approve", "reject"):
            raise HTTPException(status_code=400, detail="action must be approve or reject")
        if body.action == "reject" and not (body.reason or "").strip():
            raise HTTPException(status_code=400, detail="A reason is required to reject")
        s = await db.ledger_services.find_one({"id": sid, "is_deleted": {"$ne": True}}, {"_id": 0})
        if not s:
            raise HTTPException(status_code=404, detail="Service not found")
        if s["status"] != "pending_review":
            raise HTTPException(status_code=400, detail=f"Already {s['status']} — only pending entries can be reviewed")
        upd = {"status": "approved" if body.action == "approve" else "rejected", "review_reason": body.reason,
               "reviewed_by": actor(current), "reviewed_at": _now(), "updated_at": _now()}
        if body.action == "approve" and body.amount is not None:
            upd["amount"] = _r2(body.amount)
        await db.ledger_services.update_one({"id": sid}, {"$set": upd})
        return {**s, **upd}

    @r.delete("/ledger/services/{sid}")
    async def delete_service(sid: str, current=Depends(get_current_user)):
        s = await db.ledger_services.find_one({"id": sid, "is_deleted": {"$ne": True}}, {"_id": 0})
        if not s:
            raise HTTPException(status_code=404, detail="Service not found")
        if not is_admin(current) and (prov_uid(current) != s["provider_user_id"] or s["status"] == "approved"):
            raise HTTPException(status_code=403, detail="Only pending entries you created can be removed")
        if s.get("invoice_id"):
            raise HTTPException(status_code=400, detail="Already invoiced — void the invoice first")
        await db.ledger_services.update_one({"id": sid}, {"$set": {"is_deleted": True, "updated_at": _now()}})
        return {"success": True}

    # ── Promotions (flat fee) ───────────────────────────────────────────────
    @r.post("/ledger/providers/{uid}/promotions")
    async def add_promo(uid: str, body: PromoBody, current=Depends(get_current_user)):
        require_admin(current)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.charge_date):
            raise HTTPException(status_code=400, detail="charge_date must be YYYY-MM-DD")
        doc = {"id": str(uuid.uuid4()), "provider_user_id": uid, **body.model_dump(), "amount": _r2(body.amount),
               "invoice_id": None, "is_deleted": False, "created_by": actor(current), "created_at": _now()}
        await db.ledger_promotions.insert_one(dict(doc))
        return doc

    @r.delete("/ledger/promotions/{pid}")
    async def delete_promo(pid: str, current=Depends(get_current_user)):
        require_admin(current)
        pm = await db.ledger_promotions.find_one({"id": pid, "is_deleted": {"$ne": True}}, {"_id": 0})
        if not pm or pm.get("invoice_id"):
            raise HTTPException(status_code=400, detail="Not found or already invoiced")
        await db.ledger_promotions.update_one({"id": pid}, {"$set": {"is_deleted": True}})
        return {"success": True}

    # ── Billing profile + Trata settings ────────────────────────────────────
    @r.put("/ledger/providers/{uid}/billing")
    async def put_billing(uid: str, body: BillingProfileBody, current=Depends(get_current_user)):
        require_admin(current)
        bad = [k for k, v in body.category_fee_pct.items() if k not in SERVICE_CATEGORIES + ["sos", "admission",
               "consultation", "teleconsultation", "ambulance_ride", "lab_test"] or not 0 <= v <= 100]
        if bad:
            raise HTTPException(status_code=400, detail=f"Invalid category fee: {bad}")
        doc = {"provider_user_id": uid, **body.model_dump(), "updated_at": _now(), "updated_by": actor(current)}
        await db.billing_profiles.update_one({"provider_user_id": uid}, {"$set": doc}, upsert=True)
        return doc

    @r.get("/ledger/settings")
    async def get_settings(current=Depends(get_current_user)):
        require_admin(current)
        return await settings()

    @r.put("/ledger/settings")
    async def put_settings(body: SettingsBody, current=Depends(get_current_user)):
        require_admin(current)
        doc = {"id": "trata", **body.model_dump(exclude_none=True), "updated_at": _now()}
        await db.ledger_settings.update_one({"id": "trata"}, {"$set": doc}, upsert=True)
        return doc

    # ── Invoices ────────────────────────────────────────────────────────────
    @r.post("/ledger/providers/{uid}/invoices")
    async def create_invoice(uid: str, body: InvoiceBody, current=Depends(get_current_user)):
        require_admin(current)
        if not _month_ok(body.month):
            raise HTTPException(status_code=400, detail="month must be YYYY-MM")
        if not body.sac_code.strip():
            raise HTTPException(status_code=400, detail="SAC code is required")
        if await db.ledger_invoices.find_one({"provider_user_id": uid, "month": body.month, "status": {"$ne": "void"}}):
            raise HTTPException(status_code=400, detail="An invoice already exists for this month — void it first")
        st, bp = await settings(), await billing_profile(uid)
        data = await auto_services(uid, fresh=True)
        if not data:
            raise HTTPException(status_code=404, detail="Provider not found")
        done = await invoiced_keys(uid)
        lines: List[Dict[str, Any]] = []
        for s in data["services"]:
            if (s["date"] or "").startswith(body.month) and s["billable"] and s["key"] not in done:
                pct = fee_for(bp, s["kind"])
                lines.append({"key": s["key"], "type": "service", "category": s["kind"], "date": (s["date"] or "")[:10],
                              "patient": s.get("patient_name") or s.get("patient_phone") or "—",
                              "description": s["title"], "billable": s["amount"], "fee_pct": pct,
                              "fee": _r2(s["amount"] * pct / 100)})
        manual = await db.ledger_services.find({"provider_user_id": uid, "status": "approved", "invoice_id": None,
                                                "is_deleted": {"$ne": True},
                                                "service_date": {"$regex": f"^{body.month}"}}, {"_id": 0}).to_list(2000)
        for m in manual:
            pct = fee_for(bp, m["category"])
            lines.append({"key": f"manual:{m['id']}", "type": "service", "category": m["category"],
                          "date": m["service_date"], "patient": m.get("patient_name") or m.get("patient_phone") or "—",
                          "description": m["title"],
                          "billable": m["amount"], "fee_pct": pct, "fee": _r2(m["amount"] * pct / 100)})
        promos = await db.ledger_promotions.find({"provider_user_id": uid, "invoice_id": None, "is_deleted": {"$ne": True},
                                                  "charge_date": {"$regex": f"^{body.month}"}}, {"_id": 0}).to_list(500)
        for pm in promos:
            lines.append({"key": f"promo:{pm['id']}", "type": "promotion", "category": "promotion",
                          "date": pm["charge_date"], "patient": "—",
                          "description": f"Marketing / promotion — {pm['title']}", "billable": None,
                          "fee_pct": None, "fee": pm["amount"]})
        if not lines:
            raise HTTPException(status_code=400, detail="Nothing billable for this month")
        lines.sort(key=lambda x: (x["type"] != "service", x["date"]))
        service_fee = _r2(sum(x["fee"] for x in lines if x["type"] == "service"))
        promo_fee = _r2(sum(x["fee"] for x in lines if x["type"] == "promotion"))
        taxable = _r2(service_fee + promo_fee)
        seller_code, buyer_code = state_code(st.get("state"), st.get("gstin")), state_code(bp.get("state"), bp.get("gstin"))
        same_state = bool(seller_code) and seller_code == buyer_code
        gst = _r2(taxable * GST_PCT / 100)
        tax = ({"cgst": _r2(gst / 2), "sgst": _r2(gst - _r2(gst / 2)), "igst": 0.0} if same_state
               else {"cgst": 0.0, "sgst": 0.0, "igst": gst})
        seq = await db.ledger_counters.find_one_and_update({"id": f"inv-{body.month}"}, {"$inc": {"n": 1}},
                                                           upsert=True, return_document=True)
        n = (seq or {}).get("n", 1)
        issue = datetime.now(timezone.utc)
        prov = next((x for x in await lsb.list_providers() if x["id"] == uid), {}) or {}
        inv = {
            "id": str(uuid.uuid4()), "number": f"{st.get('invoice_prefix') or 'TH'}/{body.month.replace('-', '')}/{n:04d}",
            "provider_user_id": uid, "provider_name": bp.get("legal_name") or prov.get("display_name"),
            "provider_vertical": data["vertical"], "provider_city": prov.get("city"), "provider_phone": prov.get("phone"),
            "provider_gstin": bp.get("gstin"), "provider_address": bp.get("billing_address"),
            "provider_state": bp.get("state"), "provider_email": bp.get("billing_email"),
            "place_of_supply": f"{STATE_CODES[buyer_code]} ({buyer_code})" if buyer_code else (bp.get("state") or None),
            "month": body.month, "sac_code": body.sac_code.strip(), "notes": body.notes,
            "issue_date": issue.date().isoformat(),
            "due_date": (issue + timedelta(days=body.due_days or st.get("payment_terms_days") or 15)).date().isoformat(),
            "lines": lines, "total_billable": _r2(sum(x["billable"] or 0 for x in lines)),
            "service_fee": service_fee, "promotion_fee": promo_fee, "taxable_value": taxable,
            "gst_pct": GST_PCT, **tax, "gst_total": gst, "grand_total": _r2(taxable + gst),
            "seller": {k: st.get(k) for k in ("legal_name", "address", "state", "gstin", "pan", "cin", "email", "phone",
                                              "bank_name", "account_name", "account_number", "ifsc", "upi_id", "terms")},
            "status": "issued", "active": True, "created_by": actor(current), "created_at": _now(),
        }
        try:
            await db.ledger_invoices.insert_one(dict(inv))
        except DuplicateKeyError:
            raise HTTPException(status_code=400, detail="An invoice already exists for this month — void it first")
        await db.ledger_services.update_many({"id": {"$in": [m["id"] for m in manual]}}, {"$set": {"invoice_id": inv["id"]}})
        await db.ledger_promotions.update_many({"id": {"$in": [p["id"] for p in promos]}}, {"$set": {"invoice_id": inv["id"]}})
        return inv

    @r.get("/ledger/invoices")
    async def list_invoices(month: Optional[str] = None, current=Depends(get_current_user)):
        require_admin(current)
        q = {"month": month} if month else {}
        return {"items": await db.ledger_invoices.find(q, {"_id": 0, "lines": 0}).sort("created_at", -1).to_list(500)}

    async def _invoice_for(iid: str, current) -> Dict[str, Any]:
        inv = await db.ledger_invoices.find_one({"id": iid}, {"_id": 0})
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        if not is_admin(current) and (prov_uid(current) != inv["provider_user_id"] or inv["status"] not in ("shared", "paid")):
            raise HTTPException(status_code=403, detail="Not your invoice")
        return inv

    @r.get("/ledger/invoices/{iid}")
    async def get_invoice(iid: str, current=Depends(get_current_user)):
        return await _invoice_for(iid, current)

    @r.post("/ledger/invoices/{iid}/share")
    async def share_invoice(iid: str, current=Depends(get_current_user)):
        require_admin(current)
        inv = await _invoice_for(iid, current)
        if inv["status"] == "void":
            raise HTTPException(status_code=400, detail="Invoice is void")
        await db.ledger_invoices.update_one({"id": iid}, {"$set": {"status": "shared" if inv["status"] != "paid" else "paid",
                                                                   "shared_at": _now(), "shared_by": actor(current)}})
        try:
            pool = await sb.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO public.notifications (id, user_id, title, message, notification_type, data, is_read, created_at)
                    VALUES ($1, $2, $3, $4, 'invoice', $5::json, FALSE, now())""",
                    str(uuid.uuid4()), inv["provider_user_id"], f"Invoice {inv['number']} from Trata Health",
                    f"Your {inv['month']} invoice of ₹{inv['grand_total']:,.2f} is ready. Due {inv['due_date']}.",
                    __import__("json").dumps({"invoice_id": iid, "number": inv["number"]}))
        except Exception as e:
            logger.warning(f"invoice notify failed: {e}")
        return {"success": True, "status": "shared"}

    @r.post("/ledger/invoices/{iid}/status")
    async def invoice_status(iid: str, status: str = Query(...), current=Depends(get_current_user)):
        require_admin(current)
        inv = await _invoice_for(iid, current)
        if status not in ("paid", "void"):
            raise HTTPException(status_code=400, detail="status must be paid or void")
        if inv["status"] == "void":
            raise HTTPException(status_code=400, detail="Invoice already void")
        upd = {"status": status, f"{status}_at": _now()}
        if status == "void":
            upd["active"] = False
        await db.ledger_invoices.update_one({"id": iid}, {"$set": upd})
        if status == "void":
            await db.ledger_services.update_many({"invoice_id": iid}, {"$set": {"invoice_id": None}})
            await db.ledger_promotions.update_many({"invoice_id": iid}, {"$set": {"invoice_id": None}})
        return {"success": True, "status": status}

    @r.get("/ledger/invoices/{iid}/pdf")
    async def invoice_pdf(iid: str, authorization: Optional[str] = Header(None), token: Optional[str] = Query(None)):
        current = await (get_current_user(authorization) if authorization else get_current_user_from_query(token))
        inv = await _invoice_for(iid, current)
        from xhtml2pdf import pisa
        buf = io.BytesIO()
        await asyncio.to_thread(pisa.CreatePDF, render_invoice_html(inv), dest=buf, encoding="utf-8")
        fname = inv["number"].replace("/", "-") + ".pdf"
        return Response(content=buf.getvalue(), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{fname}"'})

    return r


def render_invoice_html(inv: Dict[str, Any]) -> str:
    e = lambda v: _html.escape(str(v)) if v not in (None, "") else "—"  # noqa: E731
    money = lambda v: f"Rs. {float(v or 0):,.2f}"  # noqa: E731
    s = inv.get("seller") or {}
    rows = "".join(
        f"<tr><td class='c'>{i + 1}</td><td>{e(ln['date'])}</td><td>{e(ln['patient'])}</td>"
        f"<td>{e(ln['description'])}<br/><span class='mut'>{e((ln['category'] or '').replace('_', ' ').title())}</span></td>"
        f"<td class='r'>{money(ln['billable']) if ln['billable'] is not None else 'Flat fee'}</td>"
        f"<td class='r'>{(str(ln['fee_pct']) + '%') if ln['fee_pct'] is not None else '—'}</td>"
        f"<td class='r'><b>{money(ln['fee'])}</b></td></tr>"
        for i, ln in enumerate(inv["lines"]))
    tax_rows = (f"<tr><td>CGST @ 9%</td><td class='r'>{money(inv['cgst'])}</td></tr>"
                f"<tr><td>SGST @ 9%</td><td class='r'>{money(inv['sgst'])}</td></tr>") if inv.get("cgst") else \
        f"<tr><td>IGST @ 18%</td><td class='r'>{money(inv['igst'])}</td></tr>"
    bank = "".join(f"<tr><td class='mut'>{k}</td><td>{e(s.get(v))}</td></tr>" for k, v in (
        ("Bank", "bank_name"), ("Account name", "account_name"), ("Account no.", "account_number"),
        ("IFSC", "ifsc"), ("UPI", "upi_id")) if s.get(v))
    status = {"paid": "PAID", "void": "VOID"}.get(inv["status"], "TAX INVOICE")
    return f"""<html><head><meta charset="utf-8"/><style>
@page {{ size: A4; margin: 14mm 12mm 16mm 12mm; }}
body {{ font-family: Helvetica; font-size: 8.5pt; color: #091E42; }}
.band {{ background-color: #0B3D91; color: #FFFFFF; padding: 10px 12px; }}
.brand {{ font-size: 20pt; font-weight: bold; }} .tag {{ font-size: 7.5pt; color: #BFD4FF; }}
.accent {{ background-color: #00B8A9; height: 4px; }}
table {{ width: 100%; border-collapse: collapse; }}
.box td {{ vertical-align: top; padding: 4px 6px; }}
.h {{ font-size: 7pt; color: #5E6C84; text-transform: uppercase; letter-spacing: 1px; font-weight: bold; }}
.items th {{ background-color: #F0F4FA; color: #42526E; font-size: 7pt; text-align: left; padding: 5px 4px; border-bottom: 1px solid #C1C7D0; }}
.items td {{ padding: 5px 4px; border-bottom: 0.5px solid #DFE1E6; vertical-align: top; }}
.r {{ text-align: right; }} .c {{ text-align: center; }} .mut {{ color: #6B778C; font-size: 7pt; }}
.tot td {{ padding: 3px 6px; }} .grand td {{ background-color: #0B3D91; color: #FFFFFF; font-size: 11pt; font-weight: bold; padding: 7px 6px; }}
.stamp {{ color: #00875A; font-size: 12pt; font-weight: bold; }}
.foot {{ font-size: 7pt; color: #6B778C; border-top: 0.5px solid #DFE1E6; padding-top: 6px; }}
</style></head><body>
<table class="band"><tr>
 <td><span class="brand">Trata Health</span><br/><span class="tag">CONNECTED EMERGENCY &amp; CARE NETWORK</span></td>
 <td class="r"><span style="font-size:13pt;font-weight:bold;">{status}</span><br/>
   <span class="tag">Invoice # </span><b>{e(inv['number'])}</b><br/>
   <span class="tag">Issued {e(inv['issue_date'])} &#183; Due {e(inv['due_date'])}</span></td>
</tr></table>
<div class="accent"></div><br/>
<table class="box"><tr>
 <td width="50%"><div class="h">From</div><b>{e(s.get('legal_name'))}</b><br/>{e(s.get('address'))}<br/>
   State: {e(s.get('state'))}<br/>GSTIN: <b>{e(s.get('gstin'))}</b> &#183; PAN: {e(s.get('pan'))}<br/>
   {e(s.get('email'))} {('&#183; ' + e(s.get('phone'))) if s.get('phone') else ''}</td>
 <td width="50%"><div class="h">Billed to</div><b>{e(inv.get('provider_name'))}</b><br/>
   {e(inv.get('provider_address') or inv.get('provider_city'))}<br/>State: {e(inv.get('provider_state'))}<br/>
   GSTIN: <b>{e(inv.get('provider_gstin'))}</b><br/>Place of supply: <b>{e(inv.get('place_of_supply'))}</b><br/>{e(inv.get('provider_email') or inv.get('provider_phone'))}</td>
</tr></table>
<table class="box" style="background-color:#F7F9FC;"><tr>
 <td><span class="h">Billing period</span><br/><b>{e(inv['month'])}</b></td>
 <td><span class="h">SAC code</span><br/><b>{e(inv['sac_code'])}</b></td>
 <td><span class="h">Provider type</span><br/><b>{e((inv.get('provider_vertical') or '').title())}</b></td>
 <td><span class="h">Patient-App billable value</span><br/><b>{money(inv['total_billable'])}</b></td>
</tr></table><br/>
<table class="items"><thead><tr><th width="4%">#</th><th width="10%">Date</th><th width="16%">Patient</th>
 <th width="36%">Service</th><th width="13%" class="r">Billable</th><th width="7%" class="r">Fee %</th><th width="14%" class="r">Trata fee</th></tr></thead>
<tbody>{rows}</tbody></table><br/>
<table><tr><td width="55%" style="vertical-align:top;">
  <div class="h">Amount in words</div><b>{_inr_words(inv['grand_total'])}</b><br/><br/>
  {('<div class="h">Payment details</div><table class="box">' + bank + '</table>') if bank else ''}
  {('<br/><div class="h">Notes</div>' + e(inv.get('notes'))) if inv.get('notes') else ''}
 </td><td width="45%" style="vertical-align:top;"><table class="tot">
  <tr><td>Service fees</td><td class="r">{money(inv['service_fee'])}</td></tr>
  <tr><td>Marketing / promotion fees</td><td class="r">{money(inv['promotion_fee'])}</td></tr>
  <tr><td><b>Taxable value</b></td><td class="r"><b>{money(inv['taxable_value'])}</b></td></tr>
  {tax_rows}
  <tr class="grand"><td>Total payable</td><td class="r">{money(inv['grand_total'])}</td></tr>
 </table>{('<br/><div class="stamp r">&#10003; PAID</div>') if inv['status'] == 'paid' else ''}</td></tr></table>
<br/><br/><div class="foot">{e(s.get('terms'))}<br/>This is a computer-generated invoice from the Trata Health CRM and does not require a physical signature.</div>
</body></html>"""
