"""Erase cron end-to-end on TEST_probe hospital B only (destroys probe B; re-run fixtures setup afterwards)."""
import asyncio
import json
import sys
import time

import asyncpg
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import BASE_URL, DSN, ENV  # noqa: E402

API = f"{BASE_URL}/api"
S = json.load(open("/tmp/ledger_probe_state.json"))
mdb = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]
H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731


def _sb(q, *a):
    async def f():
        c = await asyncpg.connect(DSN, statement_cache_size=0)
        try:
            return await c.fetch(q, *a)
        finally:
            await c.close()
    return asyncio.run(f())


def test_erase_due_probe_b():
    # guard: nothing else may be due
    others = list(mdb.contacts.find({"archived": True, "supabase_user_id": {"$ne": S["uid_b"]}}, {"_id": 0, "id": 1}))
    assert not others, f"other archived contacts present, refusing: {others}"
    c = mdb.contacts.find_one({"supabase_user_id": S["uid_b"]}, {"_id": 0, "id": 1})
    r = requests.post(f"{API}/admin/users/bulk", headers=H(S["tok_admin"]), json={"contact_ids": [c["id"]], "action": "archive", "reason": "TEST_probe erase"}, timeout=60)
    assert r.status_code == 200 and r.json()["updated"] == 1
    mdb.contacts.update_one({"id": c["id"]}, {"$set": {"purge_after": "2000-01-01T00:00:00+00:00"}})
    _sb("UPDATE public.users SET purge_after = now() - interval '1 day' WHERE id=$1", S["uid_b"])
    r = requests.post(f"{API}/admin/cron/erase-archived", headers=H(ENV["WEBHOOK_CRON_SECRET"]), timeout=30)
    assert r.status_code == 200 and r.json() == {"accepted": True}
    for _ in range(20):
        time.sleep(2)
        if not mdb.contacts.find_one({"id": c["id"]}):
            break
    assert not mdb.contacts.find_one({"id": c["id"]}), "contact not erased"
    rows = _sb("SELECT id, name, phone, archived_reason FROM public.users WHERE id=$1", S["uid_b"])
    print("supabase row after erase:", [dict(x) for x in rows])
    assert not rows or rows[0]["name"] == "Deleted user"
    assert not mdb.crm_users.find_one({"phone": "9999900022"})
