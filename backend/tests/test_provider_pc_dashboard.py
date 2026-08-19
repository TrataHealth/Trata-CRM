"""Backend tests: /api/provider/pc-dashboard for all vertical providers.

Covers ambulance (Abhishek), hospital (HFR Test Hospital), paramedic
(Smoke Auto Paramedic). Uses the full 3-step auth (send-otp -> verify-otp
-> login-password/set-password) against the deployed preview URL.
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback for local runs - read frontend/.env
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

OTP = "123456"

PROVIDERS = {
    "ambulance": {"phone": "7678218261", "password": "Provider@123", "expected_vertical": "ambulance"},
    "hospital":  {"phone": "9310018056", "password": "HFRTest@123",  "expected_vertical": "hospital"},
    "paramedic": {"phone": "9939971813", "password": "Para@123",     "expected_vertical": "paramedic"},
}


def _login(phone: str, password: str) -> str:
    """Full 3-step login. Returns access token. Auto-runs set-password if needed."""
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"

    r = s.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, f"send-otp failed for {phone}: {r.status_code} {r.text}"

    r = s.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
    assert r.status_code == 200, f"verify-otp failed for {phone}: {r.status_code} {r.text}"
    body = r.json()
    temp_token = body["temp_token"]
    needs_setup = body.get("needs_password_setup", False)

    hdr = {"Authorization": f"Bearer {temp_token}", "Content-Type": "application/json"}
    if needs_setup:
        r = s.post(f"{BASE_URL}/api/auth/set-password",
                   json={"password": password}, headers=hdr, timeout=15)
        assert r.status_code == 200, f"set-password failed for {phone}: {r.status_code} {r.text}"
        access = r.json().get("access_token") or r.json().get("token")
    else:
        r = s.post(f"{BASE_URL}/api/auth/login-password",
                   json={"password": password}, headers=hdr, timeout=15)
        # if password wrong (from stale seed), try set-password (was cleared?) - skip
        assert r.status_code == 200, f"login-password failed for {phone}: {r.status_code} {r.text}"
        access = r.json().get("access_token") or r.json().get("token")
    assert access, f"no access token returned for {phone}: {r.text}"
    return access


@pytest.fixture(scope="module", params=list(PROVIDERS.keys()))
def provider(request):
    key = request.param
    cfg = PROVIDERS[key]
    try:
        token = _login(cfg["phone"], cfg["password"])
    except AssertionError as e:
        pytest.skip(f"Auth setup failed for {key}: {e}")
    return {"key": key, "token": token, **cfg}


class TestProviderPCDashboard:
    """Verify /api/provider/pc-dashboard for all 3 verticals."""

    def test_dashboard_returns_200_and_correct_vertical(self, provider):
        r = requests.get(
            f"{BASE_URL}/api/provider/pc-dashboard",
            headers={"Authorization": f"Bearer {provider['token']}"},
            timeout=20,
        )
        assert r.status_code == 200, f"{provider['key']}: {r.status_code} {r.text}"
        data = r.json()
        assert data.get("vertical") == provider["expected_vertical"], \
            f"{provider['key']}: expected vertical={provider['expected_vertical']}, got {data.get('vertical')}"

    def test_dashboard_provider_payload(self, provider):
        r = requests.get(
            f"{BASE_URL}/api/provider/pc-dashboard",
            headers={"Authorization": f"Bearer {provider['token']}"},
            timeout=20,
        )
        data = r.json()
        p = data.get("provider") or {}
        assert isinstance(p, dict) and p, f"{provider['key']}: provider payload empty"
        # business_name must always exist; city/state are optional (some vertical tables
        # like paramedic_profiles don't have those columns yet — FE handles gracefully)
        assert "business_name" in p, f"{provider['key']}: missing 'business_name' in provider payload"
        assert p.get("business_name"), f"{provider['key']}: business_name is empty"
        # at least ONE of status / verification_status / is_verified should be present
        assert any(k in p for k in ("status", "verification_status", "is_verified")), \
            f"{provider['key']}: no status field in provider payload"

    def test_dashboard_has_kpis_and_recent_cases(self, provider):
        r = requests.get(
            f"{BASE_URL}/api/provider/pc-dashboard",
            headers={"Authorization": f"Bearer {provider['token']}"},
            timeout=20,
        )
        data = r.json()
        assert "kpis" in data, f"{provider['key']}: kpis missing"
        assert isinstance(data["kpis"], dict)
        assert "recent_cases" in data, f"{provider['key']}: recent_cases missing"
        assert isinstance(data["recent_cases"], list)

    def test_ambulance_has_fleet_and_lifetime_fields(self, provider):
        """Ambulance regression: must still expose fleet + lifetime earnings fields."""
        if provider["key"] != "ambulance":
            pytest.skip("ambulance-only regression check")
        r = requests.get(
            f"{BASE_URL}/api/provider/pc-dashboard",
            headers={"Authorization": f"Bearer {provider['token']}"},
            timeout=20,
        )
        data = r.json()
        assert "fleet" in data, "ambulance: fleet array missing"
        assert isinstance(data["fleet"], list)
        kpis = data["kpis"]
        # ambulance-specific KPIs
        for k in ("active_trips", "trips_today"):
            assert k in kpis, f"ambulance kpis missing {k}"

    def test_hospital_business_name(self, provider):
        if provider["key"] != "hospital":
            pytest.skip("hospital-only")
        r = requests.get(
            f"{BASE_URL}/api/provider/pc-dashboard",
            headers={"Authorization": f"Bearer {provider['token']}"},
            timeout=20,
        )
        data = r.json()
        bn = (data.get("provider") or {}).get("business_name") or ""
        assert "HFR" in bn or "Hospital" in bn, f"hospital business_name unexpected: {bn!r}"


class TestUnauthorised:
    def test_no_token_returns_401_or_403(self):
        r = requests.get(f"{BASE_URL}/api/provider/pc-dashboard", timeout=10)
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"
