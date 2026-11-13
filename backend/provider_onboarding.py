"""Admin onboarding that mirrors the Provider App's sign-up forms (mobile/app/unified-signup.tsx) field-for-field
and writes the same rows its /api/self-signup/* handlers write."""
from __future__ import annotations

import json

import asyncpg
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import supabase_db as sb


def F(k, label, col=None, type="text", req=False, ph="", opts=None, show_if=None):
    return {"k": k, "label": label, "col": col, "type": type, "req": req, "ph": ph, "opts": opts, "show_if": show_if}


ADDR = [F("address", "Address", "address", req=True, ph="Full street address"),
        F("pincode", "Pincode", "pincode", req=True, ph="6-digit pincode"),
        F("city", "City", "city", req=True), F("state", "State", "state", req=True)]
ADDR_OPT = [dict(f, req=False) for f in ADDR]
EMAIL = F("email", "Email", "email", "email", ph="Email address")
HOSPITAL = [F("fullName", "Your Full Name", None, req=True, ph="e.g. Dr. Priya Sharma"),
            F("name", "Hospital/Clinic Name", "name", req=True, ph="e.g. Sunrise Care Hospital"), *ADDR,
            F("licenseNumber", "License Number", "license_number", req=True, ph="Enter license number..."),
            F("hfrId", "ABDM HFR ID (optional — for ABDM Verified badge)", "hfr_id", ph="e.g. IN1234000001"),
            F("capacity", "Bed Capacity", "capacity", "number", ph="Number of beds...")]
DOCTOR = [F("fullName", "Full Name", "full_name", req=True, ph="Dr. Full Name..."), EMAIL,
          F("licenseNumber", "License Number", "license_number", req=True, ph="Medical license number..."),
          F("hprId", "ABDM HPR ID (optional — for ABDM Verified badge)", "hpr_id", ph="e.g. dr.name@hpr.abdm"),
          F("specialization", "Specialization", "specialization", ph="e.g. Cardiology"),
          F("qualification", "Qualification", "qualification", req=True, ph="e.g., MBBS, MD Medicine"),
          F("experience", "Experience (Years)", "experience", "number"),
          F("doctorType", "Where do you practise?", "doctor_type", "select", True,
            opts=[["hospital_doctor", "At a hospital"], ["clinic_doctor", "At my own clinic"]]),
          F("hospitalId", "Hospital", "hospital_id", "hospital", show_if=["doctorType", "hospital_doctor"]),
          F("clinicName", "Clinic Name", "clinic_name", show_if=["doctorType", "clinic_doctor"])]
LAB = [F("fullName", "Full Name", None, req=True), EMAIL, F("labName", "Lab Name", "name", req=True, ph="Enter lab name..."),
       F("labAddress", "Lab Address", "address", ph="Full lab address..."),
       F("licenseNumber", "License Number", "license_number", req=True, ph="Lab license number..."),
       F("pincode", "Pincode", "pincode", req=True), F("city", "City", "city", req=True), F("state", "State", "state", req=True),
       F("qualification", "Qualification", "qualification", ph="e.g. MD Pathology")]
SPECIALITY = {"cancer_care": "Cancer Care", "diabetes": "Diabetes", "women_baby": "Women & Baby Care", "elderly_care": "Elderly Care"}


def hosp(id, label, cat, fixed=None):
    return {"id": id, "label": label, "category": cat, "table": "hospital_profiles", "role": "hospital", "loc": "json",
            "name_key": "fullName", "fields": HOSPITAL, "fixed": {"verification_status": "pending", **(fixed or {})}}


SPECS: List[Dict[str, Any]] = [
    hosp("hospital", "Multi & Super Speciality Hospital", "Hospitals and its Care Facilities", {"hospital_type": "multi_specialty"}),
    {"id": "path_lab", "label": "Path Lab", "category": "Hospitals and its Care Facilities", "table": "path_lab_profiles", "role": "path_lab",
     "loc": "latlng", "name_key": "fullName", "fields": LAB + [F("homeCollection", "Home sample collection", "home_collection", "bool")],
     "fixed": {"verification_status": "pending_review", "is_active": True, "is_verified": False, "is_demo": False}},
    {"id": "diagnostic_centre", "label": "Diagnostic Centre", "category": "Hospitals and its Care Facilities", "table": "diagnostic_centre_profiles",
     "role": "diagnostic_centre", "loc": "latlng", "name_key": "fullName",
     "fields": LAB + [F("homeCollection", "Home sample collection", "home_sample_available", "bool")],
     "fixed": {"verification_status": "pending_review", "is_active": True, "is_verified": False, "is_demo": False}},
    {"id": "pharmacy", "label": "Pharmacy", "category": "Hospitals and its Care Facilities", "table": "pharmacy_providers", "role": "pharmacy",
     "loc": "json", "name_key": "ownerName", "fields": [
        F("businessName", "Pharmacy Name", "business_name", req=True, ph="e.g. MediPlus Pharmacy"),
        F("ownerName", "Owner Name", "owner_name", req=True, ph="Full name of owner / authorised signatory"),
        F("licenseNumber", "Drug License Number", "drug_license_number", req=True, ph="Form 20 / 21 license number"),
        F("gstNumber", "GST Number (optional)", "gst_number", ph="29ABCDE1234F1Z5"), EMAIL, *ADDR,
        F("pharmacistCouncilReg", "Pharmacist Council Registration", "pharmacist_council_reg"),
        F("is24x7", "Open 24x7", "is_24x7", "bool"), F("homeDelivery", "Home delivery", "home_delivery", "bool"),
        F("deliveryRadiusKm", "Delivery radius (km)", "delivery_radius_km", "number")],
     "fixed": {"verification_status": "pending", "is_verified": False}},
    *[hosp(k, v, "Speciality centres", {"hospital_type": "specialised_centre", "specializations": [k]}) for k, v in SPECIALITY.items()],
    hosp("nursing_home", "Nursing Homes", "Speciality centres"),
    {"id": "doctor", "label": "Doctor", "category": "Doctor and Other Healthcare Professionals", "table": "doctors", "role": "doctor",
     "loc": None, "name_key": "fullName", "fields": DOCTOR, "fixed": {"is_verified": False, "is_active": True}},
    {"id": "nurse", "label": "Nurse", "category": "Doctor and Other Healthcare Professionals", "table": "doctors", "role": "doctor",
     "loc": None, "name_key": "fullName", "fields": DOCTOR, "fixed": {"is_verified": False, "is_active": True}},
    {"id": "mental_wellness", "label": "Mental Wellness", "category": "Doctor and Other Healthcare Professionals", "table": "wellness_professionals",
     "role": "wellness", "loc": "json", "name_key": "fullName", "fields": [
        F("subRole", "I practise as", "sub_role", "select", True, opts=[["therapist", "Therapist"], ["psychiatrist", "Psychiatrist"],
          ["counsellor", "Counsellor"], ["coach", "Life Coach"], ["career", "Career Counsellor"], ["relationship", "Relationship Counsellor"],
          ["child", "Child & Adolescent"]]),
        F("fullName", "Full Name", "full_name", req=True, ph="e.g. Dr Anya Sharma"), EMAIL,
        F("qualifications", "Qualifications", "qualifications", req=True, ph="e.g. M.Phil Clinical Psychology / MBBS+MD Psychiatry / ICF certified"),
        F("councilRegistration", "Council Registration", "council_registration", ph="RCI / State Psych Council / Medical Council registration"),
        F("pincode", "Pincode", "pincode"), F("city", "City", "city"), F("state", "State", "state")],
     "fixed": {"verification_status": "pending", "is_verified": False}},
    {"id": "nutritionist", "label": "Nutritionist", "category": "Doctor and Other Healthcare Professionals", "table": "nutritionists",
     "role": "nutritionist", "loc": "json", "name_key": "fullName", "fields": [
        F("fullName", "Full Name", "full_name", req=True, ph="e.g. Priya Sharma"), EMAIL,
        F("qualifications", "Qualifications", "qualifications", req=True, ph="e.g. M.Sc Nutrition, RD"),
        F("councilRegistration", "Council Registration", "council_registration"),
        F("experience", "Experience (Years)", "years_experience", "number"), *ADDR_OPT],
     "fixed": {"verification_status": "pending", "is_verified": False, "consultation_modes": ["video"], "languages": ["English"]}},
    {"id": "ambulance_provider", "label": "Ambulance Service", "category": "Emergency and Medical Support", "table": "ambulance_providers",
     "role": "ambulance_provider", "loc": "business", "name_key": "ownerName", "fields": [
        F("businessName", "Business Name", "business_name", req=True, ph="Ambulance service name..."),
        F("ownerName", "Owner Name", "owner_name", req=True, ph="Owner full name..."), EMAIL,
        F("registrationNumber", "Registration Number", "registration_number", req=True, ph="Business registration number..."),
        F("licenseNumber", "License Number", "license_number", req=True, ph="Operating license number..."), *ADDR,
        F("totalAmbulances", "Total Ambulances", "total_ambulances", "number")],
     "fixed": {"status": "pending"}},
    {"id": "ambulance_driver", "label": "Ambulance Driver", "category": "Emergency and Medical Support", "table": "ambulance_driver_profiles",
     "role": None, "user_type": "ambulance_driver", "loc": None, "name_key": "fullName", "fields": [
        F("fullName", "Full Name", "full_name", req=True, ph="e.g. Ravi Kumar"),
        F("licenseNumber", "Driving Licence Number", "license_number", req=True, ph="DL-MH-1420-XXXXXXX"),
        F("licenseCategory", "Licence Category", "license_category", "select", True, opts=[[x, x] for x in ("LMV-TR", "HMV", "HGMV", "HPMV")]),
        F("experienceYears", "Years of Driving Experience", "experience_years", "number"),
        F("ambulanceProviderId", "Parent Ambulance Service", "ambulance_provider_id", "ambulance_provider", True), *ADDR_OPT],
     "fixed": {"is_verified": False, "kyc_status": "pending"}},
    {"id": "paramedic", "label": "Paramedic", "category": "Emergency and Medical Support", "table": "paramedic_profiles", "role": "paramedic",
     "loc": None, "name_key": "fullName", "fields": [
        F("fullName", "Full Name", "full_name", req=True), EMAIL,
        F("hospitalId", "Associated Hospital", "hospital_id", "hospital", True),
        F("specialization", "Specialization", "specialization"),
        F("qualification", "Qualification", "qualification", req=True, ph="e.g., BPT, GNM, DA"),
        F("experience", "Experience (Years)", "experience_years", "number")],
     "fixed": {"verification_status": "pending", "is_verified": False}},
    {"id": "blood_bank", "label": "Blood Banks", "category": "Emergency and Medical Support", "table": "blood_banks", "role": "blood_bank",
     "loc": "json", "name_key": "ownerName", "fields": [
        F("businessName", "Blood Bank Name", "bank_name", req=True, ph="e.g. City Blood Bank"),
        F("ownerName", "Incharge Name", "incharge_name", req=True, ph="Medical officer / incharge full name"),
        F("licenseNumber", "Blood Bank Licence Number", "license_number", req=True, ph="Drugs Control / FDA licence number"),
        EMAIL, *ADDR_OPT, F("operates24x7", "Operates 24x7", "operates_24x7", "bool")],
     "fixed": {"verification_status": "pending", "is_verified": False, "accepts_walk_in_donors": True}},
    {"id": "wellness_event", "label": "Health Camps & Retreats", "category": "Wellness and Lifestyle", "table": "wellness_event_providers",
     "role": None, "user_type": "wellness_event", "loc": "latlng", "name_key": "organiserName", "fields": [
        F("organiserName", "Organiser Name", "organiser_name", req=True), F("displayName", "Display Name", "display_name", req=True),
        F("organiserType", "Organiser type", "organiser_type", "select", opts=[["individual", "Individual"], ["organisation", "Organisation"], ["hospital", "Hospital"]]),
        F("registrationNumber", "Registration Number", "registration_number"), EMAIL, *ADDR_OPT],
     "fixed": {"kyc_status": "pending"}},
    {"id": "veterinarian", "label": "Veterinarian", "category": "Wellness and Lifestyle", "table": "vet_clinics", "role": "vet",
     "loc": "json", "name_key": "ownerName", "fields": [
        F("businessName", "Clinic Name", "clinic_name", req=True, ph="e.g. Happy Tails Veterinary"),
        F("ownerName", "Owner Name", "owner_name", req=True, ph="Owner / proprietor full name"),
        F("licenseNumber", "VCI Registration", "vci_registration"), EMAIL, *ADDR_OPT],
     "fixed": {"verification_status": "pending", "is_verified": False, "species_treated": ["dog", "cat"]}},
    {"id": "dental", "label": "Dental Clinic", "category": "Wellness and Lifestyle", "table": "dental_clinics", "role": "dental",
     "loc": "json", "name_key": "ownerName", "fields": [
        F("businessName", "Clinic Name", "clinic_name", req=True, ph="e.g. Bright Smile Dental Clinic"),
        F("ownerName", "Owner Name", "owner_name", req=True, ph="Owner / proprietor full name"),
        F("licenseNumber", "Clinic Registration Number", "license_number", req=True, ph="Shop & Estab / Clinical Estab. licence"),
        EMAIL, *ADDR_OPT],
     "fixed": {"verification_status": "pending", "is_verified": False, "chair_count": 1}},
    hosp("skin_hair", "Skin and Hair Clinic", "Wellness and Lifestyle", {"hospital_type": "specialised_centre", "specializations": ["skin_hair"]}),
]
BY_ID = {s["id"]: s for s in SPECS}
CONTACT_TYPE = {"hospital_profiles": "hospital", "doctors": "doctor", "ambulance_providers": "ambulance", "pharmacy_providers": "pharmacy",
                "path_lab_profiles": "path_lab", "diagnostic_centre_profiles": "diagnostic_centre"}


class OnboardBody(BaseModel):
    type: str
    phone: str = Field(..., max_length=20)
    values: Dict[str, Any] = Field(default_factory=dict)
    lat: Optional[float] = None
    lng: Optional[float] = None


def _cast(f, v):
    if f["type"] == "number":
        try:
            return float(v) if "." in str(v) else int(v)
        except (TypeError, ValueError):
            return None
    if f["type"] == "bool":
        return bool(v)
    return (str(v).strip() or None) if v is not None else None


def create_provider_onboarding_router(db, get_current_user) -> APIRouter:
    r = APIRouter(prefix="/api/admin/onboarding")

    def _admin(current):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")

    @r.get("/provider-types")
    async def provider_types(current=Depends(get_current_user)):
        _admin(current)
        return {"types": [{k: s.get(k) for k in ("id", "label", "category", "loc")} | {"fields": [{k: v for k, v in f.items() if k != "col"} for f in s["fields"]]}
                          for s in SPECS]}

    @r.get("/lookup/{kind}")
    async def lookup(kind: str, current=Depends(get_current_user)):
        _admin(current)
        sql = {"hospital": "SELECT id, name, city FROM public.hospital_profiles WHERE verification_status IS DISTINCT FROM 'deactivated' ORDER BY name",
               "ambulance_provider": "SELECT id, business_name AS name, city FROM public.ambulance_providers WHERE verification_status IS DISTINCT FROM 'deactivated' ORDER BY business_name"}.get(kind)
        if not sql:
            raise HTTPException(status_code=400, detail="Unknown lookup")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            return {"items": [dict(x) for x in await conn.fetch(sql)]}

    @r.post("/signup")
    async def signup(body: OnboardBody, current=Depends(get_current_user)):
        _admin(current)
        spec = BY_ID.get(body.type)
        if not spec:
            raise HTTPException(status_code=400, detail="Unknown provider type")
        ten = re.sub(r"\D", "", body.phone)[-10:]
        if len(ten) != 10:
            raise HTTPException(status_code=400, detail="Enter a valid 10-digit phone")
        vals = {}
        for f in spec["fields"]:
            if f["show_if"] and body.values.get(f["show_if"][0]) != f["show_if"][1]:
                continue
            v = _cast(f, body.values.get(f["k"]))
            if f["req"] and v in (None, "") and f["type"] != "bool":
                raise HTTPException(status_code=400, detail=f"{f['label']} is required")
            vals[f["k"]] = v
        if vals.get("pincode") and not re.fullmatch(r"\d{6}", vals["pincode"]):
            raise HTTPException(status_code=400, detail="Enter a valid 6-digit pincode")
        has_loc = sb.valid_coords(body.lat, body.lng)
        if spec["loc"] and spec["table"] in CONTACT_TYPE and not has_loc:
            raise HTTPException(status_code=400, detail="Latitude & longitude are required for patient-app discovery")
        by = current.get("name") or current.get("phone")
        name = vals.get(spec["name_key"]) or ""
        try:
            uid, pid, existing = await _insert(spec, ten, name, vals, body, has_loc, by)
        except asyncpg.exceptions.UniqueViolationError as e:
            raise HTTPException(status_code=409, detail=f"Already registered — {(e.constraint_name or '').replace('ix_', '').replace('_', ' ')} must be unique")
        except asyncpg.exceptions.CheckViolationError as e:
            raise HTTPException(status_code=400, detail=f"The Provider App rejected this data ({e.constraint_name})")
        await _mirror_crm(uid, ten, name, spec, vals, by, current)
        return {"success": True, "user_id": uid, "profile_id": pid, "existing_login": existing, "next": f"/admin/onboarding/{uid}"}

    async def _insert(spec, ten, name, vals, body, has_loc, by):
        tbl = spec["table"]
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            cols = await conn.fetch("SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=$1", tbl)
            types = {c["column_name"]: c["data_type"] for c in cols}
            async with conn.transaction():
                u = await conn.fetchrow("""SELECT id FROM public.users WHERE phone IN ($1, $2) OR phone_key = $1 LIMIT 1""", ten, f"+91{ten}")
                uid = u["id"] if u else str(uuid.uuid4())
                if not u:
                    await conn.execute("""INSERT INTO public.users (id, phone, name, role, user_type, is_active, verification_status, email, created_at)
                                          VALUES ($1, $2, $3, $4, $5, TRUE, 'pending', $6, now())""",
                                       uid, ten, name, spec["role"], spec.get("user_type") or spec["role"], vals.get("email"))
                if await conn.fetchval(f"SELECT 1 FROM public.{tbl} WHERE user_id = $1 AND {'verification_status' if 'verification_status' in types else 'kyc_status'} IS DISTINCT FROM 'deactivated'", uid):
                    raise HTTPException(status_code=409, detail=f"This number already has a {spec['label']} profile")
                pid = str(uuid.uuid4())
                row = {"id": pid, "user_id": uid, "phone": ten, "onboarded_by": f"admin:{by}", **spec["fixed"]}
                for f in spec["fields"]:
                    if f["col"] and f["k"] in vals and vals[f["k"]] is not None:
                        row[f["col"]] = vals[f["k"]]
                if tbl == "paramedic_profiles":
                    row["name"] = row.get("full_name")
                if tbl == "hospital_profiles":
                    row["total_beds"] = row.get("capacity")
                if row.get("hospital_id"):
                    row["hospital_name"] = await conn.fetchval("SELECT name FROM public.hospital_profiles WHERE id = $1", row["hospital_id"])
                if has_loc:
                    lat, lng = float(body.lat), float(body.lng)
                    row.update({"json": {"location": {"lat": lat, "lng": lng}}, "latlng": {"latitude": lat, "longitude": lng},
                                "business": {"business_lat": lat, "business_lng": lng}}.get(spec["loc"], {}))
                row = {k: v for k, v in row.items() if k in types}
                vals_sql = [f"${i + 1}::json" if types[k] == "json" else f"${i + 1}" for i, k in enumerate(row)]
                args = [json.dumps(v) if types[k] == "json" else v for k, v in row.items()]
                stamps = [c for c in ("created_at", "updated_at") if c in types]
                await conn.execute(f"INSERT INTO public.{tbl} ({', '.join([*row, *stamps])}) VALUES ({', '.join([*vals_sql, *['now()'] * len(stamps)])})", *args)
                if tbl in ("path_lab_profiles", "diagnostic_centre_profiles"):
                    _, btbl, fk = sb.LAB_KINDS[spec["role"]]
                    await conn.execute(f"""INSERT INTO public.{btbl} (id, {fk}, name, phone, address, city, state, latitude, longitude,
                        is_active, is_verified, created_at, updated_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,FALSE,FALSE,now(),now())""",
                        str(uuid.uuid4()), pid, row.get("name"), ten, row.get("address"), row.get("city"), row.get("state"),
                        row.get("latitude"), row.get("longitude"))
        return uid, pid, bool(u)

    async def _mirror_crm(uid, ten, name, spec, vals, by, current):
        """PC-console login + CRM contact, as the legacy onboarding did."""
        now = datetime.now(timezone.utc).isoformat()
        if not await db.crm_users.find_one({"phone": ten}, {"_id": 1}):
            await db.crm_users.insert_one({"id": str(uuid.uuid4()), "phone": ten, "name": name, "role": "provider_owner",
                                           "provider_type": spec["id"], "is_master_admin": False, "password_hash": None,
                                           "supabase_user_id": uid, "supabase_role": spec["role"], "created_at": now, "updated_at": now,
                                           "onboarded_by_admin": by})
        if not await db.contacts.find_one({"phone": ten}, {"_id": 1}):
            await db.contacts.insert_one({"id": str(uuid.uuid4()), "name": name, "type": CONTACT_TYPE.get(spec["table"], spec["id"]),
                                          "phone": ten, "email": vals.get("email"), "city": vals.get("city"), "state": vals.get("state"),
                                          "address": vals.get("address") or vals.get("labAddress"), "is_verified": False, "is_active": True,
                                          "pipeline_stage": "won", "kyc_status": "pending", "deal_value": 0, "source": "admin_direct_onboard",
                                          "onboarded_by": by, "onboarded_at": now, "created_at": now, "updated_at": now, "supabase_user_id": uid})

    return r
