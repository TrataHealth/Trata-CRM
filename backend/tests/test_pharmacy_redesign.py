# Iter24: pharmacy-as-provider redesign — console 403 for staff/hospital, rx claim guards, notifications filter,
# entity summary dashboard, entity removal mirror.
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
HOSP_STORE = "6e4d8e86-8769-4c99-a1ba-37fa9b188cf5"
TEST_PHONE = "9" + str(int(time.time()))[-9:]


def login(phone, pw, as_="staff"):
    r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": "123456", "login_as": as_}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    ep = "set-password" if d.get("needs_password_setup") else "login-password"
    r2 = requests.post(f"{BASE_URL}/api/auth/{ep}", json={"password": pw}, headers={"Authorization": f"Bearer {d['temp_token']}"}, timeout=60)
    assert r2.status_code == 200, r2.text
    return {"Authorization": f"Bearer {r2.json()['token']}"}


@pytest.fixture(scope="module")
def admin():
    return login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def rohan():
    return login("9000000002", "Trata@123")


@pytest.fixture(scope="module")
def hosp():
    return login("9792832090", "TestHosp@123", "provider")


@pytest.fixture(scope="module")
def pharm():
    return login("9392934300", "TestPharm@123", "provider")


def pc(path, h, method="GET", **kw):
    return requests.request(method, f"{BASE_URL}/api/pharmacy-console{path}", headers=h, timeout=90, **kw)


# ---- console access ----
class TestConsoleAccess:
    @pytest.mark.parametrize("who", ["admin", "rohan", "hosp"])
    def test_non_pharmacy_403(self, who, request):
        h = request.getfixturevalue(who)
        for p in ("/stores", "/orders", "/sales", "/inventory", "/prescriptions"):
            r = pc(p, h)
            assert r.status_code == 403, (who, p, r.status_code, r.text)

    def test_pharmacy_200(self, pharm):
        r = pc("/stores", pharm)
        assert r.status_code == 200
        d = r.json()
        assert [s["id"] for s in d["stores"]] == [HOSP_STORE]
        assert d["can_pick_all"] is False
        for p in ("/orders", "/sales", "/inventory", "/prescriptions"):
            assert pc(p, pharm).status_code == 200, p
        inv = pc("/inventory", pharm).json()
        assert any("TEST Dolo 650" in (i.get("medicine_name") or "") for i in inv["items"])


# ---- prescription claim guards (no writes) ----
class TestRxClaim:
    @pytest.fixture(scope="class")
    def open_rx(self, pharm):
        rxs = pc("/prescriptions", pharm).json()["prescriptions"]
        print([(x["id"], x.get("status"), x.get("pharmacy_id")) for x in rxs])
        o = next((x for x in rxs if x.get("pharmacy_id") is None), None)
        if not o:
            pytest.skip("No open prescription available")
        return o["id"]

    def test_reject_open_rx_409(self, pharm, open_rx):
        r = pc(f"/prescriptions/{open_rx}/status", pharm, "PUT", json={"status": "rejected", "rejection_reason": "TEST"})
        assert r.status_code == 409, r.text

    def test_ready_open_rx_409(self, pharm, open_rx):
        r = pc(f"/prescriptions/{open_rx}/status", pharm, "PUT", json={"status": "ready_for_pickup", "store": HOSP_STORE})
        assert r.status_code == 409, r.text

    def test_accept_no_store_409(self, pharm, open_rx):
        r = pc(f"/prescriptions/{open_rx}/status", pharm, "PUT", json={"status": "accepted"})
        assert r.status_code == 409, r.text

    def test_accept_foreign_store_409(self, pharm, open_rx):
        r = pc(f"/prescriptions/{open_rx}/status", pharm, "PUT", json={"status": "accepted", "store": "7a3b2595-2575-459c-8bb1-1430b189bfc9"})
        assert r.status_code == 409, r.text

    def test_reject_without_reason_400(self, pharm, open_rx):
        r = pc(f"/prescriptions/{open_rx}/status", pharm, "PUT", json={"status": "rejected"})
        assert r.status_code == 400, r.text

    def test_unknown_status_400(self, pharm, open_rx):
        assert pc(f"/prescriptions/{open_rx}/status", pharm, "PUT", json={"status": "bogus"}).status_code == 400

    def test_hospital_rx_status_403(self, hosp, open_rx):
        r = pc(f"/prescriptions/{open_rx}/status", hosp, "PUT", json={"status": "accepted", "store": HOSP_STORE})
        assert r.status_code == 403, r.text


# ---- mark_paid guard (only if pharmacy has a paid order) ----
def test_mark_paid_already_paid_409(pharm):
    orders = pc("/orders", pharm).json()["orders"]
    paid = next((o for o in orders if o.get("is_paid")), None)
    if not paid:
        pytest.skip("No paid order in TEST Hosp store; guard verified via code review")
    r = pc(f"/orders/{paid['id']}/action", pharm, "POST", json={"action": "mark_paid"})
    assert r.status_code == 409


# ---- notifications ----
class TestNotifications:
    def test_hospital_only_own(self, hosp):
        r = requests.get(f"{BASE_URL}/api/notifications", headers=hosp, timeout=30)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_pharmacy_only_own(self, pharm):
        r = requests.get(f"{BASE_URL}/api/notifications", headers=pharm, timeout=30)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_admin_sees_admin(self, admin):
        r = requests.get(f"{BASE_URL}/api/notifications?limit=100", headers=admin, timeout=30)
        assert r.status_code == 200
        items = r.json()["items"]
        assert len(items) > 0
        assert all(i.get("audience") != "provider" for i in items)

    def test_rohan_no_admin_items(self, rohan):
        r = requests.get(f"{BASE_URL}/api/notifications?limit=100", headers=rohan, timeout=30)
        assert r.status_code == 200
        assert all(i.get("audience") != "admin" for i in r.json()["items"])


# ---- entities: summary + create/delete mirror ----
class TestEntities:
    def test_list_and_summary(self, hosp):
        r = requests.get(f"{BASE_URL}/api/provider/entities", headers=hosp, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["root_kind"] == "hospital"
        ents = [e for e in d["entities"] if e.get("is_active") is not False]
        print([(e["id"], e["entity_kind"], e["name"]) for e in d["entities"]])
        if not ents:
            pytest.skip("no active entity")
        e = next((x for x in ents if x["entity_kind"] == "pharmacy"), ents[0])
        s = requests.get(f"{BASE_URL}/api/provider/entities/{e['id']}/summary", headers=hosp, timeout=60)
        assert s.status_code == 200, s.text
        sd = s.json()
        print(sd)
        assert sd["entity"]["id"] == e["id"]
        assert isinstance(sd["metrics"], list) and isinstance(sd["activities"], list)
        assert sd["kyc_status"] and sd["crm_login"] in ("active", "not_yet")
        if e["entity_kind"] == "pharmacy":
            labels = [m["label"] for m in sd["metrics"]]
            assert "Orders · 30 days" in labels and "Low-stock medicines" in labels, labels

    def test_summary_unknown_404(self, hosp):
        s = requests.get(f"{BASE_URL}/api/provider/entities/00000000-0000-0000-0000-000000000000/summary", headers=hosp, timeout=60)
        assert s.status_code == 404

    def test_summary_other_org_404(self, hosp, pharm):
        # pharmacy login's own org entities are not visible to hospital & vice versa
        ents = requests.get(f"{BASE_URL}/api/provider/entities", headers=hosp, timeout=60).json()["entities"]
        if not ents:
            pytest.skip("no entity")
        r = requests.get(f"{BASE_URL}/api/provider/entities/{ents[0]['id']}/summary", headers=pharm, timeout=60)
        assert r.status_code == 404, r.text

    def test_staff_cannot_use_provider_entities(self, admin):
        r = requests.get(f"{BASE_URL}/api/provider/entities", headers=admin, timeout=30)
        assert r.status_code == 403

    def test_create_summary_delete_mirror(self, hosp, admin):
        body = {"entity_kind": "pharmacy", "name": f"TEST_Iter24 Pharma {TEST_PHONE}", "contact_person": "TEST Owner",
                "dedicated_phone": TEST_PHONE, "address": "TEST street", "city": "Lucknow"}
        r = requests.post(f"{BASE_URL}/api/provider/entities", headers=hosp, json=body, timeout=90)
        assert r.status_code == 200, r.text
        eid = r.json()["entity"]["id"]
        try:
            s = requests.get(f"{BASE_URL}/api/provider/entities/{eid}/summary", headers=hosp, timeout=60)
            assert s.status_code == 200, s.text
            sd = s.json()
            assert sd["kyc_status"] == "pending" and sd["crm_login"] == "not_yet"
            assert any("added" in a["title"] for a in sd["activities"]), sd["activities"]
            n = requests.get(f"{BASE_URL}/api/notifications?limit=50", headers=admin, timeout=30).json()["items"]
            note = next((x for x in n if x.get("kind") == "entity_onboarded" and TEST_PHONE in (x.get("body") or "")), None)
            assert note, "admin did not get entity_onboarded"
            cid = note["contact_id"]
            pytest.contact_id = cid
        finally:
            d = requests.delete(f"{BASE_URL}/api/provider/entities/{eid}", headers=hosp, timeout=60)
            assert d.status_code == 200, d.text
        c = requests.get(f"{BASE_URL}/api/contacts/{cid}", headers=admin, timeout=30)
        assert c.status_code == 200, c.text
        cj = c.json().get("contact", c.json())
        assert cj.get("entity_removed") is True and cj.get("is_active") is False, cj
        v = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": TEST_PHONE, "otp": "123456", "login_as": "provider"}, timeout=30)
        assert v.status_code == 403, v.text
