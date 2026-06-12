"""
Trata-admin <-> CRM bridge.

- Inbound: receives 7 event types from the Trata Admin App at /api/webhooks/admin-app.
- Outbound: emits 6 event types from the CRM to the admin app (signed HMAC POSTs).
- Idempotency: every event carries an `id`; dedupe through the `admin_bridge_events` collection.
- Retries: failed outbound sends are queued in `admin_bridge_outbound` and retried by a
  background task with exponential backoff (capped at 6 attempts).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


def _secret() -> str:
    return os.environ.get("ADMIN_CRM_WEBHOOK_SECRET", "")


def _admin_webhook_url() -> str:
    return os.environ.get("TRATA_ADMIN_WEBHOOK_URL", "")


def _admin_api_key() -> str:
    return os.environ.get("TRATA_ADMIN_API_KEY", "")


def _admin_api_url() -> str:
    return os.environ.get("TRATA_ADMIN_API_URL", "").rstrip("/")


async def admin_api_get(path: str) -> Optional[Dict[str, Any]]:
    """Authenticated GET to the Trata Admin App. Returns parsed JSON or None on failure."""
    base = _admin_api_url()
    key = _admin_api_key()
    if not base or not key:
        return None
    url = base + (path if path.startswith("/") else "/" + path)
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 200:
            return r.json()
        logger.warning(f"admin_api_get {path} -> {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"admin_api_get {path} failed: {e}")
    return None


async def find_admin_user_by_phone(phone: str) -> Optional[Dict[str, Any]]:
    """Look up an admin-app user by phone. Strips +91/spaces on both sides; if multiple users share
    the same 10-digit phone (e.g. patient + provider), prefer the provider role."""
    payload = await admin_api_get("/api/admin/users")
    if not payload:
        return None

    def norm(p: Optional[str]) -> str:
        s = "".join(ch for ch in (p or "") if ch.isdigit())
        if len(s) == 12 and s.startswith("91"):
            s = s[2:]
        return s

    target = norm(phone)
    matches = [u for u in payload.get("users", []) if norm(u.get("phone")) == target]
    if not matches:
        return None
    # Prefer provider/agent roles over customer/patient/null
    priority = {"ambulance_provider": 0, "hospital": 1, "paramedic": 1, "doctor": 1, "lab": 1, "pharmacy": 1, "agent": 2, "customer": 8, "patient": 9, None: 10}
    matches.sort(key=lambda u: priority.get(u.get("role"), 5))
    return matches[0]


async def fetch_cases() -> Optional[Dict[str, Any]]:
    """Fetch all emergency cases from the Trata Admin App."""
    return await admin_api_get("/api/admin/cases")


async def fetch_network_stats() -> Optional[Dict[str, Any]]:
    """Fetch network-wide stats (users/cases/EHR/HealthGuard) from the Trata Admin App."""
    return await admin_api_get("/api/admin/stats")


async def fetch_ambulance_providers() -> Optional[List[Dict[str, Any]]]:
    """Fetch business records for every ambulance provider (registration #, GST, owner, etc.)."""
    payload = await admin_api_get("/api/admin/ambulance-providers")
    # This endpoint historically returns a bare list, not a {providers: [...]} object.
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return payload.get("providers") or payload.get("items") or []
    return None


async def fetch_kyc(user_id: str) -> Optional[Dict[str, Any]]:
    return await admin_api_get(f"/api/admin/users/{user_id}/kyc")

INBOUND_EVENTS = {
    "provider.signed_up",
    "provider.first_use",
    "provider.kyc.submitted",
    "provider.kyc.updated",
    "provider.deactivated",
    "provider.profile.updated",
    "payout.processed",
}

OUTBOUND_EVENTS = {
    "crm.lead.created",
    "crm.lead.assigned",
    "crm.kyc.reviewed",
    "crm.kyc.doc_reviewed",
    "crm.kyc.agent_completed",
    "crm.kyc.admin_verified",
    "crm.kyc.ai_prescreened",
    "crm.activity.logged",
    "crm.deal.closed",
    "crm.note.added",
}

# Translation: our internal canonical event names → names that the Trata Admin App
# endpoint actually accepts. Their endpoint taxonomy as of 2026-06-12:
#   ping, lead.created, user.upsert, user.suspended, kyc.note_added, kyc.review_requested, deal.closed
OUTBOUND_NAME_MAP = {
    "crm.lead.created":         "lead.created",
    "crm.lead.assigned":        "user.upsert",
    "crm.activity.logged":      "user.upsert",
    "crm.kyc.reviewed":         "kyc.note_added",
    "crm.kyc.doc_reviewed":     "kyc.note_added",
    "crm.kyc.agent_completed":  "kyc.review_requested",   # signals admin to do final review
    "crm.kyc.admin_verified":   "kyc.note_added",          # final master-admin verification
    "crm.kyc.ai_prescreened":   "kyc.note_added",          # AI doc-screen recommendation
    "crm.deal.closed":          "deal.closed",
    "crm.note.added":           "user.upsert",
}

MAX_ATTEMPTS = 6


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sign_payload(raw: bytes) -> str:
    """Returns bare HMAC-SHA256 hex digest (admin app expects no `sha256=` prefix)."""
    return hmac.new(_secret().encode("utf-8"), raw, hashlib.sha256).hexdigest()


def verify_signature(raw: bytes, signature_header: Optional[str]) -> bool:
    """Accepts either bare hex or `sha256=<hex>` for compatibility."""
    secret = _secret()
    if not secret or not signature_header:
        return False
    sig = signature_header.strip()
    if sig.startswith("sha256="):
        sig = sig[len("sha256="):]
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


async def queue_outbound(db, event: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Enqueue an outbound event. Returns the queued record."""
    if event not in OUTBOUND_EVENTS:
        logger.warning(f"queue_outbound: unknown event '{event}' — not queued")
        return {"queued": False, "reason": "unknown_event"}
    record = {
        "id": str(uuid.uuid4()),
        "event": event,
        "data": data,
        "status": "pending",
        "attempts": 0,
        "last_error": None,
        "created_at": _now(),
        "next_attempt_at": _now(),
        "sent_at": None,
    }
    await db.admin_bridge_outbound.insert_one(record.copy())
    record.pop("_id", None)
    # Fire-and-forget — dispatcher will pick it up on next tick.
    asyncio.create_task(_send_one(db, record["id"]))
    return record


async def _send_one(db, record_id: str) -> bool:
    url = _admin_webhook_url()
    secret = _secret()
    if not url or not secret:
        await db.admin_bridge_outbound.update_one(
            {"id": record_id},
            {"$set": {"status": "skipped", "last_error": "TRATA_ADMIN_WEBHOOK_URL or secret not configured"}},
        )
        return False
    rec = await db.admin_bridge_outbound.find_one({"id": record_id}, {"_id": 0})
    if not rec or rec.get("status") in ("sent", "skipped"):
        return False
    # Translate our internal name to admin app's expected event name.
    upstream_event = OUTBOUND_NAME_MAP.get(rec["event"], rec["event"])
    payload = {
        "event": upstream_event,
        "id": rec["id"],
        "timestamp": _now(),
        "data": {**rec["data"], "crm_event": rec["event"]},  # preserve original name for traceability
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = sign_payload(raw)
    headers = {
        "Content-Type": "application/json",
        # Send signature under both header names — admin app uses X-CRM-Signature,
        # we use X-Trata-Signature on our inbound. Both safely point to the same HMAC.
        "X-CRM-Signature": signature,
        "X-Trata-Signature": signature,
    }
    api_key = _admin_api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    attempts = rec.get("attempts", 0) + 1
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, content=raw, headers=headers)
        if r.status_code in (200, 201, 202, 204) or r.status_code == 409:
            # 409 = duplicate, treated as already-delivered
            await db.admin_bridge_outbound.update_one(
                {"id": record_id},
                {"$set": {
                    "status": "sent",
                    "attempts": attempts,
                    "sent_at": _now(),
                    "last_error": None,
                    "last_status_code": r.status_code,
                }},
            )
            return True
        err = f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        err = str(e)[:200]

    # Failure path — exponential backoff
    backoff_seconds = min(2 ** attempts, 300)
    next_at = datetime.now(timezone.utc).timestamp() + backoff_seconds
    next_at_iso = datetime.fromtimestamp(next_at, tz=timezone.utc).isoformat()
    final = attempts >= MAX_ATTEMPTS
    await db.admin_bridge_outbound.update_one(
        {"id": record_id},
        {"$set": {
            "status": "failed" if final else "retrying",
            "attempts": attempts,
            "last_error": err,
            "next_attempt_at": next_at_iso,
        }},
    )
    logger.warning(f"admin_bridge: send {rec['event']} attempt {attempts} failed: {err}")
    return False


async def dispatcher_loop(db, interval_seconds: int = 30):
    """Background loop: every N seconds, retry any pending/retrying events whose next_attempt_at <= now."""
    while True:
        try:
            now_iso = _now()
            pending = await db.admin_bridge_outbound.find(
                {"status": {"$in": ["pending", "retrying"]}, "next_attempt_at": {"$lte": now_iso}},
                {"_id": 0, "id": 1},
            ).to_list(50)
            for p in pending:
                await _send_one(db, p["id"])
        except Exception as e:
            logger.error(f"admin_bridge dispatcher tick failed: {e}")
        await asyncio.sleep(interval_seconds)


# ---------- Periodic user sync from /api/admin/users ----------
USER_SYNC_INTERVAL_SECONDS = 300   # 5 min


def _normalize_phone(p: Optional[str]) -> str:
    s = "".join(ch for ch in (p or "") if ch.isdigit())
    if len(s) == 12 and s.startswith("91"):
        s = s[2:]
    return s


async def sync_users_from_admin(db) -> Dict[str, int]:
    """Pull /api/admin/users from the admin app and upsert healthcare-provider records as CRM contacts.
    Includes ambulance_provider, hospital, doctor, paramedic, lab/pathologist, pharmacy.
    Existing contacts get a metadata refresh; never overwrites pipeline_stage or assigned_agent_id."""
    PROVIDER_ROLES = {"ambulance_provider", "hospital", "doctor", "paramedic", "lab", "pathologist", "pharmacy"}
    # Map upstream role → CRM contact type (CRM uses 'pathologist' for labs)
    ROLE_TO_TYPE = {"lab": "pathologist"}
    payload = await admin_api_get("/api/admin/users")
    if not payload:
        return {"fetched": 0, "created": 0, "updated": 0, "skipped": 0}
    users = payload.get("users", [])
    created = 0
    updated = 0
    skipped = 0
    for u in users:
        role = u.get("role")
        if role not in PROVIDER_ROLES:
            skipped += 1
            continue
        contact_type = ROLE_TO_TYPE.get(role, role)
        phone = _normalize_phone(u.get("phone"))
        if not phone:
            skipped += 1
            continue
        existing = await db.contacts.find_one({"phone": phone}, {"_id": 0, "id": 1, "name": 1, "city": 1, "type": 1})
        if existing:
            # Refresh metadata only — never clobber pipeline_stage / assigned_agent / KYC
            patch = {}
            if u.get("name") and u["name"] != existing.get("name"): patch["name"] = u["name"]
            if u.get("city") and u["city"] != existing.get("city"): patch["city"] = u["city"]
            # If a contact was previously typed differently (e.g. defaulted), correct it to the upstream role
            if existing.get("type") != contact_type: patch["type"] = contact_type
            patch["upstream_user_id"] = u["id"]
            patch["last_admin_sync_at"] = _now()
            await db.contacts.update_one({"id": existing["id"]}, {"$set": patch})
            updated += 1
        else:
            # Fresh import — auto-assign by territory using same logic as webhook
            from server import _pick_agent_for_territory  # type: ignore
            agent = await _pick_agent_for_territory(u.get("city"))
            new_doc = {
                "id": str(uuid.uuid4()),
                "name": u.get("name") or f"Provider {phone}",
                "type": contact_type,
                "phone": phone,
                "city": u.get("city"),
                "state": u.get("state"),
                "is_verified": u.get("verification_status") == "verified",
                "is_active": False,
                "pipeline_stage": "verified" if u.get("verification_status") == "verified" else "lead",
                "deal_value": 0,
                "assigned_agent_id": agent["id"] if agent else None,
                "assigned_agent_name": agent["name"] if agent else None,
                "source": "admin_users_sync",
                "upstream_user_id": u["id"],
                "last_admin_sync_at": _now(),
                "created_at": _now(),
                "updated_at": _now(),
                "avatar": None,
            }
            await db.contacts.insert_one(new_doc)
            created += 1
    logger.info(f"sync_users_from_admin: fetched={len(users)} created={created} updated={updated} skipped={skipped}")
    return {"fetched": len(users), "created": created, "updated": updated, "skipped": skipped}


async def user_sync_loop(db, interval_seconds: int = USER_SYNC_INTERVAL_SECONDS):
    # Wait 30s after boot before first run so the rest of the app is ready
    await asyncio.sleep(30)
    while True:
        try:
            await sync_users_from_admin(db)
        except Exception as e:
            logger.error(f"user_sync tick failed: {e}")
        await asyncio.sleep(interval_seconds)


# ---------- Auto-escalation ----------
ESCALATION_INTERVAL_SECONDS = 900  # 15 min
SLA_REP_HOURS = 36   # nudge manager when sales rep hasn't moved in 36h
SLA_ADMIN_HOURS = 24 # email master admin when his queue item is >24h old


async def _send_resend_email(to_email: str, subject: str, html: str, text: str) -> bool:
    """Send email via Resend if configured. Returns True on success."""
    try:
        import os as _os
        key = _os.environ.get("RESEND_API_KEY", "")
        sender = _os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
        if not key:
            return False
        import resend
        resend.api_key = key
        result = await asyncio.to_thread(
            resend.Emails.send,
            {"from": f"Trata Health CRM <{sender}>", "to": [to_email], "subject": subject, "html": html, "text": text},
        )
        logger.info(f"escalation email sent: {result if isinstance(result, dict) else 'ok'}")
        return True
    except Exception as e:
        logger.warning(f"escalation email failed: {e}")
        return False


async def escalation_loop(db, interval_seconds: int = ESCALATION_INTERVAL_SECONDS):
    await asyncio.sleep(60)
    while True:
        try:
            now = datetime.now(timezone.utc)
            rep_cutoff = (now - timedelta(hours=SLA_REP_HOURS)).isoformat()
            admin_cutoff = (now - timedelta(hours=SLA_ADMIN_HOURS)).isoformat()
            # --- Sales rep overdue: notify their manager ---
            async for c in db.contacts.find({
                "kyc_status": {"$in": [None, "pending", "in_review", "kyc_submitted", "agent_doc_reviewing"]},
                "assigned_agent_id": {"$ne": None},
                "created_at": {"$lt": rep_cutoff},
                "escalation_rep_at": {"$exists": False},
                "type": {"$in": ["ambulance_provider", "hospital", "doctor", "paramedic", "pathologist", "pharmacy"]},
            }):
                agent = await db.crm_users.find_one({"id": c["assigned_agent_id"]}, {"_id": 0, "id": 1, "name": 1, "reports_to": 1})
                if not agent:
                    continue
                manager = None
                if agent.get("reports_to"):
                    manager = await db.crm_users.find_one({"id": agent["reports_to"]}, {"_id": 0, "id": 1, "name": 1, "email": 1})
                hours = int((now - datetime.fromisoformat(c["created_at"].replace("Z", "+00:00") if c["created_at"].endswith("Z") else c["created_at"])).total_seconds() / 3600)
                msg = f"{c.get('name')} has been with {agent.get('name')} for {hours}h without KYC submission."
                await db.notifications.insert_one({
                    "id": str(uuid.uuid4()),
                    "kind": "kyc_rep_escalation",
                    "title": f"Stale lead — {c.get('name')}",
                    "body": msg,
                    "audience": "manager" if manager else "admin",
                    "manager_id": manager.get("id") if manager else None,
                    "contact_id": c["id"],
                    "created_at": _now(),
                    "read": False,
                })
                await db.contacts.update_one({"id": c["id"]}, {"$set": {"escalation_rep_at": _now()}})
                logger.info(f"escalation: rep stale on {c.get('name')} → {manager.get('name') if manager else 'admin'}")
            # --- Admin queue overdue: email master admin ---
            async for c in db.contacts.find({
                "kyc_status": "agent_reviewed",
                "kyc_agent_completed_at": {"$lt": admin_cutoff},
                "escalation_admin_at": {"$exists": False},
            }):
                admin = await db.crm_users.find_one({"is_master_admin": True}, {"_id": 0, "recovery_email": 1, "email": 1, "name": 1})
                to = (admin or {}).get("recovery_email") or (admin or {}).get("email")
                hours = int((now - datetime.fromisoformat(c["kyc_agent_completed_at"].replace("Z","+00:00") if c["kyc_agent_completed_at"].endswith("Z") else c["kyc_agent_completed_at"])).total_seconds() / 3600)
                subject = f"⏰ KYC awaiting your final approval — {c.get('name')} ({hours}h overdue)"
                html = f"""
                <p>Hi {(admin or {}).get('name') or 'Master Admin'},</p>
                <p><b>{c.get('name')}</b>'s KYC has been sitting in your Final Approval queue for <b>{hours} hours</b>.</p>
                <p>Sales rep summary: {c.get('kyc_agent_summary', {}).get('approved', 0)} approved · {c.get('kyc_agent_summary', {}).get('rejected', 0)} rejected.</p>
                <p><a href="https://patient-hub-133.preview.emergentagent.com/admin/kyc-queue">Open the queue →</a></p>
                <hr>
                <small>Trata Health CRM · automated escalation</small>
                """
                text = f"{c.get('name')}'s KYC has been pending your final approval for {hours}h. Open the queue: https://patient-hub-133.preview.emergentagent.com/admin/kyc-queue"
                sent = False
                if to:
                    sent = await _send_resend_email(to, subject, html, text)
                await db.notifications.insert_one({
                    "id": str(uuid.uuid4()),
                    "kind": "kyc_admin_escalation",
                    "title": f"⏰ KYC overdue — {c.get('name')}",
                    "body": f"{hours}h waiting for your final approval. {'Email sent.' if sent else 'Email could not be sent.'}",
                    "audience": "admin",
                    "contact_id": c["id"],
                    "created_at": _now(),
                    "read": False,
                })
                await db.contacts.update_one({"id": c["id"]}, {"$set": {"escalation_admin_at": _now(), "escalation_email_sent": sent}})
                logger.info(f"escalation: admin overdue on {c.get('name')} (email sent={sent})")
        except Exception as e:
            logger.error(f"escalation tick failed: {e}")
        await asyncio.sleep(interval_seconds)


_bg_task: Optional[asyncio.Task] = None
_sync_task: Optional[asyncio.Task] = None
_esc_task: Optional[asyncio.Task] = None


def start_dispatcher(db):
    global _bg_task, _sync_task, _esc_task
    if _bg_task is None or _bg_task.done():
        _bg_task = asyncio.create_task(dispatcher_loop(db))
        logger.info("admin_bridge dispatcher started")
    if _sync_task is None or _sync_task.done():
        _sync_task = asyncio.create_task(user_sync_loop(db))
        logger.info("admin_users sync loop started (5min interval)")
    if _esc_task is None or _esc_task.done():
        _esc_task = asyncio.create_task(escalation_loop(db))
        logger.info("escalation loop started (15min interval)")


def stop_dispatcher():
    global _bg_task, _sync_task, _esc_task
    for t in (_bg_task, _sync_task, _esc_task):
        if t and not t.done():
            t.cancel()
    _bg_task = _sync_task = _esc_task = None
