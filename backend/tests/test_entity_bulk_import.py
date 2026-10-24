"""Bulk entity import + Pending rows (CRM contact-entities + provider /entities).
WRITES TO SHARED SUPABASE PROD: creates <=3 TEST entities, all deleted at teardown; leftover pending rows discarded.
"""
import random
import sys
import time

import pytest
import requests

sys.path.insert(0, "/app/backend/tests")
from test_provider_app_onboard import API, H, login, HOSP_CONTACT, HOSP_PHONE, HOSP_PWD  # noqa: E402

CRM = f"{API}/admin/provider-app/contact-entities"
PROV = f"{API}/provider/entities"
P = {"contact_id": HOSP_CONTACT}
CREATED = []  # (base, params, token, entity_id)


def phone():
    return "9" + "".join(random.choice("0123456789") for _ in range(9))


def row(**kw):
    r = {"entity_kind": "hospital_branch", "name": f"TEST Bulk {random.randint(1000, 9999)}", "contact_person": "TEST Owner",
         "dedicated_phone": phone(), "address": "1 Test Road", "city": "Lucknow"}
    r.update(kw)
    return {k: v for k, v in r.items() if v is not None}


@pytest.fixture(scope="module")
def adm():
    return login("9873117605", "Master@123")[0]


@pytest.fixture(scope="module")
def rohan():
    return login("9000000002", "Trata@123")[0]


@pytest.fixture(scope="module")
def priya():
    return login("9000000001", "Trata@123")[0]


@pytest.fixture(scope="module")
def hosp():
    return login(HOSP_PHONE, HOSP_PWD, "provider")[0]


@pytest.fixture(scope="module", autouse=True)
def cleanup(adm):
    yield
    ents = requests.get(CRM, headers=H(adm), params=P, timeout=60).json().get("entities", [])
    for e in ents:
        if e.get("name", "").startswith("TEST Bulk") and e.get("is_active") is not False:
            print("cleanup entity", e["id"], requests.delete(f"{CRM}/{e['id']}", headers=H(adm), params=P, timeout=60).status_code)
    for it in requests.get(f"{CRM}/pending", headers=H(adm), params=P, timeout=60).json().get("items", []):
        requests.delete(f"{CRM}/pending/{it['id']}", headers=H(adm), params=P, timeout=60)


def poll(base, tok, params, job_id, limit=90):
    for _ in range(limit):
        j = requests.get(f"{base}/bulk/{job_id}", headers=H(tok), params=params, timeout=60).json()
        if j.get("status") == "done":
            return j
        time.sleep(1.5)
    raise AssertionError("bulk job did not finish")


def existing_phone(tok):
    ents = requests.get(CRM, headers=H(tok), params=P, timeout=60).json()["entities"]
    act = [e for e in ents if e.get("is_active") is not False and e.get("dedicated_phone")]
    return act[0]["dedicated_phone"] if act else None


# Access rules
class TestAccess:
    def test_priya_403_bulk(self, priya):
        r = requests.post(f"{CRM}/bulk", headers=H(priya), params=P, json={"rows": [], "pending": []}, timeout=60)
        assert r.status_code == 403

    def test_priya_403_pending(self, priya):
        assert requests.get(f"{CRM}/pending", headers=H(priya), params=P, timeout=60).status_code == 403

    def test_staff_cannot_use_provider_prefix(self, adm):
        assert requests.get(f"{PROV}/pending", headers=H(adm), timeout=60).status_code == 403

    def test_too_many_rows_400(self, adm):
        r = requests.post(f"{CRM}/bulk", headers=H(adm), params=P, json={"rows": [row() for _ in range(300)], "pending": [row() for _ in range(201)]}, timeout=60)
        assert r.status_code == 400 and "500" in r.json()["detail"]

    def test_unknown_job_404(self, adm):
        assert requests.get(f"{CRM}/bulk/nope", headers=H(adm), params=P, timeout=60).status_code == 404

    def test_non_dict_row(self, adm):
        r = requests.post(f"{CRM}/bulk", headers=H(adm), params=P, json={"rows": ["oops"], "pending": []}, timeout=60)
        print("non-dict row status", r.status_code, r.text[:200])
        assert r.status_code in (400, 422), f"non-dict row returned {r.status_code}"


# Bulk via CRM (Rohan, assigned agent)
class TestBulkCRM:
    def test_bulk_mixed(self, rohan):
        used = existing_phone(rohan)
        good = row()
        rows = [good, row(city=None), row(dedicated_phone="12345"), row(entity_kind="blood_bank")]
        if used:
            rows.append(row(dedicated_phone=used))  # upstream reject -> pending
        client_pending = [row(address=None)]
        r = requests.post(f"{CRM}/bulk", headers=H(rohan), params=P, json={"rows": rows, "pending": client_pending}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total"] == (2 if used else 1) and d["pending_saved"] == 4
        j = poll(CRM, rohan, P, d["job_id"])
        assert j["done"] == j["total"] and j["created"] == 1 and j["failed"] == (1 if used else 0), j
        ents = requests.get(CRM, headers=H(rohan), params=P, timeout=60).json()["entities"]
        assert any(e["dedicated_phone"] == good["dedicated_phone"] for e in ents)
        items = requests.get(f"{CRM}/pending", headers=H(rohan), params=P, timeout=60).json()["items"]
        errs = " | ".join(" ".join(i["errors"]) for i in items)
        print("pending errors:", errs)
        assert len(items) >= (5 if used else 4)
        assert "city is required" in errs and "not allowed" in errs and "address is required" in errs
        assert all("_id" not in i and "id" in i and "data" in i for i in items)
        if used:
            rej = [i for i in items if i["data"].get("dedicated_phone") == used]
            assert rej and rej[0]["source"] == "import_failed" and rej[0]["errors"], rej

    def test_pending_update_and_import(self, rohan, adm):
        items = requests.get(f"{CRM}/pending", headers=H(rohan), params=P, timeout=60).json()["items"]
        it = next(i for i in items if "city is required" in " ".join(i["errors"]))
        # still invalid import -> 400
        r = requests.post(f"{CRM}/pending/{it['id']}/import", headers=H(rohan), params=P, timeout=60)
        assert r.status_code == 400 and "city" in r.json()["detail"]
        # bad update returns errors
        r = requests.put(f"{CRM}/pending/{it['id']}", headers=H(rohan), params=P, json={"data": {**it["data"], "pincode": "12"}}, timeout=60)
        assert r.status_code == 200 and r.json()["errors"]
        # fix
        fixed = {**it["data"], "city": "Kanpur"}
        fixed.pop("pincode", None)
        r = requests.put(f"{CRM}/pending/{it['id']}", headers=H(rohan), params=P, json={"data": fixed}, timeout=60)
        assert r.status_code == 200 and r.json()["errors"] == [], r.text
        r = requests.post(f"{CRM}/pending/{it['id']}/import", headers=H(rohan), params=P, timeout=90)
        assert r.status_code == 200, r.text
        items2 = requests.get(f"{CRM}/pending", headers=H(rohan), params=P, timeout=60).json()["items"]
        assert all(i["id"] != it["id"] for i in items2)
        ents = requests.get(CRM, headers=H(adm), params=P, timeout=60).json()["entities"]
        assert any(e["dedicated_phone"] == fixed["dedicated_phone"] and e.get("city") == "Kanpur" for e in ents)

    def test_priya_cannot_touch_pending(self, rohan, priya):
        it = requests.get(f"{CRM}/pending", headers=H(rohan), params=P, timeout=60).json()["items"][0]
        assert requests.put(f"{CRM}/pending/{it['id']}", headers=H(priya), params=P, json={"data": {}}, timeout=60).status_code == 403
        assert requests.delete(f"{CRM}/pending/{it['id']}", headers=H(priya), params=P, timeout=60).status_code == 403

    def test_discard(self, rohan):
        it = requests.get(f"{CRM}/pending", headers=H(rohan), params=P, timeout=60).json()["items"][0]
        assert requests.delete(f"{CRM}/pending/{it['id']}", headers=H(rohan), params=P, timeout=60).status_code == 200
        assert requests.delete(f"{CRM}/pending/{it['id']}", headers=H(rohan), params=P, timeout=60).status_code == 404


# Provider portal prefix (same org as the CRM contact)
class TestBulkProvider:
    def test_provider_bulk_and_pending(self, hosp, adm):
        good = row()
        r = requests.post(f"{PROV}/bulk", headers=H(hosp), json={"rows": [good, row(name=None)], "pending": []}, timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total"] == 1 and d["pending_saved"] == 1
        j = poll(PROV, hosp, {}, d["job_id"])
        assert j["created"] == 1
        items = requests.get(f"{PROV}/pending", headers=H(hosp), timeout=60).json()["items"]
        assert any("name is required" in " ".join(i["errors"]) for i in items)
        # job of same org visible via CRM prefix too
        assert requests.get(f"{CRM}/bulk/{d['job_id']}", headers=H(adm), params=P, timeout=60).status_code == 200

    def test_cross_org_404(self, hosp, adm):
        # pending-only bulk (no entity creation) on the test hospital org
        r = requests.post(f"{PROV}/bulk", headers=H(hosp), json={"rows": [], "pending": [row(city=None)]}, timeout=60)
        assert r.status_code == 200
        it = requests.get(f"{PROV}/pending", headers=H(hosp), timeout=60).json()["items"][0]
        OP = {"contact_id": "b2e36653-6fa1-4052-afe5-70aaa191f1a7"}  # a different (pharmacy) org
        assert requests.get(f"{CRM}/pending", headers=H(adm), params=OP, timeout=60).status_code == 200
        r = requests.put(f"{CRM}/pending/{it['id']}", headers=H(adm), params=OP, json={"data": {}}, timeout=60)
        assert r.status_code == 404, r.text
        assert requests.delete(f"{CRM}/pending/{it['id']}", headers=H(adm), params=OP, timeout=60).status_code == 404
        assert requests.post(f"{CRM}/pending/{it['id']}/import", headers=H(adm), params=OP, timeout=60).status_code == 404
        assert requests.delete(f"{PROV}/pending/{it['id']}", headers=H(hosp), timeout=60).status_code == 200
