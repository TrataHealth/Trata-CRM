# Admin onboarding (21 Provider-App sign-up types) + master-admin name/phone edit + no-login profile bulk actions
# Uses ONLY test phones 9000099000-9000099099; run `python scripts/cleanup_test_onboarding.py` afterwards.
import asyncio
import os

import asyncpg
import pytest
import requests
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
load_dotenv("/app/backend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
DB = os.environ.get("DATABASE_URL")
MEDP = "22222222-bbbb-4ccc-8ddd-pharmacymedp"
LAT, LNG = 26.85, 80.95
ADDR = {"address": "TEST 1 Street", "pincode": "226010", "city": "Lucknow", "state": "Uttar Pradesh"}


def q(sql, *a):
    async def run():
        c = await asyncpg.connect(DB, statement_cache_size=0)
        try:
            return await c.fetch(sql, *a)
        finally:
            await c.close()
    return asyncio.run(run())


def _login(phone, pwd):
    s = requests.Session()
    s.post(BASE_URL + "/api/auth/send-otp", json={"phone": phone})
    t = s.post(BASE_URL + "/api/auth/verify-otp", json={"phone": phone, "otp": "123456"}).json()["temp_token"]
    r = s.post(BASE_URL + "/api/auth/login-password", json={"password": pwd}, headers={"Authorization": "Bearer " + t}).json()
    s.headers["Authorization"] = "Bearer " + (r.get("token") or r.get("access_token"))
    return s


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def lookups(admin):
    h = admin.get(BASE_URL + "/api/admin/onboarding/lookup/hospital").json()["items"]
    a = admin.get(BASE_URL + "/api/admin/onboarding/lookup/ambulance_provider").json()["items"]
    return h[0]["id"], a[0]["id"]


HOSP = {"fullName": "TEST Admin", "name": "TEST Hosp", **ADDR, "licenseNumber": "TESTLIC1"}
CASES = {  # type: (phone, values, loc?, table, extra-check)
    "hospital": ("9000099001", HOSP, True, "hospital_profiles", "multi_specialty"),
    "cancer_care": ("9000099002", HOSP, True, "hospital_profiles", "specialised_centre"),
    "diabetes": ("9000099003", HOSP, True, "hospital_profiles", "specialised_centre"),
    "women_baby": ("9000099004", HOSP, True, "hospital_profiles", "specialised_centre"),
    "elderly_care": ("9000099005", HOSP, True, "hospital_profiles", "specialised_centre"),
    "nursing_home": ("9000099006", HOSP, True, "hospital_profiles", None),
    "skin_hair": ("9000099007", HOSP, True, "hospital_profiles", "specialised_centre"),
    "path_lab": ("9000099008", {"fullName": "TEST Lab Admin", "labName": "TEST Lab", "licenseNumber": "TL1", "pincode": "226010",
                                "city": "Lucknow", "state": "UP", "labAddress": "TEST addr"}, True, "path_lab_profiles", None),
    "diagnostic_centre": ("9000099009", {"fullName": "TEST DC Admin", "labName": "TEST DC", "licenseNumber": "TD1", "pincode": "226010",
                                         "city": "Lucknow", "state": "UP"}, True, "diagnostic_centre_profiles", None),
    "pharmacy": ("9000099010", {"businessName": "TEST Pharma", "ownerName": "TEST Owner", "licenseNumber": "TESTDL-9000099010", **ADDR},
                 True, "pharmacy_providers", None),
    "doctor": ("9000099011", {"fullName": "TEST Dr", "licenseNumber": "MCI1", "qualification": "MBBS", "doctorType": "clinic_doctor",
                              "clinicName": "TEST Clinic"}, False, "doctors", None),
    "nurse": ("9000099012", {"fullName": "TEST Nurse", "licenseNumber": "N1", "qualification": "GNM", "doctorType": "clinic_doctor"},
              False, "doctors", None),
    "mental_wellness": ("9000099013", {"subRole": "therapist", "fullName": "TEST Therapist", "qualifications": "MPhil"},
                        False, "wellness_professionals", None),
    "nutritionist": ("9000099014", {"fullName": "TEST Nutri", "qualifications": "MSc"}, False, "nutritionists", None),
    "ambulance_provider": ("9000099015", {"businessName": "TEST Amb", "ownerName": "TEST AmbOwner", "registrationNumber": "R1",
                                          "licenseNumber": "L1", **ADDR}, True, "ambulance_providers", None),
    "ambulance_driver": ("9000099016", {"fullName": "TEST Driver", "licenseNumber": "DL-TEST", "licenseCategory": "LMV-TR"},
                         False, "ambulance_driver_profiles", None),
    "paramedic": ("9000099017", {"fullName": "TEST Para", "qualification": "BPT"}, False, "paramedic_profiles", None),
    "blood_bank": ("9000099018", {"businessName": "TEST Blood Bank", "ownerName": "TEST Incharge", "licenseNumber": "BB1"},
                   False, "blood_banks", None),
    "wellness_event": ("9000099019", {"organiserName": "TEST Org", "displayName": "TEST Retreat"}, False, "wellness_event_providers", None),
    "veterinarian": ("9000099020", {"businessName": "TEST Vet", "ownerName": "TEST VetOwner"}, False, "vet_clinics", None),
    "dental": ("9000099021", {"businessName": "TEST Dental", "ownerName": "TEST DentOwner", "licenseNumber": "DC1"}, False, "dental_clinics", None),
}


def signup(admin, t, phone, values, loc=True):
    body = {"type": t, "phone": phone, "values": values}
    if loc:
        body.update(lat=LAT, lng=LNG)
    return admin.post(BASE_URL + "/api/admin/onboarding/signup", json=body, timeout=60)


class TestTypes:
    def test_provider_types(self, admin):
        r = admin.get(BASE_URL + "/api/admin/onboarding/provider-types")
        assert r.status_code == 200
        types = r.json()["types"]
        assert len(types) == 21
        assert {t["id"] for t in types} == set(CASES)
        assert len({t["category"] for t in types}) == 5
        assert all(t["fields"] and "col" not in t["fields"][0] for t in types)

    def test_lookups(self, lookups):
        assert lookups[0] and lookups[1]

    def test_non_master_403(self):
        s = _login("9000000001", "Trata@123")
        assert s.get(BASE_URL + "/api/admin/onboarding/provider-types").status_code == 403


class TestSignup:
    @pytest.mark.parametrize("t", list(CASES))
    def test_signup_creates_row(self, admin, lookups, t):
        phone, vals, loc, table, htype = CASES[t]
        vals = dict(vals)
        if t == "paramedic":
            vals["hospitalId"] = lookups[0]
        if t == "ambulance_driver":
            vals["ambulanceProviderId"] = lookups[1]
        r = signup(admin, t, phone, vals, loc)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["next"] == f"/admin/onboarding/{d['user_id']}"
        rows = q(f"select * from public.{table} where id::text = $1", d["profile_id"])
        assert rows and str(rows[0]["user_id"]) == d["user_id"], f"{t} not in {table}"
        if htype:
            assert rows[0]["hospital_type"] == htype
        u = q("select phone, role from public.users where id::text = $1", d["user_id"])
        assert u and u[0]["phone"].endswith(phone)
        if t in ("path_lab", "diagnostic_centre"):
            btbl, fk = {"path_lab": ("path_lab_branches", "path_lab_profile_id"),
                        "diagnostic_centre": ("diagnostic_centre_branches", "diagnostic_centre_profile_id")}[t]
            assert q(f"select 1 from public.{btbl} where {fk}::text = $1", d["profile_id"])

    def test_doctor_hospital_type(self, admin, lookups):
        r = signup(admin, "doctor", "9000099022", {"fullName": "TEST HospDr", "licenseNumber": "MCI2", "qualification": "MBBS",
                                                   "doctorType": "hospital_doctor", "hospitalId": lookups[0]}, False)
        assert r.status_code == 200, r.text
        row = q("select hospital_id, doctor_type from public.doctors where id::text=$1", r.json()["profile_id"])[0]
        assert str(row["hospital_id"]) == lookups[0] and row["doctor_type"] == "hospital_doctor"

    def test_duplicate_409(self, admin):
        r = signup(admin, "dental", "9000099021", CASES["dental"][1], False)
        assert r.status_code == 409, r.text

    def test_required_400(self, admin):
        r = signup(admin, "dental", "9000099030", {"businessName": "TEST X"}, False)
        assert r.status_code == 400 and "required" in r.json()["detail"]

    def test_bad_pincode_400(self, admin):
        r = signup(admin, "pharmacy", "9000099031", {**CASES["pharmacy"][1], "pincode": "12"})
        assert r.status_code == 400 and "pincode" in r.json()["detail"].lower()

    @pytest.mark.parametrize("t", ["hospital", "path_lab", "pharmacy", "ambulance_provider"])
    def test_latlng_required(self, admin, t):
        r = signup(admin, t, "9000099032", CASES[t][1], loc=False)
        assert r.status_code == 400 and "Latitude" in r.json()["detail"]


def providers(admin, **p):
    r = admin.get(BASE_URL + "/api/admin/directory/providers", params=p, timeout=90)
    assert r.status_code == 200
    return r.json()["items"]


class TestDirectory:
    @pytest.mark.parametrize("role,name", [("dental", "TEST Dental"), ("blood_bank", "TEST Blood Bank"), ("vet", "TEST Vet"),
                                           ("nutritionist", "TEST Nutri"), ("wellness", "TEST Therapist"),
                                           ("ambulance_driver", "TEST Driver"), ("wellness_event", "TEST Retreat")])
    def test_new_role_tabs(self, admin, role, name):
        items = providers(admin, role=role)
        assert any(name in ((i["org_name"] or "") + (i["admin_name"] or "")) for i in items), [i["org_name"] for i in items]

    def test_ravi_admin_name(self, admin):
        ravi = [i for i in providers(admin, role="pharmacy") if i["org_name"] == "Ravi Kumar"]
        assert ravi and ravi[0]["admin_name"] == "Ravi Kumar"

    def test_regression_doctor_patients(self, admin):
        docs = [i for i in providers(admin, role="doctor") if not (i["phone"] or "").startswith("90000990")]
        assert len(docs) == 5
        p = admin.get(BASE_URL + "/api/admin/patients", params={"limit": 500}, timeout=90).json()["patients"]
        assert len(p) == 10


class TestEdit:
    def _pharma(self, admin):
        return [i for i in providers(admin, role="pharmacy") if (i["phone"] or "").endswith("9000099010")
                or (i["org_name"] or "").startswith("TEST")][0]

    def test_edit_name_and_phone(self, admin):
        p = self._pharma(admin)
        r = admin.put(BASE_URL + f"/api/admin/directory/profiles/pharmacy_providers/{p['profile_id']}",
                      json={"provider_name": "TEST Pharma Renamed", "admin_name": "TEST Owner2", "phone": "9000099040"})
        assert r.status_code == 200, r.text
        row = q("select business_name, owner_name, phone from public.pharmacy_providers where id::text=$1", p["profile_id"])[0]
        assert (row["business_name"], row["owner_name"], row["phone"]) == ("TEST Pharma Renamed", "TEST Owner2", "9000099040")
        u = q("select phone, phone_key from public.users where id::text=$1", p["id"])[0]
        assert u["phone_key"] == "9000099040" and u["phone"].endswith("9000099040")
        print("users.phone after edit:", u["phone"])

    def test_users_phone_format_matches_provider_app(self, admin):
        # Provider App auth does exact `User.phone == data.phone` with 10-digit phone (all its users rows are 10-digit)
        u = q("select phone from public.users where phone_key = '9000099040'")
        assert u and u[0]["phone"] == "9000099040", f"users.phone stored as {u[0]['phone']!r}; Provider App login would miss it"

    def test_edit_phone_clash_409(self, admin):
        p = self._pharma(admin)
        r = admin.put(BASE_URL + f"/api/admin/directory/profiles/pharmacy_providers/{p['profile_id']}", json={"phone": "9000099001"})
        assert r.status_code == 409, r.text

    def test_edit_master_phone_400(self, admin):
        p = self._pharma(admin)
        r = admin.put(BASE_URL + f"/api/admin/directory/profiles/pharmacy_providers/{p['profile_id']}", json={"phone": "9873117605"})
        assert r.status_code == 400, r.text

    def test_edit_non_master_403(self):
        s = _login("9000000001", "Trata@123")
        r = s.put(BASE_URL + f"/api/admin/directory/profiles/pharmacy_providers/{MEDP}", json={"admin_name": "X"})
        assert r.status_code == 403

    def test_edit_no_login_admin_name_and_restore(self, admin):
        url = BASE_URL + f"/api/admin/directory/profiles/pharmacy_providers/{MEDP}"
        try:
            r = admin.put(url, json={"admin_name": "TEST Anita"})
            assert r.status_code == 200, r.text
            assert q("select owner_name from public.pharmacy_providers where id=$1", MEDP)[0]["owner_name"] == "TEST Anita"
        finally:
            admin.put(url, json={"admin_name": "Ms. Anita Singh"})
        assert q("select owner_name from public.pharmacy_providers where id=$1", MEDP)[0]["owner_name"] == "Ms. Anita Singh"

    def test_edit_person_doctor(self, admin):
        d = [i for i in providers(admin, role="doctor") if (i["phone"] or "").endswith("9000099011")][0]
        r = admin.put(BASE_URL + f"/api/admin/directory/profiles/doctors/{d['profile_id']}", json={"admin_name": "TEST Dr Renamed"})
        assert r.status_code == 200, r.text
        assert q("select full_name from public.doctors where id::text=$1", d["profile_id"])[0]["full_name"] == "TEST Dr Renamed"

    def test_edit_new_role_dental(self, admin):
        d = [i for i in providers(admin, role="dental") if (i["org_name"] or "") == "TEST Dental"][0]
        r = admin.put(BASE_URL + f"/api/admin/directory/profiles/dental_clinics/{d['profile_id']}", json={"admin_name": "TEST Dent2"})
        assert r.status_code == 200, f"new-role profiles not editable: {r.status_code} {r.text}"


class TestNoLoginBulk:
    def test_suspend_unsuspend_medplus(self, admin):
        u = BASE_URL + "/api/admin/users/bulk"
        r = admin.post(u, json={"profile_refs": [f"pharmacy_providers:{MEDP}"], "action": "suspend", "reason": "test suspend"})
        try:
            assert r.status_code == 200 and r.json()["updated"] == 1, r.text
            m = [i for i in providers(admin, role="pharmacy") if i["profile_id"] == MEDP][0]
            assert m["kyc_status"] != "verified" or m["is_suspended"]
        finally:
            r2 = admin.post(u, json={"profile_refs": [f"pharmacy_providers:{MEDP}"], "action": "unsuspend"})
        assert r2.status_code == 200, r2.text
        m = [i for i in providers(admin, role="pharmacy") if i["profile_id"] == MEDP][0]
        assert m["kyc_status"] == "verified"

    def test_bad_ref_400(self, admin):
        r = admin.post(BASE_URL + "/api/admin/users/bulk", json={"profile_refs": ["users:abc"], "action": "unsuspend"})
        assert r.status_code == 400
