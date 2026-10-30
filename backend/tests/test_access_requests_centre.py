"""Iter 27: public provider search + access requests, Trata Health Admin notification centre, alert prefs 'access'.
Run: cd /app/backend && python -m pytest tests/test_access_requests_centre.py -v"""
import os
import time
import uuid

import pytest
import requests

ENV = {}
for _f in ("/app/backend/.env", "/app/frontend/.env"):
    for line in open(_f):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            ENV[k] = v.strip().strip('"')
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or ENV["REACT_APP_BACKEND_URL"]).rstrip("/")
API = f"{BASE_URL}/api"
OTP = "123456"
SUF = str(int(time.time()))[-3:]
PHONE_A = f"9111133{SUF}"


def login(phone, pwd):
    requests.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=60)
    r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=60)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['temp_token']}"}
    r = requests.post(f"{API}/auth/login-password", json={"password": pwd}, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    return r.json().get("token") or r.json().get("access_token")


@pytest.fixture(scope="module")
def M():
    return {"Authorization": f"Bearer {login('9873117605', 'Master@123')}"}


@pytest.fixture(scope="module")
def S():
    return {"Authorization": f"Bearer {login('9000000001', 'Trata@123')}"}


@pytest.fixture(scope="module")
def provider():
    r = requests.get(f"{API}/public/providers/search", params={"q": "lila"}, timeout=30)
    assert r.status_code == 200
    items = r.json()["items"]
    assert items, "no provider matching 'lila'"
    return items[0]


# ── Public provider search ──
def test_search_short_query_empty():
    r = requests.get(f"{API}/public/providers/search", params={"q": "l"}, timeout=30)
    assert r.status_code == 200 and r.json()["items"] == []


def test_search_lila_no_patients(provider):
    r = requests.get(f"{API}/public/providers/search", params={"q": "lila"}, timeout=30)
    items = r.json()["items"]
    assert all(i.get("type") != "patient" for i in items)
    assert set(items[0].keys()) <= {"id", "name", "type", "city"}


def test_search_regex_safe():
    r = requests.get(f"{API}/public/providers/search", params={"q": ".*"}, timeout=30)
    assert r.status_code == 200


# ── Public access request validation ──
@pytest.mark.parametrize("patch,code", [
    ({"phone": "12345"}, 400), ({"role_wanted": "superuser"}, 400),
    ({"provider_contact_id": "does-not-exist"}, 400), ({"name": "A"}, 422)])
def test_create_validation(provider, patch, code):
    body = {"name": "TEST_Val", "phone": "9111133998", "role_wanted": "provider_staff",
            "provider_contact_id": provider["id"], "note": ""}
    body.update(patch)
    r = requests.post(f"{API}/public/access-requests", json=body, timeout=30)
    assert r.status_code == code, r.text


STATE = {}


def test_create_and_duplicate(provider):
    body = {"name": "TEST_Asha", "phone": PHONE_A, "role_wanted": "provider_admin",
            "provider_contact_id": provider["id"], "note": "TEST front desk"}
    r = requests.post(f"{API}/public/access-requests", json=body, timeout=30)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    r2 = requests.post(f"{API}/public/access-requests", json=body, timeout=30)
    assert r2.status_code == 409


# ── Notification centre ──
def test_centre_shows_unread(M):
    r = requests.get(f"{API}/admin/notification-centre", headers=M, timeout=30)
    assert r.status_code == 200
    d = r.json()
    assert d["pending_access"] >= 1
    it = [n for n in d["items"] if n.get("kind") == "access_request" and PHONE_A in (n.get("message") or "")]
    assert it and it[0]["is_read"] is False
    assert "read_by" not in it[0]
    STATE["nid"] = it[0]["id"]


def test_list_pending_and_decide(M):
    r = requests.get(f"{API}/admin/access-requests", params={"status": "pending"}, headers=M, timeout=30)
    assert r.status_code == 200
    mine = [x for x in r.json()["items"] if x["phone"] == PHONE_A]
    assert mine and "ip" not in mine[0] and mine[0]["status"] == "pending"
    rid = mine[0]["id"]
    bad = requests.post(f"{API}/admin/access-requests/{rid}", json={"action": "nope"}, headers=M, timeout=30)
    assert bad.status_code == 400
    d = requests.post(f"{API}/admin/access-requests/{rid}", json={"action": "decline", "note": "TEST reason"}, headers=M, timeout=30)
    assert d.status_code == 200 and d.json()["status"] == "declined" and d.json()["decision_note"] == "TEST reason"
    again = requests.post(f"{API}/admin/access-requests/{rid}", json={"action": "approve"}, headers=M, timeout=30)
    assert again.status_code == 404
    r = requests.get(f"{API}/admin/access-requests", params={"status": "declined"}, headers=M, timeout=30)
    assert any(x["id"] == rid for x in r.json()["items"])
    # deciding marks the notification read
    c = requests.get(f"{API}/admin/notification-centre", headers=M, timeout=30).json()
    n = [x for x in c["items"] if x["id"] == STATE["nid"]]
    assert n and n[0]["is_read"] is True


def test_mark_read_single(M):
    r = requests.post(f"{API}/admin/notification-centre/read", json={"id": STATE["nid"]}, headers=M, timeout=30)
    assert r.status_code == 200 and "updated" in r.json()


def test_approve_flow(M, provider):
    phone = f"9111134{SUF}"
    r = requests.post(f"{API}/public/access-requests", json={"name": "TEST_Bina", "phone": phone, "role_wanted": "provider_staff",
                                                            "provider_contact_id": provider["id"]}, timeout=30)
    assert r.status_code == 200, r.text
    items = requests.get(f"{API}/admin/access-requests", params={"status": "pending"}, headers=M, timeout=30).json()["items"]
    rid = [x for x in items if x["phone"] == phone][0]["id"]
    d = requests.post(f"{API}/admin/access-requests/{rid}", json={"action": "approve"}, headers=M, timeout=30)
    assert d.status_code == 200 and d.json()["status"] == "approved"


# ── RBAC ──
@pytest.mark.parametrize("method,path,body", [
    ("get", "/admin/notification-centre", None), ("post", "/admin/notification-centre/read", {}),
    ("get", "/admin/access-requests", None), ("post", "/admin/access-requests/xyz", {"action": "approve"})])
def test_sales_manager_forbidden(S, method, path, body):
    r = getattr(requests, method)(f"{API}{path}", headers=S, json=body, timeout=30)
    assert r.status_code == 403


def test_unauth_forbidden():
    assert requests.get(f"{API}/admin/notification-centre", timeout=30).status_code in (401, 403)


# ── Alerts prefs include access ──
def test_alert_prefs_include_access(M):
    r = requests.get(f"{API}/admin/alerts/devices", headers=M, timeout=30)
    assert r.status_code == 200
    assert "access" in r.json()["prefs"]


# ── Rate limit (run last) ──
def test_zz_rate_limit(provider):
    codes = []
    for i in range(7):
        r = requests.post(f"{API}/public/access-requests", json={"name": "TEST_Rate", "phone": f"91111350{i:02d}",
                                                                "role_wanted": "provider_staff", "provider_contact_id": provider["id"]}, timeout=30)
        codes.append(r.status_code)
    assert 429 in codes, codes


def test_zz_rate_limit_xff_spoof(provider):
    """Spoofing X-Forwarded-For should not bypass the per-IP limit."""
    r = requests.post(f"{API}/public/access-requests", headers={"X-Forwarded-For": f"10.9.{uuid.uuid4().int % 250}.7"},
                      json={"name": "TEST_Spoof", "phone": f"91111360{SUF[-2:]}", "role_wanted": "provider_staff",
                            "provider_contact_id": provider["id"]}, timeout=30)
    assert r.status_code == 429, f"XFF spoof bypassed rate limit: {r.status_code} {r.text}"
