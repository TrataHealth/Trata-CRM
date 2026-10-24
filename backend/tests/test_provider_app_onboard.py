"""Provider-app onboarding (job + poll) and hospital internal entities (CRM contact + provider portal).
WRITES TO SHARED SUPABASE PROD: only 1 pharmacy onboarding (TEST name) + 1 entity created then removed.
"""
import random
import sys
import time

import pytest
import requests
from pymongo import MongoClient

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import BASE_URL, ENV  # noqa: E402

API = f"{BASE_URL}/api"
OTP = "123456"
mdb = MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]
HOSP_CONTACT = "d256e122-8728-42b8-929b-1f03eca6f6db"
HOSP_PHONE = "9792832090"
HOSP_PWD = "TestHosp@123"
NOSB_CONTACT = "6d3d61ff-f5d6-42d3-8b78-d374dc4fe8e8"
AMB_CONTACT = "5050d227-a398-46e6-8eee-f57f52e33de7"
STATE = {}


def login(phone, pwd, login_as="staff"):
    requests.post(f"{API}/auth/send-otp", json={"phone": phone}, timeout=60)
    r = requests.post(f"{API}/auth/verify-otp", json={"phone": phone, "otp": OTP, "login_as": login_as}, timeout=60)
    assert r.status_code == 200, r.text
    d = r.json()
    ep = "set-password" if d.get("needs_password_setup") else "login-password"
    r = requests.post(f"{API}/auth/{ep}", json={"password": pwd}, headers={"Authorization": f"Bearer {d['temp_token']}"}, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    tok = j.get("token") or j.get("access_token")
    if j.get("user", {}).get("security_setup_required"):
        requests.post(f"{API}/auth/security-setup", headers={"Authorization": f"Bearer {tok}"}, json={
            "recovery_email": "delivered@resend.dev",
            "questions": [{"question_id": "q1", "answer": "trata"}, {"question_id": "q4", "answer": "trata"}]}, timeout=60)
    return tok, j.get("user")


def H(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture(scope="module")
def adm():
    return login("9873117605", "Master@123")[0]


@pytest.fixture(scope="module")
def rohan():
    return login("9000000002", "Trata@123")


@pytest.fixture(scope="module")
def priya():
    return login("9000000001", "Trata@123")[0]


@pytest.fixture(scope="module")
def hosp():
    return login(HOSP_PHONE, HOSP_PWD, "provider")


# --- onboard validation
class TestOnboardValidation:
    def test_invalid_role(self, adm):
        r = requests.post(f"{API}/admin/provider-app/onboard", headers=H(adm), json={"role_id": "bogus", "phone": "9123456789", "data": {}})
        assert r.status_code == 400, r.text

    def test_invalid_phone(self, adm):
        r = requests.post(f"{API}/admin/provider-app/onboard", headers=H(adm), json={"role_id": "pharmacy", "phone": "12345", "data": {}})
        assert r.status_code == 422

    def test_provider_forbidden(self, hosp):
        r = requests.post(f"{API}/admin/provider-app/onboard", headers=H(hosp[0]), json={"role_id": "pharmacy", "phone": "9123456789", "data": {}})
        assert r.status_code == 403, r.text

    def test_unknown_job_404(self, adm):
        r = requests.get(f"{API}/admin/provider-app/onboard/doesnotexist", headers=H(adm))
        assert r.status_code == 404


# --- onboarding by sales agent (pharmacy, ~12s)
class TestOnboardPharmacyByAgent:
    def test_onboard_job(self, rohan, priya, adm):
        tok, user = rohan
        phone = "9" + "".join(random.choice("0123456789") for _ in range(9))
        STATE["pharm_phone"] = phone
        lic = f"TESTDL{random.randint(100000, 999999)}"
        r = requests.post(f"{API}/admin/provider-app/onboard", headers=H(tok), json={"role_id": "pharmacy", "phone": phone, "data": {
            "ownerName": "TEST Owner", "businessName": f"TEST Pharmacy {phone[-4:]}", "email": "delivered@resend.dev",
            "drugLicenseNumber": lic, "address": "1 Test Street", "city": "Mumbai", "state": "Maharashtra", "pincode": "400001"}}, timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "running" and j["job_id"]
        jid = j["job_id"]
        # other non-master staff cannot see the job
        assert requests.get(f"{API}/admin/provider-app/onboard/{jid}", headers=H(priya)).status_code == 404
        st = None
        for _ in range(45):
            time.sleep(2)
            st = requests.get(f"{API}/admin/provider-app/onboard/{jid}", headers=H(tok)).json()
            if st["status"] != "running":
                break
        print("JOB", st)
        assert st["status"] == "done", st
        res = st["result"]
        assert res["success"] is True and res["status"] == "pending_kyc"
        assert res["supabase_user_id"] and res["contact_id"]
        assert res["welcome_email"] in ("sent", "failed")
        STATE["pharm_welcome"] = res["welcome_email"]
        STATE["pharm_contact"] = res["contact_id"]
        # master admin can view another user's job
        assert requests.get(f"{API}/admin/provider-app/onboard/{jid}", headers=H(adm)).status_code == 200
        c = mdb.contacts.find_one({"id": res["contact_id"]}, {"_id": 0})
        assert c["assigned_agent_id"] == user["id"]
        assert c["type"] == "pharmacy" and c["kyc_status"] == "pending" and c["pipeline_stage"] == "contacted"
        assert c["supabase_user_id"] == res["supabase_user_id"]
        assert mdb.activities.find_one({"contact_id": res["contact_id"], "subtype": "provider_onboarded"})

    def test_welcome_sent(self):
        assert STATE.get("pharm_welcome") == "sent", STATE.get("pharm_welcome")


# --- contact entities (CRM)
class TestContactEntities:
    def test_admin_list(self, adm):
        r = requests.get(f"{API}/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=H(adm), timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["root_kind"] == "hospital" and isinstance(d["entities"], list)

    def test_agent_list(self, rohan):
        r = requests.get(f"{API}/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=H(rohan[0]), timeout=60)
        assert r.status_code == 200, r.text

    def test_other_staff_403(self, priya):
        r = requests.get(f"{API}/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=H(priya), timeout=60)
        assert r.status_code == 403

    def test_no_supabase_400(self, adm):
        r = requests.get(f"{API}/admin/provider-app/contact-entities", params={"contact_id": NOSB_CONTACT}, headers=H(adm), timeout=60)
        assert r.status_code == 400, r.text

    def test_non_hospital_root_403(self, adm):
        r = requests.get(f"{API}/admin/provider-app/contact-entities", params={"contact_id": AMB_CONTACT}, headers=H(adm), timeout=60)
        assert r.status_code == 403, r.text

    def test_missing_fields_400(self, adm):
        r = requests.post(f"{API}/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=H(adm),
                          json={"entity_kind": "pharmacy", "name": "TEST x"}, timeout=60)
        assert r.status_code == 400

    def test_create_and_delete_by_agent(self, rohan):
        tok = rohan[0]
        phone = "9" + "".join(random.choice("0123456789") for _ in range(9))
        r = requests.post(f"{API}/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=H(tok), timeout=60, json={
            "entity_kind": "pharmacy", "name": f"TEST Branch Pharmacy {phone[-4:]}", "contact_person": "TEST Person",
            "dedicated_phone": phone, "address": "2 Test Rd", "city": "Mumbai"})
        assert r.status_code == 200, r.text
        print("CREATE", r.json())
        lst = requests.get(f"{API}/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=H(tok), timeout=60).json()
        ent = next((e for e in lst["entities"] if e.get("dedicated_phone") == phone), None)
        assert ent, lst
        d = requests.delete(f"{API}/admin/provider-app/contact-entities/{ent['id']}", params={"contact_id": HOSP_CONTACT}, headers=H(tok), timeout=60)
        assert d.status_code == 200, d.text
        lst = requests.get(f"{API}/admin/provider-app/contact-entities", params={"contact_id": HOSP_CONTACT}, headers=H(tok), timeout=60).json()
        e2 = next((e for e in lst["entities"] if e["id"] == ent["id"]), None)
        assert e2 is None or e2.get("is_active") is False


# --- provider portal entities
class TestProviderEntities:
    def test_provider_list(self, hosp):
        tok, user = hosp
        print("HOSP USER", {k: user.get(k) for k in ("role", "provider_type", "supabase_user_id")})
        r = requests.get(f"{API}/provider/entities", headers=H(tok), timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["root_kind"] == "hospital"

    def test_staff_forbidden(self, adm):
        r = requests.get(f"{API}/provider/entities", headers=H(adm), timeout=60)
        assert r.status_code == 403

    def test_provider_create_delete(self, hosp):
        tok = hosp[0]
        phone = "9" + "".join(random.choice("0123456789") for _ in range(9))
        r = requests.post(f"{API}/provider/entities", headers=H(tok), timeout=60, json={
            "entity_kind": "ambulance", "name": f"TEST Amb Unit {phone[-4:]}", "contact_person": "TEST Driver",
            "dedicated_phone": phone, "address": "3 Test Rd", "city": "Mumbai", "dispatch_radius_km": 10})
        assert r.status_code == 200, r.text
        lst = requests.get(f"{API}/provider/entities", headers=H(tok), timeout=60).json()
        ent = next((e for e in lst["entities"] if e.get("dedicated_phone") == phone), None)
        assert ent
        d = requests.delete(f"{API}/provider/entities/{ent['id']}", headers=H(tok), timeout=60)
        assert d.status_code == 200, d.text
