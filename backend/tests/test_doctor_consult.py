# Doctor consultation notes + prescription (shared consultation_ehr): GET/PUT consult, share, RBAC (iter 29)
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
def tests_rows(doc):
    d = doc.get(f"{API}/provider/doctor/appointments").json()
    rows = [a for a in d["upcoming"] + d["past"] if str(a.get("reason") or "").startswith("TEST —")]
    print("TEST rows:", [(a["source"], a["id"], a["date"], a["status"]) for a in rows])
    assert rows
    return rows


def url(a, suffix=""):
    return f"{API}/provider/doctor/appointments/{a['source']}/{a['id']}/consult{suffix}"


PAYLOAD = {
    "chief_complaint": "TEST fever 3 days", "diagnosis": "TEST Viral fever, TEST URTI",
    "vitals": {"bp": "120/80", "pulse": "88", "temp": "101", "spo2": "98", "weight": "70"},
    "notes": "TEST private note do-not-show", "treatment_plan": "TEST rest and fluids",
    "prescriptions": [{"name": "TEST Paracetamol 650", "dosage": "1 tab", "frequency": "1-0-1", "duration": "5 days", "instructions": "After food"},
                      {"name": "", "dosage": "x"}],
    "investigations": ["TEST CBC", " ", "TEST CRP"], "follow_up_date": "2026-02-10", "follow_up_notes": "TEST review", "complete": False,
}


class TestConsultRBAC:
    def test_hospital_403(self, tests_rows):
        h = login("9000020004", "Trata@123")
        a = tests_rows[0]
        assert h.get(url(a)).status_code == 403
        assert h.put(url(a), json={}).status_code == 403
        assert h.post(url(a, "/share")).status_code == 403

    def test_master_403(self, tests_rows):
        m = login("9873117605", "Master@123", "staff")
        a = tests_rows[0]
        assert m.get(url(a)).status_code == 403
        assert m.post(url(a, "/share")).status_code == 403

    def test_unauth(self, tests_rows):
        assert requests.get(url(tests_rows[0])).status_code in (401, 403)

    def test_invalid_source_400(self, doc):
        assert doc.get(f"{API}/provider/doctor/appointments/bogus/x/consult").status_code == 400
        assert doc.put(f"{API}/provider/doctor/appointments/bogus/x/consult", json={}).status_code == 400
        assert doc.post(f"{API}/provider/doctor/appointments/bogus/x/consult/share").status_code == 400

    @pytest.mark.parametrize("src", ["clinic", "hospital", "video", "general"])
    def test_unknown_id_404(self, doc, src):
        for aid in ("not-real", "00000000-0000-0000-0000-000000000000"):
            r = doc.get(f"{API}/provider/doctor/appointments/{src}/{aid}/consult")
            print(src, aid, r.status_code, r.text[:150])
            assert r.status_code == 404
        assert doc.post(f"{API}/provider/doctor/appointments/{src}/00000000-0000-0000-0000-000000000000/consult/share").status_code == 404


class TestConsultFlow:
    def test_get_shape(self, doc, tests_rows):
        for a in tests_rows:
            r = doc.get(url(a))
            assert r.status_code == 200, r.text
            d = r.json()
            assert set(["appointment", "ehr", "doctor"]) <= set(d)
            assert d["appointment"]["id"] == a["id"]
            print(a["id"], "ehr:", (d["ehr"] or {}).get("id"), (d["ehr"] or {}).get("status"), "doctor:", d["doctor"].get("full_name"))

    def test_save_roundtrip_and_share(self, doc, tests_rows):
        a = tests_rows[-1]
        r = doc.put(url(a), json=PAYLOAD)
        assert r.status_code == 200, r.text
        e = r.json()["ehr"]
        assert r.json()["completed"] is False
        g = doc.get(url(a)).json()["ehr"]
        assert g["id"] == e["id"]
        assert g["notes"] == "TEST private note do-not-show"
        assert g["diagnosis"] == ["TEST Viral fever", "TEST URTI"]
        assert g["primary_diagnosis"] == "TEST Viral fever"
        assert len(g["prescriptions"]) == 1 and g["prescriptions"][0]["name"] == "TEST Paracetamol 650"
        assert g["prescriptions"][0]["frequency"] == "1-0-1"
        assert g["investigations"] == ["TEST CBC", "TEST CRP"]
        assert g["vitals"]["bp"] == "120/80"
        from datetime import datetime, timedelta, timezone
        assert datetime.fromisoformat(g["follow_up_date"]).astimezone(timezone(timedelta(hours=5, minutes=30))).date().isoformat() == "2026-02-10"
        assert g["treatment_plan"] == "TEST rest and fluids"
        print("status before share:", g["status"], "shared:", g["shared"])
        s = doc.post(url(a, "/share"))
        print("share:", s.status_code, s.text[:300])
        assert s.status_code == 200
        assert s.json()["ehr"]["status"] == "signed" and s.json()["ehr"]["shared"] is True
        assert "patient_notified" in s.json()
        g2 = doc.get(url(a)).json()["ehr"]
        assert g2["status"] == "signed" and g2["signed_at"]
        # edit after share -> updated_at > signed_at, status stays signed
        r = doc.put(url(a), json={**PAYLOAD, "notes": "TEST private note v2"})
        g3 = r.json()["ehr"]
        assert g3["status"] == "signed"
        assert g3["updated_at"] > g3["signed_at"]
        assert g3["notes"] == "TEST private note v2"

    def test_draft_status_on_new_row(self, doc, tests_rows):
        # find a TEST row without ehr to check 'draft' on insert
        for a in tests_rows:
            if doc.get(url(a)).json()["ehr"] is None:
                r = doc.put(url(a), json={"chief_complaint": "TEST only complaint"})
                assert r.status_code == 200
                assert r.json()["ehr"]["status"] == "draft"
                # share rejected: no diagnosis no meds
                s = doc.post(url(a, "/share"))
                print("share empty:", s.status_code, s.text)
                assert s.status_code == 400
                return
        pytest.skip("all TEST rows already have ehr")

    def test_share_rejected_without_diag_meds(self, doc, tests_rows):
        a = tests_rows[-1]
        r = doc.put(url(a), json={"chief_complaint": "TEST x", "diagnosis": "", "prescriptions": []})
        assert r.status_code == 200
        s = doc.post(url(a, "/share"))
        assert s.status_code == 400
        assert "diagnosis" in s.json()["detail"].lower()
        # restore
        doc.put(url(a), json=PAYLOAD)

    def test_followup_date_iso_string_day(self, doc, tests_rows):
        # BUG: frontend does follow_up_date.slice(0,10); API returns UTC iso so the day is shifted back by one
        g = doc.get(url(tests_rows[-1])).json()["ehr"]
        print("follow_up_date raw:", g["follow_up_date"])
        assert g["follow_up_date"][:10] == "2026-02-10"

    def test_invalid_followup_date(self, doc, tests_rows):
        r = doc.put(url(tests_rows[-1]), json={**PAYLOAD, "follow_up_date": "10-02-2026"})
        print("bad date:", r.status_code, r.text[:200])
        assert r.status_code in (400, 422), f"expected 4xx, got {r.status_code}"

    def test_complete_on_final_noop(self, doc, tests_rows):
        a = next((x for x in tests_rows if str(x["status"]).lower() in ("completed", "no_show")), None)
        if not a:
            pytest.skip()
        r = doc.put(url(a), json={**PAYLOAD, "complete": True})
        assert r.status_code == 200, r.text
        d = doc.get(f"{API}/provider/doctor/appointments").json()
        row = next(x for x in d["upcoming"] + d["past"] if x["id"] == a["id"])
        assert row["status"] == a["status"]
