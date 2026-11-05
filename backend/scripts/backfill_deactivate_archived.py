"""One-off: accounts deleted from the Admin Console (users.is_archived) get their profiles deactivated, as the Provider App does."""
import asyncio
import os
import sys

import asyncpg
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
import canonical_providers as cp  # noqa: E402


async def main():
    conn = await asyncpg.connect(os.environ["DATABASE_URL"], statement_cache_size=0)
    rows = await conn.fetch("SELECT id, archived_reason FROM public.users WHERE coalesce(is_archived, FALSE)")
    groups = {}
    for r in rows:
        groups.setdefault((r["archived_reason"] or "Deleted in Admin Console").replace("admin_deleted: ", ""), []).append(r["id"])
    n = 0
    for reason, ids in groups.items():
        n += await cp.deactivate_profiles(conn, ids, "Admin Console", reason)
        print(reason, len(ids), n, flush=True)
    print(f"archived accounts: {len(rows)} · profiles deactivated: {n}")
    await conn.close()

asyncio.run(main())
