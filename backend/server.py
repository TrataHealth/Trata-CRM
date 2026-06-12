"""
TrataHealth Master Admin CRM - Backend
Comprehensive CRM for managing all users (patients, doctors, hospitals, paramedics, ambulance providers, pathologists),
their activities (emergency cases, appointments, bookings, KYC), deal pipeline, tasks, and analytics.
"""
import os
import logging
import uuid
import random
import hmac
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Query, Request, Body
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
import jwt
import bcrypt
import io
import csv

import upstream_sync as us
import admin_bridge as ab

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# ---------- Setup ----------
MONGO_URL = os.environ['MONGO_URL']
DB_NAME = os.environ['DB_NAME']
JWT_SECRET = os.environ['JWT_SECRET']
MASTER_ADMIN_PHONE = os.environ['MASTER_ADMIN_PHONE']
MASTER_ADMIN_OTP = os.environ['MASTER_ADMIN_OTP']
EMERGENT_LLM_KEY = os.environ.get('EMERGENT_LLM_KEY', '')
UPSTREAM_SYNC_INTERVAL_MIN = int(os.environ.get('UPSTREAM_SYNC_INTERVAL_MIN', '5'))
PROVIDER_WEBHOOK_SECRET = os.environ.get('PROVIDER_WEBHOOK_SECRET', '')
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
SENDER_EMAIL = os.environ.get('SENDER_EMAIL', 'onboarding@resend.dev')

if RESEND_API_KEY:
    import resend as _resend
    _resend.api_key = RESEND_API_KEY

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="TrataHealth CRM API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------- Roles & Scopes ----------
INTERNAL_ROLES = {"admin", "manager", "national_manager", "regional_manager", "zonal_manager", "area_manager", "sales_rep", "ops_rep"}
PROVIDER_ROLES = {"provider_owner"}
# This app only supports ambulance providers. Hospital / clinic / pathology owners use the separate HMS.
PROVIDER_TYPE_TO_CONTACT_TYPE = {
    "ambulance": "ambulance_provider",
}
SUPPORTED_PROVIDER_TYPES = set(PROVIDER_TYPE_TO_CONTACT_TYPE.keys())

# Org hierarchy (top → bottom). Each role can ONLY report to the role immediately above it.
HIERARCHY = ["national_manager", "regional_manager", "zonal_manager", "area_manager", "sales_rep"]
# Map legacy "manager" → regional_manager (kept for backwards-compat during migration)
LEGACY_ROLE_ALIASES = {"manager": "regional_manager"}
MANAGER_ROLES = {"national_manager", "regional_manager", "zonal_manager", "area_manager", "manager"}


def normalize_role(role: str) -> str:
    return LEGACY_ROLE_ALIASES.get(role, role)


def parent_role_of(role: str) -> Optional[str]:
    r = normalize_role(role)
    if r not in HIERARCHY:
        return None
    idx = HIERARCHY.index(r)
    return HIERARCHY[idx - 1] if idx > 0 else None  # national_manager → reports to nobody (admin manages)


def is_internal(user: dict) -> bool:
    return user.get("role") in INTERNAL_ROLES or user.get("is_master_admin")


def is_sales_rep(user: dict) -> bool:
    return user.get("role") == "sales_rep" and not user.get("is_master_admin")


def is_admin_or_manager(user: dict) -> bool:
    return user.get("is_master_admin") or user.get("role") in ("admin", "manager", "national_manager", "regional_manager", "zonal_manager", "area_manager")


def is_provider(user: dict) -> bool:
    return user.get("role") in PROVIDER_ROLES


def scope_filter(user: dict, key_contact: str = "id", key_provider: str = "provider_ids") -> dict:
    """
    Returns a Mongo filter dict scoping a query to what the user is allowed to see.
    Internal users → {} (full access). Provider users → only docs linked to their provider_id or themselves.
    """
    if is_internal(user):
        return {}
    if is_provider(user):
        pid = user.get("provider_id")
        # Match the provider's own contact OR any doc linked via provider_ids array OR its own owner-id
        return {"$or": [
            {key_contact: pid},
            {key_provider: pid},
        ]}
    # Unknown role → see nothing
    return {"_never_": True}


# ---------- Password helpers ----------
def hash_password(password: str) -> str:
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def make_token(user: dict, ttype: str = "access") -> str:
    payload = {
        "sub": user["id"],
        "phone": user["phone"],
        "role": user.get("role"),
        "name": user.get("name"),
        "type": ttype,
        "exp": datetime.now(timezone.utc) + (timedelta(minutes=10) if ttype == "temp" else timedelta(days=30)),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str, expected_type: Optional[str] = None) -> dict:
    payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    if expected_type and payload.get("type", "access") != expected_type:
        raise jwt.PyJWTError("Wrong token type")
    return payload


async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await db.crm_users.find_one({"id": payload["sub"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def require_internal(user: dict = Depends(get_current_user)) -> dict:
    if not is_internal(user):
        raise HTTPException(status_code=403, detail="Admin access only")
    return user


# ---------- Models ----------
class LoginSendOTP(BaseModel):
    phone: str


class LoginVerifyOTP(BaseModel):
    phone: str
    otp: str


class PasswordSet(BaseModel):
    password: str


class PasswordLogin(BaseModel):
    password: str


class ContactStatusUpdate(BaseModel):
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    pipeline_stage: Optional[str] = None
    notes: Optional[str] = None


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    assigned_to: Optional[str] = None
    contact_id: Optional[str] = None
    priority: str = "medium"   # low, medium, high, critical
    status: str = "open"       # open, in_progress, done
    due_date: Optional[str] = None


class TaskUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[str] = None


class NoteCreate(BaseModel):
    contact_id: str
    body: str


class TeamMemberCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    role: str = "sales_rep"
    reports_to: Optional[str] = None
    territories: Optional[List[str]] = None


class AISummaryRequest(BaseModel):
    contact_id: str
    mode: str = "summary"  # summary | next_action | draft_email


def normalize_phone(p: str) -> str:
    p = (p or "").strip().replace(" ", "")
    if p.startswith("+91"):
        p = p[3:]
    elif p.startswith("91") and len(p) > 10:
        p = p[2:]
    return p


# ---------- Auth (3-step: phone → OTP → password) ----------
@api.post("/auth/send-otp")
async def send_otp(data: LoginSendOTP):
    phone = normalize_phone(data.phone)
    # TODO: when UPSTREAM_API_URL is set, forward to upstream /api/auth/send-otp
    logger.info(f"Mock OTP sent to {phone}: {MASTER_ADMIN_OTP}")
    return {
        "success": True,
        "message": f"OTP sent (use {MASTER_ADMIN_OTP} for testing)",
        "provider": "mock",
    }


def _safe_user(u: dict) -> dict:
    u = {**u}
    u.pop("password_hash", None)
    u.pop("_id", None)
    sec = u.pop("security_questions", None) or []
    u.pop("reset_code_hash", None)
    u.pop("reset_code_expires_at", None)
    u.pop("reset_code_sent_at", None)
    u["has_security_questions"] = len(sec) >= 2
    u["has_recovery_email"] = bool(u.get("recovery_email"))
    u["security_setup_required"] = not (u["has_security_questions"] and u["has_recovery_email"])
    return u


async def _ensure_master_admin_user(phone: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "phone": phone,
        "name": "Master Admin",
        "email": "admin@tratahealth.com",
        "role": "admin",
        "is_master_admin": True,
        "is_active": True,
        "avatar": None,
        "provider_type": None,
        "provider_id": None,
        "password_hash": None,
        "created_at": now_iso(),
    }


@api.post("/auth/verify-otp")
async def verify_otp(data: LoginVerifyOTP):
    phone = normalize_phone(data.phone)
    if data.otp != MASTER_ADMIN_OTP:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    user = await db.crm_users.find_one({"phone": phone}, {"_id": 0})
    if not user:
        if phone == MASTER_ADMIN_PHONE:
            user = await _ensure_master_admin_user(phone)
            await db.crm_users.insert_one(user.copy())
        else:
            raise HTTPException(status_code=403, detail="Phone not authorized. Contact master admin to be added.")

    # Guard: only ambulance provider portals are supported here. Hospital/clinic/path-lab owners
    # belong to the separate HMS and must not be allowed to log in.
    if user.get("role") == "provider_owner" and user.get("provider_type") not in SUPPORTED_PROVIDER_TYPES:
        raise HTTPException(
            status_code=403,
            detail="This portal is for Trata Health admin and ambulance providers only. Please use the Hospital Management System for your account.",
        )

    needs_setup = not user.get("password_hash")
    # Short-lived temp token good only for the next step (set/verify password)
    temp = make_token(user, ttype="temp")
    return {
        "success": True,
        "needs_password_setup": needs_setup,
        "temp_token": temp,
        "user": {
            "id": user["id"],
            "name": user.get("name"),
            "phone": user["phone"],
            "role": user.get("role"),
            "provider_type": user.get("provider_type"),
            "has_recovery_email": bool(user.get("recovery_email")),
            "has_security_questions": len(user.get("security_questions") or []) >= 2,
        },
    }


async def _user_from_temp(authorization: Optional[str]) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing temp token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = decode_token(token, expected_type="temp")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired temp token")
    user = await db.crm_users.find_one({"id": payload["sub"]}, {"_id": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@api.post("/auth/set-password")
async def set_password(data: PasswordSet, authorization: Optional[str] = Header(None)):
    if len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    user = await _user_from_temp(authorization)
    if user.get("password_hash"):
        raise HTTPException(status_code=400, detail="Password already set. Use login.")
    await db.crm_users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(data.password), "updated_at": now_iso()}},
    )
    user = await db.crm_users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    token = make_token(user, ttype="access")
    return {"success": True, "user": _safe_user(user), "token": token}


@api.post("/auth/login-password")
async def login_password(data: PasswordLogin, authorization: Optional[str] = Header(None)):
    user = await _user_from_temp(authorization)
    if not user.get("password_hash"):
        raise HTTPException(status_code=400, detail="Password not set. Use set-password first.")
    if not verify_password(data.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect password")
    safe = _safe_user(user)
    token = make_token(safe, ttype="access")
    return {"success": True, "user": safe, "token": token}


@api.get("/auth/me")
async def me(current=Depends(get_current_user)):
    return {"user": _safe_user(current)}


# ---------- Security questions + Password reset (Resend) ----------
SECURITY_QUESTIONS = [
    {"id": "q1", "text": "What city were you born in?"},
    {"id": "q2", "text": "What is the name of your first school?"},
    {"id": "q3", "text": "What is your mother's maiden name?"},
    {"id": "q4", "text": "What was the name of your first pet?"},
    {"id": "q5", "text": "What is your favourite movie?"},
    {"id": "q6", "text": "In which city did your parents meet?"},
    {"id": "q7", "text": "What was the model of your first car or two-wheeler?"},
    {"id": "q8", "text": "What is the name of your childhood best friend?"},
]
SECURITY_QUESTION_TEXT = {q["id"]: q["text"] for q in SECURITY_QUESTIONS}


def _norm_answer(ans: str) -> str:
    return " ".join((ans or "").strip().lower().split())


class SecuritySetupItem(BaseModel):
    question_id: str
    answer: str


class SecuritySetupBody(BaseModel):
    recovery_email: str
    questions: List[SecuritySetupItem]


class ForgotStartBody(BaseModel):
    phone: str


class ForgotRequestCodeBody(BaseModel):
    phone: str
    answers: List[SecuritySetupItem]   # at least 1 of 2 must be correct


class ForgotResetBody(BaseModel):
    phone: str
    code: str
    new_password: str


def _mask_email(email: Optional[str]) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    keep = local[:2] if len(local) > 2 else local[:1]
    return f"{keep}{'*' * max(2, len(local) - len(keep))}@{domain}"


def _is_valid_email(email: str) -> bool:
    import re
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", (email or "").strip()))


async def _send_reset_email_resend(to_email: str, agent_name: str, code: str) -> bool:
    """Send a 6-digit reset code via Resend. Returns True on success, False otherwise."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY not configured — printing reset code instead")
        logger.info(f"[DEV ONLY] Password reset code for {to_email}: {code}")
        return False
    html = f"""
    <div style="font-family: Arial, Helvetica, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; color: #091E42;">
      <div style="font-size: 13px; letter-spacing: 0.1em; text-transform: uppercase; color: #5E6C84;">Trata Health CRM</div>
      <h1 style="font-size: 22px; margin: 8px 0 4px 0;">Password reset code</h1>
      <p style="color: #42526E; font-size: 14px; line-height: 1.5; margin: 12px 0;">
        Hi {agent_name or "there"},<br>
        Use the code below to reset your TrataHealth CRM password. This code expires in <b>15 minutes</b>.
      </p>
      <div style="font-family: 'Courier New', monospace; font-size: 32px; letter-spacing: 12px; font-weight: bold;
                  background: #F4F5F7; border: 1px solid #DFE1E6; border-radius: 8px; padding: 16px 24px;
                  text-align: center; margin: 20px 0; color: #0052CC;">
        {code}
      </div>
      <p style="color: #5E6C84; font-size: 12px; line-height: 1.5;">
        If you did not request this, ignore this email — your password has not been changed. For security, never share this code.
      </p>
      <hr style="border: none; border-top: 1px solid #DFE1E6; margin: 24px 0;">
      <div style="font-size: 11px; color: #5E6C84;">Trata Health · Automated email</div>
    </div>
    """
    text = (
        f"Trata Health CRM password reset\n\n"
        f"Hi {agent_name or 'there'},\n"
        f"Use this 6-digit code to reset your password: {code}\n"
        f"It expires in 15 minutes.\n\n"
        f"If you did not request this, ignore this email."
    )
    params = {
        "from": f"Trata Health CRM <{SENDER_EMAIL}>",
        "to": [to_email],
        "subject": f"Your Trata CRM password reset code: {code}",
        "html": html,
        "text": text,
    }
    try:
        import asyncio
        result = await asyncio.to_thread(_resend.Emails.send, params)
        logger.info(f"Resend email sent: id={result.get('id') if isinstance(result, dict) else result}")
        return True
    except Exception as e:
        logger.error(f"Resend send failed: {e}")
        return False


@api.get("/auth/security-questions")
async def list_security_questions():
    return {"items": SECURITY_QUESTIONS}


@api.get("/auth/security-status")
async def security_status(current=Depends(get_current_user)):
    sec = current.get("security_questions") or []
    return {
        "has_recovery_email": bool(current.get("recovery_email")),
        "has_security_questions": len(sec) >= 2,
        "recovery_email_masked": _mask_email(current.get("recovery_email")),
        "questions_set": [{"id": s.get("question_id"), "text": SECURITY_QUESTION_TEXT.get(s.get("question_id"), "")} for s in sec],
    }


@api.post("/auth/security-setup")
async def security_setup(data: SecuritySetupBody, current=Depends(get_current_user)):
    if not _is_valid_email(data.recovery_email):
        raise HTTPException(status_code=400, detail="Enter a valid recovery email")
    if len(data.questions) != 2:
        raise HTTPException(status_code=400, detail="Pick exactly 2 security questions")
    ids = [q.question_id for q in data.questions]
    if len(set(ids)) != 2:
        raise HTTPException(status_code=400, detail="Pick two different questions")
    for q in data.questions:
        if q.question_id not in SECURITY_QUESTION_TEXT:
            raise HTTPException(status_code=400, detail=f"Unknown question id: {q.question_id}")
        if len(_norm_answer(q.answer)) < 2:
            raise HTTPException(status_code=400, detail="Answers must be at least 2 characters")
    stored = [
        {"question_id": q.question_id, "answer_hash": hash_password(_norm_answer(q.answer))}
        for q in data.questions
    ]
    await db.crm_users.update_one(
        {"id": current["id"]},
        {"$set": {
            "recovery_email": data.recovery_email.strip().lower(),
            "security_questions": stored,
            "security_set_at": now_iso(),
        }},
    )
    return {"success": True, "recovery_email_masked": _mask_email(data.recovery_email)}


@api.post("/auth/forgot/start")
async def forgot_start(data: ForgotStartBody):
    """Step 1 of forgot-password. Returns the 2 security questions for this user
    (so the UI can prompt them) plus a masked recovery email."""
    phone = normalize_phone(data.phone)
    user = await db.crm_users.find_one({"phone": phone}, {"_id": 0})
    if not user:
        # Don't leak account existence — return a neutral OK
        return {"ok": False, "reason": "not_recoverable", "message": "If this account is registered, recovery info will be shown."}
    sec = user.get("security_questions") or []
    if len(sec) < 2 or not user.get("recovery_email"):
        return {"ok": False, "reason": "no_recovery_set", "message": "This account has not set up password recovery. Please contact your admin."}
    return {
        "ok": True,
        "name": user.get("name"),
        "recovery_email_masked": _mask_email(user.get("recovery_email")),
        "questions": [{"id": s["question_id"], "text": SECURITY_QUESTION_TEXT.get(s["question_id"], "")} for s in sec],
    }


@api.post("/auth/forgot/request-code")
async def forgot_request_code(data: ForgotRequestCodeBody):
    """Step 2: verify at least 1 of 2 security answers, then email a 6-digit code."""
    phone = normalize_phone(data.phone)
    user = await db.crm_users.find_one({"phone": phone}, {"_id": 0})
    if not user or not user.get("security_questions") or not user.get("recovery_email"):
        raise HTTPException(status_code=400, detail="Recovery is not available for this account")

    # Rate-limit: 30s between sends
    last = user.get("reset_code_sent_at")
    if last:
        try:
            last_dt = datetime.fromisoformat(last)
            if (datetime.now(timezone.utc) - last_dt).total_seconds() < 30:
                raise HTTPException(status_code=429, detail="Please wait a few seconds before requesting another code")
        except (ValueError, TypeError):
            pass

    # Verify ≥1 of 2 answers
    stored_by_qid = {s["question_id"]: s["answer_hash"] for s in user["security_questions"]}
    correct = 0
    for ans in data.answers:
        h = stored_by_qid.get(ans.question_id)
        if h and verify_password(_norm_answer(ans.answer), h):
            correct += 1
    if correct < 1:
        raise HTTPException(status_code=403, detail="Security answers do not match")

    # Generate code, hash, store, email
    code = f"{random.randint(0, 999999):06d}"
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    await db.crm_users.update_one(
        {"id": user["id"]},
        {"$set": {
            "reset_code_hash": hash_password(code),
            "reset_code_expires_at": expires_at,
            "reset_code_sent_at": now_iso(),
        }},
    )
    sent = await _send_reset_email_resend(user["recovery_email"], user.get("name") or "", code)
    return {
        "success": True,
        "email_sent": sent,
        "recovery_email_masked": _mask_email(user.get("recovery_email")),
        "expires_in_minutes": 15,
        # For dev: when Resend isn't configured, this lets the frontend show the code anyway
        "dev_code": code if not sent else None,
    }


@api.post("/auth/forgot/reset")
async def forgot_reset(data: ForgotResetBody):
    """Step 3: verify code + set the new password."""
    if len(data.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    phone = normalize_phone(data.phone)
    user = await db.crm_users.find_one({"phone": phone}, {"_id": 0})
    if not user or not user.get("reset_code_hash") or not user.get("reset_code_expires_at"):
        raise HTTPException(status_code=400, detail="No active reset code. Request a new one.")
    code_clean = (data.code or "").strip()
    if not (4 <= len(code_clean) <= 12):
        raise HTTPException(status_code=400, detail="Invalid code")
    try:
        exp = datetime.fromisoformat(user["reset_code_expires_at"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid reset code state")
    if datetime.now(timezone.utc) > exp:
        await db.crm_users.update_one({"id": user["id"]}, {"$unset": {"reset_code_hash": "", "reset_code_expires_at": ""}})
        raise HTTPException(status_code=400, detail="Code expired. Request a new one.")
    if not verify_password(code_clean, user["reset_code_hash"]):
        raise HTTPException(status_code=403, detail="Incorrect reset code")
    await db.crm_users.update_one(
        {"id": user["id"]},
        {"$set": {"password_hash": hash_password(data.new_password), "password_changed_at": now_iso()},
         "$unset": {"reset_code_hash": "", "reset_code_expires_at": "", "reset_code_sent_at": ""}},
    )
    return {"success": True, "message": "Password has been reset. Please log in."}


# ---------- Dashboard ----------
RANGE_TO_DAYS = {"7d": 7, "30d": 30, "3m": 90, "6m": 180, "12m": 365, "all": None}


def _range_window(range_key: str):
    """Return (since_iso, label, days) for a given range pill.
    `days=None` ⇒ no lower-bound (all-time)."""
    days = RANGE_TO_DAYS.get(range_key, 7)
    if days is None:
        return None, "All time", None
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    label = {"7d": "Last 7 days", "30d": "Last 30 days", "3m": "Last 3 months",
             "6m": "Last 6 months", "12m": "Last 12 months"}.get(range_key, f"Last {days} days")
    return since, label, days


@api.get("/dashboard/stats")
async def dashboard_stats(range_key: str = Query("7d", alias="range"), current=Depends(require_internal)):
    since_iso, range_label, days_back = _range_window(range_key)

    # Helper to add the time window to a Mongo query
    def _scoped(q: Dict[str, Any]) -> Dict[str, Any]:
        if since_iso:
            return {**q, "created_at": {"$gte": since_iso}}
        return q

    total_contacts = await db.contacts.count_documents({})
    by_type = {}
    for t in ["patient", "doctor", "hospital", "paramedic", "ambulance_provider", "pathologist"]:
        by_type[t] = await db.contacts.count_documents({"type": t})

    verified = await db.contacts.count_documents({"is_verified": True})
    pending = await db.contacts.count_documents({"is_verified": False})

    active_cases = await db.activities.count_documents(_scoped({
        "category": "emergency_case",
        "status": {"$nin": ["COMPLETED", "CANCELLED", "CLOSED"]},
    }))
    completed_cases = await db.activities.count_documents(_scoped({"category": "emergency_case", "status": "COMPLETED"}))

    appointments_today = await db.activities.count_documents({
        "category": "appointment",
        "created_at": {"$gte": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
    })

    # Pipeline stages (always all-time snapshot — pipeline is current state, not historical)
    pipeline = {}
    for stage in ["lead", "contacted", "kyc_submitted", "verified", "active", "churned"]:
        pipeline[stage] = await db.contacts.count_documents({"pipeline_stage": stage})

    # Revenue scoped to the time window (sum of activities with amount in window)
    rev_q = _scoped({"amount": {"$gt": 0}})
    cursor = db.activities.find(rev_q, {"amount": 1, "_id": 0})
    total_revenue = 0
    async for d in cursor:
        total_revenue += d.get("amount", 0) or 0

    # Tasks are current-state, not time-bounded
    tasks_open = await db.tasks.count_documents({"status": {"$ne": "done"}})
    tasks_overdue = await db.tasks.count_documents({
        "status": {"$ne": "done"},
        "due_date": {"$lt": now_iso()},
    })

    # Growth — adaptive bucket size so the chart never has more than ~14 points
    growth = []
    bucket_count = 14 if (days_back is None or days_back >= 14) else max(1, days_back or 14)
    total_days = days_back if days_back is not None else 365
    bucket_days = max(1, total_days // bucket_count)
    for i in range(bucket_count - 1, -1, -1):
        end_dt = datetime.now(timezone.utc) - timedelta(days=i * bucket_days)
        start_dt = end_dt - timedelta(days=bucket_days)
        start = start_dt.isoformat()
        end = end_dt.isoformat()
        c = await db.contacts.count_documents({"created_at": {"$gte": start, "$lt": end}})
        a = await db.activities.count_documents({"created_at": {"$gte": start, "$lt": end}})
        growth.append({"date": start_dt.date().isoformat(), "new_contacts": c, "activities": a})

    # Activity by category (donut) — scoped to time window
    activity_breakdown = {}
    for cat in ["emergency_case", "appointment", "ambulance_booking", "lab_booking", "pathology_booking", "kyc"]:
        activity_breakdown[cat] = await db.activities.count_documents(_scoped({"category": cat}))

    return {
        "range": {"key": range_key, "label": range_label, "days": days_back, "since": since_iso},
        "users": {
            "total": total_contacts,
            "verified": verified,
            "pending": pending,
            "by_type": by_type,
        },
        "cases": {
            "total": await db.activities.count_documents(_scoped({"category": "emergency_case"})),
            "active": active_cases,
            "completed": completed_cases,
            "appointments_today": appointments_today,
        },
        "pipeline": pipeline,
        "revenue": {"total": round(total_revenue, 2), "currency": "INR"},
        "tasks": {"open": tasks_open, "overdue": tasks_overdue},
        "growth_14d": growth,
        "activity_breakdown": activity_breakdown,
    }



@api.post("/dashboard/ai-insights")
async def dashboard_ai_insights(payload: Dict[str, Any] = Body(default={}), current=Depends(require_internal)):
    """Generate executive AI insights for the dashboard's currently-selected time range.
    Uses the same time-windowed stats the dashboard already renders, then asks Claude
    to surface trends, anomalies and the single highest-leverage action for the team."""
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI not configured (EMERGENT_LLM_KEY missing)")
    range_key = (payload.get("range") or "7d").lower()
    if range_key not in RANGE_TO_DAYS:
        range_key = "7d"
    # Re-use the same stats endpoint to keep the AI's source-of-truth identical to the UI.
    stats = await dashboard_stats(range_key=range_key, current=current)  # type: ignore[arg-type]
    # Pull top-N most-recent activities for narrative colour
    recent = await db.activities.find({}, {"_id": 0, "title": 1, "category": 1, "subtype": 1, "status": 1, "contact_name": 1, "amount": 1, "created_at": 1}).sort("created_at", -1).limit(25).to_list(25)

    # Build a compact JSON context the LLM can reason about
    context_obj = {
        "range_label": stats["range"]["label"],
        "users": stats["users"],
        "cases": stats["cases"],
        "pipeline": stats["pipeline"],
        "revenue": stats["revenue"],
        "tasks": stats["tasks"],
        "activity_breakdown": stats["activity_breakdown"],
        "growth": stats["growth_14d"],
        "recent_activity_titles": [a.get("title") or f"{a.get('category')}/{a.get('subtype')}" for a in recent[:15]],
    }
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"dash-insights-{current['id']}-{range_key}-{datetime.now(timezone.utc).date()}",
            system_message=(
                "You are an executive analyst for TrataHealth's healthcare-provider CRM. "
                "Given a JSON snapshot of activity for a chosen time range, produce a SHORT, "
                "high-signal briefing for the master admin. Be specific to the numbers you see — "
                "never invent metrics. If the dataset is small, say so honestly and recommend what "
                "to instrument next. Always end with one concrete next action."
            ),
        ).with_model("anthropic", "claude-sonnet-4-6")
        msg = UserMessage(text=(
            f"Time range: {context_obj['range_label']}\n\n"
            f"Data (JSON):\n{json.dumps(context_obj, default=str)}\n\n"
            "Write the briefing in markdown using EXACTLY these four sections (use these literal headings):\n"
            "## Headline\nOne sentence — the single most important thing happening right now.\n"
            "## What's working\n2-3 bullets, each citing a number from the data.\n"
            "## What's at risk\n2-3 bullets, each citing a number from the data.\n"
            "## Do next\nOne concrete action the team should take in the next 48 hours."
        ))
        text = await chat.send_message(msg)
        return {"success": True, "range": stats["range"], "markdown": str(text), "context": context_obj}
    except Exception as e:
        logger.error(f"Dashboard AI insights error: {e}")
        raise HTTPException(status_code=502, detail=f"AI generation failed: {str(e)[:200]}")



@api.get("/dashboard/activity-feed")
async def activity_feed(limit: int = 20, current=Depends(require_internal)):
    items = await db.activities.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": items}


# ---------- Contacts ----------
@api.get("/contacts")
async def list_contacts(
    type: Optional[str] = None,
    q: Optional[str] = None,
    pipeline_stage: Optional[str] = None,
    is_verified: Optional[bool] = None,
    city: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current=Depends(get_current_user),
):
    qry: Dict[str, Any] = {}
    if type:
        qry["type"] = type
    if pipeline_stage:
        qry["pipeline_stage"] = pipeline_stage
    if is_verified is not None:
        qry["is_verified"] = is_verified
    if city:
        qry["city"] = {"$regex": city, "$options": "i"}
    if q:
        qry["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
            {"email": {"$regex": q, "$options": "i"}},
            {"specialization": {"$regex": q, "$options": "i"}},
        ]
    # Scope: providers only see themselves; sales reps only see leads assigned to them
    if is_provider(current):
        qry["id"] = current.get("provider_id")
    elif is_sales_rep(current):
        qry["assigned_agent_id"] = current["id"]
    total = await db.contacts.count_documents(qry)
    items = (
        await db.contacts.find(qry, {"_id": 0})
        .sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    )
    return {"items": items, "total": total}


# ---------- Onboard new provider from CRM ----------
# Master Admin / Manager can create a provider directly from the CRM (mirrors the
# admin app's onboarding flow). Creates a CRM contact and emits crm.lead.created →
# user.upsert outbound so the Trata Admin App + Provider App see the same user.
PROVIDER_ROLES_ALLOWED = {
    "ambulance_provider", "hospital", "doctor", "paramedic", "pathologist", "pharmacy",
}


@api.post("/admin/onboard-provider")
async def onboard_provider(payload: Dict[str, Any] = Body(...), current=Depends(get_current_user)):
    """Internal staff (admin, manager, sales rep, ops rep) create a new provider lead from
    the CRM. The contact is persisted locally and pushed to the Trata Admin App via the
    outbound webhook bridge (crm.lead.created → user.upsert)."""
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal staff only")

    role = (payload.get("role") or "").strip()
    if role not in PROVIDER_ROLES_ALLOWED:
        raise HTTPException(status_code=400, detail=f"role must be one of {sorted(PROVIDER_ROLES_ALLOWED)}")
    name = (payload.get("name") or "").strip()
    phone = _normalize_phone(payload.get("phone") or "")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if not phone or len(phone) != 10:
        raise HTTPException(status_code=400, detail="A valid 10-digit phone is required")

    # Duplicate check
    existing = await db.contacts.find_one({"phone": phone}, {"_id": 0, "id": 1, "name": 1})
    if existing:
        raise HTTPException(status_code=409, detail=f"A provider with phone {phone} already exists: {existing.get('name')}")

    email   = (payload.get("email") or "").strip() or None
    city    = (payload.get("city") or "").strip() or None
    state   = (payload.get("state") or "").strip() or None
    address = (payload.get("address") or "").strip() or None

    # Optional role-specific fields (kept open-ended so different verticals can pass extras)
    extras: Dict[str, Any] = {}
    for k in ("hospital_name", "ambulance_count", "specialization", "license_number",
              "vehicle_reg", "pan_number", "gst_number", "lab_specialty", "pharmacy_type"):
        v = payload.get(k)
        if v not in (None, ""):
            extras[k] = v

    # Auto-assignment rule: if a sales rep is onboarding, the contact is assigned to them.
    # Otherwise (admin/manager) auto-assign by territory.
    if is_sales_rep(current):
        agent = {"id": current["id"], "name": current.get("name") or current.get("phone")}
    else:
        agent = await _pick_agent_for_territory(city)

    contact_id = str(uuid.uuid4())
    new_contact = {
        "id": contact_id,
        "name": name,
        "type": role,
        "phone": phone,
        "email": email,
        "city": city,
        "state": state,
        "address": address,
        "is_verified": False,
        "is_active": False,
        "pipeline_stage": "contacted",        # they've been actively onboarded — past "lead"
        "kyc_status": "pending",
        "deal_value": 0,
        "assigned_agent_id": agent["id"] if agent else None,
        "assigned_agent_name": agent["name"] if agent else None,
        "source": "crm_admin_onboarded",
        "onboarded_by": current.get("name") or current.get("phone"),
        "onboarded_at": now_iso(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "avatar": None,
        **extras,
    }
    await db.contacts.insert_one(new_contact.copy())

    # Log an activity for the audit trail
    await db.activities.insert_one({
        "id": str(uuid.uuid4()),
        "type": "note",
        "category": "kyc",
        "subtype": "provider_onboarded",
        "title": f"Onboarded {role.replace('_', ' ')} — {name}",
        "description": f"Created in CRM by {current.get('name')}. Assigned to {agent['name'] if agent else 'unassigned'}.",
        "contact_id": contact_id,
        "contact_name": name,
        "agent_id": current.get("id"),
        "agent_name": current.get("name"),
        "status": "completed",
        "created_at": now_iso(),
    })

    # Push to Trata Admin App via the outbound webhook bridge — this triggers user.upsert
    # on the admin side which creates the user record. After that, the provider can OTP-
    # log into the Provider App using this phone.
    await ab.queue_outbound(db, "crm.lead.created", {
        "contact_id": contact_id,
        "phone": phone,
        "name": name,
        "role": role,
        "user_type": _user_type_for_role(role),
        "email": email,
        "city": city,
        "state": state,
        "address": address,
        "verification_status": "pending",
        "is_active": True,
        "source": "crm_admin_onboarded",
        "onboarded_by_crm": current.get("name") or current.get("phone"),
        **extras,
    })

    return {
        "success": True,
        "contact": new_contact,
        "login_hint": {
            "phone": phone,
            "otp": "Provider can OTP-login at the Provider App. (Universal dev OTP: 123456)",
            "synced_to_admin": True,
        },
    }


def _user_type_for_role(role: str) -> str:
    """Map CRM role → Trata Admin App's `user_type` field (observed in /api/admin/users)."""
    mapping = {
        "ambulance_provider": "ambulance_admin",
        "hospital": "hospital_admin",
        "doctor": "doctor",
        "paramedic": "paramedic",
        "pathologist": "lab",
        "pharmacy": "pharmacy",
    }
    return mapping.get(role, role)




@api.get("/contacts/{contact_id}")
async def get_contact(contact_id: str, current=Depends(get_current_user)):
    if is_provider(current) and contact_id != current.get("provider_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    if is_sales_rep(current) and c.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    acts = await db.activities.find({"contact_id": contact_id}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    notes = await db.notes.find({"contact_id": contact_id}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    tasks = await db.tasks.find({"contact_id": contact_id}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    return {"contact": c, "activities": acts, "notes": notes, "tasks": tasks}


@api.patch("/contacts/{contact_id}")
async def update_contact(contact_id: str, data: ContactStatusUpdate, current=Depends(get_current_user)):
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    # Sales reps can only update their own assigned leads
    if is_sales_rep(current):
        if c.get("assigned_agent_id") != current["id"]:
            raise HTTPException(status_code=403, detail="This lead is not assigned to you")
    elif not is_internal(current):
        raise HTTPException(status_code=403, detail="Forbidden")
    update = {k: v for k, v in data.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    update["updated_at"] = now_iso()
    await db.contacts.update_one({"id": contact_id}, {"$set": update})
    c2 = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    # Emit crm.deal.closed if the lead just reached verified/active from another stage (CRM side, not via inbound)
    if (
        update.get("pipeline_stage") in {"verified", "active"}
        and c.get("pipeline_stage") != update["pipeline_stage"]
        and c.get("source") not in {"trata_admin_webhook", "provider_app_webhook"}
    ):
        await ab.queue_outbound(db, "crm.deal.closed", {
            "phone": c2.get("phone"),
            "name": c2.get("name"),
            "final_stage": update["pipeline_stage"],
            "agent_phone": (await db.crm_users.find_one({"id": c2.get("assigned_agent_id")}, {"phone": 1}) or {}).get("phone"),
            "updated_at": c2.get("updated_at"),
        })
    return {"success": True, "contact": c2}


class AssignLead(BaseModel):
    agent_id: Optional[str] = None  # None = unassign


@api.patch("/contacts/{contact_id}/assign")
async def assign_lead(contact_id: str, data: AssignLead, current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Only admins/managers can assign leads")
    agent_name = None
    if data.agent_id:
        agent = await db.crm_users.find_one({"id": data.agent_id, "role": {"$in": ["sales_rep", "manager"]}}, {"_id": 0})
        if not agent:
            raise HTTPException(status_code=404, detail="Sales agent not found")
        agent_name = agent.get("name")
    await db.contacts.update_one(
        {"id": contact_id},
        {"$set": {"assigned_agent_id": data.agent_id, "assigned_agent_name": agent_name, "updated_at": now_iso()}},
    )
    # Emit lead.assigned outbound
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0, "phone": 1, "name": 1, "city": 1, "type": 1})
    old_agent = None
    if data.agent_id and c:
        new_agent = await db.crm_users.find_one({"id": data.agent_id}, {"phone": 1, "_id": 0})
        old_agent_doc = await db.crm_users.find_one({"id": (await db.contacts.find_one({"id": contact_id}) or {}).get("assigned_agent_id")}, {"phone": 1, "_id": 0}) if False else None
        await ab.queue_outbound(db, "crm.lead.assigned", {
            "phone": c.get("phone") if c else None,
            "name": c.get("name") if c else None,
            "new_agent_phone": (new_agent or {}).get("phone"),
            "old_agent_phone": (old_agent_doc or {}).get("phone"),
            "assigned_at": now_iso(),
        })
    return {"success": True, "agent_id": data.agent_id, "agent_name": agent_name}


# ---------- Pipeline ----------
@api.get("/pipeline")
async def get_pipeline(current=Depends(require_internal)):
    stages = ["lead", "contacted", "kyc_submitted", "verified", "active", "churned"]
    out = {}
    for s in stages:
        items = await db.contacts.find(
            {"pipeline_stage": s, "type": {"$in": ["doctor", "hospital", "paramedic", "ambulance_provider", "pathologist"]}},
            {"_id": 0, "id": 1, "name": 1, "type": 1, "phone": 1, "city": 1, "specialization": 1, "created_at": 1, "deal_value": 1, "avatar": 1},
        ).sort("created_at", -1).limit(50).to_list(50)
        out[s] = items
    return {"stages": stages, "items_by_stage": out}


# ---------- Activities ----------
@api.get("/activities")
async def list_activities(
    category: Optional[str] = None,
    status: Optional[str] = None,
    contact_id: Optional[str] = None,
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current=Depends(get_current_user),
):
    qry: Dict[str, Any] = {}
    if category:
        qry["category"] = category
    if status:
        qry["status"] = status
    if contact_id:
        qry["contact_id"] = contact_id
    if q:
        qry["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"contact_name": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]
    if is_provider(current):
        qry["provider_ids"] = current.get("provider_id")
    elif is_sales_rep(current):
        qry["agent_id"] = current["id"]
    total = await db.activities.count_documents(qry)
    items = await db.activities.find(qry, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"items": items, "total": total}


@api.get("/activities/{activity_id}")
async def get_activity(activity_id: str, current=Depends(get_current_user)):
    a = await db.activities.find_one({"id": activity_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Activity not found")
    if is_provider(current) and current.get("provider_id") not in (a.get("provider_ids") or []):
        raise HTTPException(status_code=403, detail="Forbidden")
    return a


# ---------- Tasks ----------
@api.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    contact_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current=Depends(get_current_user),
):
    qry: Dict[str, Any] = {}
    if status:
        qry["status"] = status
    if assigned_to:
        qry["assigned_to"] = assigned_to
    if contact_id:
        qry["contact_id"] = contact_id
    items = await db.tasks.find(qry, {"_id": 0}).sort("due_date", 1).skip(skip).limit(limit).to_list(limit)
    total = await db.tasks.count_documents(qry)
    # sales reps see only their tasks
    if is_sales_rep(current):
        items = [t for t in items if t.get("assigned_to") == current["id"] or (t.get("created_by") == current["id"])]
        total = len(items)
    return {"items": items, "total": total}


@api.post("/tasks")
async def create_task(data: TaskCreate, current=Depends(get_current_user)):
    t = data.dict()
    t["id"] = str(uuid.uuid4())
    t["created_by"] = current["id"]
    t["created_by_name"] = current.get("name")
    t["created_at"] = now_iso()
    t["updated_at"] = now_iso()
    await db.tasks.insert_one(t.copy())
    t.pop("_id", None)
    return {"success": True, "task": t}


@api.patch("/tasks/{task_id}")
async def update_task(task_id: str, data: TaskUpdate, current=Depends(get_current_user)):
    update = {k: v for k, v in data.dict().items() if v is not None}
    update["updated_at"] = now_iso()
    r = await db.tasks.update_one({"id": task_id}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    t = await db.tasks.find_one({"id": task_id}, {"_id": 0})
    return {"success": True, "task": t}


@api.delete("/tasks/{task_id}")
async def delete_task(task_id: str, current=Depends(get_current_user)):
    r = await db.tasks.delete_one({"id": task_id})
    return {"success": r.deleted_count > 0}


# ---------- Notes ----------
@api.post("/notes")
async def create_note(data: NoteCreate, current=Depends(get_current_user)):
    note = {
        "id": str(uuid.uuid4()),
        "contact_id": data.contact_id,
        "body": data.body,
        "author_id": current["id"],
        "author_name": current.get("name"),
        "created_at": now_iso(),
    }
    await db.notes.insert_one(note.copy())
    note.pop("_id", None)
    # Emit outbound — note.added
    c = await db.contacts.find_one({"id": data.contact_id}, {"_id": 0, "phone": 1, "name": 1})
    if c:
        await ab.queue_outbound(db, "crm.note.added", {
            "phone": c.get("phone"),
            "contact_name": c.get("name"),
            "note_text": data.body,
            "author_phone": current.get("phone"),
            "created_at": note["created_at"],
        })
    return {"success": True, "note": note}


# ---------- KYC review (Phase 6 — CRM agent decision) ----------
class KycReviewBody(BaseModel):
    decision: str   # "approved" | "rejected" | "needs_more_info"
    notes: Optional[str] = None


@api.post("/contacts/{contact_id}/kyc-review")
async def review_kyc(contact_id: str, data: KycReviewBody, current=Depends(get_current_user)):
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal users only")
    if data.decision not in {"approved", "rejected", "needs_more_info"}:
        raise HTTPException(status_code=400, detail="decision must be approved|rejected|needs_more_info")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_sales_rep(current) and c.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="Not your lead")
    new_kyc = {"approved": "approved", "rejected": "rejected", "needs_more_info": "needs_more_info"}[data.decision]
    set_doc: Dict[str, Any] = {"kyc_status": new_kyc, "kyc_reviewed_at": now_iso(), "kyc_review_notes": data.notes, "updated_at": now_iso()}
    if data.decision == "approved":
        # Bump pipeline forward if still pre-verified
        if c.get("pipeline_stage") in {"lead", "contacted", "kyc_submitted"}:
            set_doc["pipeline_stage"] = "verified"
    await db.contacts.update_one({"id": contact_id}, {"$set": set_doc})

    # Audit + outbound
    await db.activities.insert_one({
        "id": str(uuid.uuid4()),
        "category": "kyc_review",
        "subtype": data.decision,
        "title": f"KYC {data.decision} — {c['name']}",
        "description": data.notes or "",
        "contact_id": contact_id,
        "contact_name": c["name"],
        "status": "completed",
        "agent_id": current["id"],
        "agent_name": current.get("name"),
        "created_at": now_iso(),
        "provider_ids": [contact_id],
    })
    await ab.queue_outbound(db, "crm.kyc.reviewed", {
        "phone": c.get("phone"),
        "contact_name": c["name"],
        "kyc_id": c.get("kyc_id"),
        "upstream_user_id": c.get("upstream_user_id"),
        "decision": data.decision,
        # Admin-app expects these specific field names on its note schema:
        "text": data.notes or "",
        "author_phone": current.get("phone"),
        "author_role": current.get("role") or "sales_rep",
        "author_name": current.get("name"),
        # Keep both naming conventions for safety:
        "notes": data.notes,
        "reviewer_phone": current.get("phone"),
        "reviewer_name": current.get("name"),
        "reviewed_at": now_iso(),
    })
    c2 = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    return {"success": True, "contact": c2}


@api.get("/contacts/{contact_id}/kyc")
async def get_contact_kyc(contact_id: str, refresh: bool = False, current=Depends(get_current_user)):
    """Phase 6: Mirror the lead's KYC checklist + docs from the Trata Admin App.

    Lookup chain: cached upstream_user_id → live /api/admin/users?role=ambulance_provider lookup by phone.
    Caches kyc_id and upstream_user_id on the contact for fast subsequent emissions of crm.kyc.reviewed.
    """
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal users only")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_sales_rep(current) and c.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="Not your lead")

    upstream_user_id = c.get("upstream_user_id")
    if not upstream_user_id or refresh:
        admin_user = await ab.find_admin_user_by_phone(c.get("phone") or "")
        if not admin_user:
            return {
                "available": False,
                "reason": "no_admin_user_match",
                "message": "This lead has no matching record in the Trata Admin App yet.",
            }
        upstream_user_id = admin_user["id"]

    kyc = await ab.fetch_kyc(upstream_user_id)
    if not kyc:
        return {
            "available": False,
            "reason": "kyc_fetch_failed",
            "upstream_user_id": upstream_user_id,
            "message": "Could not fetch KYC payload from Trata Admin App.",
        }

    # Cache identifiers + last fetched payload on the contact
    cache_update = {
        "upstream_user_id": upstream_user_id,
        "kyc_id": kyc.get("kyc_id"),
        "kyc_upstream_status": kyc.get("status"),
        "kyc_synced_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.contacts.update_one({"id": contact_id}, {"$set": cache_update})

    # Resolve relative doc URLs to absolute upstream URLs so the CRM UI can hyperlink them
    admin_base = os.environ.get("TRATA_ADMIN_API_URL", "").rstrip("/")
    if admin_base:
        for d in kyc.get("docs") or []:
            u = d.get("url") or ""
            if u.startswith("/"):
                d["url"] = admin_base + u

    return {
        "available": True,
        "kyc": kyc,
        "synced_at": cache_update["kyc_synced_at"],
        "local_decision": c.get("kyc_status"),
        "local_decision_at": c.get("kyc_reviewed_at"),
        "local_decision_notes": c.get("kyc_review_notes"),
    }


class KycDocReviewBody(BaseModel):
    doc_id: str
    decision: str   # "approved" | "rejected"
    notes: Optional[str] = None


@api.post("/contacts/{contact_id}/kyc-doc-review")
async def review_kyc_doc(contact_id: str, data: KycDocReviewBody, current=Depends(get_current_user)):
    """Per-document review by sales rep. Stored locally in contact.agent_doc_reviews; emitted as kyc.note_added."""
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal users only")
    if data.decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be approved|rejected")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_sales_rep(current) and c.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="Not your lead")
    reviews = c.get("agent_doc_reviews") or {}
    reviews[data.doc_id] = {
        "decision": data.decision,
        "notes": data.notes,
        "reviewer_phone": current.get("phone"),
        "reviewer_name": current.get("name"),
        "reviewed_at": now_iso(),
    }
    await db.contacts.update_one({"id": contact_id}, {"$set": {"agent_doc_reviews": reviews, "updated_at": now_iso()}})
    await ab.queue_outbound(db, "crm.kyc.doc_reviewed", {
        "phone": c.get("phone"),
        "kyc_id": c.get("kyc_id"),
        "upstream_user_id": c.get("upstream_user_id"),
        "doc_id": data.doc_id,
        "decision": data.decision,
        "text": f"[Doc {data.doc_id[:8]}] {data.decision.upper()}" + (f" — {data.notes}" if data.notes else ""),
        "author_phone": current.get("phone"),
        "author_role": current.get("role") or "sales_rep",
        "author_name": current.get("name"),
        "reviewed_at": now_iso(),
    })
    return {"success": True, "agent_doc_reviews": reviews}


# ---------- AI KYC Pre-screening (Phase 6.6) ----------
# Scans every KYC doc with Gemini Vision and pre-fills approve/reject recommendations
# so the sales rep starts from an AI suggestion instead of a blank slate.
_DOC_MIME_BY_EXT = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "heic": "image/heic", "heif": "image/heif",
}


def _mime_from(url: str, fallback: str = "application/octet-stream") -> str:
    u = (url or "").split("?")[0].lower()
    for ext, mt in _DOC_MIME_BY_EXT.items():
        if u.endswith("." + ext):
            return mt
    return fallback


async def _download_admin_doc(url: str) -> Optional[tuple]:
    """Download a KYC doc from the Trata Admin App. Returns (tmp_path, mime_type) or None."""
    import httpx
    import tempfile
    key = os.environ.get("TRATA_ADMIN_API_KEY", "")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
        if r.status_code != 200:
            logger.warning(f"_download_admin_doc {url} -> {r.status_code}")
            return None
        mime = r.headers.get("content-type", "").split(";")[0].strip() or _mime_from(url)
        # Pick extension for the temp file so Gemini can sniff it
        ext_map = {v: "." + k for k, v in _DOC_MIME_BY_EXT.items()}
        suffix = ext_map.get(mime) or "." + (_mime_from(url, "bin").split("/")[-1])
        fd = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        fd.write(r.content)
        fd.close()
        return fd.name, mime
    except Exception as e:
        logger.error(f"_download_admin_doc failed for {url}: {e}")
        return None


def _parse_ai_json(text: str) -> Dict[str, Any]:
    """Best-effort JSON extraction from an LLM response."""
    s = (text or "").strip()
    # Strip ```json … ``` or ``` … ``` fences
    if s.startswith("```"):
        # Drop the opening fence (and optional language tag) then the closing fence
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    # Find the outermost {...}
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(s[start:end + 1])
        except Exception:
            pass
    return {}


async def _ai_screen_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Send a single KYC document to Gemini Vision and return a structured recommendation.

    Returns: {recommendation: 'approve'|'reject'|'unclear', reason: str, confidence: 0..1, model: str}
    """
    import os as _os
    from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType

    kind = doc.get("kind") or "kyc_document"
    name = doc.get("name") or kind
    url = doc.get("url") or ""

    if not url:
        return {"recommendation": "unclear", "reason": "No document URL available.", "confidence": 0.0, "model": "skipped"}

    dl = await _download_admin_doc(url)
    if not dl:
        return {"recommendation": "unclear", "reason": "Could not download document from upstream.", "confidence": 0.0, "model": "skipped"}
    path, mime = dl

    # Gemini Flash supports image/* and application/pdf via FileContentWithMimeType.
    supported = mime.startswith("image/") or mime == "application/pdf"
    if not supported:
        try:
            _os.unlink(path)
        except Exception:
            pass
        return {"recommendation": "unclear", "reason": f"Unsupported mime type: {mime}", "confidence": 0.0, "model": "skipped"}

    system = (
        "You are a KYC document verification assistant for TrataHealth's ambulance-provider "
        "onboarding workflow. You inspect uploaded Indian compliance documents (PAN card, "
        "Aadhaar, GST certificate, RC, insurance, fitness certificate, drug license, etc.) and "
        "(1) give the sales rep a fast first-pass approve/reject recommendation and "
        "(2) extract the structured fields visible on the document so the rep doesn't have to "
        "retype them. You are NOT the final approver — the sales rep and master admin make the "
        "binding decision. Be strict on the recommendation: only APPROVE if the document is "
        "clearly legible, the document type matches the expected kind, and there are no obvious "
        "tampering or expiry red flags. Be conservative on extraction: only return fields you can "
        "read with certainty; leave others empty. Never invent values."
    )
    prompt = (
        f"Expected document kind: {kind}\nFile name: {name}\n\n"
        "Inspect the attached file and respond with ONLY a single JSON object, no prose, no markdown.\n"
        "Schema:\n"
        "{\n"
        '  "recommendation": "approve" | "reject" | "unclear",\n'
        '  "reason": "<one short sentence>",\n'
        '  "confidence": <0.0-1.0>,\n'
        '  "extracted": {\n'
        '    "document_number": "<the primary id printed on the doc, e.g. PAN no., GST no., Aadhaar last-4, registration no.>",\n'
        '    "name": "<full name on doc, if any>",\n'
        '    "father_name": "<father name on PAN/Aadhaar, if any>",\n'
        '    "dob": "<YYYY-MM-DD or as printed>",\n'
        '    "pan_number": "<if PAN>",\n'
        '    "gst_number": "<if GST cert>",\n'
        '    "aadhaar_last4": "<last 4 digits if Aadhaar>",\n'
        '    "vehicle_reg": "<if RC/insurance/fitness>",\n'
        '    "vehicle_make_model": "<if RC>",\n'
        '    "issue_date": "<YYYY-MM-DD>",\n'
        '    "expiry_date": "<YYYY-MM-DD>",\n'
        '    "address": "<full address if printed>",\n'
        '    "issuing_authority": "<RTO/dept/insurer name if shown>"\n'
        "  }\n"
        "}\n"
        "Omit (do NOT include) any key inside `extracted` whose value you cannot read with certainty."
    )

    try:
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"kyc-ai-screen-{doc.get('id') or uuid.uuid4()}",
            system_message=system,
        ).with_model("gemini", "gemini-2.5-flash")
        attachment = FileContentWithMimeType(file_path=path, mime_type=mime)
        reply = await chat.send_message(UserMessage(text=prompt, file_contents=[attachment]))
        raw_text = str(reply)
        parsed = _parse_ai_json(raw_text)
        if not parsed:
            logger.warning(f"AI prescreen: could not parse JSON. Raw response (first 500 chars): {raw_text[:500]}")
        rec = (parsed.get("recommendation") or "").strip().lower()
        if rec not in {"approve", "reject", "unclear"}:
            rec = "unclear"
        try:
            conf = float(parsed.get("confidence", 0.0))
        except Exception:
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        raw_extracted = parsed.get("extracted") or {}
        # Whitelist + sanitize extracted fields (drop empties, cap length)
        ALLOWED = {
            "document_number", "name", "father_name", "dob",
            "pan_number", "gst_number", "aadhaar_last4",
            "vehicle_reg", "vehicle_make_model", "issue_date", "expiry_date",
            "address", "issuing_authority",
        }
        extracted: Dict[str, str] = {}
        if isinstance(raw_extracted, dict):
            for k, v in raw_extracted.items():
                if k in ALLOWED and v is not None:
                    sv = str(v).strip()
                    if sv and sv.lower() not in {"unknown", "n/a", "na", "none", "null"}:
                        extracted[k] = sv[:200]
        return {
            "recommendation": rec,
            "reason": str(parsed.get("reason") or "").strip()[:400] or "No reason returned.",
            "confidence": conf,
            "extracted": extracted,
            "model": "gemini-2.5-flash",
        }
    except Exception as e:
        logger.error(f"_ai_screen_doc failed: {e}")
        return {"recommendation": "unclear", "reason": f"AI scan failed: {str(e)[:160]}", "confidence": 0.0, "model": "error"}
    finally:
        try:
            _os.unlink(path)
        except Exception:
            pass


@api.post("/contacts/{contact_id}/kyc-ai-prescreen")
async def ai_prescreen_kyc(contact_id: str, current=Depends(get_current_user)):
    """Run AI vision pre-screening over every uploaded KYC document for this lead.
    Stores per-doc {recommendation, reason, confidence} on contact.ai_doc_prescreens
    so the sales rep starts from an AI suggestion in KycMirrorCard."""
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal users only")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI not configured (EMERGENT_LLM_KEY missing)")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_sales_rep(current) and c.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="Not your lead")

    upstream_user_id = c.get("upstream_user_id")
    if not upstream_user_id:
        admin_user = await ab.find_admin_user_by_phone(c.get("phone") or "")
        if not admin_user:
            raise HTTPException(status_code=400, detail="No matching Trata Admin user — open KYC tab first to sync.")
        upstream_user_id = admin_user["id"]

    kyc = await ab.fetch_kyc(upstream_user_id)
    if not kyc:
        raise HTTPException(status_code=502, detail="Could not fetch KYC from Trata Admin App.")

    docs = kyc.get("docs") or []
    if not docs:
        raise HTTPException(status_code=400, detail="No documents uploaded yet — nothing to scan.")

    admin_base = os.environ.get("TRATA_ADMIN_API_URL", "").rstrip("/")
    for d in docs:
        u = d.get("url") or ""
        if u.startswith("/") and admin_base:
            d["url"] = admin_base + u

    prescreens: Dict[str, Any] = c.get("ai_doc_prescreens") or {}
    aggregated_fields: Dict[str, Dict[str, str]] = {}  # field_name -> {value, source_doc_id, source_kind}
    approve_n = reject_n = unclear_n = 0
    started = now_iso()

    for d in docs:
        result = await _ai_screen_doc(d)
        result["doc_kind"] = d.get("kind")
        result["doc_name"] = d.get("name")
        result["scanned_at"] = now_iso()
        result["scanned_by"] = current.get("name") or current.get("phone")
        doc_key = d.get("id") or d.get("kind")
        prescreens[doc_key] = result
        if result["recommendation"] == "approve":
            approve_n += 1
        elif result["recommendation"] == "reject":
            reject_n += 1
        else:
            unclear_n += 1
        # Aggregate extracted fields — only from docs the AI approves (skip rejected/unclear to avoid wrong data)
        if result.get("recommendation") == "approve":
            for fk, fv in (result.get("extracted") or {}).items():
                if fk not in aggregated_fields:
                    aggregated_fields[fk] = {"value": fv, "source_doc_id": doc_key, "source_kind": d.get("kind") or ""}

    summary = {
        "approve": approve_n,
        "reject": reject_n,
        "unclear": unclear_n,
        "total": len(docs),
        "scanned_at": now_iso(),
        "scanned_by": current.get("name") or current.get("phone"),
        "model": "gemini-2.5-flash",
    }
    # Merge with any previously extracted fields (preserve old ones not overwritten this run)
    prior_fields = c.get("ai_extracted_fields") or {}
    merged_fields = {**prior_fields, **aggregated_fields}
    await db.contacts.update_one({"id": contact_id}, {"$set": {
        "ai_doc_prescreens": prescreens,
        "ai_prescreen_summary": summary,
        "ai_extracted_fields": merged_fields,
        "updated_at": now_iso(),
    }})

    await ab.queue_outbound(db, "crm.kyc.ai_prescreened", {
        "phone": c.get("phone"),
        "contact_name": c["name"],
        "kyc_id": c.get("kyc_id"),
        "upstream_user_id": c.get("upstream_user_id"),
        "text": f"AI pre-screen: {approve_n} approve / {reject_n} reject / {unclear_n} unclear (model gemini-2.5-flash)",
        "author_phone": current.get("phone"),
        "author_role": current.get("role") or "sales_rep",
        "author_name": current.get("name"),
        "summary": summary,
        "scanned_at": started,
    })

    return {"success": True, "ai_doc_prescreens": prescreens, "ai_prescreen_summary": summary, "ai_extracted_fields": merged_fields}


# Map AI-extracted field names → contact-record field names. Only whitelisted fields can be
# written from AI extraction; everything else is ignored. Values longer than 200 chars are dropped.
AI_FIELD_TO_CONTACT_FIELD = {
    "name":                "name",
    "father_name":         "father_name",
    "dob":                 "dob",
    "pan_number":          "pan_number",
    "gst_number":          "gst_number",
    "aadhaar_last4":       "aadhaar_last4",
    "vehicle_reg":         "vehicle_reg",
    "vehicle_make_model":  "vehicle_make_model",
    "issue_date":          "kyc_doc_issue_date",
    "expiry_date":         "kyc_doc_expiry_date",
    "address":             "address",
    "issuing_authority":   "kyc_doc_authority",
    "document_number":     "kyc_document_number",
}


@api.post("/contacts/{contact_id}/apply-extracted-fields")
async def apply_extracted_fields(contact_id: str, payload: Dict[str, Any] = Body(default={}), current=Depends(get_current_user)):
    """Write AI-extracted KYC fields into the actual contact record.
    Body: {"fields": ["name", "gst_number", ...]}  — list of AI field-names to apply.
    If `fields` is missing or empty, applies ALL fields available in contact.ai_extracted_fields.
    Returns the list of applied {ai_field, contact_field, value} entries."""
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal users only")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_sales_rep(current) and c.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="Not your lead")
    extracted: Dict[str, Any] = c.get("ai_extracted_fields") or {}
    if not extracted:
        raise HTTPException(status_code=400, detail="No AI-extracted fields available — run AI pre-screen first.")

    requested = payload.get("fields") if isinstance(payload, dict) else None
    if isinstance(requested, list) and requested:
        targets = [f for f in requested if f in extracted]
    else:
        targets = list(extracted.keys())

    applied: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    updates: Dict[str, Any] = {}
    for ai_field in targets:
        contact_field = AI_FIELD_TO_CONTACT_FIELD.get(ai_field)
        if not contact_field:
            skipped.append({"ai_field": ai_field, "reason": "Field not in whitelist"})
            continue
        info = extracted.get(ai_field) or {}
        value = str(info.get("value") or "").strip()
        if not value or len(value) > 200:
            skipped.append({"ai_field": ai_field, "reason": "Empty or oversize value"})
            continue
        updates[contact_field] = value
        applied.append({"ai_field": ai_field, "contact_field": contact_field, "value": value, "source_kind": info.get("source_kind")})

    if not applied:
        raise HTTPException(status_code=400, detail="Nothing to apply (no valid fields).")

    updates["updated_at"] = now_iso()
    updates["ai_fields_applied_at"] = now_iso()
    updates["ai_fields_applied_by"] = current.get("name") or current.get("phone")
    await db.contacts.update_one({"id": contact_id}, {"$set": updates})

    # Log an activity for the audit trail
    await db.activities.insert_one({
        "id": str(uuid.uuid4()),
        "type": "note",
        "category": "kyc",
        "subtype": "ai_fields_applied",
        "title": f"Applied {len(applied)} AI-extracted field(s) to contact",
        "outcome": "ai_fields_applied",
        "contact_id": contact_id,
        "contact_name": c.get("name"),
        "agent_id": current.get("id"),
        "agent_name": current.get("name"),
        "summary": f"Applied {len(applied)} AI-extracted field(s) to contact: " + ", ".join(a["ai_field"] for a in applied),
        "payload": {"applied": applied, "skipped": skipped},
        "status": "completed",
        "created_at": now_iso(),
    })

    fresh = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    return {"success": True, "applied": applied, "skipped": skipped, "contact": fresh}




@api.post("/contacts/{contact_id}/kyc-submit-for-admin")
async def submit_kyc_for_admin_final(contact_id: str, current=Depends(get_current_user)):
    """Sales rep declares 'I'm done reviewing all docs — please final-approve, master admin.'
    Sets contact.kyc_status='agent_reviewed' and emits crm.kyc.agent_completed for the admin queue."""
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal users only")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_sales_rep(current) and c.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="Not your lead")
    reviews = c.get("agent_doc_reviews") or {}
    approved = sum(1 for r in reviews.values() if r.get("decision") == "approved")
    rejected = sum(1 for r in reviews.values() if r.get("decision") == "rejected")
    await db.contacts.update_one({"id": contact_id}, {"$set": {
        "kyc_status": "agent_reviewed",
        "kyc_agent_completed_at": now_iso(),
        "kyc_agent_summary": {"approved": approved, "rejected": rejected, "total": len(reviews)},
        "updated_at": now_iso(),
    }})
    await ab.queue_outbound(db, "crm.kyc.agent_completed", {
        "phone": c.get("phone"),
        "name": c.get("name"),
        "kyc_id": c.get("kyc_id"),
        "upstream_user_id": c.get("upstream_user_id"),
        "agent_phone": current.get("phone"),
        "agent_name": current.get("name"),
        "summary": {"approved": approved, "rejected": rejected, "total": len(reviews)},
        "submitted_at": now_iso(),
    })
    return {"success": True, "summary": {"approved": approved, "rejected": rejected, "total": len(reviews)}}


class KycAdminFinalBody(BaseModel):
    decision: str   # "verified" | "rejected"
    notes: Optional[str] = None


@api.post("/contacts/{contact_id}/kyc-admin-final")
async def kyc_admin_final(contact_id: str, data: KycAdminFinalBody, current=Depends(get_current_user)):
    """Master admin final approval/rejection after sales rep submits."""
    if not (current.get("is_master_admin") or current.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="Master admin only")
    if data.decision not in {"verified", "rejected"}:
        raise HTTPException(status_code=400, detail="decision must be verified|rejected")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Lead not found")
    new_stage = "verified" if data.decision == "verified" else c.get("pipeline_stage")
    await db.contacts.update_one({"id": contact_id}, {"$set": {
        "kyc_status": data.decision,
        "kyc_admin_decision_at": now_iso(),
        "kyc_admin_decision_notes": data.notes,
        "kyc_admin_decision_by": current.get("name") or current.get("phone"),
        "pipeline_stage": new_stage,
        "updated_at": now_iso(),
    }})
    await ab.queue_outbound(db, "crm.kyc.admin_verified", {
        "phone": c.get("phone"),
        "name": c.get("name"),
        "kyc_id": c.get("kyc_id"),
        "upstream_user_id": c.get("upstream_user_id"),
        "decision": data.decision,
        "text": f"MASTER ADMIN FINAL: {data.decision.upper()}" + (f" — {data.notes}" if data.notes else ""),
        "author_phone": current.get("phone"),
        "author_role": "admin",
        "author_name": current.get("name"),
        "reviewed_at": now_iso(),
    })
    c2 = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    return {"success": True, "contact": c2}


@api.get("/admin/kyc-queue")
async def kyc_admin_queue(current=Depends(get_current_user)):
    """Master admin: list of leads awaiting final approval (kyc_status='agent_reviewed')."""
    if not (current.get("is_master_admin") or current.get("role") == "admin"):
        raise HTTPException(status_code=403, detail="Master admin only")
    items = await db.contacts.find(
        {"kyc_status": "agent_reviewed"},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "city": 1, "state": 1, "type": 1,
         "assigned_agent_name": 1, "assigned_agent_id": 1, "kyc_id": 1,
         "kyc_agent_completed_at": 1, "kyc_agent_summary": 1, "agent_doc_reviews": 1,
         "pipeline_stage": 1, "updated_at": 1},
    ).sort("kyc_agent_completed_at", 1).to_list(200)
    return {"items": items, "total": len(items)}


@api.get("/admin/kyc-queue-count")
async def kyc_admin_queue_count(current=Depends(get_current_user)):
    """Cheap counter for the sidebar badge."""
    if not (current.get("is_master_admin") or current.get("role") == "admin"):
        return {"count": 0}
    return {"count": await db.contacts.count_documents({"kyc_status": "agent_reviewed"})}


# ---------- Team ----------
@api.get("/team")
async def list_team(current=Depends(require_internal)):
    items = await db.crm_users.find(
        {"role": {"$in": ["admin", "manager", "national_manager", "regional_manager", "zonal_manager", "area_manager", "sales_rep", "ops_rep"]}},
        {"_id": 0, "password_hash": 0, "security_questions": 0, "reset_code_hash": 0, "reset_code_expires_at": 0, "reset_code_sent_at": 0, "password": 0},
    ).sort("created_at", 1).to_list(500)
    out = [await _enrich_member(m) for m in items]
    return {"items": out}


@api.post("/team")
async def create_team_member(data: TeamMemberCreate, current=Depends(get_current_user)):
    if current.get("role") != "admin" and not current.get("is_master_admin"):
        raise HTTPException(status_code=403, detail="Only admins can add members")
    if data.role not in INTERNAL_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}")
    existing = await db.crm_users.find_one({"phone": data.phone})
    if existing:
        raise HTTPException(status_code=400, detail="Member with this phone already exists")
    target_role = normalize_role(data.role)
    # Validate reports_to using the same rules as PATCH
    reports_to = None
    if data.reports_to:
        mgr = await db.crm_users.find_one({"id": data.reports_to})
        if not mgr:
            raise HTTPException(status_code=400, detail="Proposed manager not found")
        mgr_role = normalize_role(mgr.get("role") or "")
        expected = parent_role_of(target_role)
        if mgr.get("is_master_admin"):
            if target_role != "national_manager":
                raise HTTPException(status_code=400, detail="Only National Managers can report directly to the Master Admin")
        elif expected is None:
            raise HTTPException(status_code=400, detail=f"{target_role} cannot have a reporting manager")
        elif mgr_role != expected:
            raise HTTPException(status_code=400, detail=f"{target_role.replace('_',' ').title()} must report to a {expected.replace('_',' ').title()}")
        reports_to = data.reports_to
    member = {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "phone": data.phone,
        "email": data.email,
        "role": target_role,
        "is_master_admin": False,
        "is_active": True,
        "reports_to": reports_to,
        "territories": [t.strip() for t in (data.territories or []) if t.strip()],
        "created_at": now_iso(),
    }
    await db.crm_users.insert_one(member.copy())
    member.pop("_id", None)
    return {"success": True, "member": await _enrich_member(member)}


@api.delete("/team/{member_id}")
async def delete_team_member(member_id: str, current=Depends(get_current_user)):
    if current.get("role") != "admin" and not current.get("is_master_admin"):
        raise HTTPException(status_code=403, detail="Only admins can remove members")
    m = await db.crm_users.find_one({"id": member_id})
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    if m.get("is_master_admin"):
        raise HTTPException(status_code=400, detail="Cannot remove master admin")
    # Unassign any subordinates (set their reports_to to null)
    await db.crm_users.update_many({"reports_to": member_id}, {"$set": {"reports_to": None}})
    await db.crm_users.delete_one({"id": member_id})
    return {"success": True}


# ---------- Team hierarchy (Phase: Org Chart) ----------
async def _enrich_member(m: dict) -> dict:
    role = normalize_role(m.get("role") or "")
    out = {
        "id": m.get("id"),
        "name": m.get("name"),
        "phone": m.get("phone"),
        "email": m.get("email"),
        "role": role,
        "raw_role": m.get("role"),
        "is_master_admin": bool(m.get("is_master_admin")),
        "is_active": m.get("is_active", True),
        "territories": m.get("territories") or [],
        "reports_to": m.get("reports_to"),
        "created_at": m.get("created_at"),
    }
    if out["reports_to"]:
        mgr = await db.crm_users.find_one({"id": out["reports_to"]}, {"_id": 0, "id": 1, "name": 1, "role": 1})
        if mgr:
            out["manager_name"] = mgr.get("name")
            out["manager_role"] = normalize_role(mgr.get("role") or "")
    out["reports_count"] = await db.crm_users.count_documents({"reports_to": m["id"]})
    return out


@api.get("/team/{member_id}")
async def get_team_member(member_id: str, current=Depends(require_internal)):
    m = await db.crm_users.find_one({"id": member_id}, {"_id": 0, "password_hash": 0, "security_questions": 0, "reset_code_hash": 0, "reset_code_expires_at": 0, "reset_code_sent_at": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    info = await _enrich_member(m)

    # Manager chain (climb up to root)
    chain = []
    cursor = info.get("reports_to")
    visited = set()
    while cursor and cursor not in visited:
        visited.add(cursor)
        mgr = await db.crm_users.find_one({"id": cursor}, {"_id": 0, "id": 1, "name": 1, "role": 1})
        if not mgr:
            break
        chain.append({"id": mgr["id"], "name": mgr["name"], "role": normalize_role(mgr.get("role") or "")})
        cursor = (await db.crm_users.find_one({"id": cursor}, {"reports_to": 1}) or {}).get("reports_to")
    info["reports_chain"] = chain

    # Direct reports
    reports = []
    async for r in db.crm_users.find({"reports_to": member_id}, {"_id": 0, "password_hash": 0, "security_questions": 0}):
        reports.append(await _enrich_member(r))
    info["direct_reports"] = reports

    # Providers handled (contacts assigned to this user)
    providers_handled = await db.contacts.count_documents({"assigned_agent_id": member_id})
    info["providers_handled"] = providers_handled

    # Sales performance — only meaningful for sales_rep, but compute for managers too based on their tree
    role = normalize_role(m.get("role") or "")
    target_ids = [member_id]
    if role != "sales_rep":
        # Aggregate over all descendants
        async def collect_subs(parent_id, depth=0):
            if depth > 6:
                return
            async for r in db.crm_users.find({"reports_to": parent_id}, {"id": 1, "_id": 0}):
                target_ids.append(r["id"])
                await collect_subs(r["id"], depth + 1)
        await collect_subs(member_id)

    from datetime import timedelta as _td
    month_start = (datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)).isoformat()
    perf_pipeline = [
        {"$match": {"agent_id": {"$in": target_ids}, "created_at": {"$gte": month_start}}},
        {"$group": {"_id": "$category", "count": {"$sum": 1}}},
    ]
    perf_by_cat = {row["_id"]: row["count"] for row in await db.activities.aggregate(perf_pipeline).to_list(50)}
    onboarded = await db.contacts.count_documents({
        "assigned_agent_id": {"$in": target_ids},
        "pipeline_stage": {"$in": ["app_onboarded", "live_on_app", "active", "verified"]},
        "updated_at": {"$gte": month_start},
    })
    info["performance"] = {
        "scope": "self" if role == "sales_rep" else "team_rollup",
        "team_size": len(target_ids),
        "month_start": month_start,
        "activities_total": sum(perf_by_cat.values()),
        "by_category": perf_by_cat,
        "onboarded_mtd": onboarded,
    }

    # Recent activities for this user
    recent = await db.activities.find({"agent_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(10)
    info["recent_activities"] = recent

    # Manager feedback notes
    fb = await db.team_feedback.find({"member_id": member_id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    info["feedback"] = fb

    return info


class TeamMemberUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    reports_to: Optional[str] = None   # pass None or "" to unset
    territories: Optional[List[str]] = None
    is_active: Optional[bool] = None


@api.patch("/team/{member_id}")
async def update_team_member(member_id: str, data: TeamMemberUpdate, current=Depends(get_current_user)):
    if current.get("role") != "admin" and not current.get("is_master_admin"):
        raise HTTPException(status_code=403, detail="Only admins can update team members")
    m = await db.crm_users.find_one({"id": member_id})
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    if m.get("is_master_admin") and (data.role and data.role != "admin"):
        raise HTTPException(status_code=400, detail="Cannot change the master admin's role")

    update: Dict[str, Any] = {}
    if data.name is not None: update["name"] = data.name.strip()
    if data.email is not None: update["email"] = data.email.strip() or None
    if data.territories is not None: update["territories"] = [t.strip() for t in data.territories if t.strip()]
    if data.is_active is not None: update["is_active"] = bool(data.is_active)

    target_role = normalize_role(data.role) if data.role else normalize_role(m.get("role") or "")
    if data.role is not None:
        if data.role not in INTERNAL_ROLES:
            raise HTTPException(status_code=400, detail=f"Invalid role: {data.role}")
        update["role"] = target_role

    # reports_to validation (strict hierarchy)
    if data.reports_to is not None:
        if data.reports_to in ("", None):
            update["reports_to"] = None
        else:
            if data.reports_to == member_id:
                raise HTTPException(status_code=400, detail="A member cannot report to themselves")
            mgr = await db.crm_users.find_one({"id": data.reports_to}, {"_id": 0})
            if not mgr:
                raise HTTPException(status_code=400, detail="Proposed manager not found")
            mgr_role = normalize_role(mgr.get("role") or "")
            expected_parent = parent_role_of(target_role)
            if mgr.get("is_master_admin"):
                # Master admin can be parent only of national_manager
                if target_role != "national_manager":
                    raise HTTPException(status_code=400, detail="Only National Managers can report directly to the Master Admin")
            elif expected_parent is None:
                raise HTTPException(status_code=400, detail=f"{target_role} cannot have a reporting manager")
            elif mgr_role != expected_parent:
                pretty = expected_parent.replace("_", " ").title()
                raise HTTPException(status_code=400, detail=f"{target_role.replace('_', ' ').title()} must report to a {pretty}")
            # Cycle check
            cursor = mgr.get("reports_to")
            visited = {member_id, data.reports_to}
            while cursor:
                if cursor in visited:
                    raise HTTPException(status_code=400, detail="This change would create a reporting cycle")
                visited.add(cursor)
                upper = await db.crm_users.find_one({"id": cursor}, {"reports_to": 1, "_id": 0})
                cursor = upper.get("reports_to") if upper else None
            update["reports_to"] = data.reports_to

    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = now_iso()
    await db.crm_users.update_one({"id": member_id}, {"$set": update})
    new_doc = await db.crm_users.find_one({"id": member_id}, {"_id": 0, "password_hash": 0, "security_questions": 0})
    return {"success": True, "member": await _enrich_member(new_doc)}


class TeamFeedbackBody(BaseModel):
    rating: Optional[int] = None       # 1..5
    note: str


@api.post("/team/{member_id}/feedback")
async def add_team_feedback(member_id: str, data: TeamFeedbackBody, current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Only admins or managers can leave feedback")
    if not (data.note or "").strip():
        raise HTTPException(status_code=400, detail="Feedback note cannot be empty")
    if data.rating is not None and not (1 <= data.rating <= 5):
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")
    target = await db.crm_users.find_one({"id": member_id})
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")
    fb = {
        "id": str(uuid.uuid4()),
        "member_id": member_id,
        "author_id": current["id"],
        "author_name": current.get("name"),
        "author_role": normalize_role(current.get("role") or "admin"),
        "rating": data.rating,
        "note": data.note.strip(),
        "created_at": now_iso(),
    }
    await db.team_feedback.insert_one(fb.copy())
    fb.pop("_id", None)
    return {"success": True, "feedback": fb}


@api.delete("/team/{member_id}/feedback/{fb_id}")
async def delete_team_feedback(member_id: str, fb_id: str, current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Only admins or managers can delete feedback")
    fb = await db.team_feedback.find_one({"id": fb_id, "member_id": member_id})
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    if fb.get("author_id") != current["id"] and not current.get("is_master_admin") and current.get("role") != "admin":
        raise HTTPException(status_code=403, detail="You can only delete your own feedback")
    await db.team_feedback.delete_one({"id": fb_id})
    return {"success": True}


# ---------- Analytics ----------
@api.get("/analytics/overview")
async def analytics_overview(current=Depends(require_internal)):
    # Cases by status
    cases_by_status: Dict[str, int] = {}
    statuses = ["CREATED", "PARAMEDIC_ASSIGNED", "AMBULANCE_DISPATCHED", "ON_THE_WAY", "REACHED", "COMPLETED", "CANCELLED"]
    for s in statuses:
        cases_by_status[s] = await db.activities.count_documents({"category": "emergency_case", "status": s})

    # Response times distribution
    cursor = db.activities.find({"category": "emergency_case", "response_time_minutes": {"$exists": True}}, {"response_time_minutes": 1, "_id": 0})
    buckets = {"0-5": 0, "5-10": 0, "10-15": 0, "15-30": 0, "30+": 0}
    async for d in cursor:
        rt = d.get("response_time_minutes", 0) or 0
        if rt < 5: buckets["0-5"] += 1
        elif rt < 10: buckets["5-10"] += 1
        elif rt < 15: buckets["10-15"] += 1
        elif rt < 30: buckets["15-30"] += 1
        else: buckets["30+"] += 1

    # Top cities
    pipeline = [
        {"$match": {"city": {"$ne": None}}},
        {"$group": {"_id": "$city", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 8},
    ]
    cities = await db.contacts.aggregate(pipeline).to_list(20)
    top_cities = [{"city": c["_id"], "count": c["count"]} for c in cities if c["_id"]]

    # Revenue trend last 30 days
    rev_by_day = []
    for i in range(29, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()
        end = (datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
        cur = db.activities.find({"created_at": {"$gte": start, "$lt": end}, "amount": {"$gt": 0}}, {"amount": 1})
        total = 0
        async for d in cur:
            total += d.get("amount", 0)
        rev_by_day.append({"date": day.isoformat(), "revenue": round(total, 2)})

    return {
        "cases_by_status": cases_by_status,
        "response_time_buckets": buckets,
        "top_cities": top_cities,
        "revenue_30d": rev_by_day,
    }


# ---------- Export ----------
@api.get("/export/contacts.csv")
async def export_contacts_csv(type: Optional[str] = None, current=Depends(require_internal)):
    qry = {"type": type} if type else {}
    items = await db.contacts.find(qry, {"_id": 0}).to_list(10000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    cols = ["id", "name", "type", "phone", "email", "city", "state", "specialization", "is_verified", "pipeline_stage", "deal_value", "created_at"]
    writer.writerow(cols)
    for it in items:
        writer.writerow([it.get(c, "") for c in cols])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


# ---------- Notifications ----------
@api.get("/notifications")
async def list_notifications(limit: int = 30, current=Depends(get_current_user)):
    items = await db.notifications.find({}, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return {"items": items}


# ---------- Global search ----------
@api.get("/search")
async def global_search(q: str, current=Depends(get_current_user)):
    if not q.strip():
        return {"contacts": [], "activities": [], "tasks": []}
    rx = {"$regex": q, "$options": "i"}
    c_filter = {"$or": [{"name": rx}, {"phone": rx}, {"email": rx}, {"specialization": rx}]}
    a_filter = {"$or": [{"title": rx}, {"description": rx}, {"contact_name": rx}]}
    t_filter = {"$or": [{"title": rx}, {"description": rx}]}
    if is_provider(current):
        pid = current.get("provider_id")
        c_filter = {"$and": [c_filter, {"id": pid}]}
        a_filter = {"$and": [a_filter, {"provider_ids": pid}]}
        t_filter = {"$and": [t_filter, {"contact_id": pid}]}
    contacts = await db.contacts.find(
        c_filter,
        {"_id": 0, "id": 1, "name": 1, "type": 1, "phone": 1, "city": 1, "is_verified": 1, "avatar": 1},
    ).limit(10).to_list(10)
    activities = await db.activities.find(
        a_filter,
        {"_id": 0, "id": 1, "title": 1, "category": 1, "status": 1, "contact_name": 1, "created_at": 1},
    ).limit(10).to_list(10)
    tasks = await db.tasks.find(
        t_filter,
        {"_id": 0, "id": 1, "title": 1, "status": 1, "priority": 1, "due_date": 1},
    ).limit(10).to_list(10)
    return {"contacts": contacts, "activities": activities, "tasks": tasks}


# ---------- Sales Agent (onboarding workflow) ----------
class QuickLogActivity(BaseModel):
    contact_id: str
    activity_type: str       # cold_call | pitch_meeting | site_visit | demo | kyc_collection | app_training | follow_up | whatsapp | email | note
    outcome: Optional[str] = None
    notes: Optional[str] = ""
    next_action_at: Optional[str] = None  # ISO date — auto-creates a follow-up task
    advance_to_stage: Optional[str] = None  # explicit stage move
    gps: Optional[Dict[str, float]] = None  # {lat, lng} for site visits


SALES_ACTIVITY_TYPES = {
    "cold_call", "pitch_meeting", "site_visit", "demo",
    "kyc_collection", "app_training", "follow_up", "whatsapp", "email", "note",
}
OUTCOME_TO_STAGE = {
    "not_interested": "churned",
    "interested": "contacted",
    "meeting_scheduled": "contacted",
    "pitched": "contacted",
    "kyc_pending": "contacted",
    "kyc_collected": "kyc_submitted",
    "signed_on_app": "verified",
    "first_use": "active",
}


@api.post("/agent/quick-log")
async def quick_log(data: QuickLogActivity, current=Depends(get_current_user)):
    if not is_sales_rep(current) and not is_internal(current):
        raise HTTPException(status_code=403, detail="Agent or admin only")
    if data.activity_type not in SALES_ACTIVITY_TYPES:
        raise HTTPException(status_code=400, detail=f"Unknown activity type: {data.activity_type}")
    contact = await db.contacts.find_one({"id": data.contact_id}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Lead not found")
    if is_sales_rep(current) and contact.get("assigned_agent_id") != current["id"]:
        raise HTTPException(status_code=403, detail="This lead is not assigned to you")

    activity = {
        "id": str(uuid.uuid4()),
        "category": "sales_activity",
        "subtype": data.activity_type,
        "outcome": data.outcome,
        "contact_id": contact["id"],
        "contact_name": contact["name"],
        "contact_type": contact["type"],
        "city": contact.get("city"),
        "title": f"{data.activity_type.replace('_', ' ').title()} — {contact['name']}",
        "description": data.notes or "",
        "status": data.outcome or "logged",
        "agent_id": current["id"],
        "agent_name": current.get("name"),
        "gps": data.gps,
        "amount": 0,
        "created_at": now_iso(),
        "provider_ids": [],
    }
    await db.activities.insert_one(activity.copy())
    activity.pop("_id", None)

    # Emit outbound — activity logged
    await ab.queue_outbound(db, "crm.activity.logged", {
        "phone": contact.get("phone"),
        "contact_name": contact["name"],
        "activity_type": data.activity_type,
        "outcome": data.outcome,
        "gps": data.gps,
        "agent_phone": current.get("phone"),
        "occurred_at": activity["created_at"],
    })

    # Auto-advance pipeline stage
    target_stage = data.advance_to_stage or OUTCOME_TO_STAGE.get(data.outcome or "")
    if target_stage:
        await db.contacts.update_one(
            {"id": contact["id"]},
            {"$set": {"pipeline_stage": target_stage, "updated_at": now_iso()}},
        )
        if target_stage in {"verified", "active"} and contact.get("pipeline_stage") != target_stage:
            await ab.queue_outbound(db, "crm.deal.closed", {
                "phone": contact.get("phone"),
                "name": contact["name"],
                "final_stage": target_stage,
                "agent_phone": current.get("phone"),
                "updated_at": now_iso(),
            })

    # Auto-create follow-up task
    task = None
    if data.next_action_at:
        task = {
            "id": str(uuid.uuid4()),
            "title": f"Follow up with {contact['name']}",
            "description": f"Auto-created from {data.activity_type} on {now_iso()[:10]}",
            "contact_id": contact["id"],
            "assigned_to": current["id"],
            "priority": "medium",
            "status": "open",
            "due_date": data.next_action_at,
            "created_by": current["id"],
            "created_by_name": current.get("name"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.tasks.insert_one(task.copy())
        task.pop("_id", None)

    return {"success": True, "activity": activity, "advanced_to_stage": target_stage, "follow_up_task": task}


@api.get("/agent/dashboard")
async def agent_dashboard(range_key: str = Query("7d", alias="range"), current=Depends(get_current_user)):
    if not is_sales_rep(current):
        raise HTTPException(status_code=403, detail="Sales rep only")
    aid = current["id"]
    since_iso, range_label, days_back = _range_window(range_key)
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    # "Stale" is fixed at 7 days regardless of the dashboard range — that's the SLA.
    stale_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    window_start = since_iso or "1970-01-01T00:00:00+00:00"

    total_leads = await db.contacts.count_documents({"assigned_agent_id": aid})
    stale_leads = await db.contacts.count_documents({
        "assigned_agent_id": aid,
        "pipeline_stage": {"$in": ["lead", "contacted"]},
        "$or": [{"updated_at": {"$lt": stale_cutoff}}, {"updated_at": {"$exists": False}}],
    })
    by_stage = {}
    for stage in ["lead", "contacted", "kyc_submitted", "verified", "active", "churned"]:
        by_stage[stage] = await db.contacts.count_documents({"assigned_agent_id": aid, "pipeline_stage": stage})

    today_activities = await db.activities.count_documents({"agent_id": aid, "created_at": {"$gte": today_start}})
    window_activities = await db.activities.count_documents({"agent_id": aid, "created_at": {"$gte": window_start}})
    onboarded_in_window = await db.contacts.count_documents({
        "assigned_agent_id": aid, "pipeline_stage": {"$in": ["verified", "active"]},
        "updated_at": {"$gte": window_start},
    })

    # Today's pending tasks
    tasks = await db.tasks.find(
        {"assigned_to": aid, "status": {"$ne": "done"}},
        {"_id": 0},
    ).sort("due_date", 1).limit(20).to_list(20)

    # Hot leads = mine in stages contacted/kyc_submitted, most recent first
    hot = await db.contacts.find(
        {"assigned_agent_id": aid, "pipeline_stage": {"$in": ["contacted", "kyc_submitted", "verified"]}},
        {"_id": 0, "id": 1, "name": 1, "type": 1, "phone": 1, "city": 1, "pipeline_stage": 1, "updated_at": 1, "deal_value": 1, "avatar": 1, "specialization": 1},
    ).sort("updated_at", -1).limit(10).to_list(10)

    # Stale leads needing attention
    stale = await db.contacts.find(
        {"assigned_agent_id": aid, "pipeline_stage": {"$in": ["lead", "contacted"]},
         "$or": [{"updated_at": {"$lt": stale_cutoff}}, {"updated_at": {"$exists": False}}]},
        {"_id": 0, "id": 1, "name": 1, "type": 1, "phone": 1, "city": 1, "pipeline_stage": 1, "updated_at": 1, "specialization": 1},
    ).sort("created_at", 1).limit(10).to_list(10)

    return {
        "range": {"key": range_key, "label": range_label, "days": days_back, "since": since_iso},
        "kpis": {
            "total_leads": total_leads,
            "stale_leads": stale_leads,
            "today_activities": today_activities,
            "window_activities": window_activities,
            "week_activities": window_activities,             # backward-compat alias
            "onboarded_in_window": onboarded_in_window,
            "onboarded_this_week": onboarded_in_window,        # backward-compat alias
        },
        "by_stage": by_stage,
        "today_tasks": tasks,
        "hot_leads": hot,
        "stale_leads_list": stale,
    }


@api.post("/agent/ai-insights")
async def agent_ai_insights(payload: Dict[str, Any] = Body(default={}), current=Depends(get_current_user)):
    """Per-agent AI insights for the agent's currently-selected dashboard range.
    Uses the agent's own dashboard data; admins/managers can also call this."""
    if not is_internal(current):
        raise HTTPException(status_code=403, detail="Internal staff only")
    if not EMERGENT_LLM_KEY:
        raise HTTPException(status_code=503, detail="AI not configured (EMERGENT_LLM_KEY missing)")
    range_key = (payload.get("range") or "7d").lower()
    if range_key not in RANGE_TO_DAYS:
        range_key = "7d"
    # Sales reps see their own data; admins/managers can pass an agent_id to inspect any rep.
    target_id = payload.get("agent_id") or current["id"]
    if is_sales_rep(current) and target_id != current["id"]:
        raise HTTPException(status_code=403, detail="Sales reps can only inspect their own data")
    target = await db.crm_users.find_one({"id": target_id}, {"_id": 0, "id": 1, "name": 1, "role": 1, "phone": 1, "is_master_admin": 1}) if target_id != current["id"] else current
    if not target:
        raise HTTPException(status_code=404, detail="Agent not found")
    # Borrow the same windowed snapshot the dashboard uses
    snap = await agent_dashboard(range_key=range_key, current=target)  # type: ignore[arg-type]
    recent = await db.activities.find(
        {"agent_id": target["id"]},
        {"_id": 0, "title": 1, "subtype": 1, "outcome": 1, "contact_name": 1, "created_at": 1},
    ).sort("created_at", -1).limit(20).to_list(20)
    context_obj = {
        "agent_name": target.get("name") or "this agent",
        "range_label": snap["range"]["label"],
        "kpis": snap["kpis"],
        "by_stage": snap["by_stage"],
        "today_tasks_count": len(snap["today_tasks"]),
        "hot_leads_count": len(snap["hot_leads"]),
        "stale_leads_count": len(snap["stale_leads_list"]),
        "recent_activity_titles": [(a.get("title") or a.get("subtype") or "activity") for a in recent[:15]],
    }
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"agent-insights-{target['id']}-{range_key}-{datetime.now(timezone.utc).date()}",
            system_message=(
                "You are a sales coach for healthcare-provider onboarding agents at TrataHealth. "
                "Given a JSON snapshot of one sales rep's pipeline for a chosen time range, write a "
                "SHORT briefing that the rep (or their manager) can act on in the next 48 hours. "
                "Be specific to the numbers — never invent. If the dataset is small, say so honestly "
                "and recommend what to instrument next. End with one concrete next action."
            ),
        ).with_model("anthropic", "claude-sonnet-4-6")
        msg = UserMessage(text=(
            f"Sales rep: {context_obj['agent_name']}\n"
            f"Time range: {context_obj['range_label']}\n\n"
            f"Data (JSON):\n{json.dumps(context_obj, default=str)}\n\n"
            "Reply in markdown using EXACTLY these four sections (use these literal headings):\n"
            "## Headline\nOne sentence — the single most important thing about this rep's performance right now.\n"
            "## What's working\n2-3 bullets, each citing a number from the data.\n"
            "## What's at risk\n2-3 bullets, each citing a number from the data.\n"
            "## Do next\nOne concrete action the rep should take in the next 48 hours."
        ))
        text = await chat.send_message(msg)
        return {"success": True, "range": snap["range"], "markdown": str(text), "context": context_obj}
    except Exception as e:
        logger.error(f"Agent AI insights error: {e}")
        raise HTTPException(status_code=502, detail=f"AI generation failed: {str(e)[:200]}")


@api.get("/agent/leads/map")
async def agent_leads_map(current=Depends(get_current_user)):
    if not is_sales_rep(current):
        raise HTTPException(status_code=403, detail="Sales rep only")
    leads = await db.contacts.find(
        {"assigned_agent_id": current["id"], "lat": {"$ne": None}},
        {"_id": 0, "id": 1, "name": 1, "type": 1, "phone": 1, "city": 1, "lat": 1, "lng": 1, "pipeline_stage": 1, "updated_at": 1, "specialization": 1},
    ).limit(500).to_list(500)
    if not leads:
        return {"center": None, "leads": []}
    avg_lat = sum(l["lat"] for l in leads) / len(leads)
    avg_lng = sum(l["lng"] for l in leads) / len(leads)
    return {"center": {"lat": avg_lat, "lng": avg_lng}, "leads": leads}


@api.get("/agent/team")
async def list_agents(current=Depends(get_current_user)):
    """Used by admin assignment UI."""
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin only")
    items = await db.crm_users.find(
        {"role": {"$in": ["sales_rep", "manager"]}, "is_active": True},
        {"_id": 0, "id": 1, "name": 1, "phone": 1, "role": 1},
    ).to_list(100)
    return {"items": items}


@api.get("/agent/leads")
async def agent_leads(
    stage: Optional[str] = None,
    city: Optional[str] = None,
    provider_type: Optional[str] = None,
    last_touched: Optional[str] = None,  # 'today' | '7d' | '30d' | 'stale'
    q: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    current=Depends(get_current_user),
):
    if not is_sales_rep(current):
        raise HTTPException(status_code=403, detail="Sales rep only")
    qry: Dict[str, Any] = {"assigned_agent_id": current["id"]}
    if stage: qry["pipeline_stage"] = stage
    if city: qry["city"] = {"$regex": city, "$options": "i"}
    if provider_type: qry["type"] = provider_type
    if q:
        qry["$or"] = [
            {"name": {"$regex": q, "$options": "i"}},
            {"phone": {"$regex": q, "$options": "i"}},
            {"specialization": {"$regex": q, "$options": "i"}},
        ]
    now = datetime.now(timezone.utc)
    if last_touched == "today":
        qry["updated_at"] = {"$gte": now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()}
    elif last_touched == "7d":
        qry["updated_at"] = {"$gte": (now - timedelta(days=7)).isoformat()}
    elif last_touched == "30d":
        qry["updated_at"] = {"$gte": (now - timedelta(days=30)).isoformat()}
    elif last_touched == "stale":
        qry["$or"] = [{"updated_at": {"$lt": (now - timedelta(days=7)).isoformat()}}, {"updated_at": {"$exists": False}}]
    total = await db.contacts.count_documents(qry)
    items = await db.contacts.find(qry, {"_id": 0}).sort("updated_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"items": items, "total": total}


@api.post("/agent/digest")
async def agent_digest(current=Depends(get_current_user)):
    if not is_sales_rep(current):
        raise HTTPException(status_code=403, detail="Sales rep only")
    aid = current["id"]
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    activities = await db.activities.find({"agent_id": aid, "created_at": {"$gte": today_start}}, {"_id": 0}).to_list(200)
    onboarded = await db.contacts.count_documents({"assigned_agent_id": aid, "pipeline_stage": {"$in": ["verified", "active"]}, "updated_at": {"$gte": today_start}})
    tasks_done = await db.tasks.count_documents({"assigned_to": aid, "status": "done", "updated_at": {"$gte": today_start}})

    by_type: Dict[str, int] = {}
    for a in activities:
        st = a.get("subtype") or a.get("category")
        by_type[st] = by_type.get(st, 0) + 1

    summary_lines = [f"- {n}× {t.replace('_', ' ').title()}" for t, n in by_type.items()]
    context = (
        f"Sales agent: {current.get('name')}\n"
        f"Date: {datetime.now(timezone.utc).date().isoformat()}\n"
        f"Activities logged today ({len(activities)}):\n" + "\n".join(summary_lines) + "\n"
        f"Providers onboarded today: {onboarded}\n"
        f"Tasks completed today: {tasks_done}\n"
    )
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"digest-{aid}-{datetime.now(timezone.utc).date()}",
            system_message="You are a sales coach for healthcare-provider onboarding agents at TrataHealth. Be concise, motivating and practical.",
        ).with_model("anthropic", "claude-sonnet-4-6")
        msg = UserMessage(text=f"Write a 4-line end-of-day digest for this agent. Line 1: numbers summary. Line 2: a win to celebrate. Line 3: a gap to address tomorrow. Line 4: the single highest-leverage action for tomorrow morning.\n\n---\n{context}")
        text = await chat.send_message(msg)
        return {"success": True, "text": str(text), "stats": {"activities": len(activities), "by_type": by_type, "onboarded": onboarded, "tasks_done": tasks_done}}
    except Exception as e:
        logger.error(f"Digest AI error: {e}")
        return {"success": False, "text": context, "stats": {"activities": len(activities), "by_type": by_type, "onboarded": onboarded, "tasks_done": tasks_done}}


@api.get("/agent/targets")
async def agent_targets(current=Depends(get_current_user)):
    if not is_sales_rep(current) and not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Forbidden")
    aid = current["id"]
    t = await db.targets.find_one({"agent_id": aid}, {"_id": 0})
    if not t:
        t = {"agent_id": aid, "month_calls": 80, "month_meetings": 24, "month_kyc": 8, "month_onboarded": 5}
    # Compute actuals month-to-date
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    actual = {
        "calls": await db.activities.count_documents({"agent_id": aid, "subtype": {"$in": ["cold_call", "follow_up"]}, "created_at": {"$gte": month_start}}),
        "meetings": await db.activities.count_documents({"agent_id": aid, "subtype": {"$in": ["pitch_meeting", "site_visit", "demo"]}, "created_at": {"$gte": month_start}}),
        "kyc": await db.activities.count_documents({"agent_id": aid, "subtype": "kyc_collection", "created_at": {"$gte": month_start}}),
        "onboarded": await db.contacts.count_documents({"assigned_agent_id": aid, "pipeline_stage": {"$in": ["verified", "active"]}, "updated_at": {"$gte": month_start}}),
    }
    return {"target": t, "actual": actual, "month_start": month_start}


@api.get("/agent/leaderboard")
async def agent_leaderboard(current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    agents = await db.crm_users.find({"role": {"$in": ["sales_rep", "manager"]}, "is_active": True}, {"_id": 0}).to_list(100)
    rows = []
    for a in agents:
        aid = a["id"]
        rows.append({
            "agent_id": aid,
            "name": a.get("name"),
            "role": a.get("role"),
            "calls": await db.activities.count_documents({"agent_id": aid, "subtype": {"$in": ["cold_call", "follow_up"]}, "created_at": {"$gte": month_start}}),
            "meetings": await db.activities.count_documents({"agent_id": aid, "subtype": {"$in": ["pitch_meeting", "site_visit", "demo"]}, "created_at": {"$gte": month_start}}),
            "onboarded": await db.contacts.count_documents({"assigned_agent_id": aid, "pipeline_stage": {"$in": ["verified", "active"]}, "updated_at": {"$gte": month_start}}),
            "leads": await db.contacts.count_documents({"assigned_agent_id": aid}),
        })
    rows.sort(key=lambda r: (r["onboarded"], r["meetings"], r["calls"]), reverse=True)
    return {"items": rows, "month_start": month_start}


# ---------- Provider (multi-tenant) ----------
@api.get("/provider/me")
async def provider_me(current=Depends(get_current_user)):
    """Returns the calling provider's own contact record + KYC + summary."""
    if not is_provider(current):
        raise HTTPException(status_code=403, detail="Provider access only")
    pid = current.get("provider_id")
    contact = await db.contacts.find_one({"id": pid}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Provider record not found")
    return {"contact": contact, "user": current}


@api.get("/provider/dashboard")
async def provider_dashboard(current=Depends(get_current_user)):
    """Per-type tailored dashboard. Returns KPIs + breakdowns scoped to this provider."""
    if not is_provider(current):
        raise HTTPException(status_code=403, detail="Provider access only")
    pid = current.get("provider_id")
    ptype = current.get("provider_type")
    contact = await db.contacts.find_one({"id": pid}, {"_id": 0})

    scope = {"provider_ids": pid}

    # Totals
    total_activities = await db.activities.count_documents(scope)
    completed = await db.activities.count_documents({**scope, "status": {"$in": ["COMPLETED", "completed", "report_ready", "approved"]}})
    active = await db.activities.count_documents({**scope, "status": {"$nin": ["COMPLETED", "completed", "CANCELLED", "cancelled", "report_ready", "no_show"]}})

    # Revenue
    rev_cursor = db.activities.find({**scope, "amount": {"$gt": 0}}, {"amount": 1, "_id": 0})
    revenue = 0
    async for d in rev_cursor:
        revenue += d.get("amount", 0) or 0

    # Last 14 days trend
    trend = []
    for i in range(13, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()
        end = (datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
        c = await db.activities.count_documents({**scope, "created_at": {"$gte": start, "$lt": end}})
        trend.append({"date": day.isoformat(), "activities": c})

    # By category
    by_category = {}
    for cat in ["emergency_case", "appointment", "ambulance_booking", "lab_booking", "pathology_booking", "kyc"]:
        by_category[cat] = await db.activities.count_documents({**scope, "category": cat})

    # Type-specific KPIs (ambulance only — hospital/clinic/path-lab use their HMS)
    extras: Dict[str, Any] = {}
    if ptype == "ambulance":
        meta = contact.get("meta") or {}
        extras["fleet_size"] = meta.get("ambulance_count") or 0
        rt = []
        async for d in db.activities.find({**scope, "response_time_minutes": {"$exists": True, "$ne": None}}, {"response_time_minutes": 1, "_id": 0}):
            rt.append(d["response_time_minutes"])
        extras["avg_response_min"] = round(sum(rt) / len(rt), 1) if rt else None
        extras["trips_completed"] = await db.activities.count_documents({**scope, "category": {"$in": ["ambulance_booking", "emergency_case"]}, "status": {"$in": ["completed", "COMPLETED"]}})
        extras["live_trips"] = await db.activities.count_documents({**scope, "category": "emergency_case", "status": {"$in": ["AMBULANCE_DISPATCHED", "ON_THE_WAY", "REACHED"]}})

    return {
        "contact": contact,
        "provider_type": ptype,
        "kpis": {
            "total_activities": total_activities,
            "active": active,
            "completed": completed,
            "revenue": round(revenue, 2),
            **extras,
        },
        "trend_14d": trend,
        "by_category": by_category,
    }


@api.get("/provider/activities")
async def provider_activities(
    category: Optional[str] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    current=Depends(get_current_user),
):
    if not is_provider(current):
        raise HTTPException(status_code=403, detail="Provider access only")
    pid = current.get("provider_id")
    qry: Dict[str, Any] = {"provider_ids": pid}
    if category: qry["category"] = category
    if status: qry["status"] = status
    total = await db.activities.count_documents(qry)
    items = await db.activities.find(qry, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"items": items, "total": total}


# ---------- Earnings & Payouts ----------
PLATFORM_FEE_PCT = 15.0  # global platform commission for this MVP
PAID_STATUSES = ["COMPLETED", "completed", "report_ready", "delivered"]


def _next_monday_iso() -> str:
    """Next payout = next Monday at 11:00 IST (~05:30 UTC)."""
    now = datetime.now(timezone.utc)
    days_ahead = (7 - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    nxt = (now + timedelta(days=days_ahead)).replace(hour=5, minute=30, second=0, microsecond=0)
    return nxt.isoformat()


@api.get("/provider/earnings")
async def provider_earnings(period: str = "30d", current=Depends(get_current_user)):
    if not is_provider(current):
        raise HTTPException(status_code=403, detail="Provider access only")
    pid = current.get("provider_id")

    # Period window
    days = {"7d": 7, "30d": 30, "90d": 90, "all": 3650}.get(period, 30)
    start = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    base_match = {"provider_ids": pid, "status": {"$in": PAID_STATUSES}, "amount": {"$gt": 0}}
    period_match = {**base_match, "created_at": {"$gte": start}}

    # Aggregations
    total_gross = 0
    transactions = 0
    by_category: Dict[str, float] = {}
    cursor = db.activities.find(period_match, {"_id": 0, "amount": 1, "category": 1})
    async for d in cursor:
        amt = d.get("amount", 0) or 0
        total_gross += amt
        transactions += 1
        cat = d.get("category", "other")
        by_category[cat] = round(by_category.get(cat, 0) + amt, 2)

    # Daily series (last `days`)
    daily = []
    for i in range(min(days, 60) - 1, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).date()
        s = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()
        e = (datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
        cur = db.activities.find({**base_match, "created_at": {"$gte": s, "$lt": e}}, {"amount": 1, "_id": 0})
        v = 0
        async for d in cur:
            v += d.get("amount", 0) or 0
        daily.append({"date": day.isoformat(), "amount": round(v, 2)})

    # Lifetime totals
    lifetime_gross = 0
    async for d in db.activities.find(base_match, {"_id": 0, "amount": 1}):
        lifetime_gross += d.get("amount", 0) or 0

    # Next payout = unpaid period from last paid → next Monday
    last_paid = await db.payouts.find_one({"provider_id": pid, "status": "paid"}, {"_id": 0}, sort=[("period_end", -1)])
    unpaid_since = last_paid["period_end"] if last_paid else (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    unpaid_gross = 0
    async for d in db.activities.find({**base_match, "created_at": {"$gte": unpaid_since}}, {"amount": 1, "_id": 0}):
        unpaid_gross += d.get("amount", 0) or 0
    next_payout_fee = round(unpaid_gross * PLATFORM_FEE_PCT / 100, 2)
    next_payout_net = round(unpaid_gross - next_payout_fee, 2)

    fee = round(total_gross * PLATFORM_FEE_PCT / 100, 2)
    net = round(total_gross - fee, 2)

    return {
        "currency": "INR",
        "period": period,
        "fee_pct": PLATFORM_FEE_PCT,
        "summary": {
            "gross": round(total_gross, 2),
            "fee": fee,
            "net": net,
            "transactions": transactions,
        },
        "lifetime": {
            "gross": round(lifetime_gross, 2),
            "fee": round(lifetime_gross * PLATFORM_FEE_PCT / 100, 2),
            "net": round(lifetime_gross * (1 - PLATFORM_FEE_PCT / 100), 2),
        },
        "next_payout": {
            "scheduled_for": _next_monday_iso(),
            "gross": round(unpaid_gross, 2),
            "fee": next_payout_fee,
            "net": next_payout_net,
        },
        "by_category": by_category,
        "daily": daily,
    }


@api.get("/provider/payouts")
async def provider_payouts(current=Depends(get_current_user), limit: int = 24):
    if not is_provider(current):
        raise HTTPException(status_code=403, detail="Provider access only")
    pid = current.get("provider_id")
    items = await db.payouts.find({"provider_id": pid}, {"_id": 0}).sort("period_end", -1).limit(limit).to_list(limit)
    return {"items": items, "total": len(items)}


# ---------- Fleet (ambulance live map) ----------
@api.get("/provider/fleet")
async def provider_fleet(current=Depends(get_current_user)):
    if not is_provider(current):
        raise HTTPException(status_code=403, detail="Provider access only")
    if current.get("provider_type") != "ambulance":
        raise HTTPException(status_code=400, detail="Fleet map is for ambulance providers only")
    pid = current.get("provider_id")

    vehicles = await db.fleet_vehicles.find({"provider_id": pid}, {"_id": 0}).to_list(200)
    active_states = ["AMBULANCE_DISPATCHED", "ON_THE_WAY", "REACHED"]
    sos = await db.activities.find(
        {"provider_ids": pid, "category": "emergency_case", "status": {"$in": active_states}},
        {"_id": 0, "id": 1, "title": 1, "status": 1, "priority": 1, "contact_name": 1, "city": 1, "response_time_minutes": 1, "created_at": 1, "lat": 1, "lng": 1},
    ).sort("created_at", -1).to_list(50)

    provider = await db.contacts.find_one({"id": pid}, {"_id": 0, "lat": 1, "lng": 1, "city": 1})
    base_lat = (provider or {}).get("lat")
    base_lng = (provider or {}).get("lng")
    for s in sos:
        if not s.get("lat") or not s.get("lng"):
            if base_lat and base_lng:
                s["lat"] = base_lat + random.uniform(-0.04, 0.04)
                s["lng"] = base_lng + random.uniform(-0.04, 0.04)

    return {
        "center": {"lat": base_lat, "lng": base_lng} if base_lat else None,
        "vehicles": vehicles,
        "sos": sos,
    }


@api.get("/provider/invoice/{payout_id}")
async def provider_invoice(payout_id: str, current=Depends(get_current_user)):
    """Returns a printable HTML invoice for one payout, scoped to the calling provider."""
    if not is_provider(current):
        raise HTTPException(status_code=403, detail="Provider access only")
    pid = current.get("provider_id")
    payout = await db.payouts.find_one({"id": payout_id, "provider_id": pid}, {"_id": 0})
    if not payout:
        raise HTTPException(status_code=404, detail="Payout not found")
    contact = await db.contacts.find_one({"id": pid}, {"_id": 0}) or {}

    rows = (
        f"<tr><td>{payout['activity_count']} fulfilled activities ({payout['period_start'][:10]} → {payout['period_end'][:10]})</td>"
        f"<td style='text-align:right'>₹{payout['gross']:,.2f}</td></tr>"
        f"<tr><td>Platform fee ({payout['fee_pct']}%)</td>"
        f"<td style='text-align:right;color:#FF5630'>-₹{payout['fee']:,.2f}</td></tr>"
    )
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Invoice {payout['invoice_number']}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#091E42;max-width:780px;margin:40px auto;padding:0 24px;}}
.hd{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #091E42;padding-bottom:16px;margin-bottom:24px;}}
.brand{{font-weight:900;font-size:24px;letter-spacing:-.02em;}} .brand small{{font-weight:600;color:#5E6C84;font-size:11px;letter-spacing:.12em;text-transform:uppercase;display:block;}}
.meta{{text-align:right;font-size:12px;color:#5E6C84;}} .meta b{{color:#091E42;display:block;font-size:14px;}}
h2{{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#5E6C84;margin:24px 0 8px;}}
table{{width:100%;border-collapse:collapse;margin-bottom:24px;}} td{{padding:10px 0;border-bottom:1px solid #DFE1E6;font-size:14px;}}
.totals{{margin-top:8px;font-size:14px;}} .totals .row{{display:flex;justify-content:space-between;padding:6px 0;}}
.net{{font-weight:900;font-size:20px;background:#091E42;color:#fff;padding:14px 16px;border-radius:6px;display:flex;justify-content:space-between;margin-top:12px;}}
.stamp{{display:inline-block;padding:4px 10px;border:2px solid #36B37E;color:#36B37E;border-radius:4px;font-weight:700;letter-spacing:.1em;font-size:12px;text-transform:uppercase;}}
.foot{{margin-top:48px;font-size:11px;color:#5E6C84;border-top:1px solid #DFE1E6;padding-top:12px;}}
@media print {{ body {{margin:0;}} }}
</style></head><body>
<div class='hd'>
  <div class='brand'>TrataHealth<small>Payout Statement</small></div>
  <div class='meta'><b>{payout['invoice_number']}</b>Issued {payout.get('paid_at', payout.get('created_at',''))[:10]}<br/>Status: {payout['status'].upper()}</div>
</div>
<h2>Billed to</h2>
<div style='font-size:15px;font-weight:700;'>{contact.get('name','—')}</div>
<div style='font-size:13px;color:#5E6C84;'>{(contact.get('type') or '').replace('_',' ').title()} · {contact.get('city','')}, {contact.get('state','')} · +91 {contact.get('phone','')}</div>
{('<div style="font-size:13px;color:#5E6C84;">License: ' + (contact.get('meta') or {}).get('license_number','—') + '</div>') if contact.get('meta') else ''}

<h2>Period</h2>
<table><tr><td>From {payout['period_start'][:10]} to {payout['period_end'][:10]}</td><td style='text-align:right'>{payout['activity_count']} transactions</td></tr></table>

<h2>Breakdown</h2>
<table>{rows}</table>

<div class='net'><span>Net Payout</span><span>₹{payout['net']:,.2f}</span></div>

<h2>Settlement</h2>
<table>
  <tr><td>Method</td><td style='text-align:right'>UPI / NEFT</td></tr>
  <tr><td>UTR / Reference</td><td style='text-align:right;font-family:monospace'>{payout.get('utr','—')}</td></tr>
  <tr><td>Scheduled for</td><td style='text-align:right'>{payout.get('paid_at') or payout.get('scheduled_for','—')}</td></tr>
  <tr><td>Status</td><td style='text-align:right'>{'<span class=stamp>Paid</span>' if payout['status']=='paid' else payout['status'].upper()}</td></tr>
</table>

<div class='foot'>This is a system-generated statement. For any disputes, write to billing@tratahealth.com within 7 days of issue.</div>
<script>window.onload=()=>{{try{{window.focus();}}catch(e){{}}}};</script>
</body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html)


# ---------- AI ----------
@api.post("/ai/insight")
async def ai_insight(data: AISummaryRequest, current=Depends(get_current_user)):
    contact = await db.contacts.find_one({"id": data.contact_id}, {"_id": 0})
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    activities = await db.activities.find({"contact_id": data.contact_id}, {"_id": 0}).sort("created_at", -1).limit(20).to_list(20)

    if data.mode == "next_action":
        prompt = "Suggest the single best next action for this CRM contact in 3-4 short bullet points. Include who should act, what to do, and by when."
    elif data.mode == "draft_email":
        prompt = "Draft a concise, friendly follow-up email/WhatsApp message (max 120 words) tailored to the contact's stage, role and recent activities."
    else:
        prompt = "Summarize this contact's relationship and engagement with TrataHealth in 5 short bullet points (status, recent activity highlights, risks, opportunities)."

    context = (
        f"Contact: {contact.get('name')} ({contact.get('type')})\n"
        f"Phone: {contact.get('phone')}, City: {contact.get('city')}\n"
        f"Specialization: {contact.get('specialization')}\n"
        f"Pipeline stage: {contact.get('pipeline_stage')}, Verified: {contact.get('is_verified')}\n"
        f"Deal value: {contact.get('deal_value', 0)} INR\n"
        f"Recent activities ({len(activities)}):\n"
    )
    for a in activities[:10]:
        context += f" - [{a.get('category')}] {a.get('title')} ({a.get('status')}) on {a.get('created_at', '')[:10]}\n"

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"crm-{data.contact_id}-{data.mode}",
            system_message="You are a helpful CRM assistant for a healthcare emergency platform called TrataHealth. Be concise, practical, and operational.",
        ).with_model("anthropic", "claude-sonnet-4-6")
        msg = UserMessage(text=f"{prompt}\n\n--- Context ---\n{context}")
        text = await chat.send_message(msg)
        return {"success": True, "text": str(text), "mode": data.mode}
    except Exception as e:
        logger.error(f"AI insight error: {e}")
        # fallback summary
        return {
            "success": False,
            "error": str(e),
            "text": f"AI unavailable. Fallback summary: {contact.get('name')} is a {contact.get('type')} in {contact.get('city')} with {len(activities)} recent activities. Stage: {contact.get('pipeline_stage')}.",
            "mode": data.mode,
        }


# ---------- Seed ----------
@api.post("/admin/seed")
async def seed_data(force: bool = False, current=Depends(require_internal)):
    return await _do_seed(force)


async def _do_seed(force: bool = False) -> dict:
    if not force:
        existing = await db.contacts.count_documents({})
        if existing > 0:
            return {"success": True, "skipped": True, "message": f"{existing} contacts already exist"}

    # Wipe (only crm domain collections, not crm_users)
    for col in ["contacts", "activities", "tasks", "notes", "notifications"]:
        await db[col].delete_many({})

    cities = [
        ("Mumbai", "Maharashtra", 19.0760, 72.8777),
        ("Delhi", "Delhi", 28.6139, 77.2090),
        ("Bengaluru", "Karnataka", 12.9716, 77.5946),
        ("Chennai", "Tamil Nadu", 13.0827, 80.2707),
        ("Hyderabad", "Telangana", 17.3850, 78.4867),
        ("Pune", "Maharashtra", 18.5204, 73.8567),
        ("Kolkata", "West Bengal", 22.5726, 88.3639),
        ("Ahmedabad", "Gujarat", 23.0225, 72.5714),
        ("Jaipur", "Rajasthan", 26.9124, 75.7873),
        ("Lucknow", "Uttar Pradesh", 26.8467, 80.9462),
    ]
    specializations = ["Cardiology", "Orthopedics", "Pediatrics", "Neurology", "Dermatology",
                       "General Medicine", "Gynecology", "Oncology", "Psychiatry", "Radiology"]
    pipeline_stages = ["lead", "contacted", "kyc_submitted", "verified", "active", "churned"]
    avatars_doctor = [
        "https://images.unsplash.com/photo-1594824476967-48c8b964273f?w=128&q=80",
        "https://images.unsplash.com/photo-1612349317150-e413f6a5b16d?w=128&q=80",
        "https://images.unsplash.com/photo-1559839734-2b71ea197ec2?w=128&q=80",
    ]
    avatars_hospital = [
        "https://images.unsplash.com/photo-1615770922480-0b9ae80afeba?w=256&q=80",
        "https://images.unsplash.com/photo-1580615631392-aeb060d526e4?w=256&q=80",
    ]

    contacts: list = []
    indian_first_names = ["Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Sai", "Reyansh", "Ayaan", "Krishna", "Ishaan",
                          "Saanvi", "Aanya", "Aadhya", "Aaradhya", "Anaya", "Pari", "Riya", "Diya", "Myra", "Ira"]
    indian_last_names = ["Sharma", "Verma", "Patel", "Kumar", "Singh", "Gupta", "Reddy", "Khan", "Mehta", "Iyer", "Joshi"]

    def make_phone(i):
        return f"9{random.randint(700000000, 999999999)}"

    def make_contact(type_, idx):
        city, state, lat, lng = random.choice(cities)
        first = random.choice(indian_first_names)
        last = random.choice(indian_last_names)
        if type_ == "doctor":
            name = f"Dr. {first} {last}"
            avatar = random.choice(avatars_doctor)
            spec = random.choice(specializations)
        elif type_ == "hospital":
            name = f"{random.choice(['Apollo', 'Fortis', 'Max', 'AIIMS', 'Manipal', 'Narayana', 'City', 'Lifeline', 'Wellness', 'Care'])} {city} Hospital"
            avatar = random.choice(avatars_hospital)
            spec = random.choice(["Multi-Specialty", "Cardiac Care", "Orthopedic Center", "Maternity Hospital", "Tertiary Care"])
        elif type_ == "paramedic":
            name = f"{first} {last}"
            avatar = None
            spec = random.choice(["BLS", "ALS", "Trauma Care", "Cardiac Life Support"])
        elif type_ == "ambulance_provider":
            name = f"{random.choice(['Speed', 'Quick', 'Rapid', 'Lifesaver', 'Emergency', 'Sanjeevani', 'Helping'])} Ambulance Service"
            avatar = None
            spec = f"{random.randint(2, 25)} vehicles"
        elif type_ == "pathologist":
            name = f"{random.choice(['Dr.', ''])} {first} {last} Lab".strip()
            avatar = None
            spec = random.choice(["Blood Tests", "Imaging", "Pathology", "Full Diagnostic"])
        else:  # patient
            name = f"{first} {last}"
            avatar = None
            spec = None

        stage = random.choice(pipeline_stages) if type_ != "patient" else "active"
        is_verified = stage in ("verified", "active")

        return {
            "id": str(uuid.uuid4()),
            "name": name,
            "type": type_,
            "phone": make_phone(idx),
            "email": f"{first.lower()}.{last.lower()}{idx}@example.com" if type_ != "patient" else None,
            "city": city,
            "state": state,
            "lat": lat + random.uniform(-0.1, 0.1),
            "lng": lng + random.uniform(-0.1, 0.1),
            "specialization": spec,
            "avatar": avatar,
            "pipeline_stage": stage,
            "is_verified": is_verified,
            "is_active": True,
            "deal_value": random.choice([0, 10000, 25000, 50000, 100000, 250000]) if type_ != "patient" else 0,
            "rating": round(random.uniform(3.6, 5.0), 1) if type_ != "patient" else None,
            "created_at": (datetime.now(timezone.utc) - timedelta(days=random.randint(0, 90))).isoformat(),
            "notes": None,
            "meta": {
                "license_number": f"LIC-{random.randint(10000, 99999)}" if type_ in ("doctor", "hospital", "ambulance_provider", "pathologist") else None,
                "experience_years": random.randint(2, 30) if type_ == "doctor" else None,
                "total_beds": random.randint(50, 500) if type_ == "hospital" else None,
                "available_beds": random.randint(0, 100) if type_ == "hospital" else None,
                "ambulance_count": random.randint(2, 25) if type_ == "ambulance_provider" else None,
            },
        }

    # build dataset
    counts = {"patient": 80, "doctor": 35, "hospital": 18, "paramedic": 25, "ambulance_provider": 14, "pathologist": 10}
    for t, n in counts.items():
        for i in range(n):
            contacts.append(make_contact(t, i))

    await db.contacts.insert_many([c.copy() for c in contacts])

    # Activities
    activities = []
    case_statuses = ["CREATED", "PARAMEDIC_ASSIGNED", "AMBULANCE_DISPATCHED", "ON_THE_WAY", "REACHED", "COMPLETED", "CANCELLED"]
    appt_statuses = ["scheduled", "completed", "cancelled", "no_show"]
    reasons = ["Chest pain", "Road accident", "Difficulty breathing", "Cardiac arrest", "Severe abdominal pain", "Fall injury", "Stroke symptoms", "Pregnancy emergency", "Fracture", "Allergic reaction"]
    tests = ["CBC", "Lipid Profile", "Liver Function", "Kidney Function", "Thyroid Panel", "HbA1c", "COVID-19 RT-PCR", "Chest X-Ray", "MRI Brain", "USG Abdomen"]

    patient_contacts = [c for c in contacts if c["type"] == "patient"]
    doctor_contacts = [c for c in contacts if c["type"] == "doctor"]
    hospital_contacts = [c for c in contacts if c["type"] == "hospital"]
    ambulance_contacts = [c for c in contacts if c["type"] == "ambulance_provider"]
    pathology_contacts = [c for c in contacts if c["type"] == "pathologist"]

    def make_activity(category, contact, days_back_max=60, extra=None):
        days_back = random.randint(0, days_back_max)
        created = datetime.now(timezone.utc) - timedelta(days=days_back, hours=random.randint(0, 23))
        a = {
            "id": str(uuid.uuid4()),
            "category": category,
            "contact_id": contact["id"],
            "contact_name": contact["name"],
            "contact_type": contact["type"],
            "city": contact["city"],
            "created_at": created.isoformat(),
        }
        if extra:
            a.update(extra)
        return a

    # Emergency cases - tied to patients
    for _ in range(120):
        p = random.choice(patient_contacts)
        status = random.choices(case_statuses, weights=[5, 8, 8, 10, 8, 55, 6])[0]
        resp = random.randint(3, 45)
        amb = random.choice(ambulance_contacts) if random.random() > 0.2 else None
        # destination hospital: most cases route to a hospital, esp. completed ones
        hosp = random.choice(hospital_contacts) if (random.random() > 0.25 or status in ("REACHED", "COMPLETED")) else None
        pids = [x for x in [amb["id"] if amb else None, hosp["id"] if hosp else None] if x]
        a = make_activity("emergency_case", p, 30, {
            "title": f"SOS: {random.choice(reasons)}",
            "description": f"Patient triggered SOS at {p['city']}." + (f" Destination: {hosp['name']}." if hosp else ""),
            "status": status,
            "priority": random.choice(["CRITICAL", "HIGH", "MODERATE"]),
            "response_time_minutes": resp,
            "ambulance_provider_id": amb["id"] if amb else None,
            "ambulance_provider_name": amb["name"] if amb else None,
            "hospital_id": hosp["id"] if hosp else None,
            "hospital_name": hosp["name"] if hosp else None,
            "amount": random.choice([0, 1500, 2500, 3500]) if status == "COMPLETED" else 0,
            "provider_ids": pids,
        })
        activities.append(a)

    # Appointments - patient ↔ doctor
    for _ in range(160):
        p = random.choice(patient_contacts)
        d = random.choice(doctor_contacts)
        status = random.choices(appt_statuses, weights=[35, 50, 10, 5])[0]
        a = make_activity("appointment", p, 60, {
            "title": f"Consultation with {d['name']}",
            "description": f"{random.choice(['Video', 'In-Person'])} consultation - {d['specialization']}",
            "status": status,
            "doctor_id": d["id"],
            "doctor_name": d["name"],
            "amount": random.choice([300, 500, 800, 1200]) if status == "completed" else 0,
            "provider_ids": [d["id"]],
        })
        activities.append(a)

    # Ambulance bookings
    for _ in range(70):
        p = random.choice(patient_contacts)
        amb = random.choice(ambulance_contacts)
        status = random.choices(["pending", "accepted", "in_progress", "completed", "cancelled"], weights=[5, 10, 10, 65, 10])[0]
        a = make_activity("ambulance_booking", p, 45, {
            "title": f"Ambulance — {amb['name']}",
            "description": f"{random.choice(['Emergency', 'Scheduled transfer'])} from {p['city']}",
            "status": status,
            "ambulance_provider_id": amb["id"],
            "ambulance_provider_name": amb["name"],
            "amount": random.choice([800, 1500, 2500, 5000]) if status == "completed" else 0,
            "provider_ids": [amb["id"]],
        })
        activities.append(a)

    # Lab / pathology bookings
    for _ in range(90):
        p = random.choice(patient_contacts)
        lab = random.choice(pathology_contacts)
        status = random.choices(["booked", "sample_collected", "report_ready", "cancelled"], weights=[15, 25, 55, 5])[0]
        cat = random.choice(["lab_booking", "pathology_booking"])
        a = make_activity(cat, p, 45, {
            "title": f"{random.choice(tests)} — {lab['name']}",
            "description": f"Sample collection {random.choice(['at home', 'at lab'])}",
            "status": status,
            "lab_id": lab["id"],
            "lab_name": lab["name"],
            "amount": random.choice([400, 800, 1500, 2500, 4500]) if status == "report_ready" else 0,
            "provider_ids": [lab["id"]],
        })
        activities.append(a)

    # KYC activities - providers
    for c in doctor_contacts + hospital_contacts + ambulance_contacts + pathology_contacts:
        status = "approved" if c["is_verified"] else random.choice(["pending", "submitted", "rejected"])
        activities.append(make_activity("kyc", c, 90, {
            "title": f"KYC — {c['name']}",
            "description": f"{c['type'].replace('_', ' ').title()} KYC review",
            "status": status,
            "amount": 0,
            "provider_ids": [c["id"]],
        }))

    await db.activities.insert_many([a.copy() for a in activities])

    # Tasks
    tasks = []
    for i in range(25):
        c = random.choice(contacts)
        due = datetime.now(timezone.utc) + timedelta(days=random.randint(-5, 14))
        tasks.append({
            "id": str(uuid.uuid4()),
            "title": random.choice([
                f"Follow up with {c['name']}",
                f"Verify KYC docs for {c['name']}",
                f"Schedule onboarding call with {c['name']}",
                f"Review pending bookings for {c['name']}",
                f"Re-engage churned: {c['name']}",
            ]),
            "description": "Auto-generated CRM task",
            "contact_id": c["id"],
            "assigned_to": None,
            "priority": random.choice(["low", "medium", "high", "critical"]),
            "status": random.choices(["open", "in_progress", "done"], weights=[60, 25, 15])[0],
            "due_date": due.isoformat(),
            "created_by": None,
            "created_by_name": "System",
            "created_at": (datetime.now(timezone.utc) - timedelta(days=random.randint(0, 10))).isoformat(),
            "updated_at": now_iso(),
        })
    await db.tasks.insert_many([t.copy() for t in tasks])

    # Notifications
    notifs = []
    for _ in range(15):
        a = random.choice(activities)
        notifs.append({
            "id": str(uuid.uuid4()),
            "title": a["title"],
            "body": a.get("description", ""),
            "level": random.choice(["info", "warning", "danger", "success"]),
            "category": a["category"],
            "ref_id": a["id"],
            "created_at": a["created_at"],
            "read": False,
        })
    await db.notifications.insert_many([n.copy() for n in notifs])

    # Seed team members (besides master admin) — passwords pre-set for demo
    sales_pw = hash_password("Trata@123")
    team_seed = [
        {"name": "Priya Sales Lead", "phone": "9000000001", "email": "priya@tratahealth.com", "role": "manager", "territories": ["Mumbai", "Bengaluru", "Pune"]},
        {"name": "Rohan Sales Rep", "phone": "9000000002", "email": "rohan@tratahealth.com", "role": "sales_rep", "territories": ["Delhi", "Gurugram", "Noida"]},
        {"name": "Anita Ops", "phone": "9000000003", "email": "anita@tratahealth.com", "role": "ops_rep", "territories": []},
    ]
    sales_ids: dict = {}
    for m in team_seed:
        existing = await db.crm_users.find_one({"phone": m["phone"]})
        if existing:
            sales_ids[m["role"]] = existing["id"]
            # Backfill territories on existing agents
            await db.crm_users.update_one(
                {"id": existing["id"]},
                {"$set": {"territories": m.get("territories", [])}},
            )
            continue
        m_full = {
            **m,
            "id": str(uuid.uuid4()),
            "is_master_admin": False,
            "is_active": True,
            "password_hash": sales_pw,
            "created_at": now_iso(),
        }
        await db.crm_users.insert_one(m_full)
        sales_ids[m["role"]] = m_full["id"]

    # Auto-assign provider-type contacts to sales agents (round-robin Rohan + Priya)
    sales_agent_ids = [sales_ids.get("sales_rep"), sales_ids.get("manager")]
    sales_agent_ids = [x for x in sales_agent_ids if x]
    name_by_id = {}
    async for u in db.crm_users.find({"id": {"$in": sales_agent_ids}}, {"_id": 0, "id": 1, "name": 1}):
        name_by_id[u["id"]] = u["name"]
    provider_contacts_for_sales = [c for c in contacts if c["type"] in ("hospital", "doctor", "ambulance_provider", "pathologist", "paramedic")]
    for idx, c in enumerate(provider_contacts_for_sales):
        if not sales_agent_ids:
            break
        aid = sales_agent_ids[idx % len(sales_agent_ids)]
        await db.contacts.update_one(
            {"id": c["id"]},
            {"$set": {"assigned_agent_id": aid, "assigned_agent_name": name_by_id.get(aid)}},
        )

    # Seed demo PROVIDER OWNER accounts — ambulance only. Hospital/clinic/pathology
    # owners use the separate Hospital Management System.
    demo_pw = hash_password("Trata@123")
    demo_provider_seed = [
        ("ambulance", "9000020003", "Ambulance Fleet Owner"),
    ]
    provider_owners = []
    for ptype, phone, label in demo_provider_seed:
        if await db.crm_users.find_one({"phone": phone}):
            continue
        ctype = PROVIDER_TYPE_TO_CONTACT_TYPE[ptype]
        candidates = [c for c in contacts if c["type"] == ctype and c.get("is_verified")]
        if not candidates:
            candidates = [c for c in contacts if c["type"] == ctype]
        if not candidates:
            continue
        contact = candidates[0]
        await db.crm_users.insert_one({
            "id": str(uuid.uuid4()),
            "phone": phone,
            "name": label,
            "email": f"{ptype}.owner@tratahealth.com",
            "role": "provider_owner",
            "provider_type": ptype,
            "provider_id": contact["id"],
            "provider_name": contact["name"],
            "is_master_admin": False,
            "is_active": True,
            "password_hash": demo_pw,
            "created_at": now_iso(),
        })
        provider_owners.append((ptype, contact))

    # Seed fleet VEHICLES for each ambulance provider — coordinates clustered near their city
    await db.fleet_vehicles.delete_many({"provider_id": {"$in": [c["id"] for _, c in provider_owners]}})
    plates = ["MH 01 AB", "MH 02 CD", "DL 03 EF", "DL 04 GH", "KA 05 JK", "TN 06 LM", "WB 07 NP", "GJ 08 QR"]
    veh_types = ["BLS", "ALS", "Patient Transport", "Cardiac"]
    fleet_count = 0
    for ptype, contact in provider_owners:
        if ptype != "ambulance":
            continue
        meta = contact.get("meta") or {}
        n = meta.get("ambulance_count") or random.randint(8, 18)
        for i in range(n):
            state = random.choices(
                ["available", "on_trip", "off_duty", "maintenance"],
                weights=[55, 25, 15, 5],
            )[0]
            await db.fleet_vehicles.insert_one({
                "id": str(uuid.uuid4()),
                "provider_id": contact["id"],
                "plate_number": f"{random.choice(plates)} {random.randint(1000, 9999)}",
                "vehicle_type": random.choice(veh_types),
                "driver_name": random.choice(indian_first_names) + " " + random.choice(indian_last_names),
                "state": state,
                "lat": (contact["lat"] or 19.07) + random.uniform(-0.08, 0.08),
                "lng": (contact["lng"] or 72.87) + random.uniform(-0.08, 0.08),
                "speed_kmh": random.randint(0, 65) if state == "on_trip" else 0,
                "last_updated": now_iso(),
            })
            fleet_count += 1

    # Seed past PAYOUTS for each demo provider — weekly payouts for the last ~10 weeks
    await db.payouts.delete_many({"provider_id": {"$in": [c["id"] for _, c in provider_owners]}})
    payouts_seeded = 0
    for ptype, contact in provider_owners:
        pid = contact["id"]
        # Use existing activity revenue to make payouts feel plausible
        all_acts = [a for a in activities if pid in (a.get("provider_ids") or []) and (a.get("amount") or 0) > 0
                    and a.get("status") in PAID_STATUSES]
        now = datetime.now(timezone.utc)
        for week in range(2, 12):  # weeks 2..11 ago are PAID; the current open week is the upcoming payout
            period_end = now - timedelta(days=now.weekday() + 7 * (week - 1))  # last Monday minus N weeks
            period_start = period_end - timedelta(days=7)
            window = [a for a in all_acts if period_start.isoformat() <= a["created_at"] < period_end.isoformat()]
            if not window:
                continue
            gross = round(sum(a["amount"] for a in window), 2)
            fee = round(gross * PLATFORM_FEE_PCT / 100, 2)
            net = round(gross - fee, 2)
            paid_at = (period_end + timedelta(hours=11)).isoformat()
            await db.payouts.insert_one({
                "id": str(uuid.uuid4()),
                "provider_id": pid,
                "provider_type": ptype,
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "activity_count": len(window),
                "gross": gross,
                "fee": fee,
                "fee_pct": PLATFORM_FEE_PCT,
                "net": net,
                "currency": "INR",
                "status": "paid",
                "paid_at": paid_at,
                "utr": f"UPI{random.randint(100000000000, 999999999999)}",
                "invoice_number": f"TH-INV-{period_end.strftime('%Y%m')}-{random.randint(100, 999)}",
                "created_at": paid_at,
            })
            payouts_seeded += 1

    return {
        "success": True,
        "contacts": len(contacts),
        "activities": len(activities),
        "tasks": len(tasks),
        "notifications": len(notifs),
        "payouts": payouts_seeded,
        "fleet_vehicles": fleet_count,
        "demo_providers": [p[1] for p in demo_provider_seed],
    }


# ---------- Upstream Sync ----------
@api.get("/admin/sync/status")
async def sync_status(current=Depends(require_internal)):
    s = await db.sync_status.find_one({"_id": "upstream"}, {"_id": 0})
    return {
        "enabled": us.upstream_enabled(),
        "interval_min": UPSTREAM_SYNC_INTERVAL_MIN,
        "base_url": os.environ.get("UPSTREAM_API_URL"),
        "last": s,
        "mode": "live" if us.upstream_enabled() else "seeded",
    }


@api.post("/admin/sync/run")
async def sync_run(current=Depends(get_current_user)):
    if not current.get("is_master_admin"):
        raise HTTPException(status_code=403, detail="Only master admin can trigger sync")
    if not us.upstream_enabled():
        raise HTTPException(status_code=400, detail="UPSTREAM_API_URL is not configured")
    syncer = us.make_sync(db)
    try:
        res = await syncer.sync_all(wipe_seed=True)
    finally:
        await syncer.close()
    return res


# ---------- Provider-App Webhook Bridge (Phase 5) ----------
# Receives events from the Trata Provider App so the CRM lead pipeline can
# auto-advance the moment a healthcare provider signs up or starts using the app.

WEBHOOK_EVENT_TO_STAGE = {
    "provider.signed_up": "verified",
    "provider.first_use": "active",
}


def _normalize_phone(phone: Optional[str]) -> str:
    if not phone:
        return ""
    s = "".join(ch for ch in str(phone) if ch.isdigit())
    # Drop country code 91 if present and total length 12+
    if len(s) == 12 and s.startswith("91"):
        s = s[2:]
    return s


def _verify_webhook_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    if not PROVIDER_WEBHOOK_SECRET:
        return False
    if not signature_header:
        return False
    sig = signature_header.strip()
    if sig.startswith("sha256="):
        sig = sig[len("sha256="):]
    expected = hmac.new(PROVIDER_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def sign_webhook_payload(raw_body: bytes) -> str:
    return "sha256=" + hmac.new(PROVIDER_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


async def _pick_agent_for_territory(city: Optional[str]) -> Optional[Dict[str, Any]]:
    """Pick the next sales agent for a given city using round-robin within matching territories."""
    city_l = (city or "").strip().lower()
    agents = await db.crm_users.find(
        {"role": {"$in": ["sales_rep", "manager"]}, "is_active": True},
        {"_id": 0, "id": 1, "name": 1, "territories": 1, "role": 1},
    ).to_list(200)
    if not agents:
        return None
    matched = [a for a in agents if city_l and any(city_l == (t or "").strip().lower() for t in (a.get("territories") or []))]
    pool = matched or agents  # fall back to all agents
    # Round-robin counter keyed by territory bucket
    bucket = (city_l if matched else "_global_")
    ctr_doc = await db.webhook_counters.find_one_and_update(
        {"_id": bucket},
        {"$inc": {"n": 1}},
        upsert=True, return_document=True,
    ) or {"n": 1}
    idx = (ctr_doc.get("n", 1) - 1) % len(pool)
    return pool[idx]


class ProviderWebhookBody(BaseModel):
    event: str
    occurred_at: Optional[str] = None
    provider: Dict[str, Any]   # {phone, name, type, city, state, lat, lng, upstream_id, specialization, email}


@api.post("/webhooks/provider-app")
async def provider_app_webhook(
    request: Request,
    x_trata_signature: Optional[str] = Header(default=None, alias="X-Trata-Signature"),
):
    raw = await request.body()
    if not _verify_webhook_signature(raw, x_trata_signature):
        # Log failed attempt
        await db.webhook_events.insert_one({
            "id": str(uuid.uuid4()),
            "event": "invalid_signature",
            "status": "rejected",
            "error": "Bad or missing X-Trata-Signature",
            "payload": (raw[:512].decode("utf-8", errors="ignore") if raw else ""),
            "created_at": now_iso(),
        })
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        body_dict = json.loads(raw.decode("utf-8") or "{}")
        body = ProviderWebhookBody(**body_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")

    if body.event not in WEBHOOK_EVENT_TO_STAGE:
        raise HTTPException(status_code=400, detail=f"Unsupported event: {body.event}")

    target_stage = WEBHOOK_EVENT_TO_STAGE[body.event]
    provider = body.provider or {}
    phone_norm = _normalize_phone(provider.get("phone"))
    if not phone_norm:
        raise HTTPException(status_code=400, detail="provider.phone is required")

    # Match by normalized phone
    contact = None
    async for c in db.contacts.find({}, {"_id": 0}):
        if _normalize_phone(c.get("phone")) == phone_norm:
            contact = c
            break

    action = ""
    created_new = False
    prev_stage = contact.get("pipeline_stage") if contact else None

    if not contact:
        # Auto-create a brand-new lead and assign by territory round-robin
        agent = await _pick_agent_for_territory(provider.get("city"))
        contact = {
            "id": str(uuid.uuid4()),
            "name": provider.get("name") or f"Provider {phone_norm}",
            "type": provider.get("type") or "ambulance_provider",
            "phone": phone_norm,
            "email": provider.get("email"),
            "city": provider.get("city"),
            "state": provider.get("state"),
            "lat": provider.get("lat"),
            "lng": provider.get("lng"),
            "specialization": provider.get("specialization"),
            "is_verified": target_stage in ("verified", "active"),
            "is_active": target_stage == "active",
            "pipeline_stage": target_stage,
            "deal_value": 0,
            "assigned_agent_id": agent["id"] if agent else None,
            "assigned_agent_name": agent["name"] if agent else None,
            "source": "provider_app_webhook",
            "upstream_id": provider.get("upstream_id"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "avatar": None,
        }
        await db.contacts.insert_one(contact.copy())
        contact.pop("_id", None)
        created_new = True
        action = f"created_lead_in_stage_{target_stage}"
    else:
        await db.contacts.update_one(
            {"id": contact["id"]},
            {"$set": {
                "pipeline_stage": target_stage,
                "is_verified": target_stage in ("verified", "active"),
                "is_active": target_stage == "active",
                "upstream_id": provider.get("upstream_id") or contact.get("upstream_id"),
                "updated_at": now_iso(),
            }},
        )
        action = f"advanced_{prev_stage}_to_{target_stage}"

    # Log activity so it shows in feed + agent dashboard
    activity = {
        "id": str(uuid.uuid4()),
        "category": "webhook_sync",
        "subtype": body.event,
        "outcome": target_stage,
        "contact_id": contact["id"],
        "contact_name": contact["name"],
        "contact_type": contact.get("type"),
        "city": contact.get("city"),
        "title": f"Provider App: {body.event.replace('.', ' ').replace('_', ' ').title()} — {contact['name']}",
        "description": f"Auto-advanced pipeline to {target_stage} via Trata Provider App webhook.",
        "status": "completed",
        "agent_id": contact.get("assigned_agent_id"),
        "agent_name": contact.get("assigned_agent_name"),
        "amount": 0,
        "created_at": body.occurred_at or now_iso(),
        "provider_ids": [contact["id"]],
        "source": "provider_app_webhook",
    }
    await db.activities.insert_one(activity.copy())

    # Persist webhook event record
    event_record = {
        "id": str(uuid.uuid4()),
        "event": body.event,
        "status": "accepted",
        "contact_id": contact["id"],
        "contact_name": contact["name"],
        "action": action,
        "stage": target_stage,
        "created_new_lead": created_new,
        "assigned_agent_name": contact.get("assigned_agent_name"),
        "phone": phone_norm,
        "city": provider.get("city"),
        "created_at": now_iso(),
    }
    await db.webhook_events.insert_one(event_record.copy())
    event_record.pop("_id", None)

    return {"ok": True, "action": action, "contact_id": contact["id"], "pipeline_stage": target_stage, "created_new_lead": created_new}


@api.get("/admin/webhooks/events")
async def list_webhook_events(limit: int = 50, current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    items = await db.webhook_events.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 200))
    return {"items": items, "total": len(items), "secret_configured": bool(PROVIDER_WEBHOOK_SECRET)}


class WebhookTestSendBody(BaseModel):
    event: str = "provider.signed_up"
    phone: str
    name: Optional[str] = None
    type: Optional[str] = "ambulance_provider"
    city: Optional[str] = None
    state: Optional[str] = None
    upstream_id: Optional[str] = None


@api.post("/admin/webhooks/test-send")
async def webhook_test_send(data: WebhookTestSendBody, current=Depends(get_current_user)):
    """Admin/manager-only: signs a mock provider-app event with our shared secret and processes it."""
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    if data.event not in WEBHOOK_EVENT_TO_STAGE:
        raise HTTPException(status_code=400, detail=f"Unsupported event: {data.event}. Use {list(WEBHOOK_EVENT_TO_STAGE)}")
    payload = {
        "event": data.event,
        "occurred_at": now_iso(),
        "provider": {
            "phone": data.phone,
            "name": data.name,
            "type": data.type,
            "city": data.city,
            "state": data.state,
            "upstream_id": data.upstream_id or f"mock-{uuid.uuid4().hex[:8]}",
        },
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = sign_webhook_payload(raw)
    # Process inline as if the upstream had POSTed it — easier than self-HTTP.
    body_obj = ProviderWebhookBody(**payload)
    if not _verify_webhook_signature(raw, signature):
        raise HTTPException(status_code=500, detail="Internal: signature self-verification failed (check PROVIDER_WEBHOOK_SECRET)")

    phone_norm = _normalize_phone(body_obj.provider.get("phone"))
    if not phone_norm:
        raise HTTPException(status_code=400, detail="phone is required")
    target_stage = WEBHOOK_EVENT_TO_STAGE[body_obj.event]
    contact = None
    async for c in db.contacts.find({}, {"_id": 0}):
        if _normalize_phone(c.get("phone")) == phone_norm:
            contact = c
            break
    prev_stage = contact.get("pipeline_stage") if contact else None
    created_new = False
    if not contact:
        agent = await _pick_agent_for_territory(body_obj.provider.get("city"))
        contact = {
            "id": str(uuid.uuid4()),
            "name": body_obj.provider.get("name") or f"Provider {phone_norm}",
            "type": body_obj.provider.get("type") or "ambulance_provider",
            "phone": phone_norm,
            "city": body_obj.provider.get("city"),
            "state": body_obj.provider.get("state"),
            "specialization": body_obj.provider.get("specialization"),
            "is_verified": True,
            "is_active": target_stage == "active",
            "pipeline_stage": target_stage,
            "deal_value": 0,
            "assigned_agent_id": agent["id"] if agent else None,
            "assigned_agent_name": agent["name"] if agent else None,
            "source": "provider_app_webhook",
            "upstream_id": body_obj.provider.get("upstream_id"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "avatar": None,
        }
        await db.contacts.insert_one(contact.copy())
        created_new = True
        action = f"created_lead_in_stage_{target_stage}"
    else:
        await db.contacts.update_one(
            {"id": contact["id"]},
            {"$set": {
                "pipeline_stage": target_stage,
                "is_verified": target_stage in ("verified", "active"),
                "is_active": target_stage == "active",
                "upstream_id": body_obj.provider.get("upstream_id") or contact.get("upstream_id"),
                "updated_at": now_iso(),
            }},
        )
        action = f"advanced_{prev_stage}_to_{target_stage}"

    await db.activities.insert_one({
        "id": str(uuid.uuid4()),
        "category": "webhook_sync",
        "subtype": body_obj.event,
        "outcome": target_stage,
        "contact_id": contact["id"],
        "contact_name": contact["name"],
        "contact_type": contact.get("type"),
        "city": contact.get("city"),
        "title": f"Provider App: {body_obj.event.replace('.', ' ').replace('_', ' ').title()} — {contact['name']}",
        "description": f"Auto-advanced pipeline to {target_stage} via Trata Provider App webhook (test send).",
        "status": "completed",
        "agent_id": contact.get("assigned_agent_id"),
        "agent_name": contact.get("assigned_agent_name"),
        "amount": 0,
        "created_at": now_iso(),
        "provider_ids": [contact["id"]],
        "source": "provider_app_webhook_test",
    })
    await db.webhook_events.insert_one({
        "id": str(uuid.uuid4()),
        "event": body_obj.event,
        "status": "accepted",
        "contact_id": contact["id"],
        "contact_name": contact["name"],
        "action": action,
        "stage": target_stage,
        "created_new_lead": created_new,
        "assigned_agent_name": contact.get("assigned_agent_name"),
        "phone": phone_norm,
        "city": body_obj.provider.get("city"),
        "test_send": True,
        "created_at": now_iso(),
    })
    return {
        "ok": True,
        "action": action,
        "contact_id": contact["id"],
        "pipeline_stage": target_stage,
        "created_new_lead": created_new,
        "signed_payload": payload,
        "signature": signature,
    }


# ---------- Trata Admin App ⇄ CRM Bridge ----------
class AdminInboundBody(BaseModel):
    event: str
    id: str
    timestamp: Optional[str] = None
    data: Dict[str, Any]


async def _handle_admin_event(body: AdminInboundBody) -> Dict[str, Any]:
    """Apply the inbound event to CRM state. Mirrors Phase 5 webhook semantics for provider lifecycle."""
    event = body.event
    d = body.data or {}
    phone = _normalize_phone(d.get("phone") or d.get("provider_phone"))
    if event in {"provider.signed_up", "provider.first_use"} and phone:
        stage = "verified" if event == "provider.signed_up" else "active"
        contact = None
        async for c in db.contacts.find({}, {"_id": 0}):
            if _normalize_phone(c.get("phone")) == phone:
                contact = c
                break
        if not contact:
            agent = await _pick_agent_for_territory(d.get("city"))
            contact = {
                "id": str(uuid.uuid4()),
                "name": d.get("name") or f"Provider {phone}",
                "type": d.get("type") or "ambulance_provider",
                "phone": phone,
                "city": d.get("city"),
                "state": d.get("state"),
                "is_verified": True,
                "is_active": stage == "active",
                "pipeline_stage": stage,
                "deal_value": 0,
                "assigned_agent_id": agent["id"] if agent else None,
                "assigned_agent_name": agent["name"] if agent else None,
                "source": "trata_admin_webhook",
                "upstream_id": d.get("upstream_id"),
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "avatar": None,
            }
            await db.contacts.insert_one(contact.copy())
            # Notify master admin (in-app notification + outbound to admin app for cross-channel)
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "kind": "new_provider_signup",
                "title": f"New {d.get('type','provider')} signed up — {contact['name']}",
                "body": f"Auto-assigned to {contact.get('assigned_agent_name') or 'no agent'} (city: {d.get('city') or '—'}). Review and reassign if needed.",
                "audience": "admin",
                "contact_id": contact["id"],
                "created_at": now_iso(),
                "read": False,
            })
            return {"action": f"created_lead_in_stage_{stage}", "contact_id": contact["id"]}
        await db.contacts.update_one({"id": contact["id"]}, {"$set": {
            "pipeline_stage": stage,
            "is_verified": True,
            "is_active": stage == "active",
            "upstream_id": d.get("upstream_id") or contact.get("upstream_id"),
            "updated_at": now_iso(),
        }})
        return {"action": f"advanced_to_{stage}", "contact_id": contact["id"]}

    if event in {"provider.kyc.submitted", "provider.kyc.updated"} and phone:
        contact = await db.contacts.find_one({"phone": phone}, {"_id": 0, "id": 1, "name": 1})
        if not contact:
            return {"action": "ignored_unknown_phone"}
        docs = d.get("docs") or []
        kyc_status = "in_review" if event == "provider.kyc.submitted" else "updated"
        await db.contacts.update_one({"id": contact["id"]}, {"$set": {
            "kyc_status": kyc_status,
            "kyc_docs": docs,
            "kyc_updated_at": now_iso(),
            "updated_at": now_iso(),
        }})
        # Stage bump if still in early stages
        await db.contacts.update_one(
            {"id": contact["id"], "pipeline_stage": {"$in": ["lead", "contacted"]}},
            {"$set": {"pipeline_stage": "kyc_submitted"}},
        )
        return {"action": f"kyc_{kyc_status}", "contact_id": contact["id"], "docs_count": len(docs)}

    if event == "provider.deactivated" and phone:
        contact = await db.contacts.find_one({"phone": phone}, {"_id": 0, "id": 1})
        if not contact:
            return {"action": "ignored_unknown_phone"}
        await db.contacts.update_one({"id": contact["id"]}, {"$set": {
            "is_active": False,
            "deactivated_at": now_iso(),
            "deactivation_reason": d.get("reason"),
            "updated_at": now_iso(),
        }})
        return {"action": "deactivated", "contact_id": contact["id"]}

    if event == "provider.profile.updated" and phone:
        contact = await db.contacts.find_one({"phone": phone}, {"_id": 0, "id": 1})
        if not contact:
            return {"action": "ignored_unknown_phone"}
        allowed = {"name", "email", "city", "state", "specialization", "lat", "lng"}
        changes = {k: v for k, v in (d.get("changed_fields") or {}).items() if k in allowed}
        if changes:
            changes["updated_at"] = now_iso()
            await db.contacts.update_one({"id": contact["id"]}, {"$set": changes})
        return {"action": "profile_updated", "contact_id": contact["id"], "fields": list(changes.keys())}

    if event == "payout.processed" and phone:
        # Just log it as an activity tied to the provider so it shows in their timeline.
        contact = await db.contacts.find_one({"phone": phone}, {"_id": 0, "id": 1, "name": 1, "assigned_agent_id": 1, "assigned_agent_name": 1})
        if not contact:
            return {"action": "ignored_unknown_phone"}
        await db.activities.insert_one({
            "id": str(uuid.uuid4()),
            "category": "payout",
            "subtype": "processed",
            "title": f"Weekly payout settled — ₹{d.get('amount', 0):,}",
            "description": f"Period: {d.get('period', 'this week')}",
            "contact_id": contact["id"],
            "contact_name": contact["name"],
            "amount": d.get("amount") or 0,
            "status": "completed",
            "agent_id": contact.get("assigned_agent_id"),
            "agent_name": contact.get("assigned_agent_name"),
            "created_at": now_iso(),
            "provider_ids": [contact["id"]],
            "source": "trata_admin_webhook",
        })
        return {"action": "payout_logged", "contact_id": contact["id"]}

    return {"action": "ignored", "reason": "unsupported event or missing phone"}


@api.post("/webhooks/admin-app")
async def admin_app_webhook(
    request: Request,
    x_trata_signature: Optional[str] = Header(default=None, alias="X-Trata-Signature"),
):
    raw = await request.body()
    if not ab.verify_signature(raw, x_trata_signature):
        await db.admin_bridge_events.insert_one({
            "id": str(uuid.uuid4()),
            "direction": "inbound",
            "status": "rejected",
            "reason": "invalid_signature",
            "raw": raw[:512].decode("utf-8", errors="ignore"),
            "created_at": now_iso(),
        })
        raise HTTPException(status_code=401, detail="Invalid signature")
    try:
        body_dict = json.loads(raw.decode("utf-8") or "{}")
        body = AdminInboundBody(**body_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
    if body.event not in ab.INBOUND_EVENTS:
        raise HTTPException(status_code=400, detail=f"Unsupported event: {body.event}")

    # Idempotency dedupe by event.id
    existing = await db.admin_bridge_events.find_one({"event_id": body.id, "direction": "inbound"}, {"_id": 0})
    if existing:
        return {"ok": False, "error": "duplicate_event", "received": False}

    try:
        result = await _handle_admin_event(body)
    except Exception as e:
        logger.exception("admin-app webhook handler failed")
        await db.admin_bridge_events.insert_one({
            "id": str(uuid.uuid4()),
            "direction": "inbound",
            "event_id": body.id,
            "event": body.event,
            "status": "errored",
            "reason": str(e)[:200],
            "data": body.data,
            "created_at": now_iso(),
        })
        raise HTTPException(status_code=500, detail="Handler failed")

    await db.admin_bridge_events.insert_one({
        "id": str(uuid.uuid4()),
        "direction": "inbound",
        "event_id": body.id,
        "event": body.event,
        "status": "accepted",
        "result": result,
        "data": body.data,
        "created_at": now_iso(),
    })
    return {"ok": True, "received": True, "result": result}


@api.get("/admin/bridge/events")
async def list_bridge_events(limit: int = 50, direction: Optional[str] = None, current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    q: Dict[str, Any] = {}
    if direction in ("inbound", "outbound"):
        q["direction"] = direction
    inbound = await db.admin_bridge_events.find(q or {}, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 200))
    outbound = await db.admin_bridge_outbound.find({}, {"_id": 0}).sort("created_at", -1).to_list(min(limit, 200))
    counts = {
        "outbound_pending": await db.admin_bridge_outbound.count_documents({"status": {"$in": ["pending", "retrying"]}}),
        "outbound_sent": await db.admin_bridge_outbound.count_documents({"status": "sent"}),
        "outbound_failed": await db.admin_bridge_outbound.count_documents({"status": "failed"}),
        "inbound_total": await db.admin_bridge_events.count_documents({"direction": "inbound"}),
    }
    return {
        "inbound": inbound,
        "outbound": outbound,
        "counts": counts,
        "config": {
            "admin_api_url": os.environ.get("TRATA_ADMIN_API_URL", ""),
            "admin_webhook_url": os.environ.get("TRATA_ADMIN_WEBHOOK_URL", ""),
            "secret_configured": bool(os.environ.get("ADMIN_CRM_WEBHOOK_SECRET")),
            "admin_api_key_configured": bool(os.environ.get("TRATA_ADMIN_API_KEY")),
        },
    }


class AdminBridgeTestSend(BaseModel):
    event: str
    data: Dict[str, Any]


@api.post("/admin/bridge/test-send")
async def bridge_test_send(body: AdminBridgeTestSend, current=Depends(get_current_user)):
    """Admin/manager-only: queue an outbound event RIGHT NOW so we can confirm the upstream URL works."""
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    if body.event not in ab.OUTBOUND_EVENTS:
        raise HTTPException(status_code=400, detail=f"Unsupported outbound event: {body.event}. Allowed: {sorted(ab.OUTBOUND_EVENTS)}")
    record = await ab.queue_outbound(db, body.event, body.data)
    return {"ok": True, "queued": record}


@api.post("/admin/bridge/sync-users")
async def bridge_sync_users(current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    result = await ab.sync_users_from_admin(db)
    return {"ok": True, **result}



@api.post("/admin/bridge/retry/{record_id}")
async def bridge_retry(record_id: str, current=Depends(get_current_user)):
    if not is_admin_or_manager(current):
        raise HTTPException(status_code=403, detail="Admin/manager only")
    rec = await db.admin_bridge_outbound.find_one({"id": record_id}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="Outbound event not found")
    if rec.get("status") == "sent":
        return {"ok": True, "already_sent": True}
    # Reset attempts so retry is not blocked
    await db.admin_bridge_outbound.update_one(
        {"id": record_id},
        {"$set": {"status": "retrying", "next_attempt_at": now_iso(), "attempts": 0, "last_error": None}},
    )
    ok = await ab._send_one(db, record_id)
    fresh = await db.admin_bridge_outbound.find_one({"id": record_id}, {"_id": 0})
    return {"ok": ok, "record": fresh}


# ---------- Startup ----------
@app.on_event("startup")
async def startup():
    # NOTE: Demo seeding disabled (iter 17). The CRM now operates entirely on real data sourced from
    # the Trata Admin App via /api/webhooks/admin-app + the 5-min /api/admin/users sync.
    # To re-seed for local dev, call POST /api/admin/seed manually.
    # Backfill agent territories for Phase-5 webhook bridge (idempotent)
    territory_backfill = [
        ("9000000001", ["Mumbai", "Bengaluru", "Pune"]),
        ("9000000002", ["Delhi", "Gurugram", "Noida"]),
    ]
    for phone, terr in territory_backfill:
        await db.crm_users.update_one(
            {"phone": phone, "$or": [{"territories": {"$exists": False}}, {"territories": {"$size": 0}}]},
            {"$set": {"territories": terr}},
        )
    # Migrate legacy "manager" role → "regional_manager" (idempotent)
    await db.crm_users.update_many({"role": "manager"}, {"$set": {"role": "regional_manager"}})
    # Start background loops: outbound dispatcher, periodic /admin/users sync, escalation
    ab.start_dispatcher(db)
    # Backfill agent territories for Phase-5 webhook bridge (idempotent)
    territory_backfill = [
        ("9000000001", ["Mumbai", "Bengaluru", "Pune"]),
        ("9000000002", ["Delhi", "Gurugram", "Noida"]),
    ]
    for phone, terr in territory_backfill:
        await db.crm_users.update_one(
            {"phone": phone, "$or": [{"territories": {"$exists": False}}, {"territories": {"$size": 0}}]},
            {"$set": {"territories": terr}},
        )
    # Migrate legacy "manager" role → "regional_manager" (idempotent)
    await db.crm_users.update_many({"role": "manager"}, {"$set": {"role": "regional_manager"}})
    # Start outbound bridge dispatcher
    ab.start_dispatcher(db)
    # Wire baseline hierarchy: Rohan (sales_rep) reports to Priya if not set yet
    priya = await db.crm_users.find_one({"phone": "9000000001"}, {"id": 1, "_id": 0})
    rohan = await db.crm_users.find_one({"phone": "9000000002"}, {"id": 1, "reports_to": 1, "_id": 0})
    if priya and rohan and not rohan.get("reports_to"):
        # Sales rep must report to area_manager — but Priya is regional_manager.
        # Skip auto-link to keep hierarchy clean; admin can wire it via UI once area managers exist.
        pass
    # Ensure master admin exists
    if not await db.crm_users.find_one({"phone": MASTER_ADMIN_PHONE}):
        await db.crm_users.insert_one({
            "id": str(uuid.uuid4()),
            "phone": MASTER_ADMIN_PHONE,
            "name": "Master Admin",
            "email": "admin@tratahealth.com",
            "role": "admin",
            "is_master_admin": True,
            "is_active": True,
            "avatar": None,
            "created_at": now_iso(),
        })
    # Kick upstream sync (immediate + background loop)
    if us.upstream_enabled():
        logger.info(f"Upstream sync enabled → {os.environ.get('UPSTREAM_API_URL')}")
        try:
            syncer = us.make_sync(db)
            res = await syncer.sync_all(wipe_seed=True)
            await syncer.close()
            logger.info(f"Initial upstream sync: {res}")
            # If upstream returned nothing, fall back to demo seed so the UI isn't empty
            if not res.get("success") and (await db.contacts.count_documents({})) == 0:
                logger.warning("Upstream returned no data; falling back to demo seed")
                await _do_seed(force=True)
        except Exception as e:
            logger.exception(f"Initial upstream sync failed: {e}")
            if (await db.contacts.count_documents({})) == 0:
                await _do_seed(force=True)
        us.start_background(db, UPSTREAM_SYNC_INTERVAL_MIN)


@app.on_event("shutdown")
async def shutdown():
    us.stop_background()
    client.close()


@api.get("/")
async def root():
    return {"name": "TrataHealth CRM API", "status": "ok"}


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)
