"""
Backend tests for Sales Agent features (iteration 3):
- Auth 3-step flow for all 4 roles
- /api/agent/dashboard, /api/agent/leads, /api/agent/leads/map
- /api/agent/quick-log (with gps for site_visit + auto-advance + follow-up task)
- /api/agent/digest (Claude AI digest, graceful fallback)
- /api/agent/targets, /api/agent/leaderboard
- Role-scoping (403s)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

# ---------- auth helpers ----------

def _auth(phone: str, password: str = "Trata@123", first_time_password: str | None = None):
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, f"send-otp failed for {phone}: {r.status_code} {r.text}"
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456"}, timeout=15)
    assert r.status_code == 200, f"verify-otp failed for {phone}: {r.status_code} {r.text}"
    body = r.json()
    temp = body["temp_token"]
    needs_setup = body.get("needs_password_setup", False)
    s.headers["Authorization"] = f"Bearer {temp}"
    if needs_setup:
        pw = first_time_password or password
        r = s.post(f"{API}/auth/set-password", json={"password": pw}, timeout=15)
        assert r.status_code == 200, f"set-password failed for {phone}: {r.status_code} {r.text}"
    else:
        r = s.post(f"{API}/auth/login-password", json={"password": password}, timeout=15)
        assert r.status_code == 200, f"login-password failed for {phone}: {r.status_code} {r.text}"
    body2 = r.json()
    access = body2.get("token") or body2.get("access_token")
    assert access, f"no token in response for {phone}: {body2}"
    s.headers["Authorization"] = f"Bearer {access}"
    return s, body2.get("user", {})


@pytest.fixture(scope="module")
def admin_client():
    s, u = _auth("9873117605", password="Master@123", first_time_password="Master@123")
    return s, u


@pytest.fixture(scope="module")
def manager_client():
    s, u = _auth("9000000001", password="Trata@123")
    return s, u


@pytest.fixture(scope="module")
def rep_client():
    s, u = _auth("9000000002", password="Trata@123")
    return s, u


@pytest.fixture(scope="module")
def provider_client():
    s, u = _auth("9000020003", password="Trata@123")
    return s, u


# ---------- auth flow sanity ----------

class TestAuth:
    def test_admin_logged_in(self, admin_client):
        _, u = admin_client
        assert u.get("role") in ("admin",) or u.get("is_master_admin") is True

    def test_rep_role(self, rep_client):
        _, u = rep_client
        assert u.get("role") == "sales_rep"

    def test_manager_role(self, manager_client):
        _, u = manager_client
        assert u.get("role") == "manager"

    def test_provider_role(self, provider_client):
        _, u = provider_client
        assert u.get("role") == "provider_owner"


# ---------- /api/agent/dashboard ----------

class TestDashboard:
    def test_rep_dashboard_shape(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/dashboard", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        for k in ("kpis", "by_stage", "today_tasks", "hot_leads", "stale_leads_list"):
            assert k in d, f"missing {k} in dashboard"
        assert isinstance(d["kpis"], dict)
        assert "total_leads" in d["kpis"]
        assert isinstance(d["hot_leads"], list)
        assert isinstance(d["stale_leads_list"], list)

    def test_provider_forbidden(self, provider_client):
        s, _ = provider_client
        r = s.get(f"{API}/agent/dashboard", timeout=15)
        assert r.status_code == 403


# ---------- /api/agent/leads ----------

class TestLeads:
    def test_list_basic(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leads", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "items" in d and "total" in d
        assert isinstance(d["items"], list)
        assert isinstance(d["total"], int)

    def test_filter_stage(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leads", params={"stage": "lead"}, timeout=15)
        assert r.status_code == 200
        for c in r.json()["items"]:
            assert c.get("pipeline_stage") == "lead"

    def test_filter_provider_type(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leads", params={"provider_type": "ambulance"}, timeout=15)
        assert r.status_code == 200
        for c in r.json()["items"]:
            assert c.get("type") == "ambulance"

    def test_filter_touched_today(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leads", params={"last_touched": "today"}, timeout=15)
        assert r.status_code == 200

    def test_filter_stale(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leads", params={"last_touched": "stale"}, timeout=15)
        assert r.status_code == 200

    def test_search_q(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leads", params={"q": "a"}, timeout=15)
        assert r.status_code == 200

    def test_provider_forbidden(self, provider_client):
        s, _ = provider_client
        r = s.get(f"{API}/agent/leads", timeout=15)
        assert r.status_code == 403


# ---------- /api/agent/leads/map ----------

class TestLeadsMap:
    def test_map(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leads/map", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert "leads" in d and "center" in d
        assert isinstance(d["leads"], list)


# ---------- /api/agent/quick-log ----------

class TestQuickLog:
    def _first_lead(self, s):
        r = s.get(f"{API}/agent/leads", params={"limit": 5}, timeout=15)
        assert r.status_code == 200
        items = r.json()["items"]
        assert items, "no leads available for sales rep — seed missing?"
        return items[0]

    def test_quick_log_with_gps_and_advance(self, rep_client):
        s, _ = rep_client
        lead = self._first_lead(s)
        payload = {
            "contact_id": lead["id"],
            "activity_type": "kyc_collection",
            "outcome": "kyc_collected",
            "notes": "TEST_ collected KYC docs",
            "gps": {"lat": 12.97, "lng": 77.59},
            "next_action_at": "2026-02-15T10:00:00Z",
        }
        r = s.post(f"{API}/agent/quick-log", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["success"] is True
        assert d["activity"]["subtype"] == "kyc_collection"
        # gps persisted on activity
        assert d["activity"].get("gps") == {"lat": 12.97, "lng": 77.59}
        # auto-advanced
        assert d.get("advanced_to_stage") == "kyc_submitted"
        # follow-up task created
        assert d.get("follow_up_task") is not None
        assert d["follow_up_task"]["contact_id"] == lead["id"]

        # GET contact to verify stage persisted
        r2 = s.get(f"{API}/contacts/{lead['id']}", timeout=15)
        assert r2.status_code == 200
        body2 = r2.json()
        contact_obj = body2.get("contact", body2)
        assert contact_obj.get("pipeline_stage") == "kyc_submitted"

    def test_quick_log_site_visit_gps(self, rep_client):
        s, _ = rep_client
        lead = self._first_lead(s)
        payload = {
            "contact_id": lead["id"],
            "activity_type": "site_visit",
            "outcome": "demo_completed",
            "notes": "TEST_ site visit",
            "gps": {"lat": 19.07, "lng": 72.87},
        }
        r = s.post(f"{API}/agent/quick-log", json=payload, timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["activity"]["subtype"] == "site_visit"
        assert d["activity"].get("gps") == {"lat": 19.07, "lng": 72.87}

    def test_quick_log_provider_forbidden(self, provider_client):
        s, _ = provider_client
        r = s.post(f"{API}/agent/quick-log", json={
            "contact_id": "x", "activity_type": "cold_call", "outcome": "no_answer"
        }, timeout=15)
        assert r.status_code == 403


# ---------- /api/agent/digest ----------

class TestDigest:
    def test_digest_rep(self, rep_client):
        s, _ = rep_client
        r = s.post(f"{API}/agent/digest", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "success" in d
        assert "text" in d and isinstance(d["text"], str) and d["text"].strip()
        assert "stats" in d
        for k in ("activities", "onboarded", "tasks_done", "by_type"):
            assert k in d["stats"]

    def test_digest_provider_forbidden(self, provider_client):
        s, _ = provider_client
        r = s.post(f"{API}/agent/digest", timeout=15)
        assert r.status_code == 403


# ---------- /api/agent/targets ----------

class TestTargets:
    def test_targets_rep(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/targets", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "target" in d and "actual" in d and "month_start" in d
        for k in ("calls", "meetings", "kyc", "onboarded"):
            assert k in d["actual"]


# ---------- /api/agent/leaderboard ----------

class TestLeaderboard:
    def test_leaderboard_admin(self, admin_client):
        s, _ = admin_client
        r = s.get(f"{API}/agent/leaderboard", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d and isinstance(d["items"], list)
        if d["items"]:
            row = d["items"][0]
            for k in ("agent_id", "name", "calls", "meetings", "onboarded", "leads"):
                assert k in row

    def test_leaderboard_manager_allowed(self, manager_client):
        s, _ = manager_client
        r = s.get(f"{API}/agent/leaderboard", timeout=15)
        assert r.status_code == 200

    def test_leaderboard_rep_forbidden(self, rep_client):
        s, _ = rep_client
        r = s.get(f"{API}/agent/leaderboard", timeout=15)
        assert r.status_code == 403
