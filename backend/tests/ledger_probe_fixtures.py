"""TEST_probe fixtures for Provider Ledger tests (SHARED PRODUCTION Supabase).
Creates 2 probe hospitals (phones 9999900021/22) each with one TEST emergency_cases row
for an existing Patient-App patient, so they have a "served" patient.
Usage: python ledger_probe_fixtures.py setup|cleanup
"""
import asyncio
import json
import sys
import uuid

import asyncpg
import requests

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import BASE_URL, DSN, ENV, LAT, LNG, login  # noqa: E402

PHONE_A, PHONE_B = "9999900021", "9999900022"
PHONES = [PHONE_A, PHONE_B]
PATIENT_ID = "9afe9c0c-3cb9-4827-b144-bcef70ef2bd9"
PWD = "Probe@12345"
STATE_FILE = "/tmp/ledger_probe_state.json"


async def _cleanup_sb():
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    try:
        ids = [r["id"] for r in await c.fetch("SELECT id FROM public.users WHERE phone = ANY($1::text[])", PHONES)]
        if ids:
            await c.execute("DELETE FROM public.emergency_cases WHERE hospital_id = ANY($1::text[]) OR customer_phone = 'TEST_probe_ledger'", ids)
            await c.execute("DELETE FROM public.notifications WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.kyc_documents WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.hospital_beds WHERE hospital_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.hospital_bed_inventory WHERE hospital_id IN (SELECT id FROM public.hospital_profiles WHERE user_id = ANY($1::text[])) OR hospital_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.hospital_profiles WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.users WHERE id = ANY($1::text[])", ids)
        await c.execute("DELETE FROM public.emergency_cases WHERE customer_phone = 'TEST_probe_ledger'")
        return ids
    finally:
        await c.close()


async def _cleanup_mongo(ids):
    from motor.motor_asyncio import AsyncIOMotorClient
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    db = cl[ENV["DB_NAME"]]
    q = {"provider_user_id": {"$in": ids}}
    for coll in ("ledger_services", "ledger_files", "ledger_promotions", "ledger_invoices", "billing_profiles"):
        await db[coll].delete_many(q)
    await db.ledger_services.delete_many({"title": {"$regex": "TEST_probe"}})
    await db.ledger_promotions.delete_many({"title": {"$regex": "TEST_probe"}})
    await db.crm_users.delete_many({"phone": {"$in": PHONES}})
    await db.contacts.delete_many({"phone": {"$in": PHONES}})
    for c in await db.ledger_counters.find({}, {"_id": 0, "id": 1}).to_list(500):
        if not await db.ledger_invoices.count_documents({"month": c["id"].replace("inv-", ""), "number": {"$ne": None}}):
            await db.ledger_counters.delete_one({"id": c["id"]})
    cl.close()


def cleanup():
    prev = []
    try:
        prev = json.load(open(STATE_FILE)).get("uids", [])
    except Exception:
        pass
    ids = asyncio.run(_cleanup_sb())
    asyncio.run(_cleanup_mongo(list(set(ids + prev))))


async def _seed(uids):
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    try:
        loc = json.dumps({"lat": LAT, "lng": LNG, "address": "TEST_probe ledger"})
        out = []
        for u in uids:
            cid = str(uuid.uuid4())
            await c.execute("""INSERT INTO public.emergency_cases (id, customer_id, customer_phone, case_type, location,
                                 status, hospital_id, priority, created_at, updated_at)
                               VALUES ($1,$2,'TEST_probe_ledger','medical',$3::json,'COMPLETED',$4,'high',now(),now())""",
                            cid, PATIENT_ID, loc, u)
            out.append(cid)
        return out
    finally:
        await c.close()


def setup():
    cleanup()
    from server_admin_login import admin_token
    tok = admin_token()
    hdr = {"Authorization": f"Bearer {tok}"}
    uids = []
    for phone, name in ((PHONE_A, "TEST_probe Ledger Hosp A"), (PHONE_B, "TEST_probe Ledger Hosp B")):
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers", headers=hdr, timeout=30, json={
            "vertical": "hospital", "phone": phone, "name": name, "city": "Mumbai", "state": "Maharashtra",
            "email": "probe@test.local", "address": "TEST_probe addr", "lat": LAT, "lng": LNG})
        assert r.status_code == 200, r.text
        uids.append(r.json()["user_id"])
    cases = asyncio.run(_seed(uids))
    s = {"uids": uids, "uid_a": uids[0], "uid_b": uids[1], "cases": cases, "tok_admin": tok}
    s["tok_a"], _ = login(PHONE_A, PWD)
    s["tok_b"], _ = login(PHONE_B, PWD)
    json.dump(s, open(STATE_FILE, "w"))
    return s


if __name__ == "__main__":
    if sys.argv[1] == "setup":
        print(json.dumps(setup(), indent=1))
    else:
        cleanup()
        print("cleaned")
