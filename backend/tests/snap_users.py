# Snapshot shared users rows + customer_profiles flags for given phones (read-only)
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
import supabase_db as sb  # noqa: E402


async def main(phones):
    pool = await sb.get_pool()
    async with pool.acquire() as c:
        for r in await c.fetch("""SELECT id, phone, role, is_active, is_suspended, is_archived, archived_reason, purge_after, verification_status
                                    FROM public.users WHERE right(phone,10) = ANY($1::text[]) ORDER BY phone""", phones):
            print("USER", dict(r))
        for r in await c.fetch("""SELECT user_id, phone, is_suspended, is_archived, archived_reason, purge_after
                                    FROM public.customer_profiles WHERE right(coalesce(phone,''),10) = ANY($1::text[])""", phones):
            print("CP", dict(r))
        for r in await c.fetch("""SELECT user_id, verification_status, local_decision->>'pre_suspend_status' pss, is_active
                                    FROM public.diagnostic_centre_profiles WHERE user_id IN (SELECT id FROM public.users WHERE right(phone,10)=ANY($1::text[]))""", phones):
            print("DC", dict(r))


asyncio.run(main(sys.argv[1:]))
