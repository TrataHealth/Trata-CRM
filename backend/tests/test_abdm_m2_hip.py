# ABDM Milestone 2 (CRM as HIP) — inbound /api/v3 callbacks, link engine, consent/HI flow, CRM ABDM APIs, QR check-in.
# Uses only fake ABHA values and Mongo TEST_probe docs. Requires `python ledger_probe_fixtures.py setup` first.
import json
import os
import sys
import time
import uuid

import pytest
import requests

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import BASE_URL, ENV, login  # noqa: E402

STATE = json.load(open("/tmp/ledger_probe_state.json"))
HIP = "IN0910034478"
PID = "TEST_probe_patient_hip"
REF = "DS-TEST_probe-1"
API = f"{BASE_URL}/api/abdm"


def A(t):
    return {"Authorization": f"Bearer {t}"}


from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
import jwt as pyjwt  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_KID = "TEST_probe_kid"


def _token(key=_KEY, kid=_KID, exp=300):
    return pyjwt.encode({"sub": "gateway", "exp": int(time.time()) + exp}, key, algorithm="RS256", headers={"kid": kid})


def CB(**extra):
    return {"Authorization": f"Bearer {_token()}", "X-HIP-ID": HIP, "REQUEST-ID": str(uuid.uuid4()), "Content-Type": "application/json", **extra}


@pytest.fixture(scope="session")
def mongo():
    from pymongo import MongoClient
    return MongoClient(ENV["MONGO_URL"])[ENV["DB_NAME"]]


@pytest.fixture(scope="session")
def tok_rep():
    tok, _ = login("9000000002", "Trata@123")
    return tok


@pytest.fixture(scope="session", autouse=True)
def seed(mongo):
    jwk = json.loads(pyjwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key()))
    saved = mongo.abdm_meta.find_one({"_id": "gateway_jwks"})
    mongo.abdm_meta.update_one({"_id": "gateway_jwks"}, {"$set": {"keys": [{**jwk, "kid": _KID, "alg": "RS256", "use": "sig"}], "at": time.time()}}, upsert=True)
    time.sleep(1)
    mongo.abha_records.update_one({"abha_number": "91-0000-0000-0001", "owner": "trata"}, {"$set": {
        "id": "TEST_probe_rec", "owner": "trata", "abha_number": "91-0000-0000-0001", "abha_address": "testprobe01@sbx",
        "name": "TEST_probe Patient", "gender": "M", "patient_user_id": PID, "year_of_birth": 1990}}, upsert=True)
    mongo.abdm_care_contexts.update_one({"reference": REF}, {"$set": {
        "id": "cc1", "reference": REF, "hi_type": "DischargeSummary", "display": "Discharge summary · TEST_probe",
        "record_date": "2026-10-01T10:00:00+00:00", "record": {"final_diagnosis": "Dengue", "treatment_given": "IV fluids"},
        "patient_user_id": PID, "abha_number": "91-0000-0000-0001", "abha_address": "testprobe01@sbx",
        "provider_name": "TEST_probe Hospital", "status": "new", "attempts": 5}}, upsert=True)
    yield
    if saved:
        mongo.abdm_meta.replace_one({"_id": "gateway_jwks"}, saved)
    else:
        mongo.abdm_meta.delete_one({"_id": "gateway_jwks"})


# ---- Inbound callbacks: status codes, latency, auth/facility guards ----
CALLBACKS = [("/hip/token/on-generate-token", 200), ("/hip/patient/care-context/discover", 202),
             ("/hip/link/care-context/init", 202), ("/hip/link/care-context/confirm", 200),
             ("/hip/health-information/request", 202), ("/consent/request/hip/notify", 200),
             ("/hiu/consent/request/on-init", 200), ("/hiu/consent/on-notify", 200), ("/hiu/consent/on-fetch", 200),
             ("/hiu/health-information/on-request", 200), ("/hiu/health-information/transfer", 202),
             ("/link/on_carecontext", 200), ("/some/unknown/TEST_probe", 202)]


class TestCallbacks:
    @pytest.mark.parametrize("path,code", CALLBACKS)
    def test_status_and_latency(self, path, code, mongo):
        h = CB()
        t0 = time.time()
        r = requests.post(f"{BASE_URL}/api/v3{path}", headers=h, json={"TEST_probe": True}, timeout=30)
        dt = time.time() - t0
        assert r.status_code == code, (path, r.status_code, r.text)
        assert dt < 3, (path, dt)
        doc = mongo.abdm_callbacks.find_one({"request_id": h["REQUEST-ID"]})
        assert doc and doc["path"] == f"/api/v3{path}" and doc["target"] == HIP

    @pytest.mark.parametrize("path,code", CALLBACKS[:3] + CALLBACKS[6:8])
    def test_no_auth_401(self, path, code):
        r = requests.post(f"{BASE_URL}/api/v3{path}", headers={"X-HIP-ID": HIP}, json={}, timeout=30)
        assert r.status_code == 401, (path, r.status_code)

    def test_wrong_hip_400(self):
        r = requests.post(f"{BASE_URL}/api/v3/hip/token/on-generate-token", headers=CB(**{"X-HIP-ID": "IN999"}), json={}, timeout=30)
        assert r.status_code == 400

    def test_wrong_hiu_400(self):
        h = CB()
        h.pop("X-HIP-ID")
        h["X-HIU-ID"] = "IN999"
        r = requests.post(f"{BASE_URL}/api/v3/hiu/consent/on-notify", headers=h, json={}, timeout=30)
        assert r.status_code == 400

    def test_hiu_header_ok(self):
        h = CB()
        h.pop("X-HIP-ID")
        h["X-HIU-ID"] = HIP
        r = requests.post(f"{BASE_URL}/api/v3/hiu/consent/on-notify", headers=h, json={}, timeout=30)
        assert r.status_code == 200

    def test_non_json_body_no_500(self):
        r = requests.post(f"{BASE_URL}/api/v3/hip/token/on-generate-token", headers={**CB(), "Content-Type": "text/plain"},
                          data="not json", timeout=30)
        assert r.status_code == 200, r.text

    def test_keymaterial_stripped(self, mongo):
        h = CB()
        r = requests.post(f"{BASE_URL}/api/v3/hip/health-information/request", headers=h, json={
            "transactionId": "tx-TEST_probe-strip", "hiRequest": {"consent": {"id": "TEST_probe-none"}, "keyMaterial": {"nonce": "SECRET"}}}, timeout=30)
        assert r.status_code == 202
        doc = mongo.abdm_callbacks.find_one({"request_id": h["REQUEST-ID"]})
        assert "keyMaterial" not in doc["body"]["hiRequest"]


# ---- Patient-initiated link: discover -> init -> confirm (bad, good) ----
class TestUserInitiatedLink:
    def test_flow(self, mongo):
        mongo.abdm_care_contexts.update_one({"reference": REF}, {"$set": {"status": "new", "attempts": 5}})
        tx = f"tx-TEST_probe-{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/v3/hip/patient/care-context/discover", headers=CB(), json={
            "transactionId": tx, "patient": {"id": "testprobe01@sbx", "verifiedIdentifiers": [{"type": "ABHA_ADDRESS", "value": "testprobe01@sbx"}]}}, timeout=30)
        assert r.status_code == 202
        r = requests.post(f"{BASE_URL}/api/v3/hip/link/care-context/init", headers=CB(), json={
            "transactionId": tx, "abhaAddress": "testprobe01@sbx", "patient": [{"referenceNumber": PID, "careContexts": [{"referenceNumber": REF}],
                                                                               "hiType": "DischargeSummary", "count": 1}]}, timeout=30)
        assert r.status_code == 202
        lr = None
        for _ in range(20):
            time.sleep(1)
            lr = mongo.abdm_link_requests.find_one({"transaction_id": tx})
            if lr:
                break
        assert lr and lr["status"] == "otp_sent" and len(lr["otp_display"]) == 6 and lr["references"] == [REF]
        # admin sees it in link-requests
        rows = requests.get(f"{API}/link-requests", headers=A(STATE["tok_admin"]), timeout=30).json()["link_requests"]
        assert any(x["id"] == lr["id"] and "otp_hash" not in x for x in rows)
        bad = "000000" if lr["otp_display"] != "000000" else "111111"
        r = requests.post(f"{BASE_URL}/api/v3/hip/link/care-context/confirm", headers=CB(), json={
            "confirmation": {"linkRefNumber": lr["id"], "token": bad}}, timeout=30)
        assert r.status_code == 200
        time.sleep(3)
        lr2 = mongo.abdm_link_requests.find_one({"id": lr["id"]})
        assert lr2["attempts"] == 1 and lr2["status"] == "otp_sent"
        assert mongo.abdm_care_contexts.find_one({"reference": REF})["status"] != "linked"
        r = requests.post(f"{BASE_URL}/api/v3/hip/link/care-context/confirm", headers=CB(), json={
            "confirmation": {"linkRefNumber": lr["id"], "token": lr["otp_display"]}}, timeout=30)
        assert r.status_code == 200
        for _ in range(15):
            time.sleep(1)
            cc = mongo.abdm_care_contexts.find_one({"reference": REF})
            if cc["status"] == "linked":
                break
        assert cc["status"] == "linked" and cc["linked_via"] == "patient_initiated"
        lr3 = mongo.abdm_link_requests.find_one({"id": lr["id"]})
        assert lr3["status"] == "linked" and "otp_display" not in lr3


# ---- Gateway JWT verification ----
class TestCallbackAuth:
    def test_forged_tokens_rejected(self):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        for tok in ("x", _token(key=other), _token(exp=-60), _token(kid="unknown-kid", key=other)):
            r = requests.post(f"{BASE_URL}/api/v3/consent/request/hip/notify", headers={**CB(), "Authorization": f"Bearer {tok}"},
                              json={"notification": {"status": "GRANTED", "consentId": "TEST_probe-forged"}}, timeout=30)
            assert r.status_code == 401, (tok[:10], r.status_code, r.text)

    def test_signed_token_accepted(self):
        r = requests.post(f"{BASE_URL}/api/v3/hiu/consent/on-fetch", headers=CB(), json={"TEST_probe": True}, timeout=30)
        assert r.status_code == 200, r.text


# ---- Consent notify + health-information request ----
class TestConsentHI:
    def test_consent_and_hi(self, mongo):
        from dotenv import load_dotenv  # noqa: F401
        sys.path.insert(0, "/app/backend")
        from abdm_ecdh import generate_key_material
        cid = f"TEST_probe-consent-{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/v3/consent/request/hip/notify", headers=CB(), json={"notification": {
            "status": "GRANTED", "consentId": cid, "consentDetail": {
                "consentId": cid, "patient": {"id": "testprobe01@sbx"}, "careContexts": [{"patientReference": PID, "careContextReference": REF}],
                "hiTypes": ["DischargeSummary"], "purpose": {"code": "CAREMGT", "text": "Care Management"}, "hiu": {"id": "TEST_HIU"},
                "permission": {"dateRange": {"from": "2026-01-01T00:00:00Z", "to": "2026-12-31T00:00:00Z"}}}}}, timeout=30)
        assert r.status_code == 200
        c = mongo.abdm_consents.find_one({"consent_id": cid})
        assert c and c["status"] == "GRANTED" and c["care_contexts"] == [REF]
        rows = requests.get(f"{API}/consents", headers=A(STATE["tok_admin"]), timeout=30).json()["consents"]
        assert any(x["consent_id"] == cid for x in rows)
        km = generate_key_material()
        tx = f"tx-HI-TEST_probe-{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/v3/hip/health-information/request", headers=CB(), json={"transactionId": tx, "hiRequest": {
            "consent": {"id": cid}, "dateRange": {"from": "2026-01-01T00:00:00Z", "to": "2026-12-31T00:00:00Z"},
            "dataPushUrl": f"{BASE_URL}/api/v3/hiu/health-information/transfer", "keyMaterial": {
                "cryptoAlg": "ECDH", "curve": "Curve25519", "dhPublicKey": {"expiry": "x", "parameters": "Curve25519/32byte random key",
                                                                          "keyValue": km.x509_public_key}, "nonce": km.nonce}}}, timeout=30)
        assert r.status_code == 202
        t = None
        for _ in range(45):
            time.sleep(2)
            t = mongo.abdm_transfers.find_one({"transaction_id": tx})
            if t:
                break
        print("transfer", t and (t["pushed"], t["statuses"]))
        assert t, "no abdm_transfers doc within 90s"
        assert t["references"] == [REF]
        assert all(s["hiStatus"] in ("DELIVERED", "ERRORED") for s in t["statuses"])
        out = list(mongo.abdm_callbacks.find({"kind": "outbound"}).sort("at", -1).limit(5))
        assert out and all("status" in o for o in out)
        print([(o["path"], o["status"], (o.get("error") or "")[:60]) for o in out])

    def _consent_then_hi(self, mongo, hi_types, rng):
        from abdm_ecdh import generate_key_material
        cid = f"TEST_probe-consent-{uuid.uuid4().hex[:6]}"
        requests.post(f"{BASE_URL}/api/v3/consent/request/hip/notify", headers=CB(), json={"notification": {
            "status": "GRANTED", "consentId": cid, "consentDetail": {"consentId": cid, "patient": {"id": "testprobe01@sbx"},
                "careContexts": [{"patientReference": PID, "careContextReference": REF}], "hiTypes": hi_types,
                "permission": {"dateRange": rng}}}}, timeout=30)
        km = generate_key_material()
        tx = f"tx-HI-TEST_probe-{uuid.uuid4().hex[:6]}"
        requests.post(f"{BASE_URL}/api/v3/hip/health-information/request", headers=CB(), json={"transactionId": tx, "hiRequest": {
            "consent": {"id": cid}, "dateRange": rng, "dataPushUrl": "https://example.invalid/push", "keyMaterial": {
                "cryptoAlg": "ECDH", "curve": "Curve25519", "dhPublicKey": {"keyValue": km.x509_public_key}, "nonce": km.nonce}}}, timeout=30)
        for _ in range(45):
            time.sleep(2)
            t = mongo.abdm_transfers.find_one({"transaction_id": tx})
            if t:
                return t
        return None

    def test_out_of_range_not_shared(self, mongo):
        t = self._consent_then_hi(mongo, ["DischargeSummary"], {"from": "2020-01-01T00:00:00Z", "to": "2020-12-31T00:00:00Z"})
        assert t and t["references"] == [], t

    def test_wrong_hitype_not_shared(self, mongo):
        t = self._consent_then_hi(mongo, ["Prescription"], {"from": "2026-01-01T00:00:00Z", "to": "2026-12-31T00:00:00Z"})
        assert t and t["references"] == [], t

    def test_hi_unknown_consent_no_transfer(self, mongo):
        tx = f"tx-HI-TEST_probe-none-{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{BASE_URL}/api/v3/hip/health-information/request", headers=CB(), json={
            "transactionId": tx, "hiRequest": {"consent": {"id": "TEST_probe-missing"}}}, timeout=30)
        assert r.status_code == 202
        time.sleep(25)
        assert mongo.abdm_transfers.find_one({"transaction_id": tx}) is None


# ---- CRM ABDM APIs (auth / RBAC) ----
class TestCrmApis:
    def test_care_contexts_admin(self):
        r = requests.get(f"{API}/care-contexts", params={"patient_user_id": PID}, headers=A(STATE["tok_admin"]), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["hip_id"] == HIP and any(x["reference"] == REF for x in d["care_contexts"])
        assert sum(d["counts"].values()) == len(d["care_contexts"])
        assert all("record" not in x for x in d["care_contexts"])

    def test_care_contexts_provider_scoped(self):
        r = requests.get(f"{API}/care-contexts", headers=A(STATE["tok_a"]), timeout=30)
        assert r.status_code == 200
        assert all(x["reference"] != REF for x in r.json()["care_contexts"])

    def test_sales_rep_403(self, tok_rep):
        for m, p, b in [("get", "/care-contexts", None), ("post", "/care-contexts/sync", {}), ("get", "/consents", None),
                        ("get", "/link-requests", None), ("get", "/callbacks", None), ("post", "/records/from-qr", {"qr": '{"hidn":"91-5555-6666-7777"}'}),
                        ("post", "/patients/lookup", {"user_ids": [PID]}), ("post", "/patients/attach", {"record_id": "TEST_probe_rec", "patient_user_id": "y"})]:
            r = getattr(requests, m)(f"{API}{p}", headers=A(tok_rep), json=b, timeout=30)
            assert r.status_code == 403, (p, r.status_code)

    def test_unauth(self):
        r = requests.get(f"{API}/care-contexts", timeout=30)
        assert r.status_code in (401, 403)

    def test_sync_patient_no_abha_404(self):
        r = requests.post(f"{API}/care-contexts/sync", json={"patient_user_id": "TEST_probe_noabha"}, headers=A(STATE["tok_admin"]), timeout=30)
        assert r.status_code == 404

    def test_sync_patient_ok(self):
        r = requests.post(f"{API}/care-contexts/sync", json={"patient_user_id": PID}, headers=A(STATE["tok_admin"]), timeout=90)
        assert r.status_code == 200, r.text
        assert "found" in r.json() and "new" in r.json()

    def test_sync_provider_without_id_403(self):
        r = requests.post(f"{API}/care-contexts/sync", json={}, headers=A(STATE["tok_a"]), timeout=30)
        assert r.status_code == 403

    def test_sync_all_admin(self):
        t0 = time.time()
        r = requests.post(f"{API}/care-contexts/sync", json={}, headers=A(STATE["tok_admin"]), timeout=180)
        print("sweep", r.status_code, r.text[:200], round(time.time() - t0, 1), "s")
        assert r.status_code == 200 and "patients" in r.json()

    def test_callbacks_master_only(self):
        r = requests.get(f"{API}/callbacks", headers=A(STATE["tok_admin"]), timeout=30)
        assert r.status_code == 200 and r.json()["hip_id"] == HIP and len(r.json()["callbacks"]) > 0
        assert all("body" not in x for x in r.json()["callbacks"])
        assert requests.get(f"{API}/callbacks", headers=A(STATE["tok_a"]), timeout=30).status_code == 403

    def test_cron(self):
        assert requests.post(f"{API}/cron/sync", timeout=30).status_code == 401
        assert requests.post(f"{API}/cron/sync", headers={"Authorization": "Bearer wrong"}, timeout=30).status_code == 401
        r = requests.post(f"{API}/cron/sync", headers={"Authorization": f"Bearer {ENV['WEBHOOK_CRON_SECRET']}"}, timeout=30)
        assert r.status_code == 200 and r.json()["accepted"] is True


# ---- QR check-in, lookup, attach ----
QR = json.dumps({"hidn": "91-5555-6666-7777", "phr": "testprobeqr@sbx", "name": "TEST_probe QR Patient", "gender": "F",
                 "dob": "5/3/1992", "mobile": "9999999999", "address": "TEST street"})


class TestQr:
    def test_from_qr_new(self, mongo):
        mongo.abha_records.delete_many({"abha_number": "91-5555-6666-7777"})
        r = requests.post(f"{API}/records/from-qr", json={"qr": QR}, headers=A(STATE["tok_a"]), timeout=30)
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["abha_number"] == "91-5555-6666-7777" and rec["kyc_verified"] is False and rec["abha_address"] == "testprobeqr@sbx"
        assert rec["dob"] == "05-03-1992" and rec["year_of_birth"] == 1992
        assert r.json()["profile"]["name"] == "TEST_probe QR Patient"

    def test_from_qr_no_downgrade(self, mongo):
        mongo.abha_records.update_one({"abha_number": "91-5555-6666-7777", "owner": "trata"}, {"$set": {
            "id": "TEST_probe_qr_verified", "kyc_verified": True, "last_verified_via": "abha-number", "name": "TEST_probe Verified Name"}}, upsert=True)
        r = requests.post(f"{API}/records/from-qr", json={"qr": QR}, headers=A(STATE["tok_admin"]), timeout=30)
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["id"] == "TEST_probe_qr_verified"
        assert rec["kyc_verified"] is True and rec["last_verified_via"] == "abha-number"
        print("name after QR on verified record:", rec["name"])

    @pytest.mark.parametrize("qr,code", [("this is not json at all", 400), ('["a","b","c"]', 400), ('{"name":"no abha num"}', 400),
                                         ('{"hidn":"12345"}', 400)])
    def test_from_qr_bad(self, qr, code):
        r = requests.post(f"{API}/records/from-qr", json={"qr": qr}, headers=A(STATE["tok_a"]), timeout=30)
        assert r.status_code == code, (qr, r.status_code, r.text)

    def test_lookup(self):
        r = requests.post(f"{API}/patients/lookup", json={"user_ids": [PID, "TEST_probe_nobody"]}, headers=A(STATE["tok_admin"]), timeout=30)
        assert r.status_code == 200
        d = r.json()["abha"]
        assert d[PID]["abha_number"] == "91-0000-0000-0001" and "TEST_probe_nobody" not in d

    def test_attach(self, mongo):
        rec = mongo.abha_records.find_one({"abha_number": "91-5555-6666-7777", "owner": {"$ne": "trata"}})
        r = requests.post(f"{API}/patients/attach", json={"record_id": rec["id"], "patient_user_id": "TEST_probe_qr_patient"},
                          headers=A(STATE["tok_a"]), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["patient_user_id"] == "TEST_probe_qr_patient"
        assert mongo.abha_records.find_one({"id": rec["id"]})["patient_user_id"] == "TEST_probe_qr_patient"
        # other provider can't attach
        r = requests.post(f"{API}/patients/attach", json={"record_id": rec["id"], "patient_user_id": "x"}, headers=A(STATE["tok_b"]), timeout=30)
        assert r.status_code == 404
        r = requests.post(f"{API}/patients/attach", json={"record_id": "TEST_probe_missing", "patient_user_id": "x"}, headers=A(STATE["tok_a"]), timeout=30)
        assert r.status_code == 404

    def test_lookup_cross_provider(self):
        r = requests.post(f"{API}/patients/lookup", json={"user_ids": ["TEST_probe_qr_patient"]}, headers=A(STATE["tok_b"]), timeout=30)
        print("provider B lookup of provider A's patient:", r.status_code, r.json())
        assert r.status_code == 200 and "TEST_probe_qr_patient" not in r.json()["abha"]
