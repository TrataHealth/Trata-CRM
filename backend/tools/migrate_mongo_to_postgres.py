"""One-shot Mongo → Postgres migration for Phase B.

Copies every CRM-owned record from the local Mongo database into the shared
Supabase Postgres project:

  contacts   -> crm_provider_leads
  crm_users  -> sanjeevani_agents   (only rows that don't already exist by phone)
  activities -> agent_activities    (best-effort field mapping)
  tasks      -> agent_tasks         (best-effort field mapping)

The script is idempotent: it uses ON CONFLICT DO UPDATE for contacts and
INSERT ... ON CONFLICT DO NOTHING for the reference tables so re-running it
never duplicates rows.

Run:  cd /app/backend && python3 -m tools.migrate_mongo_to_postgres
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncpg
from motor.motor_asyncio import AsyncIOMotorClient


def _iso(v):
    """Accept datetime / str / None → return str or None. asyncpg accepts strings for timestamptz."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc).isoformat()
    return str(v)


def _to_datetime(v):
    """asyncpg wants an actual datetime for TIMESTAMPTZ. Convert ISO strings to datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        # Fromisoformat handles "2026-06-12T10:30:00+00:00"
        s = str(v)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _int_or_none(v):
    try:
        return int(v) if v not in (None, "", "None") else None
    except Exception:
        return None


def _jsonb(v):
    """Serialize a Python dict/list to JSON string for asyncpg jsonb."""
    if v is None:
        return None
    return json.dumps(v, default=str)


async def migrate_contacts(pg, mongo):
    print("\n=== contacts → crm_provider_leads ===")
    n = 0
    async for c in mongo.contacts.find({}, {"_id": 0}):
        try:
            await pg.execute(
                """
                INSERT INTO public.crm_provider_leads (
                    id, upstream_user_id, name, type, phone, email, city, state, address,
                    is_verified, is_active, pipeline_stage, kyc_status, kyc_id, deal_value,
                    assigned_agent_id, assigned_agent_name, source, onboarded_by, onboarded_at,
                    avatar, specialization, pan_number, gst_number, vehicle_reg, vehicle_make_model,
                    aadhaar_last4, father_name, dob, hospital_name, ambulance_count, license_number,
                    lab_specialty, pharmacy_type, kyc_doc_issue_date, kyc_doc_expiry_date,
                    kyc_doc_authority, kyc_document_number,
                    ai_doc_prescreens, ai_prescreen_summary, ai_extracted_fields, agent_doc_reviews,
                    local_decision, ai_fields_applied_at, ai_fields_applied_by, last_admin_sync_at,
                    created_at, updated_at
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,
                    $10,$11,$12,$13,$14,$15,
                    $16,$17,$18,$19,$20,
                    $21,$22,$23,$24,$25,$26,
                    $27,$28,$29,$30,$31,$32,
                    $33,$34,$35,$36,$37,$38,
                    $39::jsonb,$40::jsonb,$41::jsonb,$42::jsonb,
                    $43::jsonb,$44,$45,$46,
                    $47,$48
                )
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    pipeline_stage = EXCLUDED.pipeline_stage,
                    kyc_status = EXCLUDED.kyc_status,
                    assigned_agent_id = EXCLUDED.assigned_agent_id,
                    assigned_agent_name = EXCLUDED.assigned_agent_name,
                    ai_doc_prescreens = EXCLUDED.ai_doc_prescreens,
                    ai_prescreen_summary = EXCLUDED.ai_prescreen_summary,
                    ai_extracted_fields = EXCLUDED.ai_extracted_fields,
                    agent_doc_reviews = EXCLUDED.agent_doc_reviews,
                    updated_at = EXCLUDED.updated_at
                """,
                c.get("id"), c.get("upstream_user_id"), c.get("name") or "(unnamed)",
                c.get("type") or "unknown", c.get("phone") or "0000000000", c.get("email"),
                c.get("city"), c.get("state"), c.get("address"),
                bool(c.get("is_verified", False)), bool(c.get("is_active", False)),
                c.get("pipeline_stage") or "lead", c.get("kyc_status") or "pending",
                c.get("kyc_id"), float(c.get("deal_value") or 0),
                c.get("assigned_agent_id"), c.get("assigned_agent_name"), c.get("source"),
                c.get("onboarded_by"), _to_datetime(c.get("onboarded_at")),
                c.get("avatar"), c.get("specialization"),
                c.get("pan_number"), c.get("gst_number"), c.get("vehicle_reg"),
                c.get("vehicle_make_model"), c.get("aadhaar_last4"), c.get("father_name"),
                c.get("dob"), c.get("hospital_name"),
                _int_or_none(c.get("ambulance_count")), c.get("license_number"),
                c.get("lab_specialty"), c.get("pharmacy_type"),
                c.get("kyc_doc_issue_date"), c.get("kyc_doc_expiry_date"),
                c.get("kyc_doc_authority"), c.get("kyc_document_number"),
                _jsonb(c.get("ai_doc_prescreens") or {}),
                _jsonb(c.get("ai_prescreen_summary")),
                _jsonb(c.get("ai_extracted_fields") or {}),
                _jsonb(c.get("agent_doc_reviews") or {}),
                _jsonb(c.get("local_decision")),
                _to_datetime(c.get("ai_fields_applied_at")),
                c.get("ai_fields_applied_by"),
                _to_datetime(c.get("last_admin_sync_at")),
                _to_datetime(c.get("created_at")) or datetime.now(timezone.utc),
                _to_datetime(c.get("updated_at")) or datetime.now(timezone.utc),
            )
            n += 1
        except Exception as e:
            print(f"  ! skipped contact {c.get('id')} ({c.get('name')}): {e}")
    print(f"  ✓ migrated {n} contacts")


async def migrate_staff(pg, mongo):
    """Migrate every crm_users row into sanjeevani_agents. If the phone already
    exists in the shared users table (e.g. Master Admin), link to that user_id
    instead of creating a duplicate; but still create the sanjeevani_agents row
    so agent_activities / agent_tasks FKs resolve."""
    print("\n=== crm_users → sanjeevani_agents ===")
    n = 0
    async for u in mongo.crm_users.find({}, {"_id": 0}):
        try:
            phone = u.get("phone")
            crm_id = u.get("id")
            if not phone or not crm_id:
                continue
            # If a sanjeevani_agents row already exists for this crm_id, skip
            if await pg.fetchrow("SELECT id FROM public.sanjeevani_agents WHERE id = $1", crm_id):
                continue
            # Find or create the users row for the FK
            existing_user = await pg.fetchrow("SELECT id FROM public.users WHERE phone = $1", phone)
            if existing_user:
                fk_user_id = existing_user["id"]
            else:
                fk_user_id = crm_id
                await pg.execute(
                    """INSERT INTO public.users (id, phone, role, user_type, name, is_active, is_admin, verification_status, created_at)
                       VALUES ($1,$2,$3,$3,$4,true,$5,'verified',$6)
                       ON CONFLICT (id) DO NOTHING""",
                    fk_user_id, phone, u.get("role") or "sales_rep", u.get("name"),
                    bool(u.get("is_master_admin", False)),
                    _to_datetime(u.get("created_at")) or datetime.now(timezone.utc),
                )
            await pg.execute(
                """INSERT INTO public.sanjeevani_agents
                   (id, user_id, full_name, phone, email, city, state, status, kyc_status, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,'active','verified',$8,$8)
                   ON CONFLICT (id) DO NOTHING""",
                crm_id, fk_user_id, u.get("name"), phone, u.get("email"),
                u.get("city"), u.get("state"),
                _to_datetime(u.get("created_at")) or datetime.now(timezone.utc),
            )
            n += 1
        except Exception as e:
            print(f"  ! skipped staff {u.get('phone')}: {e}")
    print(f"  ✓ migrated {n} new staff into sanjeevani_agents")


async def migrate_activities(pg, mongo):
    print("\n=== activities → agent_activities (best-effort) ===")
    n = 0
    async for a in mongo.activities.find({}, {"_id": 0}):
        try:
            aid = a.get("id")
            agent_id = a.get("agent_id")
            if not aid or not agent_id:
                continue
            # sanjeevani_agents FK — skip rows whose agent no longer exists in Postgres
            if not await pg.fetchrow("SELECT 1 FROM public.sanjeevani_agents WHERE id = $1", agent_id):
                continue
            await pg.execute(
                """INSERT INTO public.agent_activities
                   (id, agent_id, activity_type, description, case_id, extra_data, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7)
                   ON CONFLICT (id) DO NOTHING""",
                aid, agent_id,
                a.get("type") or a.get("category") or "note",
                a.get("summary") or a.get("description") or a.get("title") or "",
                a.get("contact_id"),
                _jsonb({k: v for k, v in a.items() if k not in
                        {"id", "agent_id", "type", "category", "summary", "description",
                         "contact_id", "created_at", "title"}}),
                _to_datetime(a.get("created_at")) or datetime.now(timezone.utc),
            )
            n += 1
        except Exception as e:
            print(f"  ! skipped activity {a.get('id')}: {e}")
    print(f"  ✓ migrated {n} activities")


async def migrate_tasks(pg, mongo):
    print("\n=== tasks → agent_tasks (best-effort) ===")
    n = 0
    async for t in mongo.tasks.find({}, {"_id": 0}):
        try:
            tid = t.get("id")
            agent_id = t.get("assigned_to") or t.get("agent_id")
            if not tid or not agent_id:
                continue
            if not await pg.fetchrow("SELECT 1 FROM public.sanjeevani_agents WHERE id = $1", agent_id):
                continue
            await pg.execute(
                """INSERT INTO public.agent_tasks
                   (id, agent_id, task_type, title, description, status, priority,
                    due_date, completed_at, notes, created_at, updated_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                   ON CONFLICT (id) DO NOTHING""",
                tid, agent_id,
                t.get("task_type") or "general",
                (t.get("title") or "")[:200], t.get("description"),
                t.get("status") or "pending",
                t.get("priority") or "normal",
                _to_datetime(t.get("due_date")), _to_datetime(t.get("completed_at")),
                t.get("notes"),
                _to_datetime(t.get("created_at")) or datetime.now(timezone.utc),
                _to_datetime(t.get("updated_at")) or datetime.now(timezone.utc),
            )
            n += 1
        except Exception as e:
            print(f"  ! skipped task {t.get('id')}: {e}")
    print(f"  ✓ migrated {n} tasks")


async def main():
    mongo_client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    mongo = mongo_client[os.environ["DB_NAME"]]
    pg = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    try:
        await migrate_contacts(pg, mongo)
        await migrate_staff(pg, mongo)
        await migrate_activities(pg, mongo)
        await migrate_tasks(pg, mongo)
        # Summary
        for tbl in ("crm_provider_leads", "sanjeevani_agents", "agent_activities", "agent_tasks"):
            row = await pg.fetchrow(f"SELECT count(*) AS c FROM public.{tbl}")
            print(f"  {tbl}: {row['c']} rows")
    finally:
        await pg.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(main())
