"""Doctor PC console: appointments from every Patient-app booking table, status updates, per-patient visit history."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import supabase_db as sb

IST = timezone(timedelta(hours=5, minutes=30))
EHR_NS = uuid.UUID("2b1f6a52-3c1e-4d1a-9a77-7d0c0e5a1e01")


class Medicine(BaseModel):
    name: str = Field(default="", max_length=120)
    dosage: str = Field(default="", max_length=60)
    frequency: str = Field(default="", max_length=60)
    duration: str = Field(default="", max_length=60)
    instructions: str = Field(default="", max_length=200)


class ConsultIn(BaseModel):
    chief_complaint: str = Field(default="", max_length=2000)
    diagnosis: str = Field(default="", max_length=500)
    vitals: Dict[str, str] = {}
    notes: str = Field(default="", max_length=5000)
    treatment_plan: str = Field(default="", max_length=3000)
    prescriptions: List[Medicine] = []
    investigations: List[str] = []
    follow_up_date: Optional[str] = None
    follow_up_notes: str = Field(default="", max_length=1000)
    complete: bool = False
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
PHONE_COL = {"clinic": "patient_phone", "hospital": "patient_phone", "video": "patient_phone", "general": "NULL::text"}


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
                          FROM public.{t} WHERE doctor_id = ANY($1::text[]) {extra.replace('{pc}', pc).replace('{ph}', PHONE_COL[src])}
                         ORDER BY created_at DESC LIMIT 2000""", ids, *args)
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
            now = datetime.now(timezone.utc)
            if source in ("hospital", "video"):
                entry = json.dumps([{"status": status, "at": now.isoformat(), "by": "doctor", "via": "admin_console"}])
                done = await conn.fetchval(f"""UPDATE public.{table} SET status = $1, updated_at = $2,
                                        status_history = (coalesce(status_history::jsonb, '[]'::jsonb) || $3::jsonb)::json
                                        WHERE id = $4 AND lower(coalesce(status, '')) <> ALL($5::text[]) RETURNING id""",
                                           status, now, entry, aid, list(DONE))
            else:
                done = await conn.fetchval(f"""UPDATE public.{table} SET status = $1, updated_at = $2
                                        WHERE id = $3 AND lower(coalesce(status, '')) <> ALL($4::text[]) RETURNING id""",
                                           status, now, aid, list(DONE))
            if not done:  # became final in between (e.g. patient cancelled on the app)
                raise HTTPException(status_code=409, detail=f"Appointment is already {row['status']}")
        return {"ok": True, "status": status}

    @r.get("/patients/{patient_id}/visits")
    async def visits(patient_id: str, phone: str = "", current=Depends(get_current_user)):
        ids = await doctor_ids(current)
        items = await fetch(ids, "AND ({pc} = $2 OR right(coalesce({ph}, ''), 10) = $3)", (patient_id, phone[-10:] if phone else "~"))
        items.sort(key=sort_key, reverse=True)
        return {"items": items}

    # ── consultation record (shared consultation_ehr — same row the Provider app reads/writes) ──
    async def appointment(conn, source: str, aid: str, ids: List[str]) -> Dict[str, Any]:
        if source not in SOURCES:
            raise HTTPException(status_code=400, detail="Invalid source")
        t, d, tm, mode, fee, cols = SOURCES[source]
        a = await conn.fetchrow(f"""SELECT id, {PATIENT_COL[source]} AS patient_id, {d} AS date, {tm} AS time, {mode} AS mode, status, {cols}
                                     FROM public.{t} WHERE id = $1 AND doctor_id = ANY($2::text[])""", aid, ids)
        if not a:
            raise HTTPException(status_code=404, detail="Appointment not found")
        return dict(a)

    async def find_ehr(conn, source: str, a: Dict[str, Any], ids: List[str]):
        eid = str(uuid.uuid5(EHR_NS, f"{source}:{a['id']}"))
        row = await conn.fetchrow("SELECT * FROM public.consultation_ehr WHERE id = $1", eid)
        if not row and a.get("patient_id") and a.get("date"):  # a record the doctor already started in the Provider app
            # console-created rows are uuid v5 (one per appointment) — never borrow another appointment's record
            row = await conn.fetchrow("""SELECT * FROM public.consultation_ehr WHERE patient_id = $1 AND doctor_id = ANY($2::text[])
                                          AND (consultation_date AT TIME ZONE 'Asia/Kolkata')::date = $3::text::date
                                          AND substr(id, 15, 1) <> '5' ORDER BY created_at DESC LIMIT 1""",
                                      str(a["patient_id"]), ids, str(a["date"])[:10])
        return eid, row

    def ehr_out(row) -> Optional[Dict[str, Any]]:
        if not row:
            return None
        j = lambda v: json.loads(v) if isinstance(v, str) else v  # noqa: E731
        e = dict(row)
        for k in ("diagnosis", "prescriptions", "investigations", "vitals", "past_medical_history", "lab_results"):
            e[k] = j(e.get(k))
        for k in ("signed_at", "created_at", "updated_at"):
            e[k] = e[k].isoformat() if e.get(k) else None
        for k in ("consultation_date", "follow_up_date"):  # stored as IST midnight -> plain IST date
            e[k] = e[k].astimezone(IST).date().isoformat() if e.get(k) else None
        e["shared"] = str(e.get("status") or "").lower() == "signed"
        return e

    @r.get("/appointments/{source}/{aid}/consult")
    async def get_consult(source: str, aid: str, current=Depends(get_current_user)):
        ids = await doctor_ids(current)
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            a = await appointment(conn, source, aid, ids)
            _, row = await find_ehr(conn, source, a, ids)
            doc = await conn.fetchrow("""SELECT full_name, specialization, qualification, clinic_name, hospital_name, address, city, phone
                                          FROM public.doctors WHERE user_id = $1 LIMIT 1""", ids[0])
        return {"appointment": {**a, "source": source}, "ehr": ehr_out(row), "doctor": dict(doc) if doc else {"full_name": current.get("name")}}

    @r.put("/appointments/{source}/{aid}/consult")
    async def save_consult(source: str, aid: str, body: ConsultIn, current=Depends(get_current_user)):
        ids = await doctor_ids(current)
        meds = [m.model_dump() for m in body.prescriptions if m.name.strip()]
        diag = [x.strip() for x in body.diagnosis.split(",") if x.strip()]
        try:
            fu = datetime.strptime(body.follow_up_date, "%Y-%m-%d").replace(tzinfo=IST) if body.follow_up_date else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Follow-up date must be YYYY-MM-DD")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            a = await appointment(conn, source, aid, ids)
            eid, row = await find_ehr(conn, source, a, ids)
            now = datetime.now(timezone.utc)
            vals = (body.chief_complaint.strip(), json.dumps(diag), diag[0] if diag else None, json.dumps(body.vitals), body.treatment_plan.strip(),
                    json.dumps(meds), json.dumps([x for x in body.investigations if x.strip()]), fu, body.follow_up_notes.strip(), body.notes.strip(), now)
            if row:
                await conn.execute("""UPDATE public.consultation_ehr SET chief_complaint = $1, diagnosis = $2::json, primary_diagnosis = $3, vitals = $4::json,
                                        treatment_plan = $5, prescriptions = $6::json, investigations = $7::json, follow_up_date = $8, follow_up_notes = $9,
                                        notes = $10, updated_at = $11 WHERE id = $12""", *vals, row["id"])
                eid = row["id"]
            else:
                cdate = datetime.strptime(str(a["date"])[:10], "%Y-%m-%d").replace(tzinfo=IST) if a.get("date") else now
                await conn.execute("""INSERT INTO public.consultation_ehr (chief_complaint, diagnosis, primary_diagnosis, vitals, treatment_plan, prescriptions,
                                        investigations, follow_up_date, follow_up_notes, notes, updated_at, id, patient_id, doctor_id, consultation_date,
                                        consultation_type, status, created_at)
                                      VALUES ($1, $2::json, $3, $4::json, $5, $6::json, $7::json, $8, $9, $10, $11, $12, $13, $14, $15, $16, 'draft', $11)""",
                                   *vals, eid, str(a.get("patient_id") or ""), ids[0], cdate, a.get("mode") or source)
            out = ehr_out(await conn.fetchrow("SELECT * FROM public.consultation_ehr WHERE id = $1", eid))
        completed, note = False, None
        if body.complete and str(a.get("status") or "").lower() not in DONE:
            try:
                await set_status(source, aid, {"status": "completed"}, current)
                completed = True
            except HTTPException as ex:  # e.g. patient cancelled meanwhile — notes are still saved
                note = ex.detail
        return {"ehr": out, "completed": completed, "complete_error": note}

    @r.post("/appointments/{source}/{aid}/consult/share")
    async def share_consult(source: str, aid: str, current=Depends(get_current_user)):
        ids = await doctor_ids(current)
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            a = await appointment(conn, source, aid, ids)
            _, row = await find_ehr(conn, source, a, ids)
            if not row:
                raise HTTPException(status_code=400, detail="Save the consultation first")
            meds = json.loads(row["prescriptions"]) if isinstance(row["prescriptions"], str) else (row["prescriptions"] or [])
            if not meds and not row["primary_diagnosis"]:
                raise HTTPException(status_code=400, detail="Add a diagnosis or at least one medicine before sharing")
            if not a.get("patient_id"):
                raise HTTPException(status_code=400, detail="This appointment isn't linked to a Patient app account")
            now = datetime.now(timezone.utc)
            name = current.get("name") or "Your doctor"
            pid = str(a["patient_id"])
            notified = bool(await conn.fetchval("SELECT 1 FROM public.users WHERE id::text = $1", pid))
            async with conn.transaction():
                await conn.execute("UPDATE public.consultation_ehr SET status = 'signed', signed_at = $1, signed_by = $2, updated_at = $1 WHERE id = $3",
                                   now, name, row["id"])
                if notified:
                    await conn.execute("""INSERT INTO public.notifications (id, user_id, title, message, notification_type, data, is_read, created_at)
                                          VALUES ($1, $2, $3, $4, 'consultation', $5::json, FALSE, $6)""",
                                       str(uuid.uuid4()), pid, f"Prescription from {name}",
                                       f"{len(meds)} medicine(s){' · ' + row['primary_diagnosis'] if row['primary_diagnosis'] else ''}. Open your consultation to view it.",
                                       json.dumps({"kind": "prescription", "consultation_ehr_id": row["id"], "doctor_id": ids[0]}), now)
            out = ehr_out(await conn.fetchrow("SELECT * FROM public.consultation_ehr WHERE id = $1", row["id"]))
        return {"ehr": out, "patient_notified": notified}

    return r
