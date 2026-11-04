"""Phase D §10 parity checks: legacy crm_provider_leads vs canonical tables. Read-only; prints markdown."""
import asyncio
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
import canonical_providers as cp  # noqa: E402
import supabase_db as sb  # noqa: E402

CMP = ["phone", "email", "city", "state", "pipeline_stage", "kyc_status", "deal_value", "assigned_agent_id"]


async def main():
    pool = await sb.get_pool()
    out = ["# Phase D parity report (§10)", ""]
    async with pool.acquire() as c:
        n = await c.fetchval("SELECT count(*) FROM public.crm_provider_leads l LEFT JOIN public.users u ON u.id = l.upstream_user_id WHERE u.id IS NULL")
        out.append(f"## 1. Legacy rows without a users row: **{n}** {'PASS' if n == 0 else 'FAIL'}")
        out.append("\n## 2. Legacy rows without a canonical row")
        for t, (tbl, name) in cp.TABLES.items():
            rows = await c.fetch(f"""SELECT l.name FROM public.crm_provider_leads l LEFT JOIN public.{tbl} p ON p.user_id = l.upstream_user_id
                                      WHERE l.type = $1 AND p.id IS NULL""", t)
            tot = await c.fetchval("SELECT count(*) FROM public.crm_provider_leads WHERE type = $1", t)
            out.append(f"- {t} → {tbl}: {tot} legacy rows, {len(rows)} missing {'PASS' if not rows else 'FAIL ' + str([r[0] for r in rows])}")
        out.append("\n## 3. Column spot-check (up to 5 per type)")
        for t, (tbl, name) in cp.TABLES.items():
            rows = await c.fetch(f"""SELECT l.name AS l_name, p.{name} AS p_name, {', '.join(f'l.{k} AS l_{k}, p.{k} AS p_{k}' for k in CMP)}
                                      FROM public.crm_provider_leads l JOIN public.{tbl} p ON p.user_id = l.upstream_user_id
                                     WHERE l.type = $1 LIMIT 5""", t)
            for r in rows:
                diffs = [f"{k}: legacy={r['l_' + k]!r} canonical={r['p_' + k]!r}" for k in ["name"] + CMP
                         if str(r['l_' + k] or '').removeprefix('+91') != str(r['p_' + k] or '').removeprefix('+91')]
                out.append(f"- {t} · {r['l_name']}: {'match' if not diffs else 'DIFF → ' + '; '.join(diffs)}")
        out.append("\n## 4. Verified counts (legacy is_verified vs canonical)")
        for t, (tbl, _) in cp.TABLES.items():
            lv = await c.fetchval("SELECT count(*) FROM public.crm_provider_leads WHERE type = $1 AND is_verified", t)
            cv = await c.fetchval(f"SELECT count(*) FROM ({await cp.union_sql(c)}) u WHERE type = $1 AND verification_status = 'verified'", t)
            out.append(f"- {t}: legacy {lv} vs canonical {cv} {'PASS' if lv == cv else 'DIFF'}")
    print("\n".join(out))


asyncio.run(main())
