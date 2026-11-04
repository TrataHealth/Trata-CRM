"""Fixtures for directory bulk actions: creates/cleans TEST users (phones 89555000xx) in shared Supabase.
Usage: python bulk_dir_fixtures.py setup|cleanup|cols
"""
import asyncio
import json
import sys
import uuid

import asyncpg
from pymongo import MongoClient

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import DSN, ENV  # noqa: E402

STATE = "/tmp/bulk_dir_state.json"
USERS = [("Bulk UI Sample", "8955500011", "patient"), ("Bulk Sample Two", "8955500012", "patient"),
         ("Bulk Sample Clinic", "8955500013", "doctor")]


async def cols():
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    rows = await c.fetch("""SELECT column_name, is_nullable, column_default, data_type FROM information_schema.columns
                            WHERE table_schema='public' AND table_name='users' AND is_nullable='NO'""")
    for r in rows:
        print(dict(r))
    await c.close()


async def setup():
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    st = {}
    for name, phone, role in USERS:
        ex = await c.fetchval("SELECT id FROM public.users WHERE phone=$1", phone)
        uid = ex or str(uuid.uuid4())
        if not ex:
            await c.execute("INSERT INTO public.users (id, phone, name, role, created_at, updated_at) VALUES ($1,$2,$3,$4,now(),now())",
                            uid, phone, name, role)
        st[phone] = uid
    await c.close()
    json.dump(st, open(STATE, "w"))
    print(st)


async def cleanup():
    st = json.load(open(STATE))
    uids = list(st.values())
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    n = await c.execute("DELETE FROM public.users WHERE id = ANY($1::text[]) AND (phone LIKE '895550%' OR phone LIKE 'pnd-895550%')", uids)
    await c.close()
    m = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]
    cids = [x["id"] for x in m.contacts.find({"supabase_user_id": {"$in": uids}}, {"id": 1})]
    print(n, m.contacts.delete_many({"supabase_user_id": {"$in": uids}}).deleted_count,
          m.notifications.delete_many({"user_id": {"$in": uids}}).deleted_count,
          m.audit_log.delete_many({"supabase_user_ids": {"$in": uids}}).deleted_count, cids)


if __name__ == "__main__":
    asyncio.run({"setup": setup, "cleanup": cleanup, "cols": cols}[sys.argv[1]]())
