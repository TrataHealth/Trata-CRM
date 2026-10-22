# ABDM Milestone 1 (ABHA create / verify) API tests — uses only fake Aadhaar/ABHA values.
import json
import os
import sys
import time

import pytest
import requests

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import BASE_URL, ENV, login  # noqa: E402

API = f"{BASE_URL}/api/abdm"
STATE = json.load(open("/tmp/ledger_probe_state.json"))


def H(t):
    return {"Authorization": f"Bearer {t}"}


def post(path, body, tok, retry=True):
    r = requests.post(f"{API}{path}", json=body, headers=H(tok), timeout=90)
    if retry and r.status_code >= 500:
        time.sleep(2)
        r = requests.post(f"{API}{path}", json=body, headers=H(tok), timeout=90)
    return r


@pytest.fixture(scope="session")
def tok_rep():
    tok, user = login("9000000002", "Trata@123")
    return tok


@pytest.fixture(scope="session")
def mongo():
    from pymongo import MongoClient
    return MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]


# ---- Status / RBAC ----
class TestStatusRBAC:
    def test_status_provider(self):
        r = requests.get(f"{API}/status", headers=H(STATE["tok_a"]), timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["connected"] is True, d
        assert d["environment"] == "sandbox"
        assert "NHA" in d["consent_text"]

    def test_status_admin(self):
        r = requests.get(f"{API}/status", headers=H(STATE["tok_admin"]), timeout=90)
        assert r.status_code == 200 and r.json()["connected"] is True, r.text

    def test_unauth_401(self):
        for m, p in [("get", "/status"), ("get", "/records"), ("post", "/enrol/otp"), ("post", "/verify/otp")]:
            r = getattr(requests, m)(f"{API}{p}", timeout=30)
            assert r.status_code in (401, 403), (p, r.status_code)
            print(p, r.status_code)

    def test_sales_rep_forbidden(self, tok_rep):
        res = {}
        res["status"] = requests.get(f"{API}/status", headers=H(tok_rep), timeout=60).status_code
        res["records"] = requests.get(f"{API}/records", headers=H(tok_rep), timeout=60).status_code
        res["enrol_consent_false"] = post("/enrol/otp", {"aadhaar": "123412341234", "consent": False}, tok_rep, retry=False).status_code
        print("sales rep:", res)
        assert all(v == 403 for v in res.values()), res


# ---- Enrol OTP ----
class TestEnrolOtp:
    def test_consent_false(self):
        r = post("/enrol/otp", {"aadhaar": "123412341234", "consent": False}, STATE["tok_a"])
        assert r.status_code == 400 and "Patient consent is required" in r.json()["detail"]

    def test_bad_aadhaar_422(self):
        for a in ["12345", "12341234123a", "1234123412345"]:
            r = post("/enrol/otp", {"aadhaar": a, "consent": True}, STATE["tok_a"])
            assert r.status_code == 422, (a, r.status_code)

    def test_fake_aadhaar_uidai(self, mongo):
        before = mongo.abdm_audit.count_documents({})
        r = post("/enrol/otp", {"aadhaar": "123412341234", "consent": True, "patient_phone": "9999900021"}, STATE["tok_a"])
        print(r.status_code, r.text)
        assert r.status_code == 400
        d = r.json()["detail"]
        assert d.startswith("ABDM: UIDAI Error code") or "multiple OTPs" in d, r.text  # ABDM throttles repeats for 30 min
        assert "{" not in r.json()["detail"]
        assert mongo.abdm_audit.count_documents({}) == before


# ---- Verify OTP ----
class TestVerifyOtp:
    def _v(self, method, ident, via="abdm"):
        return post("/verify/otp", {"method": method, "identifier": ident, "otp_via": via}, STATE["tok_a"])

    def test_abha_13_digits(self):
        r = self._v("abha-number", "91-1111-1111-111")
        assert r.status_code == 400 and "14 digits" in r.json()["detail"]

    def test_unknown_abha(self):
        r = self._v("abha-number", "91-1111-1111-1111")
        print(r.status_code, r.text)
        assert r.status_code == 400 and "ABDM: User not found" in r.json()["detail"]
        assert "{" not in r.json()["detail"]

    def test_unknown_abha_via_aadhaar(self):
        r = self._v("abha-number", "91-1111-1111-1111", "aadhaar")
        print(r.status_code, r.text)
        assert r.status_code == 400 and r.json()["detail"].startswith("ABDM:")

    def test_mobile_invalid(self):
        r = self._v("mobile", "abc")
        assert r.status_code == 400 and "10-digit" in r.json()["detail"]

    def test_aadhaar_5_digits(self):
        r = self._v("aadhaar", "12345")
        assert r.status_code == 400 and "12 digits" in r.json()["detail"]

    def test_abha_address_unknown(self):
        r = self._v("abha-address", "testprobezz998877")
        print(r.status_code, r.text)
        assert r.status_code == 400 and r.json()["detail"].startswith("ABDM:")
        assert "{" not in r.json()["detail"]

    def test_bad_method_422(self):
        r = self._v("email", "x@y.com")
        assert r.status_code == 422


# ---- Session (txn) scoping ----
class TestSessions:
    @pytest.mark.parametrize("path,body", [
        ("/enrol/verify", {"txn_id": "nope", "otp": "123456", "mobile": "9999900021"}),
        ("/enrol/mobile-otp", {"txn_id": "nope", "mobile": "9999900021"}),
        ("/enrol/mobile-verify", {"txn_id": "nope", "otp": "123456"}),
        ("/enrol/address", {"txn_id": "nope", "address": "testprobe123"}),
        ("/verify/confirm", {"txn_id": "nope", "otp": "123456"}),
        ("/verify/select", {"txn_id": "nope", "abha_number": "91-1111-1111-1111"}),
    ])
    def test_unknown_txn_404(self, path, body):
        r = post(path, body, STATE["tok_a"], retry=False)
        assert r.status_code == 404 and "Session not found" in r.json()["detail"], r.text

    def test_suggestions_unknown_404(self):
        r = requests.get(f"{API}/enrol/nope/suggestions", headers=H(STATE["tok_a"]), timeout=30)
        assert r.status_code == 404

    def test_cross_owner_txn(self, mongo):
        tid = "TEST_probe_txn_cross"
        mongo.abdm_txns.delete_many({"id": tid})
        mongo.abdm_txns.insert_one({"id": tid, "abdm_txn": tid, "kind": "verify", "owner": STATE["uid_a"], "scope": [],
                                    "phr": False, "method": "abha-number", "created_at": "x"})
        try:
            r = post("/verify/confirm", {"txn_id": tid, "otp": "123456"}, STATE["tok_b"], retry=False)
            assert r.status_code == 404, r.text
            r = post("/verify/select", {"txn_id": tid, "abha_number": "91-1111-1111-1111"}, STATE["tok_a"], retry=False)
            print("owner A select w/o t_token:", r.status_code, r.text)
            assert r.status_code in (400, 404)
            # kind mismatch: verify txn used on enrol endpoint
            r = post("/enrol/mobile-verify", {"txn_id": tid, "otp": "123456"}, STATE["tok_a"], retry=False)
            assert r.status_code == 404
        finally:
            mongo.abdm_txns.delete_many({"id": tid})


# ---- Records ----
class TestRecords:
    def test_records_scoping_and_search(self, mongo):
        ida, idb = "TEST_probe_rec_a", "TEST_probe_rec_b"
        mongo.abha_records.delete_many({"id": {"$in": [ida, idb]}})
        mongo.abha_records.insert_many([
            {"id": ida, "owner": STATE["uid_a"], "abha_number": "91-0000-0000-0001", "name": "TEST_probe Alpha", "updated_at": "2026-01-01"},
            {"id": idb, "owner": STATE["uid_b"], "abha_number": "91-0000-0000-0002", "name": "TEST_probe Beta", "updated_at": "2026-01-01"}])
        try:
            ra = requests.get(f"{API}/records", headers=H(STATE["tok_a"]), timeout=30).json()["records"]
            ids_a = {x["id"] for x in ra}
            assert ida in ids_a and idb not in ids_a
            assert all("owner" not in x for x in ra)
            rb = requests.get(f"{API}/records", headers=H(STATE["tok_b"]), timeout=30).json()["records"]
            assert idb in {x["id"] for x in rb} and ida not in {x["id"] for x in rb}
            radm = requests.get(f"{API}/records", headers=H(STATE["tok_admin"]), timeout=30).json()["records"]
            assert {ida, idb} <= {x["id"] for x in radm}
            rq = requests.get(f"{API}/records", params={"q": "alpha"}, headers=H(STATE["tok_admin"]), timeout=30).json()["records"]
            assert [x["id"] for x in rq if x["id"].startswith("TEST_probe")] == [ida]
            rq = requests.get(f"{API}/records", params={"q": "0000-0002"}, headers=H(STATE["tok_b"]), timeout=30).json()["records"]
            assert [x["id"] for x in rq] == [idb]
            rq = requests.get(f"{API}/records", params={"q": "(.*"}, headers=H(STATE["tok_a"]), timeout=30)
            assert rq.status_code == 200
            # PATCH link
            r = requests.patch(f"{API}/records/{ida}", json={"patient_phone": "9999900021", "note": "TEST_probe"}, headers=H(STATE["tok_a"]), timeout=30)
            assert r.status_code == 200 and r.json()["patient_phone"] == "9999900021"
            r = requests.patch(f"{API}/records/{ida}", json={"note": "x"}, headers=H(STATE["tok_b"]), timeout=30)
            assert r.status_code == 404
            # card: no session -> 409 for owner, 404 for other provider
            r = requests.get(f"{API}/records/{ida}/card", headers=H(STATE["tok_a"]), timeout=30)
            assert r.status_code == 409, r.text
            r = requests.get(f"{API}/records/{ida}/card", headers=H(STATE["tok_b"]), timeout=30)
            assert r.status_code == 404
        finally:
            mongo.abha_records.delete_many({"id": {"$in": [ida, idb]}})

    def test_bad_record_404(self):
        r = requests.patch(f"{API}/records/bad", json={"note": "x"}, headers=H(STATE["tok_a"]), timeout=30)
        assert r.status_code == 404
        r = requests.get(f"{API}/records/bad/card", headers=H(STATE["tok_a"]), timeout=30)
        assert r.status_code == 404


# ---- PII persistence ----
class TestPII:
    def test_no_aadhaar_or_otp_persisted(self, mongo):
        blob = json.dumps(list(mongo.abdm_txns.find({}, {"_id": 0}))) + json.dumps(list(mongo.abdm_audit.find({}, {"_id": 0})))
        assert "123412341234" not in blob
        assert "otp\":" not in blob.lower().replace("otp_", "")
        print("txns:", mongo.abdm_txns.count_documents({}), "audit:", mongo.abdm_audit.count_documents({}))
