"""Phase E — CRM sales pipeline lives in crm_sales_leads (prospects + conversion history).
Onboarded providers stay on the 6 canonical tables; an app account is created only when a lead is Won."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import supabase_db as sb

logger = logging.getLogger(__name__)

STAGES = ("new", "contacted", "qualified", "proposal", "negotiation", "won", "lost", "dropped")
OPEN_STAGES = ("new", "contacted", "qualified", "proposal", "negotiation")
CLOSED_STAGES = ("won", "lost", "dropped")
# Old console stages / provider statuses → Phase E sales stages
LEGACY_STAGE = {
    "lead": "new", "pending": "new", "kyc_submitted": "qualified", "kyc_pending": "contacted",
    "onboarded": "won", "verified": "won", "approved": "won", "active": "won", "app_onboarded": "won", "live_on_app": "won",
    "pending_review": "contacted", "pending_address": "contacted", "rejected": "lost",
    "churned": "dropped", "suspended": "dropped", "deactivated": "dropped",
}
LEAD_TYPES = {"hospital", "path_lab", "doctor", "pharmacy", "ambulance_provider", "diagnostic_centre", "nurse", "paramedic"}
SELF_SIGNUP_SOURCES = {"supabase_sync", "admin_users_sync", "org_entity", "provider_app_webhook", "trata_admin_webhook"}
COLS = ("name", "type", "email", "city", "state", "address", "pipeline_stage", "deal_value", "assigned_agent_id",
        "assigned_agent_name", "source", "onboarded_by", "avatar", "specialization", "vehicle_reg", "vehicle_make_model",
        "ambulance_count", "lab_specialty", "pharmacy_type", "notes", "next_followup_at", "upstream_user_id")


def stage(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    return v if v in STAGES else LEGACY_STAGE.get(v, "new")


def _row(c: Dict[str, Any]) -> Dict[str, Any]:
    from canonical_providers import clean_phone, user_id_of
    src = c.get("source")
    spec = c.get("specialization")
    return {
        "name": c.get("name") or "Unnamed", "type": "path_lab" if c.get("type") == "pathologist" else c.get("type"),
        "email": c.get("email"), "city": c.get("city"), "state": c.get("state"), "address": c.get("address"),
        "pipeline_stage": stage(c.get("pipeline_stage")) or "new",
        "deal_value": Decimal(str(c["deal_value"])) if c.get("deal_value") not in (None, "") else None,
        "assigned_agent_id": c.get("assigned_agent_id"), "assigned_agent_name": c.get("assigned_agent_name"),
        "source": "inbound" if src in SELF_SIGNUP_SOURCES else src, "onboarded_by": c.get("onboarded_by"),
        "avatar": c.get("avatar"), "specialization": ", ".join(spec) if isinstance(spec, list) else spec,
        "vehicle_reg": c.get("vehicle_reg"), "vehicle_make_model": c.get("vehicle_make_model"),
        "ambulance_count": int(c["ambulance_count"]) if str(c.get("ambulance_count") or "").isdigit() else None,
        "lab_specialty": c.get("lab_specialty"), "pharmacy_type": c.get("pharmacy_type"), "notes": c.get("notes"),
        "next_followup_at": sb._to_datetime(c.get("next_followup_at")) if c.get("next_followup_at") else None,
        "upstream_user_id": user_id_of(c), "_phone": clean_phone(c.get("phone")),
    }


async def upsert(c: Dict[str, Any]) -> Dict[str, Any]:
    """Write one CRM contact onto crm_sales_leads (keyed by phone — unique on both tables)."""
    if not sb.is_configured() or (c.get("type") not in LEAD_TYPES and c.get("type") != "pathologist"):
        return {"success": False, "reason": "not_a_provider_lead"}
    r = _row(c)
    phone = r.pop("_phone")
    if not phone:
        return {"success": False, "reason": "no_real_phone"}
    vals = [r[k] for k in COLS]
    sets = ", ".join(f"{k} = coalesce(EXCLUDED.{k}, crm_sales_leads.{k})" if k == "upstream_user_id" else f"{k} = EXCLUDED.{k}"
                     for k in COLS)
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(f"""INSERT INTO public.crm_sales_leads (id, phone, {', '.join(COLS)}, created_at, updated_at)
                               VALUES ($1, $2, {', '.join(f'${i + 3}' for i in range(len(COLS)))}, now(), now())
                               ON CONFLICT (phone) DO UPDATE SET {sets}, updated_at = now()""",
                           c.get("id") or str(uuid.uuid4()), phone, *vals)
    return {"success": True}


async def sync(c: Dict[str, Any], raw_contacts) -> None:
    """Lead write-through + §5 conversion: an app account and canonical row only once the lead is Won."""
    import canonical_providers as cp
    try:
        won = stage(c.get("pipeline_stage")) == "won"
        if won and not cp.user_id_of(c):
            res = await cp.sync_contact(c, None, create=True, raw_contacts=raw_contacts)
            if res.get("user_id"):
                c = {**c, "upstream_user_id": res["user_id"], "supabase_user_id": res["user_id"]}
        await upsert(c)
    except Exception as e:
        logger.warning(f"sales lead sync {c.get('id')}: {e}")


async def backfill(raw_contacts) -> Dict[str, int]:
    stats: Dict[str, int] = {}
    async for c in raw_contacts.find({"type": {"$in": list(LEAD_TYPES)}, "archived": {"$ne": True}}, {"_id": 0}):
        try:
            k = (await upsert(c)).get("reason", "ok")
        except Exception as e:
            logger.warning(f"sales backfill {c.get('id')}: {e}")
            k = "error"
        stats[k] = stats.get(k, 0) + 1
    return stats


async def followups_due(agent_id: Optional[str] = None, limit: int = 200):
    where, args = ["next_followup_at IS NOT NULL", "next_followup_at <= now()", "pipeline_stage <> ALL($1::text[])"], [list(CLOSED_STAGES)]
    if agent_id:
        args.append(agent_id)
        where.append(f"assigned_agent_id = ${len(args)}")
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""SELECT id, name, type, phone, city, pipeline_stage, assigned_agent_id, assigned_agent_name,
                                           next_followup_at, notes FROM public.crm_sales_leads WHERE {' AND '.join(where)}
                                     ORDER BY next_followup_at LIMIT {int(limit)}""", *args)
    now = datetime.now(timezone.utc)
    return [{**sb._row(r), "overdue_days": (now - r["next_followup_at"]).days} for r in rows]
