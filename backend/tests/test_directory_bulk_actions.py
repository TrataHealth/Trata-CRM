"""Directory bulk actions (POST /api/admin/users/bulk with user_ids) for Trata Patient Users + Trata Providers.
Only touches TEST users created by `python bulk_dir_fixtures.py setup` (phones 89555000xx).
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
S = json.load(open("/tmp/bulk_dir_state.json"))
P1, P2, DOC = S["8955500011"], S["8955500012"], S["8955500013"]
mdb = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]


def H(t):
    return {"Authorization": f"Bearer {t}"}


def sb_row(uid):
    async def f():
        c = await asyncpg.connect(DSN, statement_cache_size=0)
        try:
            return dict(await c.fetchrow("SELECT is_suspended, suspended_reason, is_archived, is_active, archived_reason, purge_after FROM public.users WHERE id=$1", uid))
        finally:
            await c.close()
    return asyncio.run(f())


@pytest.fixture(scope="module")
def adm():
    return admin_token()


def bulk(tok, action, user_ids=None, reason=None, contact_ids=None):
    body = {"action": action, "reason": reason}
    if user_ids is not None:
        body["user_ids"] = user_ids
    if contact_ids is not None:
        body["contact_ids"] = contact_ids
    return requests.post(f"{API}/admin/users/bulk", headers=H(tok), json=body, timeout=90)


def patients(tok, q=None):
    r = requests.get(f"{API}/admin/patients", headers=H(tok), params={"q": q} if q else {}, timeout=90)
    assert r.status_code == 200, r.text
    return {p["id"]: p for p in r.json()["patients"]}


def providers(tok, q=None):
    r = requests.get(f"{API}/admin/directory/providers", headers=H(tok), params={"q": q} if q else {}, timeout=90)
    assert r.status_code == 200, r.text
    return r.json()


# --- validation / RBAC
class TestValidation:
    def test_no_ids_400(self, adm):
        r = bulk(adm, "unsuspend", user_ids=[])
        assert r.status_code == 400 and "Select at least one" in r.json()["detail"]

    def test_short_reason_400(self, adm):
        assert bulk(adm, "suspend", [P1], "abc").status_code == 400
        assert bulk(adm, "archive", [P1], None).status_code == 400

    def test_sales_rep_403(self):
        tok = admin_token("9000000002", "Trata@123")
        assert bulk(tok, "suspend", [P1], "TEST reason here").status_code == 403


# --- patient flow
class TestPatientFlow:
    def test_patients_visible(self, adm):
        ps = patients(adm, "Bulk")
        assert P1 in ps and P2 in ps
        assert ps[P1]["is_suspended"] is False

    def test_suspend_patient_by_user_id(self, adm):
        r = bulk(adm, "suspend", [P1], "TEST suspend reason")
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 1
        row = sb_row(P1)
        assert row["is_suspended"] is True and row["suspended_reason"] == "TEST suspend reason"
        p = patients(adm, "Bulk")[P1]
        assert p["is_suspended"] is True and p["suspended_reason"] == "TEST suspend reason"
        c = mdb.contacts.find_one({"supabase_user_id": P1}, {"_id": 0})
        assert c and c.get("suspended") is True

    def test_suspend_twice_no_duplicate_contact(self, adm):
        assert bulk(adm, "suspend", [P1], "TEST suspend reason").status_code == 200
        assert mdb.contacts.count_documents({"supabase_user_id": P1}) == 1

    def test_unsuspend_patient(self, adm):
        r = bulk(adm, "unsuspend", [P1])
        assert r.status_code == 200 and r.json()["updated"] == 1
        assert sb_row(P1)["is_suspended"] is False
        assert patients(adm, "Bulk")[P1]["is_suspended"] is False

    def test_archive_patient_goes_to_bin_then_restore(self, adm):
        r = bulk(adm, "archive", [P2], "TEST delete reason")
        assert r.status_code == 200 and r.json()["updated"] == 1
        row = sb_row(P2)
        assert row["is_archived"] is True and row["archived_reason"].startswith("admin_deleted")
        assert P2 not in patients(adm, "Bulk")
        arc = requests.get(f"{API}/admin/users/archived", headers=H(adm), timeout=60).json()["items"]
        hit = [a for a in arc if a.get("supabase_user_id") == P2]
        assert hit and hit[0]["days_left"] in (29, 30)
        r = bulk(adm, "restore", contact_ids=[hit[0]["id"]])
        assert r.status_code == 200 and r.json()["updated"] == 1
        assert sb_row(P2)["is_archived"] is False
        assert P2 in patients(adm, "Bulk")


# --- provider flow (doctor test user)
class TestProviderFlow:
    def test_provider_visible(self, adm):
        items = {i["id"]: i for i in providers(adm, "Bulk Sample")["items"]}
        assert DOC in items and items[DOC]["is_suspended"] is False

    def test_suspend_provider_and_restore(self, adm):
        assert bulk(adm, "suspend", [DOC], "TEST provider suspend").status_code == 200
        items = {i["id"]: i for i in providers(adm, "Bulk Sample")["items"]}
        assert items[DOC]["is_suspended"] is True
        assert bulk(adm, "unsuspend", [DOC]).status_code == 200
        items = {i["id"]: i for i in providers(adm, "Bulk Sample")["items"]}
        assert items[DOC]["is_suspended"] is False

    def test_archive_provider_and_restore(self, adm):
        assert bulk(adm, "archive", [DOC], "TEST provider delete").status_code == 200
        assert DOC not in {i["id"] for i in providers(adm, "Bulk Sample")["items"]}
        arc = requests.get(f"{API}/admin/users/archived", headers=H(adm), timeout=60).json()["items"]
        hit = [a for a in arc if a.get("supabase_user_id") == DOC]
        assert hit
        assert bulk(adm, "restore", contact_ids=[hit[0]["id"]]).status_code == 200
        assert DOC in {i["id"] for i in providers(adm, "Bulk Sample")["items"]}


# --- Tathastu shows under Hospital tab with correct admin
class TestTathastu:
    def test_tathastu_hospital_admin(self, adm):
        r = requests.get(f"{API}/admin/directory/providers", headers=H(adm), params={"role": "hospital", "q": "tathastu"}, timeout=90)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "Tathastu not found under hospital"
        t = [i for i in items if "tathastu" in (i.get("org_name") or i.get("name") or "").lower()]
        assert t
        print([(i["org_name"], i["admin_name"], i["role"]) for i in t])
        assert all((i.get("admin_name") or "") != "DM Upadhyay" for i in t)
        assert any("ashutosh" in (i.get("admin_name") or "").lower() for i in t)
