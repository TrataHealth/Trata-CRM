# ABDM Scan & Share (facility side) API tests: QR, shares list, inbound auth, processing harness
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL") or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split()[0]
BASE_URL = BASE_URL.rstrip("/")
IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date().isoformat()
CODE = "THJ7J8LG"
HOSP_UID = "7254d4be-941d-4999-a5e3-c04664ab3a6e"


def login(phone, password, login_as=None):
    body = {"phone": phone, "otp": "123456"}
    if login_as:
        body["login_as"] = login_as
    r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json=body, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"verify-otp failed {phone}: {r.status_code} {r.text[:200]}")
    tmp = r.json()["temp_token"]
    r = requests.post(f"{BASE_URL}/api/auth/login-password", json={"password": password},
                      headers={"Authorization": f"Bearer {tmp}"}, timeout=30)
    if r.status_code != 200:
        pytest.skip(f"login-password failed {phone}: {r.status_code} {r.text[:200]}")
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def hosp():
    return login("9792832090", "TestHosp@123", "provider")


@pytest.fixture(scope="module")
def admin():
    return login("9873117605", "Master@123", "staff")


@pytest.fixture(scope="module")
def rohan():
    return login("9000000002", "Trata@123", "staff")


# --- QR endpoint ---
class TestShareQr:
    def test_qr_hospital(self, hosp):
        r = requests.get(f"{BASE_URL}/api/abdm/share/qr", headers=hosp, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["code"] == CODE
        assert d["hip_id"] == "IN0910034478"
        assert d["qr_url"] == f"https://phrsbx.abdm.gov.in/share-profile?hip-id=IN0910034478&counter-id={CODE}"
        assert "hospital_name" in d
        r2 = requests.get(f"{BASE_URL}/api/abdm/share/qr", headers=hosp, timeout=30)
        assert r2.json()["code"] == d["code"]

    def test_qr_admin_forbidden(self, admin):
        r = requests.get(f"{BASE_URL}/api/abdm/share/qr", headers=admin, timeout=30)
        assert r.status_code == 403

    def test_qr_rohan_forbidden(self, rohan):
        r = requests.get(f"{BASE_URL}/api/abdm/share/qr", headers=rohan, timeout=30)
        assert r.status_code == 403

    def test_qr_unauth(self):
        r = requests.get(f"{BASE_URL}/api/abdm/share/qr", timeout=30)
        assert r.status_code in (401, 403)


# --- Shares list endpoint ---
class TestShareProfiles:
    def test_hospital_sees_own(self, hosp):
        r = requests.get(f"{BASE_URL}/api/abdm/share/profiles", params={"date": TODAY}, headers=hosp, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["date"] == TODAY
        assert len(d["profiles"]) >= 1
        assert all(p["hospital_user_id"] == HOSP_UID for p in d["profiles"])
        assert all("_id" not in p for p in d["profiles"])

    def test_admin_sees_all(self, admin, hosp):
        r = requests.get(f"{BASE_URL}/api/abdm/share/profiles", params={"date": TODAY}, headers=admin, timeout=30)
        assert r.status_code == 200, r.text
        assert any(p["counter"] == CODE for p in r.json()["profiles"])

    def test_rohan_forbidden(self, rohan):
        r = requests.get(f"{BASE_URL}/api/abdm/share/profiles", headers=rohan, timeout=30)
        assert r.status_code == 403

    def test_past_date_empty(self, hosp):
        r = requests.get(f"{BASE_URL}/api/abdm/share/profiles", params={"date": "2020-01-01"}, headers=hosp, timeout=30)
        assert r.status_code == 200 and r.json()["profiles"] == []


# --- Inbound gateway callback auth ---
class TestInbound:
    def test_no_auth(self):
        r = requests.post(f"{BASE_URL}/api/v3/hip/patient/share", json={"metaData": {"context": CODE}}, timeout=30)
        assert r.status_code == 401, r.text

    def test_bad_auth(self):
        r = requests.post(f"{BASE_URL}/api/v3/hip/patient/share", json={"metaData": {"context": CODE}},
                          headers={"Authorization": "Bearer abc.def.ghi"}, timeout=30)
        assert r.status_code == 401, r.text


# --- Processing harness (internal process() with stubbed on-share) ---
class TestHarness:
    def test_harness(self):
        out = subprocess.run(["python3", "tests/share_harness.py", CODE], cwd="/app/backend",
                             capture_output=True, text=True, timeout=120)
        print(out.stdout, out.stderr[-1500:])
        assert out.returncode == 0, out.stderr
        lines = [l for l in out.stdout.splitlines() if l.startswith("/patient-share/v3/on-share")]
        assert len(lines) == 4
        assert '"status": "SUCCESS"' in lines[0] and '"tokenNumber"' in lines[0]
        t1 = re.search(r'"tokenNumber": "(\d+)"', lines[0]).group(1)
        t2 = re.search(r'"tokenNumber": "(\d+)"', lines[1]).group(1)
        t3 = re.search(r'"tokenNumber": "(\d+)"', lines[2]).group(1)
        assert t1 == t2
        assert t3 != t1
        assert '"error"' in lines[3] and '"requestId": "req-4"' in lines[3]
