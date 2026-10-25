# Pharmacy console (stores/orders/rx/inventory/sales), pharmacy login unblock, deactivated-entity guard, entity onboarding mirror
import os
import uuid
import datetime
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
TEST_PHARMACY = "7a3b2595-2575-459c-8bb1-1430b189bfc9"  # TEST_BKC Pharma
TEST_ORDER = "d20475fa-fde4-4c67-abf8-2b3e0c86eb2d"
HOSP_STORE = "6e4d8e86-8769-4c99-a1ba-37fa9b188cf5"
HOSP_CONTACT = "d256e122-8728-42b8-929b-1f03eca6f6db"


def login(phone, pw, as_="staff"):
    r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": "123456", "login_as": as_}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    t = d["temp_token"]
    ep = "set-password" if d.get("needs_password_setup") else "login-password"
    r2 = requests.post(f"{BASE_URL}/api/auth/{ep}", json={"password": pw}, headers={"Authorization": f"Bearer {t}"}, timeout=60)
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


def g(path, h, **kw):
    return requests.get(f"{BASE_URL}/api/pharmacy-console{path}", headers=h, timeout=90, **kw)


# ---- stores ----
class TestStores:
    def test_admin_network(self, admin):
        r = g("/stores", admin)
        assert r.status_code == 200
        s = r.json()["stores"]
        assert len(s) > 1 and all(x["kind"] == "network" for x in s)
        assert any(x["id"] == TEST_PHARMACY for x in s)

    def test_rohan_forbidden(self, rohan):
        assert g("/stores", rohan).status_code == 403

    def test_pharmacy_own(self, pharm):
        r = g("/stores", pharm)
        assert r.status_code == 200, r.text
        s = r.json()["stores"]
        print(s)
        assert s[0]["id"] == HOSP_STORE and s[0]["kind"] == "own"

    def test_hospital_sees_its_pharmacy(self, hosp):
        r = g("/stores", hosp)
        assert r.status_code == 200, r.text
        s = r.json()["stores"]
        print(s)
        assert any(x["id"] == HOSP_STORE and x["kind"] == "hospital" for x in s)


# ---- orders ----
class TestOrders:
    def test_list_scoped(self, admin):
        r = g("/orders", admin, params={"store": TEST_PHARMACY})
        assert r.status_code == 200
        d = r.json()
        assert all(o["pharmacy_id"] == TEST_PHARMACY for o in d["orders"])
        assert sum(d["counts"].values()) == len(d["orders"])
        print({o["id"]: (o["status"], o["patient_name"], o["total_amount"], o["is_paid"]) for o in d["orders"]})

    def test_status_filter(self, admin):
        r = g("/orders", admin, params={"store": TEST_PHARMACY, "status": "ACCEPTED"})
        assert r.status_code == 200
        assert all(o["status"] == "ACCEPTED" for o in r.json()["orders"])

    def test_foreign_store_403(self, pharm):
        assert g("/orders", pharm, params={"store": TEST_PHARMACY}).status_code == 403

    def test_foreign_order_404(self, pharm):
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/orders/{TEST_ORDER}/action", json={"action": "accept"}, headers=pharm)
        assert r.status_code == 404

    def test_invalid_transition_409(self, admin):
        st = [o for o in g("/orders", admin, params={"store": TEST_PHARMACY}).json()["orders"] if o["id"] == TEST_ORDER][0]["status"]
        if st != "ACCEPTED" and st != "FULFILLED":
            pytest.skip(f"order is {st}")
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/orders/{TEST_ORDER}/action", json={"action": "accept"}, headers=admin)
        assert r.status_code == 409

    def test_reject_needs_reason(self, admin):
        st = [o for o in g("/orders", admin, params={"store": TEST_PHARMACY}).json()["orders"] if o["id"] == TEST_ORDER][0]["status"]
        if st != "ACCEPTED":
            pytest.skip(f"order is {st}")
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/orders/{TEST_ORDER}/action", json={"action": "reject"}, headers=admin)
        assert r.status_code == 400

    def test_unknown_action(self, admin):
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/orders/{TEST_ORDER}/action", json={"action": "nuke"}, headers=admin)
        assert r.status_code == 400

    def test_rx_image(self, admin):
        r = g(f"/orders/{TEST_ORDER}/rx-image", admin)
        assert r.status_code == 200 and "image" in r.json()


# ---- prescriptions ----
class TestRx:
    def test_list_admin_all(self, admin):
        r = g("/prescriptions", admin, params={"store": TEST_PHARMACY})
        assert r.status_code == 200, r.text
        d = r.json()
        ids = [x["id"] for x in d["prescriptions"]]
        assert len(ids) == len(set(ids))
        assert all(x["rx_image_b64"] is None for x in d["prescriptions"])
        print(len(ids), d["unreachable_stores"])

    def test_list_pharm(self, pharm):
        r = g("/prescriptions", pharm)
        assert r.status_code == 200, r.text
        print(r.json())

    def test_bad_status(self, admin):
        r = requests.put(f"{BASE_URL}/api/pharmacy-console/prescriptions/x/status", json={"status": "bogus"}, headers=admin)
        assert r.status_code == 400

    def test_foreign_rx_404(self, pharm):
        r = requests.put(f"{BASE_URL}/api/pharmacy-console/prescriptions/00000000-0000-0000-0000-000000000000/status",
                         json={"status": "accepted"}, headers=pharm)
        print(r.status_code, r.text)
        assert r.status_code == 404


# ---- inventory ----
class TestInventory:
    def test_crud(self, pharm, admin):
        name = f"TEST_Paracetamol {uuid.uuid4().hex[:5]}"
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/inventory", params={"store": HOSP_STORE}, headers=pharm, timeout=60,
                          json={"medicine_name": name, "qty_in_stock": 3, "reorder_threshold": 5, "unit_price": 2.5,
                                "expiry_date": (datetime.date.today() + datetime.timedelta(days=20)).isoformat(), "unit": "strip"})
        assert r.status_code == 200, r.text
        print(r.json())
        lst = g("/inventory", pharm, params={"search": "TEST_Paracetamol"}).json()["items"]
        it = [x for x in lst if x["medicine_name"] == name]
        assert it, lst
        it = it[0]
        assert it["low_stock"] is True and it["expiring_soon"] is True and it["expired"] is False
        low = g("/inventory", pharm, params={"low_stock_only": "true"}).json()["items"]
        assert any(x["id"] == it["id"] for x in low)
        r = requests.patch(f"{BASE_URL}/api/pharmacy-console/inventory/{it['id']}", headers=pharm, json={"qty_in_stock": 50})
        assert r.status_code == 200, r.text
        it2 = [x for x in g("/inventory", pharm).json()["items"] if x["id"] == it["id"]][0]
        assert it2["qty_in_stock"] == 50 and it2["low_stock"] is False
        # admin also sees it
        assert any(x["id"] == it["id"] for x in g("/inventory", admin, params={"store": HOSP_STORE}).json()["items"])
        r = requests.delete(f"{BASE_URL}/api/pharmacy-console/inventory/{it['id']}", headers=pharm)
        assert r.status_code == 200, r.text
        assert not any(x["id"] == it["id"] for x in g("/inventory", pharm).json()["items"])

    def test_missing_name_400(self, pharm):
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/inventory", params={"store": HOSP_STORE}, headers=pharm, json={"qty_in_stock": 1})
        assert r.status_code == 400

    def test_bad_expiry_400(self, pharm):
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/inventory", params={"store": HOSP_STORE}, headers=pharm,
                          json={"medicine_name": "TEST_x", "expiry_date": "notadate"})
        assert r.status_code == 400

    def test_foreign_item_404(self, pharm):
        assert requests.patch(f"{BASE_URL}/api/pharmacy-console/inventory/nonexistent", headers=pharm, json={"qty_in_stock": 1}).status_code == 404
        assert requests.delete(f"{BASE_URL}/api/pharmacy-console/inventory/nonexistent", headers=pharm).status_code == 404

    def test_foreign_store_post_403(self, pharm):
        r = requests.post(f"{BASE_URL}/api/pharmacy-console/inventory", params={"store": TEST_PHARMACY}, headers=pharm, json={"medicine_name": "TEST_y"})
        assert r.status_code == 403


# ---- sales ----
class TestSales:
    def test_sales(self, admin):
        r = g("/sales", admin, params={"store": TEST_PHARMACY, "days": 7})
        assert r.status_code == 200, r.text
        d = r.json()
        assert len(d["series"]) == 7
        for k in ("revenue", "fulfilled", "total_requests", "avg_order_value", "rejection_rate", "open_orders", "top_medicines", "by_store"):
            assert k in d
        assert d["by_store"][0]["store_id"] == TEST_PHARMACY
        print({k: d[k] for k in ("revenue", "fulfilled", "total_requests", "open_orders", "status_counts")})

    def test_sales_all_admin(self, admin):
        r = g("/sales", admin, params={"days": 30})
        assert r.status_code == 200, r.text


# ---- login ----
class TestLogin:
    def test_pharmacy_can_login(self):
        r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": "9392934300", "otp": "123456", "login_as": "provider"})
        assert r.status_code == 200, r.text

    def test_deactivated_phone_blocked(self):
        r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": "9345990470", "otp": "123456", "login_as": "provider"})
        print(r.status_code, r.text)
        assert r.status_code == 403 and "removed by its organisation" in r.json()["detail"]

    def test_me_business_name(self, hosp, pharm):
        for h in (hosp, pharm):
            u = requests.get(f"{BASE_URL}/api/auth/me", headers=h).json()["user"]
            print(u.get("name"), "|", u.get("business_name"), "|", u.get("provider_type"))
            assert u.get("business_name")


# ---- entity onboarding ----
class TestEntityOnboard:
    def test_create_mirror_notify_delete(self, rohan, admin):
        phone = "93" + str(uuid.uuid4().int)[:8]
        name = f"TEST Pharma {phone[-4:]}"
        r = requests.post(f"{BASE_URL}/api/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=rohan, timeout=90,
                          json={"name": name, "entity_kind": "pharmacy", "dedicated_phone": phone, "city": "Mumbai", "contact_person": "TEST Admin", "address": "1 Test Road"})
        print(r.status_code, r.text[:600])
        assert r.status_code in (200, 201), r.text
        body = r.json()
        ent_id = (body.get("entity") or {}).get("id") or body.get("id")
        try:
            # /api/contacts list hides names containing "test", so locate via the notification
            n = requests.get(f"{BASE_URL}/api/notifications", headers=admin).json()
            n = n.get("items", n) if isinstance(n, dict) else n
            note = [x for x in n if x.get("kind") == "entity_onboarded" and phone in (x.get("body") or "")]
            assert note, "entity_onboarded notification missing"
            c = requests.get(f"{BASE_URL}/api/contacts/{note[0]['contact_id']}", headers=admin).json()
            c = c.get("contact", c)
            print(c)
            assert c["phone"] == phone and c["type"] == "pharmacy" and c["kyc_status"] == "pending"
            assert c.get("parent_contact_id") == HOSP_CONTACT and c.get("parent_name")
            assert c.get("assigned_agent_id")
            v = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": "123456", "login_as": "provider"})
            print("verify", v.status_code, v.text[:300])
            assert v.status_code == 200
        finally:
            if ent_id:
                d = requests.delete(f"{BASE_URL}/api/admin/provider-app/contact-entities/{ent_id}", params={"contact_id": HOSP_CONTACT}, headers=admin)
                print("delete", d.status_code, d.text[:200])
                v = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": "123456", "login_as": "provider"})
                print("after delete verify", v.status_code, v.text[:200])


# ---- order transitions on TEST_BKC Pharma orders only ----
class TestOrderTransitions:
    def test_accept_then_fulfil_then_paid(self, admin):
        oid = "e7c3b905-1f9f-4da8-a099-926054300b97"
        o = [x for x in g("/orders", admin, params={"store": TEST_PHARMACY}).json()["orders"] if x["id"] == oid][0]
        if o["status"] != "PENDING_PHARMACY":
            pytest.skip(f"order already {o['status']}")
        u = f"{BASE_URL}/api/pharmacy-console/orders/{oid}/action"
        r = requests.post(u, json={"action": "fulfil", "total_amount": 10}, headers=admin)
        assert r.status_code == 409
        r = requests.post(u, json={"action": "accept", "note": "TEST note"}, headers=admin)
        assert r.status_code == 200, r.text
        d = r.json()["order"]
        assert d["status"] == "ACCEPTED" and d["pharmacy_notes"] == "TEST note"
        ev = d["timeline"][-1]
        assert ev["by"] == "pharmacy" and ev["via"] == "crm" and ev["event"] == "ACCEPTED"
        r = requests.post(u, json={"action": "fulfil"}, headers=admin)
        assert r.status_code == 400  # no amount
        r = requests.post(u, json={"action": "fulfil", "total_amount": 120}, headers=admin)
        assert r.status_code == 200, r.text
        assert r.json()["order"]["status"] == "FULFILLED" and r.json()["order"]["total_amount"] == 120
        r = requests.post(u, json={"action": "mark_paid"}, headers=admin)
        assert r.status_code == 200
        assert r.json()["order"]["is_paid"] is True and r.json()["order"]["status"] == "FULFILLED"
        assert r.json()["order"]["timeline"][-1]["event"] == "PAID"
        s = g("/sales", admin, params={"store": TEST_PHARMACY, "days": 30}).json()
        print(s["revenue"], s["fulfilled"], s["top_medicines"])
        assert s["revenue"] >= 120 and s["fulfilled"] >= 1
