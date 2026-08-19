"""
Trata CRM ⇄ Supabase (shared Postgres) — Phase A: read-only mirror.

The Patient App, Provider App and Admin App all write to the same Supabase project;
this module exposes an asyncpg connection pool so the CRM can read live data
(cases, patients, providers, KYC) directly from the shared Postgres instead of
proxying via the Admin App's REST layer.

WRITES are intentionally not exposed here yet — Phase B will introduce SQLAlchemy
models + writes once we finish auditing which tables the CRM owns vs. shares.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


def _get_dsn() -> str:
    """Read DATABASE_URL lazily so it works regardless of load_dotenv() timing."""
    return os.environ.get("DATABASE_URL", "")


def is_configured() -> bool:
    return bool(_get_dsn())


async def get_pool() -> asyncpg.Pool:
    """Lazy-initialise the shared asyncpg pool. Transaction-pooler-safe."""
    global _pool
    if _pool is None:
        dsn = _get_dsn()
        if not dsn:
            raise RuntimeError("DATABASE_URL not configured (Supabase disabled)")
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=1,
            max_size=5,
            statement_cache_size=0,        # required for the transaction pooler
            max_inactive_connection_lifetime=1800,
            command_timeout=30,
        )
        logger.info("supabase asyncpg pool ready")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


# ── low-level helpers ────────────────────────────────────────────────────────
def _row(r: Optional[asyncpg.Record]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    d = dict(r)
    # Decode any *_json / json / jsonb columns that came back as strings
    for k, v in list(d.items()):
        if isinstance(v, str) and v and v[0] in "[{":
            try:
                d[k] = json.loads(v)
            except Exception:
                pass
    return d


def _rows(rs: List[asyncpg.Record]) -> List[Dict[str, Any]]:
    return [_row(r) for r in rs]  # type: ignore[misc]


# ── domain queries used by the CRM Network tab (read-only for now) ──────────
async def fetch_emergency_cases(status: Optional[str] = None,
                                case_type: Optional[str] = None,
                                limit: int = 200) -> List[Dict[str, Any]]:
    """Live board of every emergency case in the shared platform."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        parts = ["1=1"]
        args: List[Any] = []
        if status:
            args.append(status.upper())
            parts.append(f"upper(status) = ${len(args)}")
        if case_type:
            args.append(case_type)
            parts.append(f"case_type = ${len(args)}")
        args.append(limit)
        q = f"""
            SELECT id, customer_id, customer_phone, patient_id, case_type, priority,
                   status, location::text as location_json, patient_profile::text as patient_profile_json,
                   reason, paramedic_id, hospital_id, ambulance_provider_id, ambulance_id,
                   ambulance_location::text as ambulance_location_json,
                   timeline::text as timeline_json, vital_signs::text as vital_signs_json,
                   estimated_response_time, distance, rating, feedback,
                   created_at, updated_at
              FROM public.emergency_cases
             WHERE {' AND '.join(parts)}
          ORDER BY created_at DESC NULLS LAST
             LIMIT ${len(args)}
        """
        rs = await conn.fetch(q, *args)
    # Normalise the JSON columns back into dicts for the frontend.
    out: List[Dict[str, Any]] = []
    for r in _rows(rs):
        for src, dst in [("location_json", "location"), ("patient_profile_json", "patient_profile"),
                         ("ambulance_location_json", "ambulance_location"),
                         ("timeline_json", "timeline"), ("vital_signs_json", "vital_signs")]:
            v = r.pop(src, None)
            if isinstance(v, str) and v:
                try: r[dst] = json.loads(v)
                except Exception: r[dst] = None
            else:
                r[dst] = v
        out.append(r)
    return out


async def fetch_case(case_id: str) -> Optional[Dict[str, Any]]:
    """One case in full detail."""
    cases = await fetch_emergency_cases(limit=1)
    # Reuse fetch_emergency_cases so JSON normalisation is consistent, but with an id filter
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM public.emergency_cases WHERE id = $1", case_id)
    return _row(r)


async def fetch_patients(q: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    """Every patient (customer_profiles + users) — with optional name/phone search."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        args: List[Any] = []
        clauses = ["u.role = 'patient' OR u.user_type = 'patient'"]
        if q:
            args.append(f"%{q.lower()}%")
            clauses.append(f"(lower(coalesce(u.name,'')) LIKE ${len(args)} OR u.phone LIKE ${len(args)})")
        args.append(limit)
        sql = f"""
            SELECT u.id            AS user_id,
                   u.phone,
                   u.name,
                   u.email,
                   u.dob,
                   u.is_active,
                   u.verification_status,
                   u.created_at    AS registered_at,
                   u.last_login_at,
                   cp.patient_id,
                   cp.basic_info::text  AS basic_info_json,
                   cp.medical_info::text AS medical_info_json,
                   (SELECT count(*) FROM public.emergency_cases ec WHERE ec.customer_id = u.id) AS cases_count,
                   (SELECT max(ec.created_at) FROM public.emergency_cases ec WHERE ec.customer_id = u.id) AS latest_case_at
              FROM public.users u
         LEFT JOIN public.customer_profiles cp ON cp.user_id = u.id
             WHERE {' AND '.join(clauses)}
          ORDER BY latest_case_at DESC NULLS LAST, registered_at DESC NULLS LAST
             LIMIT ${len(args)}
        """
        rs = await conn.fetch(sql, *args)
    out = []
    for r in _rows(rs):
        for src, dst in [("basic_info_json", "basic_info"), ("medical_info_json", "medical_info")]:
            v = r.pop(src, None)
            if isinstance(v, str) and v:
                try: r[dst] = json.loads(v)
                except Exception: r[dst] = None
            else:
                r[dst] = v
        out.append(r)
    return out


async def fetch_network_stats() -> Dict[str, Any]:
    """One-shot aggregate for the master admin dashboard."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
              (SELECT count(*) FROM public.users)                                       AS users_total,
              (SELECT count(*) FROM public.users WHERE role = 'patient' OR user_type = 'patient') AS patients,
              (SELECT count(*) FROM public.users WHERE role = 'ambulance_provider')     AS ambulance_providers,
              (SELECT count(*) FROM public.users WHERE role = 'hospital')               AS hospitals,
              (SELECT count(*) FROM public.users WHERE role = 'doctor')                 AS doctors,
              (SELECT count(*) FROM public.users WHERE role IN ('lab','pathologist'))   AS pathologists,
              (SELECT count(*) FROM public.users WHERE role = 'paramedic')              AS paramedics,
              (SELECT count(*) FROM public.users WHERE role = 'pharmacy')               AS pharmacies,
              (SELECT count(*) FROM public.emergency_cases)                             AS cases_total,
              (SELECT count(*) FROM public.emergency_cases WHERE upper(status) IN ('ACTIVE','IN_PROGRESS','DISPATCHED')) AS cases_active,
              (SELECT count(*) FROM public.emergency_cases WHERE created_at >= now() - interval '1 day')                 AS cases_today,
              (SELECT count(*) FROM public.emergency_cases WHERE created_at >= now() - interval '7 days')                AS cases_week,
              (SELECT count(*) FROM public.ehr_records)                                                                  AS ehr_records,
              (SELECT count(*) FROM public.zones)                                                                        AS zones,
              (SELECT count(*) FROM public.health_anomalies WHERE upper(coalesce(status,'ACTIVE')) = 'ACTIVE')            AS anomalies_active
        """)
    r = dict(rows[0])
    return {
        "users":            {"total": r["users_total"], "patients": r["patients"],
                              "ambulance_providers": r["ambulance_providers"], "hospitals": r["hospitals"],
                              "doctors": r["doctors"], "pathologists": r["pathologists"],
                              "paramedics": r["paramedics"], "pharmacies": r["pharmacies"]},
        "cases":            {"total": r["cases_total"], "active": r["cases_active"],
                              "today": r["cases_today"], "week": r["cases_week"]},
        "ehr":              {"total_records": r["ehr_records"]},
        "health_guard":     {"zones": r["zones"], "anomalies_active": r["anomalies_active"]},
    }


async def fetch_kyc_overview() -> List[Dict[str, Any]]:
    """Every provider on the platform + their KYC status + latest reviewed_by/reason.
    Rolled up per user; each row is one provider ready for review."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rs = await conn.fetch("""
            SELECT u.id                    AS upstream_user_id,
                   u.phone,
                   u.name,
                   u.role,
                   u.user_type,
                   u.verification_status,
                   coalesce(ap.city, hp.city) AS city,
                   (SELECT count(*) FROM public.kyc_documents k WHERE k.user_id = u.id)                           AS docs_total,
                   (SELECT count(*) FROM public.kyc_documents k WHERE k.user_id = u.id AND lower(k.status) = 'approved') AS docs_approved,
                   (SELECT count(*) FROM public.kyc_documents k WHERE k.user_id = u.id AND lower(k.status) = 'rejected') AS docs_rejected,
                   (SELECT count(*) FROM public.kyc_documents k WHERE k.user_id = u.id AND lower(coalesce(k.status,'')) IN ('','pending','submitted','uploaded')) AS docs_pending
              FROM public.users u
         LEFT JOIN public.ambulance_providers ap ON ap.user_id = u.id
         LEFT JOIN public.hospital_profiles  hp ON hp.user_id = u.id
             WHERE u.role IN ('ambulance_provider','hospital','doctor','paramedic','lab','pathologist','pharmacy')
          ORDER BY (case when lower(coalesce(u.verification_status,'')) in ('pending','submitted','') then 0 else 1 end),
                   u.created_at DESC NULLS LAST
        """)
    return _rows(rs)


async def fetch_ambulance_providers() -> List[Dict[str, Any]]:
    """Business records for every ambulance provider."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rs = await conn.fetch("""
            SELECT ap.*, u.phone AS user_phone, u.verification_status AS user_verification_status
              FROM public.ambulance_providers ap
         LEFT JOIN public.users u ON u.id = ap.user_id
          ORDER BY ap.created_at DESC NULLS LAST
        """)
    return _rows(rs)


# ── CRM-owned tables (Phase B — read paths) ──────────────────────────────────
async def fetch_crm_contacts(type_: Optional[str] = None, stage: Optional[str] = None,
                             q: Optional[str] = None, assigned_agent_id: Optional[str] = None,
                             limit: int = 200) -> Dict[str, Any]:
    """List provider leads owned by the CRM. Mirrors the shape of GET /api/contacts."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        clauses = ["1=1"]
        args: List[Any] = []
        if type_:
            args.append(type_)
            clauses.append(f"type = ${len(args)}")
        if stage:
            args.append(stage)
            clauses.append(f"pipeline_stage = ${len(args)}")
        if assigned_agent_id:
            args.append(assigned_agent_id)
            clauses.append(f"assigned_agent_id = ${len(args)}")
        if q:
            args.append(f"%{q.lower()}%")
            clauses.append(f"(lower(name) LIKE ${len(args)} OR phone LIKE ${len(args)})")
        # count
        total_row = await conn.fetchrow(
            f"SELECT count(*) AS c FROM public.crm_provider_leads WHERE {' AND '.join(clauses)}",
            *args,
        )
        args.append(limit)
        rs = await conn.fetch(
            f"""SELECT * FROM public.crm_provider_leads
                WHERE {' AND '.join(clauses)}
             ORDER BY updated_at DESC NULLS LAST
                LIMIT ${len(args)}""",
            *args,
        )
    return {"items": _rows(rs), "total": total_row["c"]}


async def fetch_crm_contact(contact_id: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT * FROM public.crm_provider_leads WHERE id = $1", contact_id
        )
    return _row(r)


# ── Ambulance-provider PC dashboard (Phase 2 vertical slice) ────────────────
async def fetch_ambulance_provider_dashboard(user_id: str) -> Dict[str, Any]:
    """Home tiles + recent cases + fleet + earnings for one ambulance provider.
    `user_id` is public.users.id (the same id the mobile app uses)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        provider = await conn.fetchrow(
            """SELECT id, business_name, phone, city, state, status,
                      total_bookings, completed_bookings, average_rating,
                      total_earnings, created_at
                 FROM public.ambulance_providers WHERE user_id = $1""", user_id)
        if not provider:
            return {"provider": None}
        pid = provider["id"]
        kpi_row = await conn.fetchrow(
            """SELECT
                 (SELECT count(*) FROM public.emergency_cases
                    WHERE ambulance_provider_id=$1
                      AND upper(status) IN ('DISPATCHED','ACTIVE','IN_PROGRESS','AMBULANCE_ASSIGNED','EN_ROUTE')) AS active_trips,
                 (SELECT count(*) FROM public.emergency_cases
                    WHERE ambulance_provider_id=$1 AND created_at >= now() - interval '1 day') AS trips_today,
                 (SELECT count(*) FROM public.emergency_cases
                    WHERE ambulance_provider_id=$1 AND upper(status)='COMPLETED'
                      AND created_at >= now() - interval '7 days') AS trips_week,
                 (SELECT count(*) FROM public.ambulances
                    WHERE provider_id=$1) AS fleet_total,
                 (SELECT count(*) FROM public.ambulances
                    WHERE provider_id=$1 AND upper(coalesce(status,'AVAILABLE'))='AVAILABLE') AS fleet_available,
                 (SELECT count(*) FROM public.kyc_documents
                    WHERE user_id=$2 AND lower(coalesce(status,''))='approved') AS kyc_approved,
                 (SELECT count(*) FROM public.kyc_documents
                    WHERE user_id=$2 AND lower(coalesce(status,'')) IN ('','pending','submitted','uploaded')) AS kyc_pending
            """, pid, user_id)
        recent = await conn.fetch(
            """SELECT id, case_type, status, priority, customer_phone,
                      created_at, patient_profile::text AS patient_profile_json,
                      distance
                 FROM public.emergency_cases
                WHERE ambulance_provider_id=$1
             ORDER BY created_at DESC NULLS LAST
                LIMIT 10""", pid)
        fleet = await conn.fetch(
            """SELECT id, vehicle_number, ambulance_type, model, status,
                      assigned_driver_name, assigned_driver_phone,
                      current_location::text AS current_location_json,
                      insurance_expiry, fitness_expiry, permit_expiry, total_trips
                 FROM public.ambulances
                WHERE provider_id=$1
             ORDER BY vehicle_number LIMIT 20""", pid)
    recent_rows = []
    for r in _rows(recent):
        pj = r.pop("patient_profile_json", None)
        if isinstance(pj, str) and pj:
            try: r["patient_profile"] = json.loads(pj)
            except Exception: r["patient_profile"] = None
        recent_rows.append(r)
    fleet_rows = []
    for r in _rows(fleet):
        lj = r.pop("current_location_json", None)
        if isinstance(lj, str) and lj:
            try: r["current_location"] = json.loads(lj)
            except Exception: r["current_location"] = None
        fleet_rows.append(r)
    return {
        "provider": _row(provider),
        "kpis": dict(kpi_row) if kpi_row else {},
        "recent_cases": recent_rows,
        "fleet": fleet_rows,
    }


# Vertical → (table, business-name column, extra columns) so we can render every
# vertical with one generic dashboard shape.
_VERTICAL_PROFILE_SPEC = {
    "hospital":   ("hospital_profiles",  "name",         ["capacity", "available_beds", "specialization", "facilities"]),
    "doctor":     ("doctors",            "full_name",    ["specialization", "qualification", "experience", "doctor_type"]),
    "paramedic":  ("paramedic_profiles", "full_name",    ["skills", "average_response_time", "total_cases_handled", "rating"]),
    "pathology":  ("pathologists",       "lab_name",     ["registration_number", "gst_number", "display_name"]),
    "pharmacy":   ("pharmacy_profiles",  "pharmacy_name",["drug_licence_number", "pharmacist_name", "gst_number", "owner_name"]),
}


async def fetch_generic_provider_dashboard(user_id: str, vertical: str) -> Dict[str, Any]:
    """Dashboard for hospital / doctor / paramedic / pathology / pharmacy.
    Ambulance has its own richer function above."""
    spec = _VERTICAL_PROFILE_SPEC.get(vertical)
    if not spec:
        return {"provider": None}
    table, name_col, extras = spec
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Columns to always fetch when they exist. We check first to keep this table-agnostic.
        cols = {c["column_name"] for c in await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name=$1", table)}
        select_cols = ["id", "user_id"]
        if name_col in cols:                  select_cols.append(f"{name_col} AS business_name")
        for c in ("phone", "email", "city", "state", "address"):
            if c in cols:                     select_cols.append(c)
        for c in ("verification_status", "status", "is_active", "is_verified"):
            if c in cols:                     select_cols.append(c)
        for c in ("created_at", "average_rating", "rating"):
            if c in cols:                     select_cols.append(c)
        for extra in extras:
            if extra in cols:                 select_cols.append(extra)
        provider = await conn.fetchrow(
            f"SELECT {', '.join(select_cols)} FROM public.{table} WHERE user_id = $1", user_id)
        if not provider:
            return {"provider": None}
        # Cases count — meaningful for hospital (via hospital_id on cases) and paramedic (via paramedic_id).
        # NOTE: emergency_cases.hospital_id FKs to users.id, not hospital_profiles.id — so we key off
        # the caller's user_id, not provider["id"].
        cases_active = cases_today = 0
        if vertical == "hospital":
            row = await conn.fetchrow(
                """SELECT
                     (SELECT count(*) FROM public.emergency_cases WHERE hospital_id=$1
                        AND upper(status) IN ('DISPATCHED','ACTIVE','IN_PROGRESS','AMBULANCE_ASSIGNED','EN_ROUTE','HOSPITAL_ASSIGNED','ARRIVED')) AS act,
                     (SELECT count(*) FROM public.emergency_cases WHERE hospital_id=$1
                        AND created_at >= now() - interval '1 day') AS td""",
                user_id)
            if row:
                cases_active, cases_today = row["act"], row["td"]
        elif vertical == "paramedic":
            row = await conn.fetchrow(
                """SELECT
                     (SELECT count(*) FROM public.emergency_cases WHERE paramedic_id=$1
                        AND upper(status) IN ('DISPATCHED','ACTIVE','IN_PROGRESS','AMBULANCE_ASSIGNED','EN_ROUTE')) AS act,
                     (SELECT count(*) FROM public.emergency_cases WHERE paramedic_id=$1
                        AND created_at >= now() - interval '1 day') AS td""",
                provider["id"])
            if row:
                cases_active, cases_today = row["act"], row["td"]
        kyc_row = await conn.fetchrow(
            """SELECT
                 (SELECT count(*) FROM public.kyc_documents WHERE user_id=$1 AND lower(coalesce(status,''))='approved') AS approved,
                 (SELECT count(*) FROM public.kyc_documents WHERE user_id=$1 AND lower(coalesce(status,'')) IN ('','pending','submitted','uploaded')) AS pending""",
            user_id)
    return {
        "provider": _row(provider),
        "kpis": {
            "active_trips": cases_active,
            "trips_today": cases_today,
            "trips_week": 0,
            "fleet_total": None,
            "fleet_available": None,
            "kyc_approved": kyc_row["approved"] if kyc_row else 0,
            "kyc_pending":  kyc_row["pending"]  if kyc_row else 0,
        },
        "recent_cases": [],
        "fleet": [],
        "vertical": vertical,
    }


# ── Hospital Emergency Command Centre (Phase 3 — full write parity) ─────────
# NOTE on the schema: across the shared TrataHealth platform, `hospital_id` on
# emergency_cases, hospital_beds, patient_admissions etc. actually points at
# `users.id` (the hospital-owner user), NOT `hospital_profiles.id`. So every
# query in this section keys off the caller's supabase user_id directly.
async def _hospital_owner_user_id(user_id: str) -> Optional[str]:
    """Verify the caller actually owns a hospital_profiles row. Returns their
    user_id (which is the value stored as `hospital_id` on downstream tables)
    or None if they don't have a hospital profile."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT 1 FROM public.hospital_profiles WHERE user_id = $1", user_id)
    return user_id if r else None


async def fetch_hospital_command_center(user_id: str) -> Dict[str, Any]:
    """One-shot snapshot for the hospital command centre — reads all live
    counters + top-of-queue rows in a single round trip. Frontend polls this
    every ~3s to get near-realtime updates."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"hospital_id": None}
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ---- incoming (broadcasted to us, not yet accepted anywhere)
        incoming = await conn.fetch("""
            SELECT id, case_type, priority, status, customer_phone, reason,
                   location::text AS location_json,
                   patient_profile::text AS patient_profile_json,
                   vital_signs::text AS vital_signs_json,
                   estimated_response_time, distance, created_at
              FROM public.emergency_cases
             WHERE hospital_id IS NULL
               AND notified_hospitals ? $1
               AND upper(status) NOT IN ('COMPLETED','CANCELLED','AUTO_CLOSED','DECLINED')
             ORDER BY created_at DESC NULLS LAST
             LIMIT 15
        """, hospital_id)
        # ---- active (we accepted / were assigned)
        active = await conn.fetch("""
            SELECT id, case_type, priority, status, customer_phone, reason,
                   location::text AS location_json,
                   patient_profile::text AS patient_profile_json,
                   ambulance_location::text AS ambulance_location_json,
                   vital_signs::text AS vital_signs_json,
                   estimated_response_time, distance,
                   assigned_hospital_at, ambulance_id, ambulance_provider_id, paramedic_id,
                   created_at
              FROM public.emergency_cases
             WHERE hospital_id = $1
               AND upper(status) NOT IN ('COMPLETED','CANCELLED','AUTO_CLOSED','DISCHARGED')
             ORDER BY assigned_hospital_at DESC NULLS LAST, created_at DESC
             LIMIT 20
        """, hospital_id)
        # ---- beds
        beds = await conn.fetch("""
            SELECT id, bed_type, bed_number, ward, is_available, patient_id, daily_rate, updated_at
              FROM public.hospital_beds
             WHERE hospital_id = $1
             ORDER BY bed_type, bed_number
        """, hospital_id)
        # ---- admissions (in-house, not discharged)
        admissions = await conn.fetch("""
            SELECT id, admission_number, patient_id, patient_uid, admission_type, case_type,
                   triage_priority, chief_complaint, bed_id, bed_number, ward_type, status,
                   emergency_case_id, admission_time, discharge_time
              FROM public.patient_admissions
             WHERE hospital_id = $1 AND discharge_time IS NULL
             ORDER BY admission_time DESC NULLS LAST
             LIMIT 20
        """, hospital_id)
        # ---- daily stats (today, if present, else compute cheaply)
        today_row = await conn.fetchrow("""
            SELECT
              (SELECT count(*) FROM public.emergency_cases
                 WHERE hospital_id = $1 AND created_at >= now() - interval '1 day') AS cases_today,
              (SELECT count(*) FROM public.emergency_cases
                 WHERE hospital_id = $1
                   AND upper(status) IN ('AMBULANCE_ASSIGNED','EN_ROUTE','ARRIVED','ACTIVE','IN_PROGRESS')) AS cases_active,
              (SELECT count(*) FROM public.patient_admissions
                 WHERE hospital_id = $1 AND admission_time >= now() - interval '1 day') AS admissions_today,
              (SELECT count(*) FROM public.patient_admissions
                 WHERE hospital_id = $1 AND discharge_time >= now() - interval '1 day') AS discharges_today,
              (SELECT count(*) FROM public.hospital_beds
                 WHERE hospital_id = $1 AND is_available = TRUE) AS beds_free,
              (SELECT count(*) FROM public.hospital_beds
                 WHERE hospital_id = $1) AS beds_total
        """, hospital_id)

    def _normalise(rows, jsons):
        out = []
        for r in _rows(rows):
            for src, dst in jsons:
                v = r.pop(src, None)
                if isinstance(v, str) and v:
                    try: r[dst] = json.loads(v)
                    except Exception: r[dst] = None
                else:
                    r[dst] = v
            out.append(r)
        return out

    return {
        "hospital_id": hospital_id,
        "incoming": _normalise(incoming, [("location_json","location"),
                                          ("patient_profile_json","patient_profile"),
                                          ("vital_signs_json","vital_signs")]),
        "active":   _normalise(active,   [("location_json","location"),
                                          ("patient_profile_json","patient_profile"),
                                          ("ambulance_location_json","ambulance_location"),
                                          ("vital_signs_json","vital_signs")]),
        "beds":     _rows(beds),
        "admissions": _rows(admissions),
        "stats":    dict(today_row) if today_row else {},
    }


async def accept_emergency_case(user_id: str, case_id: str) -> Dict[str, Any]:
    """Hospital accepts a broadcasted case. Sets hospital_id, assigned_hospital_at,
    status → HOSPITAL_ASSIGNED, and creates a hospital_cases lifecycle row (which
    is what case_chats FK against). Idempotent when we're already assigned."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"success": False, "reason": "hospital_profile_missing"}
    import uuid as _uuid
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, hospital_id, status, patient_id, customer_id FROM public.emergency_cases WHERE id=$1",
            case_id)
        if not row:
            return {"success": False, "reason": "case_not_found"}
        if row["hospital_id"] and row["hospital_id"] != hospital_id:
            return {"success": False, "reason": "already_assigned_to_other_hospital"}
        # Get hospital name from profile
        hp = await conn.fetchrow(
            "SELECT name FROM public.hospital_profiles WHERE user_id = $1", user_id)
        hospital_name = hp["name"] if hp else None
        await conn.execute("""
            UPDATE public.emergency_cases
               SET hospital_id = $1,
                   assigned_hospital_at = COALESCE(assigned_hospital_at, now()),
                   status = 'HOSPITAL_ASSIGNED',
                   updated_at = now()
             WHERE id = $2
        """, hospital_id, case_id)
        # Lazily create the hospital_cases lifecycle row so chat/admission FKs work
        existing_hc = await conn.fetchval(
            "SELECT id FROM public.hospital_cases WHERE emergency_case_id = $1 AND hospital_id = $2",
            case_id, hospital_id)
        if not existing_hc:
            hc_id = str(_uuid.uuid4())
            await conn.execute("""
                INSERT INTO public.hospital_cases
                  (id, emergency_case_id, customer_id, patient_id, hospital_id, hospital_name,
                   admission_type, status, phase, chat_enabled, created_at, updated_at)
                VALUES ($1::text, $2, $3, $4, $5, $6, 'emergency', 'accepted', 'incoming', TRUE, now(), now())
            """, hc_id, case_id, row["customer_id"], row["patient_id"], hospital_id, hospital_name)
            existing_hc = hc_id
    return {"success": True, "case_id": case_id, "hospital_id": hospital_id, "hospital_case_id": existing_hc}


async def decline_emergency_case(user_id: str, case_id: str, reason: Optional[str]) -> Dict[str, Any]:
    """Hospital declines a broadcasted case — removes our id from notified_hospitals."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"success": False, "reason": "hospital_profile_missing"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE public.emergency_cases
               SET notified_hospitals = COALESCE(notified_hospitals, '[]'::jsonb) - $1,
                   updated_at = now()
             WHERE id = $2
        """, hospital_id, case_id)
    return {"success": True, "case_id": case_id, "reason_recorded": bool(reason)}


async def toggle_bed(user_id: str, bed_id: str, is_available: bool,
                     reason: str = "manual_toggle") -> Dict[str, Any]:
    """Flip a bed's availability + write a bed_status_logs row for audit."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"success": False, "reason": "hospital_profile_missing"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        bed = await conn.fetchrow(
            "SELECT id, bed_type, is_available FROM public.hospital_beds WHERE id=$1 AND hospital_id=$2",
            bed_id, hospital_id)
        if not bed:
            return {"success": False, "reason": "bed_not_found"}
        prev_free = await conn.fetchval(
            "SELECT count(*) FROM public.hospital_beds WHERE hospital_id=$1 AND bed_type=$2 AND is_available=TRUE",
            hospital_id, bed["bed_type"])
        await conn.execute(
            "UPDATE public.hospital_beds SET is_available=$1, updated_at=now() WHERE id=$2",
            is_available, bed_id)
        new_free = await conn.fetchval(
            "SELECT count(*) FROM public.hospital_beds WHERE hospital_id=$1 AND bed_type=$2 AND is_available=TRUE",
            hospital_id, bed["bed_type"])
        await conn.execute("""
            INSERT INTO public.bed_status_logs
              (id, hospital_id, bed_type, previous_available, new_available, change_reason, changed_by, created_at)
            VALUES ($1::text, $2, $3, $4, $5, $6, $7, now())
        """, str(__import__("uuid").uuid4()), hospital_id, bed["bed_type"], prev_free, new_free, reason, user_id)
    return {"success": True, "bed_id": bed_id, "is_available": is_available,
            "previous_available": prev_free, "new_available": new_free}


async def add_hospital_bed(user_id: str, bed_type: str, bed_number: str,
                           ward: Optional[str], daily_rate: Optional[float]) -> Dict[str, Any]:
    """Create a new bed row for this hospital."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"success": False, "reason": "hospital_profile_missing"}
    import uuid as _uuid
    bed_id = str(_uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO public.hospital_beds
              (id, hospital_id, bed_type, bed_number, ward, is_available, daily_rate, created_at, updated_at)
            VALUES ($1::text, $2, $3, $4, $5, TRUE, $6, now(), now())
        """, bed_id, hospital_id, bed_type, bed_number, ward, daily_rate)
    return {"success": True, "bed_id": bed_id}


async def fetch_case_chat(user_id: str, case_id: str) -> List[Dict[str, Any]]:
    """`case_id` here is the emergency_case_id from the URL. case_chats FKs
    against hospital_cases.id, so we translate first."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        hc_id = await conn.fetchval(
            "SELECT id FROM public.hospital_cases WHERE emergency_case_id=$1 AND hospital_id=$2",
            case_id, hospital_id)
        if not hc_id:
            return []
        rs = await conn.fetch("""
            SELECT id, case_id, sender_id, sender_type, message_type, content, file_url,
                   delivered, created_at
              FROM public.case_chats
             WHERE case_id = $1
             ORDER BY created_at ASC
             LIMIT 200
        """, hc_id)
    return _rows(rs)


async def send_case_chat(user_id: str, case_id: str, content: str,
                         message_type: str = "text") -> Dict[str, Any]:
    """`case_id` is emergency_case_id. We translate to hospital_cases.id before
    inserting into case_chats."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"success": False, "reason": "hospital_profile_missing"}
    import uuid as _uuid
    msg_id = str(_uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        hc_id = await conn.fetchval(
            "SELECT id FROM public.hospital_cases WHERE emergency_case_id=$1 AND hospital_id=$2",
            case_id, hospital_id)
        if not hc_id:
            return {"success": False, "reason": "case_not_accepted_by_us"}
        await conn.execute("""
            INSERT INTO public.case_chats
              (id, case_id, sender_id, sender_type, message_type, content, delivered, created_at)
            VALUES ($1::text, $2, $3, 'hospital', $4, $5, TRUE, now())
        """, msg_id, hc_id, user_id, message_type, content)
    return {"success": True, "message_id": msg_id}


async def admit_from_case(user_id: str, case_id: str, bed_id: Optional[str],
                          chief_complaint: Optional[str],
                          triage_priority: Optional[str]) -> Dict[str, Any]:
    """Create a patient_admissions row from an active emergency case, mark the
    case as ARRIVED, and mark the assigned bed occupied."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"success": False, "reason": "hospital_profile_missing"}
    import uuid as _uuid
    admission_id = str(_uuid.uuid4())
    admission_number = f"ADM-{__import__('datetime').datetime.utcnow().strftime('%Y%m%d')}-{admission_id[:6].upper()}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        case = await conn.fetchrow(
            "SELECT id, patient_id, customer_id, customer_phone, patient_profile::text AS pp, case_type, hospital_id FROM public.emergency_cases WHERE id=$1",
            case_id)
        if not case or case["hospital_id"] != hospital_id:
            return {"success": False, "reason": "case_not_ours"}
        # patient_admissions.patient_id FKs into users(id). For walk-in / unlinked
        # emergency cases (common when the SOS was placed anonymously), we lazily
        # create a synthetic "walk-in" user so admission still records correctly.
        patient_id = case["patient_id"] or case["customer_id"]
        if not patient_id:
            walk_in_id = str(_uuid.uuid4())
            walk_phone = case["customer_phone"] or f"walkin-{case_id[:8]}"
            walk_name = "Walk-in patient"
            try:
                pp = json.loads(case["pp"]) if case["pp"] else None
                walk_name = (pp or {}).get("basicInfo", {}).get("fullName") or walk_name
            except Exception:
                pass
            await conn.execute("""
                INSERT INTO public.users (id, phone, name, role, is_active, created_at)
                VALUES ($1, $2, $3, 'patient', TRUE, now())
                ON CONFLICT (phone) DO NOTHING
            """, walk_in_id, walk_phone, walk_name)
            row = await conn.fetchrow("SELECT id FROM public.users WHERE phone = $1", walk_phone)
            patient_id = str(row["id"]) if row else walk_in_id
            # Note: emergency_cases.patient_id is varchar(20) — can't fit a full
            # 36-char UUID, so we intentionally DON'T back-link the walk-in user
            # onto the emergency case. Downstream tables (patient_admissions,
            # hospital_beds) accept 36-char patient_id and use the full UUID.
        bed_number = None; ward = None
        if bed_id:
            bed = await conn.fetchrow(
                "SELECT bed_number, ward, bed_type FROM public.hospital_beds WHERE id=$1 AND hospital_id=$2 AND is_available=TRUE",
                bed_id, hospital_id)
            if not bed:
                return {"success": False, "reason": "bed_unavailable"}
            bed_number = bed["bed_number"]
            ward = bed["ward"] or bed["bed_type"]
            await conn.execute(
                "UPDATE public.hospital_beds SET is_available=FALSE, patient_id=$1, updated_at=now() WHERE id=$2",
                patient_id, bed_id)
        await conn.execute("""
            INSERT INTO public.patient_admissions
              (id, admission_number, patient_id, hospital_id, admission_type, case_type,
               source, triage_priority, chief_complaint, bed_id, bed_number, ward_type,
               status, emergency_case_id, admission_time, created_at, updated_at)
            VALUES ($1::text, $2, $3, $4, 'emergency', $5, 'ambulance', $6, $7, $8, $9, $10,
                    'admitted', $11, now(), now(), now())
        """, admission_id, admission_number, patient_id, hospital_id,
            case["case_type"], triage_priority or "medium", chief_complaint,
            bed_id, bed_number, ward, case_id)
        await conn.execute("""
            UPDATE public.emergency_cases
               SET status = 'ARRIVED', updated_at = now()
             WHERE id = $1
        """, case_id)
    return {"success": True, "admission_id": admission_id, "admission_number": admission_number}


async def discharge_patient(user_id: str, admission_id: str,
                            outcome: Optional[str], notes: Optional[str]) -> Dict[str, Any]:
    """Set discharge_time + status=discharged, free the bed, and optionally append
    an admission_notes row with the discharge summary."""
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id:
        return {"success": False, "reason": "hospital_profile_missing"}
    import uuid as _uuid
    pool = await get_pool()
    async with pool.acquire() as conn:
        adm = await conn.fetchrow(
            "SELECT id, bed_id, emergency_case_id, hospital_id FROM public.patient_admissions WHERE id=$1",
            admission_id)
        if not adm or adm["hospital_id"] != hospital_id:
            return {"success": False, "reason": "admission_not_ours"}
        await conn.execute("""
            UPDATE public.patient_admissions
               SET status = 'discharged', discharge_time = now(), updated_at = now()
             WHERE id = $1
        """, admission_id)
        if adm["bed_id"]:
            await conn.execute(
                "UPDATE public.hospital_beds SET is_available=TRUE, patient_id=NULL, updated_at=now() WHERE id=$1",
                adm["bed_id"])
        if adm["emergency_case_id"]:
            await conn.execute(
                "UPDATE public.emergency_cases SET status='COMPLETED', updated_at=now() WHERE id=$1",
                adm["emergency_case_id"])
        if notes:
            await conn.execute("""
                INSERT INTO public.admission_notes
                  (id, admission_id, note_type, title, content, author_id, author_role, is_critical, created_at)
                VALUES ($1::text, $2, 'discharge', 'Discharge summary', $3, $4, 'hospital', FALSE, now())
            """, str(_uuid.uuid4()), admission_id, notes, user_id)
    return {"success": True, "outcome": outcome or "discharged"}


# ── Full vertical profile fetch (Iter 36 · Profile parity with mobile app) ──
_PROFILE_TABLE_BY_VERTICAL = {
    "hospital":  "hospital_profiles",
    "ambulance": "ambulance_providers",
    "doctor":    "doctors",
    "pathology": "pathologists",
}


async def fetch_full_provider_profile(user_id: str, vertical: str) -> Optional[Dict[str, Any]]:
    """Return the full vertical-specific profile row from Supabase (same one the
    mobile Provider App reads). JSON columns are already returned as jsonb by
    asyncpg. Returns None if the vertical is unsupported OR no profile row
    exists yet."""
    table = _PROFILE_TABLE_BY_VERTICAL.get(vertical)
    if not table:
        return None
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(f"SELECT * FROM public.{table} WHERE user_id = $1 LIMIT 1", user_id)
    if not row:
        return None
    out = dict(row)
    # Cast known jsonb text columns to python objects where asyncpg returned strings
    for k, v in list(out.items()):
        if isinstance(v, str) and v and v[0] in "{[":
            try: out[k] = json.loads(v)
            except Exception: pass
    return out


# ── Hospital staff (mirrors the mobile Provider App staff screen) ───────────
async def list_hospital_staff(user_id: str) -> List[Dict[str, Any]]:
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id: return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rs = await conn.fetch("""
            SELECT id, name, role, department, specialization, phone, email,
                   is_active, is_on_duty, shift_start, shift_end, salary,
                   hpr_id, hpr_verified_at, created_at
              FROM public.hospital_staff
             WHERE hospital_id = $1
             ORDER BY is_on_duty DESC, role, name
             LIMIT 500
        """, hospital_id)
    return _rows(rs)


async def add_hospital_staff(user_id: str, name: str, role: str,
                             department: Optional[str], specialization: Optional[str],
                             phone: Optional[str], email: Optional[str],
                             shift_start: Optional[str], shift_end: Optional[str],
                             salary: Optional[int]) -> Dict[str, Any]:
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id: return {"success": False, "reason": "hospital_profile_missing"}
    import uuid as _uuid
    sid = str(_uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO public.hospital_staff
              (id, hospital_id, name, role, department, specialization, phone, email,
               is_active, is_on_duty, shift_start, shift_end, salary, created_at, updated_at)
            VALUES ($1::text, $2, $3, $4, $5, $6, $7, $8, TRUE, FALSE, $9, $10, $11, now(), now())
        """, sid, hospital_id, name, role, department, specialization, phone, email,
             shift_start, shift_end, salary)
    return {"success": True, "id": sid}


async def toggle_hospital_staff_duty(user_id: str, staff_id: str, is_on_duty: bool) -> Dict[str, Any]:
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id: return {"success": False, "reason": "hospital_profile_missing"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.execute(
            "UPDATE public.hospital_staff SET is_on_duty=$1, updated_at=now() WHERE id=$2 AND hospital_id=$3",
            is_on_duty, staff_id, hospital_id)
    return {"success": r.endswith("1")}


async def delete_hospital_staff(user_id: str, staff_id: str) -> Dict[str, Any]:
    hospital_id = await _hospital_owner_user_id(user_id)
    if not hospital_id: return {"success": False, "reason": "hospital_profile_missing"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.execute(
            "DELETE FROM public.hospital_staff WHERE id=$1 AND hospital_id=$2",
            staff_id, hospital_id)
    return {"success": r.endswith("1")}


# ── Phase B.2 — CRM Contacts ↔ Postgres dual-write ──────────────────────────
_LEAD_COLUMNS = (
    "id", "upstream_user_id", "name", "type", "phone", "email",
    "city", "state", "address", "is_verified", "is_active",
    "pipeline_stage", "kyc_status", "kyc_id", "deal_value",
    "assigned_agent_id", "assigned_agent_name",
    "source", "onboarded_by", "onboarded_at", "avatar",
    "specialization", "pan_number", "gst_number",
    "vehicle_reg", "vehicle_make_model", "aadhaar_last4",
    "father_name", "dob", "hospital_name", "ambulance_count",
    "license_number", "lab_specialty", "pharmacy_type",
    "kyc_doc_issue_date", "kyc_doc_expiry_date", "kyc_doc_authority",
    "kyc_document_number",
    "ai_doc_prescreens", "ai_prescreen_summary", "ai_extracted_fields",
    "agent_doc_reviews", "local_decision",
    "ai_fields_applied_at", "ai_fields_applied_by",
    "last_admin_sync_at", "created_at", "updated_at",
)
_LEAD_JSON_COLS = {
    "ai_doc_prescreens", "ai_prescreen_summary", "ai_extracted_fields",
    "agent_doc_reviews", "local_decision",
}
_LEAD_TIMESTAMP_COLS = {
    "onboarded_at", "ai_fields_applied_at", "last_admin_sync_at",
    "created_at", "updated_at",
}


def _to_datetime(v):
    """Best-effort coerce ISO-8601 string / datetime → datetime for asyncpg."""
    if v is None or v == "":
        return None
    from datetime import datetime
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            # Python 3.11+ tolerates the trailing 'Z' but strip just in case
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _lead_row_from_contact(c: Dict[str, Any]) -> Dict[str, Any]:
    """Map a Mongo `contacts` doc → the columns of Postgres `crm_provider_leads`.
    Everything not present becomes NULL. JSON columns are pre-serialised;
    timestamp columns are parsed from ISO strings to datetime for asyncpg."""
    def _get(k, default=None):
        v = c.get(k, default)
        return v if v is not None else default
    row = {col: _get(col) for col in _LEAD_COLUMNS}
    # NOT NULL columns fall back to sensible defaults
    row["id"] = c.get("id") or c.get("_id")
    row["name"] = c.get("name") or c.get("business_name") or c.get("phone") or "Unnamed"
    row["type"] = c.get("type") or c.get("provider_type") or "other"
    row["phone"] = c.get("phone") or ""
    row["pipeline_stage"] = c.get("pipeline_stage") or "lead"
    # JSON columns → serialised strings for asyncpg jsonb binding
    for j in _LEAD_JSON_COLS:
        v = row.get(j)
        if v is None:
            continue
        if not isinstance(v, str):
            try:
                row[j] = json.dumps(v)
            except Exception:
                row[j] = None
    # Timestamp columns → datetime instances (Mongo stores ISO strings)
    for t in _LEAD_TIMESTAMP_COLS:
        row[t] = _to_datetime(row.get(t))
    return row


async def upsert_provider_lead(contact: Dict[str, Any]) -> Dict[str, Any]:
    """Idempotently mirror a Mongo `contacts` document to Postgres
    `crm_provider_leads`. Silently no-ops if Supabase is offline — best-effort
    dual-write, never a blocker for the primary Mongo write."""
    if not is_configured():
        return {"success": False, "reason": "supabase_offline"}
    if not contact or not (contact.get("id") or contact.get("_id")):
        return {"success": False, "reason": "missing_id"}
    if not contact.get("phone"):
        return {"success": False, "reason": "missing_phone"}

    row = _lead_row_from_contact(contact)
    cols = list(row.keys())
    values = [row[c] for c in cols]
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}"
        for c in cols
        if c not in ("id", "created_at", "updated_at")
    )
    sql = f"""
        INSERT INTO public.crm_provider_leads ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = now()
    """
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(sql, *values)
        return {"success": True, "id": row["id"]}
    except Exception as e:
        logger.warning(f"upsert_provider_lead({row.get('id')}) failed: {e}")
        return {"success": False, "reason": str(e)}


# ── Provider KYC document uploader (Phase C — all verticals) ───────────────
async def list_provider_kyc_documents(user_id: str) -> List[Dict[str, Any]]:
    """List every KYC doc this provider has uploaded — no file blobs."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rs = await conn.fetch("""
            SELECT id, document_name, document_type, doc_category, status,
                   rejection_reason, rejection_comment,
                   submitted_at, reviewed_at, reviewed_by, created_at
              FROM public.kyc_documents
             WHERE user_id = $1
             ORDER BY created_at DESC
             LIMIT 200
        """, user_id)
    return _rows(rs)


async def upload_provider_kyc_document(user_id: str, provider_type: str,
                                       document_type: str, document_name: str,
                                       file_b64: str,
                                       doc_category: Optional[str] = None) -> Dict[str, Any]:
    """Persist a KYC doc into the shared `kyc_documents` table as base64 so
    the mobile KYC review flow (which reads `file_data`) picks it up
    immediately. Reject files larger than 4 MB."""
    if not file_b64:
        return {"success": False, "reason": "empty_file"}
    approx_bytes = int(len(file_b64) * 3 / 4)
    if approx_bytes > 4 * 1024 * 1024:
        return {"success": False, "reason": "file_too_large"}
    import uuid as _uuid
    doc_id = str(_uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO public.kyc_documents
              (id, user_id, provider_type, document_name, document_type,
               doc_category, file_data, status, submitted_at, created_at, updated_at)
            VALUES ($1::text, $2, $3, $4, $5, $6, $7, 'submitted',
                    now(), now(), now())
        """, doc_id, user_id, provider_type, document_name, document_type,
            doc_category or provider_type, file_b64)
    return {"success": True, "document_id": doc_id, "status": "submitted"}


# ── Legacy hospital-scoped wrappers (kept for backward compat) ──────────────
_HOSPITAL_KYC_DOC_TYPES = (
    "hospital_license", "nabh_certificate", "gst_certificate", "pan_card",
    "owner_id_proof", "clinical_establishment_reg", "fire_safety_noc",
    "biomedical_waste_auth", "pharmacy_license", "other",
)


async def list_hospital_kyc_documents(user_id: str) -> List[Dict[str, Any]]:
    if not await _hospital_owner_user_id(user_id):
        return []
    return await list_provider_kyc_documents(user_id)


async def upload_hospital_kyc_document(user_id: str, document_type: str,
                                       document_name: str, file_b64: str,
                                       doc_category: Optional[str] = None) -> Dict[str, Any]:
    if not await _hospital_owner_user_id(user_id):
        return {"success": False, "reason": "hospital_profile_missing"}
    if document_type not in _HOSPITAL_KYC_DOC_TYPES:
        return {"success": False, "reason": "invalid_document_type"}
    return await upload_provider_kyc_document(
        user_id, "hospital", document_type, document_name, file_b64,
        doc_category or "hospital_operations")


# ── Admin-driven provider onboarding + one-click KYC approval (Iter 37) ─────
_SB_ROLE_BY_VERTICAL = {
    "hospital": "hospital",
    "ambulance": "ambulance_provider",
    "doctor": "doctor",
    "pathology": "pathologist",
}


async def create_provider_from_admin(phone: str, name: str, vertical: str,
                                     city: Optional[str], state: Optional[str],
                                     email: Optional[str], address: Optional[str],
                                     onboarded_by: Optional[str]) -> Dict[str, Any]:
    """Create a provider directly in shared Supabase: `users` row + vertical
    profile row. Idempotent on phone — returns the existing user_id if the
    phone already has a row. Runs one transaction so a mid-flight failure
    doesn't leave orphaned users."""
    sb_role = _SB_ROLE_BY_VERTICAL.get(vertical)
    if not sb_role:
        return {"success": False, "reason": f"unsupported_vertical:{vertical}"}
    import uuid as _uuid
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 1) users row — reuse if the phone is already registered.
            existing = await conn.fetchrow(
                "SELECT id, role, verification_status FROM public.users WHERE phone IN ($1, $2) LIMIT 1",
                phone, f"+91{phone}")
            if existing:
                user_id = str(existing["id"])
                # If the existing account is a wildly different role, don't clobber.
                if existing["role"] and existing["role"] not in {sb_role, "patient", None}:
                    return {"success": False, "reason": f"phone_already_registered_as:{existing['role']}", "user_id": user_id}
            else:
                user_id = str(_uuid.uuid4())
                await conn.execute(
                    """INSERT INTO public.users
                         (id, phone, name, role, is_active, verification_status, email, created_at)
                       VALUES ($1, $2, $3, $4, TRUE, 'pending', $5, now())""",
                    user_id, phone, name, sb_role, email)
            # 2) vertical profile — only create if absent.
            prof_id = str(_uuid.uuid4())
            if vertical == "hospital":
                await conn.execute("""
                    INSERT INTO public.hospital_profiles
                      (id, user_id, name, phone, city, state, address, verification_status, created_at)
                    SELECT $1::text, $2::text, $3, $4, $5, $6, $7, 'pending', now()
                     WHERE NOT EXISTS (SELECT 1 FROM public.hospital_profiles WHERE user_id = $2::text)
                """, prof_id, user_id, name, phone, city, state, address)
            elif vertical == "ambulance":
                await conn.execute("""
                    INSERT INTO public.ambulance_providers
                      (id, user_id, business_name, owner_name, phone, city, state, address, email, status, created_at)
                    SELECT $1::text, $2::text, $3, $3, $4, $5, $6, $7, $8, 'pending', now()
                     WHERE NOT EXISTS (SELECT 1 FROM public.ambulance_providers WHERE user_id = $2::text)
                """, prof_id, user_id, name, phone, city, state, address, email)
            elif vertical == "doctor":
                await conn.execute("""
                    INSERT INTO public.doctors
                      (id, user_id, full_name, phone, email, city, state, is_verified, is_active, created_at)
                    SELECT $1::text, $2::text, $3, $4, $5, $6, $7, FALSE, TRUE, now()
                     WHERE NOT EXISTS (SELECT 1 FROM public.doctors WHERE user_id = $2::text)
                """, prof_id, user_id, name, phone, email, city, state)
            elif vertical == "pathology":
                await conn.execute("""
                    INSERT INTO public.pathologists
                      (id, user_id, name, lab_name, phone, city, state, address, email, status, is_active, created_at)
                    SELECT $1::text, $2::text, $3, $3, $4, $5, $6, $7, $8, 'pending', TRUE, now()
                     WHERE NOT EXISTS (SELECT 1 FROM public.pathologists WHERE user_id = $2::text)
                """, prof_id, user_id, name, phone, city, state, address, email)
    return {"success": True, "user_id": user_id, "role": sb_role,
            "already_existed": bool(existing) if 'existing' in locals() else False}


async def admin_upload_kyc_document(user_id: str, vertical: str,
                                    document_type: str, document_name: str,
                                    file_b64: str, admin_name: Optional[str]) -> Dict[str, Any]:
    """Admin proxy-uploads a KYC doc on behalf of the provider. Same target
    table (`kyc_documents`) so the mobile Provider App + Trata Admin App see
    it live. We tag the doc name with `[Admin] …` so reviewers instantly
    know the origin (schema stays untouched)."""
    if not file_b64:
        return {"success": False, "reason": "empty_file"}
    approx_bytes = int(len(file_b64) * 3 / 4)
    if approx_bytes > 4 * 1024 * 1024:
        return {"success": False, "reason": "file_too_large"}
    tagged_name = f"[Admin] {document_name.strip() or document_type}"
    import uuid as _uuid
    doc_id = str(_uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO public.kyc_documents
              (id, user_id, provider_type, document_name, document_type,
               doc_category, file_data, status, submitted_at,
               reviewed_by, created_at, updated_at)
            VALUES ($1::text, $2, $3, $4, $5, $6, $7, 'submitted', now(),
                    $8, now(), now())
        """, doc_id, user_id, vertical, tagged_name, document_type,
             vertical, file_b64, admin_name or "master_admin")
    return {"success": True, "document_id": doc_id, "status": "submitted", "uploaded_by": "admin"}


_PROFILE_APPROVE_SQL = {
    "hospital":  "UPDATE public.hospital_profiles SET verification_status='approved', updated_at=now() WHERE user_id=$1::text",
    "ambulance": "UPDATE public.ambulance_providers SET status='approved', approved_at=now(), updated_at=now() WHERE user_id=$1::text",
    "doctor":    "UPDATE public.doctors SET is_verified=TRUE, updated_at=now() WHERE user_id=$1::text",
    "pathology": "UPDATE public.pathologists SET status='approved', is_verified=TRUE, approved_at=now(), updated_at=now() WHERE user_id=$1::text",
}


async def approve_all_provider_kyc(user_id: str, vertical: str,
                                   admin_name: Optional[str]) -> Dict[str, Any]:
    """One-click bulk approval:
      • Every `kyc_documents` row for this user with status in
        (submitted | pending | uploaded | '' ) → approved
      • The vertical profile → verified/approved
      • `users.verification_status` → approved
    Returns per-vertical counts so the UI can render a receipt."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            r = await conn.execute("""
                UPDATE public.kyc_documents
                   SET status='approved', reviewed_at=now(),
                       reviewed_by=$2, updated_at=now()
                 WHERE user_id=$1
                   AND lower(coalesce(status,'')) IN ('','pending','submitted','uploaded')
            """, user_id, admin_name or "master_admin")
            approved_docs = int(r.rsplit(" ", 1)[-1] or 0)
            await conn.execute(
                "UPDATE public.users SET verification_status='approved', updated_at=now() WHERE id=$1",
                user_id)
            prof_sql = _PROFILE_APPROVE_SQL.get(vertical)
            if prof_sql:
                await conn.execute(prof_sql, user_id)
    return {"success": True, "docs_approved": approved_docs, "vertical": vertical}


async def fetch_provider_summary(user_id: str) -> Optional[Dict[str, Any]]:
    """Small identity blob (name, phone, role, verification_status) used by
    the admin onboarding uploader header."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, phone, role, verification_status, email, is_active, created_at
              FROM public.users WHERE id = $1
        """, user_id)
    return _row(row)


async def list_admin_onboarded_providers(limit: int = 100) -> List[Dict[str, Any]]:
    """List every provider (hospital / ambulance / doctor / pathology) with a
    quick KYC progress snapshot so the admin onboarding page can render a
    roster. Newest first."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rs = await conn.fetch("""
            SELECT u.id, u.name, u.phone, u.role, u.verification_status, u.created_at,
                   (SELECT count(*) FROM public.kyc_documents k
                      WHERE k.user_id = u.id) AS docs_total,
                   (SELECT count(*) FROM public.kyc_documents k
                      WHERE k.user_id = u.id AND lower(coalesce(k.status,''))='approved') AS docs_approved,
                   (SELECT count(*) FROM public.kyc_documents k
                      WHERE k.user_id = u.id AND lower(coalesce(k.status,'')) IN ('','pending','submitted','uploaded')) AS docs_pending
              FROM public.users u
             WHERE u.role IN ('hospital','ambulance_provider','doctor','pathologist')
             ORDER BY u.created_at DESC NULLS LAST
             LIMIT $1
        """, limit)
    return _rows(rs)


# ── Patients (shared with mobile Provider App · Iter 38) ────────────────────
async def list_all_patients_admin(q: Optional[str], limit: int = 200) -> List[Dict[str, Any]]:
    """Master-admin roster: every user with role='patient', with a rollup of
    total emergency cases + appointments + admissions so the roster can show
    activity counts alongside identity."""
    where = ["u.role = 'patient'"]
    args: List[Any] = []
    if q and q.strip():
        args.append(f"%{q.strip().lower()}%")
        where.append(f"(lower(coalesce(u.name,'')) LIKE ${len(args)} OR u.phone LIKE ${len(args)})")
    args.append(limit)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rs = await conn.fetch(f"""
            SELECT u.id, u.name, u.phone, u.email, u.dob, u.patient_id, u.is_active,
                   u.verification_status, u.created_at, u.last_login_at,
                   (SELECT count(*) FROM public.emergency_cases c WHERE c.patient_id = u.id OR c.customer_id = u.id) AS cases,
                   (SELECT count(*) FROM public.appointments a WHERE a.patient_id = u.id)                          AS appts,
                   (SELECT count(*) FROM public.patient_admissions ad WHERE ad.patient_id = u.id)                  AS admits
              FROM public.users u
             WHERE {' AND '.join(where)}
             ORDER BY u.created_at DESC NULLS LAST
             LIMIT ${len(args)}
        """, *args)
    return _rows(rs)


async def list_hospital_patients_for_provider(hospital_user_id: str, q: Optional[str],
                                              limit: int = 200) -> List[Dict[str, Any]]:
    """Provider-scoped roster for a hospital: every `hospital_patients` row
    plus the patient's `users` phone/name if we can match by phone."""
    hospital_id = await _hospital_owner_user_id(hospital_user_id)
    if not hospital_id:
        return []
    where = ["hp.hospital_id = $1"]
    args: List[Any] = [hospital_id]
    if q and q.strip():
        args.append(f"%{q.strip().lower()}%")
        where.append(f"(lower(coalesce(hp.name,'')) LIKE ${len(args)} OR hp.phone LIKE ${len(args)} OR lower(coalesce(hp.diagnosis,'')) LIKE ${len(args)})")
    args.append(limit)
    pool = await get_pool()
    async with pool.acquire() as conn:
        rs = await conn.fetch(f"""
            SELECT hp.id, hp.patient_id, hp.trata_patient_id, hp.name, hp.age, hp.sex,
                   hp.phone, hp.email, hp.blood_group, hp.address, hp.allergies,
                   hp.chronic_conditions, hp.emergency_contact, hp.diagnosis,
                   hp.status, hp.admission_date, hp.discharge_date, hp.bed_id, hp.created_at
              FROM public.hospital_patients hp
             WHERE {' AND '.join(where)}
             ORDER BY hp.admission_date DESC NULLS LAST, hp.created_at DESC NULLS LAST
             LIMIT ${len(args)}
        """, *args)
    return _rows(rs)


async def _fetch_patient_associations(user_id: str, hospital_scope_id: Optional[str] = None) -> Dict[str, Any]:
    """Every case / appointment / booking a patient is linked to. If
    `hospital_scope_id` is provided, restrict to rows owned by that hospital
    (so a provider only sees their own slice)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if hospital_scope_id:
            emergencies = await conn.fetch("""
                SELECT id, case_type, priority, status, reason, hospital_id,
                       ambulance_provider_id, created_at
                  FROM public.emergency_cases
                 WHERE (patient_id = $1 OR customer_id = $1) AND hospital_id = $2
                 ORDER BY created_at DESC LIMIT 20
            """, user_id, hospital_scope_id)
            appointments = await conn.fetch("""
                SELECT id, doctor_id, hospital_id, appointment_date, time_slot,
                       reason, status, created_at
                  FROM public.appointments
                 WHERE patient_id = $1 AND hospital_id = $2
                 ORDER BY appointment_date DESC NULLS LAST, created_at DESC LIMIT 20
            """, user_id, hospital_scope_id)
            admissions = await conn.fetch("""
                SELECT id, admission_number, admission_type, case_type, chief_complaint,
                       ward_type, bed_number, status, triage_priority, triage_time
                  FROM public.patient_admissions
                 WHERE patient_id = $1 AND hospital_id = $2
                 ORDER BY triage_time DESC NULLS LAST LIMIT 20
            """, user_id, hospital_scope_id)
        else:
            emergencies = await conn.fetch("""
                SELECT id, case_type, priority, status, reason, hospital_id,
                       ambulance_provider_id, created_at
                  FROM public.emergency_cases
                 WHERE patient_id = $1 OR customer_id = $1
                 ORDER BY created_at DESC LIMIT 20
            """, user_id)
            appointments = await conn.fetch("""
                SELECT id, doctor_id, hospital_id, appointment_date, time_slot,
                       reason, status, created_at
                  FROM public.appointments
                 WHERE patient_id = $1
                 ORDER BY appointment_date DESC NULLS LAST, created_at DESC LIMIT 20
            """, user_id)
            admissions = await conn.fetch("""
                SELECT id, admission_number, admission_type, case_type, chief_complaint,
                       ward_type, bed_number, status, triage_priority, triage_time, hospital_id
                  FROM public.patient_admissions
                 WHERE patient_id = $1
                 ORDER BY triage_time DESC NULLS LAST LIMIT 20
            """, user_id)
        ambulance_rides = await conn.fetch("""
            SELECT id, booking_id, booking_type, ambulance_type, is_emergency,
                   pickup_address, drop_address, status, scheduled_time, total_fare,
                   provider_id, created_at
              FROM public.ambulance_bookings
             WHERE customer_id = $1
             ORDER BY created_at DESC LIMIT 20
        """, user_id)
    return {
        "emergency_cases": _rows(emergencies),
        "appointments":    _rows(appointments),
        "admissions":      _rows(admissions),
        "ambulance_rides": _rows(ambulance_rides),
    }


async def fetch_patient_detail(user_id: str, hospital_scope_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the patient profile (from `users` + best-match hospital_patients row)
    plus their associated cases/appointments/admissions/bookings. If
    hospital_scope_id is set, associations are filtered to that hospital."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT id, name, phone, email, dob, patient_id, is_active,
                   verification_status, created_at, last_login_at, role, user_type
              FROM public.users WHERE id = $1
        """, user_id)
        if not user or user["role"] != "patient":
            return None
        # Latest hospital_patients row (best clinical profile the mobile app has)
        hp = await conn.fetchrow("""
            SELECT id, hospital_id, name, age, sex, blood_group, address, allergies,
                   chronic_conditions, emergency_contact, diagnosis, status,
                   admission_date, discharge_date, bed_id, phone, email
              FROM public.hospital_patients
             WHERE trata_patient_id = $1 OR patient_id = $1
                OR (phone IS NOT NULL AND phone = $2)
             ORDER BY admission_date DESC NULLS LAST, created_at DESC NULLS LAST
             LIMIT 1
        """, user_id, user["phone"])
    associations = await _fetch_patient_associations(user_id, hospital_scope_id)
    return {
        "patient": _row(user),
        "clinical_profile": _row(hp),
        **associations,
    }

