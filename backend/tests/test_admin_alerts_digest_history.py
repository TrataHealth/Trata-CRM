"""Iter 26: master-admin push alerts API, AI morning digest + cron, record history, audit health regression.
Run: cd /app/backend && python -m pytest tests/test_admin_alerts_digest_history.py -v"""
import base64
import os
import time

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

ENV = {}
for _f in ("/app/backend/.env", "/app/frontend/.env"):
    for line in open(_f):
        if "=" in line and not line.startswith("#"):
            k, v = line.strip().split("=", 1)
            ENV[k] = v.strip().strip('"')
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or ENV["REACT_APP_BACKEND_URL"]).rstrip("/")
CRON = ENV["WEBHOOK_CRON_SECRET"]
API = f"{BASE_URL}/api"
OTP = "123456"


def login(phone, pwd):
    requests.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=60)
    r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=60)
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['temp_token']}"}
    r = requests.post(f"{API}/auth/login-password", json={"password": pwd}, headers=h, timeout=60)
    assert r.status_code == 200, r.text
    return r.json().get("token") or r.json().get("access_token")


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def fake_keys():
    pub = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"p256dh": b64u(pub), "auth": b64u(os.urandom(16))}


@pytest.fixture(scope="module")
def M():
    return {"Authorization": f"Bearer {login('9873117605', 'Master@123')}"}


@pytest.fixture(scope="module")
def S():
    return {"Authorization": f"Bearer {login('9000000001', 'Trata@123')}"}


FAKE_EP = f"https://fcm.googleapis.com/fcm/send/TEST_fake_{int(time.time())}"


# ── Alerts: RBAC ──
@pytest.mark.parametrize("method,path,body", [
    ("get", "/admin/alerts/public-key", None), ("get", "/admin/alerts/devices", None),
    ("post", "/admin/alerts/subscribe", {"subscription": {"endpoint": "https://x.y/z", "keys": {"p256dh": "a", "auth": "b"}}}),
    ("put", "/admin/alerts/prefs", {"endpoint": "https://x"}), ("post", "/admin/alerts/unsubscribe", {"endpoint": "https://x"}),
    ("post", "/admin/alerts/test", {}), ("get", "/admin/digest/latest", None), ("post", "/admin/digest/generate", {"day": "today"}),
    ("get", "/admin/activity-log/record/abcd1234", None), ("get", "/admin/activity-log/health", None)])
def test_sales_manager_forbidden(S, method, path, body):
    r = getattr(requests, method)(f"{API}{path}", headers=S, json=body, timeout=60)
    assert r.status_code == 403, f"{path} -> {r.status_code} {r.text[:200]}"


def test_public_key(M):
    r = requests.get(f"{API}/admin/alerts/public-key", headers=M, timeout=30)
    assert r.status_code == 200
    assert isinstance(r.json()["public_key"], str) and len(r.json()["public_key"]) > 40


@pytest.mark.parametrize("sub", [
    {"endpoint": "http://fcm.googleapis.com/x", "keys": {"p256dh": "a", "auth": "b"}},
    {"endpoint": "https://fcm.googleapis.com/x"},
    {"endpoint": "https://fcm.googleapis.com/x", "keys": {"auth": "b"}}])
def test_subscribe_invalid_400(M, sub):
    r = requests.post(f"{API}/admin/alerts/subscribe", headers=M, json={"subscription": sub}, timeout=30)
    assert r.status_code == 400, r.text


def test_subscribe_missing_auth_key(M):
    """keys.auth missing should be 400, not 500."""
    r = requests.post(f"{API}/admin/alerts/subscribe", headers=M,
                      json={"subscription": {"endpoint": "https://fcm.googleapis.com/TEST_noauth", "keys": {"p256dh": "abc"}}}, timeout=30)
    assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"


def test_subscribe_prefs_unsubscribe_flow(M):
    ep = FAKE_EP + "_flow"
    r = requests.post(f"{API}/admin/alerts/subscribe", headers=M, json={
        "subscription": {"endpoint": ep, "keys": fake_keys()}, "prefs": {"kyc": True, "signup": False, "order": True, "sos": True}}, timeout=30)
    assert r.status_code == 200 and r.json()["prefs"]["signup"] is False
    d = requests.get(f"{API}/admin/alerts/devices", headers=M, params={"endpoint": ep}, timeout=30).json()
    assert d["this_device"] is True and d["devices"] >= 1 and d["prefs"]["signup"] is False
    r = requests.put(f"{API}/admin/alerts/prefs", headers=M, json={"endpoint": ep, "prefs": {"kyc": False, "signup": True, "order": True, "sos": True}}, timeout=30)
    assert r.status_code == 200
    d = requests.get(f"{API}/admin/alerts/devices", headers=M, params={"endpoint": ep}, timeout=30).json()
    assert d["prefs"] == {"kyc": False, "signup": True, "order": True, "sos": True}
    r = requests.post(f"{API}/admin/alerts/unsubscribe", headers=M, json={"endpoint": ep}, timeout=30)
    assert r.status_code == 200
    d = requests.get(f"{API}/admin/alerts/devices", headers=M, params={"endpoint": ep}, timeout=30).json()
    assert d["this_device"] is False
    r = requests.put(f"{API}/admin/alerts/prefs", headers=M, json={"endpoint": ep, "prefs": {}}, timeout=30)
    assert r.status_code == 404


def test_fake_fcm_removed_after_test(M):
    ep = FAKE_EP + "_dead"
    assert requests.post(f"{API}/admin/alerts/subscribe", headers=M, json={"subscription": {"endpoint": ep, "keys": fake_keys()}}, timeout=30).status_code == 200
    r = requests.post(f"{API}/admin/alerts/test", headers=M, timeout=90)
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["sent"], int)
    d = requests.get(f"{API}/admin/alerts/devices", headers=M, params={"endpoint": ep}, timeout=30).json()
    if d["this_device"]:
        requests.post(f"{API}/admin/alerts/unsubscribe", headers=M, json={"endpoint": ep}, timeout=30)
    assert d["this_device"] is False, "dead FCM subscription not auto-removed"


def test_test_push_with_garbage_keys(M):
    """Malformed keys stored -> /test should not 500."""
    ep = FAKE_EP + "_garbage"
    requests.post(f"{API}/admin/alerts/subscribe", headers=M, json={"subscription": {"endpoint": ep, "keys": {"p256dh": "garbage", "auth": "x"}}}, timeout=30)
    try:
        r = requests.post(f"{API}/admin/alerts/test", headers=M, timeout=90)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    finally:
        requests.post(f"{API}/admin/alerts/unsubscribe", headers=M, json={"endpoint": ep}, timeout=30)


# ── Digest ──
def test_digest_generate_today(M):
    r = requests.post(f"{API}/admin/digest/generate", headers=M, json={"day": "today"}, timeout=120)
    assert r.status_code == 200, r.text
    d = r.json()["digest"]
    assert d["day"] == "today"
    s = d["stats"]
    assert set(s["highlights"]) == {"signups", "doctor_appointments", "pathlab_bookings", "diagnostics_bookings", "pharmacy_orders", "sos", "kyc"}
    assert isinstance(s["patient_top"], list) and isinstance(s["provider_top"], list)
    if s["changes"]:
        assert d["ai"] is True and len(d["text"]) > 20, "AI text missing"
    lt = requests.get(f"{API}/admin/digest/latest", headers=M, timeout=30).json()["digest"]
    assert lt["day"] == "yesterday" or lt["date"] == d["date"]  # morning (yesterday) summary is preferred


def test_cron_digest_auth():
    assert requests.post(f"{API}/cron/admin-digest", timeout=30).status_code == 401
    assert requests.post(f"{API}/cron/admin-digest", headers={"Authorization": "Bearer wrong"}, timeout=30).status_code == 401
    r = requests.post(f"{API}/cron/admin-digest", headers={"Authorization": f"Bearer {CRON}"}, timeout=30)
    assert r.status_code == 200 and r.json()["accepted"] is True


# ── Record history ──
def test_record_history_patient(M):
    pts = requests.get(f"{API}/admin/patients", headers=M, timeout=60).json()
    items = pts if isinstance(pts, list) else pts.get("items") or pts.get("patients") or []
    assert items, "no patients"
    for p in items[:10]:
        uid = p.get("user_id") or p.get("id")
        r = requests.get(f"{API}/admin/activity-log/record/{uid}", headers=M, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert {"items", "linked_ids", "more", "recording_since"} <= set(d)
        ids = [i["id"] for i in d["items"]]
        assert ids == sorted(ids), "not oldest-first"
        if len(ids) >= 2:
            r2 = requests.get(f"{API}/admin/activity-log/record/{uid}", headers=M, params={"after_id": ids[0], "limit": 1}, timeout=60).json()
            assert r2["items"][0]["id"] == ids[1] and r2["more"] is True
            print("patient with history", uid, len(ids))
            return
    print("no patient among first 10 had >=2 history items")


def test_record_history_provider_pagination(M):
    rid = "933eee2e-315a-430b-9a58-284ae5161863"  # TEST Owner 91779969 (ambulance provider in /admin/onboarding)
    d = requests.get(f"{API}/admin/activity-log/record/{rid}", headers=M, timeout=60).json()
    ids = [i["id"] for i in d["items"]]
    if len(ids) < 2:
        pytest.skip("audit log was reset")
    assert ids == sorted(ids) and d["items"][0]["table_name"] == "users" and d["linked_ids"] >= 2
    r = requests.get(f"{API}/admin/activity-log/record/{rid}", headers=M, params={"after_id": ids[0], "limit": 1}, timeout=60).json()
    assert [i["id"] for i in r["items"]] == [ids[1]] and r["more"] is True


def test_record_history_unknown_id(M):
    r = requests.get(f"{API}/admin/activity-log/record/TEST_nonexistent_zz", headers=M, timeout=60)
    assert r.status_code == 200 and r.json()["items"] == []


# ── Regression ──
def test_audit_health(M):
    r = requests.get(f"{API}/admin/activity-log/health", headers=M, timeout=90)
    assert r.status_code == 200
    d = r.json()
    assert d["auto_attach"] is True and len(d["covered"]) > 200


@pytest.mark.parametrize("scope", ["patient", "provider"])
def test_scope_feed(M, scope):
    r = requests.get(f"{API}/admin/activity-log", headers=M, params={"scope": scope, "limit": 10}, timeout=60)
    assert r.status_code == 200 and isinstance(r.json()["items"], list)
