# Direct Postgres helper for Phase D canonical tests (read + targeted restore)
import asyncio
import os
import asyncpg
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
DSN = os.environ.get("DATABASE_URL")


async def _q(sql, *args, fetch="all"):
    conn = await asyncpg.connect(DSN, statement_cache_size=0)
    try:
        if fetch == "all":
            return [dict(r) for r in await conn.fetch(sql, *args)]
        if fetch == "row":
            r = await conn.fetchrow(sql, *args)
            return dict(r) if r else None
        if fetch == "val":
            return await conn.fetchval(sql, *args)
        return await conn.execute(sql, *args)
    finally:
        await conn.close()


def q(sql, *args, fetch="all"):
    return asyncio.run(_q(sql, *args, fetch=fetch))
