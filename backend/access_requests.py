"""Provider access requests from the login screen + the Trata Health Admin notification centre."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

ROLES = {"provider_admin": "Provider admin / owner", "provider_staff": "Provider staff"}


class AccessRequestIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    phone: str
    role_wanted: str
    provider_contact_id: str
    note: str = Field(default="", max_length=500)


def create_access_router(db, get_current_user, notify):
    r = APIRouter(prefix="/api")
    now = lambda: datetime.now(timezone.utc)  # noqa: E731

    def master(c):
        if not c.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")

    # ── public (login screen) ──
    @r.get("/public/providers/search")
    async def search_providers(q: str):
        q = q.strip()
        if len(q) < 2:
            return {"items": []}
        rows = await db.contacts.find(
            {"type": {"$nin": ["patient", None]}, "supabase_user_id": {"$ne": None}, "archived": {"$ne": True},
             "name": {"$regex": re.escape(q), "$options": "i"}},
            {"_id": 0, "id": 1, "name": 1, "type": 1, "city": 1}).limit(8).to_list(8)
        return {"items": rows}

    @r.post("/public/access-requests")
    async def create_request(body: AccessRequestIn, request: Request):
        phone = re.sub(r"\D", "", body.phone)[-10:]
        if len(phone) != 10:
            raise HTTPException(status_code=400, detail="Enter a valid 10-digit phone")
        if body.role_wanted not in ROLES:
            raise HTTPException(status_code=400, detail="Choose the access you need")
        provider = await db.contacts.find_one({"id": body.provider_contact_id, "type": {"$ne": "patient"}}, {"_id": 0})
        if not provider:
            raise HTTPException(status_code=400, detail="Choose your provider from the list")
        if await db.access_requests.find_one({"phone": phone, "status": "pending"}):
            raise HTTPException(status_code=409, detail="You already have a request waiting. Trata Health Admin will get back to you.")
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
        if await db.access_requests.count_documents({"ip": ip, "created_at": {"$gte": (now() - timedelta(hours=1)).isoformat()}}) >= 5:
            raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
        doc = {"id": str(uuid.uuid4()), "name": body.name.strip(), "phone": phone, "role_wanted": body.role_wanted,
               "provider_contact_id": provider["id"], "provider_name": provider.get("name"), "provider_type": provider.get("type"),
               "provider_user_id": provider.get("supabase_user_id"), "note": body.note.strip(), "status": "pending",
               "ip": ip, "created_at": now().isoformat()}
        await db.access_requests.insert_one(dict(doc))
        title = f"Access request: {doc['name']}"
        msg = f"{ROLES[doc['role_wanted']]} at {doc['provider_name']} · +91 {phone}" + (f" — “{doc['note'][:120]}”" if doc["note"] else "")
        await db.notifications.insert_one({"id": str(uuid.uuid4()), "kind": "access_request", "audience": "master_admin",
                                           "title": title, "message": msg, "link": "/admin/notifications?tab=access",
                                           "ref_id": doc["id"], "read_by": [], "created_at": doc["created_at"]})
        await notify("access", {"title": "New provider access request", "body": f"{doc['name']} · {doc['provider_name']}",
                                "url": "/admin/notifications?tab=access"})
        return {"ok": True}

    # ── Trata Health Admin notification centre ──
    @r.get("/admin/notification-centre")
    async def centre(kind: Optional[str] = None, limit: int = 100, current=Depends(get_current_user)):
        master(current)
        f: Dict[str, Any] = {"audience": {"$ne": "provider"}, "user_id": {"$in": [None, current["id"]]}}
        if kind:
            f["kind"] = kind
        items = await db.notifications.find(f, {"_id": 0}).sort("created_at", -1).limit(max(1, min(limit, 300))).to_list(300)
        for n in items:
            n["is_read"] = current["id"] in (n.pop("read_by", None) or [])
        unread = await db.notifications.count_documents({**f, "read_by": {"$ne": current["id"]}})
        pending = await db.access_requests.count_documents({"status": "pending"})
        return {"items": items, "unread": unread, "pending_access": pending}

    @r.post("/admin/notification-centre/read")
    async def mark_read(body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        f: Dict[str, Any] = {"audience": {"$ne": "provider"}}
        if body.get("id"):
            f["id"] = body["id"]
        res = await db.notifications.update_many(f, {"$addToSet": {"read_by": current["id"]}})
        return {"updated": res.modified_count}

    @r.get("/admin/access-requests")
    async def list_requests(status: Optional[str] = None, current=Depends(get_current_user)):
        master(current)
        items = await db.access_requests.find({"status": status} if status else {}, {"_id": 0, "ip": 0}).sort("created_at", -1).to_list(300)
        return {"items": items}

    @r.post("/admin/access-requests/{rid}")
    async def decide(rid: str, body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        action = body.get("action")
        if action not in ("approve", "decline"):
            raise HTTPException(status_code=400, detail="action must be approve or decline")
        res = await db.access_requests.update_one({"id": rid, "status": "pending"}, {"$set": {
            "status": "approved" if action == "approve" else "declined", "decision_note": str(body.get("note") or "")[:300],
            "decided_by": current.get("name") or current["id"], "decided_at": now().isoformat()}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Request not found or already handled")
        await db.notifications.update_many({"ref_id": rid}, {"$addToSet": {"read_by": current["id"]}})
        return await db.access_requests.find_one({"id": rid}, {"_id": 0, "ip": 0})

    return r
