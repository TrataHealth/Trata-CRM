"""Master-admin onboarding through the Provider app's own self-signup API (exact parity with app sign-ups)."""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import asyncio
import html as _html

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import emailer
import ledger_docs as docs
import supabase_db as sb

log = logging.getLogger("provider_onboard")
API = os.environ["PROVIDER_APP_API_URL"].rstrip("/")
SPECIALISED = ("cancer_care", "diabetes", "women_baby", "elderly_care", "skin_hair", "nursing_home")
# role id (as listed in the Provider app) -> (signup endpoint, select-role role, fixed payload extras)
ROLES: Dict[str, tuple] = {
    "hospital": ("hospital", "hospital", {}),
    **{r: ("hospital", "hospital", {"hospitalType": "specialised_centre"}) for r in SPECIALISED},
    "pathologist": ("pathologist", "pathologist", {"providerSubtype": "path_lab"}),
    "diagnostic_centre": ("pathologist", "pathologist", {"providerSubtype": "diagnostic_centre"}),
    "pharmacy": ("pharmacy", "pharmacy", {}),
    "doctor": ("doctor", "doctor", {}),
    "nurse": ("doctor", "doctor", {"subtype": "nurse"}),
    "mental_wellness": ("wellness", "wellness", {}),
    "nutritionist": ("nutritionist", "nutritionist", {}),
    "ambulance_provider": ("ambulance-provider", "ambulance_provider", {}),
    "ambulance_driver": ("ambulance-driver", "ambulance_driver", {}),
    "paramedic": ("paramedic", "paramedic", {}),
    "blood_bank": ("blood-bank", "blood_bank", {}),
    "wellness_event": ("wellness-event", "wellness_event", {}),
    "veterinarian": ("vet", "vet", {}),
    "dental": ("dental", "dental", {}),
}


CONTACT_TYPE = {**{r: "hospital" for r in SPECIALISED}, "mental_wellness": "wellness", "veterinarian": "vet"}
ROOT_BY_ROLE = {"hospital": "hospital", "pharmacy": "pharmacy", "pathologist": "path_lab", "diagnostic_centre": "diagnostic_centre"}


class OnboardBody(BaseModel):
    role_id: str
    phone: str = Field(..., pattern=r"^[6-9]\d{9}$")
    data: Dict[str, Any] = Field(default_factory=dict)


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
    except ValueError:
        return r.text[:200] or f"HTTP {r.status_code}"
    if isinstance(d, list):
        return "; ".join(f"{'.'.join(str(x) for x in e.get('loc', [])[1:])}: {e.get('msg')}" for e in d)
    return str(d or r.text[:200])


async def _welcome(to: Optional[str], name: str, role_label: str, phone: str, app_url: Optional[str]) -> str:
    if not to:
        return "no_email"
    body = (f"<h2 style='margin:0 0 8px;font-size:18px'>Welcome to Trata Health</h2><p style='font-size:14px'>Hello {_html.escape(name or 'there')},</p>"
            f"<p style='font-size:14px;line-height:20px'>Your <b>{_html.escape(role_label)}</b> account has been created on the Trata network. "
            f"Sign in to the Trata Provider app or the Trata CRM with your mobile number <b>{_html.escape(phone)}</b> using the one-time code we send you.</p>"
            "<p style='font-size:14px;background:#FFF4E5;border-left:3px solid #FF8B00;padding:10px'>Your account is <b>pending verification</b>. "
            "Please upload your KYC documents after signing in. You can start receiving patients once our team approves them.</p>"
            "<p style='font-size:13px;color:#42526E'>Questions? Reply to this email or contact your Trata relationship manager.</p>")
    try:
        await emailer.send_email(to=to, subject="Welcome to Trata Health — your provider account is ready",
                                 html=docs.email_shell(app_url, "WELCOME", body))
        return "sent"
    except Exception as ex:  # noqa: BLE001 — email failure must not undo onboarding
        log.warning("welcome email failed: %s", ex)
        return "failed"


async def _call(method: str, path: str, json: Optional[dict] = None):
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            res = await c.request(method, f"{API}{path}", json=json)
        except httpx.HTTPError as ex:
            raise HTTPException(status_code=502, detail=f"Provider app unreachable: {type(ex).__name__}")
    if res.status_code >= 300:
        raise HTTPException(status_code=400 if res.status_code < 500 else 502, detail=f"Provider app: {_detail(res)}")
    return res.json()


_ORGS: Dict[str, Dict[str, Any]] = {}
_TASKS: set = set()
BUSINESS_KEYS = ("name", "businessName", "labName", "clinicName", "bankName", "displayName")


async def _org_for_uid(uid: str, org_name: Optional[str] = None) -> Dict[str, Any]:
    if uid in _ORGS:
        return _ORGS[uid]
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        u = await conn.fetchrow("SELECT role, name, organization_name FROM public.users WHERE id::text = $1", uid)
    root = ROOT_BY_ROLE.get((u and u["role"]) or "")
    if not root:
        raise HTTPException(status_code=403, detail="Entities are available for hospitals, pharmacies, path labs and diagnostic centres")
    async with httpx.AsyncClient(timeout=30) as c:
        res = await c.get(f"{API}/api/org/by-admin/{uid}")
        org = (res.json() or {}).get("org") if res.status_code < 300 else None
    if not org:
        org = (await _call("POST", "/api/org/bootstrap", {"master_admin_user_id": uid, "root_kind": root,
                                                         "org_name": org_name or u["organization_name"] or u["name"] or "My Organisation"})).get("org")
    _ORGS[uid] = {**org, "root_kind": root}
    return _ORGS[uid]


def _entity_routes(r: APIRouter, prefix: str, resolve):
    """Registers list/create/update/delete entity routes; `resolve(current, contact_id)` returns the org."""
    @r.get(prefix)
    async def list_entities(contact_id: str = "", current=Depends(resolve.dep)):
        org = await resolve(current, contact_id)
        data = await _call("GET", f"/api/org/{org['id']}/entities")
        return {"org": org, "root_kind": org["root_kind"], "entities": data.get("entities", [])}

    @r.post(prefix)
    async def create_entity(body: "EntityBody", contact_id: str = "", current=Depends(resolve.dep)):
        org = await resolve(current, contact_id)
        if not (body.entity_kind and body.dedicated_phone and body.name and body.contact_person and body.address and body.city):
            raise HTTPException(status_code=400, detail="Type, name, admin/owner name, dedicated phone, address and city are required")
        return await _call("POST", f"/api/org/{org['id']}/entity", body.model_dump(exclude_none=True))

    @r.patch(prefix + "/{entity_id}")
    async def update_entity(entity_id: str, body: "EntityBody", contact_id: str = "", current=Depends(resolve.dep)):
        org = await resolve(current, contact_id)
        return await _call("PATCH", f"/api/org/{org['id']}/entity/{entity_id}",
                           body.model_dump(exclude_none=True, exclude={"entity_kind", "dedicated_phone"}))

    @r.delete(prefix + "/{entity_id}")
    async def delete_entity(entity_id: str, contact_id: str = "", current=Depends(resolve.dep)):
        org = await resolve(current, contact_id)
        return await _call("DELETE", f"/api/org/{org['id']}/entity/{entity_id}")


def create_provider_onboard_router(db, get_current_user, is_internal) -> APIRouter:
    r = APIRouter(prefix="/api/admin/provider-app")

    def require_staff(c):
        if not is_internal(c):
            raise HTTPException(status_code=403, detail="CRM staff only")

    @r.get("/entities")
    async def entities(kind: str, q: str = "", current=Depends(get_current_user)):
        require_staff(current)
        if kind == "ambulance_provider":
            pool = await sb.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("""SELECT id::text AS id, business_name AS name, city FROM public.ambulance_providers
                                           WHERE coalesce(business_name, '') ILIKE $1 ORDER BY 2 LIMIT 15""", f"%{q}%")
            return {"items": [dict(x) for x in rows]}
        if not q.strip():
            return {"items": []}
        async with httpx.AsyncClient(timeout=20) as c:
            res = await c.get(f"{API}/api/registered/hospitals-and-clinics", params={"q": q, "limit": 15})
        items = res.json() if res.status_code < 300 and isinstance(res.json(), list) else []
        return {"items": [{"id": i["id"], "name": i.get("name"), "city": i.get("city"), "type": i.get("type")}
                          for i in items if (i.get("type") or "hospital").lower() == kind]}

    async def run_job(job_id: str, body: OnboardBody, origin: str, current):
        try:
            result, status, error = await do_onboard(body, origin, current), "done", None
        except HTTPException as ex:
            result, status, error = None, "failed", str(ex.detail)
        except Exception as ex:  # noqa: BLE001
            log.exception("onboard job failed")
            result, status, error = None, "failed", f"Unexpected error: {type(ex).__name__}"
        await db.onboard_jobs.update_one({"id": job_id}, {"$set": {"status": status, "result": result, "error": error,
                                                                 "finished_at": datetime.now(timezone.utc).isoformat()}})

    @r.post("/onboard")
    async def onboard(body: OnboardBody, request: Request, current=Depends(get_current_user)):
        """Sign-ups on the Provider app can take ~1 min, so this runs as a job the UI polls."""
        require_staff(current)
        if body.role_id not in ROLES:
            raise HTTPException(status_code=400, detail="Unknown provider type")
        job_id = uuid.uuid4().hex
        await db.onboard_jobs.insert_one({"id": job_id, "by": current["id"], "role_id": body.role_id, "phone": body.phone,
                                          "status": "running", "created_at": datetime.now(timezone.utc).isoformat()})
        t = asyncio.create_task(run_job(job_id, body, request.headers.get("origin") or "", current))
        _TASKS.add(t)
        t.add_done_callback(_TASKS.discard)
        return {"job_id": job_id, "status": "running"}

    @r.get("/onboard/{job_id}")
    async def onboard_status(job_id: str, current=Depends(get_current_user)):
        require_staff(current)
        j = await db.onboard_jobs.find_one({"id": job_id}, {"_id": 0})
        if not j or (j["by"] != current["id"] and not current.get("is_master_admin")):
            raise HTTPException(status_code=404, detail="Job not found")
        if j["status"] == "running" and (datetime.now(timezone.utc) - datetime.fromisoformat(j["created_at"])).total_seconds() > 300:
            j.update(status="failed", error="Onboarding was interrupted. Check Contacts, then try again if the provider is missing.")
            await db.onboard_jobs.update_one({"id": job_id}, {"$set": {"status": "failed", "error": j["error"]}})
        return j

    async def do_onboard(body: OnboardBody, origin: str, current):
        endpoint, role, extra = ROLES[body.role_id]
        payload = {k: v for k, v in {**body.data, **extra, "phone": body.phone}.items() if v not in ("", None)}
        if body.role_id in SPECIALISED:
            payload.setdefault("specializations", [body.role_id])
        pool = await sb.get_pool()

        async def find_user():
            async with pool.acquire() as conn:
                return await conn.fetchrow("SELECT id::text AS id, name, role FROM public.users WHERE phone = $1 ORDER BY created_at DESC LIMIT 1", body.phone)
        out = {}
        async with httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10)) as c:
            try:
                res = await c.post(f"{API}/api/self-signup/{endpoint}", json=payload)
                if res.status_code >= 300 or (res.json() or {}).get("success") is False:
                    raise HTTPException(status_code=400, detail=f"Provider app: {_detail(res)}")
                out = res.json()
            except httpx.TimeoutException:
                # Some sign-ups (e.g. hospitals) are slow upstream; the account is usually created already.
                if not await find_user():
                    raise HTTPException(status_code=504, detail="Provider app is taking too long. Please try again in a minute.")
            except httpx.HTTPError as ex:
                raise HTTPException(status_code=502, detail=f"Provider app unreachable: {type(ex).__name__}")
            try:
                rr = await c.post(f"{API}/api/auth/select-role", json={"phone": body.phone, "role": role}, timeout=10)
                role_ok = rr.status_code < 300
            except httpx.HTTPError:
                role_ok = False
        u = await find_user()
        uid = u["id"] if u else None
        now = datetime.now(timezone.utc).isoformat()
        person = payload.get("fullName") or payload.get("ownerName") or payload.get("inchargeName") or payload.get("organiserName")
        name = next((payload[k] for k in BUSINESS_KEYS if payload.get(k)), None) or (u and u["name"]) or person
        agent = {"assigned_agent_id": current["id"], "assigned_agent_name": current.get("name")} if current.get("role") == "sales_rep" else {}
        contact = await db.contacts.find_one_and_update(
            {"$or": [{"supabase_user_id": uid}, {"phone": body.phone}]} if uid else {"phone": body.phone},
            {"$set": {"supabase_user_id": uid, "name": name, "phone": body.phone, "email": payload.get("email"),
                      "contact_person": person, "city": payload.get("city"), "state": payload.get("state"), "address": payload.get("address"),
                      "type": CONTACT_TYPE.get(body.role_id, body.role_id), "provider_type": (u and u["role"]) or role,
                      "provider_app_role": body.role_id, "pipeline_stage": "contacted", "kyc_status": "pending",
                      "is_verified": False, "onboarded_via": "crm", "onboarded_by": current.get("name"), "onboarded_at": now,
                      "updated_at": now, **agent},
             "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": now, "source": "crm_admin_onboarded", "deal_value": 0}},
            upsert=True, return_document=True, projection={"_id": 0, "id": 1})
        label = body.role_id.replace("_", " ").title()
        email_status = await _welcome(payload.get("email"), name, label, body.phone, origin if origin.startswith("https://") else None)
        await db.activities.insert_one({"id": str(uuid.uuid4()), "type": "note", "category": "kyc", "subtype": "provider_onboarded",
                                        "title": f"Onboarded {label} — {name}", "contact_id": contact["id"], "contact_name": name,
                                        "description": f"Created via the Provider app sign-up flow by {current.get('name')}. KYC pending.",
                                        "agent_id": current.get("id"), "agent_name": current.get("name"), "status": "completed", "created_at": now})
        await db.audit_log.insert_one({"id": uuid.uuid4().hex, "action": "provider.onboard_via_app", "by": current.get("id"),
                                       "role_id": body.role_id, "phone": body.phone, "supabase_user_id": uid,
                                       "at": now, "role_selected": role_ok, "welcome_email": email_status})
        return {"success": True, "supabase_user_id": uid, "contact_id": contact["id"], "role": role, "role_selected": role_ok,
                "status": "pending_kyc", "welcome_email": email_status,
                "message": out.get("message") or "Provider onboarded", "login_hint": f"Sign in on the Provider app or CRM with {body.phone} (OTP)"}

    async def contact_org(current, contact_id: str):
        require_staff(current)
        c = await db.contacts.find_one({"id": contact_id}, {"_id": 0, "supabase_user_id": 1, "assigned_agent_id": 1, "name": 1})
        if not c:
            raise HTTPException(status_code=404, detail="Contact not found")
        if not current.get("is_master_admin") and c.get("assigned_agent_id") != current["id"]:
            raise HTTPException(status_code=403, detail="Only the master admin or the assigned sales agent can manage entities")
        if not c.get("supabase_user_id"):
            raise HTTPException(status_code=400, detail="This provider is not linked to the Trata network yet")
        return await _org_for_uid(c["supabase_user_id"], c.get("name"))
    contact_org.dep = get_current_user
    _entity_routes(r, "/contact-entities", contact_org)
    return r


class EntityBody(BaseModel):
    entity_kind: Optional[str] = None
    dedicated_phone: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")
    name: Optional[str] = Field(None, max_length=200)
    contact_person: Optional[str] = Field(None, max_length=120)
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = Field(None, pattern=r"^\d{6}$")
    gst_number: Optional[str] = None
    pan_number: Optional[str] = None
    license_number: Optional[str] = None
    dispatch_radius_km: Optional[float] = Field(None, ge=0, le=200)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


def create_entities_router(db, get_current_user, is_provider) -> APIRouter:
    """Provider account owners manage their own internal entities (proxies the Provider app's /api/org/* API)."""
    r = APIRouter(prefix="/api/provider")

    async def own_org(current, _key: str):
        if not is_provider(current) or current.get("staff_role"):
            raise HTTPException(status_code=403, detail="Only the provider account owner can manage entities")
        if not current.get("supabase_user_id"):
            raise HTTPException(status_code=400, detail="Account not linked to the Trata network yet")
        return await _org_for_uid(current["supabase_user_id"])
    own_org.dep = get_current_user
    _entity_routes(r, "/entities", own_org)
    return r
