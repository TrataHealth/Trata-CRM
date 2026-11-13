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
    "path_lab": ("path_lab_profiles", "name"),
    "doctor": ("doctors", "full_name"),
    "pharmacy": ("pharmacy_providers", "business_name"),
    "ambulance_provider": ("ambulance_providers", "business_name"),
    "diagnostic_centre": ("diagnostic_centre_profiles", "name"),
}
# Phase D follow-up: nurse / paramedic leads are a users row only (right role, no profile table yet).
USER_ONLY = {"nurse", "paramedic"}
ROLE_ALIASES = {"lab": "path_lab", "lab_tech": "path_lab", "pathology": "path_lab", "pathologist": "path_lab", "ambulance": "ambulance_provider",
                "diagnostic_centre_admin": "diagnostic_centre"}
ADDRESS_RULE_TABLES = {"path_lab_profiles", "diagnostic_centre_profiles"}
LICENSE_COL = {"path_lab_profiles": "registration_number", "pharmacy_providers": "drug_license_number"}
RENAME = {"source": "lead_source", "ambulance_count": "total_ambulances"}
# Fields the CRM owns — synced on every CRM write.
# Phase E: pipeline_stage now lives on crm_sales_leads (sales_leads.py), not on the canonical row.
CRM_OWNED = {
    "kyc_status", "kyc_id", "deal_value", "assigned_agent_id", "assigned_agent_name",
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
    existing same-role account is reused (confirmed by the Provider App team)."""
    u = await conn.fetchrow("SELECT id, role FROM public.users WHERE phone = ANY($1::text[]) LIMIT 1", [phone, f"+91{phone}"])
    if u:
        if u["role"] is None:
            await conn.execute("UPDATE public.users SET role = $2, updated_at = now() WHERE id = $1", u["id"], c.get("type"))
        return u["id"] if u["role"] in (None, c.get("type")) else None
    uid = str(uuid.uuid4())
    await conn.execute("""INSERT INTO public.users (id, phone, name, role, is_active, verification_status, created_at, updated_at)
                          VALUES ($1, $2, $3, $4, TRUE, 'pending', now(), now())""", uid, phone, c.get("name"), c.get("type"))
    return uid


async def _table_for(conn, type_: str, uid: Optional[str]):
    """Pathologist accounts may live in diagnostic_centre_profiles (6th canonical table, same users.id).
    The diagnostic-centre row wins over a deprecated shadow path_lab row (sibling_path_lab_id)."""
    table, name_col = TABLES[type_]
    if type_ == "path_lab" and uid and await conn.fetchval(
            "SELECT 1 FROM public.diagnostic_centre_profiles WHERE user_id = $1", uid):
        return TABLES["diagnostic_centre"]
    return table, name_col


async def _sync_user_only(conn, c: Dict[str, Any], create: bool) -> Dict[str, Any]:
    uid = user_id_of(c)
    if uid and await conn.fetchval("SELECT 1 FROM public.users WHERE id = $1", uid):
        return {"success": True, "user_id": uid, "created": False}
    phone = clean_phone(c.get("phone"))
    if not create or not phone:
        return {"success": False, "reason": "not_created"}
    uid = await _ensure_user(conn, c, phone)
    return {"success": bool(uid), "user_id": uid, "created": bool(uid)} if uid else {"success": False, "reason": "phone_owned_by_other_role"}


async def sync_contact(c: Dict[str, Any], keys: Optional[Iterable[str]] = None, create: bool = True,
                       raw_contacts=None) -> Dict[str, Any]:
    """Write a CRM contact's fields onto its canonical provider row (WHERE user_id = users.id)."""
    if not sb.is_configured() or not c:
        return {"success": False, "reason": "skipped"}
    type_ = c.get("type") or ""
    if type_ not in TABLES and type_ not in USER_ONLY:
        return {"success": False, "reason": "no_canonical_table"}
    keys = set(CRM_OWNED if keys is None else keys) & (CRM_OWNED | DISPLAY)
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        if type_ in USER_ONLY:
            res = await _sync_user_only(conn, c, create)
            uid = res.get("user_id")
        else:
            res, uid = await _sync_profile(conn, c, type_, keys, create)
    if res.get("success") and raw_contacts is not None and c.get("id") and uid and uid != user_id_of(c):
        await raw_contacts.update_one({"id": c["id"]}, {"$set": {"upstream_user_id": uid, "supabase_user_id": uid}})
    return res


async def _sync_profile(conn, c: Dict[str, Any], type_: str, keys: set, create: bool):
    uid = user_id_of(c)
    if uid and not await conn.fetchval("SELECT 1 FROM public.users WHERE id = $1", uid):
        uid = None
    async with conn.transaction():
        if not uid:
            phone = clean_phone(c.get("phone"))
            if not create or not phone:
                return {"success": False, "reason": "no_canonical_row" if create else "not_created"}, None
            uid = await _ensure_user(conn, c, phone)
            if not uid:
                return {"success": False, "reason": "phone_owned_by_other_role"}, None
        table, name_col = await _table_for(conn, type_, uid)
        cols = await _columns(conn, table)
        exists = bool(await conn.fetchval(f"SELECT 1 FROM public.{table} WHERE user_id = $1", uid))
        if not exists:
            if not create or not clean_phone(c.get("phone")):
                return {"success": False, "reason": "no_canonical_row" if create else "not_created", "user_id": uid}, uid
            keys = keys | DISPLAY
        vals = {k: _coerce(v, cols[k], k) for k, v in _canonical_values(c, keys, table, name_col).items()
                if k in cols and (v is not None or k not in _DISPLAY_COLS)}
        for k in ("id", "user_id", "verification_status"):
            vals.pop(k, None)
        if exists:
            if vals:
                sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(vals))
                await conn.execute(f"UPDATE public.{table} SET {sets}, updated_at = now() WHERE user_id = $1", uid, *vals.values())
            return {"success": True, "user_id": uid, "created": False, "table": table}, uid
        base = {"id": str(uuid.uuid4()), "user_id": uid, "phone": clean_phone(c.get("phone")) or "",
                name_col: c.get("name") or "Unnamed"}
        if "owner_name" in cols:
            base["owner_name"] = c.get("contact_person") or c.get("owner_name") or c.get("name") or "Unnamed"
        base["verification_status"] = "pending"
        row = {**base, **vals}
        ph = ", ".join(f"${i + 1}" for i in range(len(row)))
        upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in vals) or "user_id = EXCLUDED.user_id"
        # §2 + follow-up Q6: idempotent on UNIQUE(user_id)
        await conn.execute(f"""INSERT INTO public.{table} ({', '.join(row)}, created_at, updated_at) VALUES ({ph}, now(), now())
                               ON CONFLICT (user_id) WHERE user_id IS NOT NULL DO UPDATE SET {upd}, updated_at = now()""", *row.values())
    return {"success": True, "user_id": uid, "created": True, "table": table}, uid


async def set_verification(user_id: str, type_: str, decision: str, actor: Optional[str],
                           reason: Optional[str] = None) -> Dict[str, Any]:
    """§6/§8 — the one status write (verification_status on every canonical table).
    Path labs / diagnostic centres with an incomplete address → pending_address."""
    if not sb.is_configured() or (type_ not in TABLES and type_ not in USER_ONLY):
        return {"success": False, "reason": "no_canonical_table"}
    if not user_id:
        return {"success": False, "reason": "no_canonical_row"}
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        if type_ in USER_ONLY:
            r = await conn.execute("UPDATE public.users SET verification_status = $2, updated_at = now() WHERE id = $1", user_id, decision)
            if r.rsplit(" ", 1)[-1] == "0":
                return {"success": False, "reason": "no_canonical_row"}
            return {"success": True, "verification_status": decision}
        table, _ = await _table_for(conn, type_, user_id)
        status = decision
        if decision == "verified" and table in ADDRESS_RULE_TABLES:
            missing = await conn.fetchval(f"""SELECT count(*) FROM public.{table} WHERE user_id = $1
                                               AND ({' OR '.join(f'{k} IS NULL' for k in PATH_LAB_ADDRESS)})""", user_id)
            if missing:
                status = "pending_address"
        cols = await _columns(conn, table)
        decision_json = json.dumps({"decision": status, "reason": reason, "by": actor,
                                    "at": datetime.now(timezone.utc).isoformat()})
        args = [user_id, status]
        sets = ["verification_status = $2", "updated_at = now()"]
        if "local_decision" in cols:
            args.append(decision_json)
            sets.append(f"local_decision = coalesce(local_decision, '{{}}'::jsonb) || ${len(args)}::jsonb")
        if status in ("verified", "rejected") and "pipeline_stage" in cols:
            sets.append(f"pipeline_stage = '{status}'")
        if status == "verified" and "ai_fields_applied_by" in cols:
            args.append(actor)
            sets += [f"ai_fields_applied_by = ${len(args)}", "ai_fields_applied_at = now()"]
        try:
            async with conn.transaction():
                r = await conn.execute(f"UPDATE public.{table} SET {', '.join(sets)} WHERE user_id = $1", *args)
                if r.rsplit(" ", 1)[-1] == "0":
                    return {"success": False, "reason": "no_canonical_row"}
                await conn.execute("UPDATE public.users SET verification_status = $2, updated_at = now() WHERE id = $1", user_id, status)
        except asyncpg.exceptions.CheckViolationError as e:
            return {"success": False, "reason": "check_violation", "detail": str(e)}
    return {"success": True, "verification_status": status, "table": table}


# ── Read path (§7) ───────────────────────────────────────────────────────────
_UNION_COLS = ("phone", "email", "city", "state", "pipeline_stage", "kyc_status", "deal_value", "assigned_agent_id",
               "assigned_agent_name", "lead_source", "verification_status", "created_at", "updated_at")
_union_sql: Optional[str] = None


async def union_sql(conn) -> str:
    """UNION ALL of the 6 canonical tables; labs report as entity type path_lab / diagnostic_centre (§7)."""
    global _union_sql
    if _union_sql is None:
        parts = []
        for t, (tbl, n) in TABLES.items():
            cols = await _columns(conn, tbl)
            crm_type = f"'{t}'::text"
            sel = ", ".join((f"{k}::numeric" if k == "deal_value" else (k if k.endswith("_at") else f"{k}::text")) + f" AS {k}"
                            if k in cols else (f"NULL::numeric AS {k}" if k == "deal_value" else
                                               (f"NULL::timestamptz AS {k}" if k.endswith("_at") else f"NULL::text AS {k}"))
                            for k in _UNION_COLS)
            parts.append(f"SELECT {crm_type} AS type, '{tbl}'::text AS canonical_table, id::text, user_id::text, "
                         f"{n}::text AS name, {sel} FROM public.{tbl}")
        _union_sql = " UNION ALL ".join(parts)
    return _union_sql


async def removed_user_ids(conn) -> set:
    """Accounts the Provider App removed: users.is_archived, or every canonical profile row deactivated."""
    rows = await conn.fetch(f"""SELECT id FROM public.users WHERE coalesce(is_archived, FALSE)
                                UNION SELECT user_id FROM ({await union_sql(conn)}) p WHERE user_id IS NOT NULL
                                GROUP BY user_id HAVING bool_and(verification_status = 'deactivated')""")
    return {r[0] for r in rows}


async def sync_removed_to_contacts(raw_contacts) -> Dict[str, int]:
    """Mirror Provider App removals onto CRM contacts (archived, no purge date — the CRM never erases these)."""
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        gone = list(await removed_user_ids(conn))
    now = datetime.now(timezone.utc).isoformat()
    by_uid = {"$or": [{"supabase_user_id": {"$in": gone}}, {"upstream_user_id": {"$in": gone}}]}
    hid = await raw_contacts.update_many({**by_uid, "archived": {"$ne": True}}, {"$set": {
        "archived": True, "archived_at": now, "archived_reason": "Removed in the Provider App", "archived_by": "Provider App",
        "purge_after": None, "upstream_removed": True, "is_active": False}})
    back = await raw_contacts.update_many({"upstream_removed": True, "supabase_user_id": {"$nin": gone}, "upstream_user_id": {"$nin": gone}},
                                          {"$set": {"archived": False, "archived_at": None, "archived_reason": None, "archived_by": None,
                                                    "upstream_removed": False}})
    return {"hidden": hid.modified_count, "unhidden": back.modified_count}


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
        u = await union_sql(conn)
        total = await conn.fetchval(f"SELECT count(*) FROM ({u}) p WHERE {' AND '.join(where)}", *args)
        rows = await conn.fetch(f"""SELECT * FROM ({u}) p WHERE {' AND '.join(where)}
                                     ORDER BY updated_at DESC NULLS LAST LIMIT ${len(args) + 1}""", *args, limit)
    return {"items": sb._rows(rows), "total": total}


async def get_lead(key: str) -> Optional[Dict[str, Any]]:
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(f"SELECT * FROM ({await union_sql(conn)}) p WHERE user_id = $1 OR id = $1 LIMIT 1", key)
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
        import sales_leads as sl
        canon_keys = set_keys if set_keys is None or display else set(set_keys) & CRM_OWNED
        try:
            docs = await self._c.find(flt, {"_id": 0}).to_list(1000 if many else 1)
            for d in docs:
                if not display:
                    await sl.sync(d, self._c)
                if canon_keys is not None and not canon_keys:
                    continue
                # Phase E: prospects never get an app account here — sales_leads.sync converts on Won.
                res = await sync_contact(d, canon_keys, create=False, raw_contacts=self._c)
                if not res.get("success") and res.get("reason") not in ("no_canonical_table", "not_created", "skipped"):
                    logger.info(f"canonical sync {d.get('id')}: {res}")
        except Exception as e:
            logger.warning(f"canonical sync failed ({flt}): {e}")

    @staticmethod
    def _keys(update: Dict[str, Any]):
        return set((update or {}).get("$set", {}).keys())

    @staticmethod
    def _norm(doc: Optional[Dict[str, Any]]):
        """Every pipeline_stage written by any CRM code path is coerced to the Phase E sales stages."""
        import sales_leads as sl
        for part in (doc, (doc or {}).get("$set"), (doc or {}).get("$setOnInsert")):
            if isinstance(part, dict) and part.get("pipeline_stage"):
                part["pipeline_stage"] = sl.stage(part["pipeline_stage"])
        return doc

    async def insert_one(self, doc, *a, **kw):
        r = await self._c.insert_one(self._norm(doc), *a, **kw)
        if doc.get("id"):
            _spawn(self._after({"id": doc["id"]}, None, create=True))
        return r

    async def update_one(self, flt, update, *a, **kw):
        r = await self._c.update_one(flt, self._norm(update), *a, **kw)
        if r.modified_count or r.upserted_id:
            _spawn(self._after(flt, self._keys(update), create=bool(r.upserted_id)))
        return r

    async def update_many(self, flt, update, *a, **kw):
        r = await self._c.update_many(flt, self._norm(update), *a, **kw)
        if r.modified_count:
            _spawn(self._after(flt, self._keys(update), many=True))
        return r

    async def find_one_and_update(self, flt, update, *a, **kw):
        r = await self._c.find_one_and_update(flt, self._norm(update), *a, **kw)
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
    async for c in raw_contacts.find({"type": {"$in": list(TABLES) + list(USER_ONLY)}, "archived": {"$ne": True}}, {"_id": 0}):
        try:
            res = await sync_contact(c, None, create=create, raw_contacts=raw_contacts)
            k = "created" if res.get("created") else ("updated" if res.get("success") else res.get("reason", "failed"))
        except Exception as e:
            logger.warning(f"backfill {c.get('id')}: {e}")
            k = "error"
        stats[k] = stats.get(k, 0) + 1
    logger.info(f"canonical backfill: {stats}")
    return stats


# ── Deletion parity with the Provider App: a deleted profile is verification_status = 'deactivated' ──
async def deactivate_profiles(conn, user_ids, by: Optional[str], reason: Optional[str]) -> int:
    n = 0
    meta = json.dumps({"deleted_by": by, "deleted_reason": reason, "deleted_at": datetime.now(timezone.utc).isoformat()})
    for tbl, _ in TABLES.values():
        r = await conn.execute(f"""UPDATE public.{tbl} SET local_decision = coalesce(local_decision, '{{}}'::jsonb) || $2::jsonb
                                     || jsonb_build_object('pre_delete_status', verification_status),
                                     verification_status = 'deactivated', is_active = FALSE, updated_at = now()
                                    WHERE user_id = ANY($1::text[]) AND verification_status IS DISTINCT FROM 'deactivated'""",
                               list(user_ids), meta)
        n += int(r.rsplit(" ", 1)[-1])
    r = await conn.execute("""UPDATE public.paramedic_profiles SET verification_status = 'deactivated', updated_at = now()
                               WHERE user_id = ANY($1::text[]) AND verification_status IS DISTINCT FROM 'deactivated'""", list(user_ids))
    return n + int(r.rsplit(" ", 1)[-1])


async def restore_profiles(conn, user_ids) -> int:
    n = 0
    for tbl, _ in TABLES.values():
        prev = "coalesce(nullif(local_decision->>'pre_delete_status', ''), 'pending_review')"
        for status in (prev, "'pending_review'"):
            try:
                async with conn.transaction():
                    r = await conn.execute(f"""UPDATE public.{tbl} SET verification_status = {status}, is_active = TRUE, updated_at = now(),
                                                 local_decision = coalesce(local_decision, '{{}}'::jsonb) - 'pre_delete_status' - 'deleted_by' - 'deleted_reason' - 'deleted_at'
                                                WHERE user_id = ANY($1::text[]) AND verification_status = 'deactivated'""", list(user_ids))
                n += int(r.rsplit(" ", 1)[-1])
                break
            except asyncpg.exceptions.CheckViolationError:
                continue
    r = await conn.execute("""UPDATE public.paramedic_profiles SET verification_status = 'pending', updated_at = now()
                               WHERE user_id = ANY($1::text[]) AND verification_status = 'deactivated'""", list(user_ids))
    return n + int(r.rsplit(" ", 1)[-1])


async def users_with_profiles(conn, user_ids) -> set:
    tbls = [t for t, _ in TABLES.values()] + ["paramedic_profiles"]
    sql = " UNION ".join(f"SELECT user_id::text FROM public.{t} WHERE user_id = ANY($1::text[])" for t in tbls)
    return {r[0] for r in await conn.fetch(sql, list(user_ids))}


async def suspend_profiles(conn, user_ids, by: Optional[str], reason: Optional[str]) -> int:
    """Provider App suspension = profile verification_status 'suspended' (prior status kept in local_decision)."""
    n = 0
    meta = json.dumps({"suspended_by": by, "suspended_reason": reason, "suspended_at": datetime.now(timezone.utc).isoformat()})
    async with conn.transaction():
        for tbl, _ in TABLES.values():
            # Some Provider App tables CHECK that a suspended row carries suspension_reason.
            has_reason = "suspension_reason" in await _columns(conn, tbl)
            r = await conn.execute(f"""UPDATE public.{tbl} SET local_decision = coalesce(local_decision, '{{}}'::jsonb) || $2::jsonb
                                         || jsonb_build_object('pre_suspend_status', verification_status),
                                         {"suspension_reason = $3," if has_reason else ""}
                                         verification_status = 'suspended', updated_at = now()
                                        WHERE user_id = ANY($1::text[]) AND verification_status NOT IN ('suspended', 'deactivated')""",
                                   list(user_ids), meta, *([reason or "Suspended by Trata Health Admin"] if has_reason else []))
            n += int(r.rsplit(" ", 1)[-1])
        has_reason = "suspension_reason" in await _columns(conn, "paramedic_profiles")
        r = await conn.execute(f"""UPDATE public.paramedic_profiles SET verification_status = 'suspended', updated_at = now()
                                     {", suspension_reason = $2" if has_reason else ""}
                                    WHERE user_id = ANY($1::text[]) AND verification_status NOT IN ('suspended', 'deactivated')""",
                               list(user_ids), *([reason or "Suspended by Trata Health Admin"] if has_reason else []))
        n += int(r.rsplit(" ", 1)[-1])
    return n


async def unsuspend_profiles(conn, user_ids) -> int:
    n = 0
    for tbl, _ in TABLES.values():
        prev = "coalesce(nullif(local_decision->>'pre_suspend_status', ''), 'pending_review')"
        for status in (prev, "'pending_review'"):
            try:
                async with conn.transaction():
                    clr = "suspension_reason = NULL," if "suspension_reason" in await _columns(conn, tbl) else ""
                    r = await conn.execute(f"""UPDATE public.{tbl} SET verification_status = {status}, updated_at = now(), {clr}
                                                 local_decision = coalesce(local_decision, '{{}}'::jsonb) - 'pre_suspend_status' - 'suspended_by' - 'suspended_reason' - 'suspended_at'
                                                WHERE user_id = ANY($1::text[]) AND verification_status = 'suspended'""", list(user_ids))
                n += int(r.rsplit(" ", 1)[-1])
                break
            except asyncpg.exceptions.CheckViolationError:
                continue
    clr = ", suspension_reason = NULL" if "suspension_reason" in await _columns(conn, "paramedic_profiles") else ""
    for status in ("pending", "pending_review"):
        try:
            async with conn.transaction():
                r = await conn.execute(f"""UPDATE public.paramedic_profiles SET verification_status = '{status}', updated_at = now() {clr}
                                            WHERE user_id = ANY($1::text[]) AND verification_status = 'suspended'""", list(user_ids))
            n += int(r.rsplit(" ", 1)[-1])
            break
        except asyncpg.exceptions.CheckViolationError:
            continue
    return n
