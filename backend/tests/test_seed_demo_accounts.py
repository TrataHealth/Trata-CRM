"""Tests for POST /api/admin/seed-demo-accounts + login regression on the
4 canonical demo phones (Priya + 3 provider_owner)."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://patient-hub-133.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

MASTER_PHONE = "9873117605"
MASTER_PWD   = "Master@123"
ROHAN_PHONE  = "9000000002"
ROHAN_PWD    = "Trata@123"
OTP = "123456"

DEMO_PHONES = {
    "9000000001": ("regional_manager", None),
    "9000020003": ("provider_owner",   "ambulance"),
    "9000020004": ("provider_owner",   "hospital"),
    "9000020005": ("provider_owner",   "pathology"),
}


def _login(phone: str, password: str) -> str:
    s = requests.Session()
    r = s.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, f"send-otp {phone} -> {r.status_code} {r.text}"
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
    assert r.status_code == 200, f"verify-otp {phone} -> {r.status_code} {r.text}"
    j = r.json()
    temp = j["temp_token"]
    # If password not yet set, set it
    if j.get("needs_password_setup"):
        r = s.post(f"{API}/auth/set-password", json={"password": password},
                   headers={"Authorization": f"Bearer {temp}"}, timeout=15)
        assert r.status_code == 200, f"set-password {phone} -> {r.status_code} {r.text}"
        return r.json().get("access_token") or r.json().get("token")
    r = s.post(f"{API}/auth/login-password", json={"password": password},
               headers={"Authorization": f"Bearer {temp}"}, timeout=15)
    assert r.status_code == 200, f"login-password {phone} -> {r.status_code} {r.text}"
    j = r.json()
    return j.get("access_token") or j.get("token")


@pytest.fixture(scope="module")
def master_token():
    return _login(MASTER_PHONE, MASTER_PWD)


@pytest.fixture(scope="module")
def rohan_token():
    return _login(ROHAN_PHONE, ROHAN_PWD)


# ---------- Seed endpoint ----------
class TestSeedDemoAccounts:
    def test_non_master_admin_gets_403(self, rohan_token):
        r = requests.post(f"{API}/admin/seed-demo-accounts",
                          headers={"Authorization": f"Bearer {rohan_token}"}, timeout=20)
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"
        assert "Trata Health Admin only" in r.text

    def test_master_admin_seed_first_call(self, master_token):
        r = requests.post(f"{API}/admin/seed-demo-accounts",
                          headers={"Authorization": f"Bearer {master_token}"}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["success"] is True
        # After first successful call, all 4 canonical rows must exist in DB — regardless of
        # whether they were created THIS run or already existed from a prior run.
        assert (j["created_users"] + j["already_existed"]) == 4, j

    def test_master_admin_seed_idempotent(self, master_token):
        r = requests.post(f"{API}/admin/seed-demo-accounts",
                          headers={"Authorization": f"Bearer {master_token}"}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["success"] is True
        assert j["created_users"] == 0, f"expected 0 new users on 2nd call, got {j}"
        assert j["already_existed"] == 4, j


# ---------- Login regression ----------
class TestDemoLogins:
    @pytest.mark.parametrize("phone", list(DEMO_PHONES.keys()))
    def test_demo_phone_can_login(self, master_token, phone):
        # Ensure seeded first (module-scoped, harmless)
        requests.post(f"{API}/admin/seed-demo-accounts",
                      headers={"Authorization": f"Bearer {master_token}"}, timeout=30)
        expected_role, expected_ptype = DEMO_PHONES[phone]
        s = requests.Session()
        r = s.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=15)
        assert r.status_code == 200, r.text
        r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
        assert r.status_code == 200, f"verify-otp {phone}: {r.status_code} {r.text}"
        j = r.json()
        assert j["user"]["role"] == expected_role, j
        assert j["user"].get("provider_type") == expected_ptype, j
        temp = j["temp_token"]
        # These accounts already have password_hash from seed, so login-password path
        if j.get("needs_password_setup"):
            r = s.post(f"{API}/auth/set-password", json={"password": "Trata@123"},
                       headers={"Authorization": f"Bearer {temp}"}, timeout=15)
        else:
            r = s.post(f"{API}/auth/login-password", json={"password": "Trata@123"},
                       headers={"Authorization": f"Bearer {temp}"}, timeout=15)
        assert r.status_code == 200, f"login {phone}: {r.status_code} {r.text}"
        body = r.json()
        assert body.get("access_token") or body.get("token"), body

    def test_master_admin_login_unaffected(self):
        tok = _login(MASTER_PHONE, MASTER_PWD)
        assert tok


# ---------- Contacts visibility ----------
class TestContactsSurfaced:
    @pytest.mark.parametrize("ctype,expected_phone,expected_name", [
        ("hospital",           "9000020004", "City Care Hospital"),
        ("ambulance_provider", "9000020003", "Sanjay Ambulance Fleet"),
        ("pathologist",        "9000020005", "Zenith Diagnostics"),
    ])
    def test_contact_visible(self, master_token, ctype, expected_phone, expected_name):
        r = requests.get(f"{API}/contacts", params={"type": ctype},
                         headers={"Authorization": f"Bearer {master_token}"}, timeout=20)
        assert r.status_code == 200, r.text
        rows = r.json()
        if isinstance(rows, dict):
            rows = rows.get("items") or rows.get("contacts") or []
        phones = [c.get("phone") for c in rows]
        assert expected_phone in phones, f"{expected_phone} not found in {ctype} list; got {phones[:5]}"
        match = next(c for c in rows if c.get("phone") == expected_phone)
        assert match.get("name") == expected_name, match


# ---------- Regression: real synced provider still works ----------
class TestRealProviderRegression:
    def test_abhishek_ambulance_can_still_send_otp(self):
        # This account was reported as functional pre-fix. Just ensure send-otp still 200s.
        r = requests.post(f"{API}/auth/send-otp", json={"phone": "7678218261"}, timeout=15)
        assert r.status_code == 200, r.text
