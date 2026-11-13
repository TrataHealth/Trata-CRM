"""Master-admin edits of a provider profile's name, admin name and phone (sign-in number too, Patient App untouched)."""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import canonical_providers as cp
import supabase_db as sb

PERSON_TABLES = {"doctors", "paramedic_profiles", "nutritionists", "wellness_professionals", "ambulance_driver_profiles"}
# Provider-App tables whose org / admin names live in their own columns: table -> (org column, admin column)
ORG_COLS = {"dental_clinics": ("clinic_name", "owner_name"), "vet_clinics": ("clinic_name", "owner_name"),
            "blood_banks": ("bank_name", "incharge_name"), "wellness_event_providers": ("display_name", "organiser_name")}


class ProfileEdit(BaseModel):
    provider_name: Optional[str] = Field(None, max_length=200)
    admin_name: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=20)


def _ten(p: Optional[str]) -> str:
    d = re.sub(r"\D", "", p or "")
    return d[-10:] if len(d) >= 10 else d


def create_provider_edit_router(db, get_current_user, master_phones) -> APIRouter:
    r = APIRouter(prefix="/api/admin/directory")

    @r.put("/profiles/{table}/{profile_id}")
    async def edit_profile(table: str, profile_id: str, body: ProfileEdit, current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        if table not in {t for t, _ in cp.TABLES.values()} | PERSON_TABLES | set(ORG_COLS):
            raise HTTPException(status_code=400, detail="Unknown provider profile")
        pname, aname = (body.provider_name or "").strip(), (body.admin_name or "").strip()
        phone = re.sub(r"[\s-]", "", body.phone or "")
        if phone and not re.fullmatch(r"\+?\d{10,13}", phone):
            raise HTTPException(status_code=400, detail="Enter a valid phone number (10 digits)")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            cols = await cp._columns(conn, table)
            row = await conn.fetchrow(f"SELECT * FROM public.{table} WHERE id::text = $1", profile_id)
            if not row:
                raise HTTPException(status_code=404, detail="Profile not found")
            uid = row["user_id"]
            sets: Dict[str, Any] = {}
            user_sets: Dict[str, Any] = {}
            notes = []
            if table in PERSON_TABLES:
                if aname or pname:
                    sets["full_name"] = aname or pname
                    if "name" in cols:
                        sets["name"] = aname or pname
            elif table in ORG_COLS:
                if pname:
                    sets[ORG_COLS[table][0]] = pname
                if aname:
                    sets[ORG_COLS[table][1]] = aname
            else:
                if pname:
                    sets["business_name" if "business_name" in cols else "name"] = pname
                    if "display_name" in cols and row.get("display_name"):
                        sets["display_name"] = pname
                if aname:
                    if "owner_name" in cols:
                        sets["owner_name"] = aname
                    elif uid:
                        user_sets["name"] = aname
                    else:
                        raise HTTPException(status_code=400, detail="This provider has no app login, so there's no admin name to set")
            if phone:
                ten = _ten(phone)
                if uid and ten in master_phones:
                    raise HTTPException(status_code=400, detail="That number belongs to the Trata Health Admin")
                if "phone" in cols:
                    sets["phone"] = ten if uid else phone
                if uid:
                    u = await conn.fetchrow("SELECT phone, phone_key, trata_phone FROM public.users WHERE id = $1", uid)
                    if _ten(u["phone"]) in master_phones:
                        raise HTTPException(status_code=400, detail="The Trata Health Admin's sign-in number can't be changed here")
                    clash = await conn.fetchval("""SELECT id FROM public.users WHERE id <> $1 AND
                        (right(regexp_replace(phone, '\\D', '', 'g'), 10) = $2 OR phone_key = $2)""", uid, ten)
                    if clash:
                        raise HTTPException(status_code=409, detail="Another Trata account already signs in with this number")
                    if await conn.fetchval("SELECT 1 FROM public.customer_profiles WHERE user_id = $1", uid):
                        # One login serves both apps — moving it would move the Patient App too, so only the listed phone changes.
                        notes.append("sign_in_unchanged_patient_app")
                    elif _ten(u["phone"]) != ten:
                        # Keep the stored format — the Provider App matches users.phone exactly (bare 10 digits for its accounts).
                        user_sets.update({"phone": f"+91{ten}" if (u["phone"] or "").startswith("+91") else ten, "phone_key": ten})
                        if u["trata_phone"]:
                            user_sets["trata_phone"] = f"+91{ten}"
            if aname and uid and "name" not in user_sets:
                user_sets["name"] = aname  # keep the login's display name in step; the Patient App uses its own profile name
            if not sets and not user_sets:
                raise HTTPException(status_code=400, detail="Nothing to change")
            async with conn.transaction():
                if sets:
                    sql = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(sets))
                    await conn.execute(f"UPDATE public.{table} SET {sql}, updated_at = now() WHERE id::text = $1", profile_id, *sets.values())
                if user_sets:
                    sql = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(user_sets))
                    await conn.execute(f"UPDATE public.users SET {sql}, updated_at = now() WHERE id = $1", uid, *user_sets.values())
        if uid and "phone" in user_sets:
            ten = user_sets["phone_key"]
            await db.crm_users.update_many({"supabase_user_id": uid}, {"$set": {"phone": ten}})
            await db.contacts.update_many({"$or": [{"supabase_user_id": uid}, {"upstream_user_id": uid}]}, {"$set": {"phone": ten}})
        await db.audit_log.insert_one({"id": os.urandom(8).hex(), "action": "provider.profile_edit", "by": current.get("id"),
                                       "by_name": current.get("name"), "table": table, "profile_id": profile_id, "user_id": uid,
                                       "changes": {**sets, **{f"users.{k}": v for k, v in user_sets.items()}},
                                       "at": datetime.now(timezone.utc).isoformat()})
        return {"success": True, "updated": list(sets) + [f"users.{k}" for k in user_sets], "notes": notes}

    return r
