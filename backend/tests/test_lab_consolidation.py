# Labs consolidation (Path Lab / Diagnostic Centre) — legacy-table regressions, onboarding, smoke §8, lab_staff API
import os
import sys
import time

import pytest
import requests
from pymongo import MongoClient
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from pg_helper import q  # noqa: E402

load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"
MDB = MongoClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

PL_PHONE, DC_PHONE = "8955500201", "8955500202"
CITY_XRAY = "5acb0629-7428-4901-a913-0215648955cb"
NEW_SS = "a44545ac-6cc6-5f39-b86c-9d3a66e134a8"
ROHAN_ID = "7044b30e-5995-4bc5-a606-4f230a3f5d10"


def _login(phone, password):
    s = requests.Session()
    assert s.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=30).status_code == 200
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=30)
    assert r.status_code == 200, r.text
    tmp = r.json().get("temp_token") or r.json().get("token")
    r = s.post(f"{API}/auth/login-password", json={"password": password},
               headers={"Authorization": f"Bearer {tmp}"}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    s.user = r.json().get("user") or {}
    return s


def _poll(fn, ok, timeout=10):
    end = time.time() + timeout
    v = fn()
    while time.time() < end and not ok(v):
        time.sleep(1)
        v = fn()
    return v


def _cleanup(uid, phone):
    if not uid:
        return
    for tbl, btbl, fk in (("path_lab_profiles", "path_lab_branches", "path_lab_profile_id"),
                          ("diagnostic_centre_profiles", "diagnostic_centre_branches", "diagnostic_centre_profile_id")):
        pid = q(f"SELECT id FROM public.{tbl} WHERE user_id=$1", uid, fetch="val")
        if pid:
            q("DELETE FROM public.lab_staff WHERE lab_id=$1", pid, fetch="exec")
            q(f"DELETE FROM public.{btbl} WHERE {fk}=$1", pid, fetch="exec")
            q(f"DELETE FROM public.{tbl} WHERE id=$1", pid, fetch="exec")
    try:
        q("DELETE FROM public.users WHERE id=$1", uid, fetch="exec")
    except Exception as e:  # FK from other tables
        print("user delete failed", e)
    ids = [c["id"] for c in MDB.contacts.find({"$or": [{"phone": phone}, {"supabase_user_id": uid}]}, {"id": 1})]
    MDB.activities.delete_many({"contact_id": {"$in": ids}})
    MDB.contacts.delete_many({"id": {"$in": ids}})
    MDB.crm_users.delete_many({"phone": phone})


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def rohan():
    return _login("9000000002", "Trata@123")


@pytest.fixture(scope="module")
def labs(admin):
    out = {}
    for kind, phone, addr in (("path_lab", PL_PHONE, None), ("diagnostic_centre", DC_PHONE, "TEST addr, Sector 1")):
        r = admin.post(f"{API}/admin/onboarding/providers", json={
            "phone": phone, "name": f"TEST_{kind}_lab", "vertical": "pathology", "lab_kind": kind,
            "city": "Gurugram", "state": "Haryana", "address": addr, "lat": 28.45, "lng": 77.02}, timeout=60)
        out[kind] = {"resp": r, "phone": phone, "uid": (r.json() if r.status_code == 200 else {}).get("user_id")}
    yield out
    time.sleep(6)
    for v in out.values():
        _cleanup(v["uid"], v["phone"])


# ── legacy tables gone → no 500s ─────────────────────────────────────────────
class TestNoLegacy500:
    def test_sync_supabase_users(self, admin):
        r = admin.post(f"{API}/admin/sync-supabase-users", timeout=120)
        assert r.status_code == 200, r.text[:300]

    def test_contacts_list(self, admin):
        r = admin.get(f"{API}/contacts", params={"limit": 50}, timeout=60)
        assert r.status_code == 200, r.text[:300]

    def test_mongo_contacts_no_pathologist(self):
        assert MDB.contacts.count_documents({"type": "pathologist"}) == 0

    def test_supabase_contacts_types(self, admin):
        r = admin.get(f"{API}/supabase/contacts", params={"limit": 500}, timeout=90)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        items = d.get("items") or d.get("contacts") or (d if isinstance(d, list) else [])
        types = {i.get("type") for i in items}
        print("supabase types", types)
        assert "pathologist" not in types

    def test_supabase_contacts_lab_filter(self, admin):
        for t in ("path_lab", "diagnostic_centre"):
            r = admin.get(f"{API}/supabase/contacts", params={"type": t, "limit": 50}, timeout=90)
            assert r.status_code == 200, r.text[:300]

    def test_ledger_pages(self, admin):
        r = admin.get(f"{API}/ledger/providers", timeout=90)
        assert r.status_code == 200, r.text[:300]
        for uid in (CITY_XRAY, NEW_SS):
            r = admin.get(f"{API}/ledger/providers/{uid}", timeout=60)
            assert r.status_code in (200, 404), r.text[:300]

    @pytest.mark.parametrize("uid,kind", [(CITY_XRAY, "diagnostic_centre"), (NEW_SS, "diagnostic_centre")])
    def test_kyc_profile_real(self, admin, uid, kind):
        r = admin.get(f"{API}/admin/onboarding/providers/{uid}/kyc", timeout=60)
        assert r.status_code == 200, r.text[:300]
        print(uid, str(r.json())[:300])

    def test_kyc_profile_real_path_lab(self, admin):
        uid = q("SELECT user_id FROM public.path_lab_profiles WHERE user_id IS NOT NULL AND user_id NOT IN "
                "(SELECT user_id FROM public.diagnostic_centre_profiles WHERE user_id IS NOT NULL) LIMIT 1", fetch="val")
        r = admin.get(f"{API}/admin/onboarding/providers/{uid}/kyc", timeout=60)
        assert r.status_code == 200, r.text[:300]


# ── onboarding + smoke §8 + lab staff ────────────────────────────────────────
class TestLabFlows:
    @pytest.mark.parametrize("kind,tbl", [("path_lab", "path_lab_profiles"), ("diagnostic_centre", "diagnostic_centre_profiles")])
    def test_onboard(self, labs, kind, tbl):
        r = labs[kind]["resp"]
        assert r.status_code == 200, r.text[:300]
        uid = labs[kind]["uid"]
        assert q("SELECT role FROM public.users WHERE id=$1", uid, fetch="val") == kind
        assert q(f"SELECT count(*) FROM public.{tbl} WHERE user_id=$1", uid, fetch="val") == 1
        c = MDB.contacts.find_one({"phone": labs[kind]["phone"]})
        assert c and c["type"] == kind
        assert MDB.crm_users.find_one({"phone": labs[kind]["phone"]})

    def test_onboard_bad_lab_kind(self, admin):
        r = admin.post(f"{API}/admin/onboarding/providers", json={
            "phone": "8955500299", "name": "TEST_x", "vertical": "pathology", "lab_kind": "pathologist",
            "lat": 28.4, "lng": 77.0}, timeout=30)
        assert r.status_code == 400

    @pytest.mark.parametrize("kind,tbl", [("path_lab", "path_lab_profiles"), ("diagnostic_centre", "diagnostic_centre_profiles")])
    def test_pipeline_assign_land_on_canonical(self, admin, labs, kind, tbl):
        uid = labs[kind]["uid"]
        cid = MDB.contacts.find_one({"phone": labs[kind]["phone"]})["id"]
        r = admin.patch(f"{API}/contacts/{cid}", json={"pipeline_stage": "qualified"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        v = _poll(lambda: q(f"SELECT pipeline_stage FROM public.{tbl} WHERE user_id=$1", uid, fetch="val"), lambda x: x == "qualified")
        assert v == "qualified"
        r = admin.patch(f"{API}/contacts/{cid}/assign", json={"agent_id": ROHAN_ID}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        v = _poll(lambda: q(f"SELECT assigned_agent_id FROM public.{tbl} WHERE user_id=$1", uid, fetch="val"), lambda x: x == ROHAN_ID)
        assert v == ROHAN_ID

    def test_verify_path_lab_incomplete_address(self, admin, labs):
        uid = labs["path_lab"]["uid"]
        cid = MDB.contacts.find_one({"phone": PL_PHONE})["id"]
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified", "notes": "TEST"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        v = _poll(lambda: q("SELECT verification_status FROM public.path_lab_profiles WHERE user_id=$1", uid, fetch="val"),
                  lambda x: x == "pending_address", 8)
        assert v == "pending_address"

    def test_verify_then_reject_dc(self, admin, labs):
        uid = labs["diagnostic_centre"]["uid"]
        q("UPDATE public.diagnostic_centre_profiles SET pincode='122001' WHERE user_id=$1", uid, fetch="exec")
        cid = MDB.contacts.find_one({"phone": DC_PHONE})["id"]
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified"}, timeout=30)
        print("verify dc", r.status_code, r.text[:200])
        assert r.status_code == 200
        v = _poll(lambda: q("SELECT verification_status FROM public.diagnostic_centre_profiles WHERE user_id=$1", uid, fetch="val"),
                  lambda x: x == "verified", 8)
        assert v == "verified"
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "rejected", "notes": "TEST"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        v = _poll(lambda: q("SELECT verification_status FROM public.diagnostic_centre_profiles WHERE user_id=$1", uid, fetch="val"),
                  lambda x: x == "rejected", 8)
        assert v == "rejected"

    def test_kyc_profile_new_labs(self, admin, labs):
        for kind in ("path_lab", "diagnostic_centre"):
            r = admin.get(f"{API}/admin/onboarding/providers/{labs[kind]['uid']}/kyc", timeout=60)
            assert r.status_code == 200, r.text[:300]

    def test_staff_crud_path_lab(self, admin, labs):
        uid = labs["path_lab"]["uid"]
        r = admin.get(f"{API}/admin/labs/{uid}/staff", timeout=30)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["lab"]["entity_type"] == "path_lab" and "radiologist" not in d["roles"]
        r = admin.post(f"{API}/admin/labs/{uid}/staff", json={"name": "TEST_Rad", "role": "radiologist"}, timeout=30)
        assert r.status_code == 400
        r = admin.post(f"{API}/admin/labs/{uid}/staff", json={"name": "TEST_Tech", "role": "lab_technician", "phone": "9999999999"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        items = r.json()["items"]
        assert len(items) == 1 and items[0]["name"] == "TEST_Tech"
        sid = items[0]["id"]
        pid = r.json()["lab"]["id"]
        # canonical id also works
        assert admin.get(f"{API}/admin/labs/{pid}/staff", timeout=30).json()["counts"]["total"] == 1
        r = admin.put(f"{API}/admin/labs/{uid}/staff/{sid}", json={"name": "TEST_Tech2", "role": "pathologist"}, timeout=30)
        assert r.status_code == 200 and r.json()["items"][0]["name"] == "TEST_Tech2" and r.json()["items"][0]["role"] == "pathologist"
        r = admin.put(f"{API}/admin/labs/{uid}/staff/{sid}", json={"name": "TEST_Tech2", "role": "radiologist"}, timeout=30)
        assert r.status_code == 400
        r = admin.post(f"{API}/admin/labs/{uid}/staff/toggle-duty/{sid}", timeout=30)
        assert r.status_code == 200 and r.json()["counts"]["on_duty"] == 1
        assert q("SELECT is_on_duty FROM public.lab_staff WHERE id=$1", sid, fetch="val") is True
        r = admin.delete(f"{API}/admin/labs/{uid}/staff/{sid}", timeout=30)
        assert r.status_code == 200 and r.json()["counts"]["total"] == 0
        assert admin.delete(f"{API}/admin/labs/{uid}/staff/{sid}", timeout=30).status_code == 404

    def test_staff_dc_radiologist(self, admin, labs):
        uid = labs["diagnostic_centre"]["uid"]
        r = admin.post(f"{API}/admin/labs/{uid}/staff", json={"name": "TEST_Rad", "role": "radiologist"}, timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["lab"]["entity_type"] == "diagnostic_centre"
        assert r.json()["items"][0]["role"] == "radiologist"

    def test_staff_invalid_inputs(self, admin, labs):
        uid = labs["diagnostic_centre"]["uid"]
        assert admin.post(f"{API}/admin/labs/{uid}/staff", json={"name": "", "role": "admin"}, timeout=30).status_code == 422
        assert admin.post(f"{API}/admin/labs/{uid}/staff", json={"name": "TEST_x", "role": "chef"}, timeout=30).status_code == 400

    def test_staff_rbac_and_404(self, admin, rohan, labs):
        uid = labs["path_lab"]["uid"]
        assert rohan.get(f"{API}/admin/labs/{uid}/staff", timeout=30).status_code == 403
        assert rohan.post(f"{API}/admin/labs/{uid}/staff", json={"name": "TEST_x", "role": "admin"}, timeout=30).status_code == 403
        assert admin.get(f"{API}/admin/labs/{ROHAN_ID}/staff", timeout=30).status_code == 404

    def test_staff_read_real_dc_wins(self, admin):
        r = admin.get(f"{API}/admin/labs/{NEW_SS}/staff", timeout=30)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["lab"]["entity_type"] == "diagnostic_centre"

    def test_service_types(self, admin, labs):
        r = admin.get(f"{API}/admin/directory/providers/{labs['path_lab']['uid']}/service-types", timeout=30)
        print("svc path_lab", r.status_code, r.text[:200])
        dc = labs["diagnostic_centre"]["uid"]
        r = admin.get(f"{API}/admin/directory/providers/{dc}/service-types", timeout=30)
        print("svc dc", r.status_code, r.text[:200])
        assert r.status_code == 200 and r.json()["applicable"] is True
        r = admin.put(f"{API}/admin/directory/providers/{dc}/service-types", json={"service_types": ["imaging", "pathology", "bogus"]}, timeout=30)
        assert r.status_code == 200 and r.json()["service_types"] == ["imaging", "pathology"]
        assert sorted(q("SELECT service_types FROM public.diagnostic_centre_profiles WHERE user_id=$1", dc, fetch="val")) == ["imaging", "pathology"]
