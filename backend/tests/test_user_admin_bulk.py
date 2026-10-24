"""Master-admin bulk user actions (suspend/unsuspend/archive/restore) + erase cron.
Only acts on TEST_probe ledger hospitals (run `python ledger_probe_fixtures.py setup` first).
"""
import asyncio
import json
import sys

import asyncpg
import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import BASE_URL, DSN, ENV  # noqa: E402
from server_admin_login import admin_token  # noqa: E402

API = f"{BASE_URL}/api"
S = json.load(open("/tmp/ledger_probe_state.json"))
mdb = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def sb_row(uid):
    async def f():
        c = await asyncpg.connect(DSN, statement_cache_size=0)
        try:
            return dict(await c.fetchrow("SELECT is_suspended, suspended_reason, suspended_by, is_archived, is_active, archived_reason, purge_after FROM public.users WHERE id=$1", uid))
        finally:
            await c.close()
    return asyncio.run(f())


@pytest.fixture(scope="module")
def adm():
    return S["tok_admin"]


@pytest.fixture(scope="module")
def cid_a():
    c = mdb.contacts.find_one({"supabase_user_id": S["uid_a"]}, {"_id": 0, "id": 1})
    assert c, "probe A contact missing"
    return c["id"]


@pytest.fixture(scope="module")
def cid_b():
    c = mdb.contacts.find_one({"supabase_user_id": S["uid_b"]}, {"_id": 0, "id": 1})
    assert c
    return c["id"]


@pytest.fixture(scope="module", autouse=True)
def restore_all(cid_a, cid_b):
    yield
    for act in ("restore", "unsuspend"):
        requests.post(f"{API}/admin/users/bulk", headers=H(S["tok_admin"]), json={"contact_ids": [cid_a, cid_b], "action": act}, timeout=60)


def bulk(tok, ids, action, reason=None):
    return requests.post(f"{API}/admin/users/bulk", headers=H(tok), json={"contact_ids": ids, "action": action, "reason": reason}, timeout=60)


# --- RBAC / validation
class TestValidation:
    def test_provider_forbidden(self, cid_b):
        r = bulk(S["tok_a"], [cid_b], "suspend", "TEST_probe reason")
        assert r.status_code == 403

    def test_sales_rep_forbidden(self, cid_b):
        tok = admin_token("9000000002", "Trata@123")
        assert bulk(tok, [cid_b], "suspend", "TEST_probe reason").status_code == 403

    def test_reason_required_suspend(self, adm, cid_a):
        assert bulk(adm, [cid_a], "suspend", "abc").status_code == 400
        assert bulk(adm, [cid_a], "suspend", None).status_code == 400

    def test_reason_required_archive(self, adm, cid_a):
        assert bulk(adm, [cid_a], "archive", "  x  ").status_code == 400

    def test_bad_action_422(self, adm, cid_a):
        assert bulk(adm, [cid_a], "nuke", "TEST_probe reason").status_code == 422

    def test_empty_ids_422(self, adm):
        assert bulk(adm, [], "unsuspend").status_code == 422

    def test_self_skipped(self, adm):
        me = requests.get(f"{API}/auth/me", headers=H(adm), timeout=30).json()["user"]
        c = mdb.contacts.find_one({"phone": {"$regex": "9873117605$"}}, {"_id": 0, "id": 1})
        if not c:
            pytest.skip("no master contact row")
        r = bulk(adm, [c["id"]], "unsuspend")
        assert r.status_code == 200
        assert r.json()["updated"] == 0 and len(r.json()["skipped"]) == 1, (me.get("phone"), r.json())


# --- suspend / unsuspend
class TestSuspend:
    def test_suspend_flow(self, adm, cid_a):
        r = bulk(adm, [cid_a], "suspend", "TEST_probe KYC docs expired")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["updated"] == 1 and d["action"] == "suspend"
        row = sb_row(S["uid_a"])
        assert row["is_suspended"] is True and row["suspended_reason"] == "TEST_probe KYC docs expired"
        c = mdb.contacts.find_one({"id": cid_a})
        assert c["suspended"] is True
        u = mdb.crm_users.find_one({"phone": "9999900021"})
        assert u["suspended"] is True

    def test_me_ok_while_suspended(self):
        r = requests.get(f"{API}/auth/me", headers=H(S["tok_a"]), timeout=30)
        assert r.status_code == 200
        u = r.json()["user"]
        assert u.get("suspended") is True and u.get("suspended_reason") == "TEST_probe KYC docs expired"

    @pytest.mark.parametrize("path", ["/provider/ledger", "/contacts", "/provider/me", "/provider/dashboard", "/notifications"])
    def test_other_apis_423(self, path):
        r = requests.get(f"{API}{path}", headers=H(S["tok_a"]), timeout=30)
        assert r.status_code == 423, (path, r.status_code, r.text[:200])
        assert r.json()["detail"]["code"] == "account_suspended"

    def test_relogin_still_suspended(self):
        from live_probe_fixtures import login
        tok, _ = login("9999900021", "Probe@12345")
        u = requests.get(f"{API}/auth/me", headers=H(tok), timeout=30).json()["user"]
        assert u.get("suspended") is True

    def test_other_provider_unaffected(self):
        r = requests.get(f"{API}/auth/me", headers=H(S["tok_b"]), timeout=30)
        assert r.status_code == 200 and not r.json()["user"].get("suspended")

    def test_unsuspend(self, adm, cid_a):
        r = bulk(adm, [cid_a], "unsuspend")
        assert r.status_code == 200 and r.json()["updated"] == 1
        assert sb_row(S["uid_a"])["is_suspended"] is False
        assert requests.get(f"{API}/auth/me", headers=H(S["tok_a"]), timeout=30).json()["user"].get("suspended") is False
        r = requests.get(f"{API}/provider/ledger", headers=H(S["tok_a"]), timeout=30)
        assert r.status_code != 423


# --- archive / restore
class TestArchive:
    def test_archive(self, adm, cid_b):
        r = bulk(adm, [cid_b], "archive", "TEST_probe duplicate account")
        assert r.status_code == 200 and r.json()["updated"] == 1 and r.json()["purge_after"]
        row = sb_row(S["uid_b"])
        assert row["is_archived"] is True and row["archived_reason"].startswith("admin_deleted")

    def test_archived_list(self, adm, cid_b):
        d = requests.get(f"{API}/admin/users/archived", headers=H(adm), timeout=30).json()
        it = [x for x in d["items"] if x["id"] == cid_b]
        assert it and it[0]["days_left"] in (29, 30)

    def test_hidden_from_contacts(self, adm, cid_b):
        d = requests.get(f"{API}/contacts", headers=H(adm), params={"limit": 500}, timeout=60).json()
        items = d.get("items", d) if isinstance(d, dict) else d
        assert cid_b not in [x["id"] for x in items]

    def test_archived_token_401(self):
        assert requests.get(f"{API}/auth/me", headers=H(S["tok_b"]), timeout=30).status_code == 401

    def test_archived_login_blocked(self):
        r = requests.post(f"{API}/auth/send-otp", json={"phone": "9999900022"}, timeout=30)
        r2 = requests.post(f"{API}/auth/verify-otp", json={"phone": "9999900022", "otp": "123456"}, timeout=30)
        print("archived login:", r.status_code, r2.status_code, r2.text[:200])
        # a deleted user should not be able to obtain a usable session
        if r2.status_code == 200 and r2.json().get("temp_token"):
            r3 = requests.post(f"{API}/auth/login-password", json={"password": "Probe@12345"}, headers=H(r2.json()["temp_token"]), timeout=30)
            print("login-password:", r3.status_code, r3.text[:200])
            assert r3.status_code != 200, "deleted user got a token from login-password"

    def test_archived_list_master_only(self):
        assert requests.get(f"{API}/admin/users/archived", headers=H(S["tok_a"]), timeout=30).status_code == 403

    def test_restore(self, adm, cid_b):
        r = bulk(adm, [cid_b], "restore")
        assert r.status_code == 200 and r.json()["updated"] == 1
        row = sb_row(S["uid_b"])
        assert row["is_archived"] is False and row["is_active"] is True
        assert requests.get(f"{API}/auth/me", headers=H(S["tok_b"]), timeout=30).status_code == 200
        d = requests.get(f"{API}/admin/users/archived", headers=H(adm), timeout=30).json()
        assert cid_b not in [x["id"] for x in d["items"]]

    def test_restore_ignores_non_archived(self, adm, cid_a):
        r = bulk(adm, [cid_a], "restore")
        assert r.status_code == 200 and r.json()["updated"] == 0


# --- cron
class TestCron:
    def test_no_auth(self):
        assert requests.post(f"{API}/admin/cron/erase-archived", timeout=30).status_code == 401

    def test_wrong_secret(self):
        assert requests.post(f"{API}/admin/cron/erase-archived", headers=H("nope"), timeout=30).status_code == 401
