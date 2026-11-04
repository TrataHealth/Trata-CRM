"""Phase D — CRM provider leads live on the 5 canonical provider tables, keyed only by users.id."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional

import asyncpg

import supabase_db as sb

logger = logging.getLogger(__name__)

# crm type -> (canonical table, name column)
TABLES = {
    "hospital": ("hospital_profiles", "name"),
    "pathologist": ("path_lab_profiles", "name"),
    "doctor": ("doctors", "full_name"),
    "pharmacy": ("pharmacy_providers", "business_name"),
    "ambulance_provider": ("ambulance_providers", "business_name"),
}
LICENSE_COL = {"path_lab_profiles": "registration_number", "pharmacy_providers": "drug_license_number"}
RENAME = {"source": "lead_source", "ambulance_count": "total_ambulances"}
# Fields the CRM owns — synced on every CRM write.
CRM_OWNED = {
    "pipeline_stage", "kyc_status", "kyc_id", "deal_value", "assigned_agent_id", "assigned_agent_name",
    "source", "onboarded_by", "pan_number", "gst_number", "aadhaar_last4", "father_name", "dob",
    "kyc_document_number", "kyc_doc_issue_date", "kyc_doc_expiry_date", "kyc_doc_authority",
    "ai_doc_prescreens", "ai_prescreen_summary", "ai_extracted_fields", "agent_doc_reviews", "local_decision",
    "ai_fields_applied_at", "ai_fields_applied_by", "last_admin_sync_at", "vehicle_reg", "vehicle_make_model",
    "ambulance_count", "license_number", "lab_specialty", "pharmacy_type", "specialization",
}
# Shared display fields — written only from explicit CRM edits / new leads.
DISPLAY = {"name", "phone", "email", "city", "state", "address", "is_active", "avatar"}
_DISPLAY_COLS = {"name", "full_name", "business_name", "phone", "email", "city", "state", "address", "is_active",
                 "logo_url", "profile_image"}
PATH_LAB_ADDRESS = ("address", "city", "state", "pincode", "latitude", "longitude")

_cols: Dict[str, Dict[str, str]] = {}


async def _columns(conn, table: str) -> Dict[str, str]:
    if table not in _cols:
        rows = await conn.fetch("""SELECT column_name, data_type FROM information_schema.columns
                                    WHERE table_schema='public' AND table_name=$1""", table)
        _cols[table] = {r["column_name"]: r["data_type"] for r in rows}
    return _cols[table]


def user_id_of(c: Dict[str, Any]) -> Optional[str]:
    return c.get("upstream_user_id") or c.get("supabase_user_id") or None


def clean_phone(p: Any) -> Optional[str]:
    s = str(p or "")
    if s.startswith("pnd-"):
        return None
    d = re.sub(r"\D", "", s)
    return d[-10:] if len(d) >= 10 else None


def _coerce(v: Any, dtype: str, col: str) -> Any:
    if v is None:
        return None
    if dtype in ("json", "jsonb"):
        if col == "specialization" and isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        if isinstance(v, str):
            try:
                json.loads(v)
                return v
            except ValueError:
                pass
        return json.dumps(v, default=str)
    if dtype.startswith("timestamp"):
        return v if isinstance(v, datetime) else sb._to_datetime(v)
    if dtype == "numeric":
        try:
            return Decimal(str(v))
        except Exception:
            return None
    if dtype in ("integer", "bigint", "smallint"):
        try:
            return int(v)
        except Exception:
            return None
    if dtype == "boolean":
        return bool(v)
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return v if isinstance(v, str) else (json.dumps(v, default=str) if isinstance(v, dict) else str(v))


def _canonical_values(c: Dict[str, Any], keys: Iterable[str], table: str, name_col: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in keys:
        if k not in c:
            continue
        v = c.get(k)
        if k == "name":
            if v:
                out[name_col] = v
        elif k == "phone":
            p = clean_phone(v)
            if p:
                out["phone"] = p
        elif k == "avatar":
            out["logo_url" if table == "hospital_profiles" else "profile_image"] = v
        elif k == "license_number":
            out[LICENSE_COL.get(table, "license_number")] = v
        else:
            out[RENAME.get(k, k)] = v
    return out


async def _ensure_user(conn, c: Dict[str, Any], phone: str) -> Optional[str]:
    """§2 — a canonical row never exists without a users row. users.phone is unique, so an
    existing same-role account is reused; a phone owned by another role is left alone."""
    u = await conn.fetchrow("SELECT id, role FROM public.users WHERE phone = ANY($1::text[]) LIMIT 1", [phone, f"+91{phone}"])
    if u:
        return u["id"] if u["role"] in (None, c.get("type")) else None
    uid = str(uuid.uuid4())
    await conn.execute("""INSERT INTO public.users (id, phone, name, role, is_active, verification_status, created_at, updated_at)
                          VALUES ($1, $2, $3, $4, TRUE, 'pending', now(), now())""", uid, phone, c.get("name"), c.get("type"))
    return uid


async def sync_contact(c: Dict[str, Any], keys: Optional[Iterable[str]] = None, create: bool = True,
                       raw_contacts=None) -> Dict[str, Any]:
    """Write a CRM contact's fields onto its canonical provider row (WHERE user_id = users.id)."""
    if not sb.is_configured() or not c:
        return {"success": False, "reason": "skipped"}
    spec = TABLES.get(c.get("type") or "")
    if not spec:
        return {"success": False, "reason": "no_canonical_table"}
    table, name_col = spec
    keys = set(CRM_OWNED if keys is None else keys) & (CRM_OWNED | DISPLAY)
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        cols = await _columns(conn, table)
        uid = user_id_of(c)
        if uid and not await conn.fetchval("SELECT 1 FROM public.users WHERE id = $1", uid):
            uid = None
        async with conn.transaction():
            exists = bool(uid) and await conn.fetchval(f"SELECT 1 FROM public.{table} WHERE user_id = $1 LIMIT 1", uid)
            if not exists:
                phone = clean_phone(c.get("phone"))
                if not create or not phone:
                    return {"success": False, "reason": "no_canonical_row" if create else "not_created", "user_id": uid}
                if not uid:
                    uid = await _ensure_user(conn, c, phone)
                    if not uid:
                        return {"success": False, "reason": "phone_owned_by_other_role"}
                    if await conn.fetchval(f"SELECT 1 FROM public.{table} WHERE user_id = $1 LIMIT 1", uid):
                        exists = True
                if not exists and table == "path_lab_profiles" and await conn.fetchval(
                        "SELECT 1 FROM public.diagnostic_centre_profiles WHERE user_id = $1 LIMIT 1", uid):
                    return {"success": False, "reason": "lives_in_diagnostic_centre_profiles", "user_id": uid}
                if not exists:
                    keys = keys | DISPLAY
            vals = {k: _coerce(v, cols[k], k) for k, v in _canonical_values(c, keys, table, name_col).items()
                    if k in cols and (v is not None or k not in _DISPLAY_COLS)}
            vals.pop("user_id", None)
            if exists:
                if not vals:
                    return {"success": True, "user_id": uid, "updated": 0}
                sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(vals))
                await conn.execute(f"UPDATE public.{table} SET {sets}, updated_at = now() WHERE user_id = $1", uid, *vals.values())
            else:
                base = {"id": str(uuid.uuid4()), "user_id": uid, "phone": clean_phone(c.get("phone")),
                        name_col: c.get("name") or "Unnamed"}
                if "owner_name" in cols:
                    base["owner_name"] = c.get("contact_person") or c.get("owner_name") or c.get("name") or "Unnamed"
                if "verification_status" in cols:
                    base["verification_status"] = "pending_review" if table == "path_lab_profiles" else "pending"
                row = {**vals, **base}
                ph = ", ".join(f"${i + 1}" for i in range(len(row)))
                await conn.execute(f"INSERT INTO public.{table} ({', '.join(row)}, created_at, updated_at) VALUES ({ph}, now(), now())",
                                   *row.values())
    if raw_contacts is not None and c.get("id") and uid != user_id_of(c):
        await raw_contacts.update_one({"id": c["id"]}, {"$set": {"upstream_user_id": uid, "supabase_user_id": uid}})
    return {"success": True, "user_id": uid, "created": not exists}


async def set_verification(user_id: str, type_: str, decision: str, actor: Optional[str],
                           reason: Optional[str] = None) -> Dict[str, Any]:
    """§6/§8 — the one status write. decision: 'verified' | 'rejected'. Path labs with an incomplete address → pending_address."""
    spec = TABLES.get(type_)
    if not spec or not sb.is_configured():
        return {"success": False, "reason": "no_canonical_table"}
    if not user_id:
        return {"success": False, "reason": "no_canonical_row"}
    table, _ = spec
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        cols = await _columns(conn, table)
        status = decision
        if decision == "verified" and table == "path_lab_profiles":
            missing = await conn.fetchval(f"""SELECT count(*) FROM public.path_lab_profiles WHERE user_id = $1
                                               AND ({' OR '.join(f'{k} IS NULL' for k in PATH_LAB_ADDRESS)})""", user_id)
            if missing:
                status = "pending_address"
        decision_json = json.dumps({"decision": status, "reason": reason, "by": actor,
                                    "at": datetime.now(timezone.utc).isoformat()})
        sets = ["local_decision = coalesce(local_decision, '{}'::jsonb) || $2::jsonb", "updated_at = now()"]
        if status in ("verified", "rejected"):
            sets.append(f"pipeline_stage = '{status}'")
        if status == "verified":
            sets += ["ai_fields_applied_by = $3", "ai_fields_applied_at = now()"]
        if "verification_status" in cols:
            sets.append(f"verification_status = '{status}'")
        elif table == "doctors":
            sets.append(f"is_verified = {'TRUE' if status == 'verified' else 'FALSE'}")
        elif table == "ambulance_providers":
            sets.append("status = 'approved', approved_at = now()" if status == "verified" else "status = 'rejected'")
        args = [user_id, decision_json] + ([actor] if status == "verified" else [])
        try:
            async with conn.transaction():
                r = await conn.execute(f"UPDATE public.{table} SET {', '.join(sets)} WHERE user_id = $1", *args)
                if r.rsplit(" ", 1)[-1] == "0":
                    return {"success": False, "reason": "no_canonical_row"}
                await conn.execute("UPDATE public.users SET verification_status = $2, updated_at = now() WHERE id = $1", user_id, status)
        except asyncpg.exceptions.CheckViolationError as e:
            return {"success": False, "reason": "check_violation", "detail": str(e)}
    return {"success": True, "verification_status": status}


# ── Read path (§7) ───────────────────────────────────────────────────────────
_UNION = " UNION ALL ".join(
    f"""SELECT '{t}'::text AS type, id::text, user_id::text, {n}::text AS name, phone::text, email::text, city::text, state::text,
               pipeline_stage::text, kyc_status::text, deal_value, assigned_agent_id::text, assigned_agent_name::text, lead_source::text,
               {"verification_status::text" if t not in ("doctor", "ambulance_provider") else
                ("CASE WHEN is_verified THEN 'verified' ELSE 'pending' END" if t == "doctor" else
                 "CASE WHEN status = 'approved' THEN 'verified' ELSE coalesce(status, 'pending') END")} AS verification_status,
               created_at, updated_at FROM public.{tbl}"""
    for t, (tbl, n) in TABLES.items())


async def list_leads(type_: Optional[str] = None, stage: Optional[str] = None, q: Optional[str] = None,
                     assigned_agent_id: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
    where, args = ["1=1"], []
    for col, v in (("type", type_), ("pipeline_stage", stage), ("assigned_agent_id", assigned_agent_id)):
        if v:
            args.append(v)
            where.append(f"{col} = ${len(args)}")
    if q:
        args.append(f"%{q.lower()}%")
        where.append(f"(lower(coalesce(name, '')) LIKE ${len(args)} OR phone LIKE ${len(args)})")
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT count(*) FROM ({_UNION}) p WHERE {' AND '.join(where)}", *args)
        rows = await conn.fetch(f"""SELECT * FROM ({_UNION}) p WHERE {' AND '.join(where)}
                                     ORDER BY updated_at DESC NULLS LAST LIMIT ${len(args) + 1}""", *args, limit)
    return {"items": sb._rows(rows), "total": total}


async def get_lead(key: str) -> Optional[Dict[str, Any]]:
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(f"SELECT * FROM ({_UNION}) p WHERE user_id = $1 OR id = $1 LIMIT 1", key)
    return sb._row(r)


# ── Mongo hook: every CRM contacts write is mirrored onto the canonical row ─
_bg: set = set()


def _spawn(coro) -> None:
    """Supabase round-trips are ~0.5s from here, so canonical writes never block the CRM request."""
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


class _ContactsProxy:
    def __init__(self, coll):
        self._c = coll

    def __getattr__(self, n):
        return getattr(self._c, n)

    async def _after(self, flt: Dict[str, Any], set_keys: Optional[Iterable[str]], many: bool = False, create: bool = False,
                     display: bool = False):
        """Automatic hook carries CRM-owned fields only; shared display fields are written solely by explicit CRM edits."""
        if set_keys is not None and not display:
            set_keys = set(set_keys) & CRM_OWNED
            if not set_keys:
                return
        try:
            docs = await self._c.find(flt, {"_id": 0}).to_list(1000 if many else 1)
            for d in docs:
                res = await sync_contact(d, set_keys, create=create, raw_contacts=self._c)
                if not res.get("success") and res.get("reason") not in ("no_canonical_table", "not_created", "skipped"):
                    logger.info(f"canonical sync {d.get('id')}: {res}")
        except Exception as e:
            logger.warning(f"canonical sync failed ({flt}): {e}")

    @staticmethod
    def _keys(update: Dict[str, Any]):
        return set((update or {}).get("$set", {}).keys())

    async def insert_one(self, doc, *a, **kw):
        r = await self._c.insert_one(doc, *a, **kw)
        if doc.get("id"):
            _spawn(self._after({"id": doc["id"]}, None, create=True))
        return r

    async def update_one(self, flt, update, *a, **kw):
        r = await self._c.update_one(flt, update, *a, **kw)
        if r.modified_count or r.upserted_id:
            _spawn(self._after(flt, self._keys(update), create=bool(r.upserted_id)))
        return r

    async def update_many(self, flt, update, *a, **kw):
        r = await self._c.update_many(flt, update, *a, **kw)
        if r.modified_count:
            _spawn(self._after(flt, self._keys(update), many=True))
        return r

    async def find_one_and_update(self, flt, update, *a, **kw):
        r = await self._c.find_one_and_update(flt, update, *a, **kw)
        if r:
            _spawn(self._after({"id": r.get("id")} if r.get("id") else flt, self._keys(update), create=bool(kw.get("upsert"))))
        return r


class SyncedDB:
    def __init__(self, db):
        self._db = db
        self.contacts = _ContactsProxy(db.contacts)

    def __getattr__(self, n):
        return getattr(self._db, n)

    def __getitem__(self, n):
        return self.contacts if n == "contacts" else self._db[n]


async def backfill(raw_contacts, create: bool = True) -> Dict[str, Any]:
    stats: Dict[str, int] = {}
    async for c in raw_contacts.find({"type": {"$in": list(TABLES)}, "archived": {"$ne": True}}, {"_id": 0}):
        try:
            res = await sync_contact(c, None, create=create, raw_contacts=raw_contacts)
            k = "created" if res.get("created") else ("updated" if res.get("success") else res.get("reason", "failed"))
        except Exception as e:
            logger.warning(f"backfill {c.get('id')}: {e}")
            k = "error"
        stats[k] = stats.get(k, 0) + 1
    logger.info(f"canonical backfill: {stats}")
    return stats
