"""Team hierarchy tests for the Team detail / org chart feature."""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"


# ---------- helpers ----------
def _login(phone: str, password: str) -> str:
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{API}/auth/send-otp", json={"phone": phone})
    assert r.status_code == 200, r.text
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456"})
    assert r.status_code == 200, r.text
    temp = r.json()["temp_token"]
    r = s.post(f"{API}/auth/login-password", json={"password": password},
               headers={"Authorization": f"Bearer {temp}"})
    assert r.status_code == 200, f"login failed for {phone}: {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def admin_token():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def admin(admin_token):
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def rep_token():
    return _login("9000000002", "Trata@123")


@pytest.fixture(scope="module")
def created_members(admin):
    """Build a clean test hierarchy: NM -> RM -> ZM -> AM, then yield ids and delete."""
    ids = {}
    # Find master admin id from /team list
    r = admin.get(f"{API}/team")
    assert r.status_code == 200
    items = r.json()["items"]
    master = next(m for m in items if m.get("is_master_admin"))
    ids["master"] = master["id"]

    # National Manager (no reports_to required, but admin can be parent)
    r = admin.post(f"{API}/team", json={
        "name": "TEST_NM", "phone": "9911100001", "role": "national_manager",
        "reports_to": master["id"], "territories": ["India"]
    })
    assert r.status_code == 200, r.text
    ids["nm"] = r.json()["member"]["id"]

    r = admin.post(f"{API}/team", json={
        "name": "TEST_RM", "phone": "9911100002", "role": "regional_manager",
        "reports_to": ids["nm"], "territories": ["North"]
    })
    assert r.status_code == 200, r.text
    ids["rm"] = r.json()["member"]["id"]

    r = admin.post(f"{API}/team", json={
        "name": "TEST_ZM", "phone": "9911100003", "role": "zonal_manager",
        "reports_to": ids["rm"]
    })
    assert r.status_code == 200, r.text
    ids["zm"] = r.json()["member"]["id"]

    r = admin.post(f"{API}/team", json={
        "name": "TEST_AM", "phone": "9911100004", "role": "area_manager",
        "reports_to": ids["zm"]
    })
    assert r.status_code == 200, r.text
    ids["am"] = r.json()["member"]["id"]

    yield ids

    # Cleanup
    for k in ("am", "zm", "rm", "nm"):
        try:
            admin.delete(f"{API}/team/{ids[k]}")
        except Exception:
            pass


# ---------- GET /api/team enrichment ----------
class TestTeamList:
    def test_team_list_enriched(self, admin):
        r = admin.get(f"{API}/team")
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0
        sample = items[0]
        for key in ("id", "name", "role", "is_master_admin", "reports_count", "territories"):
            assert key in sample, f"missing {key}"

    def test_legacy_manager_migrated(self, admin):
        """Priya was a legacy 'manager' — expect 'regional_manager' now."""
        r = admin.get(f"{API}/team")
        items = r.json()["items"]
        priya = next((m for m in items if m.get("phone") == "9000000001"), None)
        if priya:
            assert priya["role"] == "regional_manager", f"got {priya['role']}"


# ---------- POST /api/team strict hierarchy validation ----------
class TestCreateValidation:
    def test_sales_rep_to_regional_manager_fails(self, admin, created_members):
        r = admin.post(f"{API}/team", json={
            "name": "TEST_BAD_REP", "phone": "9911199001",
            "role": "sales_rep", "reports_to": created_members["rm"]
        })
        assert r.status_code == 400
        assert "area" in r.json()["detail"].lower()

    def test_sales_rep_to_area_manager_ok(self, admin, created_members):
        r = admin.post(f"{API}/team", json={
            "name": "TEST_REP", "phone": "9911199002",
            "role": "sales_rep", "reports_to": created_members["am"]
        })
        assert r.status_code == 200, r.text
        member = r.json()["member"]
        assert member["role"] == "sales_rep"
        assert member["reports_to"] == created_members["am"]
        # Cleanup
        admin.delete(f"{API}/team/{member['id']}")

    def test_national_manager_to_master_admin_ok(self, admin, created_members):
        r = admin.post(f"{API}/team", json={
            "name": "TEST_NM2", "phone": "9911199003",
            "role": "national_manager", "reports_to": created_members["master"]
        })
        assert r.status_code == 200, r.text
        admin.delete(f"{API}/team/{r.json()['member']['id']}")

    def test_national_manager_to_nm_fails(self, admin, created_members):
        r = admin.post(f"{API}/team", json={
            "name": "TEST_NM_BAD", "phone": "9911199004",
            "role": "national_manager", "reports_to": created_members["nm"]
        })
        assert r.status_code == 400


# ---------- PATCH /api/team/{id} ----------
class TestPatchValidation:
    def test_self_loop_rejected(self, admin, created_members):
        r = admin.patch(f"{API}/team/{created_members['rm']}",
                        json={"reports_to": created_members["rm"]})
        assert r.status_code == 400
        assert "themselves" in r.json()["detail"].lower() or "cycle" in r.json()["detail"].lower()

    def test_cycle_detection(self, admin, created_members):
        # Make NM a sales_rep reporting to AM (AM is valid parent for sales_rep tier-wise).
        # But AM transitively reports back to NM → must trigger cycle detection.
        r = admin.patch(f"{API}/team/{created_members['nm']}",
                        json={"role": "sales_rep", "reports_to": created_members["am"]})
        assert r.status_code == 400
        assert "cycle" in r.json()["detail"].lower()

    def test_wrong_tier_rejected(self, admin, created_members):
        # Try to set ZM to report to NM (skipping RM)
        r = admin.patch(f"{API}/team/{created_members['zm']}",
                        json={"reports_to": created_members["nm"]})
        assert r.status_code == 400

    def test_patch_name_persists(self, admin, created_members):
        r = admin.patch(f"{API}/team/{created_members['am']}",
                        json={"name": "TEST_AM_Renamed", "territories": ["West", "Central"]})
        assert r.status_code == 200, r.text
        r = admin.get(f"{API}/team/{created_members['am']}")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "TEST_AM_Renamed"
        assert set(body["territories"]) == {"West", "Central"}


# ---------- GET /api/team/{id} detail ----------
class TestMemberDetail:
    def test_chain_built_bottom_up(self, admin, created_members):
        # Attach a sales rep to AM
        r = admin.post(f"{API}/team", json={
            "name": "TEST_REP_CHAIN", "phone": "9911199010",
            "role": "sales_rep", "reports_to": created_members["am"]
        })
        rep_id = r.json()["member"]["id"]
        try:
            r = admin.get(f"{API}/team/{rep_id}")
            assert r.status_code == 200
            body = r.json()
            chain_ids = [c["id"] for c in body["reports_chain"]]
            # Expect AM -> ZM -> RM -> NM -> master
            assert chain_ids[:4] == [created_members["am"], created_members["zm"],
                                      created_members["rm"], created_members["nm"]]
            assert body["performance"]["scope"] == "self"
            assert isinstance(body["direct_reports"], list)
            assert isinstance(body["feedback"], list)
            assert "providers_handled" in body
        finally:
            admin.delete(f"{API}/team/{rep_id}")

    def test_manager_scope_team_rollup(self, admin, created_members):
        r = admin.get(f"{API}/team/{created_members['nm']}")
        assert r.status_code == 200
        body = r.json()
        assert body["performance"]["scope"] == "team_rollup"
        # NM + RM + ZM + AM = 4
        assert body["performance"]["team_size"] >= 4


# ---------- Feedback ----------
class TestFeedback:
    def test_admin_creates_feedback(self, admin, created_members):
        r = admin.post(f"{API}/team/{created_members['rm']}/feedback",
                       json={"rating": 4, "note": "TEST_FB_great work"})
        assert r.status_code == 200, r.text
        fb = r.json()["feedback"]
        assert fb["rating"] == 4
        assert fb["author_role"] == "admin"
        # Author can delete
        d = admin.delete(f"{API}/team/{created_members['rm']}/feedback/{fb['id']}")
        assert d.status_code == 200

    def test_invalid_rating_rejected(self, admin, created_members):
        r = admin.post(f"{API}/team/{created_members['rm']}/feedback",
                       json={"rating": 9, "note": "bad rating"})
        assert r.status_code == 400

    def test_empty_note_rejected(self, admin, created_members):
        r = admin.post(f"{API}/team/{created_members['rm']}/feedback",
                       json={"rating": 3, "note": "   "})
        assert r.status_code == 400

    def test_sales_rep_cannot_post_feedback(self, rep_token, created_members):
        r = requests.post(f"{API}/team/{created_members['rm']}/feedback",
                          headers={"Authorization": f"Bearer {rep_token}",
                                   "Content-Type": "application/json"},
                          json={"rating": 5, "note": "blocked"})
        assert r.status_code == 403


# ---------- DELETE /api/team/{id} ----------
class TestDelete:
    def test_master_admin_cannot_be_deleted(self, admin, created_members):
        r = admin.delete(f"{API}/team/{created_members['master']}")
        assert r.status_code == 400

    def test_delete_unassigns_subordinates(self, admin, created_members):
        # Create RM2 + ZM2 under NM
        r = admin.post(f"{API}/team", json={
            "name": "TEST_RM2", "phone": "9911100099", "role": "regional_manager",
            "reports_to": created_members["nm"]
        })
        rm2 = r.json()["member"]["id"]
        r = admin.post(f"{API}/team", json={
            "name": "TEST_ZM2", "phone": "9911100098", "role": "zonal_manager",
            "reports_to": rm2
        })
        zm2 = r.json()["member"]["id"]
        try:
            # Delete RM2 → ZM2.reports_to should become null
            d = admin.delete(f"{API}/team/{rm2}")
            assert d.status_code == 200
            r = admin.get(f"{API}/team/{zm2}")
            assert r.status_code == 200
            assert r.json()["reports_to"] is None
        finally:
            admin.delete(f"{API}/team/{zm2}")
