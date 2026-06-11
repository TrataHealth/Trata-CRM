"""Phase-7 password recovery & security questions coverage.

Covers:
- /auth/security-questions
- /auth/security-status (auth required)
- /auth/security-setup (validation + persist)
- /auth/verify-otp returns recovery flags
- /auth/login-password returns security flags
- /auth/forgot/start (not_recoverable / no_recovery_set / ok paths)
- /auth/forgot/request-code (wrong/right answers, 30s rate-limit, dev_code surface)
- /auth/forgot/reset (wrong/right code, password length, persistence + re-login)
- _safe_user redactions on /auth/me
"""
import os
import time
import pytest
import requests
from datetime import datetime, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"

OTP = "123456"

# Personas
MASTER_PHONE = "9873117605"
MASTER_PWD = "Master@123"

ROHAN_PHONE = "9000000002"     # security already configured per agent_to_agent_context_note
ROHAN_PWD = "Trata@123"
ROHAN_EMAIL = "rohan.test@example.com"

PRIYA_PHONE = "9000000001"     # security NOT yet set
PRIYA_PWD = "Trata@123"

UNKNOWN_PHONE = "9999999999"   # not registered


# ---------- helpers ----------
def _login(phone: str, password: str) -> dict:
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": phone}, timeout=15)
    assert r.status_code == 200, r.text
    r = s.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": phone, "otp": OTP}, timeout=15)
    assert r.status_code == 200, r.text
    body = r.json()
    temp = body["temp_token"]
    if body.get("needs_password_setup"):
        rr = s.post(
            f"{BASE_URL}/api/auth/set-password",
            json={"password": password},
            headers={"Authorization": f"Bearer {temp}"},
            timeout=15,
        )
        assert rr.status_code == 200, rr.text
        token = rr.json()["token"]
        user = rr.json()["user"]
    else:
        rr = s.post(
            f"{BASE_URL}/api/auth/login-password",
            json={"password": password},
            headers={"Authorization": f"Bearer {temp}"},
            timeout=15,
        )
        assert rr.status_code == 200, rr.text
        token = rr.json()["token"]
        user = rr.json()["user"]
    return {"token": token, "user": user, "verify_otp_user": body["user"]}


def _try_login(phone: str, password: str) -> dict | None:
    try:
        return _login(phone, password)
    except AssertionError:
        return None


def _force_rohan_password(target_pwd: str):
    """If rohan's current pwd is unknown, use the forgot cycle to set it."""
    time.sleep(31)  # past 30s rate limit
    start = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": ROHAN_PHONE}, timeout=10).json()
    if not start.get("ok"):
        return False
    qids = [q["id"] for q in start["questions"]]
    ans_map = {"q1": "Mumbai", "q4": "Rex"}
    rc = requests.post(
        f"{BASE_URL}/api/auth/forgot/request-code",
        json={"phone": ROHAN_PHONE, "answers": [
            {"question_id": qids[0], "answer": ans_map.get(qids[0], "x")},
            {"question_id": qids[1], "answer": ans_map.get(qids[1], "x")},
        ]},
        timeout=10,
    ).json()
    code = rc.get("dev_code")
    if not code:
        return False
    r = requests.post(
        f"{BASE_URL}/api/auth/forgot/reset",
        json={"phone": ROHAN_PHONE, "code": code, "new_password": target_pwd},
        timeout=10,
    )
    return r.status_code == 200


@pytest.fixture(scope="module")
def rohan():
    info = _try_login(ROHAN_PHONE, ROHAN_PWD)
    if info:
        return info
    # try a few common alternatives left over from prior partial runs
    for alt in ("Trata@New123", "Trata@New1234", "NewPass@123"):
        info = _try_login(ROHAN_PHONE, alt)
        if info:
            # restore canonical
            try:
                _force_rohan_password(ROHAN_PWD)
            except Exception:
                pass
            return info
    # last resort: force via forgot flow
    if _force_rohan_password(ROHAN_PWD):
        info = _try_login(ROHAN_PHONE, ROHAN_PWD)
        if info:
            return info
    pytest.skip("Could not log in as Rohan with any known password")


@pytest.fixture(scope="module")
def master():
    return _login(MASTER_PHONE, MASTER_PWD)


# ---------- /auth/security-questions ----------
class TestSecurityQuestions:
    def test_list_questions_public(self):
        r = requests.get(f"{BASE_URL}/api/auth/security-questions", timeout=10)
        assert r.status_code == 200
        items = r.json()["items"]
        assert isinstance(items, list) and len(items) == 8
        for q in items:
            assert "id" in q and "text" in q
            assert q["id"].startswith("q")


# ---------- /auth/security-status ----------
class TestSecurityStatus:
    def test_requires_auth(self):
        r = requests.get(f"{BASE_URL}/api/auth/security-status", timeout=10)
        assert r.status_code in (401, 403)

    def test_rohan_has_setup(self, rohan):
        r = requests.get(
            f"{BASE_URL}/api/auth/security-status",
            headers={"Authorization": f"Bearer {rohan['token']}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["has_recovery_email"] is True
        assert b["has_security_questions"] is True
        # rohan.test@example.com -> "ro***@example.com" style
        assert "@" in b["recovery_email_masked"]
        assert "*" in b["recovery_email_masked"]
        assert isinstance(b["questions_set"], list) and len(b["questions_set"]) == 2


# ---------- /auth/security-setup validation ----------
class TestSecuritySetupValidation:
    def _post(self, token, payload):
        return requests.post(
            f"{BASE_URL}/api/auth/security-setup",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )

    def test_rejects_invalid_email(self, rohan):
        r = self._post(rohan["token"], {
            "recovery_email": "not-an-email",
            "questions": [{"question_id": "q1", "answer": "Mumbai"}, {"question_id": "q4", "answer": "Rex"}],
        })
        assert r.status_code == 400

    def test_rejects_fewer_than_two(self, rohan):
        r = self._post(rohan["token"], {
            "recovery_email": "a@b.com",
            "questions": [{"question_id": "q1", "answer": "Mumbai"}],
        })
        assert r.status_code == 400

    def test_rejects_duplicate_qids(self, rohan):
        r = self._post(rohan["token"], {
            "recovery_email": "a@b.com",
            "questions": [{"question_id": "q1", "answer": "Mumbai"}, {"question_id": "q1", "answer": "Pune"}],
        })
        assert r.status_code == 400

    def test_rejects_short_answer(self, rohan):
        r = self._post(rohan["token"], {
            "recovery_email": "a@b.com",
            "questions": [{"question_id": "q1", "answer": "M"}, {"question_id": "q4", "answer": "Re"}],
        })
        assert r.status_code == 400

    def test_rejects_unknown_qid(self, rohan):
        r = self._post(rohan["token"], {
            "recovery_email": "a@b.com",
            "questions": [{"question_id": "q99", "answer": "Mumbai"}, {"question_id": "q4", "answer": "Rex"}],
        })
        assert r.status_code == 400

    def test_setup_then_restore_rohan(self, rohan):
        # Re-set Rohan to known values so other tests stay deterministic
        r = self._post(rohan["token"], {
            "recovery_email": ROHAN_EMAIL,
            "questions": [
                {"question_id": "q1", "answer": "Mumbai"},
                {"question_id": "q4", "answer": "Rex"},
            ],
        })
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True
        assert "*" in r.json()["recovery_email_masked"]


# ---------- /auth/verify-otp + login-password flags ----------
class TestAuthFlagsExposed:
    def test_verify_otp_user_has_recovery_flags(self):
        s = requests.Session()
        s.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": ROHAN_PHONE}, timeout=10)
        r = s.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": ROHAN_PHONE, "otp": OTP}, timeout=10)
        assert r.status_code == 200
        u = r.json()["user"]
        assert u["has_recovery_email"] is True
        assert u["has_security_questions"] is True

    def test_login_password_returns_flags(self, rohan):
        u = rohan["user"]
        assert u["has_recovery_email"] is True
        assert u["has_security_questions"] is True
        assert u["security_setup_required"] is False

    def test_priya_security_setup_required(self):
        # Priya has password but NOT recovery -> security_setup_required True
        info = _login(PRIYA_PHONE, PRIYA_PWD)
        u = info["user"]
        assert u["security_setup_required"] is True
        assert u["has_security_questions"] is False


# ---------- /auth/me redactions ----------
class TestSafeUserRedactions:
    def test_me_excludes_sensitive_fields(self, rohan):
        r = requests.get(
            f"{BASE_URL}/api/auth/me",
            headers={"Authorization": f"Bearer {rohan['token']}"},
            timeout=10,
        )
        assert r.status_code == 200
        u = r.json()["user"]
        for k in ["password_hash", "security_questions", "reset_code_hash",
                  "reset_code_expires_at", "reset_code_sent_at"]:
            assert k not in u, f"/auth/me leaked {k}"
        # /auth/me must NOT include questions_set (that's only on /security-status)
        assert "questions_set" not in u
        assert u["has_recovery_email"] is True
        assert u["has_security_questions"] is True
        assert u["security_setup_required"] is False
        # Raw recovery_email may be shown to owner — allowed
        assert u.get("recovery_email") == ROHAN_EMAIL


# ---------- /auth/forgot/start ----------
class TestForgotStart:
    def test_unknown_phone_not_recoverable(self):
        r = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": UNKNOWN_PHONE}, timeout=10)
        assert r.status_code == 200
        b = r.json()
        assert b["ok"] is False and b["reason"] == "not_recoverable"

    def test_no_recovery_set(self):
        r = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": PRIYA_PHONE}, timeout=10)
        assert r.status_code == 200
        b = r.json()
        assert b["ok"] is False and b["reason"] == "no_recovery_set"

    def test_rohan_ok(self):
        r = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": ROHAN_PHONE}, timeout=10)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["ok"] is True
        assert b.get("name")
        assert "*" in b["recovery_email_masked"]
        assert isinstance(b["questions"], list) and len(b["questions"]) == 2


# ---------- /auth/forgot/request-code ----------
class TestForgotRequestCode:
    def test_all_wrong_answers_forbidden(self):
        # First find the question ids set for rohan
        start = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": ROHAN_PHONE}, timeout=10).json()
        qids = [q["id"] for q in start["questions"]]
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot/request-code",
            json={"phone": ROHAN_PHONE, "answers": [
                {"question_id": qids[0], "answer": "ZZZZ"},
                {"question_id": qids[1], "answer": "YYYY"},
            ]},
            timeout=10,
        )
        assert r.status_code == 403

    def test_one_of_two_correct_returns_dev_code(self):
        # Wait past the rate limit just in case prior test triggered nothing
        time.sleep(1)
        start = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": ROHAN_PHONE}, timeout=10).json()
        qids = [q["id"] for q in start["questions"]]
        # Provide correct answers for both known qids
        ans_map = {"q1": "mumbai", "q4": "REX  "}  # case-insensitive + whitespace trim
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot/request-code",
            json={"phone": ROHAN_PHONE, "answers": [
                {"question_id": qids[0], "answer": ans_map.get(qids[0], "wrong")},
                {"question_id": qids[1], "answer": "DEFINITELY_WRONG"},
            ]},
            timeout=15,
        )
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["success"] is True
        assert b["expires_in_minutes"] == 15
        # Resend test mode rejects rohan.test@example.com -> email_sent False -> dev_code surfaced
        if not b.get("email_sent"):
            assert b.get("dev_code") and len(b["dev_code"]) == 6
        TestForgotRequestCode._last_code = b.get("dev_code")
        TestForgotRequestCode._last_at = time.time()

    def test_rate_limit_429_within_30s(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot/request-code",
            json={"phone": ROHAN_PHONE, "answers": [{"question_id": "q1", "answer": "Mumbai"}]},
            timeout=10,
        )
        assert r.status_code == 429, r.text


# ---------- /auth/forgot/reset ----------
class TestForgotReset:
    def test_wrong_code_forbidden(self):
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot/reset",
            json={"phone": ROHAN_PHONE, "code": "000000", "new_password": "NewPass@123"},
            timeout=10,
        )
        # Either 403 (wrong code) since a code is already set from prior test
        assert r.status_code in (400, 403)

    def test_short_password_400(self):
        code = getattr(TestForgotRequestCode, "_last_code", None)
        if not code:
            pytest.skip("dev_code unavailable")
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot/reset",
            json={"phone": ROHAN_PHONE, "code": code, "new_password": "abc"},
            timeout=10,
        )
        assert r.status_code == 400

    def test_correct_code_resets_and_relogin(self):
        code = getattr(TestForgotRequestCode, "_last_code", None)
        if not code:
            pytest.skip("dev_code unavailable")
        new_pwd = "Trata@New123"
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot/reset",
            json={"phone": ROHAN_PHONE, "code": code, "new_password": new_pwd},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["success"] is True

        # Old password rejected
        s = requests.Session()
        s.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": ROHAN_PHONE}, timeout=10)
        vo = s.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": ROHAN_PHONE, "otp": OTP}, timeout=10).json()
        temp = vo["temp_token"]
        bad = s.post(
            f"{BASE_URL}/api/auth/login-password",
            json={"password": ROHAN_PWD},
            headers={"Authorization": f"Bearer {temp}"},
            timeout=10,
        )
        assert bad.status_code == 401

        # New password works
        # Need a fresh temp token (the prior one was consumed by the 401)
        s.post(f"{BASE_URL}/api/auth/send-otp", json={"phone": ROHAN_PHONE}, timeout=10)
        vo2 = s.post(f"{BASE_URL}/api/auth/verify-otp", json={"phone": ROHAN_PHONE, "otp": OTP}, timeout=10).json()
        temp2 = vo2["temp_token"]
        good = s.post(
            f"{BASE_URL}/api/auth/login-password",
            json={"password": new_pwd},
            headers={"Authorization": f"Bearer {temp2}"},
            timeout=10,
        )
        assert good.status_code == 200, good.text

        # Reset back to canonical Trata@123 via a fresh forgot cycle so credentials file stays valid
        time.sleep(31)  # past rate limit
        start = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": ROHAN_PHONE}, timeout=10).json()
        qids = [q["id"] for q in start["questions"]]
        ans_map = {"q1": "Mumbai", "q4": "Rex"}
        rc = requests.post(
            f"{BASE_URL}/api/auth/forgot/request-code",
            json={"phone": ROHAN_PHONE, "answers": [
                {"question_id": qids[0], "answer": ans_map.get(qids[0], "x")},
                {"question_id": qids[1], "answer": ans_map.get(qids[1], "x")},
            ]},
            timeout=10,
        ).json()
        restore_code = rc.get("dev_code")
        if restore_code:
            requests.post(
                f"{BASE_URL}/api/auth/forgot/reset",
                json={"phone": ROHAN_PHONE, "code": restore_code, "new_password": ROHAN_PWD},
                timeout=10,
            )


# ---------- Expiration is set ~15min future in DB (verified via state inspection) ----------
class TestExpirationConfigured:
    def test_expires_about_15_min(self):
        # Force a fresh request-code (after the restore above, rate-limit may apply; wait if needed)
        time.sleep(31)
        start = requests.post(f"{BASE_URL}/api/auth/forgot/start", json={"phone": ROHAN_PHONE}, timeout=10).json()
        if not start.get("ok"):
            pytest.skip("rohan recovery not configured for expiration check")
        qids = [q["id"] for q in start["questions"]]
        ans_map = {"q1": "Mumbai", "q4": "Rex"}
        r = requests.post(
            f"{BASE_URL}/api/auth/forgot/request-code",
            json={"phone": ROHAN_PHONE, "answers": [
                {"question_id": qids[0], "answer": ans_map.get(qids[0], "x")},
                {"question_id": qids[1], "answer": ans_map.get(qids[1], "x")},
            ]},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        assert r.json()["expires_in_minutes"] == 15
