"""Master-admin only: device push alerts (KYC, sign-ups, orders, SOS) driven by the audit recorder, and the AI morning digest."""
from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pywebpush import WebPushException, webpush

import audit_log
import supabase_db as sb

log = logging.getLogger("admin_alerts")
IST = timezone(timedelta(hours=5, minutes=30))
KINDS = ["kyc", "signup", "order", "sos", "access"]
ORDER_TABLES = {"medicine_orders", "consultation_bookings", "pathology_bookings", "ambulance_bookings", "at_home_care_bookings",
                "diagnostic_bookings", "path_lab_bookings", "appointments", "doctor_appointments", "vaccination_bookings",
                "lab_test_bookings", "nurse_bookings", "hospital_public_bookings", "teleconsultation_bookings", "wellness_bookings"}
KYC_PENDING = {"pending", "under_review", "submitted", "pending_review"}
DIGEST_METRICS = {
    "signups": (["users"], "AND coalesce(role, 'patient') IN ('patient', 'customer') AND coalesce(user_type, 'patient') IN ('patient', 'customer')"),
    "doctor_appointments": (["consultation_bookings", "doctor_appointments", "appointments", "teleconsultation_bookings"], ""),
    "pathlab_bookings": (["pathology_bookings", "path_lab_bookings", "lab_bookings", "lab_test_bookings"], ""),
    "diagnostics_bookings": (["diagnostic_bookings"], ""),
    "pharmacy_orders": (["medicine_orders", "medication_orders"], ""),
    "sos": (["emergency_cases"], ""),
}
_BG: set = set()


def classify(e: Dict[str, Any]) -> Optional[str]:
    t, op, n = e["table_name"], e["op"], e.get("new_data") or {}
    if t == "emergency_cases" and op == "INSERT":
        return "sos"
    if t == "users" and op == "INSERT":
        return "signup"
    if t in ORDER_TABLES and op == "INSERT":
        return "order"
    if t in ("tratax_kyc_applications", "kyc_documents") and (
            op == "INSERT" or (op == "UPDATE" and "status" in (e.get("changed") or []))) and str(n.get("status") or "pending") in KYC_PENDING:
        return "kyc"
    return None


def message(kind: str, evs: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = evs[0].get("new_data") or {}
    many = len(evs) > 1
    label = lambda t: t.replace("_", " ")  # noqa: E731
    if kind == "sos":
        return {"title": f"{len(evs)} new SOS cases" if many else "New SOS / emergency case",
                "body": str(n.get("case_type") or n.get("reason") or "Open the console to respond"), "url": "/activities?view=cases", "urgent": True}
    if kind == "signup":
        roles = Counter(str((e.get("new_data") or {}).get("user_type") or (e.get("new_data") or {}).get("role") or "user") for e in evs)
        return {"title": f"{len(evs)} new sign-ups" if many else "New sign-up",
                "body": ", ".join(f"{v} {k}" for k, v in roles.items()) if many else f"{n.get('name') or 'Someone'} joined as {next(iter(roles))}",
                "url": "/contacts"}
    if kind == "order":
        tabs = Counter(label(e["table_name"]) for e in evs)
        return {"title": f"{len(evs)} new orders & bookings" if many else f"New {label(evs[0]['table_name']).rstrip('s')}",
                "body": ", ".join(f"{v} {k}" for k, v in tabs.items()), "url": "/admin/audit/patient"}
    return {"title": f"{len(evs)} KYC items need review" if many else "New KYC submitted for review",
            "body": str(n.get("document_name") or n.get("org_type") or n.get("provider_type") or "Open the KYC queue"), "url": "/admin/kyc-queue"}


def create_alerts_router(db, get_current_user, llm_key: str):
    r = APIRouter(prefix="/api")
    subs = db.push_subscriptions

    def master(c):
        if not c.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")

    async def push(doc: Dict[str, Any], payload: Dict[str, Any]) -> bool:
        try:
            await asyncio.to_thread(webpush, subscription_info={"endpoint": doc["endpoint"], "keys": doc["keys"]}, data=json.dumps(payload),
                                    vapid_private_key=os.environ["VAPID_PRIVATE_KEY"], vapid_claims={"sub": os.environ["VAPID_SUBJECT"]}, ttl=3600)
            return True
        except WebPushException as ex:
            if ex.response is None or ex.response.status_code in (404, 410):  # gone, or keys the push library can't use
                await subs.delete_one({"endpoint": doc["endpoint"]})
            else:
                log.warning(f"push failed: {ex.response.status_code if ex.response is not None else ex}")
            return False

    async def fan_out(kind: str, payload: Dict[str, Any]) -> int:
        sent = 0
        async for doc in subs.find({f"prefs.{kind}": {"$ne": False}}, {"_id": 0}):
            sent += await push(doc, {**payload, "kind": kind, "tag": f"trata-{kind}"})
        return sent

    # ── subscription management ──
    @r.get("/admin/alerts/public-key")
    async def public_key(current=Depends(get_current_user)):
        master(current)
        return {"public_key": os.environ["VAPID_PUBLIC_KEY"]}

    @r.get("/admin/alerts/devices")
    async def devices(endpoint: Optional[str] = None, current=Depends(get_current_user)):
        master(current)
        mine = await subs.count_documents({"admin_id": current["id"]})
        this = await subs.find_one({"endpoint": endpoint, "admin_id": current["id"]}, {"_id": 0, "prefs": 1}) if endpoint else None
        return {"devices": mine, "this_device": bool(this), "prefs": (this or {}).get("prefs") or {k: True for k in KINDS}}

    @r.post("/admin/alerts/subscribe")
    async def subscribe(body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        sub = body.get("subscription") or {}
        if not str(sub.get("endpoint", "")).startswith("https://") or not (sub.get("keys") or {}).get("p256dh") or not (sub.get("keys") or {}).get("auth"):
            raise HTTPException(status_code=400, detail="Invalid push subscription")
        prefs = {k: bool((body.get("prefs") or {}).get(k, True)) for k in KINDS}
        await subs.update_one({"endpoint": sub["endpoint"]}, {"$set": {
            "endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]}, "admin_id": current["id"],
            "prefs": prefs, "user_agent": str(body.get("user_agent") or "")[:200], "updated_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
        return {"ok": True, "prefs": prefs}

    @r.put("/admin/alerts/prefs")
    async def set_prefs(body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        prefs = {k: bool((body.get("prefs") or {}).get(k, True)) for k in KINDS}
        res = await subs.update_one({"endpoint": body.get("endpoint"), "admin_id": current["id"]}, {"$set": {"prefs": prefs}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="This device is not subscribed")
        return {"ok": True, "prefs": prefs}

    @r.post("/admin/alerts/unsubscribe")
    async def unsubscribe(body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        await subs.delete_one({"endpoint": body.get("endpoint"), "admin_id": current["id"]})
        return {"ok": True}

    @r.post("/admin/alerts/test")
    async def test(current=Depends(get_current_user)):
        master(current)
        sent = 0
        async for doc in subs.find({"admin_id": current["id"]}, {"_id": 0}):
            sent += await push(doc, {"title": "Test alert", "body": "Push alerts are working on this device.", "url": "/settings", "kind": "test", "tag": "trata-test"})
        return {"sent": sent}

    # ── watcher: follows the gap-free audit cursor, groups a batch per kind, pushes ──
    async def watch():
        state = db.alert_state
        while True:
            try:
                pool = await sb.get_pool()
                doc = await state.find_one({"_id": "push"})
                async with pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):
                    safe = await conn.fetchval("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint - 1")
                    if not doc:
                        await state.insert_one({"_id": "push", "txid": safe})
                        rows = []
                    else:
                        rows = await conn.fetch("""SELECT table_name, op, new_data, changed FROM trata_audit.activity_log
                                                    WHERE txid > $1::text::xid8 AND txid::text::bigint <= $2 AND (op = 'INSERT' OR table_name IN ('tratax_kyc_applications', 'kyc_documents'))
                                                    ORDER BY txid, id""", str(doc["txid"]), safe)
                if doc and safe > doc["txid"]:
                    groups: Dict[str, List[Dict[str, Any]]] = {}
                    for x in rows:
                        e = {**dict(x), "new_data": json.loads(x["new_data"]) if x["new_data"] else None}
                        k = classify(e)
                        if k:
                            groups.setdefault(k, []).append(e)
                    await state.update_one({"_id": "push"}, {"$set": {"txid": safe}})
                    for k, evs in groups.items():
                        await fan_out(k, message(k, evs))
            except Exception as ex:  # noqa: BLE001
                log.warning(f"alert watcher: {ex}")
            await asyncio.sleep(10)

    # ── morning digest ──
    async def day_metrics(start: datetime, end: datetime) -> Dict[str, int]:
        """Counted from the source tables by created_at, so any past day works (not only since recording began)."""
        pool = await sb.get_pool()
        out: Dict[str, int] = {}
        async with pool.acquire() as conn:
            have = {r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'created_at'")}
            for key, (tables, where) in DIGEST_METRICS.items():
                n = 0
                for t in tables:
                    if t in have:
                        n += await conn.fetchval(f'SELECT count(*) FROM public."{t}" WHERE created_at >= $1 AND created_at < $2 {where}', start, end)
                out[key] = n
        return out

    async def build_digest(day: str) -> Dict[str, Any]:
        d = datetime.now(IST).date() - timedelta(days=1 if day == "yesterday" else 0)
        start = datetime(d.year, d.month, d.day, tzinfo=IST)
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""SELECT table_name, op, count(*) n FROM trata_audit.activity_log
                                        WHERE at >= $1 AND at < $2 GROUP BY 1, 2""", start, start + timedelta(days=1))
            kinds = await conn.fetch("""SELECT table_name, op, jsonb_build_object('status', new_data->'status') AS new_data, changed
                                          FROM trata_audit.activity_log WHERE at >= $1 AND at < $2
                                         AND (op = 'INSERT' OR table_name IN ('tratax_kyc_applications', 'kyc_documents'))""", start, start + timedelta(days=1))
        totals = {"patient": Counter(), "provider": Counter()}
        for x in rows:
            for s in audit_log.scope_of(x["table_name"]):
                totals[s][x["table_name"].replace("_", " ")] += x["n"]
        counts = Counter(classify({**dict(k), "new_data": json.loads(k["new_data"]) if k["new_data"] else None}) for k in kinds)
        metrics = await day_metrics(start, start + timedelta(days=1))
        previous = await day_metrics(start - timedelta(days=1), start)
        stats = {"date": d.isoformat(), "changes": sum(x["n"] for x in rows), "previous": previous,
                 "highlights": {**metrics, "kyc": counts.get("kyc", 0)},
                 "patient_top": [{"table": t, "n": n} for t, n in totals["patient"].most_common(5)],
                 "provider_top": [{"table": t, "n": n} for t, n in totals["provider"].most_common(5)],
                 "patient_total": sum(totals["patient"].values()), "provider_total": sum(totals["provider"].values())}
        text = ""
        if stats["changes"] or any(metrics.values()):
            try:
                from emergentintegrations.llm.chat import LlmChat, UserMessage
                chat = LlmChat(api_key=llm_key, session_id=f"admin-digest-{d}-{datetime.now(timezone.utc).timestamp()}",
                               system_message="You brief the Trata Health Admin of Trata Health (a health platform with a Patient app and a Provider app). Plain English, no markdown headings, no emojis.").with_model("openai", "gpt-5.4")
                text = str(await chat.send_message(UserMessage(text=(
                    "Write 3-4 short sentences summarising this day's activity: what was busiest in the Patient app, what was busiest in the "
                    f"Provider app, and one thing the admin should look at first. Data:\n{json.dumps(stats)}")))).strip()
            except Exception as ex:  # noqa: BLE001
                log.warning(f"digest AI failed: {ex}")
        doc = {"date": d.isoformat(), "day": day, "stats": stats, "text": text, "ai": bool(text), "created_at": datetime.now(timezone.utc).isoformat()}
        await db.admin_digests.update_one({"date": doc["date"]}, {"$set": doc}, upsert=True)
        return doc

    @r.get("/admin/digest/latest")
    async def latest(current=Depends(get_current_user)):
        master(current)
        return {"digest": await db.admin_digests.find_one({"day": "yesterday"}, {"_id": 0}, sort=[("date", -1)])
                or await db.admin_digests.find_one({}, {"_id": 0}, sort=[("date", -1)])}

    @r.post("/admin/digest/generate")
    async def generate(body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        return {"digest": await build_digest("today" if body.get("day") == "today" else "yesterday")}

    @r.get("/admin/digest/records")
    async def digest_records(metric: str, date: str, current=Depends(get_current_user)):
        """The rows behind one summary number, for one IST day."""
        master(current)
        if metric not in DIGEST_METRICS:
            raise HTTPException(status_code=400, detail="Unknown metric")
        try:
            d = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
        start = datetime(d.year, d.month, d.day, tzinfo=IST)
        tables, where = DIGEST_METRICS[metric]
        pool = await sb.get_pool()
        items: List[Dict[str, Any]] = []
        async with pool.acquire() as conn:
            have = {r["table_name"] for r in await conn.fetch(
                "SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'created_at'")}
            for t in tables:
                if t not in have:
                    continue
                for x in await conn.fetch(f'SELECT to_jsonb(r) j FROM public."{t}" r WHERE created_at >= $1 AND created_at < $2 {where} '
                                          f'ORDER BY created_at DESC LIMIT 500', start, start + timedelta(days=1)):
                    j = json.loads(x["j"])
                    pick = lambda *ks: next((j[k] for k in ks if j.get(k) not in (None, "")), None)  # noqa: E731
                    items.append({"table": t, "id": str(j.get("id")), "created_at": j.get("created_at"), "status": pick("status"),
                                  "who": pick("patient_name", "customer_name", "full_name", "name", "contact_name"),
                                  "phone": pick("phone", "patient_phone", "customer_phone", "contact_phone"),
                                  "what": pick("case_type", "emergency_type", "service_type", "booking_type", "test_name", "consultation_type", "specialty", "order_type"),
                                  "patient_user_id": str(j["id"]) if t == "users" else pick("user_id", "patient_user_id", "customer_id", "patient_id")})
            missing = list({i["patient_user_id"] for i in items if not i["who"] and i["patient_user_id"]})
            if missing:
                names = {str(u["id"]): u["name"] for u in await conn.fetch(
                    "SELECT id, name FROM public.users WHERE id::text = ANY($1::text[])", missing)}
                for i in items:
                    i["who"] = i["who"] or names.get(i["patient_user_id"])
        items.sort(key=lambda i: str(i["created_at"]), reverse=True)
        return {"metric": metric, "date": d.isoformat(), "items": items}

    @r.post("/cron/admin-digest")
    async def cron_digest(request: Request):
        auth, secret = request.headers.get("authorization") or "", os.environ.get("WEBHOOK_CRON_SECRET") or ""
        if not secret or not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], secret):
            raise HTTPException(status_code=401, detail="Unauthorized")
        # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
        run_id = request.headers.get("x-webhook-id")
        if run_id and await db.cron_runs.find_one({"_id": f"admin-digest-{run_id}"}):
            return {"accepted": True, "duplicate": True}
        if run_id:
            await db.cron_runs.insert_one({"_id": f"admin-digest-{run_id}", "at": datetime.now(timezone.utc).isoformat()})
        t = asyncio.create_task(build_digest("yesterday"))
        _BG.add(t)
        t.add_done_callback(_BG.discard)
        return {"accepted": True}

    async def start():
        await subs.create_index("endpoint", unique=True)
        t = asyncio.create_task(watch())
        _BG.add(t)

    return {"router": r, "start": start, "notify": fan_out}
