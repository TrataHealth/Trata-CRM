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
