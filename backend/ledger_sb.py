"""Provider Ledger — read-only Supabase aggregation of Patient-App services
catered by each provider (canonical tables, never written here)."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

import supabase_db as sb

LEDGER_ROLES = {"hospital": "hospital", "ambulance_provider": "ambulance",
                "pathologist": "pathology", "doctor": "doctor"}


def _j(v):
    if v is None:
        return None
    try:
        return json.loads(v) if isinstance(v, str) else v
    except Exception:
        return v


def _f(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _is_test(name: Optional[str]) -> bool:
    return bool(name) and (bool(sb._TEST_RX.search(name)) or name in sb._TEST_EXACT)


async def list_providers() -> List[Dict[str, Any]]:
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.id, u.name, u.phone, u.role, u.verification_status, u.created_at,
                   coalesce(hp.name, ap.business_name, pa.lab_name, d.full_name, u.name) AS display_name,
                   coalesce(hp.city, ap.city, pa.city, d.city) AS city
              FROM public.users u
         LEFT JOIN public.hospital_profiles hp ON hp.user_id = u.id
         LEFT JOIN public.ambulance_providers ap ON ap.user_id = u.id
         LEFT JOIN public.pathologists pa ON pa.user_id = u.id
         LEFT JOIN public.doctors d ON d.user_id = u.id
             WHERE u.role = ANY($1::text[]) AND coalesce(u.is_archived, FALSE) = FALSE
             ORDER BY u.created_at DESC NULLS LAST""", list(LEDGER_ROLES))
    split = {}
    if await sb.lab_split_live():
        async with pool.acquire() as conn:
            for kind, (tbl, _b, _fk) in sb.LAB_KINDS.items():
                for x in await conn.fetch(f"SELECT user_id::text AS uid, name, city FROM public.{tbl} WHERE coalesce(is_demo, FALSE) = FALSE"):
                    split[x["uid"]] = (kind, x["name"], x["city"])
    out = []
    for r in rows:
        d = dict(r)
        if d["id"] in split:
            d["role"] = "pathologist"
            kind, nm, city = split[d["id"]]
            d.update(display_name=nm or d["display_name"], city=city or d["city"], lab_kind=kind)
        if _is_test(d["display_name"]) or _is_test(d["name"]):
            continue
        d["vertical"] = d.get("lab_kind") or LEDGER_ROLES[d["role"]]
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        out.append(d)
    return out


async def _id_map(conn, user_ids: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
    """{any provider id (users.id or profile id) → {user_id, vertical}} in one round-trip."""
    rows = await conn.fetch("""
        WITH u AS (SELECT id, role FROM public.users WHERE role = ANY($1::text[])
                    AND ($2::text[] IS NULL OR id = ANY($2::text[])))
        SELECT u.id AS user_id, u.role, x.pid FROM u
          LEFT JOIN LATERAL (
               SELECT id AS pid FROM public.hospital_profiles WHERE user_id=u.id AND u.role='hospital'
         UNION ALL SELECT id FROM public.ambulance_providers WHERE user_id=u.id AND u.role='ambulance_provider'
         UNION ALL SELECT id FROM public.pathologists WHERE user_id=u.id AND u.role='pathologist'
         UNION ALL SELECT id FROM public.doctors WHERE user_id=u.id AND u.role='doctor') x ON TRUE""",
        list(LEDGER_ROLES), user_ids)
    m: Dict[str, Dict[str, Any]] = {}
    if await sb.lab_split_live():
        for kind, (tbl, _b, _fk) in sb.LAB_KINDS.items():
            for x in await conn.fetch(f"""SELECT id::text AS pid, user_id::text AS uid FROM public.{tbl}
                                          WHERE ($1::text[] IS NULL OR user_id::text = ANY($1::text[]))""", user_ids):
                if x["uid"]:
                    o = m.setdefault(x["uid"], {"user_id": x["uid"], "vertical": kind})
                    o.update(vertical=kind, profile_id=x["pid"])
                    m[x["pid"]] = o
    for r in rows:
        if r["user_id"] in m and m[r["user_id"]]["vertical"] in sb.LAB_KINDS:
            continue
        o = m.setdefault(r["user_id"], {"user_id": r["user_id"], "vertical": LEDGER_ROLES[r["role"]]})
        if r["pid"]:
            o["profile_id"] = r["pid"]
            m[r["pid"]] = o
    return m


def _svc(kind, r, patient_id, patient_name, patient_phone, at, title, amount, status, details) -> Dict[str, Any]:
    return {
        "key": f"{kind}:{r['id']}", "kind": kind, "ref_id": r["id"], "source": "patient_app",
        "patient_id": patient_id, "patient_name": patient_name, "patient_phone": patient_phone,
        "date": at.isoformat() if hasattr(at, "isoformat") else at, "title": title,
        "amount": _f(amount), "status": status, "details": details,
    }


async def _collect(conn, idmap: Dict[str, Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """All Patient-App services for every provider in idmap, grouped by users.id."""
    ids = list(idmap)
    by: Dict[str, List[Dict[str, Any]]] = {}
    pool = await sb.get_pool()

    async def q(sql):
        async with pool.acquire() as c:
            return await c.fetch(sql, ids)

    R = await asyncio.gather(
        q("""
        SELECT id, booking_ref, patient_id, patient_name, patient_phone, patient_age, patient_gender,
               hospital_id, doctor_id, doctor_name, doctor_specialty, hospital_name, reason, preferred_date,
               preferred_time, consult_mode, fee, booking_type, status, outcome_notes, hospital_note, created_at
          FROM public.consultation_bookings WHERE hospital_id = ANY($1::text[]) OR doctor_id = ANY($1::text[])"""),
        q("""
        SELECT id, booking_number, user_id, doctor_id, patient_name, patient_phone, consultation_type, scheduled_date,
               scheduled_time, chief_complaint, diagnosis, doctor_notes, call_duration_minutes,
               consultation_fee, payment_status, status, created_at
          FROM public.teleconsultation_bookings WHERE doctor_id = ANY($1::text[])"""),
        q("""
        SELECT id, customer_id, customer_phone, case_type, priority, status, reason, hospital_id, ambulance_provider_id,
               patient_profile::text AS pp, distance, created_at
          FROM public.emergency_cases WHERE hospital_id = ANY($1::text[]) OR ambulance_provider_id = ANY($1::text[])"""),
        q("""
        SELECT a.id, a.admission_number, a.patient_id, a.hospital_id, a.admission_type, a.chief_complaint,
               a.initial_diagnosis, a.bed_number, a.ward_type, a.status, a.insurance_provider,
               a.estimated_cost, a.admission_time, a.discharge_time, a.created_at,
               u.name AS patient_name, u.phone AS patient_phone,
               ds.final_diagnosis, ds.condition_at_discharge, ds.follow_up_instructions,
               ds.total_bill_amount, ds.treatment_given
          FROM public.patient_admissions a
     LEFT JOIN public.users u ON u.id = a.patient_id
     LEFT JOIN public.discharge_summaries ds ON ds.admission_id = a.id
         WHERE a.hospital_id = ANY($1::text[])"""),
        q("""
        SELECT id, booking_id, customer_id, customer_phone, patient_name, booking_type, ambulance_type, provider_id,
               is_emergency, pickup_address, drop_address, destination_hospital_name,
               actual_distance_km, estimated_distance_km, total_fare, payment_status, status, created_at
          FROM public.ambulance_bookings WHERE provider_id = ANY($1::text[])"""),
        q("""
        SELECT id, booking_id, patient_id, patient_name, patient_phone, pathologist_id, service_type, tests::text AS tests,
               subtotal, home_collection_fee, discount_amount, total_amount, scheduled_date, scheduled_time,
               collection_address, report_url, payment_status, status, pathologist_notes, created_at
          FROM public.pathology_bookings WHERE pathologist_id = ANY($1::text[])"""),
    )

    if await sb.lab_split_live():
        L = await asyncio.gather(
            q("""SELECT b.id::text AS id, b.path_lab_profile_id::text AS owner, b.patient_id::text AS patient_id,
                        b.tests::text AS tests, b.collection_type, b.scheduled_for, b.total_amount, b.status,
                        b.report_url, b.created_at, br.name AS branch
                   FROM public.path_lab_bookings b LEFT JOIN public.path_lab_branches br ON br.id = b.path_lab_branch_id
                  WHERE b.path_lab_profile_id::text = ANY($1::text[])"""),
            q("""SELECT b.id::text AS id, b.diagnostic_centre_profile_id::text AS owner, b.patient_id::text AS patient_id,
                        b.scans::text AS scans, b.scheduled_for, b.total_amount, b.status, b.report_url, b.images_url,
                        b.referring_doctor_id::text AS referring_doctor_id, b.created_at, br.name AS branch
                   FROM public.diagnostic_bookings b LEFT JOIN public.diagnostic_centre_branches br ON br.id = b.diagnostic_centre_branch_id
                  WHERE b.diagnostic_centre_profile_id::text = ANY($1::text[])"""))
        R = (*R[:5], [])  # legacy pathology_bookings ignored once split is live (ids preserved by migration)
    else:
        L = ([], [])

    def add(owner_id, vertical_ok, svc):
        o = idmap.get(owner_id)
        if o and o["vertical"] in vertical_ok:
            by.setdefault(o["user_id"], []).append(svc)

    for r in R[0]:
        mk = lambda: _svc("consultation", r, r["patient_id"], r["patient_name"], r["patient_phone"], r["created_at"],  # noqa: E731
                          f"OPD consultation · {r['doctor_name'] or 'Doctor'}", r["fee"], r["status"], {
                              "Booking ref": r["booking_ref"], "Doctor": r["doctor_name"], "Specialty": r["doctor_specialty"],
                              "Hospital": r["hospital_name"], "Reason": r["reason"], "Mode": r["consult_mode"],
                              "Type": r["booking_type"], "Preferred slot": f"{r['preferred_date'] or ''} {r['preferred_time'] or ''}".strip(),
                              "Age / gender": f"{r['patient_age'] or '—'} / {r['patient_gender'] or '—'}",
                              "Outcome notes": r["outcome_notes"], "Hospital note": r["hospital_note"]})
        add(r["hospital_id"], {"hospital"}, mk())
        add(r["doctor_id"], {"doctor"}, mk())

    for r in R[1]:
        add(r["doctor_id"], {"doctor"}, _svc("teleconsultation", r, r["user_id"], r["patient_name"], r["patient_phone"], r["created_at"],
            "Video teleconsultation", r["consultation_fee"], r["status"], {
                "Booking #": r["booking_number"], "Type": r["consultation_type"],
                "Scheduled": f"{r['scheduled_date'] or ''} {r['scheduled_time'] or ''}".strip(),
                "Chief complaint": r["chief_complaint"], "Diagnosis": r["diagnosis"],
                "Doctor notes": r["doctor_notes"], "Call minutes": r["call_duration_minutes"], "Payment": r["payment_status"]}))

    for r in R[2]:
        pp = _j(r["pp"]) or {}
        bi = (pp.get("basicInfo") or {}) if isinstance(pp, dict) else {}
        mk = lambda: _svc("sos", r, r["customer_id"], bi.get("fullName"), r["customer_phone"], r["created_at"],  # noqa: E731
                          f"Emergency SOS · {(r['case_type'] or '').replace('_', ' ')}", 0, r["status"], {
                              "Case type": r["case_type"], "Priority": r["priority"], "Reason": r["reason"],
                              "Distance": r["distance"], "Blood group": bi.get("bloodGroup"),
                              "Age / gender": f"{bi.get('age') or '—'} / {bi.get('gender') or '—'}"})
        add(r["hospital_id"], {"hospital"}, mk())
        add(r["ambulance_provider_id"], {"ambulance"}, mk())

    for r in R[3]:
        add(r["hospital_id"], {"hospital"}, _svc("admission", r, r["patient_id"], r["patient_name"], r["patient_phone"],
            r["admission_time"] or r["created_at"],
            f"In-patient admission · {r['ward_type'] or r['admission_type'] or ''}".strip(" ·"),
            r["total_bill_amount"] or r["estimated_cost"], r["status"], {
                "Admission #": r["admission_number"], "Bed": r["bed_number"], "Ward": r["ward_type"],
                "Chief complaint": r["chief_complaint"], "Initial diagnosis": r["initial_diagnosis"],
                "Final diagnosis": r["final_diagnosis"], "Condition at discharge": r["condition_at_discharge"],
                "Treatment": r["treatment_given"], "Follow-up": r["follow_up_instructions"],
                "Insurance": r["insurance_provider"],
                "Discharged": r["discharge_time"].isoformat() if r["discharge_time"] else None}))

    for r in R[4]:
        add(r["provider_id"], {"ambulance"}, _svc("ambulance_ride", r, r["customer_id"], r["patient_name"], r["customer_phone"], r["created_at"],
            f"Ambulance ride · {r['ambulance_type'] or r['booking_type'] or ''}".strip(" ·"), r["total_fare"], r["status"], {
                "Booking": r["booking_id"], "Emergency": "Yes" if r["is_emergency"] else "No",
                "Pickup": r["pickup_address"], "Drop": r["drop_address"],
                "Destination hospital": r["destination_hospital_name"],
                "Distance km": r["actual_distance_km"] or r["estimated_distance_km"], "Payment": r["payment_status"]}))

    for r in R[5]:
        tests = _j(r["tests"]) or []
        names = ", ".join(str(t.get("testName") or t.get("name") or "") for t in tests if isinstance(t, dict)) or None
        add(r["pathologist_id"], {"pathology"}, _svc("lab_test", r, r["patient_id"], r["patient_name"], r["patient_phone"], r["created_at"],
            f"Lab tests · {names or r['service_type'] or ''}".strip(" ·"), r["total_amount"], r["status"], {
                "Booking": r["booking_id"], "Tests": names, "Service": r["service_type"],
                "Subtotal": r["subtotal"], "Home collection fee": r["home_collection_fee"], "Discount": r["discount_amount"],
                "Scheduled": f"{r['scheduled_date'] or ''} {r['scheduled_time'] or ''}".strip(),
                "Collection address": r["collection_address"], "Report": r["report_url"],
                "Payment": r["payment_status"], "Lab notes": r["pathologist_notes"]}))

    for r in L[0]:
        tests = _j(r["tests"]) or []
        names = ", ".join(str(t.get("name") or t.get("code") or "") for t in tests if isinstance(t, dict)) or None
        add(r["owner"], {"path_lab"}, _svc("lab_test", r, r["patient_id"], None, None, r["created_at"],
            f"Lab tests · {names or ''}".strip(" ·"), r["total_amount"], r["status"], {
                "Tests": names, "Collection": (r["collection_type"] or "").replace("_", " "), "Branch": r["branch"],
                "Scheduled": r["scheduled_for"].isoformat() if r["scheduled_for"] else None, "Report": r["report_url"]}))
    for r in L[1]:
        scans = _j(r["scans"]) or []
        names = ", ".join(" ".join(filter(None, [str(t.get("modality") or ""), str(t.get("body_part") or "")])) for t in scans if isinstance(t, dict)) or None
        add(r["owner"], {"diagnostic_centre"}, _svc("diagnostic_scan", r, r["patient_id"], None, None, r["created_at"],
            f"Imaging · {names or ''}".strip(" ·"), r["total_amount"], r["status"], {
                "Scans": names, "Branch": r["branch"], "Referring doctor": r["referring_doctor_id"],
                "Scheduled": r["scheduled_for"].isoformat() if r["scheduled_for"] else None,
                "Report": r["report_url"], "Images": r["images_url"]}))

    allsv = [x for v in by.values() for x in v]
    pids = list({x["patient_id"] for x in allsv if x["patient_id"]})
    users = {u["id"]: u for u in await conn.fetch(
        "SELECT id, name, phone FROM public.users WHERE id = ANY($1::text[])", pids)} if pids else {}
    for uid in list(by):
        out = []
        for x in by[uid]:
            u = users.get(x["patient_id"])
            if u:
                x["patient_name"] = x["patient_name"] or u["name"]
                x["patient_phone"] = x["patient_phone"] or u["phone"]
            x["details"] = {k: v for k, v in x["details"].items() if v not in (None, "", "— / —")}
            if not _is_test(x["patient_name"]):
                out.append(x)
        out.sort(key=lambda x: x["date"] or "", reverse=True)
        by[uid] = out
    return by


async def fetch_all_provider_services() -> Dict[str, List[Dict[str, Any]]]:
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        return await _collect(conn, await _id_map(conn))


async def fetch_provider_services(user_id: str) -> Dict[str, Any]:
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        idmap = await _id_map(conn, [user_id])
        if user_id not in idmap:
            return {}
        by = await _collect(conn, idmap)
    me = idmap[user_id]
    return {"user_id": user_id, "vertical": me["vertical"], "profile_id": me.get("profile_id"),
            "services": by.get(user_id, [])}
