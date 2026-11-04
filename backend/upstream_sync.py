"""
Upstream sync: pulls live data from the existing TrataHealth/Trata-admin backend
into the CRM's MongoDB mirror.

Activation: set UPSTREAM_API_URL (and optionally UPSTREAM_ADMIN_TOKEN) in backend/.env
and either trigger POST /api/admin/sync or let the background task run every
UPSTREAM_SYNC_INTERVAL_MIN minutes.

Mapping (upstream → CRM):
  /admin/users               → contacts (role=customer → patient, paramedic → paramedic, hospital → hospital,
                                doctor → doctor; ambulance_provider/pathologist via dedicated endpoints if exposed)
  /admin/recently-onboarded  → contacts (additional fields: specialization, deal hints)
  /admin/cases               → activities (category=emergency_case)
"""
from __future__ import annotations

import os
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_phone(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    p = str(p).strip().replace(" ", "")
    if p.startswith("+91"):
        p = p[3:]
    elif p.startswith("91") and len(p) > 10:
        p = p[2:]
    return p


ROLE_TO_TYPE = {
    "customer": "patient",
    "patient": "patient",
    "paramedic": "paramedic",
    "doctor": "doctor",
    "hospital": "hospital",
    "ambulance_provider": "ambulance_provider",
    "path_lab": "path_lab",
    "diagnostic_centre": "diagnostic_centre",
    "pathologist": "path_lab",
    "pathology": "path_lab",
}


class UpstreamSync:
    def __init__(self, db, base_url: str, token: Optional[str] = None, login_phone: Optional[str] = None, login_otp: Optional[str] = None):
        self.db = db
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.login_phone = login_phone
        self.login_otp = login_otp
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def _ensure_token(self):
        if self.token:
            return
        if not self.login_phone or not self.login_otp:
            return  # anonymous; admin endpoints in the upstream may allow unauthenticated calls
        try:
            await self.client.post(f"{self.base_url}/api/auth/send-otp", json={"phone": self.login_phone})
            r = await self.client.post(
                f"{self.base_url}/api/auth/verify-otp",
                json={"phone": self.login_phone, "otp": self.login_otp},
            )
            r.raise_for_status()
            data = r.json()
            self.token = data.get("token") or data.get("access_token")
            logger.info(f"Acquired upstream token: {bool(self.token)}")
        except Exception as e:
            logger.warning(f"Upstream login failed: {e}")

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _get(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        url = f"{self.base_url}{path}"
        try:
            r = await self.client.get(url, params=params, headers=self._headers())
            if r.status_code == 401 and self.login_phone:
                self.token = None
                await self._ensure_token()
                r = await self.client.get(url, params=params, headers=self._headers())
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Upstream GET {path} failed: {e}")
            return None

    # ------------------- mappers -------------------
    def _map_user_to_contact(self, u: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        role = u.get("role") or u.get("user_type")
        t = ROLE_TO_TYPE.get(role)
        if not t:
            return None
        phone = _norm_phone(u.get("phone"))
        if not phone:
            return None
        v_status = (u.get("verification_status") or "").lower()
        is_verified = v_status in ("verified", "approved") or bool(u.get("is_verified"))
        stage = "active" if is_verified else "kyc_submitted"
        if t == "patient":
            stage = "active"
        return {
            "id": str(u.get("id") or uuid.uuid4()),
            "name": u.get("name") or u.get("full_name") or u.get("business_name") or f"Unknown {t}",
            "type": t,
            "phone": phone,
            "email": u.get("email"),
            "city": (u.get("location") or {}).get("city") if isinstance(u.get("location"), dict) else u.get("city"),
            "state": u.get("state"),
            "lat": u.get("lat"),
            "lng": u.get("lng"),
            "specialization": u.get("specialization") or u.get("detail"),
            "avatar": u.get("avatar") or u.get("profile_image"),
            "pipeline_stage": stage,
            "is_verified": is_verified,
            "is_active": u.get("is_active", True),
            "deal_value": 0,
            "rating": u.get("rating"),
            "created_at": u.get("created_at") or _now_iso(),
            "_synced_at": _now_iso(),
            "_source": "upstream",
            "meta": {
                "license_number": u.get("license_number"),
                "experience_years": u.get("experience_years"),
                "patient_id": u.get("patient_id"),
                "verification_status": v_status or None,
            },
        }

    def _map_case_to_activity(self, c: Dict[str, Any], patients_by_id: Dict[str, Dict]) -> Dict[str, Any]:
        cust_id = c.get("customer_id") or c.get("user_id")
        patient = patients_by_id.get(cust_id) if cust_id else None
        loc = c.get("location") or {}
        return {
            "id": str(c.get("id") or uuid.uuid4()),
            "category": "emergency_case",
            "contact_id": cust_id,
            "contact_name": (patient or {}).get("name") or c.get("customer_phone") or "Patient",
            "contact_type": "patient",
            "city": (loc.get("city") if isinstance(loc, dict) else None) or (patient or {}).get("city"),
            "title": f"SOS: {c.get('reason') or c.get('case_type', 'Emergency')}",
            "description": c.get("reason") or "Emergency dispatch",
            "status": c.get("status") or "CREATED",
            "priority": c.get("priority") or "MEDIUM",
            "response_time_minutes": c.get("estimated_response_time"),
            "ambulance_provider_id": c.get("ambulance_provider_id"),
            "amount": 0,
            "created_at": c.get("created_at") or _now_iso(),
            "_synced_at": _now_iso(),
            "_source": "upstream",
        }

    # ------------------- sync entry point -------------------
    async def sync_all(self, wipe_seed: bool = True) -> Dict[str, Any]:
        await self._ensure_token()

        # 1) Users (paginate)
        all_users: List[Dict[str, Any]] = []
        for role in ["customer", "patient", "doctor", "paramedic", "hospital", "ambulance_provider", "path_lab", "diagnostic_centre"]:
            for skip in range(0, 2000, 200):
                data = await self._get("/api/admin/users", {"role": role, "skip": skip, "limit": 200})
                if not data:
                    break
                items = data.get("users") if isinstance(data, dict) else data
                if not items:
                    break
                all_users.extend(items)
                if len(items) < 200:
                    break

        # 2) Also pull recently-onboarded (richer detail)
        recent = await self._get("/api/admin/recently-onboarded", {"limit": 200})
        if isinstance(recent, list):
            all_users.extend(recent)

        if not all_users:
            logger.warning("Upstream sync: no users fetched; aborting")
            return {"success": False, "reason": "no_data_from_upstream"}

        # 3) Cases
        all_cases: List[Dict[str, Any]] = []
        for skip in range(0, 2000, 200):
            data = await self._get("/api/admin/cases", {"skip": skip, "limit": 200})
            if not data:
                break
            items = data.get("cases") if isinstance(data, dict) else data
            if not items:
                break
            all_cases.extend(items)
            if len(items) < 200:
                break

        # Map
        contacts: List[Dict[str, Any]] = []
        seen = set()
        for u in all_users:
            c = self._map_user_to_contact(u)
            if not c:
                continue
            key = (c["type"], c["phone"])
            if key in seen:
                continue
            seen.add(key)
            contacts.append(c)

        patients_by_id = {c["id"]: c for c in contacts if c["type"] == "patient"}
        activities = [self._map_case_to_activity(cs, patients_by_id) for cs in all_cases]

        # Replace
        if wipe_seed:
            await self.db.contacts.delete_many({})
            await self.db.activities.delete_many({})
            await self.db.notifications.delete_many({})

        if contacts:
            await self.db.contacts.insert_many([c.copy() for c in contacts])
        if activities:
            await self.db.activities.insert_many([a.copy() for a in activities])

        await self.db.sync_status.replace_one(
            {"_id": "upstream"},
            {
                "_id": "upstream",
                "last_synced_at": _now_iso(),
                "contacts": len(contacts),
                "activities": len(activities),
                "users_fetched": len(all_users),
                "cases_fetched": len(all_cases),
                "base_url": self.base_url,
                "ok": True,
            },
            upsert=True,
        )

        return {
            "success": True,
            "contacts": len(contacts),
            "activities": len(activities),
            "users_fetched": len(all_users),
            "cases_fetched": len(all_cases),
        }


# ------------------- module-level singleton + background task -------------------
_bg_task: Optional[asyncio.Task] = None


def upstream_enabled() -> bool:
    return bool(os.environ.get("UPSTREAM_API_URL"))


def make_sync(db) -> Optional[UpstreamSync]:
    if not upstream_enabled():
        return None
    return UpstreamSync(
        db=db,
        base_url=os.environ["UPSTREAM_API_URL"],
        token=os.environ.get("UPSTREAM_ADMIN_TOKEN") or None,
        login_phone=os.environ.get("UPSTREAM_LOGIN_PHONE") or None,
        login_otp=os.environ.get("UPSTREAM_LOGIN_OTP") or None,
    )


async def _bg_loop(db, interval_min: int):
    while True:
        try:
            s = make_sync(db)
            if s:
                logger.info("Running scheduled upstream sync…")
                res = await s.sync_all(wipe_seed=True)
                logger.info(f"Sync result: {res}")
                await s.close()
        except Exception as e:
            logger.exception(f"Background sync failed: {e}")
        await asyncio.sleep(interval_min * 60)


def start_background(db, interval_min: int = 5):
    global _bg_task
    if _bg_task and not _bg_task.done():
        return
    if not upstream_enabled():
        return
    _bg_task = asyncio.create_task(_bg_loop(db, interval_min))


def stop_background():
    global _bg_task
    if _bg_task:
        _bg_task.cancel()
        _bg_task = None
