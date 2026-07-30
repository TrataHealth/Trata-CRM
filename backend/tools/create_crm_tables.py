"""One-shot: create the CRM-owned Postgres tables in the shared Supabase project.

Only `crm_provider_leads` is genuinely new — everything else the CRM writes
maps to a pre-existing table in the shared schema:
  - contacts     -> new: crm_provider_leads          (this file creates it)
  - crm_users    -> existing: sanjeevani_agents      (already has all fields)
  - activities   -> existing: agent_activities       (already has all fields)
  - tasks        -> existing: agent_tasks            (already has all fields)
  - notes        -> merged into agent_activities via activity_type='note'
  - notifications-> existing: notifications          (already has all fields)

Run once:  python -m tools.create_crm_tables
"""
import asyncio
import os
import sys
from pathlib import Path

# Allow this script to be run from anywhere by ensuring /app/backend is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import asyncpg

DDL = """
CREATE TABLE IF NOT EXISTS public.crm_provider_leads (
    id                        TEXT PRIMARY KEY,
    upstream_user_id          TEXT,
    name                      TEXT NOT NULL,
    type                      TEXT NOT NULL,
    phone                     TEXT NOT NULL,
    email                     TEXT,
    city                      TEXT,
    state                     TEXT,
    address                   TEXT,
    is_verified               BOOLEAN DEFAULT false,
    is_active                 BOOLEAN DEFAULT false,
    pipeline_stage            TEXT NOT NULL DEFAULT 'lead',
    kyc_status                TEXT DEFAULT 'pending',
    kyc_id                    TEXT,
    deal_value                NUMERIC DEFAULT 0,
    assigned_agent_id         TEXT,
    assigned_agent_name       TEXT,
    source                    TEXT,
    onboarded_by              TEXT,
    onboarded_at              TIMESTAMPTZ,
    avatar                    TEXT,
    specialization            TEXT,
    pan_number                TEXT,
    gst_number                TEXT,
    vehicle_reg               TEXT,
    vehicle_make_model        TEXT,
    aadhaar_last4             TEXT,
    father_name               TEXT,
    dob                       TEXT,
    hospital_name             TEXT,
    ambulance_count           INTEGER,
    license_number            TEXT,
    lab_specialty             TEXT,
    pharmacy_type             TEXT,
    kyc_doc_issue_date        TEXT,
    kyc_doc_expiry_date       TEXT,
    kyc_doc_authority         TEXT,
    kyc_document_number       TEXT,
    ai_doc_prescreens         JSONB DEFAULT '{}'::jsonb,
    ai_prescreen_summary      JSONB,
    ai_extracted_fields       JSONB DEFAULT '{}'::jsonb,
    agent_doc_reviews         JSONB DEFAULT '{}'::jsonb,
    local_decision            JSONB,
    ai_fields_applied_at      TIMESTAMPTZ,
    ai_fields_applied_by      TEXT,
    last_admin_sync_at        TIMESTAMPTZ,
    created_at                TIMESTAMPTZ DEFAULT now(),
    updated_at                TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS crm_provider_leads_phone_key ON public.crm_provider_leads(phone);
CREATE INDEX IF NOT EXISTS crm_provider_leads_agent_idx    ON public.crm_provider_leads(assigned_agent_id);
CREATE INDEX IF NOT EXISTS crm_provider_leads_stage_idx    ON public.crm_provider_leads(pipeline_stage);
CREATE INDEX IF NOT EXISTS crm_provider_leads_type_idx     ON public.crm_provider_leads(type);
CREATE INDEX IF NOT EXISTS crm_provider_leads_upstream_idx ON public.crm_provider_leads(upstream_user_id);
"""


async def main():
    dsn = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        await conn.execute(DDL)
        print("✓ crm_provider_leads created (or already existed)")
        row = await conn.fetchrow(
            "SELECT count(*) AS c FROM public.crm_provider_leads"
        )
        print(f"  rows now: {row['c']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
