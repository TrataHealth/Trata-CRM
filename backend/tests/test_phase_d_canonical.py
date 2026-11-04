# Phase D — CRM reads/writes the 6 canonical provider tables (no crm_provider_leads)
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
from pg_helper import q  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"

ZEN_CONTACT = "77d46c7b-8a90-46e6-9043-84b698fc7a1e"
ZEN_USER = "f585d675-96bb-569a-8b28-1ef336ff71ff"
ROHAN_ID = "7044b30e-5995-4bc5-a606-4f230a3f5d10"
FIELDS = {"type", "id", "user_id", "name", "phone", "pipeline_stage", "kyc_status", "deal_value",
          "assigned_agent_id", "verification_status"}
TYPES = {"hospital", "pathologist", "doctor", "pharmacy", "ambulance_provider"}


def _login(phone, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=30)
    assert r.status_code == 200, r.text
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=30)
    assert r.status_code == 200, r.text
    tmp = r.json().get("temp_token") or r.json().get("token")
    r = s.post(f"{API}/auth/login-password", json={"password": password},
               headers={"Authorization": f"Bearer {tmp}"}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    s.user = r.json().get("user") or {}
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def manager():
    return _login("9000000001", "Trata@123")


@pytest.fixture(scope="module")
def rohan():
    return _login("9000000002", "Trata@123")


def _zen():
    return q("SELECT city, pipeline_stage, kyc_status, verification_status, local_decision, assigned_agent_id, "
             "assigned_agent_name, ai_fields_applied_by, ai_fields_applied_at, address, state, pincode, latitude, longitude FROM public.path_lab_profiles WHERE user_id=$1", ZEN_USER, fetch="row")


def _poll(fn, ok, timeout=12):
    end = time.time() + timeout
    v = fn()
    while time.time() < end and not ok(v):
        time.sleep(1)
        v = fn()
    return v


@pytest.fixture(scope="module")
def legacy_before():
    return q("SELECT count(*) c, max(updated_at) m FROM public.crm_provider_leads", fetch="row")


@pytest.fixture(scope="module", autouse=True)
def restore_zenith(legacy_before):
    snap = _zen()
    yield
    time.sleep(6)  # let background canonical writes drain before restoring
    q("""UPDATE public.path_lab_profiles SET city=NULL, kyc_status='pending', local_decision=NULL,
         pipeline_stage=$2, verification_status=$3, assigned_agent_id=$4, assigned_agent_name=$5,
         ai_fields_applied_by=$6, ai_fields_applied_at=$7, address=$8, state=$9, pincode=$10, latitude=$11, longitude=$12
         WHERE user_id=$1""", ZEN_USER, snap["pipeline_stage"], snap["verification_status"],
      snap["assigned_agent_id"], snap["assigned_agent_name"], snap["ai_fields_applied_by"], snap["ai_fields_applied_at"],
      snap["address"], snap["state"], snap["pincode"], snap["latitude"], snap["longitude"], fetch="exec")
    q("UPDATE public.users SET verification_status='pending' WHERE id=$1", ZEN_USER, fetch="exec")
    from pymongo import MongoClient
    from dotenv import dotenv_values
    env = dotenv_values("/app/backend/.env")
    MongoClient(env["MONGO_URL"])[env["DB_NAME"]].contacts.update_one(
        {"id": ZEN_CONTACT}, {"$set": {"kyc_status": "pending", "pipeline_stage": "verified", "city": "Pune",
                                       "assigned_agent_id": ROHAN_ID, "assigned_agent_name": "Rohan Sales Rep"}})


# ── Read path ────────────────────────────────────────────────────────────────
class TestSupabaseContactsList:
    def test_admin_list_union(self, admin):
        r = admin.get(f"{API}/supabase/contacts", params={"limit": 500}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["source"] == "supabase" and isinstance(d["items"], list) and d["total"] > 0
        assert FIELDS <= set(d["items"][0].keys())
        types = {i["type"] for i in d["items"]}
        assert types <= TYPES
        # Phase D follow-up: 6 canonical tables (diagnostic_centre_profiles reported as type 'pathologist')
        expected = sum(q(f"SELECT count(*) FROM public.{t}", fetch="val") for t in
                       ["hospital_profiles", "path_lab_profiles", "doctors", "pharmacy_providers", "ambulance_providers",
                        "diagnostic_centre_profiles"])
        assert all("canonical_table" in i for i in d["items"])
        assert d["total"] == expected
        print("types", types, "total", d["total"])

    def test_manager_list(self, manager):
        r = manager.get(f"{API}/supabase/contacts", timeout=60)
        assert r.status_code == 200 and r.json()["total"] > 0

    @pytest.mark.parametrize("t", sorted(TYPES))
    def test_type_filter(self, admin, t):
        r = admin.get(f"{API}/supabase/contacts", params={"type": t}, timeout=60)
        assert r.status_code == 200
        assert all(i["type"] == t for i in r.json()["items"])

    def test_stage_and_q_filter(self, admin):
        r = admin.get(f"{API}/supabase/contacts", params={"stage": "verified"}, timeout=60)
        assert r.status_code == 200 and all(i["pipeline_stage"] == "verified" for i in r.json()["items"])
        r = admin.get(f"{API}/supabase/contacts", params={"q": "zenith"}, timeout=60)
        items = r.json()["items"]
        assert any(i["user_id"] == ZEN_USER for i in items)
        assert all("zenith" in (i["name"] or "").lower() or "zenith" in (i["phone"] or "") for i in items)
        r = admin.get(f"{API}/supabase/contacts", params={"q": "9000020005"}, timeout=60)
        assert any(i["user_id"] == ZEN_USER for i in r.json()["items"])

    def test_rep_scoped(self, rohan):
        r = rohan.get(f"{API}/supabase/contacts", timeout=60)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert all(i["assigned_agent_id"] == rohan.user.get("id", ROHAN_ID) for i in items)
        print("rohan sees", len(items))


class TestSupabaseContactDetail:
    def test_by_user_id_and_canonical_id(self, admin):
        r = admin.get(f"{API}/supabase/contacts/{ZEN_USER}", timeout=30)
        assert r.status_code == 200, r.text
        c = r.json()["contact"]
        assert c["user_id"] == ZEN_USER and c["type"] == "pathologist" and c["name"] == "Zenith Diagnostics"
        r2 = admin.get(f"{API}/supabase/contacts/{c['id']}", timeout=30)
        assert r2.status_code == 200 and r2.json()["contact"]["user_id"] == ZEN_USER

    def test_unknown_404(self, admin):
        r = admin.get(f"{API}/supabase/contacts/00000000-0000-0000-0000-000000000000", timeout=30)
        assert r.status_code == 404
        r = admin.get(f"{API}/supabase/contacts/not-a-uuid-TEST", timeout=30)
        assert r.status_code == 404, r.text


# ── Write path ───────────────────────────────────────────────────────────────
class TestCanonicalWrites:
    def test_patch_stage_city_syncs(self, admin):
        r = admin.patch(f"{API}/contacts/{ZEN_CONTACT}", json={"pipeline_stage": "contacted", "city": "TEST_City"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["contact"]["pipeline_stage"] == "contacted"
        row = _poll(_zen, lambda v: v["pipeline_stage"] == "contacted" and v["city"] == "TEST_City")
        assert row["pipeline_stage"] == "contacted" and row["city"] == "TEST_City", row
        # revert
        r = admin.patch(f"{API}/contacts/{ZEN_CONTACT}", json={"pipeline_stage": "verified", "city": "Pune"}, timeout=30)
        assert r.status_code == 200
        row = _poll(_zen, lambda v: v["pipeline_stage"] == "verified" and v["city"] == "Pune")
        assert row["pipeline_stage"] == "verified", row

    def test_assign_syncs(self, admin, manager):
        # only Rohan exists as an assignable sales_rep/manager → unassign then re-assign
        r = admin.patch(f"{API}/contacts/{ZEN_CONTACT}/assign", json={"agent_id": None}, timeout=30)
        assert r.status_code == 200, r.text
        row = _poll(_zen, lambda v: v["assigned_agent_id"] is None)
        assert row["assigned_agent_id"] is None and row["assigned_agent_name"] is None, row
        r = admin.patch(f"{API}/contacts/{ZEN_CONTACT}/assign", json={"agent_id": ROHAN_ID}, timeout=30)
        assert r.status_code == 200
        row = _poll(_zen, lambda v: v["assigned_agent_id"] == ROHAN_ID)
        assert row["assigned_agent_id"] == ROHAN_ID and row["assigned_agent_name"] == "Rohan Sales Rep"

    def test_kyc_final_pending_address(self, admin):
        q("UPDATE public.path_lab_profiles SET city=NULL WHERE user_id=$1", ZEN_USER, fetch="exec")
        r = admin.post(f"{API}/contacts/{ZEN_CONTACT}/kyc-admin-final", json={"decision": "verified", "notes": "TEST_phase_d"}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["verification_status"] == "pending_address", d
        assert d["contact"]["kyc_status"] == "pending_address"
        row = _zen()
        assert row["verification_status"] == "pending_address"
        assert row["local_decision"] and "pending_address" in str(row["local_decision"])
        assert q("SELECT verification_status FROM public.users WHERE id=$1", ZEN_USER, fetch="val") == "pending_address"

    def test_kyc_final_reject(self, admin):
        r = admin.post(f"{API}/contacts/{ZEN_CONTACT}/kyc-admin-final", json={"decision": "rejected", "notes": "TEST_reason"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["verification_status"] == "rejected"
        assert r.json()["contact"]["pipeline_stage"] == "rejected"
        time.sleep(3)
        row = _zen()
        assert row["verification_status"] == "rejected" and row["pipeline_stage"] == "rejected", row
        assert "TEST_reason" in str(row["local_decision"])
        assert q("SELECT verification_status FROM public.users WHERE id=$1", ZEN_USER, fetch="val") == "rejected"

    def test_kyc_final_verified_full_address(self, admin):
        q("""UPDATE public.path_lab_profiles SET address='TEST_addr', city='TEST_City', state='TEST_State', pincode='411001',
             latitude=18.5, longitude=73.8 WHERE user_id=$1""", ZEN_USER, fetch="exec")
        r = admin.post(f"{API}/contacts/{ZEN_CONTACT}/kyc-admin-final", json={"decision": "verified"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["verification_status"] == "verified"
        assert r.json()["contact"]["kyc_status"] == "verified"
        time.sleep(3)
        row = _zen()
        assert row["verification_status"] == "verified" and row["pipeline_stage"] == "verified", row
        assert row["ai_fields_applied_by"] and row["ai_fields_applied_at"]
        assert q("SELECT verification_status FROM public.users WHERE id=$1", ZEN_USER, fetch="val") == "verified"

    def test_kyc_final_bad_decision_and_rep_forbidden(self, admin, rohan):
        r = admin.post(f"{API}/contacts/{ZEN_CONTACT}/kyc-admin-final", json={"decision": "maybe"}, timeout=30)
        assert r.status_code == 400
        r = rohan.post(f"{API}/contacts/{ZEN_CONTACT}/kyc-admin-final", json={"decision": "verified"}, timeout=30)
        assert r.status_code == 403


class TestBackfill:
    def test_rep_forbidden(self, rohan):
        r = rohan.post(f"{API}/admin/canonical/backfill", timeout=30)
        assert r.status_code == 403

    def test_admin_started(self, admin):
        t = time.time()
        r = admin.post(f"{API}/admin/canonical/backfill", timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["started"] is True
        assert time.time() - t < 5


# ── Regression ───────────────────────────────────────────────────────────────
class TestRegression:
    def test_contacts_list_and_detail(self, admin):
        r = admin.get(f"{API}/contacts", timeout=60)
        assert r.status_code == 200, r.text
        r = admin.get(f"{API}/contacts/{ZEN_CONTACT}", timeout=30)
        assert r.status_code == 200 and r.json()["contact"]["id"] == ZEN_CONTACT

    def test_kyc_queue(self, admin):
        r = admin.get(f"{API}/admin/kyc-queue", timeout=30)
        assert r.status_code == 200 and "items" in r.json()

    def test_directory_providers(self, admin):
        r = admin.get(f"{API}/admin/directory/providers", timeout=60)
        assert r.status_code == 200, r.text[:300]


class TestZLegacyUntouched:
    def test_crm_provider_leads_untouched(self, legacy_before):
        time.sleep(8)
        now = q("SELECT count(*) c, max(updated_at) m FROM public.crm_provider_leads", fetch="row")
        assert now["c"] == 6 and now["c"] == legacy_before["c"]
        assert now["m"] == legacy_before["m"]
        assert str(now["m"]).startswith("2026-11-04 09:25:49")
