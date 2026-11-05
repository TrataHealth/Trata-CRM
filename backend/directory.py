"""Trata Health Admin directories — one row per canonical provider profile, the same list the Provider App admin shows."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import canonical_providers as cp
import supabase_db as sb

NON_PROVIDER = ("admin", "patient", "customer")


SERVICE_TYPES = ("pathology", "imaging")


class ServiceTypes(BaseModel):
    service_types: List[str]


def create_directory_router(get_current_user):
    r = APIRouter(prefix="/api/admin/directory")

    @r.get("/providers/{user_id}/service-types")
    async def get_service_types(user_id: str, current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            v = await conn.fetchrow("SELECT service_types FROM public.diagnostic_centre_profiles WHERE user_id = $1", user_id)
        return {"applicable": bool(v), "service_types": list(v["service_types"] or []) if v else []}

    @r.put("/providers/{user_id}/service-types")
    async def put_service_types(user_id: str, body: ServiceTypes, current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        types = sorted({t for t in body.service_types if t in SERVICE_TYPES})
        if not types:
            raise HTTPException(status_code=400, detail="A diagnostic centre must offer at least one service")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            res = await conn.execute("""UPDATE public.diagnostic_centre_profiles SET service_types = $2::text[], updated_at = now()
                                         WHERE user_id = $1""", user_id, types)
        if res.endswith(" 0"):
            raise HTTPException(status_code=404, detail="No diagnostic centre for this account")
        return {"success": True, "service_types": types}

    async def profile_rows(conn, deleted: bool) -> List[Dict[str, Any]]:
        """One row per canonical profile — exactly what the Provider App admin lists (or its Deleted page)."""
        parts = []
        for role, (tbl, name_col) in cp.TABLES.items():
            cols = await cp._columns(conn, tbl)
            ph = "coalesce(u.phone, p.phone::text)" if "phone" in cols else "u.phone"
            if role == "doctor":
                org = "coalesce(nullif(p.hospital_name, ''), h.name, nullif(p.clinic_name, ''), nullif(p.facility_name, ''))"
                admin, join = "p.full_name", "LEFT JOIN public.hospital_profiles h ON h.id = p.hospital_id"
            else:
                name = "coalesce(nullif(p.display_name, ''), p.name)" if "display_name" in cols else f"p.{name_col}"
                org, join = name, ""
                admin = "coalesce(nullif(p.owner_name, ''), u.name)" if "owner_name" in cols else "u.name"
            parts.append(f"""SELECT '{role}'::text AS role, '{tbl}'::text AS profile_table, p.id::text AS profile_id, p.user_id::text AS user_id,
                                    {org}::text AS org_name, {admin}::text AS admin_name, {ph}::text AS phone, u.email::text AS email,
                                    p.verification_status::text AS kyc_status, p.created_at::timestamptz AS created_at, p.updated_at::timestamptz AS updated_at,
                                    p.local_decision->>'deleted_reason' AS deleted_reason, p.local_decision->>'deleted_by' AS deleted_by
                               FROM public.{tbl} p LEFT JOIN public.users u ON u.id = p.user_id {join}
                              WHERE p.verification_status {'=' if deleted else 'IS DISTINCT FROM'} 'deactivated'""")
        staff = f"""SELECT u.role::text, 'users'::text, NULL::text, u.id::text, coalesce(nullif(u.organization_name, ''), hs.org, pm.org)::text, u.name::text, u.phone::text, u.email::text,
                           coalesce(u.verification_status, 'pending')::text, u.created_at::timestamptz, u.archived_at::timestamptz, u.archived_reason::text, NULL::text
                      FROM public.users u
                      LEFT JOIN LATERAL (SELECT h.name AS org FROM public.hospital_staff s JOIN public.hospital_profiles h ON h.id = s.hospital_id
                                          WHERE s.user_id = u.id LIMIT 1) hs ON TRUE
                      LEFT JOIN LATERAL (SELECT coalesce(p.hospital_name, h.name) AS org FROM public.paramedic_profiles p
                                          LEFT JOIN public.hospital_profiles h ON h.id = p.hospital_id WHERE p.user_id = u.id LIMIT 1) pm ON TRUE
                     WHERE u.role IS NOT NULL AND u.role <> ALL($1::text[]) AND {'' if deleted else 'NOT '}coalesce(u.is_archived, FALSE)"""
        rows = await conn.fetch(f"""
            WITH x AS ({' UNION ALL '.join(parts)} UNION ALL {staff})
            SELECT x.*, u.is_active, coalesce(u.is_suspended, FALSE) AS is_suspended, u.suspended_reason, u.last_login_at,
                   u.archived_at, u.purge_after,
                   (SELECT count(*) FROM public.kyc_documents k WHERE k.user_id = x.user_id) AS docs_total,
                   (SELECT count(*) FROM public.kyc_documents k WHERE k.user_id = x.user_id AND lower(coalesce(k.status, '')) = 'approved') AS docs_approved,
                   (SELECT count(*) FROM public.kyc_documents k WHERE k.user_id = x.user_id AND lower(coalesce(k.status, '')) = 'rejected') AS docs_rejected
              FROM x LEFT JOIN public.users u ON u.id = x.user_id
             ORDER BY coalesce(x.updated_at, x.created_at) DESC NULLS LAST""", list(NON_PROVIDER) + list(cp.TABLES))
        out = []
        for x in rows:
            i = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(x).items()}
            i["row_key"] = f"{i['profile_table']}:{i['profile_id'] or i['user_id']}"
            i["id"] = i["user_id"]
            i["kyc_status"] = i["kyc_status"] or "pending"
            i["phone"] = i["phone"] if re.fullmatch(r"\+?\d{10,13}", i["phone"] or "") else None
            if i["org_name"] and (i["admin_name"] or "").strip().lower() == i["org_name"].strip().lower():
                i["admin_name"] = None
            out.append(i)
        return out

    def matches(i, q, kyc):
        if q and q.strip():
            s = q.strip().lower()
            if not any(s in str(i.get(f) or "").lower() for f in ("org_name", "admin_name", "phone", "email")):
                return False
        if kyc:
            v = str(i["kyc_status"]).lower()
            ok = {"pending": v.startswith("pending") or v in ("submitted", "under_review"),
                  "verified": v in ("verified", "approved"), "rejected": v in ("rejected", "declined")}
            if kyc.lower() not in ok:
                raise HTTPException(status_code=400, detail="kyc must be pending, verified or rejected")
            return ok[kyc.lower()]
        return True

    def role_counts(items):
        from collections import Counter
        c = Counter(i["role"] for i in items)
        order = [r for r in cp.TABLES if c.get(r)] + sorted((r for r in c if r not in cp.TABLES), key=lambda r: -c[r])
        return [{"role": r, "count": c[r]} for r in order]

    @r.get("/providers")
    async def providers(role: Optional[str] = None, q: Optional[str] = None, kyc: Optional[str] = None,
                        current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            items = [i for i in await profile_rows(conn, False) if matches(i, q, kyc)]
        return {"items": [i for i in items if not role or i["role"] == role], "roles": role_counts(items)}

    @r.get("/deleted")
    async def deleted(app: str = "provider", q: Optional[str] = None, current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        if app not in ("provider", "patient"):
            raise HTTPException(status_code=400, detail="app must be provider or patient")
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            if app == "provider":
                items = [i for i in await profile_rows(conn, True) if matches(i, q, None)]
            else:
                rows = await conn.fetch(f"""SELECT u.id, u.name, u.phone, u.email, u.role, u.created_at, u.archived_at, u.archived_reason, u.purge_after,
                                                   d.status AS deletion_status, d.requested_at, d.scheduled_at
                                              FROM public.users u
                                              LEFT JOIN LATERAL (SELECT status, requested_at, scheduled_at FROM public.account_deletions a
                                                                  WHERE a.user_id = u.id ORDER BY requested_at DESC LIMIT 1) d ON TRUE
                                             WHERE {sb._PATIENT_ROLE_SQL.format(a="u.")}
                                               AND (coalesce(u.is_archived, FALSE) OR d.status IN ('pending', 'completed'))
                                             ORDER BY coalesce(u.archived_at, d.requested_at) DESC NULLS LAST""")
                items = [{**{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(x).items()}, "row_key": x["id"]}
                         for x in rows]
                items = [i for i in items if not q or q.strip().lower() in f"{i['name'] or ''} {i['phone'] or ''} {i['email'] or ''}".lower()]
        now = datetime.now(timezone.utc)
        for i in items:
            pa = i.get("purge_after")
            i["days_left"] = max(0, math.ceil((datetime.fromisoformat(pa) - now).total_seconds() / 86400)) if pa else None
        return {"items": items, "total": len(items), "roles": role_counts(items) if app == "provider" else []}

    return r
