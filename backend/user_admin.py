"""Master-admin bulk user actions: suspend / unsuspend / archive (30-day) / restore, plus auto-erase cron."""
from __future__ import annotations

import hmac
import math
import html as _html
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import emailer
import ledger_docs as docs
import supabase_db as sb

log = logging.getLogger("user_admin")
ARCHIVE_DAYS = 30
_BG: set = set()
ALLOWED_WHILE_SUSPENDED = ("/api/auth/me", "/api/auth/logout", "/api/auth/refresh")
SUSPENSION_DDL = """
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_suspended BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS suspended_reason TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS suspended_by TEXT;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS purge_after TIMESTAMPTZ;
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BulkBody(BaseModel):
    contact_ids: List[str] = Field(default_factory=list, max_length=500)
    user_ids: List[str] = Field(default_factory=list, max_length=500)
    action: Literal["suspend", "unsuspend", "archive", "restore"]
    reason: Optional[str] = Field(None, max_length=500)


def create_user_admin_router(db, get_current_user, master_phones) -> Dict[str, Any]:
    r = APIRouter(prefix="/api")

    def require_master(c):
        if not c.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")

    async def ensure_schema():
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(SUSPENSION_DDL)

    async def notify(contact: Dict[str, Any], suspended: bool, reason: Optional[str], app_url: Optional[str]):
        bp = await db.billing_profiles.find_one({"provider_user_id": contact.get("supabase_user_id")}, {"_id": 0, "email": 1}) or {}
        to = bp.get("email") or contact.get("email")
        name = _html.escape(contact.get("name") or "there")
        if suspended:
            subject = "Your Trata Health account has been suspended"
            body = (f"<h2 style='margin:0 0 8px;font-size:18px'>Account suspended</h2><p style='font-size:14px'>Hello {name},</p>"
                    "<p style='font-size:14px;line-height:20px'>Your Trata Health account has been suspended. Until it is restored you "
                    "won't be able to use the Trata Provider app, TrataX or the Trata CRM.</p>"
                    f"<p style='font-size:14px;background:#FFF4E5;border-left:3px solid #FF8B00;padding:10px'><b>Reason:</b> {_html.escape(reason or '')}</p>"
                    "<p style='font-size:13px;color:#42526E'>If you think this is a mistake, please contact your Trata relationship manager.</p>")
        else:
            subject = "Your Trata Health account is active again"
            body = (f"<h2 style='margin:0 0 8px;font-size:18px'>Account restored</h2><p style='font-size:14px'>Hello {name},</p>"
                    "<p style='font-size:14px;line-height:20px'>Your Trata Health account suspension has been lifted. You can use the "
                    "Trata Provider app, TrataX and the Trata CRM again.</p>")
        await db.notifications.insert_one({"id": os.urandom(8).hex(), "user_id": contact.get("supabase_user_id"), "provider_id": contact.get("id"),
                                           "kind": "account_suspended" if suspended else "account_restored", "title": subject,
                                           "message": reason or subject, "read": False, "created_at": _now()})
        if not to:
            return "no_email_on_file"
        try:
            await emailer.send_email(to=to, subject=subject, html=docs.email_shell(app_url, "ACCOUNT NOTICE", body))
            return "sent"
        except Exception as ex:  # noqa: BLE001 — email failure must not undo the action
            log.warning("suspension email failed: %s", ex)
            return "failed"

    async def contacts_for_users(user_ids: List[str]) -> List[str]:
        """Patient / Provider directory rows are users.id — map them to CRM contacts, creating a plain one if missing."""
        raw = getattr(db, "_db", db).contacts
        found = await raw.find({"$or": [{"supabase_user_id": {"$in": user_ids}}, {"upstream_user_id": {"$in": user_ids}}]},
                               {"_id": 0, "id": 1, "supabase_user_id": 1, "upstream_user_id": 1}).to_list(2000)
        have = {c.get("supabase_user_id") for c in found} | {c.get("upstream_user_id") for c in found}
        missing = [u for u in user_ids if u not in have]
        ids = [c["id"] for c in found]
        if missing:
            pool = await sb.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch("SELECT id, name, phone, email, role FROM public.users WHERE id = ANY($1::text[])", missing)
            for u in rows:
                cid = str(uuid.uuid4())
                await raw.insert_one({"id": cid, "name": u["name"], "phone": (u["phone"] or "")[-10:], "email": u["email"],
                                      "type": u["role"] or "patient", "supabase_user_id": u["id"], "upstream_user_id": u["id"],
                                      "source": "directory_bulk", "created_at": _now(), "updated_at": _now()})
                ids.append(cid)
        return ids

    @r.post("/admin/users/bulk")
    async def bulk(body: BulkBody, request: Request, current=Depends(get_current_user)):
        require_master(current)
        reason = (body.reason or "").strip()
        if body.action in ("suspend", "archive") and len(reason) < 5:
            raise HTTPException(status_code=400, detail="Please give a reason (at least 5 characters)")
        if not body.contact_ids and not body.user_ids:
            raise HTTPException(status_code=400, detail="Select at least one user")
        contact_ids = list(body.contact_ids) + (await contacts_for_users(body.user_ids) if body.user_ids else [])
        q = {"id": {"$in": contact_ids}}
        if body.action == "restore":
            q["archived"] = True
        contacts = await db.contacts.find(q, {"_id": 0}).to_list(500)
        skipped, done = [], []
        for c in contacts:
            if (c.get("phone") or "")[-10:] in master_phones or (current.get("supabase_user_id") and c.get("supabase_user_id") == current.get("supabase_user_id")):
                skipped.append({"id": c["id"], "name": c.get("name"), "why": "Trata Health Admin / yourself"})
                continue
            done.append(c)
        uids = [c["supabase_user_id"] for c in done if c.get("supabase_user_id")]
        ids, phones = [c["id"] for c in done], [c["phone"] for c in done if c.get("phone")]
        by = current.get("name") or current.get("phone")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            if body.action == "suspend":
                await conn.execute("""UPDATE public.users SET is_suspended = TRUE, suspended_at = now(), suspended_reason = $2,
                                      suspended_by = $3, updated_at = now() WHERE id = ANY($1::text[])""", uids, reason, by)
            elif body.action == "unsuspend":
                await conn.execute("""UPDATE public.users SET is_suspended = FALSE, suspended_at = NULL, suspended_reason = NULL,
                                      suspended_by = NULL, updated_at = now() WHERE id = ANY($1::text[])""", uids)
            elif body.action == "archive":
                await conn.execute("""UPDATE public.users SET is_archived = TRUE, is_active = FALSE, archived_at = now(),
                                      archived_reason = $2, purge_after = now() + interval '30 days', updated_at = now()
                                      WHERE id = ANY($1::text[])""", uids, f"admin_deleted: {reason}"[:50])
            else:
                await conn.execute("""UPDATE public.users SET is_archived = FALSE, is_active = TRUE, archived_at = NULL,
                                      archived_reason = NULL, purge_after = NULL, updated_at = now()
                                      WHERE id = ANY($1::text[]) AND coalesce(archived_reason, '') LIKE 'admin_deleted%'""", uids)
        purge_at = (datetime.now(timezone.utc) + timedelta(days=ARCHIVE_DAYS)).isoformat()
        susp = {"suspended": True, "suspended_at": _now(), "suspended_reason": reason, "suspended_by": by}
        unsusp = {"suspended": False, "suspended_at": None, "suspended_reason": None, "suspended_by": None}
        cset = {"suspend": susp, "unsuspend": unsusp,
                "archive": {"archived": True, "archived_at": _now(), "archived_reason": reason, "archived_by": by, "purge_after": purge_at},
                "restore": {"archived": False, "archived_at": None, "archived_reason": None, "archived_by": None, "purge_after": None}}[body.action]
        await db.contacts.update_many({"id": {"$in": ids}}, {"$set": cset})
        uq = {"$or": [{"provider_id": {"$in": ids}}, {"supabase_user_id": {"$in": uids}}, {"phone": {"$in": phones}}], "is_master_admin": {"$ne": True}}
        if body.action in ("suspend", "unsuspend"):
            await db.crm_users.update_many(uq, {"$set": susp if body.action == "suspend" else unsusp})
        else:
            await db.crm_users.update_many(uq, {"$set": {"disabled": body.action == "archive"}})
        emails = {}
        if body.action in ("suspend", "unsuspend"):
            origin = request.headers.get("origin") or ""
            for c in done:
                emails[c["id"]] = await notify(c, body.action == "suspend", reason, origin if origin.startswith("https://") else None)
        await db.audit_log.insert_one({"id": os.urandom(8).hex(), "action": f"users.{body.action}", "by": current.get("id"), "by_name": by,
                                       "reason": reason or None, "contact_ids": ids, "supabase_user_ids": uids, "at": _now()})
        return {"success": True, "action": body.action, "updated": len(done), "skipped": skipped, "emails": emails,
                "purge_after": purge_at if body.action == "archive" else None}

    @r.get("/admin/users/archived")
    async def archived(current=Depends(get_current_user)):
        require_master(current)
        rows = await db.contacts.find({"archived": True}, {"_id": 0}).sort("archived_at", -1).to_list(1000)
        now = datetime.now(timezone.utc)
        for x in rows:
            pa = x.get("purge_after")
            x["days_left"] = max(0, math.ceil((datetime.fromisoformat(pa) - now).total_seconds() / 86400)) if pa else None
        return {"items": rows, "total": len(rows)}

    async def erase_due() -> Dict[str, int]:
        due = await db.contacts.find({"archived": True, "purge_after": {"$lt": _now()}}, {"_id": 0}).to_list(500)
        if not due:
            return {"erased": 0}
        uids = [c["supabase_user_id"] for c in due if c.get("supabase_user_id")]
        pool = await sb.get_pool()
        hard = soft = 0
        async with pool.acquire() as conn:
            ready = {x["id"] for x in await conn.fetch("""SELECT id FROM public.users WHERE id = ANY($1::text[]) AND is_archived
                                                        AND coalesce(archived_reason,'') LIKE 'admin_deleted%' AND purge_after < now()""", uids)}
            for tbl, col in (("kyc_documents", "user_id"), ("hospital_staff", "user_id"), ("hospital_profiles", "user_id"),
                             ("ambulance_providers", "user_id"), ("doctors", "user_id"), ("pathologists", "user_id"),
                             ("path_lab_profiles", "user_id"), ("diagnostic_centre_profiles", "user_id")):
                try:
                    async with conn.transaction():
                        await conn.execute(f"DELETE FROM public.{tbl} WHERE {col} = ANY($1::text[])", list(ready))
                except Exception as ex:  # noqa: BLE001 — profile rows referenced by history stay; user row is anonymised below
                    log.info("erase: kept %s rows (%s)", tbl, type(ex).__name__)
            for uid in ready:
                try:
                    async with conn.transaction():
                        await conn.execute("DELETE FROM public.users WHERE id = $1", uid)
                    hard += 1
                except Exception:  # noqa: BLE001 — FK history (bills, cases) → anonymise instead
                    await conn.execute("""UPDATE public.users SET name = 'Deleted user', email = NULL, recovery_email = NULL,
                        password_hash = NULL, pin_hash = NULL, security_questions = NULL, dob = NULL, organization_name = NULL,
                        phone = left('del-' || id, 20), phone_key = NULL, trata_phone = NULL, archived_reason = 'erased',
                        purge_after = NULL, updated_at = now() WHERE id = $1""", uid)
                    soft += 1
        ids = [c["id"] for c in due if not c.get("supabase_user_id") or c["supabase_user_id"] in ready]
        phones = [c["phone"] for c in due if c["id"] in ids and c.get("phone")]
        await db.contacts.delete_many({"id": {"$in": ids}})
        await db.crm_users.delete_many({"$or": [{"provider_id": {"$in": ids}}, {"phone": {"$in": phones}}], "is_master_admin": {"$ne": True}})
        await db.activities.delete_many({"contact_id": {"$in": ids}})
        await db.audit_log.insert_one({"id": os.urandom(8).hex(), "action": "users.erase", "by": "cron", "contact_ids": ids, "at": _now()})
        return {"erased": len(ids), "deleted_rows": hard, "anonymised_rows": soft}

    @r.post("/admin/cron/erase-archived")
    async def cron_erase(request: Request):
        auth, secret = request.headers.get("authorization") or "", os.environ.get("WEBHOOK_CRON_SECRET") or ""
        if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
        import asyncio
        t = asyncio.create_task(erase_due())
        _BG.add(t)
        t.add_done_callback(_BG.discard)
        return {"accepted": True}

    return {"router": r, "ensure_schema": ensure_schema, "erase_due": erase_due}
