"""Trata Health Admin directories straight from the shared users table — one row per Provider-app / Patient-app account."""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException

import supabase_db as sb

NON_PROVIDER = ("admin", "patient", "customer")


def create_directory_router(get_current_user):
    r = APIRouter(prefix="/api/admin/directory")

    @r.get("/providers")
    async def providers(role: Optional[str] = None, q: Optional[str] = None, kyc: Optional[str] = None, limit: int = 500,
                        current=Depends(get_current_user)):
        if not current.get("is_master_admin"):
            raise HTTPException(status_code=403, detail="Trata Health Admin only")
        where = ["u.role IS NOT NULL", "u.role <> ALL($1::text[])", "coalesce(u.is_archived, FALSE) = FALSE"]
        args: list = [list(NON_PROVIDER)]
        if role:
            args.append(role)
            where.append(f"u.role = ${len(args)}")
        if q and q.strip():
            args.append(f"%{q.strip().lower()}%")
            where.append(f"(lower(coalesce(u.name, '')) LIKE ${len(args)} OR u.phone LIKE ${len(args)} OR lower(coalesce(u.email, '')) LIKE ${len(args)})")
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
                SELECT u.id, u.name, u.phone, u.email, u.role, coalesce(u.verification_status, 'pending') AS kyc_status,
                       u.is_active, u.created_at, u.last_login_at,
                       count(k.id) AS docs_total,
                       count(k.id) FILTER (WHERE lower(coalesce(k.status, '')) = 'approved') AS docs_approved,
                       count(k.id) FILTER (WHERE lower(coalesce(k.status, '')) = 'rejected') AS docs_rejected
                  FROM public.users u LEFT JOIN public.kyc_documents k ON k.user_id = u.id
                 WHERE {' AND '.join(where)}
                 GROUP BY u.id ORDER BY u.created_at DESC NULLS LAST LIMIT ${len(args)}""", *args)
            roles = await conn.fetch("""SELECT role, count(*) n FROM public.users WHERE role IS NOT NULL AND role <> ALL($1::text[])
                                         AND coalesce(is_archived, FALSE) = FALSE GROUP BY 1 ORDER BY 2 DESC""", list(NON_PROVIDER))
        items = [{**dict(x), "id": str(x["id"]), "created_at": x["created_at"].isoformat() if x["created_at"] else None,
                  "last_login_at": x["last_login_at"].isoformat() if x["last_login_at"] else None,
                  "_pnd": str(x["phone"] or "").startswith("pnd-"),
                  "phone": x["phone"] if re.fullmatch(r"\+?\d{10,13}", x["phone"] or "") else None} for x in rows]
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
        if not (role or q or kyc):
            from collections import Counter
            role_counts = [{"role": k, "count": v} for k, v in Counter(i["role"] for i in items).most_common()]
        return {"items": items, "roles": role_counts}

    return r
