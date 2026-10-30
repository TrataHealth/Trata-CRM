# Trata Health Admin directories: Trata Providers (/api/admin/directory/providers) + provider KYC details + Patient users (read-only)
import os
import sys
import collections
import pytest
import requests

sys.path.insert(0, os.path.dirname(__file__))
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
OTP = "123456"


def _login(phone, pwd):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": phone}, timeout=30)
    assert r.status_code == 200, r.text
    r = s.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=30)
    assert r.status_code == 200, r.text
    tmp = r.json().get("temp_token")
    r = s.post(f"{BASE_URL}/api/auth/login-password", json={"password": pwd},
               headers={"Authorization": f"Bearer {tmp}"}, timeout=30)
    assert r.status_code == 200, r.text
    tok = r.json().get("token") or r.json().get("access_token")
    s.headers.update({"Authorization": f"Bearer {tok}"})
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def manager():
    return _login("9000000001", "Trata@123")


@pytest.fixture(scope="module")
def directory(admin):
    r = admin.get(f"{BASE_URL}/api/admin/directory/providers", timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


# Provider directory list
class TestProviderDirectory:
    def test_shape(self, directory):
        assert isinstance(directory["items"], list) and len(directory["items"]) > 0
        assert isinstance(directory["roles"], list)
        it = directory["items"][0]
        for k in ("id", "name", "phone", "role", "kyc_status", "docs_total", "docs_approved", "created_at"):
            assert k in it
        assert "stage" not in it and "value" not in it

    def test_unique_ids(self, directory):
        ids = [x["id"] for x in directory["items"]]
        dup = [k for k, v in collections.Counter(ids).items() if v > 1]
        assert not dup, f"duplicate ids: {dup}"

    def test_unique_phones(self, directory):
        phones = [x["phone"] for x in directory["items"] if x.get("phone")]
        dup = [k for k, v in collections.Counter(phones).items() if v > 1]
        print("dup phones:", dup)
        assert not dup, f"duplicate phones: {dup}"

    def test_excludes_non_provider_roles(self, directory):
        roles = {x["role"] for x in directory["items"]}
        assert not roles & {"admin", "patient", "customer"}
        assert not {r["role"] for r in directory["roles"]} & {"admin", "patient", "customer"}

    def test_role_counts_match_total(self, directory):
        total = sum(r["count"] for r in directory["roles"])
        print("roles:", directory["roles"], "items:", len(directory["items"]))
        assert total == len(directory["items"]) or len(directory["items"]) == 500

    def test_role_filter(self, admin, directory):
        role = directory["roles"][0]["role"]
        r = admin.get(f"{BASE_URL}/api/admin/directory/providers", params={"role": role}, timeout=60)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items and all(x["role"] == role for x in items)
        assert len(items) == directory["roles"][0]["count"]

    def test_search_by_name_and_phone(self, admin, directory):
        p = next(x for x in directory["items"] if x.get("name") and x.get("phone"))
        r = admin.get(f"{BASE_URL}/api/admin/directory/providers", params={"q": p["name"][:5].upper()}, timeout=60)
        assert r.status_code == 200 and any(x["id"] == p["id"] for x in r.json()["items"])
        r = admin.get(f"{BASE_URL}/api/admin/directory/providers", params={"q": p["phone"][-6:]}, timeout=60)
        assert r.status_code == 200 and any(x["id"] == p["id"] for x in r.json()["items"])

    def test_kyc_filter(self, admin):
        allowed = {"pending": ("pending", "submitted", "under_review"), "verified": ("verified", "approved"), "rejected": ("rejected", "declined")}
        for k in ("pending", "verified", "rejected"):
            r = admin.get(f"{BASE_URL}/api/admin/directory/providers", params={"kyc": k}, timeout=60)
            assert r.status_code == 200
            assert all(str(x["kyc_status"]).lower().startswith(allowed[k]) for x in r.json()["items"])

    def test_kyc_filter_uppercase(self, admin):
        r1 = admin.get(f"{BASE_URL}/api/admin/directory/providers", params={"kyc": "pending"}, timeout=60).json()["items"]
        r2 = admin.get(f"{BASE_URL}/api/admin/directory/providers", params={"kyc": "Pending"}, timeout=60).json()["items"]
        assert len(r1) == len(r2), f"case sensitive kyc filter: {len(r1)} vs {len(r2)}"

    def test_forbidden_for_sales_manager(self, manager):
        r = manager.get(f"{BASE_URL}/api/admin/directory/providers", timeout=30)
        assert r.status_code == 403

    def test_unauthenticated(self):
        r = requests.get(f"{BASE_URL}/api/admin/directory/providers", timeout=30)
        assert r.status_code in (401, 403)


# Provider KYC details endpoint for every role in the directory
class TestProviderKycDetails:
    def test_details_for_each_role(self, admin, directory):
        seen, fails = {}, []
        for x in directory["items"]:
            if x["role"] in seen:
                continue
            seen[x["role"]] = x["id"]
        for role, uid in seen.items():
            r = admin.get(f"{BASE_URL}/api/admin/onboarding/providers/{uid}/kyc", timeout=60)
            if r.status_code != 200:
                fails.append((role, uid, r.status_code, r.text[:150]))
                continue
            d = r.json()
            for k in ("provider", "vertical", "checklist", "all_documents", "profile", "profile_table", "kyc_application"):
                assert k in d, f"{role}: missing {k}"
            assert d["provider"]["id"] == uid or str(d["provider"].get("id")) == uid
            print(role, "vertical=", d["vertical"], "profile_table=", d["profile_table"], "profile?", bool(d["profile"]),
                  "app?", bool(d["kyc_application"]), "checklist", len(d["checklist"]))
            if d["profile"]:
                assert not any(s in k.lower() for k in d["profile"] for s in ("password", "pin_hash"))
        assert not fails, fails

    def test_unknown_provider_404(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/onboarding/providers/00000000-0000-0000-0000-000000000000/kyc", timeout=30)
        assert r.status_code == 404

    def test_kyc_forbidden_for_manager(self, manager, directory):
        r = manager.get(f"{BASE_URL}/api/admin/onboarding/providers/{directory['items'][0]['id']}/kyc", timeout=30)
        assert r.status_code == 403


# Patient users (read-only)
class TestPatients:
    def test_list_unique(self, admin):
        r = admin.get(f"{BASE_URL}/api/admin/patients", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        items = d.get("patients") or d.get("items") or []
        assert items
        ids = [x["id"] for x in items]
        assert len(ids) == len(set(ids))
        r2 = admin.get(f"{BASE_URL}/api/admin/patients/{ids[0]}", timeout=60)
        assert r2.status_code == 200, r2.text

    def test_forbidden_for_manager(self, manager):
        r = manager.get(f"{BASE_URL}/api/admin/patients", timeout=30)
        assert r.status_code == 403
