"""Doctor PC console: appointments from every Patient-app booking table, status updates, per-patient visit history."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

import supabase_db as sb

IST = timezone(timedelta(hours=5, minutes=30))
DONE = {"completed", "cancelled", "canceled", "no_show", "rejected", "declined", "expired", "failed", "missed"}
ACTIONS = {"completed", "no_show", "cancelled"}
# source -> (table, date expr, time expr, mode expr, fee expr, extra cols)
SOURCES = {
    "clinic": ("doctor_appointments", "date", "time", "coalesce(appointment_type, 'in-person')", "consultation_fee",
               "patient_name, patient_phone, NULL::text AS age, NULL::text AS gender, reason, notes, payment_status, visit_type, token_number::text AS token"),
    "hospital": ("consultation_bookings", "preferred_date", "preferred_time", "coalesce(consult_mode, 'in-person')", "fee",
                 "patient_name, patient_phone, patient_age AS age, patient_gender AS gender, reason, outcome_notes AS notes, NULL::text AS payment_status, booking_type AS visit_type, booking_ref AS token"),
    "video": ("teleconsultation_bookings", "scheduled_date::text", "scheduled_time", "'video'", "consultation_fee",
              "patient_name, patient_phone, patient_age::text AS age, patient_gender AS gender, chief_complaint AS reason, doctor_notes AS notes, payment_status, consultation_type AS visit_type, booking_number AS token"),
    "general": ("appointments", "to_char(appointment_date AT TIME ZONE 'Asia/Kolkata', 'YYYY-MM-DD')", "time_slot", "'in-person'", "NULL::float8",
                "NULL::text AS patient_name, NULL::text AS patient_phone, NULL::text AS age, NULL::text AS gender, reason, notes, NULL::text AS payment_status, NULL::text AS visit_type, NULL::text AS token"),
}
PATIENT_COL = {"clinic": "patient_id", "hospital": "patient_id", "video": "user_id", "general": "patient_id"}


def create_doctor_router(get_current_user):
    r = APIRouter(prefix="/api/provider/doctor")

    async def doctor_ids(current) -> List[str]:
        if current.get("role") != "provider_owner" or current.get("provider_type") != "doctor":
            raise HTTPException(status_code=403, detail="Doctor account required")
        uid = str(current.get("supabase_user_id") or current["id"])
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT id FROM public.doctors WHERE user_id = $1", uid)
        return [uid] + [str(x["id"]) for x in rows]

    async def fetch(ids: List[str], extra: str = "", args: tuple = ()) -> List[Dict[str, Any]]:
        pool = await sb.get_pool()
        out: List[Dict[str, Any]] = []
        async with pool.acquire() as conn:
            for src, (t, d, tm, mode, fee, cols) in SOURCES.items():
                pc = PATIENT_COL[src]
                rows = await conn.fetch(
                    f"""SELECT id, {pc} AS patient_id, {d} AS date, {tm} AS time, {mode} AS mode, {fee} AS fee, status, created_at, {cols}
                          FROM public.{t} WHERE doctor_id = ANY($1::text[]) {extra.replace('{pc}', pc)}
                         ORDER BY created_at DESC LIMIT 500""", ids, *args)
                out += [{**dict(x), "source": src, "fee": x["fee"], "created_at": x["created_at"].isoformat() if x["created_at"] else None} for x in rows]
            missing = list({a["patient_id"] for a in out if a["patient_id"] and not a["patient_name"]})
            if missing:
                users = {str(u["id"]): u for u in await conn.fetch("SELECT id, name, phone FROM public.users WHERE id::text = ANY($1::text[])", missing)}
                for a in out:
                    u = users.get(str(a["patient_id"]))
                    if u and not a["patient_name"]:
                        a["patient_name"], a["patient_phone"] = u["name"], a["patient_phone"] or u["phone"]
        return out

    def sort_key(a):
        return (str(a.get("date") or ""), str(a.get("time") or ""))

    @r.get("/appointments")
    async def appointments(current=Depends(get_current_user)):
        items = await fetch(await doctor_ids(current))
        today = datetime.now(IST).date().isoformat()
        upcoming = [a for a in items if str(a.get("date") or "")[:10] >= today and str(a.get("status") or "").lower() not in DONE]
        past = [a for a in items if a not in upcoming]
        upcoming.sort(key=sort_key)
        past.sort(key=sort_key, reverse=True)
        return {"upcoming": upcoming, "past": past, "today": today,
                "counts": {"today": sum(1 for a in upcoming if str(a["date"])[:10] == today), "upcoming": len(upcoming), "past": len(past)}}

    @r.post("/appointments/{source}/{aid}/status")
    async def set_status(source: str, aid: str, body: Dict[str, Any], current=Depends(get_current_user)):
        status = str(body.get("status") or "")
        if source not in SOURCES or status not in ACTIONS:
            raise HTTPException(status_code=400, detail="Invalid source or status")
        ids = await doctor_ids(current)
        table = SOURCES[source][0]
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"SELECT id, status FROM public.{table} WHERE id = $1 AND doctor_id = ANY($2::text[])", aid, ids)
            if not row:
                raise HTTPException(status_code=404, detail="Appointment not found")
            if str(row["status"] or "").lower() in DONE:
                raise HTTPException(status_code=409, detail=f"Appointment is already {row['status']}")
            now = datetime.now(timezone.utc)
            if source in ("hospital", "video"):
                entry = json.dumps([{"status": status, "at": now.isoformat(), "by": "doctor", "via": "admin_console"}])
                await conn.execute(f"""UPDATE public.{table} SET status = $1, updated_at = $2,
                                        status_history = (coalesce(status_history::jsonb, '[]'::jsonb) || $3::jsonb)::json WHERE id = $4""",
                                   status, now, entry, aid)
            else:
                await conn.execute(f"UPDATE public.{table} SET status = $1, updated_at = $2 WHERE id = $3", status, now, aid)
        return {"ok": True, "status": status}

    @r.get("/patients/{patient_id}/visits")
    async def visits(patient_id: str, phone: str = "", current=Depends(get_current_user)):
        ids = await doctor_ids(current)
        items = [a for a in await fetch(ids) if str(a["patient_id"] or "") == patient_id or (phone and str(a.get("patient_phone") or "")[-10:] == phone[-10:])]
        items.sort(key=sort_key, reverse=True)
        return {"items": items}

    return r
