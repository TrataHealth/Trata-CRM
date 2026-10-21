"""Shared TEST_probe fixtures for ambulance dispatch / discharge / live-updates tests.
SHARED PRODUCTION DB — only rows tied to phones 99999000 11/12/13 (names TEST_probe) are touched.
Usage: python live_probe_fixtures.py setup|cleanup
"""
import asyncio
import json
import sys
import uuid

import asyncpg
import requests

ENV = {}
for _f in ("/app/backend/.env", "/app/frontend/.env"):
    for line in open(_f):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            ENV[k] = v.strip().strip('"')
BASE_URL = ENV["REACT_APP_BACKEND_URL"].rstrip("/")
DSN = ENV["DATABASE_URL"]
OTP = "123456"
PROBE_PWD = "Probe@12345"
PHONE_AMB, PHONE_HOSP, PHONE_AMB_B = "9999900011", "9999900012", "9999900013"
PHONES = [PHONE_AMB, PHONE_HOSP, PHONE_AMB_B]
STATE_FILE = "/tmp/live_probe_state.json"
LAT, LNG = 19.1178, 72.8631


def login(phone, pwd):
    r = requests.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": phone}, timeout=60)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    h = {"Authorization": f"Bearer {d['temp_token']}"}
    ep = "set-password" if d.get("needs_password_setup") else "login-password"
    r = requests.post(f"{BASE_URL}/api/auth/{ep}", json={"password": pwd}, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    tok = r.json().get("token") or r.json().get("access_token")
    if r.json().get("user", {}).get("security_setup_required"):
        requests.post(f"{BASE_URL}/api/auth/security-setup", headers={"Authorization": f"Bearer {tok}"}, json={
            "recovery_email": "probe@test.local",
            "questions": [{"question_id": "q1", "answer": "trata"}, {"question_id": "q4", "answer": "trata"}]}, timeout=60)
    return tok, r.json().get("user")


async def _cleanup():
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    try:
        ids = [r["id"] for r in await c.fetch("SELECT id FROM public.users WHERE phone = ANY($1::text[])", PHONES)]
        apids = [r["id"] for r in await c.fetch("SELECT id FROM public.ambulance_providers WHERE user_id = ANY($1::text[])", ids)] if ids else []
        case_ids = [r["id"] for r in await c.fetch(
            "SELECT id FROM public.emergency_cases WHERE customer_phone = ANY($1::text[]) OR ambulance_provider_id = ANY($2::text[])",
            PHONES, apids)]
        await c.execute("DELETE FROM public.ambulance_allocations WHERE case_id = ANY($1::text[]) OR ambulance_provider_id = ANY($2::text[])", case_ids, apids)
        if ids:
            adm = [r["id"] for r in await c.fetch("SELECT id FROM public.patient_admissions WHERE hospital_id = ANY($1::text[]) OR patient_id = ANY($1::text[])", ids)]
            await c.execute("DELETE FROM public.discharge_summaries WHERE admission_id = ANY($1::text[])", adm)
            await c.execute("DELETE FROM public.admission_notes WHERE admission_id = ANY($1::text[])", adm)
            await c.execute("DELETE FROM public.patient_admissions WHERE id = ANY($1::text[])", adm)
        await c.execute("DELETE FROM public.emergency_cases WHERE id = ANY($1::text[])", case_ids)
        await c.execute("DELETE FROM public.ambulances WHERE provider_id = ANY($1::text[])", apids)
        if ids:
            await c.execute("DELETE FROM public.notifications WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.hospital_beds WHERE hospital_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.kyc_documents WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.hospital_bed_inventory WHERE hospital_id IN (SELECT id FROM public.hospital_profiles WHERE user_id = ANY($1::text[])) OR hospital_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.hospital_profiles WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.ambulance_providers WHERE user_id = ANY($1::text[])", ids)
            await c.execute("DELETE FROM public.users WHERE id = ANY($1::text[])", ids)
        await c.execute("DELETE FROM public.crm_provider_leads WHERE phone = ANY($1::text[]) AND name ILIKE 'TEST_probe%'", PHONES)
    finally:
        await c.close()
    from motor.motor_asyncio import AsyncIOMotorClient
    cl = AsyncIOMotorClient(ENV["MONGO_URL"])
    db = cl[ENV["DB_NAME"]]
    await db.crm_users.delete_many({"phone": {"$in": PHONES}})
    await db.contacts.delete_many({"phone": {"$in": PHONES}})
    await db.payouts.delete_many({"id": {"$regex": "^TEST_probe"}})
    await db.activities.delete_many({"contact_name": {"$regex": "^TEST_probe"}})
    cl.close()


def cleanup():
    asyncio.run(_cleanup())


async def _seed_db(amb_uid, hosp_uid, ambB_uid):
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    try:
        pa = await c.fetchval("SELECT id FROM public.ambulance_providers WHERE user_id=$1", amb_uid)
        pb = await c.fetchval("SELECT id FROM public.ambulance_providers WHERE user_id=$1", ambB_uid)
        s = {"amb_uid": amb_uid, "hosp_uid": hosp_uid, "ambB_uid": ambB_uid, "pa": pa, "pb": pb}
        loc = json.dumps({"lat": LAT, "lng": LNG, "address": "TEST_probe Andheri"})
        for key, prov in (("veh_a", pa), ("veh_a2", pa), ("veh_b", pb)):
            vid = str(uuid.uuid4())
            await c.execute("""INSERT INTO public.ambulances (id, provider_id, vehicle_number, ambulance_type, status)
                               VALUES ($1,$2,$3,'BLS','available')""", vid, prov, f"TEST-PROBE-{key.upper()}")
            s[key] = vid
        for key, prov, status in (("case_ok", pa, "PENDING"), ("case_ui", pa, "PENDING"), ("case_null", None, "PENDING"),
                                  ("case_other", pb, "PENDING"), ("case_closed", pa, "COMPLETED")):
            cid = str(uuid.uuid4())
            await c.execute("""INSERT INTO public.emergency_cases (id, customer_phone, case_type, location, status,
                                 ambulance_provider_id, priority, created_at, updated_at)
                               VALUES ($1,$2,'medical',$3::json,$4,$5,'high',now(),now())""",
                            cid, PHONE_AMB, loc, status, prov)
            s[key] = cid
        for key in ("adm_api", "adm_ui"):
            aid = str(uuid.uuid4())
            await c.execute("""INSERT INTO public.patient_admissions (id, admission_number, patient_id, hospital_id,
                                 admission_type, case_type, source, status, chief_complaint, triage_priority,
                                 admission_time, created_at, updated_at)
                               VALUES ($1,$2,$3,$4,'emergency','medical','walk_in','admitted','TEST_probe chest pain','medium',now(),now(),now())""",
                            aid, f"TEST-PROBE-{key.upper()}-{aid[:4]}", amb_uid, hosp_uid)
            s[key] = aid
        return s
    finally:
        await c.close()


def setup():
    cleanup()
    from server_admin_login import admin_token  # noqa
    hdr = {"Authorization": f"Bearer {admin_token()}"}
    uids = {}
    for phone, vert, name in ((PHONE_AMB, "ambulance", "TEST_probe Ambulance A"),
                              (PHONE_HOSP, "hospital", "TEST_probe Hospital"),
                              (PHONE_AMB_B, "ambulance", "TEST_probe Ambulance B")):
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers", headers=hdr, timeout=30, json={
            "vertical": vert, "phone": phone, "name": name, "city": "Mumbai", "state": "MH",
            "email": "probe@test.local", "address": "TEST_probe addr", "lat": LAT, "lng": LNG})
        assert r.status_code == 200, r.text
        uids[phone] = r.json()["user_id"]
    s = asyncio.run(_seed_db(uids[PHONE_AMB], uids[PHONE_HOSP], uids[PHONE_AMB_B]))
    s["tok_amb"], s["user_amb"] = login(PHONE_AMB, PROBE_PWD)
    s["tok_hosp"], s["user_hosp"] = login(PHONE_HOSP, PROBE_PWD)
    s["tok_ambB"], _ = login(PHONE_AMB_B, PROBE_PWD)
    s["tok_admin"] = hdr["Authorization"].split()[1]
    json.dump(s, open(STATE_FILE, "w"), default=str)
    return s


if __name__ == "__main__":
    sys.path.insert(0, "/app/backend/tests")
    if sys.argv[1] == "setup":
        print(json.dumps(setup(), default=str, indent=1))
    else:
        cleanup(); print("cleaned")
