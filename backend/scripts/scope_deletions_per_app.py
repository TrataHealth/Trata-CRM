"""One-off: old console deletions/suspensions sat on the shared users row — move them to the app-specific profiles only."""
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
load_dotenv(os.path.join(ROOT, ".env"))
import canonical_providers as cp  # noqa: E402

STAFF = ["pharmacist", "lab_tech", "receptionist", "nurse"]


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    r = await conn.execute("""UPDATE public.users SET is_archived = FALSE, is_active = TRUE, archived_at = NULL, archived_reason = NULL,
                                     purge_after = NULL, updated_at = now()
                               WHERE coalesce(is_archived, FALSE) AND coalesce(archived_reason, '') <> 'erased'
                                 AND coalesce(role, '') <> ALL($1::text[])""", STAFF)
    print("logins unlocked:", r)
    susp = await conn.fetch("SELECT id, suspended_by, suspended_reason FROM public.users WHERE coalesce(is_suspended, FALSE)")
    moved = 0
    for s in susp:
        if await cp.users_with_profiles(conn, [s["id"]]):
            moved += await cp.suspend_profiles(conn, [s["id"]], s["suspended_by"], s["suspended_reason"])
        else:
            moved += int((await conn.execute("""UPDATE public.customer_profiles SET is_suspended = TRUE, suspended_at = now(),
                          suspended_by = $2, suspended_reason = $3 WHERE user_id = $1""", s["id"], s["suspended_by"], s["suspended_reason"])).rsplit(" ", 1)[-1])
        await conn.execute("""UPDATE public.users SET is_suspended = FALSE, suspended_at = NULL, suspended_reason = NULL,
                              suspended_by = NULL WHERE id = $1""", s["id"])
    print("suspensions moved to app profiles:", moved, "of", len(susp))
    await conn.close()

asyncio.run(main())
