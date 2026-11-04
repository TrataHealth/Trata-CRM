# Phase D follow-up — 6 canonical tables, verification_status everywhere, nurse/paramedic user-only,
# idempotent ON CONFLICT inserts, diagnostic_centre_profiles routing, outbound webhooks retired.
# All data is TEST_ prefixed with fresh 8999xxxxxx phones and removed in the module teardown.
import asyncio
import os
import random
import sys
import time
import uuid

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, "/app/backend")
from pg_helper import q  # noqa: E402

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    for line in open("/app/frontend/.env"):
        if line.startswith("REACT_APP_BACKEND_URL="):
            BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
API = f"{BASE_URL}/api"
ENV = dotenv_values("/app/backend/.env")
MDB = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]
RUN = f"{random.randint(100000, 999999)}"
TABLE = {"hospital": "hospital_profiles", "pathologist": "path_lab_profiles", "doctor": "doctors",
         "pharmacy": "pharmacy_providers", "ambulance_provider": "ambulance_providers",
         "diagnostic_centre": "diagnostic_centre_profiles"}
ALL_TABLES = list(TABLE.values())
API_ROLES = ["doctor", "hospital", "paramedic", "ambulance_provider", "pharmacy", "pathologist"]
STATE = {"contacts": {}, "users": set(), "outbound_before": None}

_loop = asyncio.new_event_loop()


def run(coro):
    return _loop.run_until_complete(coro)


def _phone(i):
    return f"89{RUN}{i:02d}"  # 10 digits, TEST-only range


def _login(phone, password):
    s = requests.Session()
    r = s.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=30)
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=30)
    tmp = r.json().get("temp_token") or r.json().get("token")
    r = s.post(f"{API}/auth/login-password", json={"password": password},
               headers={"Authorization": f"Bearer {tmp}"}, timeout=30)
    assert r.status_code == 200, r.text
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}"})
    return s


def _poll(fn, ok, timeout=15):
    end = time.time() + timeout
    v = fn()
    while time.time() < end and not ok(v):
        time.sleep(1)
        v = fn()
    return v


def _user_by_phone(p):
    return q("SELECT id, role, verification_status FROM public.users WHERE phone = ANY($1::text[])", [p, f"+91{p}"])


def _canon(table, uid):
    return q(f"SELECT * FROM public.{table} WHERE user_id=$1", uid)


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    STATE["outbound_before"] = MDB.admin_bridge_outbound.count_documents({})
    yield
    time.sleep(6)  # drain background canonical writes
    for cid, info in STATE["contacts"].items():
        c = MDB.contacts.find_one({"id": cid}) or {}
        for k in ("supabase_user_id", "upstream_user_id"):
            if c.get(k):
                STATE["users"].add(c[k])
        STATE["users"].update(u["id"] for u in _user_by_phone(info["phone"]))
    for uid in STATE["users"]:
        q("DELETE FROM public.kyc_documents WHERE user_id=$1", uid, fetch="exec")
        for t in ALL_TABLES:
            q(f"DELETE FROM public.{t} WHERE user_id=$1", uid, fetch="exec")
        try:
            q("DELETE FROM public.users WHERE id=$1", uid, fetch="exec")
        except Exception as e:  # noqa
            print("user delete failed", uid, e)
    for cid in STATE["contacts"]:
        MDB.contacts.delete_one({"id": cid})
        MDB.activities.delete_many({"contact_id": cid})
    print("cleanup users", len(STATE["users"]), "contacts", len(STATE["contacts"]))


# ── New lead inserts ────────────────────────────────────────────────────────
class TestNewLeadInsert:
    @pytest.mark.parametrize("i,role", list(enumerate(API_ROLES)))
    def test_onboard_creates_user_and_canonical(self, admin, i, role):
        phone = _phone(i)
        r = admin.post(f"{API}/admin/onboard-provider", json={"role": role, "name": f"TEST_{role}_{RUN}",
                                                             "phone": phone, "city": "TEST_City"}, timeout=30)
        assert r.status_code == 200, r.text
        cid = r.json()["contact"]["id"]
        STATE["contacts"][cid] = {"phone": phone, "type": role}
        users = _poll(lambda: _user_by_phone(phone), lambda v: len(v) == 1)
        assert len(users) == 1, users
        u = users[0]
        assert u["role"] == role and u["verification_status"] == "pending"
        STATE["users"].add(u["id"])
        STATE["contacts"][cid]["uid"] = u["id"]
        mc = _poll(lambda: MDB.contacts.find_one({"id": cid}), lambda v: v.get("supabase_user_id") == u["id"])
        assert mc.get("supabase_user_id") == u["id"]
        if role in TABLE:
            rows = _poll(lambda: _canon(TABLE[role], u["id"]), lambda v: len(v) == 1)
            assert len(rows) == 1 and rows[0]["verification_status"] == "pending", rows
            # never lands on another table
            for t in ALL_TABLES:
                if t != TABLE[role]:
                    assert not _canon(t, u["id"]), t
        else:
            for t in ALL_TABLES:
                assert not _canon(t, u["id"]), f"{role} must be users-only, found in {t}"

    @pytest.mark.parametrize("i,role", [(10, "nurse"), (11, "diagnostic_centre")])
    def test_console_onboard_nurse_and_diag(self, admin, i, role):
        """Console add of nurse / diagnostic_centre leads (user choice: create user accounts for nurse)."""
        phone = _phone(i)
        r = admin.post(f"{API}/admin/onboard-provider", json={"role": role, "name": f"TEST_{role}_{RUN}",
                                                             "phone": phone, "city": "TEST_City"}, timeout=30)
        if r.status_code == 200:
            STATE["contacts"][r.json()["contact"]["id"]] = {"phone": phone, "type": role}
        assert r.status_code == 200, f"/admin/onboard-provider rejects role={role}: {r.status_code} {r.text[:200]}"

    @pytest.mark.parametrize("i,role", [(20, "nurse"), (21, "diagnostic_centre")])
    def test_sync_contact_inprocess(self, i, role):
        """Direct cp.sync_contact for types the console API may not accept."""
        import canonical_providers as cp
        phone = _phone(i)
        cid = str(uuid.uuid4())
        doc = {"id": cid, "name": f"TEST_{role}_{RUN}", "type": role, "phone": phone, "city": "TEST_City",
               "pipeline_stage": "contacted", "kyc_status": "pending", "is_active": False}
        MDB.contacts.insert_one(dict(doc))
        STATE["contacts"][cid] = {"phone": phone, "type": role}
        res = run(cp.sync_contact(doc, None, create=True))
        assert res.get("success"), res
        u = _user_by_phone(phone)
        assert len(u) == 1 and u[0]["role"] == role and u[0]["verification_status"] == "pending", u
        STATE["users"].add(u[0]["id"])
        STATE["contacts"][cid]["uid"] = u[0]["id"]
        MDB.contacts.update_one({"id": cid}, {"$set": {"supabase_user_id": u[0]["id"]}})
        if role in TABLE:
            rows = _canon(TABLE[role], u[0]["id"])
            assert len(rows) == 1 and rows[0]["verification_status"] == "pending"
        else:
            assert all(not _canon(t, u[0]["id"]) for t in ALL_TABLES)


class TestIdempotent:
    def test_second_sync_no_duplicates(self):
        import canonical_providers as cp
        assert STATE["contacts"]
        for cid, info in STATE["contacts"].items():
            c = MDB.contacts.find_one({"id": cid}, {"_id": 0})
            if not c or not info.get("uid"):
                continue
            stripped = {k: v for k, v in c.items() if k not in ("supabase_user_id", "upstream_user_id")}
            for doc in (c, stripped):  # by user id, then by phone (reuses users row, ON CONFLICT path)
                res = run(cp.sync_contact(doc, None, create=True))
                assert res.get("success") and res.get("user_id") == info["uid"], (info, res)
            assert len(_user_by_phone(info["phone"])) == 1
            if info["type"] in TABLE:
                assert len(_canon(TABLE[info["type"]], info["uid"])) == 1


# ── set_verification across tables ───────────────────────────────────────────
def _cid_of(role):
    for cid, info in STATE["contacts"].items():
        if info["type"] == role and info.get("uid"):
            return cid, info
    pytest.skip(f"no {role} test contact")


class TestSetVerification:
    @pytest.mark.parametrize("role", ["doctor", "ambulance_provider", "hospital", "pharmacy"])
    def test_verified_then_rejected(self, admin, role):
        cid, info = _cid_of(role)
        t = TABLE[role]
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified", "notes": "TEST_ok"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["verification_status"] == "verified"
        row = _canon(t, info["uid"])[0]
        assert row["verification_status"] == "verified" and row["pipeline_stage"] == "verified", (t, row["verification_status"], row["pipeline_stage"])
        assert "TEST_ok" in str(row["local_decision"])
        assert q("SELECT verification_status FROM public.users WHERE id=$1", info["uid"], fetch="val") == "verified"
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "rejected", "notes": "TEST_reason"}, timeout=30)
        assert r.status_code == 200, r.text
        row = _canon(t, info["uid"])[0]
        assert row["verification_status"] == "rejected" and row["pipeline_stage"] == "rejected"
        assert "TEST_reason" in str(row["local_decision"])
        assert q("SELECT verification_status FROM public.users WHERE id=$1", info["uid"], fetch="val") == "rejected"
        assert r.json()["contact"]["pipeline_stage"] == "rejected"

    @pytest.mark.parametrize("role", ["pathologist", "diagnostic_centre"])
    def test_incomplete_address_pending_address(self, admin, role):
        cid, info = _cid_of(role)
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified", "notes": "TEST_pa"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["verification_status"] == "pending_address"
        row = _canon(TABLE[role], info["uid"])[0]
        assert row["verification_status"] == "pending_address"
        if "local_decision" in row:
            assert "pending_address" in str(row["local_decision"])
        assert q("SELECT verification_status FROM public.users WHERE id=$1", info["uid"], fetch="val") == "pending_address"

    @pytest.mark.parametrize("role", ["paramedic", "nurse"])
    def test_user_only_verification(self, admin, role):
        cid, info = _cid_of(role)
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified"}, timeout=30)
        assert r.status_code == 200, r.text
        assert q("SELECT verification_status FROM public.users WHERE id=$1", info["uid"], fetch="val") == "verified"
        assert all(not _canon(t, info["uid"]) for t in ALL_TABLES)


# ── Pathologist whose account lives only in diagnostic_centre_profiles ─────
class TestPathologistInDiag:
    def test_syncs_to_diag_not_new_path_lab(self, admin):
        phone = _phone(30)
        uid = str(uuid.uuid4())
        q("""INSERT INTO public.users (id, phone, name, role, is_active, verification_status, created_at, updated_at)
             VALUES ($1,$2,$3,'pathologist',TRUE,'pending',now(),now())""", uid, phone, f"TEST_diagpath_{RUN}", fetch="exec")
        STATE["users"].add(uid)
        q("""INSERT INTO public.diagnostic_centre_profiles (id, user_id, name, phone, verification_status, created_at, updated_at)
             VALUES ($1,$2,$3,$4,'pending',now(),now())""", str(uuid.uuid4()), uid, f"TEST_diagpath_{RUN}", phone, fetch="exec")
        cid = str(uuid.uuid4())
        MDB.contacts.insert_one({"id": cid, "name": f"TEST_diagpath_{RUN}", "type": "pathologist", "phone": phone,
                                 "supabase_user_id": uid, "pipeline_stage": "lead", "kyc_status": "pending",
                                 "created_at": "2026-01-01T00:00:00Z"})
        STATE["contacts"][cid] = {"phone": phone, "type": "pathologist_diag", "uid": uid}
        r = admin.patch(f"{API}/contacts/{cid}", json={"city": "TEST_DiagCity", "pipeline_stage": "contacted"}, timeout=30)
        assert r.status_code == 200, r.text
        row = _poll(lambda: _canon("diagnostic_centre_profiles", uid), lambda v: v and v[0]["city"] == "TEST_DiagCity")
        assert row and row[0]["city"] == "TEST_DiagCity", row
        time.sleep(2)
        assert not _canon("path_lab_profiles", uid), "a new path_lab_profiles row was created"
        # verification goes to diag table (incomplete address → pending_address)
        r = admin.post(f"{API}/contacts/{cid}/kyc-admin-final", json={"decision": "verified"}, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["verification_status"] == "pending_address"
        assert _canon("diagnostic_centre_profiles", uid)[0]["verification_status"] == "pending_address"
        assert not _canon("path_lab_profiles", uid)
        # union reports it as type pathologist from diagnostic_centre_profiles
        r = admin.get(f"{API}/supabase/contacts", params={"q": f"TEST_diagpath_{RUN}".lower()}, timeout=60)
        items = [i for i in r.json()["items"] if i["user_id"] == uid]
        assert len(items) == 1 and items[0]["type"] == "pathologist" and items[0]["canonical_table"] == "diagnostic_centre_profiles", items


# ── Approve-all on doctor / ambulance ─────────────────────────────────────
DOCS = {"doctor": ("doctor", ["pan_card", "address_proof", "signatory_photo", "authorized_signatory_id", "medical_council_reg", "degree_certificate"]),
        "ambulance_provider": ("ambulance", ["pan_card", "address_proof", "signatory_photo", "authorized_signatory_id", "vehicle_rc",
                                             "vehicle_permit", "driver_license", "puc_certificate", "insurance_certificate"])}


class TestApproveAll:
    @pytest.mark.parametrize("role", ["doctor", "ambulance_provider"])
    def test_approve_all_sets_verified(self, admin, role):
        cid, info = _cid_of(role)
        t = TABLE[role]
        time.sleep(2)
        q(f"UPDATE public.{t} SET verification_status='pending' WHERE user_id=$1", info["uid"], fetch="exec")
        pt, keys = DOCS[role]
        for k in keys:
            q("""INSERT INTO public.kyc_documents (id, user_id, provider_type, document_name, document_type, status, submitted_at, created_at, updated_at)
                 VALUES ($1,$2,$3,$4,$4,'submitted',now(),now(),now())""", str(uuid.uuid4()), info["uid"], pt, k, fetch="exec")
        r = admin.post(f"{API}/admin/onboarding/providers/{info['uid']}/approve-all", json={"lat": 18.52, "lng": 73.85}, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json().get("verification_status") == "verified", r.json()
        row = _canon(t, info["uid"])[0]
        assert row["verification_status"] == "verified", row["verification_status"]
        assert q("SELECT verification_status FROM public.users WHERE id=$1", info["uid"], fetch="val") == "verified"
        print(role, "is_active", row.get("is_active"), "status", row.get("status"), "is_verified", row.get("is_verified"))


# ── Outbound retired ─────────────────────────────────────────────────────
class TestOutboundRetired:
    def test_test_send(self, admin):
        r = admin.post(f"{API}/admin/bridge/test-send", json={"event": "crm.lead.assigned", "data": {"phone": "TEST"}}, timeout=30)
        assert r.status_code == 200, r.text
        qd = r.json()["queued"]
        assert qd["queued"] is False and qd["reason"] == "outbound_retired"

    def test_assign_no_outbound(self, admin):
        cid, _ = _cid_of("hospital")
        r = admin.patch(f"{API}/contacts/{cid}/assign", json={"agent_id": None}, timeout=30)
        assert r.status_code == 200, r.text
        time.sleep(2)
        assert MDB.admin_bridge_outbound.count_documents({}) == STATE["outbound_before"]

    def test_zz_no_outbound_rows_whole_run(self):
        assert MDB.admin_bridge_outbound.count_documents({}) == STATE["outbound_before"]


# ── Union ───────────────────────────────────────────────────────────────
class TestUnion:
    def test_six_table_union(self, admin):
        r = admin.get(f"{API}/supabase/contacts", params={"limit": 1000}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        expected = sum(q(f"SELECT count(*) FROM public.{t}", fetch="val") for t in ALL_TABLES)
        assert d["total"] == expected, (d["total"], expected)
        assert all("canonical_table" in i for i in d["items"])
        assert {i["canonical_table"] for i in d["items"]} <= set(ALL_TABLES)
        diag = [i for i in d["items"] if i["canonical_table"] == "diagnostic_centre_profiles"]
        assert diag and all(i["type"] == "pathologist" for i in diag)
        r = admin.get(f"{API}/supabase/contacts", params={"type": "pathologist", "limit": 1000}, timeout=60)
        assert any(i["canonical_table"] == "diagnostic_centre_profiles" for i in r.json()["items"])
