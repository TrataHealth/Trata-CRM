# Directory parity with Provider App: one row per canonical profile, deleted list, delete/restore round trip
import os
import time

import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
PROTECTED_PHONES = {"7007123456", "9794131548", "8887652749", "8888765274", "9873117605", "9161108882"}


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


@pytest.fixture(scope="module")
def providers(admin):
    r = admin.get(BASE_URL + "/api/admin/directory/providers", timeout=90)
    assert r.status_code == 200, r.text
    return r.json()


# Providers listing: shape + counts
class TestProviders:
    def test_shape(self, providers):
        it = providers["items"][0]
        for k in ("row_key", "id", "org_name", "admin_name", "role", "kyc_status"):
            assert k in it
        keys = [i["row_key"] for i in providers["items"]]
        assert len(keys) == len(set(keys)), "duplicate row_key"

    def test_role_counts(self, providers):
        c = {x["role"]: x["count"] for x in providers["roles"]}
        print("ROLE COUNTS", c, [x["role"] for x in providers["roles"]])
        exp = {"hospital": 2, "path_lab": 13, "doctor": 5, "pharmacy": 5, "ambulance_provider": 3, "diagnostic_centre": 4,
               "paramedic": 2, "pharmacist": 1, "lab_tech": 1, "receptionist": 1, "nurse": 1}
        mism = {k: (v, c.get(k)) for k, v in exp.items() if c.get(k) != v}
        assert not mism, f"mismatch expected,actual: {mism}; extra roles: {set(c) - set(exp)}"

    def test_doctor_tab(self, admin):
        r = admin.get(BASE_URL + "/api/admin/directory/providers", params={"role": "doctor"}, timeout=90)
        d = r.json()["items"]
        names = sorted((i["admin_name"] or i["org_name"] or "") for i in d)
        phones = sorted((i["phone"] or "")[-10:] for i in d)
        print("DOCTORS", [(i["admin_name"], i["org_name"], i["phone"]) for i in d])
        assert len(d) == 5
        assert phones == sorted(["7007123456", "9794131548", "8887652749", "8888765274", "9873117605"])
        assert not any("meera" in (str(i["org_name"]) + str(i["admin_name"])).lower() for i in d)
        assert all(i["role"] == "doctor" for i in d)

    def test_q_filter(self, admin):
        r = admin.get(BASE_URL + "/api/admin/directory/providers", params={"q": "Prasad"}, timeout=90)
        items = r.json()["items"]
        assert items and all("prasad" in f"{i['org_name']} {i['admin_name']} {i['phone']} {i['email']}".lower() for i in items)

    @pytest.mark.parametrize("kyc", ["pending", "verified", "rejected"])
    def test_kyc_filter(self, admin, kyc):
        r = admin.get(BASE_URL + "/api/admin/directory/providers", params={"kyc": kyc}, timeout=90)
        assert r.status_code == 200
        print(kyc, len(r.json()["items"]), {i["kyc_status"] for i in r.json()["items"]})

    def test_kyc_invalid(self, admin):
        assert admin.get(BASE_URL + "/api/admin/directory/providers", params={"kyc": "bogus"}, timeout=90).status_code == 400

    def test_non_master_403(self):
        s = _login("9000000002", "Trata@123")
        assert s.get(BASE_URL + "/api/admin/directory/providers", timeout=60).status_code == 403
        assert s.get(BASE_URL + "/api/admin/directory/deleted", timeout=60).status_code == 403


# Deleted list
class TestDeleted:
    def test_provider_deleted(self, admin):
        r = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "provider"}, timeout=90)
        assert r.status_code == 200
        d = r.json()
        print("DELETED total", d["total"], d["roles"])
        assert 100 <= d["total"] <= 200
        assert all(i["kyc_status"] == "deactivated" for i in d["items"] if i["profile_table"] != "users")
        assert any("meera" in (str(i["org_name"]) + str(i["admin_name"])).lower() and i["role"] == "doctor" for i in d["items"])
        assert d["roles"]

    def test_patient_deleted(self, admin):
        r = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "patient"}, timeout=90)
        assert r.status_code == 200
        print("PATIENT deleted", r.json()["total"])
        assert r.json()["roles"] == []

    def test_invalid_app(self, admin):
        assert admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "x"}, timeout=60).status_code == 400


# Delete / restore round trip on a TEST throwaway
class TestRoundTrip:
    def test_round_trip(self, admin, providers):
        cands = [i for i in providers["items"] if i["id"] and i["profile_table"] != "users"
                 and "test" in f"{i['org_name']} {i['admin_name']}".lower()
                 and (i["phone"] or "")[-10:] not in PROTECTED_PHONES
                 and not any(w in f"{i['org_name']}".lower() for w in ("tathastu", "sahayak"))]
        print("CANDIDATES", [(i["role"], i["org_name"], i["phone"], i["kyc_status"]) for i in cands])
        if not cands:
            pytest.skip("no TEST throwaway provider")
        t = cands[0]
        uid, prev = t["id"], t["kyc_status"]
        same_user_rows = [i["row_key"] for i in providers["items"] if i["id"] == uid]
        print("TARGET", t["row_key"], t["org_name"], prev, "rows for user:", same_user_rows)
        try:
            r = admin.post(BASE_URL + "/api/admin/users/bulk", json={"user_ids": [uid], "action": "archive", "reason": "testing parity"}, timeout=90)
            assert r.status_code == 200, r.text
            print("ARCHIVE", r.json())
            p = admin.get(BASE_URL + "/api/admin/directory/providers", timeout=90).json()["items"]
            assert t["row_key"] not in [i["row_key"] for i in p]
            d = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "provider"}, timeout=90).json()["items"]
            row = next((i for i in d if i["row_key"] == t["row_key"]), None)
            assert row and row["deleted_reason"] == "testing parity"
        finally:
            r = admin.post(BASE_URL + "/api/admin/users/bulk", json={"user_ids": [uid], "action": "restore"}, timeout=90)
            print("RESTORE", r.status_code, r.text[:300])
        assert r.status_code == 200
        p = admin.get(BASE_URL + "/api/admin/directory/providers", timeout=90).json()["items"]
        back = next((i for i in p if i["row_key"] == t["row_key"]), None)
        assert back, "not restored to providers"
        assert back["kyc_status"] == prev, f"status {back['kyc_status']} != {prev}"
