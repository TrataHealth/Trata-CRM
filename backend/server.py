"""
TrataHealth Master Admin CRM - Backend
Comprehensive CRM for managing all users (patients, doctors, hospitals, paramedics, ambulance providers, pathologists),
their activities (emergency cases, appointments, bookings, KYC), deal pipeline, tasks, and analytics.
"""
import os
import logging
import uuid
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, APIRouter, HTTPException, Depends, Header, Query
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

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

app = FastAPI(title="TrataHealth CRM API")
api = APIRouter(prefix="/api")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------- Roles & Scopes ----------
INTERNAL_ROLES = {"admin", "manager", "sales_rep", "ops_rep"}
PROVIDER_ROLES = {"provider_owner"}
PROVIDER_TYPE_TO_CONTACT_TYPE = {
    "hospital": "hospital",
    "clinic": "doctor",   # clinic is run by a doctor in this MVP
    "ambulance": "ambulance_provider",
    "pathology": "pathologist",
}


def is_internal(user: dict) -> bool:
    return user.get("role") in INTERNAL_ROLES or user.get("is_master_admin")


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
    role: str = "sales_rep"   # admin, manager, sales_rep, ops_rep


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
    return {"user": current}


# ---------- Dashboard ----------
@api.get("/dashboard/stats")
async def dashboard_stats(current=Depends(require_internal)):
    total_contacts = await db.contacts.count_documents({})
    by_type = {}
    for t in ["patient", "doctor", "hospital", "paramedic", "ambulance_provider", "pathologist"]:
        by_type[t] = await db.contacts.count_documents({"type": t})

    verified = await db.contacts.count_documents({"is_verified": True})
    pending = await db.contacts.count_documents({"is_verified": False})

    total_activities = await db.activities.count_documents({})
    active_cases = await db.activities.count_documents({
        "category": "emergency_case",
        "status": {"$nin": ["COMPLETED", "CANCELLED", "CLOSED"]},
    })
    completed_cases = await db.activities.count_documents({"category": "emergency_case", "status": "COMPLETED"})

    appointments_today = await db.activities.count_documents({
        "category": "appointment",
        "created_at": {"$gte": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
    })

    # Pipeline stages
    pipeline = {}
    for stage in ["lead", "contacted", "kyc_submitted", "verified", "active", "churned"]:
        pipeline[stage] = await db.contacts.count_documents({"pipeline_stage": stage})

    # Revenue (sum of activities with amount)
    cursor = db.activities.find({"amount": {"$gt": 0}}, {"amount": 1, "_id": 0})
    total_revenue = 0
    async for d in cursor:
        total_revenue += d.get("amount", 0) or 0

    tasks_open = await db.tasks.count_documents({"status": {"$ne": "done"}})
    tasks_overdue = await db.tasks.count_documents({
        "status": {"$ne": "done"},
        "due_date": {"$lt": now_iso()},
    })

    # Growth: last 14 days
    growth = []
    for i in range(13, -1, -1):
        day = (datetime.now(timezone.utc) - timedelta(days=i)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc).isoformat()
        end = (datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(days=1)).isoformat()
        c = await db.contacts.count_documents({"created_at": {"$gte": start, "$lt": end}})
        a = await db.activities.count_documents({"created_at": {"$gte": start, "$lt": end}})
        growth.append({"date": day.isoformat(), "new_contacts": c, "activities": a})

    # Activity by category (donut)
    activity_breakdown = {}
    for cat in ["emergency_case", "appointment", "ambulance_booking", "lab_booking", "pathology_booking", "kyc"]:
        activity_breakdown[cat] = await db.activities.count_documents({"category": cat})

    return {
        "users": {
            "total": total_contacts,
            "verified": verified,
            "pending": pending,
            "by_type": by_type,
        },
        "cases": {
            "total": await db.activities.count_documents({"category": "emergency_case"}),
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
    # Scope: providers only see themselves (everything else hidden)
    if is_provider(current):
        qry["id"] = current.get("provider_id")
    total = await db.contacts.count_documents(qry)
    items = (
        await db.contacts.find(qry, {"_id": 0})
        .sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    )
    return {"items": items, "total": total}


@api.get("/contacts/{contact_id}")
async def get_contact(contact_id: str, current=Depends(get_current_user)):
    if is_provider(current) and contact_id != current.get("provider_id"):
        raise HTTPException(status_code=403, detail="Forbidden")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Contact not found")
    acts = await db.activities.find({"contact_id": contact_id}, {"_id": 0}).sort("created_at", -1).limit(100).to_list(100)
    notes = await db.notes.find({"contact_id": contact_id}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    tasks = await db.tasks.find({"contact_id": contact_id}, {"_id": 0}).sort("created_at", -1).limit(50).to_list(50)
    return {"contact": c, "activities": acts, "notes": notes, "tasks": tasks}


@api.patch("/contacts/{contact_id}")
async def update_contact(contact_id: str, data: ContactStatusUpdate, current=Depends(require_internal)):
    update = {k: v for k, v in data.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="No fields to update")
    update["updated_at"] = now_iso()
    r = await db.contacts.update_one({"id": contact_id}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Contact not found")
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    return {"success": True, "contact": c}


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
    return {"success": True, "note": note}


# ---------- Team ----------
@api.get("/team")
async def list_team(current=Depends(require_internal)):
    items = await db.crm_users.find({}, {"_id": 0, "password": 0}).sort("created_at", 1).to_list(200)
    return {"items": items}


@api.post("/team")
async def create_team_member(data: TeamMemberCreate, current=Depends(get_current_user)):
    if current.get("role") != "admin" and not current.get("is_master_admin"):
        raise HTTPException(status_code=403, detail="Only admins can add members")
    existing = await db.crm_users.find_one({"phone": data.phone})
    if existing:
        raise HTTPException(status_code=400, detail="Member with this phone already exists")
    member = {
        "id": str(uuid.uuid4()),
        "name": data.name,
        "phone": data.phone,
        "email": data.email,
        "role": data.role,
        "is_master_admin": False,
        "is_active": True,
        "created_at": now_iso(),
    }
    await db.crm_users.insert_one(member.copy())
    member.pop("_id", None)
    return {"success": True, "member": member}


@api.delete("/team/{member_id}")
async def delete_team_member(member_id: str, current=Depends(get_current_user)):
    if current.get("role") != "admin" and not current.get("is_master_admin"):
        raise HTTPException(status_code=403, detail="Only admins can remove members")
    m = await db.crm_users.find_one({"id": member_id})
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    if m.get("is_master_admin"):
        raise HTTPException(status_code=400, detail="Cannot remove master admin")
    await db.crm_users.delete_one({"id": member_id})
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

    # Type-specific KPIs
    extras: Dict[str, Any] = {}
    if ptype == "hospital":
        meta = contact.get("meta") or {}
        extras["total_beds"] = meta.get("total_beds") or 0
        extras["available_beds"] = meta.get("available_beds") or 0
        extras["occupancy_pct"] = (
            round(100 * (1 - (extras["available_beds"] / extras["total_beds"])), 1)
            if extras["total_beds"] else 0
        )
        extras["incoming_today"] = await db.activities.count_documents({
            **scope, "category": "emergency_case",
            "status": {"$in": ["AMBULANCE_DISPATCHED", "ON_THE_WAY"]},
        })
    elif ptype == "ambulance":
        meta = contact.get("meta") or {}
        extras["fleet_size"] = meta.get("ambulance_count") or 0
        # avg response time
        rt = []
        async for d in db.activities.find({**scope, "response_time_minutes": {"$exists": True, "$ne": None}}, {"response_time_minutes": 1, "_id": 0}):
            rt.append(d["response_time_minutes"])
        extras["avg_response_min"] = round(sum(rt) / len(rt), 1) if rt else None
        extras["trips_completed"] = await db.activities.count_documents({**scope, "category": {"$in": ["ambulance_booking", "emergency_case"]}, "status": {"$in": ["completed", "COMPLETED"]}})
        extras["live_trips"] = await db.activities.count_documents({**scope, "category": "emergency_case", "status": {"$in": ["AMBULANCE_DISPATCHED", "ON_THE_WAY", "REACHED"]}})
    elif ptype == "clinic":
        extras["appointments_today"] = await db.activities.count_documents({
            **scope, "category": "appointment",
            "created_at": {"$gte": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},
        })
        extras["no_show_rate_pct"] = await _no_show_rate(scope)
    elif ptype == "pathology":
        extras["samples_collected"] = await db.activities.count_documents({**scope, "status": "sample_collected"})
        extras["reports_ready"] = await db.activities.count_documents({**scope, "status": "report_ready"})
        extras["pending_bookings"] = await db.activities.count_documents({**scope, "status": "booked"})

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


async def _no_show_rate(scope: dict) -> float:
    total = await db.activities.count_documents({**scope, "category": "appointment"})
    if not total:
        return 0.0
    no_show = await db.activities.count_documents({**scope, "category": "appointment", "status": "no_show"})
    return round(100 * no_show / total, 1)


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

    # Seed team members (besides master admin)
    team_seed = [
        {"name": "Priya Sales Lead", "phone": "9000000001", "email": "priya@tratahealth.com", "role": "manager"},
        {"name": "Rohan Sales Rep", "phone": "9000000002", "email": "rohan@tratahealth.com", "role": "sales_rep"},
        {"name": "Anita Ops", "phone": "9000000003", "email": "anita@tratahealth.com", "role": "ops_rep"},
    ]
    for m in team_seed:
        existing = await db.crm_users.find_one({"phone": m["phone"]})
        if not existing:
            m_full = {**m, "id": str(uuid.uuid4()), "is_master_admin": False, "is_active": True, "created_at": now_iso()}
            await db.crm_users.insert_one(m_full)

    # Seed demo PROVIDER OWNER accounts — one per provider type, linked to a verified contact
    demo_pw = hash_password("Trata@123")
    demo_provider_seed = [
        ("hospital",  "9000020001", "Apollo Hospital Owner"),
        ("clinic",    "9000020002", "Clinic Doctor Owner"),
        ("ambulance", "9000020003", "Ambulance Fleet Owner"),
        ("pathology", "9000020004", "Path Lab Owner"),
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


# ---------- Startup ----------
@app.on_event("startup")
async def startup():
    # Auto-seed on first boot ONLY when upstream is not configured
    count = await db.contacts.count_documents({})
    if count == 0 and not us.upstream_enabled():
        logger.info("No contacts found, seeding demo data...")
        result = await _do_seed(force=True)
        logger.info(f"Seeded: {result}")
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
