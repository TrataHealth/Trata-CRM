"""Lab / Diagnostic Centre staff (shared `lab_staff` table) — Trata Health Admin view + edit."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import supabase_db as sb

BASE_ROLES = ["lab_technician", "pathologist", "phlebotomist", "front_desk", "admin"]
ROLES = {"path_lab": BASE_ROLES, "diagnostic_centre": BASE_ROLES + ["radiologist"]}
COLS = ("name", "phone", "email", "role", "specialization", "qualification", "shift_start", "shift_end", "is_active")


class StaffIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None
    specialization: Optional[str] = None
    qualification: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    is_active: bool = True


def create_lab_staff_router(get_current_user):
    r = APIRouter(prefix="/api/admin/labs")

    def _admin(current):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")

    async def _lab(conn, key: str):
        """{lab_id}: canonical row id or owner users.id. Diagnostic centre wins over a shadow path_lab row."""
        for entity, tbl in (("diagnostic_centre", "diagnostic_centre_profiles"), ("path_lab", "path_lab_profiles")):
            row = await conn.fetchrow(f"SELECT id, name FROM public.{tbl} WHERE user_id = $1 OR id = $1 LIMIT 1", key)
            if row:
                return {"id": row["id"], "name": row["name"], "entity_type": entity}
        raise HTTPException(status_code=404, detail="No path lab or diagnostic centre for this account")

    def _check_role(entity: str, role: str):
        if role not in ROLES[entity]:
            raise HTTPException(status_code=400, detail=f"Role must be one of: {', '.join(ROLES[entity])}")

    async def _list(conn, lab):
        rows = await conn.fetch("""SELECT id, name, phone, email, role, specialization, qualification, shift_start, shift_end,
                                          coalesce(is_on_duty, FALSE) AS is_on_duty, coalesce(is_active, TRUE) AS is_active, created_at
                                     FROM public.lab_staff WHERE lab_id = $1 ORDER BY is_active DESC, role, name""", lab["id"])
        items = sb._rows(rows)
        return {"lab": lab, "roles": ROLES[lab["entity_type"]], "items": items,
                "counts": {"total": len(items), "active": sum(1 for i in items if i["is_active"]),
                           "on_duty": sum(1 for i in items if i["is_on_duty"] and i["is_active"])}}

    @r.get("/{lab_id}/staff")
    async def list_staff(lab_id: str, current=Depends(get_current_user)):
        _admin(current)
        async with (await sb.get_pool()).acquire() as conn:
            return await _list(conn, await _lab(conn, lab_id))

    @r.post("/{lab_id}/staff")
    async def add_staff(lab_id: str, body: StaffIn, current=Depends(get_current_user)):
        _admin(current)
        async with (await sb.get_pool()).acquire() as conn:
            lab = await _lab(conn, lab_id)
            _check_role(lab["entity_type"], body.role)
            vals = body.model_dump()
            await conn.execute(f"""INSERT INTO public.lab_staff (id, lab_id, entity_type, {', '.join(COLS)}, is_on_duty, created_at, updated_at)
                                   VALUES ($1, $2, $3, {', '.join(f'${i + 4}' for i in range(len(COLS)))}, FALSE, now(), now())""",
                               str(uuid.uuid4()), lab["id"], lab["entity_type"], *[vals[k] for k in COLS])
            return await _list(conn, lab)

    @r.put("/{lab_id}/staff/{staff_id}")
    async def edit_staff(lab_id: str, staff_id: str, body: StaffIn, current=Depends(get_current_user)):
        _admin(current)
        async with (await sb.get_pool()).acquire() as conn:
            lab = await _lab(conn, lab_id)
            _check_role(lab["entity_type"], body.role)
            vals = body.model_dump()
            res = await conn.execute(f"""UPDATE public.lab_staff SET {', '.join(f'{k} = ${i + 3}' for i, k in enumerate(COLS))}, updated_at = now()
                                          WHERE id = $1 AND lab_id = $2""", staff_id, lab["id"], *[vals[k] for k in COLS])
            if res.endswith(" 0"):
                raise HTTPException(status_code=404, detail="Staff member not found")
            return await _list(conn, lab)

    @r.delete("/{lab_id}/staff/{staff_id}")
    async def remove_staff(lab_id: str, staff_id: str, current=Depends(get_current_user)):
        _admin(current)
        async with (await sb.get_pool()).acquire() as conn:
            lab = await _lab(conn, lab_id)
            res = await conn.execute("DELETE FROM public.lab_staff WHERE id = $1 AND lab_id = $2", staff_id, lab["id"])
            if res.endswith(" 0"):
                raise HTTPException(status_code=404, detail="Staff member not found")
            return await _list(conn, lab)

    @r.post("/{lab_id}/staff/toggle-duty/{staff_id}")
    async def toggle_duty(lab_id: str, staff_id: str, current=Depends(get_current_user)):
        _admin(current)
        async with (await sb.get_pool()).acquire() as conn:
            lab = await _lab(conn, lab_id)
            res = await conn.execute("""UPDATE public.lab_staff SET is_on_duty = NOT coalesce(is_on_duty, FALSE), updated_at = now()
                                         WHERE id = $1 AND lab_id = $2""", staff_id, lab["id"])
            if res.endswith(" 0"):
                raise HTTPException(status_code=404, detail="Staff member not found")
            return await _list(conn, lab)

    return r
