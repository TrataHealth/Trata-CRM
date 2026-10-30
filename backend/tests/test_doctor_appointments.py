# Doctor PC console: appointments list, status updates, visit history, RBAC (iter 28)
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"


def login(phone, password, mode="provider"):
    s = requests.Session()
    r = s.post(f"{API}/auth/send-otp", json={"phone": phone, "login_as": mode})
    assert r.status_code == 200, r.text
    r = s.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": "123456", "login_as": mode})
    assert r.status_code == 200, r.text
    tmp = r.json()["temp_token"]
    r = s.post(f"{API}/auth/login-password", json={"password": password}, headers={"Authorization": f"Bearer {tmp}"})
    assert r.status_code == 200, r.text
    tok = r.json().get("token") or r.json().get("access_token")
    if tok:
        s.headers["Authorization"] = f"Bearer {tok}"
    return s


@pytest.fixture(scope="module")
def doc():
    return login("9000020006", "Trata@123")


@pytest.fixture(scope="module")
def hosp():
    return login("9000020004", "Trata@123")


@pytest.fixture(scope="module")
def master():
    return login("9873117605", "Master@123", "staff")


def get_appts(doc):
    r = doc.get(f"{API}/provider/doctor/appointments")
    assert r.status_code == 200, r.text
    return r.json()


class TestList:
    def test_shape(self, doc):
        d = get_appts(doc)
        assert set(["upcoming", "past", "today", "counts"]) <= set(d)
        assert d["counts"]["upcoming"] == len(d["upcoming"])
        assert d["counts"]["past"] == len(d["past"])
        tests = [a for a in d["upcoming"] + d["past"] if str(a.get("reason") or "").startswith("TEST —")]
        print("TEST rows:", [(a["id"], a["date"], a["status"]) for a in tests])
        assert len(tests) >= 3
        for a in d["upcoming"] + d["past"]:
            assert "_id" not in a
            assert a["source"] in ("clinic", "hospital", "video", "general")

    def test_upcoming_sorted_and_not_final(self, doc):
        d = get_appts(doc)
        keys = [(str(a["date"] or ""), str(a["time"] or "")) for a in d["upcoming"]]
        assert keys == sorted(keys)
        for a in d["upcoming"]:
            assert str(a["status"]).lower() not in ("completed", "cancelled", "no_show")
            assert str(a["date"])[:10] >= d["today"]

    def test_hospital_forbidden(self, hosp):
        assert hosp.get(f"{API}/provider/doctor/appointments").status_code == 403
        assert hosp.get(f"{API}/provider/doctor/patients/x/visits").status_code == 403
        assert hosp.post(f"{API}/provider/doctor/appointments/clinic/x/status", json={"status": "completed"}).status_code == 403

    def test_master_forbidden(self, master):
        assert master.get(f"{API}/provider/doctor/appointments").status_code == 403

    def test_unauth(self):
        assert requests.get(f"{API}/provider/doctor/appointments").status_code in (401, 403)


class TestStatus:
    def test_invalid_status(self, doc):
        r = doc.post(f"{API}/provider/doctor/appointments/clinic/abc/status", json={"status": "foo"})
        assert r.status_code == 400

    def test_invalid_source(self, doc):
        r = doc.post(f"{API}/provider/doctor/appointments/bogus/abc/status", json={"status": "completed"})
        assert r.status_code == 400

    @pytest.mark.parametrize("src", ["clinic", "hospital", "video", "general"])
    def test_unknown_id_non_uuid(self, doc, src):
        r = doc.post(f"{API}/provider/doctor/appointments/{src}/not-a-real-id/status", json={"status": "completed"})
        print(src, r.status_code, r.text[:200])
        assert r.status_code == 404

    @pytest.mark.parametrize("src", ["clinic", "hospital", "video", "general"])
    def test_unknown_id_uuid(self, doc, src):
        r = doc.post(f"{API}/provider/doctor/appointments/{src}/00000000-0000-0000-0000-000000000000/status", json={"status": "completed"})
        print(src, r.status_code, r.text[:200])
        assert r.status_code == 404

    def test_already_final_409(self, doc):
        d = get_appts(doc)
        final = [a for a in d["past"] if str(a.get("reason") or "").startswith("TEST —")
                 and str(a["status"]).lower() in ("completed", "cancelled", "no_show")]
        if not final:
            pytest.skip("no final TEST row")
        a = final[0]
        r = doc.post(f"{API}/provider/doctor/appointments/{a['source']}/{a['id']}/status", json={"status": "completed"})
        assert r.status_code == 409


class TestVisits:
    def test_visits_for_test_patient(self, doc):
        d = get_appts(doc)
        a = next(a for a in d["upcoming"] + d["past"] if str(a.get("reason") or "").startswith("TEST —"))
        r = doc.get(f"{API}/provider/doctor/patients/{a['patient_id'] or 'none'}/visits", params={"phone": a.get("patient_phone") or ""})
        assert r.status_code == 200
        items = r.json()["items"]
        print("visits:", len(items), [(v["date"], v["status"]) for v in items])
        assert any(v["id"] == a["id"] for v in items)
        assert sum(1 for v in items if str(v.get("reason") or "").startswith("TEST —")) >= 3

    def test_visits_unknown_patient(self, doc):
        r = doc.get(f"{API}/provider/doctor/patients/nonexistent-xyz/visits")
        assert r.status_code == 200
        assert r.json()["items"] == []
