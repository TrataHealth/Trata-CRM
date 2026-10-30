"""Gap-free change capture on the shared Supabase DB: a trigger on each app table writes every INSERT/UPDATE/DELETE
into trata_audit.activity_log in the same transaction. The Admin Console reads it in id order with a snapshot-safe cursor."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import supabase_db as sb

# Constant-churn or secret-bearing tables (key-value caches, callback/outbox queues, chats, OTP/token stores, GPS pings).
NOISY_RE = r"(_kv$|callback_log|outbox|outbound_.*events|webhook_events|chat|_messages$|conversations$|location_ping|heartbeat|presence|crypto_sessions|otp|_tokens$|recommendation_cache|alembic_version)"
# Tables owned by the Provider app / TrataX; everything else belongs to the Patient app. `users` is shared by both.
PROVIDER_RE = (r"^(tratax_|hospital_|labs$|lab_|patholog|path_lab|pharmacy_|ambulance|paramedic|doctor|diagnostic_centre|kyc_|org_entities|"
               r"organisations|provider_|crm_provider|bed_|bills$|admission_notes|discharge|duty_|referring|sanjeevani|test_packages|"
               r"medicine_catalog|facilities|blood_banks|blood_stock|dental_clinics|vet_clinics|nutritionists|wellness_professionals|"
               r"wellness_event_providers|mental_health_consultants|retreat_centers|companies|company_employees|platform_plans|tenant_|users$)")
PATIENT_EXCLUDE_RE = PROVIDER_RE.replace("|users$)", ")")


# Rows that "are" a person/organisation; ids found on them pull in that record's linked rows (tenant, KYC application...).
PROFILE_RE = (r"^(users|.*_profiles|.*_providers|labs|doctors|pathologists|org_entities|organisations|tratax_tenants|"
              r"tratax_kyc_applications|customer_profiles|sanjeevani_agents)$")


def scope_of(t: str) -> List[str]:
    if t == "users":
        return ["patient", "provider"]
    return ["provider"] if re.search(PROVIDER_RE, t) else ["patient"]

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
ALTER TABLE trata_audit.activity_log ADD COLUMN IF NOT EXISTS refs text[];
CREATE INDEX IF NOT EXISTS activity_log_refs ON trata_audit.activity_log USING gin (refs);
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

-- Every id-like value in the row (id, *_id, *_uid) so a record's full history can be found with one index lookup.
CREATE OR REPLACE FUNCTION trata_audit.refs_of(j jsonb) RETURNS text[] LANGUAGE sql IMMUTABLE AS $f$
  SELECT array_agg(DISTINCT value) FROM jsonb_each_text(j)
   WHERE (key = 'id' OR key ~ '_(id|uid)$') AND value IS NOT NULL AND length(value) BETWEEN 4 AND 80
$f$;
UPDATE trata_audit.activity_log SET refs = trata_audit.refs_of(coalesce(new_data, '{}'::jsonb) || coalesce(old_data, '{}'::jsonb))
 WHERE refs IS NULL;

CREATE OR REPLACE FUNCTION trata_audit.capture() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $f$
DECLARE o jsonb; n jsonb; ch text[]; rf text[];
BEGIN
  BEGIN
    IF TG_OP <> 'INSERT' THEN o := trata_audit.clean(to_jsonb(OLD)); END IF;
    IF TG_OP <> 'DELETE' THEN n := trata_audit.clean(to_jsonb(NEW)); END IF;
    rf := trata_audit.refs_of(coalesce(n, '{}'::jsonb) || coalesce(o, '{}'::jsonb));
    IF TG_OP = 'UPDATE' THEN
      SELECT array_agg(k) INTO ch FROM jsonb_object_keys(n) k WHERE n->k IS DISTINCT FROM o->k AND k NOT IN ('updated_at', 'last_seen_at');
      IF ch IS NULL THEN RETURN NULL; END IF;
      SELECT jsonb_object_agg(k, o->k) INTO o FROM unnest(ch) k;
      SELECT jsonb_object_agg(k, n->k) INTO n FROM unnest(ch) k;
    END IF;
    INSERT INTO trata_audit.activity_log (table_name, op, row_id, app, db_role, old_data, new_data, changed, refs)
    VALUES (TG_TABLE_NAME, TG_OP, coalesce(n->>'id', o->>'id', (to_jsonb(coalesce(NEW, OLD)))->>'id'),
            coalesce(nullif(current_setting('trata.app', true), ''),
                     nullif(nullif(current_setting('application_name', true), ''), 'Supavisor'),
                     CASE WHEN current_setting('role', true) IN ('authenticated', 'anon') THEN 'app-user (Supabase client)'
                          WHEN current_setting('role', true) = 'service_role' THEN 'app-server (service key)' END),
            coalesce(nullif(current_setting('role', true), 'none'), session_user), o, n, ch, rf);
  EXCEPTION WHEN others THEN
    -- Never block another app's write because of auditing.
    RAISE WARNING 'trata_audit.capture failed on %: %', TG_TABLE_NAME, SQLERRM;
  END;
  RETURN NULL;
END $f$;

CREATE OR REPLACE FUNCTION trata_audit.is_noisy(t text) RETURNS boolean LANGUAGE sql IMMUTABLE AS $f$
  SELECT t ~* '__NOISY__'
$f$;

-- Any table any app creates later in public is tracked the moment it is created.
CREATE OR REPLACE FUNCTION trata_audit.auto_attach() RETURNS event_trigger LANGUAGE plpgsql AS $f$
DECLARE r record;
BEGIN
  FOR r IN SELECT * FROM pg_event_trigger_ddl_commands() WHERE object_type IN ('table') AND schema_name = 'public' LOOP
    BEGIN
      IF NOT trata_audit.is_noisy(split_part(r.object_identity, '.', 2)) THEN
        EXECUTE format('CREATE OR REPLACE TRIGGER trata_audit_capture AFTER INSERT OR UPDATE OR DELETE ON %s '
                       'FOR EACH ROW EXECUTE FUNCTION trata_audit.capture()', r.object_identity);
      END IF;
    EXCEPTION WHEN others THEN
      RAISE WARNING 'trata_audit.auto_attach failed on %: %', r.object_identity, SQLERRM;
    END;
  END LOOP;
END $f$;
DROP EVENT TRIGGER IF EXISTS trata_audit_auto_attach;
CREATE EVENT TRIGGER trata_audit_auto_attach ON ddl_command_end WHEN TAG IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO')
  EXECUTE FUNCTION trata_audit.auto_attach();
""".replace("__NOISY__", NOISY_RE)


async def install(tables: Optional[List[str]] = None) -> Dict[str, Any]:
    """Attach the recorder to the given tables, or to every non-noisy public table that is not tracked yet."""
    pool = await sb.get_pool()
    attached, missing, failed = [], [], []
    async with pool.acquire() as conn:
        await conn.execute(INSTALL_SQL)
        existing = {r["relname"] for r in await conn.fetch(
            "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT c.relispartition")}
        covered = {r["relname"] for r in await conn.fetch(
            "SELECT c.relname FROM pg_trigger g JOIN pg_class c ON c.oid = g.tgrelid WHERE g.tgname = 'trata_audit_capture'")}
        todo = tables or sorted(t for t in existing - covered if not re.search(NOISY_RE, t, re.I))
        for t in todo:
            if t not in existing:
                missing.append(t)
                continue
            try:
                async with conn.transaction():
                    await conn.execute("SET LOCAL lock_timeout = '3s'")
                    await conn.execute(f'CREATE OR REPLACE TRIGGER trata_audit_capture AFTER INSERT OR UPDATE OR DELETE ON public."{t}" '
                                       f'FOR EACH ROW EXECUTE FUNCTION trata_audit.capture()')
                attached.append(t)
            except Exception as e:  # busy table: picked up on the next run
                failed.append({"table": t, "error": str(e)[:200]})
    return {"attached": attached, "missing": missing, "failed": failed}


def create_audit_router(get_current_user) -> APIRouter:
    r = APIRouter(prefix="/api/admin/activity-log")

    def master(c):
        if not c.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")

    @r.get("")
    async def feed(after_txid: Optional[int] = None, before_id: Optional[int] = None, table: Optional[str] = None, op: Optional[str] = None,
                   app: Optional[str] = None, row_id: Optional[str] = None, scope: Optional[str] = None, limit: int = 50, current=Depends(get_current_user)):
        """Newest-first page (before_id) or catch-up page (after_txid). Catch-up walks whole finished transactions in txid
        order and stops at the oldest in-flight one, so a slow commit can never be skipped by the cursor."""
        master(current)
        limit = max(1, min(limit, 200))
        cond, args = ["true"], []
        for col, val in (("table_name", table), ("op", op), ("app", app), ("row_id", row_id)):
            if val:
                args.append(val)
                cond.append(f"{col} = ${len(args)}")
        if scope == "provider":
            args.append(PROVIDER_RE)
            cond.append(f"table_name ~ ${len(args)}")
        elif scope == "patient":
            args.append(PATIENT_EXCLUDE_RE)
            cond.append(f"table_name !~ ${len(args)}")
        if before_id:
            args.append(before_id)
            cond.append(f"id < ${len(args)}")
        order = "id DESC"
        if after_txid is not None:
            args.append(after_txid)
            cond.append(f"txid > ${len(args)}::xid8 AND txid < pg_snapshot_xmin(pg_current_snapshot())")
            order = "txid ASC, id ASC"
        pool = await sb.get_pool()
        async with pool.acquire() as conn, conn.transaction(isolation="repeatable_read", readonly=True):  # one snapshot for rows + cursor
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
            cursor = safe if after_txid is None or safe > after_txid else after_txid
        return {"items": items, "cursor_txid": cursor}

    @r.get("/record/{rid}")
    async def record_history(rid: str, after_id: int = 0, limit: int = 300, current=Depends(get_current_user)):
        """Every recorded change to this person/organisation and to rows that point at them, oldest first."""
        master(current)
        limit = max(1, min(limit, 500))
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            seeds = await conn.fetchval("""SELECT array_agg(DISTINCT x) FROM (
                     SELECT unnest(refs) x FROM trata_audit.activity_log
                      WHERE table_name ~ $2 AND (row_id = $1 OR refs @> ARRAY[$1])) s""", rid, PROFILE_RE) or []
            ids = sorted(set(seeds) | {rid})
            rows = await conn.fetch("""SELECT id, at, table_name, op, row_id, app, old_data, new_data, changed
                                         FROM trata_audit.activity_log WHERE refs && $1::text[] AND id > $2
                                        ORDER BY id ASC LIMIT $3""", ids, after_id, limit)
            since = await conn.fetchval("SELECT min(at) FROM trata_audit.activity_log")
        import json
        items = [{**dict(x), "at": x["at"].isoformat(), "old_data": json.loads(x["old_data"]) if x["old_data"] else None,
                  "new_data": json.loads(x["new_data"]) if x["new_data"] else None} for x in rows]
        return {"items": items, "linked_ids": len(ids), "more": len(items) == limit,
                "recording_since": since.isoformat() if since else None}

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
                                              AND relname <> ALL($1::text[]) ORDER BY n_live_tup DESC""", covered)
            auto = await conn.fetchval("SELECT evtenabled <> 'D' FROM pg_event_trigger WHERE evtname = 'trata_audit_auto_attach'")
            apps = await conn.fetch("""SELECT coalesce(app, 'unknown') AS app, count(*) AS n FROM trata_audit.activity_log
                                        WHERE at > now() - interval '7 days' GROUP BY 1 ORDER BY 2 DESC""")
        by = {s["table_name"]: s for s in stats}
        noisy = [u for u in uncovered if re.search(NOISY_RE, u["relname"], re.I)]
        return {"auto_attach": bool(auto),
                "skipped_noisy": [{"table": u["relname"], "rows": u["n_live_tup"]} for u in noisy],
                "covered": [{"table": t, "scope": scope_of(t), "last_24h": (by.get(t) or {}).get("last_24h", 0), "total": (by.get(t) or {}).get("total", 0),
                             "last_at": by[t]["last_at"].isoformat() if t in by else None} for t in covered],
                "uncovered_with_data": [{"table": u["relname"], "rows": u["n_live_tup"]} for u in uncovered if u not in noisy],
                "apps_7d": [dict(a) for a in apps]}

    @r.post("/install")
    async def do_install(body: Dict[str, Any], current=Depends(get_current_user)):
        master(current)
        tables = [t for t in (body.get("tables") or []) if isinstance(t, str) and t.replace("_", "").isalnum()]
        return await install(tables or None)

    return r
