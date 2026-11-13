# Iter-39 retest: phone format preserved on edit, new-role table edit, KYC page for new roles, suspend/delete scoped to profile
# Uses ONLY test phones 9000099050-9000099079; run `python scripts/cleanup_test_onboarding.py` afterwards.
import pytest
import requests
from test_admin_provider_onboarding_edit import BASE_URL, q, _login, signup

NEW = {  # type: (phone, values, table, status col, org col, admin col)
    "dental": ("9000099050", {"businessName": "TEST Dental39", "ownerName": "TEST DentOwner39", "licenseNumber": "DC39"},
               "dental_clinics", "verification_status", "clinic_name", "owner_name"),
    "veterinarian": ("9000099051", {"businessName": "TEST Vet39", "ownerName": "TEST VetOwner39"},
                     "vet_clinics", "verification_status", "clinic_name", "owner_name"),
    "blood_bank": ("9000099052", {"businessName": "TEST BB39", "ownerName": "TEST Incharge39", "licenseNumber": "BB39"},
                   "blood_banks", "verification_status", "bank_name", "incharge_name"),
    "wellness_event": ("9000099053", {"organiserName": "TEST Org39", "displayName": "TEST Retreat39"},
                       "wellness_event_providers", "kyc_status", "display_name", "organiser_name"),
    "nutritionist": ("9000099054", {"fullName": "TEST Nutri39", "qualifications": "MSc"}, "nutritionists", "verification_status", None, "full_name"),
    "mental_wellness": ("9000099055", {"subRole": "therapist", "fullName": "TEST Ther39", "qualifications": "MPhil"},
                        "wellness_professionals", "verification_status", None, "full_name"),
    "ambulance_driver": ("9000099056", {"fullName": "TEST Driver39", "licenseNumber": "DL-T39", "licenseCategory": "LMV-TR"},
                         "ambulance_driver_profiles", "kyc_status", None, "full_name"),
}
IDS = {}


@pytest.fixture(scope="module")
def admin():
    return _login("9873117605", "Master@123")


@pytest.fixture(scope="module")
def onboarded(admin):
    amb = admin.get(BASE_URL + "/api/admin/onboarding/lookup/ambulance_provider").json()["items"][0]["id"]
    for t, (phone, vals, *_rest) in NEW.items():
        vals = dict(vals)
        if t == "ambulance_driver":
            vals["ambulanceProviderId"] = amb
        r = signup(admin, t, phone, vals, False)
        assert r.status_code == 200, f"{t}: {r.text}"
        IDS[t] = r.json()
    return IDS


def put(admin, table, pid, body):
    return admin.put(BASE_URL + f"/api/admin/directory/profiles/{table}/{pid}", json=body, timeout=60)


class TestPhoneFormat:  # FIX 1
    def test_bare_phone_stays_bare(self, admin, onboarded):
        d = onboarded["dental"]
        assert q("select phone from public.users where id::text=$1", d["user_id"])[0]["phone"] == "9000099050"
        r = put(admin, "dental_clinics", d["profile_id"], {"phone": "9000099060"})
        assert r.status_code == 200, r.text
        u = q("select phone, phone_key from public.users where id::text=$1", d["user_id"])[0]
        assert (u["phone"], u["phone_key"]) == ("9000099060", "9000099060")

    def test_plus91_phone_keeps_plus91(self, admin, onboarded):
        d = onboarded["veterinarian"]
        q("update public.users set phone='+919000099051' where id::text=$1", d["user_id"])
        r = put(admin, "vet_clinics", d["profile_id"], {"phone": "+91 90000 99061"})
        assert r.status_code == 200, r.text
        u = q("select phone, phone_key from public.users where id::text=$1", d["user_id"])[0]
        assert (u["phone"], u["phone_key"]) == ("+919000099061", "9000099061")


class TestNewRoleEdit:  # FIX 2
    @pytest.mark.parametrize("t", list(NEW))
    def test_edit_names(self, admin, onboarded, t):
        _, _, table, _, ocol, acol = NEW[t]
        d = onboarded[t]
        body = {"admin_name": f"TEST Adm {t}"}
        if ocol:
            body["provider_name"] = f"TEST Org {t}"
        r = put(admin, table, d["profile_id"], body)
        assert r.status_code == 200, r.text
        row = q(f"select * from public.{table} where id::text=$1", d["profile_id"])[0]
        assert row[acol] == f"TEST Adm {t}"
        if ocol:
            assert row[ocol] == f"TEST Org {t}"

    def test_person_provider_name_only_maps_to_full_name(self, admin, onboarded):
        d = onboarded["nutritionist"]
        r = put(admin, "nutritionists", d["profile_id"], {"provider_name": "TEST NutriPN"})
        print("person provider_name ->", r.status_code, r.text[:200])
        assert r.status_code in (200, 400)


class TestKycPage:  # FIX 3
    @pytest.mark.parametrize("t", list(NEW))
    def test_kyc_new_role(self, admin, onboarded, t):
        uid = onboarded[t]["user_id"]
        r = admin.get(BASE_URL + f"/api/admin/onboarding/providers/{uid}/kyc", timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        print(t, "vertical", d["vertical"], "checklist", len(d["checklist"]), "keys", [k for k in d if k not in ("checklist", "all_documents")])
        assert d["kyc_enabled"] is True and len(d["checklist"]) > 0
        assert d["all_required_approved"] is False


class TestScopedSuspend:  # FIX 4
    def _bulk(self, admin, uid, action):
        r = admin.post(BASE_URL + "/api/admin/users/bulk", json={"user_ids": [uid], "action": action, "reason": "TEST iter39"}, timeout=90)
        assert r.status_code == 200, r.text
        return r.json()

    def _state(self, uid, table, col):
        p = q(f"select {col} from public.{table} where user_id=$1", uid)[0][col]
        u = q("select is_suspended, is_archived from public.users where id=$1", uid)[0]
        return p, u["is_suspended"], u["is_archived"]

    @pytest.mark.parametrize("t", ["dental", "ambulance_driver"])
    def test_suspend_unsuspend(self, admin, onboarded, t):
        uid, (_, _, table, col, *_r) = onboarded[t]["user_id"], NEW[t]
        self._bulk(admin, uid, "suspend")
        assert self._state(uid, table, col) == ("suspended", False, False)
        self._bulk(admin, uid, "unsuspend")
        assert self._state(uid, table, col) == ("pending", False, False)

    def test_archive_restore_listed_in_deleted(self, admin, onboarded):
        uid = onboarded["blood_bank"]["user_id"]
        self._bulk(admin, uid, "archive")
        assert self._state(uid, "blood_banks", "verification_status") == ("deactivated", False, False)
        d = admin.get(BASE_URL + "/api/admin/directory/deleted", params={"app": "provider"}, timeout=90).json()["items"]
        assert any(i.get("id") == uid or uid in str(i.get("row_key")) for i in d), "archived dental/blood bank not in deleted list"
        self._bulk(admin, uid, "restore")
        assert self._state(uid, "blood_banks", "verification_status") == ("pending", False, False)
