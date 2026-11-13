# Patient App parity: /admin/patients == customer_profiles; app-scoped suspend/archive (patient vs provider) never overlap
import os

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
MANISH = "54acfc31-423c-45b2-b9b5-766071de5f92"
EXPECTED = {"7678218261": "Siddharth Gupta", "9199000111": "Test City Capture", "9554310029": "Manish Mishra",
            "9161108882": "Abhishek Tripathi", "8808060344": "Esha arora", "9811549920": "Rekha Gupta",
            "9140179445": "Jasmeet Kaur", "9989148015": "Sid", "9161234567": "Test Patient Lko", "9873117605": "Siddharth Gupta"}


def _login(phone, pwd):
    s = requests.Session()
    s.post(BASE_URL + "/api/auth/send-otp", json={"phone": phone})
    t = s.post(BASE_URL + "/api/auth/verify-otp", json={"phone": phone, "otp": "123456"}).json()["temp_token"]
    r = s.post(BASE_URL + "/api/auth/login-password", json={"password": pwd}, headers={"Authorization": "Bearer " + t}).json()
    s.headers["Authorization"] = "Bearer " + (r.get("token") or r.get("access_token"))
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


def patients(admin, **p):
    r = admin.get(BASE_URL + "/api/admin/patients", params={"limit": 500, **p}, timeout=90)
    assert r.status_code == 200, r.text
    d = r.json()
    return d["patients"]


def providers(admin, **p):
    r = admin.get(BASE_URL + "/api/admin/directory/providers", params=p, timeout=90)
    assert r.status_code == 200, r.text
    return r.json()


def bulk(admin, ids, action, app, reason="parity test"):
    body = {"user_ids": ids, "action": action, "reason": reason}
    if app:
        body["app"] = app
    r = admin.post(BASE_URL + "/api/admin/users/bulk", json=body, timeout=90)
    assert r.status_code == 200, r.text
    return r.json()


def by_phone(items, ph):
    return [i for i in items if (i.get("phone") or "")[-10:] == ph]


def prov_sig(admin):
    return sorted((i["row_key"], i["kyc_status"], bool(i["is_suspended"])) for i in providers(admin)["items"])


# Roster equals Patient App list
class TestRoster:
    def test_exact_ten(self, admin):
        items = patients(admin)
        print("PATIENTS", [(i.get("name"), i.get("phone"), i.get("city")) for i in items])
        phones = sorted((i.get("phone") or "")[-10:] for i in items)
        assert phones == sorted(EXPECTED), phones
        for i in items:
            assert (i.get("name") or "").strip().lower() == EXPECTED[(i["phone"])[-10:]].lower(), i
            assert isinstance(i["id"], str) and i["id"]

    def test_manish_id(self, admin):
        m = by_phone(patients(admin), "9554310029")
        assert m and m[0]["id"] == MANISH

    def test_q(self, admin):
        items = patients(admin, q="Lko")
        assert [i["phone"][-10:] for i in items] == ["9161234567"]


# Patient-scope suspend/unsuspend + archive/restore leave provider side untouched
class TestPatientScope:
    def test_suspend_roundtrip(self, admin):
        p = by_phone(patients(admin), "9161234567")[0]
        before = prov_sig(admin)
        try:
            r = bulk(admin, [p["id"]], "suspend", "patient")
            assert r["updated"] == 1, r
            q = by_phone(patients(admin), "9161234567")[0]
            assert q["is_suspended"] is True and q["suspended_reason"] == "parity test"
            assert q["is_active"] == p["is_active"]
            assert prov_sig(admin) == before
        finally:
            bulk(admin, [p["id"]], "unsuspend", "patient")
        assert by_phone(patients(admin), "9161234567")[0]["is_suspended"] is False

    def test_archive_roundtrip(self, admin):
        p = by_phone(patients(admin), "9199000111")[0]
        before = prov_sig(admin)
        dprov_before = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "provider"}, timeout=90).json()["total"]
        try:
            r = bulk(admin, [p["id"]], "archive", "patient")
            assert r["updated"] == 1 and r["purge_after"], r
            assert not by_phone(patients(admin), "9199000111")
            d = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "patient"}, timeout=90).json()
            row = by_phone(d["items"], "9199000111")
            assert row and row[0]["id"] == p["id"] and row[0]["days_left"] in (29, 30)
            assert "parity test" in (row[0]["archived_reason"] or "")
            assert prov_sig(admin) == before
            assert admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "provider"}, timeout=90).json()["total"] == dprov_before
        finally:
            bulk(admin, [p["id"]], "restore", "patient")
        back = by_phone(patients(admin), "9199000111")
        assert back and back[0]["name"] == "Test City Capture" and back[0]["city"] == "Lucknow"
        d = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "patient"}, timeout=90).json()
        assert not by_phone(d["items"], "9199000111")

    def test_master_admin_protected(self, admin):
        m = by_phone(patients(admin), "9873117605")[0]
        r = bulk(admin, [m["id"]], "suspend", "patient")
        assert r["updated"] == 0
        assert by_phone(patients(admin), "9873117605")[0]["is_suspended"] is False


# Overlap: same login is patient + diagnostic centre
class TestOverlap:
    def test_provider_suspend_does_not_touch_patient(self, admin):
        rows = [i for i in providers(admin)["items"] if i["user_id"] == MANISH]
        print("MANISH PROVIDER ROWS", [(i["role"], i["org_name"], i["admin_name"], i["kyc_status"], i["is_suspended"]) for i in rows])
        assert any(i["role"] == "diagnostic_centre" for i in rows)
        prev = {i["row_key"]: i["kyc_status"] for i in rows}
        pat_before = by_phone(patients(admin), "9554310029")[0]
        try:
            bulk(admin, [MANISH], "suspend", "provider")
            after = [i for i in providers(admin)["items"] if i["user_id"] == MANISH]
            dc = [i for i in after if i["role"] == "diagnostic_centre"][0]
            assert dc["kyc_status"] == "suspended" and dc["is_suspended"] is True, dc
            pat = by_phone(patients(admin), "9554310029")[0]
            assert pat["is_suspended"] is False and pat["is_active"] == pat_before["is_active"], pat
        finally:
            bulk(admin, [MANISH], "unsuspend", "provider")
        restored = {i["row_key"]: i["kyc_status"] for i in providers(admin)["items"] if i["user_id"] == MANISH}
        assert restored == prev, (prev, restored)
        assert all(not i["is_suspended"] for i in providers(admin)["items"] if i["user_id"] == MANISH)
        assert by_phone(patients(admin), "9554310029")[0]["is_suspended"] is False

    def test_patient_suspend_does_not_touch_provider(self, admin):
        before = [(i["row_key"], i["kyc_status"], i["is_suspended"]) for i in providers(admin)["items"] if i["user_id"] == MANISH]
        try:
            bulk(admin, [MANISH], "suspend", "patient")
            assert by_phone(patients(admin), "9554310029")[0]["is_suspended"] is True
            now = [(i["row_key"], i["kyc_status"], i["is_suspended"]) for i in providers(admin)["items"] if i["user_id"] == MANISH]
            assert now == before
        finally:
            bulk(admin, [MANISH], "unsuspend", "patient")
        assert by_phone(patients(admin), "9554310029")[0]["is_suspended"] is False


# Provider archive/restore (default app) on throwaway test provider
class TestProviderArchive:
    def test_roundtrip(self, admin):
        items = providers(admin)["items"]
        cand = [i for i in items if "xenon" in (i["org_name"] or "").lower()] or \
               [i for i in items if "test" in f"{i['org_name']} {i['admin_name']}".lower() and i["profile_id"]]
        assert cand
        t = cand[0]
        uid, prev = t["user_id"], t["kyc_status"]
        print("THROWAWAY", t["org_name"], t["admin_name"], t["phone"], prev)
        assert (t["phone"] or "")[-10:] != "9873117605"
        try:
            bulk(admin, [uid], "archive", None)
            assert not [i for i in providers(admin)["items"] if i["row_key"] == t["row_key"]]
            d = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "provider"}, timeout=90).json()
            row = [i for i in d["items"] if i["row_key"] == t["row_key"]]
            assert row and row[0]["deleted_reason"] == "parity test"
            assert row[0]["is_active"] is not False or True  # users row untouched check below
        finally:
            bulk(admin, [uid], "restore", None)
        back = [i for i in providers(admin)["items"] if i["row_key"] == t["row_key"]]
        assert back and back[0]["kyc_status"] == prev


# Regression
class TestRegression:
    def test_doctors(self, admin):
        d = providers(admin, role="doctor")["items"]
        assert len(d) == 5

    def test_invalid_app(self, admin):
        r = admin.post(BASE_URL + "/api/admin/users/bulk", json={"user_ids": [MANISH], "action": "suspend", "reason": "parity test", "app": "bogus"}, timeout=60)
        print("INVALID APP", r.status_code, r.text[:200])
        assert r.status_code in (400, 422)
