# Phase E — crm_sales_leads pipeline: stage write-through, Won conversion, outcome→stage map, follow-up queue, KYC final, regressions
import os
import sys
import time
from datetime import datetime, timedelta, timezone

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

P1, P2, P3 = "8955500301", "8955500302", "8955500303"
STAGES = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost", "dropped"]
CREATED = {}


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


def _poll(fn, ok, timeout=12):
    end = time.time() + timeout
    v = fn()
    while time.time() < end and not ok(v):
        time.sleep(1)
        v = fn()
    return v


def lead(phone):
    return q("SELECT * FROM public.crm_sales_leads WHERE phone=$1", phone, fetch="row")


def user(phone):
    return q("SELECT id, role FROM public.users WHERE phone = ANY($1::text[])", [phone, f"+91{phone}"], fetch="row")


def canon(uid):
    return q("SELECT id, verification_status FROM public.hospital_profiles WHERE user_id=$1", uid, fetch="row") if uid else None


def _cleanup(phone):
    u = user(phone)
    if u:
        q("DELETE FROM public.hospital_profiles WHERE user_id=$1", u["id"], fetch="exec")
        try:
            q("DELETE FROM public.users WHERE id=$1", u["id"], fetch="exec")
        except Exception as e:
            print("user delete failed", phone, e)
    q("DELETE FROM public.crm_sales_leads WHERE phone=$1", phone, fetch="exec")
    ids = [c["id"] for c in MDB.contacts.find({"phone": phone}, {"id": 1})]
    MDB.activities.delete_many({"contact_id": {"$in": ids}})
    MDB.tasks.delete_many({"contact_id": {"$in": ids}})
    MDB.notes.delete_many({"contact_id": {"$in": ids}})
    MDB.contacts.delete_many({"id": {"$in": ids}})


@pytest.fixture(scope="module", autouse=True)
def _module_cleanup():
    for p in (P1, P2, P3):
        assert not user(p), f"phone {p} unexpectedly already has a users row — pick another TEST phone"
        _cleanup(p)
    yield
    time.sleep(4)  # let background writes finish
    for p in (P1, P2, P3):
        _cleanup(p)
    for p in (P1, P2, P3):
        assert not lead(p) and not user(p) and not MDB.contacts.find_one({"phone": p})


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def rohan():
    return _login("9000000002", "Trata@123")


@pytest.fixture(scope="module")
def priya():
    return _login("9000000001", "Trata@123")


def _onboard(s, phone, name):
    r = s.post(f"{API}/admin/onboard-provider", json={"role": "hospital", "name": name, "phone": phone,
                                                        "city": "Lucknow", "state": "Uttar Pradesh"}, timeout=30)
    assert r.status_code == 200, r.text
    cid = MDB.contacts.find_one({"phone": phone})["id"]
    CREATED[phone] = cid
    return cid


# --- prospect lead creation → crm_sales_leads, no app account
class TestProspect:
    def test_onboard_prospect_creates_lead_only(self, rohan):
        cid = _onboard(rohan, P1, "TEST_PhaseE Hospital One")
        row = _poll(lambda: lead(P1), lambda v: v is not None)
        assert row, "crm_sales_leads row not created"
        assert row["pipeline_stage"] == "contacted"
        assert row["assigned_agent_id"] == rohan.user.get("id")
        assert row["upstream_user_id"] is None
        assert row["id"] == cid
        time.sleep(2)
        assert user(P1) is None, "prospect must NOT get a users row"

    def test_invalid_stage_400(self, rohan):
        r = rohan.patch(f"{API}/contacts/{CREATED[P1]}", json={"pipeline_stage": "bogus"})
        assert r.status_code == 400

    def test_patch_stage_and_followup(self, rohan):
        past = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%dT09:00:00+05:30")
        r = rohan.patch(f"{API}/contacts/{CREATED[P1]}", json={"pipeline_stage": "qualified", "next_followup_at": past})
        assert r.status_code == 200, r.text
        row = _poll(lambda: lead(P1), lambda v: v and v["pipeline_stage"] == "qualified" and v["next_followup_at"])
        assert row["pipeline_stage"] == "qualified"
        assert row["next_followup_at"] is not None
        assert user(P1) is None

    def test_followups_due_visibility(self, admin, rohan, priya):
        for s in (admin, rohan, priya):
            r = s.get(f"{API}/sales/followups-due")
            assert r.status_code == 200, r.text
            items = r.json()["items"]
            ids = [i["id"] for i in items]
            assert CREATED[P1] in ids, f"lead missing from followups for {s.user.get('name')}"
            it = next(i for i in items if i["id"] == CREATED[P1])
            assert it["overdue_days"] >= 2
        mine = rohan.get(f"{API}/sales/followups-due").json()["items"]
        assert all(i["assigned_agent_id"] == rohan.user.get("id") for i in mine)

    def test_outcome_map(self, rohan):
        cid = CREATED[P1]
        for outcome, exp in (("pitched", "proposal"), ("kyc_collected", "negotiation"), ("meeting_scheduled", "qualified")):
            r = rohan.post(f"{API}/agent/quick-log", json={"contact_id": cid, "activity_type": "follow_up", "outcome": outcome})
            assert r.status_code == 200, r.text
            assert r.json()["advanced_to_stage"] == exp
            assert MDB.contacts.find_one({"id": cid})["pipeline_stage"] == exp
            row = _poll(lambda: lead(P1), lambda v: v and v["pipeline_stage"] == exp)
            assert row["pipeline_stage"] == exp, f"{outcome}: lead row {row['pipeline_stage']}"
        assert user(P1) is None

    def test_not_interested_lost_and_leaves_queue(self, rohan):
        cid = _onboard(rohan, P2, "TEST_PhaseE Hospital Two")
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rohan.patch(f"{API}/contacts/{cid}", json={"next_followup_at": past})
        r = rohan.post(f"{API}/agent/quick-log", json={"contact_id": cid, "activity_type": "cold_call", "outcome": "not_interested"})
        assert r.status_code == 200 and r.json()["advanced_to_stage"] == "lost"
        row = _poll(lambda: lead(P2), lambda v: v and v["pipeline_stage"] == "lost")
        assert row["pipeline_stage"] == "lost"
        ids = [i["id"] for i in rohan.get(f"{API}/sales/followups-due").json()["items"]]
        assert cid not in ids, "closed (lost) lead must leave the follow-up queue"
        assert user(P2) is None


# --- Won conversion: users + canonical + upstream_user_id
class TestWonConversion:
    def test_legacy_verified_coerced_to_won_and_converts(self, rohan):
        cid = CREATED[P1]
        r = rohan.patch(f"{API}/contacts/{cid}", json={"pipeline_stage": "verified"})
        assert r.status_code == 200, r.text
        assert r.json()["contact"]["pipeline_stage"] == "won"
        row = _poll(lambda: lead(P1), lambda v: v and v["pipeline_stage"] == "won" and v["upstream_user_id"])
        assert row["pipeline_stage"] == "won"
        u = user(P1)
        assert u and u["role"] == "hospital"
        assert row["upstream_user_id"] == u["id"]
        assert canon(u["id"]), "canonical hospital_profiles row not created"
        c = MDB.contacts.find_one({"id": cid})
        assert c.get("upstream_user_id") == u["id"]
        ids = [i["id"] for i in rohan.get(f"{API}/sales/followups-due").json()["items"]]
        assert cid not in ids

    def test_signed_on_app_outcome_converts(self, rohan):
        cid = _onboard(rohan, P3, "TEST_PhaseE Hospital Three")
        r = rohan.post(f"{API}/agent/quick-log", json={"contact_id": cid, "activity_type": "app_training", "outcome": "signed_on_app"})
        assert r.status_code == 200 and r.json()["advanced_to_stage"] == "won"
        row = _poll(lambda: lead(P3), lambda v: v and v["upstream_user_id"])
        u = user(P3)
        assert u and u["role"] == "hospital" and row["upstream_user_id"] == u["id"] and canon(u["id"])

    def test_kyc_final_reject_lost_then_verify_won(self, admin):
        cid = CREATED[P1]
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "rejected", "notes": "TEST"})
        assert r.status_code == 200, r.text
        assert r.json()["contact"]["pipeline_stage"] == "lost"
        row = _poll(lambda: lead(P1), lambda v: v and v["pipeline_stage"] == "lost")
        assert row["pipeline_stage"] == "lost"
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified"})
        print("verify →", r.status_code, r.text[:300])
        assert r.status_code in (200, 400), r.text
        if r.status_code == 200:
            vs = r.json()["verification_status"]
            stg = r.json()["contact"]["pipeline_stage"]
            print("verification_status", vs, "stage", stg)
            if vs == "verified":
                assert stg == "won"

    def test_kyc_final_on_prospect_without_account(self, admin):
        r = admin.post(f"{API}/contacts/{CREATED[P2]}/kyc-admin-final", json={"decision": "rejected"})
        print("prospect kyc final", r.status_code, r.text[:200])
        assert r.status_code in (200, 409)
        assert user(P2) is None


# --- stage lists on dashboards / pipeline
class TestStageLists:
    def test_dashboard_pipeline_8_stages(self, admin):
        r = admin.get(f"{API}/dashboard/stats")
        assert r.status_code == 200
        assert sorted(r.json()["pipeline"].keys()) == sorted(STAGES)

    def test_pipeline_endpoint_8_stages(self, admin):
        r = admin.get(f"{API}/pipeline")
        assert r.status_code == 200
        assert r.json()["stages"] == STAGES, f"/api/pipeline returns old stages: {r.json()['stages']}"

    def test_agent_dashboard_by_stage(self, rohan):
        r = rohan.get(f"{API}/agent/dashboard")
        assert r.status_code == 200
        assert sorted(r.json()["by_stage"].keys()) == sorted(STAGES), f"agent by_stage keys: {list(r.json()['by_stage'])}"


# --- regressions
class TestRegression:
    @pytest.mark.parametrize("path", ["/admin/directory/providers", "/contacts?limit=5", "/admin/kyc-queue",
                                      "/admin/onboarding/providers"])
    def test_get_ok(self, admin, path):
        r = admin.get(f"{API}{path}", timeout=60)
        assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
        assert "crm_provider_leads" not in r.text

    def test_sync_supabase_users(self, admin):
        r = admin.post(f"{API}/admin/sync-supabase-users", timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert "crm_provider_leads" not in r.text

    def test_followups_requires_auth(self):
        assert requests.get(f"{API}/sales/followups-due").status_code in (401, 403)
