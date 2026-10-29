"""Gap-free change capture on the shared Supabase DB: a trigger on each app table writes every INSERT/UPDATE/DELETE
into trata_audit.activity_log in the same transaction. The Admin Console reads it in id order with a snapshot-safe cursor."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import supabase_db as sb

KEY_TABLES = ["users", "emergency_cases", "consultation_bookings", "medicine_orders", "prescriptions", "kyc_documents",
              "user_consents", "consultation_payments", "pathology_bookings", "ambulance_bookings", "patient_admissions",
              "at_home_care_bookings"]

INSTALL_SQL = r"""
CREATE SCHEMA IF NOT EXISTS trata_audit;
REVOKE ALL ON SCHEMA trata_audit FROM PUBLIC;
CREATE TABLE IF NOT EXISTS trata_audit.activity_log (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT clock_timestamp(),
    txid       xid8        NOT NULL DEFAULT pg_current_xact_id(),
    table_name text        NOT NULL,
    op         text        NOT NULL,
    row_id     text,
    app        text,
    db_role    text,
    old_data   jsonb,
    new_data   jsonb,
    changed    text[]
);
CREATE INDEX IF NOT EXISTS activity_log_table_id ON trata_audit.activity_log (table_name, id);
CREATE INDEX IF NOT EXISTS activity_log_row ON trata_audit.activity_log (table_name, row_id);
CREATE INDEX IF NOT EXISTS activity_log_at ON trata_audit.activity_log (at);
CREATE INDEX IF NOT EXISTS activity_log_txid ON trata_audit.activity_log (txid, id);
REVOKE ALL ON trata_audit.activity_log FROM PUBLIC;

-- Drop secrets/large blobs; mask sensitive health text so admins see that it changed, not what it says.
CREATE OR REPLACE FUNCTION trata_audit.clean(j jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $f$
  SELECT coalesce(jsonb_object_agg(k, CASE
           WHEN k ~* '(aadhaar|mood|journal|symptom_text|chat_text|message_body)' THEN to_jsonb('«masked»'::text)
           WHEN jsonb_typeof(v) = 'string' AND length(v #>> '{}') > 2000 THEN to_jsonb(left(v #>> '{}', 200) || '…')
           ELSE v END), '{}'::jsonb)
    FROM jsonb_each(j) AS e(k, v)
   WHERE k !~* '(password|otp|token|secret|_b64$|photo|signature_image|pin_hash)'
$f$;

CREATE OR REPLACE FUNCTION trata_audit.capture() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $f$
DECLARE o jsonb; n jsonb; ch text[];
BEGIN
  BEGIN
    IF TG_OP <> 'INSERT' THEN o := trata_audit.clean(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN n := trata_audit.clean(to_jsonb(NEW)); END IF;
    IF TG_OP = 'UPDATE' THEN
      SELECT array_agg(k) INTO ch FROM jsonb_object_keys(n) k WHERE n->k IS DISTINCT FROM o->k AND k NOT IN ('updated_at', 'last_seen_at');
      IF ch IS NULL THEN RETURN NULL; END IF;
      SELECT jsonb_object_agg(k, o->k) INTO o FROM unnest(ch) k;
      SELECT jsonb_object_agg(k, n->k) INTO n FROM unnest(ch) k;
    END IF;
    INSERT INTO trata_audit.activity_log (table_name, op, row_id, app, db_role, old_data, new_data, changed)
    VALUES (TG_TABLE_NAME, TG_OP, coalesce(n->>'id', o->>'id', (to_jsonb(coalesce(NEW, OLD)))->>'id'),
            coalesce(nullif(current_setting('trata.app', true), ''),
                     nullif(nullif(current_setting('application_name', true), ''), 'Supavisor'),
                     CASE WHEN current_setting('role', true) IN ('authenticated', 'anon') THEN 'app-user (Supabase client)'
                          WHEN current_setting('role', true) = 'service_role' THEN 'app-server (service key)' END),
            coalesce(nullif(current_setting('role', true), 'none'), session_user), o, n, ch);
  EXCEPTION WHEN others THEN
    -- Never block another app's write because of auditing.
    RAISE WARNING 'trata_audit.capture failed on %: %', TG_TABLE_NAME, SQLERRM;
  END;
  RETURN NULL;
END $f$;
"""


async def install(tables: Optional[List[str]] = None) -> Dict[str, Any]:
    tables = tables or KEY_TABLES
    pool = await sb.get_pool()
    attached, missing = [], []
    async with pool.acquire() as conn:
        await conn.execute(INSTALL_SQL)
        existing = {r["relname"] for r in await conn.fetch(
            "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r','p')")}
        for t in tables:
            if t not in existing:
                missing.append(t)
                continue
            await conn.execute(f'DROP TRIGGER IF EXISTS trata_audit_capture ON public."{t}"')
            await conn.execute(f'CREATE TRIGGER trata_audit_capture AFTER INSERT OR UPDATE OR DELETE ON public."{t}" '
                               f'FOR EACH ROW EXECUTE FUNCTION trata_audit.capture()')
            attached.append(t)
    return {"attached": attached, "missing": missing}


def create_audit_router(get_current_user) -> APIRouter:
    r = APIRouter(prefix="/api/admin/activity-log")

    def master(c):
        if not c.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Master admin only")

    @r.get("")
    async def feed(after_txid: Optional[int] = None, before_id: Optional[int] = None, table: Optional[str] = None, op: Optional[str] = None,
                   app: Optional[str] = None, row_id: Optional[str] = None, limit: int = 50, current=Depends(get_current_user)):
        """Newest-first page (before_id) or catch-up page (after_txid). Catch-up walks whole finished transactions in txid
        order and stops at the oldest in-flight one, so a slow commit can never be skipped by the cursor."""
        master(current)
        limit = max(1, min(limit, 200))
        cond, args = ["true"], []
        for col, val in (("table_name", table), ("op", op), ("app", app), ("row_id", row_id)):
            if val:
                args.append(val)
                cond.append(f"{col} = ${len(args)}")
        if before_id:
            args.append(before_id)
            cond.append(f"id < ${len(args)}")
        order = "id DESC"
        if after_txid is not None:
            args.append(after_txid)
            cond.append(f"txid > ${len(args)}::xid8 AND txid < pg_snapshot_xmin(pg_current_snapshot())")
            order = "txid ASC, id ASC"
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""SELECT id, txid::text::bigint AS txid, at, table_name, op, row_id, app, db_role, old_data, new_data, changed
                                          FROM trata_audit.activity_log WHERE {' AND '.join(cond)} ORDER BY {order} LIMIT {limit}""", *args)
            safe = await conn.fetchval("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint - 1")
        import json
        items = [{**dict(x), "at": x["at"].isoformat(), "old_data": json.loads(x["old_data"]) if x["old_data"] else None,
                  "new_data": json.loads(x["new_data"]) if x["new_data"] else None} for x in rows]
        if after_txid is not None and len(items) == limit:
            last = items[-1]["txid"]  # page may end mid-transaction: resume from the last complete one
            items = [i for i in items if i["txid"] < last] or items
            cursor = items[-1]["txid"] if items[-1]["txid"] < last else last
        else:
            cursor = max([i["txid"] for i in items], default=after_txid) if after_txid is not None else safe
        return {"items": items, "cursor_txid": cursor}

    @r.get("/health")
    async def health(current=Depends(get_current_user)):
        master(current)
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            covered = [x["t"] for x in await conn.fetch("""SELECT c.relname AS t FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid
                         JOIN pg_namespace n ON n.oid = c.relnamespace WHERE g.tgname = 'trata_audit_capture' AND n.nspname = 'public' ORDER BY 1""")]
            stats = await conn.fetch("""SELECT table_name, count(*) FILTER (WHERE at > now() - interval '24 hours') AS last_24h,
                                               count(*) AS total, max(at) AS last_at FROM trata_audit.activity_log GROUP BY 1""")
            uncovered = await conn.fetch("""SELECT relname, n_live_tup FROM pg_stat_user_tables WHERE schemaname = 'public'
                                              AND n_live_tup > 0 AND relname <> ALL($1::text[]) ORDER BY n_live_tup DESC""", covered)
            apps = await conn.fetch("""SELECT coalesce(app, 'unknown') AS app, count(*) AS n FROM trata_audit.activity_log
                                        WHERE at > now() - interval '7 days' GROUP BY 1 ORDER BY 2 DESC""")
        by = {s["table_name"]: s for s in stats}
        return {"covered": [{"table": t, "last_24h": (by.get(t) or {}).get("last_24h", 0), "total": (by.get(t) or {}).get("total", 0),
                             "last_at": by[t]["last_at"].isoformat() if t in by else None} for t in covered],
                "uncovered_with_data": [{"table": u["relname"], "rows": u["n_live_tup"]} for u in uncovered],
                "apps_7d": [dict(a) for a in apps]}

    @r.post("/install")
    async def do_install(body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        tables = [t for t in (body.get("tables") or []) if isinstance(t, str) and t.replace("_", "").isalnum()]
        return await install(tables or None)

    return r
