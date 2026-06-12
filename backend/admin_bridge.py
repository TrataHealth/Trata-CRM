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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


def _secret() -> str:
    return os.environ.get("ADMIN_CRM_WEBHOOK_SECRET", "")


def _admin_webhook_url() -> str:
    return os.environ.get("TRATA_ADMIN_WEBHOOK_URL", "")


def _admin_api_key() -> str:
    return os.environ.get("TRATA_ADMIN_API_KEY", "")

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
    "crm.activity.logged",
    "crm.deal.closed",
    "crm.note.added",
}

# Translation: our internal canonical event names → names that the Trata Admin App
# endpoint actually accepts. Their endpoint taxonomy as of 2026-06-12:
#   ping, lead.created, user.upsert, user.suspended, kyc.note_added, kyc.review_requested, deal.closed
OUTBOUND_NAME_MAP = {
    "crm.lead.created":    "lead.created",
    "crm.lead.assigned":   "user.upsert",       # lead reassignment = user record upsert in admin
    "crm.activity.logged": "user.upsert",       # touchpoint mirrors as user upsert in admin
    "crm.kyc.reviewed":    "kyc.note_added",    # reviewer's decision becomes a KYC note (needs kyc_id)
    "crm.deal.closed":     "deal.closed",
    "crm.note.added":      "user.upsert",       # general CRM note → user upsert (KYC-specific notes go via kyc.reviewed)
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


_bg_task: Optional[asyncio.Task] = None


def start_dispatcher(db):
    global _bg_task
    if _bg_task is None or _bg_task.done():
        _bg_task = asyncio.create_task(dispatcher_loop(db))
        logger.info("admin_bridge dispatcher started")


def stop_dispatcher():
    global _bg_task
    if _bg_task and not _bg_task.done():
        _bg_task.cancel()
        _bg_task = None
