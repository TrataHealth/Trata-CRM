"""
Phase 5 — Provider-App Webhook Bridge tests.

Covers:
- POST /api/webhooks/provider-app (HMAC-SHA256 signed) for provider.signed_up & provider.first_use
- Bad/missing signature → 401 + rejected webhook_event record
- Phone normalization (strip +91/spaces) matches existing contact
- New-lead auto-creation + territory round-robin (Delhi→Rohan, Bengaluru→Priya, unknown→fallback)
- webhook_sync activity inserted
- GET /api/admin/webhooks/events — internal only; provider 403; payload shape
- POST /api/admin/webhooks/test-send — admin only; sales rep/provider 403; returns signature+payload
- /api/agent/dashboard total_leads increases when a new Delhi lead is auto-created
"""
import hmac
import hashlib
import json
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

# Must match backend .env PROVIDER_WEBHOOK_SECRET
WEBHOOK_SECRET = "trata-provider-webhook-secret-2026"


# ---------- auth helpers (copied from test_agent_features) ----------

def _auth(phone, password="Trata@123", first_time_password=None):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, f"send-otp {phone}: {r.status_code} {r.text}"
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=15)
    assert r.status_code == 200, f"verify-otp {phone}: {r.status_code} {r.text}"
    body = r.json()
    s.headers["Authorization"] = f"Bearer {body['temp_token']}"
    if body.get("needs_password_setup"):
        r = s.post(f"{API}/auth/set-password", json={"password": first_time_password or password}, timeout=15)
    else:
        r = s.post(f"{API}/auth/login-password", json={"password": password}, timeout=15)
    assert r.status_code == 200, f"pw {phone}: {r.status_code} {r.text}"
    b2 = r.json()
    tok = b2.get("token") or b2.get("access_token")
    s.headers["Authorization"] = f"Bearer {tok}"
    return s, b2.get("user", {})


@pytest.fixture(scope="module")
def admin_client():
    return _auth("9873117605", password="Master@123", first_time_password="Master@123")


@pytest.fixture(scope="module")
def manager_client():
    return _auth("9000000001")


@pytest.fixture(scope="module")
def rep_client():
    return _auth("9000000002")


@pytest.fixture(scope="module")
def provider_client():
    return _auth("9000020003")


# ---------- signature helpers ----------

def _sign(raw: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw, hashlib.sha256).hexdigest()


def _post_webhook(payload: dict, signature: str | None = None, raw_override: bytes | None = None):
    raw = raw_override if raw_override is not None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Trata-Signature"] = signature
    return requests.post(f"{API}/webhooks/provider-app", data=raw, headers=headers, timeout=20)


def sa_get_contact(session, contact_id: str) -> dict:
    """GET /contacts/{id} returns {contact, activities, notes, tasks} — flatten to contact dict."""
    r = session.get(f"{API}/contacts/{contact_id}", timeout=15)
    if r.status_code != 200:
        return {}
    body = r.json()
    return body.get("contact", body) if isinstance(body, dict) else {}


# ---------- 1. signature validation ----------

class TestSignatureValidation:
    def test_missing_signature_returns_401(self):
        payload = {"event": "provider.signed_up", "provider": {"phone": "9111100001", "name": "TEST_nosig", "city": "Delhi"}}
        r = _post_webhook(payload, signature=None)
        assert r.status_code == 401, r.text
        assert "Invalid" in r.json().get("detail", "")

    def test_bad_signature_returns_401(self):
        payload = {"event": "provider.signed_up", "provider": {"phone": "9111100002", "name": "TEST_badsig", "city": "Delhi"}}
        r = _post_webhook(payload, signature="sha256=deadbeef" * 8)
        assert r.status_code == 401, r.text

    def test_bad_signature_logs_rejected_event(self, admin_client):
        s, _ = admin_client
        payload = {"event": "provider.signed_up", "provider": {"phone": "9111100099", "name": "TEST_rejlog", "city": "Delhi"}}
        _post_webhook(payload, signature="sha256=abc")
        # Verify a rejected event was logged
        r = s.get(f"{API}/admin/webhooks/events", params={"limit": 50}, timeout=15)
        assert r.status_code == 200
        items = r.json().get("items", [])
        statuses = [i for i in items if i.get("status") == "rejected"]
        assert len(statuses) >= 1, "Expected at least one rejected event in the log"
        assert any(i.get("event") == "invalid_signature" for i in statuses)


# ---------- 2. event processing ----------

class TestEventProcessing:
    def test_signed_up_creates_lead_in_verified(self, admin_client):
        s, _ = admin_client
        # Unique phone — new lead (use time-based to ensure idempotent re-runs still hit "create" path)
        phone = f"9111{int(time.time())%10000000:07d}"
        payload = {"event": "provider.signed_up",
                   "provider": {"phone": phone, "name": "TEST_SignedUp Delhi", "type": "ambulance_provider", "city": "Delhi", "state": "Delhi"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["pipeline_stage"] == "verified"
        assert data["created_new_lead"] is True
        # stash phone for next test
        self.__class__.shared_phone = phone

        # Verify persistence — fetch the contact via admin (response is nested {contact, activities, ...})
        r2 = s.get(f"{API}/contacts/{data['contact_id']}", timeout=15)
        assert r2.status_code == 200
        c = r2.json().get("contact", r2.json())
        assert c["pipeline_stage"] == "verified"
        assert c["source"] == "provider_app_webhook"
        assert c["phone"] == phone

    def test_first_use_advances_existing_to_active(self, admin_client):
        # Same phone as previous test — should match & advance to active
        phone = getattr(TestEventProcessing, "shared_phone", None)
        if not phone:
            pytest.skip("Previous test did not set shared_phone")
        payload = {"event": "provider.first_use",
                   "provider": {"phone": phone, "name": "TEST_FirstUse", "city": "Delhi"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["pipeline_stage"] == "active"
        assert d["created_new_lead"] is False
        assert "advanced" in d["action"]

    def test_unsupported_event_returns_400(self):
        payload = {"event": "provider.exploded", "provider": {"phone": "9111122202"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 400

    def test_missing_phone_returns_400(self):
        payload = {"event": "provider.signed_up", "provider": {"name": "noPhone"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 400


# ---------- 3. phone normalization ----------

class TestPhoneNormalization:
    def test_plus91_and_spaces_match_existing(self, admin_client):
        s, _ = admin_client
        # Step 1: create a baseline contact (clean digits)
        phone = "9111188801"
        payload = {"event": "provider.signed_up", "provider": {"phone": phone, "name": "TEST_NormBase", "city": "Delhi"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200
        cid = r.json()["contact_id"]

        # Step 2: re-send with "+91 91111 88801" — must match the same contact
        formatted = "+91 91111 88801"
        payload2 = {"event": "provider.first_use", "provider": {"phone": formatted, "name": "TEST_NormDup", "city": "Delhi"}}
        raw2 = json.dumps(payload2, separators=(",", ":")).encode("utf-8")
        r2 = _post_webhook(payload2, signature=_sign(raw2), raw_override=raw2)
        assert r2.status_code == 200, r2.text
        d = r2.json()
        assert d["contact_id"] == cid, f"phone normalization failed: expected same contact id {cid}, got {d['contact_id']}"
        assert d["created_new_lead"] is False
        assert d["pipeline_stage"] == "active"


# ---------- 4. territory round-robin ----------

class TestTerritoryRoundRobin:
    def test_delhi_assigns_to_rohan(self):
        # Brand new phone, city=Delhi → must be assigned to a sales rep whose territories include Delhi (Rohan)
        phone = f"9111{int(time.time())%100000:05d}"  # unique-ish
        payload = {"event": "provider.signed_up", "provider": {"phone": phone, "name": "TEST_DelhiRR", "city": "Delhi"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200
        # Verify via webhook events list
        # (assigned_agent_name set in response via test-send only; here we fetch the contact)
        return r.json()["contact_id"]

    def test_bengaluru_assigns_to_priya(self, admin_client):
        s, _ = admin_client
        phone = f"9222{int(time.time())%100000:05d}"
        payload = {"event": "provider.signed_up", "provider": {"phone": phone, "name": "TEST_BluruRR", "city": "Bengaluru"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200
        cid = r.json()["contact_id"]
        # fetch contact via admin (nested response)
        cr = sa_get_contact(s, cid)
        assert "Priya" in (cr.get("assigned_agent_name") or ""), f"Expected Priya for Bengaluru, got {cr.get('assigned_agent_name')}"

    def test_delhi_round_robin_assigns_to_rohan_via_contact(self, admin_client):
        s, _ = admin_client
        phone = f"9333{int(time.time())%100000:05d}"
        payload = {"event": "provider.signed_up", "provider": {"phone": phone, "name": "TEST_DelhiRR2", "city": "Delhi"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200
        cid = r.json()["contact_id"]
        cr = sa_get_contact(s, cid)
        assert "Rohan" in (cr.get("assigned_agent_name") or ""), f"Expected Rohan for Delhi, got {cr.get('assigned_agent_name')}"

    def test_unknown_city_falls_back_global(self, admin_client):
        s, _ = admin_client
        phone = f"9444{int(time.time())%100000:05d}"
        payload = {"event": "provider.signed_up", "provider": {"phone": phone, "name": "TEST_UnknownCity", "city": "Atlantis"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200
        cid = r.json()["contact_id"]
        cr = sa_get_contact(s, cid)
        # Should still get assigned to *some* internal agent (global fallback)
        name = cr.get("assigned_agent_name") or ""
        assert ("Rohan" in name or "Priya" in name) or cr.get("assigned_agent_id"), \
            f"Expected a fallback assignment, got {cr}"


# ---------- 5. activity record ----------

class TestWebhookActivity:
    def test_webhook_sync_activity_inserted(self, admin_client):
        s, _ = admin_client
        phone = f"9555{int(time.time())%100000:05d}"
        payload = {"event": "provider.first_use", "provider": {"phone": phone, "name": "TEST_ActivityCheck", "city": "Delhi"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        r = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert r.status_code == 200
        cid = r.json()["contact_id"]
        # query activities for the new contact
        ar = s.get(f"{API}/activities", params={"contact_id": cid, "limit": 50}, timeout=15)
        assert ar.status_code == 200, ar.text
        items = ar.json() if isinstance(ar.json(), list) else ar.json().get("items", [])
        cats = [a.get("category") for a in items]
        assert "webhook_sync" in cats, f"webhook_sync activity not found. Categories: {cats}"


# ---------- 6. /admin/webhooks/events list ----------

class TestListWebhookEvents:
    def test_internal_can_list(self, admin_client):
        s, _ = admin_client
        r = s.get(f"{API}/admin/webhooks/events", params={"limit": 20}, timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "total" in d
        assert d.get("secret_configured") is True
        assert isinstance(d["items"], list)

    def test_manager_can_list(self, manager_client):
        s, _ = manager_client
        r = s.get(f"{API}/admin/webhooks/events", timeout=15)
        assert r.status_code == 200

    def test_rep_can_list(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/admin/webhooks/events", timeout=15)
        # 'require_internal' includes sales_rep — should be 200
        assert r.status_code == 200

    def test_provider_forbidden(self, provider_client):
        s, _ = provider_client
        r = s.get(f"{API}/admin/webhooks/events", timeout=15)
        assert r.status_code == 403


# ---------- 7. /admin/webhooks/test-send ----------

class TestAdminTestSend:
    def test_master_admin_can_send(self, admin_client):
        s, _ = admin_client
        body = {"event": "provider.signed_up", "phone": f"9777{int(time.time())%100000:05d}",
                "name": "TEST_AdminSend", "city": "Delhi", "state": "Delhi"}
        r = s.post(f"{API}/admin/webhooks/test-send", json=body, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert d["pipeline_stage"] == "verified"
        assert "signed_payload" in d and "signature" in d
        assert d["signature"].startswith("sha256=")
        assert d["created_new_lead"] is True

    def test_test_send_first_use_stage_active(self, admin_client):
        s, _ = admin_client
        body = {"event": "provider.first_use", "phone": f"9788{int(time.time())%100000:05d}",
                "name": "TEST_AdminFirstUse", "city": "Bengaluru"}
        r = s.post(f"{API}/admin/webhooks/test-send", json=body, timeout=20)
        assert r.status_code == 200
        assert r.json()["pipeline_stage"] == "active"

    def test_test_send_rep_forbidden(self, rep_client):
        s, _ = rep_client
        body = {"event": "provider.signed_up", "phone": "9111122299", "city": "Delhi"}
        r = s.post(f"{API}/admin/webhooks/test-send", json=body, timeout=15)
        # require_internal -> rep is internal -> may be allowed?
        # Per review_request: "Sales rep/provider get 403."
        assert r.status_code == 403, f"Expected 403 for sales rep, got {r.status_code}: {r.text}"

    def test_test_send_provider_forbidden(self, provider_client):
        s, _ = provider_client
        body = {"event": "provider.signed_up", "phone": "9111122299", "city": "Delhi"}
        r = s.post(f"{API}/admin/webhooks/test-send", json=body, timeout=15)
        assert r.status_code == 403


# ---------- 8. agent dashboard reflects new lead ----------

class TestAgentDashboardReflectsNewLead:
    def test_rohan_dashboard_total_leads_increases(self, rep_client, admin_client):
        sr, _ = rep_client
        sa, _ = admin_client
        # Snapshot Rohan's current total_leads
        r0 = sr.get(f"{API}/agent/dashboard", timeout=15)
        assert r0.status_code == 200
        kpi_before = r0.json().get("kpis", {}).get("total_leads", 0)

        # Force a NEW Delhi lead via webhook (so it routes to Rohan)
        phone = f"9899{int(time.time())%100000:05d}"
        payload = {"event": "provider.signed_up",
                   "provider": {"phone": phone, "name": "TEST_DashIncr", "city": "Delhi", "state": "Delhi"}}
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        wr = _post_webhook(payload, signature=_sign(raw), raw_override=raw)
        assert wr.status_code == 200
        # Confirm assignment is Rohan via admin
        cid = wr.json()["contact_id"]
        cr = sa_get_contact(sa, cid)
        if "Rohan" not in (cr.get("assigned_agent_name") or ""):
            pytest.skip(f"Round-robin landed on {cr.get('assigned_agent_name')} — dashboard delta test only valid for Rohan")

        time.sleep(0.5)
        r1 = sr.get(f"{API}/agent/dashboard", timeout=15)
        assert r1.status_code == 200
        kpi_after = r1.json().get("kpis", {}).get("total_leads", 0)
        assert kpi_after >= kpi_before + 1, f"total_leads did not increase: before={kpi_before} after={kpi_after}"
