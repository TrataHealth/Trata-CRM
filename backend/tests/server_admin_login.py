"""Master-admin login helper for TEST_probe fixtures."""
import requests

from live_probe_fixtures import BASE_URL, OTP


def admin_token(phone="9873117605", pwd="Master@123"):
    r = requests.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": phone}, timeout=20)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=20)
    assert r.status_code == 200, r.text
    r = requests.post(f"{BASE_URL}/api/auth/login-password", json={"password": pwd},
                      headers={"Authorization": f"Bearer {r.json()['temp_token']}"}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json().get("token") or r.json().get("access_token")
