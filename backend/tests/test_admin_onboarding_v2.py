"""Backend tests for admin onboarding (Iter 11) — canonical users + vertical profile
writes with location, admin/geocode, admin/migrations/hospital-verified, patient
detail now reading from consultation_bookings, approve-all with KYC uploads.

CRITICAL: shared production Supabase. Every test row uses TEST/probe in name and
phones 9999900000-9999900009. Cleanup runs in a module teardown fixture.
"""
import base64
import os
import uuid

import asyncio
import asyncpg
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as fh:
        for line in fh:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break

OTP = "123456"
ADMIN_PHONE = "9873117605"
ADMIN_PWD = "Master@123"

# Phones MUST be test-safe (9999900001..) — cleanup wipes them at end.
PHONE_HOSPITAL = "9999900001"
PHONE_PATHOLOGY = "9999900002"
PHONE_AMBULANCE = "9999900003"
PHONE_DOCTOR = "9999900004"
PHONE_HOSPITAL_NOCOORD = "9999900005"  # negative-case probe
TEST_PHONES = [PHONE_HOSPITAL, PHONE_PATHOLOGY, PHONE_AMBULANCE, PHONE_DOCTOR,
               PHONE_HOSPITAL_NOCOORD]

# Known Mumbai lat/lng for test rows
LAT, LNG = 19.1178, 72.8631  # Andheri area

DATABASE_URL = os.environ.get("DATABASE_URL") or ""
if not DATABASE_URL:
    with open("/app/backend/.env") as fh:
        for line in fh:
            if line.startswith("DATABASE_URL="):
                DATABASE_URL = line.split("=", 1)[1].strip().strip('"')
                break


# ──────── Auth helpers ────────────────────────────────────────────────────
def _login_admin() -> str:
    s = requests.Session()
    s.headers["Content-Type"] = "application/json"
    r = s.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": ADMIN_PHONE}, timeout=20)
    assert r.status_code == 200, r.text
    r = s.post(f"{BASE_URL}/api/auth/verify-otp",
               json={"phone": ADMIN_PHONE, "otp": OTP}, timeout=20)
    assert r.status_code == 200, r.text
    temp = r.json()["temp_token"]
    r = s.post(f"{BASE_URL}/api/auth/login-password",
               json={"password": ADMIN_PWD},
               headers={"Authorization": f"Bearer {temp}"}, timeout=20)
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="module")
def admin_token():
    return _login_admin()


@pytest.fixture(scope="module")
def hdr(admin_token):
    return {"Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json"}


# ──────── DB cleanup ──────────────────────────────────────────────────────
async def _cleanup_async():
    conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
    try:
        # Collect user_ids for test phones
        rows = await conn.fetch(
            "SELECT id FROM public.users WHERE phone = ANY($1::text[])",
            TEST_PHONES)
        ids = [str(r["id"]) for r in rows]
        if not ids:
            return
        # Child cleanup first
        await conn.execute("""DELETE FROM public.labs
             WHERE pathologist_profile_id IN
                (SELECT id FROM public.pathologists WHERE user_id = ANY($1::text[]))""",
                           ids)
        await conn.execute(
            "DELETE FROM public.kyc_documents WHERE user_id = ANY($1::text[])", ids)
        await conn.execute(
            "DELETE FROM public.hospital_bed_inventory WHERE hospital_id IN "
            "(SELECT id FROM public.hospital_profiles WHERE user_id = ANY($1::text[]))",
            ids)
        await conn.execute(
            "DELETE FROM public.hospital_profiles WHERE user_id = ANY($1::text[])", ids)
        await conn.execute(
            "DELETE FROM public.pathologists WHERE user_id = ANY($1::text[])", ids)
        await conn.execute(
            "DELETE FROM public.ambulance_providers WHERE user_id = ANY($1::text[])", ids)
        await conn.execute(
            "DELETE FROM public.doctors WHERE user_id = ANY($1::text[])", ids)
        await conn.execute(
            "DELETE FROM public.users WHERE id = ANY($1::text[])", ids)
    finally:
        await conn.close()


async def _cleanup_mongo_async():
    # Clean CRM mirror rows
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
        with open("/app/backend/.env") as fh:
            env = {}
            for line in fh:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k] = v.strip().strip('"')
        client = AsyncIOMotorClient(env["MONGO_URL"].strip('"'))
        db = client[env["DB_NAME"].strip('"')]
        await db.crm_users.delete_many({"phone": {"$in": TEST_PHONES}})
        await db.contacts.delete_many({"phone": {"$in": TEST_PHONES}})
        client.close()
    except Exception as e:
        print(f"mongo cleanup skipped: {e}")


@pytest.fixture(scope="module", autouse=True)
def _module_cleanup():
    # Pre-clean leftovers from previous aborted runs
    asyncio.get_event_loop().run_until_complete(_cleanup_async())
    asyncio.get_event_loop().run_until_complete(_cleanup_mongo_async())
    yield
    asyncio.get_event_loop().run_until_complete(_cleanup_async())
    asyncio.get_event_loop().run_until_complete(_cleanup_mongo_async())


# ──────── Tests ───────────────────────────────────────────────────────────
class TestGeocode:
    def test_geocode_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/admin/geocode", params={"q": "Andheri, Mumbai"},
                         timeout=20)
        # No auth → 401 or 403
        assert r.status_code in (401, 403), r.text

    def test_geocode_valid_query(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/geocode",
                         params={"q": "Andheri, Mumbai"}, headers=hdr, timeout=25)
        # 502 is acceptable (upstream rate-limit per spec)
        if r.status_code == 502:
            pytest.skip("Nominatim rate-limited")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "results" in data and isinstance(data["results"], list)
        if data["results"]:
            first = data["results"][0]
            assert "lat" in first and "lng" in first
            assert isinstance(first["lat"], (int, float))


class TestMigration:
    def test_migrate_hospital_verified(self, hdr):
        r = requests.post(f"{BASE_URL}/api/admin/migrations/hospital-verified",
                          headers=hdr, timeout=25)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("success") is True
        assert "migrated" in data and isinstance(data["migrated"], int)


class TestOnboardingValidation:
    """Non-doctor verticals require lat/lng; doctor doesn't."""

    def _payload(self, vertical, phone, name, **extra):
        p = {"vertical": vertical, "phone": phone, "name": name,
             "city": "Mumbai", "state": "Maharashtra",
             "email": "probe@test.local", "address": "TEST address"}
        p.update(extra)
        return p

    def test_hospital_without_coords_400(self, hdr):
        body = self._payload("hospital", PHONE_HOSPITAL_NOCOORD, "TEST Probe Hospital NoCoord")
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=25)
        assert r.status_code == 400, r.text
        assert "lat" in r.text.lower() or "coord" in r.text.lower()

    def test_ambulance_without_coords_400(self, hdr):
        body = self._payload("ambulance", PHONE_HOSPITAL_NOCOORD, "TEST Probe Amb NoCoord")
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=25)
        assert r.status_code == 400, r.text

    def test_pathology_without_coords_400(self, hdr):
        body = self._payload("pathology", PHONE_HOSPITAL_NOCOORD, "TEST Probe Path NoCoord")
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=25)
        assert r.status_code == 400, r.text

    def test_hospital_with_invalid_coords_400(self, hdr):
        body = self._payload("hospital", PHONE_HOSPITAL_NOCOORD, "TEST Probe",
                             lat=0, lng=0)
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=25)
        assert r.status_code == 400, r.text

    def test_doctor_without_coords_ok(self, hdr):
        body = self._payload("doctor", PHONE_DOCTOR, "TEST Dr Probe")
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=25)
        assert r.status_code == 200, r.text
        assert r.json().get("success") is True


class TestOnboardingCreation:
    """Create each vertical with lat/lng and verify canonical row shape in Supabase."""

    def test_onboard_hospital_writes_canonical(self, hdr):
        body = {"vertical": "hospital", "phone": PHONE_HOSPITAL,
                "name": "TEST Probe Hospital", "city": "Mumbai", "state": "MH",
                "email": "probe-hosp@test.local", "address": "TEST addr Mumbai",
                "lat": LAT, "lng": LNG}
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["success"] and data["user_id"]

        # DB-side verify
        async def _check():
            conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
            try:
                u = await conn.fetchrow(
                    "SELECT role, verification_status FROM public.users WHERE id=$1",
                    data["user_id"])
                assert u is not None
                assert u["verification_status"] == "pending"
                hp = await conn.fetchrow(
                    "SELECT user_id, location::text AS loc, verification_status "
                    "FROM public.hospital_profiles WHERE user_id=$1::text",
                    data["user_id"])
                assert hp is not None
                assert hp["verification_status"] == "pending_review"
                import json as _j
                loc = _j.loads(hp["loc"])
                assert abs(loc["lat"] - LAT) < 0.001
                assert abs(loc["lng"] - LNG) < 0.001
            finally:
                await conn.close()
        asyncio.get_event_loop().run_until_complete(_check())

    def test_onboard_pathology_also_creates_labs_row(self, hdr):
        body = {"vertical": "pathology", "phone": PHONE_PATHOLOGY,
                "name": "TEST Probe Pathology", "city": "Mumbai", "state": "MH",
                "email": "probe-path@test.local", "address": "TEST addr",
                "lat": LAT, "lng": LNG}
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        uid = r.json()["user_id"]

        async def _check():
            conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
            try:
                p = await conn.fetchrow(
                    "SELECT id, status, is_active, is_verified, latitude, longitude, "
                    "location::text AS loc FROM public.pathologists WHERE user_id=$1::text",
                    uid)
                assert p is not None
                assert p["status"] == "pending"
                assert p["is_active"] is True
                assert p["is_verified"] is False
                assert abs(float(p["latitude"]) - LAT) < 0.001
                assert p["loc"] is not None
                # labs row linked
                lab = await conn.fetchrow(
                    "SELECT id, is_active, is_verified FROM public.labs "
                    "WHERE pathologist_profile_id=$1", p["id"])
                assert lab is not None
                assert lab["is_active"] is False
                assert lab["is_verified"] is False
            finally:
                await conn.close()
        asyncio.get_event_loop().run_until_complete(_check())

    def test_onboard_ambulance_writes_business_lat_lng(self, hdr):
        body = {"vertical": "ambulance", "phone": PHONE_AMBULANCE,
                "name": "TEST Probe Ambulance", "city": "Mumbai", "state": "MH",
                "email": "probe-amb@test.local", "address": "TEST addr",
                "lat": LAT, "lng": LNG}
        r = requests.post(f"{BASE_URL}/api/admin/onboarding/providers",
                          json=body, headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        uid = r.json()["user_id"]

        async def _check():
            conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
            try:
                a = await conn.fetchrow(
                    "SELECT status, business_lat, business_lng "
                    "FROM public.ambulance_providers WHERE user_id=$1::text", uid)
                assert a is not None
                assert a["status"] == "pending"
                assert abs(float(a["business_lat"]) - LAT) < 0.001
                assert abs(float(a["business_lng"]) - LNG) < 0.001
            finally:
                await conn.close()
        asyncio.get_event_loop().run_until_complete(_check())


class TestApproveAll:
    """After uploading required KYC docs, approve-all should flip profile to verified."""

    def _onboarded_user(self):
        # Find hospital user created above
        async def _f():
            conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
            try:
                r = await conn.fetchval(
                    "SELECT id FROM public.users WHERE phone=$1", PHONE_HOSPITAL)
                return str(r) if r else None
            finally:
                await conn.close()
        return asyncio.get_event_loop().run_until_complete(_f())

    def test_approve_all_requires_docs(self, hdr):
        uid = self._onboarded_user()
        if not uid:
            pytest.skip("hospital onboarding did not run")
        r = requests.post(
            f"{BASE_URL}/api/admin/onboarding/providers/{uid}/approve-all",
            headers=hdr, timeout=30)
        assert r.status_code == 400, r.text
        detail = r.json().get("detail", {})
        if isinstance(detail, dict):
            assert detail.get("error") == "required_docs_missing"

    def test_upload_docs_and_approve_hospital(self, hdr):
        uid = self._onboarded_user()
        if not uid:
            pytest.skip("hospital onboarding did not run")
        # Fetch the required docs
        r = requests.get(f"{BASE_URL}/api/admin/onboarding/providers/{uid}/kyc",
                         headers=hdr, timeout=25)
        assert r.status_code == 200, r.text
        checklist = r.json()["checklist"]
        required = [c for c in checklist if c.get("required")]
        assert required, "hospital must have required docs"

        tiny_b64 = base64.b64encode(b"TEST probe kyc doc content").decode()
        for item in required:
            u = requests.post(
                f"{BASE_URL}/api/admin/onboarding/providers/{uid}/kyc/upload",
                json={"document_type": item["key"],
                      "document_name": f"TEST {item['label'] if 'label' in item else item['key']}",
                      "file_base64": tiny_b64},
                headers=hdr, timeout=25)
            assert u.status_code == 200, u.text

        # Now approve-all should succeed
        r = requests.post(
            f"{BASE_URL}/api/admin/onboarding/providers/{uid}/approve-all",
            headers=hdr, timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("success") is True

        async def _verify():
            conn = await asyncpg.connect(DATABASE_URL, statement_cache_size=0)
            try:
                u = await conn.fetchrow(
                    "SELECT verification_status FROM public.users WHERE id=$1", uid)
                assert u["verification_status"] == "verified"
                hp = await conn.fetchrow(
                    "SELECT verification_status FROM public.hospital_profiles WHERE user_id=$1::text",
                    uid)
                assert hp["verification_status"] == "verified"
            finally:
                await conn.close()
        asyncio.get_event_loop().run_until_complete(_verify())


class TestPatientDetail:
    """Patient-app users have role NULL/'customer'. 9afe9c0c… is a live NULL-role
    patient-app user with 1 SOS case. consultation_bookings patient ids currently
    have no users row, so only shape is asserted for appointments."""

    PID = "9afe9c0c-3cb9-4827-b144-bcef70ef2bd9"

    def test_patient_detail_includes_appointments(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/patients/{self.PID}",
                         headers=hdr, timeout=25)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("patient", {}).get("id") == self.PID
        assert isinstance(data.get("appointments"), list)
        for a0 in data["appointments"]:
            for k in ("doctor_name", "hospital_name", "appointment_date"):
                assert k in a0

    def test_patient_detail_lab_bookings_field(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/patients/{self.PID}",
                         headers=hdr, timeout=25)
        assert r.status_code == 200
        assert isinstance(r.json()["lab_bookings"], list)

    def test_patient_roster_nonempty_and_no_test_rows(self, hdr):
        r = requests.get(f"{BASE_URL}/api/admin/patients", headers=hdr, timeout=25)
        assert r.status_code == 200
        ps = r.json()["patients"]
        assert len(ps) >= 1
        assert not any("test" in (p.get("name") or "").lower() for p in ps)
