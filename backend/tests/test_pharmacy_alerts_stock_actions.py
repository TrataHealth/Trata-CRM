# Iter25: pharmacy new-order alert poll (/orders/new) and stock actions (expiry clearance + reorder suggestions).
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
STORE = "6e4d8e86-8769-4c99-a1ba-37fa9b188cf5"
MAKE = ["python3", "/app/backend/tests/make_test_order.py"]


def login(phone, pw, as_="staff"):
    r = requests.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": "123456", "login_as": as_}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    r2 = requests.post(f"{BASE_URL}/api/auth/login-password", json={"password": pw},
                       headers={"Authorization": f"Bearer {d['temp_token']}"}, timeout=60)
    assert r2.status_code == 200, r2.text
    return {"Authorization": f"Bearer {r2.json()['token']}"}


@pytest.fixture(scope="module")
def pharm():
    return login("9392934300", "TestPharm@123", "provider")


@pytest.fixture(scope="module")
def admin():
    return login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def hosp():
    return login("9792832090", "TestHosp@123", "provider")


def pc(path, h, **kw):
    return requests.get(f"{BASE_URL}/api/pharmacy-console{path}", headers=h, timeout=90, **kw)


# ---- new-order poll ----
class TestNewOrders:
    def test_no_since_returns_server_time(self, pharm):
        r = pc("/orders/new", pharm)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["orders"] == []
        ts = datetime.fromisoformat(d["server_time"])
        assert abs((datetime.now(timezone.utc) - ts).total_seconds()) < 120

    def test_bad_since_400(self, pharm):
        r = pc("/orders/new", pharm, params={"since": "not-a-date"})
        assert r.status_code == 400
        assert "ISO" in r.json()["detail"]

    @pytest.mark.parametrize("who", ["admin", "hosp"])
    def test_non_pharmacy_403(self, who, request):
        r = pc("/orders/new", request.getfixturevalue(who))
        assert r.status_code == 403
        r = pc("/stock-actions", request.getfixturevalue(who))
        assert r.status_code == 403

    def test_since_returns_only_new_order(self, pharm):
        st = pc("/orders/new", pharm).json()["server_time"]
        time.sleep(1)
        oid = subprocess.check_output(MAKE + ["create"], text=True).strip().splitlines()[-1]
        try:
            d = pc("/orders/new", pharm, params={"since": st}).json()
            ids = [o["id"] for o in d["orders"]]
            assert oid in ids, d
            o = next(o for o in d["orders"] if o["id"] == oid)
            assert o["patient_name"] == "TEST_Alert Patient"
            assert o["order_number"].startswith("RXT")
            assert o["items"][0]["name"] == "TEST_Dolo 650"
            assert o["delivery_mode"] == "pickup"
            # cursor = this order's created_at -> no longer returned
            d2 = pc("/orders/new", pharm, params={"since": o["created_at"]}).json()
            assert oid not in [x["id"] for x in d2["orders"]]
            # a since in the future returns nothing
            fut = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            assert pc("/orders/new", pharm, params={"since": fut}).json()["orders"] == []
        finally:
            subprocess.run(MAKE + ["cleanup"], check=True)


# ---- stock actions ----
class TestStockActions:
    @pytest.fixture(scope="class")
    def sa(self, pharm):
        r = pc("/stock-actions", pharm, params={"store": STORE, "days": 60})
        assert r.status_code == 200, r.text
        return r.json()

    def test_shape(self, sa):
        for k in ("days", "expiring", "reorder", "value_at_risk", "reorder_cost"):
            assert k in sa
        assert sa["days"] == 60

    def test_expiring_rules(self, sa):
        today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
        prev = -10**9
        for e in sa["expiring"]:
            assert e["qty_in_stock"] > 0
            assert e["days_left"] <= 60
            d = datetime.fromisoformat(e["expiry_date"][:10]).date()
            assert (d - today).days == e["days_left"]
            assert e["value_at_risk"] == round(e["qty_in_stock"] * float(e["unit_price"] or 0), 2)
            assert e["days_left"] >= prev
            prev = e["days_left"]
        assert sa["value_at_risk"] == round(sum(e["value_at_risk"] for e in sa["expiring"]), 2)

    def test_reorder_rules(self, sa):
        for x in sa["reorder"]:
            q, lvl, s = x["qty_in_stock"] or 0, x["reorder_threshold"] or 0, x["sold_30d"]
            assert q <= lvl or q < s
            target = s + lvl if s else 2 * lvl
            assert x["suggested_qty"] == max(0, target - q)
            assert x["est_cost"] == round(x["suggested_qty"] * float(x["unit_price"] or 0), 2)
            assert x["basis"]
        assert sa["reorder_cost"] == round(sum(x["est_cost"] for x in sa["reorder"]), 2)

    def test_dolo_in_reorder(self, sa):
        dolo = [x for x in sa["reorder"] if "dolo" in (x["medicine_name"] or "").lower()]
        assert dolo, [x["medicine_name"] for x in sa["reorder"]]
        print([(x["medicine_name"], x["qty_in_stock"], x["reorder_threshold"], x["sold_30d"], x["suggested_qty"], x["basis"]) for x in dolo])

    def test_large_days_includes_nov_expiry(self, pharm):
        # NOTE: provider app inventory call times out ~1/8 runs -> backend silently returns empty lists; retry once.
        for _ in range(2):
            d = pc("/stock-actions", pharm, params={"store": STORE, "days": 365}).json()
            names = [e["medicine_name"] for e in d["expiring"]]
            if names:
                break
        print(names)
        assert any("dolo" in n.lower() for n in names)

    def test_foreign_store_403(self, pharm):
        r = pc("/stock-actions", pharm, params={"store": "00000000-0000-0000-0000-000000000000"})
        assert r.status_code == 403
