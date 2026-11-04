"""Trata Health Admin directories straight from the shared users table — one row per Provider-app / Patient-app account."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

import supabase_db as sb

NON_PROVIDER = ("admin", "patient", "customer")
ORG_ROLES = ("hospital", "pathologist", "ambulance_provider", "pharmacy")


def create_directory_router(get_current_user):
    r = APIRouter(prefix="/api/admin/directory")

    @r.get("/providers")
    async def providers(role: Optional[str] = None, q: Optional[str] = None, kyc: Optional[str] = None, limit: int = 500,
                        current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        where = ["u.role IS NOT NULL", "u.role <> ALL($1::text[])", "coalesce(u.is_archived, FALSE) = FALSE", "NOT u.deactivated"]
        args: list = [list(NON_PROVIDER)]
        if role:
            args.append(role)
            where.append(f"u.role = ${len(args)}")
        if q and q.strip():
            args.append(f"%{q.strip().lower()}%")
            where.append(f"(lower(coalesce(u.name, '')) LIKE ${len(args)} OR lower(coalesce(u.org_name, '')) LIKE ${len(args)} OR lower(coalesce(u.admin_name, '')) LIKE ${len(args)} OR u.phone LIKE ${len(args)} OR lower(coalesce(u.email, '')) LIKE ${len(args)})")
        if kyc:
            groups = {"pending": "(coalesce(lower(u.verification_status), 'pending') LIKE 'pending%' OR lower(u.verification_status) IN ('submitted', 'under_review'))",
                      "verified": "lower(u.verification_status) IN ('verified', 'approved')",
                      "rejected": "lower(u.verification_status) IN ('rejected', 'declined')"}
            if kyc.lower() not in groups:
                raise HTTPException(status_code=400, detail="kyc must be pending, verified or rejected")
            where.append(groups[kyc.lower()])
        args.append(max(1, min(limit, 1000)))
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""
                WITH base AS (
                  SELECT u.*, coalesce(oe.name, nullif(u.organization_name, ''), hp.name, pp.business_name, ph.pharmacy_name,
                                       pl.name, dc.name, ap.business_name, dr.org, pm.hospital_name, hs.org) AS org_name,
                         coalesce(dz.all_off, FALSE) AS deactivated,
                         coalesce(nullif(oe.contact_person, ''), nullif(pp.owner_name, ''), nullif(ph.owner_name, ''),
                                  nullif(ap.owner_name, ''), CASE WHEN u.role = 'doctor' THEN nullif(dr.full_name, '') END, u.name) AS admin_name
                    FROM public.users u
                    LEFT JOIN LATERAL (SELECT name, contact_person FROM public.org_entities e WHERE e.entity_user_id = u.id
                                         AND NOT EXISTS (SELECT 1 FROM public.hospital_profiles x WHERE x.user_id = u.id AND x.verification_status = 'deactivated'
                                                         AND lower(x.name) = lower(e.name))
                                       ORDER BY created_at LIMIT 1) oe ON TRUE
                    LEFT JOIN LATERAL (SELECT name FROM public.hospital_profiles WHERE (user_id = u.id OR admin_user_id = u.id) AND verification_status IS DISTINCT FROM 'deactivated' LIMIT 1) hp ON TRUE
                    LEFT JOIN LATERAL (SELECT business_name, owner_name FROM public.pharmacy_providers WHERE user_id = u.id AND verification_status IS DISTINCT FROM 'deactivated' LIMIT 1) pp ON TRUE
                    LEFT JOIN LATERAL (SELECT pharmacy_name, owner_name FROM public.pharmacy_profiles WHERE user_id = u.id LIMIT 1) ph ON TRUE
                    LEFT JOIN LATERAL (SELECT coalesce(display_name, name) AS name FROM public.path_lab_profiles WHERE user_id = u.id AND verification_status IS DISTINCT FROM 'deactivated' LIMIT 1) pl ON TRUE
                    LEFT JOIN LATERAL (SELECT name FROM public.diagnostic_centre_profiles WHERE user_id = u.id AND verification_status IS DISTINCT FROM 'deactivated' LIMIT 1) dc ON TRUE
                    LEFT JOIN LATERAL (SELECT business_name, owner_name FROM public.ambulance_providers WHERE user_id = u.id AND verification_status IS DISTINCT FROM 'deactivated' LIMIT 1) ap ON TRUE
                    LEFT JOIN LATERAL (SELECT d.full_name, coalesce(d.hospital_name, h.name, d.clinic_name, d.facility_name) AS org
                                         FROM public.doctors d LEFT JOIN public.hospital_profiles h ON h.id = d.hospital_id WHERE d.user_id = u.id LIMIT 1) dr ON TRUE
                    LEFT JOIN LATERAL (SELECT coalesce(p.hospital_name, h.name) AS hospital_name FROM public.paramedic_profiles p
                                         LEFT JOIN public.hospital_profiles h ON h.id = p.hospital_id WHERE p.user_id = u.id LIMIT 1) pm ON TRUE
                    LEFT JOIN LATERAL (SELECT bool_and(z.v = 'deactivated') AS all_off FROM (
                        SELECT verification_status v FROM public.hospital_profiles WHERE user_id = u.id
                        UNION ALL SELECT verification_status FROM public.path_lab_profiles WHERE user_id = u.id
                        UNION ALL SELECT verification_status FROM public.doctors WHERE user_id = u.id
                        UNION ALL SELECT verification_status FROM public.pharmacy_providers WHERE user_id = u.id
                        UNION ALL SELECT verification_status FROM public.ambulance_providers WHERE user_id = u.id
                        UNION ALL SELECT verification_status FROM public.diagnostic_centre_profiles WHERE user_id = u.id) z) dz ON TRUE
                    LEFT JOIN LATERAL (SELECT h.name AS org FROM public.hospital_staff s JOIN public.hospital_profiles h ON h.id = s.hospital_id
                                        WHERE s.user_id = u.id LIMIT 1) hs ON TRUE)
                SELECT u.id, u.name, u.org_name, u.admin_name, u.phone, u.email, u.role, coalesce(u.verification_status, 'pending') AS kyc_status,
                       u.is_active, coalesce(u.is_suspended, FALSE) AS is_suspended, u.suspended_reason, u.created_at, u.last_login_at,
                       count(k.id) AS docs_total,
                       count(k.id) FILTER (WHERE lower(coalesce(k.status, '')) = 'approved') AS docs_approved,
                       count(k.id) FILTER (WHERE lower(coalesce(k.status, '')) = 'rejected') AS docs_rejected
                  FROM base u LEFT JOIN public.kyc_documents k ON k.user_id = u.id
                 WHERE {' AND '.join(where)}
                 GROUP BY u.id, u.name, u.org_name, u.admin_name, u.phone, u.email, u.role, u.verification_status, u.is_active, u.is_suspended, u.suspended_reason, u.created_at, u.last_login_at
                 ORDER BY u.created_at DESC NULLS LAST LIMIT ${len(args)}""", *args)
            roles = await conn.fetch("""SELECT role, count(*) n FROM public.users WHERE role IS NOT NULL AND role <> ALL($1::text[])
                                         AND coalesce(is_archived, FALSE) = FALSE GROUP BY 1 ORDER BY 2 DESC""", list(NON_PROVIDER))
        items = [{**dict(x), "id": str(x["id"]), "created_at": x["created_at"].isoformat() if x["created_at"] else None,
                  "last_login_at": x["last_login_at"].isoformat() if x["last_login_at"] else None,
                  "_pnd": str(x["phone"] or "").startswith("pnd-"),
                  "phone": x["phone"] if re.fullmatch(r"\+?\d{10,13}", x["phone"] or "") else None} for x in rows]
        for i in items:
            if not i["org_name"] and i["role"] in ORG_ROLES:
                i["org_name"] = i["name"]
            if i["org_name"] and (i["admin_name"] or "").strip().lower() == i["org_name"].strip().lower():
                i["admin_name"] = None
        # The Provider app sometimes leaves placeholder accounts (no real phone) for the same organisation — show one row per name.
        best: Dict[tuple, Dict[str, Any]] = {}
        for i in items:
            k = (i["role"], (i["name"] or i["id"]).strip().lower())
            rank = (bool(i["phone"]), i["docs_total"], i["kyc_status"] != "pending", not i["_pnd"], i["created_at"] or "")
            cur = best.get(k)
            if not cur:
                best[k] = {**i, "linked_accounts": [], "_rank": rank}
            elif rank > cur["_rank"]:
                best[k] = {**i, "linked_accounts": cur["linked_accounts"] + [cur["id"]], "_rank": rank}
            else:
                cur["linked_accounts"].append(i["id"])
        items = [{k: v for k, v in i.items() if k not in ("_rank", "_pnd")} for i in best.values()]
        items.sort(key=lambda i: i["created_at"] or "", reverse=True)
        role_counts = [{"role": x["role"], "count": x["n"]} for x in roles]
        if role and not (q or kyc):
            role_counts = [{**x, "count": len(items)} if x["role"] == role else x for x in role_counts]
        if not (role or q or kyc):
            from collections import Counter
            role_counts = [{"role": k, "count": v} for k, v in Counter(i["role"] for i in items).most_common()]
        return {"items": items, "roles": role_counts}

    return r
