# Phase D retest (iter 32) — Supabase->CRM mirror must not echo onto canonical tables; hook is CRM-owned only;
# kyc-admin-final final-status event / 400 CHECK / 409 no canonical row; /supabase/contacts limit cap
import asyncio
import os
import sys
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, "/app/backend")
from pg_helper import q, _q  # noqa: E402
from test_phase_d_canonical import _login, API, ZEN_CONTACT, ZEN_USER  # noqa: E402

ENV = dotenv_values("/app/backend/.env")
MDB = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]
SNAP_SQL = " UNION ALL ".join(
    f"SELECT '{t}' t, user_id::text u, {n}::text n, city::text c, state::text s, address::text a, email::text e FROM public.{t}"
    for t, n in (("path_lab_profiles", "name"), ("pharmacy_providers", "business_name"), ("hospital_profiles", "name"),
                 ("doctors", "full_name"), ("ambulance_providers", "business_name")))


def _snap():
    return {(r["t"], r["u"]): (r["n"], r["c"], r["s"], r["a"], r["e"]) for r in q(SNAP_SQL)}


def _zen():
    return q("SELECT city, state, address, pincode, latitude, longitude, is_demo, verification_status, pipeline_stage, kyc_status, "
             "local_decision, ai_fields_applied_by, ai_fields_applied_at FROM public.path_lab_profiles WHERE user_id=$1", ZEN_USER, fetch="row")


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module", autouse=True)
def restore_all():
    zen = _zen()
    users_vs = q("SELECT verification_status FROM public.users WHERE id=$1", ZEN_USER, fetch="val")
    mongo = MDB.contacts.find_one({"id": ZEN_CONTACT}, {"_id": 0})
    yield
    time.sleep(6)
    q("""UPDATE public.path_lab_profiles SET city=$2, state=$3, address=$4, pincode=$5, latitude=$6, longitude=$7, is_demo=$8,
         verification_status=$9, pipeline_stage=$10, kyc_status=$11, local_decision=$12::jsonb, ai_fields_applied_by=$13,
         ai_fields_applied_at=$14 WHERE user_id=$1""", ZEN_USER, zen["city"], zen["state"], zen["address"], zen["pincode"],
      zen["latitude"], zen["longitude"], zen["is_demo"], zen["verification_status"], zen["pipeline_stage"], zen["kyc_status"],
      zen["local_decision"] if zen["local_decision"] is None or isinstance(zen["local_decision"], str) else __import__("json").dumps(zen["local_decision"]),
      zen["ai_fields_applied_by"], zen["ai_fields_applied_at"], fetch="exec")
    q("UPDATE public.users SET verification_status=$2 WHERE id=$1", ZEN_USER, users_vs, fetch="exec")
    keep = {k: mongo.get(k) for k in ("city", "state", "address", "email", "kyc_status", "pipeline_stage", "deal_value",
                                     "kyc_admin_decision_at", "kyc_admin_decision_notes", "kyc_admin_decision_by")}
    MDB.contacts.update_one({"id": ZEN_CONTACT}, {"$set": keep})


# ── Mirror must not echo ─────────────────────────────────────────────────────
class TestMirrorNoEcho:
    def test_sync_endpoint_no_canonical_write(self, admin):
        q("UPDATE public.path_lab_profiles SET city='TEST_Repro' WHERE user_id=$1", ZEN_USER, fetch="exec")
        before = _snap()
        r = admin.post(f"{API}/admin/sync-supabase-users", timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        print("sync:", d)
        assert d.get("success") is not False, d
        time.sleep(10)
        assert _zen()["city"] == "TEST_Repro"
        after = _snap()
        diff = {k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)}
        assert not diff, f"canonical rows changed by mirror: {diff}"
        # upstream city now read from path_lab_profiles → mongo picks it up
        assert MDB.contacts.find_one({"id": ZEN_CONTACT})["city"] == "TEST_Repro"

    def test_mirror_never_sets_none(self, admin):
        q("UPDATE public.path_lab_profiles SET city=NULL WHERE user_id=$1", ZEN_USER, fetch="exec")
        MDB.contacts.update_one({"id": ZEN_CONTACT}, {"$set": {"city": "Pune"}})
        nulls_before = MDB.contacts.count_documents({"city": None})
        time.sleep(1)
        r = admin.post(f"{API}/admin/sync-supabase-users", timeout=120)
        assert r.status_code == 200, r.text
        assert MDB.contacts.find_one({"id": ZEN_CONTACT})["city"] == "Pune"
        assert MDB.contacts.count_documents({"city": None}) <= nulls_before
        time.sleep(5)
        assert _zen()["city"] is None

    def test_contacts_ttl_autosync_no_echo(self, admin):
        q("UPDATE public.path_lab_profiles SET city='TEST_Repro2' WHERE user_id=$1", ZEN_USER, fetch="exec")
        before = _snap()
        time.sleep(62)  # outlive the 60s TTL so GET /contacts runs the mirror
        r = admin.get(f"{API}/contacts?limit=5", timeout=120)
        assert r.status_code == 200, r.text
        time.sleep(10)
        assert MDB.contacts.find_one({"id": ZEN_CONTACT}).get("last_upstream_sync_at")
        assert _zen()["city"] == "TEST_Repro2"
        after = _snap()
        diff = {k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)}
        assert not diff, diff
        q("UPDATE public.path_lab_profiles SET city=NULL WHERE user_id=$1", ZEN_USER, fetch="exec")


# ── Proxy hook: CRM-owned only (in-process) ──────────────────────────────────
class TestHookCrmOwnedOnly:
    def test_hook_drops_display_keys(self):
        async def run():
            for k, v in ENV.items():
                os.environ.setdefault(k, v)
            from motor.motor_asyncio import AsyncIOMotorClient
            import canonical_providers as cp
            raw = AsyncIOMotorClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]
            sdb = cp.SyncedDB(raw)
            orig = await raw.contacts.find_one({"id": ZEN_CONTACT}, {"_id": 0, "deal_value": 1, "city": 1, "name": 1})
            canon0 = await _q("SELECT name, city, deal_value FROM public.path_lab_profiles WHERE user_id=$1", ZEN_USER, fetch="row")
            await sdb.contacts.update_one({"id": ZEN_CONTACT}, {"$set": {"city": "TEST_HookCity", "name": "TEST_HookName",
                                                                       "deal_value": 4242}})
            await asyncio.sleep(6)
            canon = await _q("SELECT name, city, deal_value FROM public.path_lab_profiles WHERE user_id=$1", ZEN_USER, fetch="row")
            await raw.contacts.update_one({"id": ZEN_CONTACT}, {"$set": {"city": orig.get("city"), "name": orig.get("name"),
                                                                       "deal_value": orig.get("deal_value")}})
            await _q("UPDATE public.path_lab_profiles SET deal_value=$2 WHERE user_id=$1", ZEN_USER, canon0["deal_value"], fetch="exec")
            return canon0, canon
        canon0, canon = asyncio.run(run())
        assert float(canon["deal_value"] or 0) == 4242, canon
        assert canon["city"] == canon0["city"] and canon["name"] == canon0["name"], (canon0, canon)


# ── kyc-admin-final ──────────────────────────────────────────────────────────
class TestKycFinal:
    def test_pending_address_outbound_uses_final(self, admin):
        q("UPDATE public.path_lab_profiles SET city=NULL WHERE user_id=$1", ZEN_USER, fetch="exec")
        t0 = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 2))
        r = admin.post(f"{API}/contacts/{ZEN_CONTACT}/kyc-admin-final", json={"decision": "verified", "notes": "TEST_iter32"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["verification_status"] == "pending_address"
        # Phase D follow-up: outbound webhooks retired → no admin_bridge_outbound row is written
        ev = MDB.admin_bridge_outbound.find_one({"event": "crm.kyc.admin_verified", "created_at": {"$gte": t0}})
        assert ev is None, "outbound retired but an event was queued"
        assert r.json()["contact"]["kyc_status"] == "pending_address"

    def test_check_violation_is_400(self, admin):
        q("""UPDATE public.path_lab_profiles SET address='TEST_addr', city='TEST_City', state='TEST_State', pincode='411001',
             latitude=18.5, longitude=73.8, is_demo=true WHERE user_id=$1""", ZEN_USER, fetch="exec")
        before = MDB.contacts.find_one({"id": ZEN_CONTACT}, {"_id": 0, "kyc_status": 1})
        r = admin.post(f"{API}/contacts/{ZEN_CONTACT}/kyc-admin-final", json={"decision": "verified"}, timeout=30)
        assert r.status_code == 400, r.text
        assert MDB.contacts.find_one({"id": ZEN_CONTACT})["kyc_status"] == before["kyc_status"]
        assert _zen()["verification_status"] != "verified"

    @pytest.mark.parametrize("uid", ["random", "none"])
    def test_no_canonical_row_is_409(self, admin, uid):
        cid = str(uuid.uuid4())
        doc = {"id": cid, "name": f"TEST_iter32_{uid}", "phone": f"TEST{cid[:8]}", "type": "pathologist",
               "pipeline_stage": "new", "kyc_status": "agent_reviewed", "archived": True}
        if uid == "random":
            doc["supabase_user_id"] = str(uuid.uuid4())
        MDB.contacts.insert_one(doc)
        try:
            r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified"}, timeout=30)
            got = MDB.contacts.find_one({"id": cid})
            assert r.status_code == 409, f"{r.status_code} {r.text[:300]}"
            assert got["kyc_status"] == "agent_reviewed"
        finally:
            MDB.contacts.delete_one({"id": cid})


# ── /supabase/contacts limit cap ─────────────────────────────────────────────
class TestLimitCap:
    def test_limit_capped(self, admin):
        r = admin.get(f"{API}/supabase/contacts?limit=5000", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["items"]) <= 1000 and len(d["items"]) == min(d["total"], 1000)
        r = admin.get(f"{API}/supabase/contacts?limit=0", timeout=60)
        assert r.status_code == 200 and len(r.json()["items"]) == 1
