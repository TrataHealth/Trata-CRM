"""Pharmacy console: medicine orders, prescriptions inbox, stock and sales for independent chains and hospital pharmacies.
Orders read/write the shared Supabase `medicine_orders` (same rows the Patient app shows); prescriptions and stock go
through the Provider app's own /api/pharmacy/* API so both apps stay in sync."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import supabase_db as sb

API = os.environ["PROVIDER_APP_API_URL"].rstrip("/")
IST = timezone(timedelta(hours=5, minutes=30))
OPEN = ("PENDING_PHARMACY", "PREORDER_PENDING")
ACTIONS = {  # action -> (allowed from, new status)
    "accept": (OPEN, "ACCEPTED"),
    "reject": (OPEN + ("ACCEPTED",), "REJECTED"),
    "fulfil": (("ACCEPTED",), "FULFILLED"),
    "mark_paid": (("ACCEPTED", "FULFILLED"), None),
}
RX_STATUSES = {"accepted", "ready_for_pickup", "fulfilled", "rejected"}
ORDER_COLS = """id, order_number, patient_id, patient_name, patient_phone, pharmacy_id, pharmacy_name, source_prescription_id, items,
    notes, delivery_mode, delivery_address, status, pharmacy_notes, rejection_reason, total_amount, is_paid, timeline, created_at,
    updated_at, payment_method, is_preorder, (rx_image_b64 IS NOT NULL AND rx_image_b64 <> '') AS has_rx_image"""


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


def _row(r) -> Dict[str, Any]:
    d = dict(r)
    for k in ("items", "timeline"):
        d[k] = _j(d.get(k)) or []
    for k in ("created_at", "updated_at", "fulfilled_at", "accepted_at", "submitted_at", "expiry_date"):
        if isinstance(d.get(k), datetime):
            d[k] = d[k].isoformat()
    return d


async def _provider_api(method: str, path: str, **kw):
    async with httpx.AsyncClient(timeout=30) as c:
        try:
            res = await c.request(method, f"{API}{path}", **kw)
        except httpx.HTTPError as ex:
            raise HTTPException(status_code=502, detail=f"Provider app unreachable: {type(ex).__name__}")
    if res.status_code >= 300:
        try:
            detail = res.json().get("detail")
        except ValueError:
            detail = res.text[:200]
        raise HTTPException(status_code=400 if res.status_code < 500 else 502, detail=f"Provider app: {detail}")
    return res.json()


class OrderAction(BaseModel):
    action: str
    total_amount: Optional[float] = Field(None, ge=0, le=1_000_000)
    note: Optional[str] = Field(None, max_length=500)
    reason: Optional[str] = Field(None, max_length=300)


class RxStatus(BaseModel):
    status: str
    total_amount: Optional[float] = Field(None, ge=0, le=1_000_000)
    rejection_reason: Optional[str] = Field(None, max_length=300)
    is_paid: Optional[bool] = None


class StockItem(BaseModel):
    medicine_name: Optional[str] = Field(None, max_length=160)
    sku: Optional[str] = Field(None, max_length=60)
    manufacturer: Optional[str] = Field(None, max_length=120)
    unit: Optional[str] = Field(None, max_length=40)
    qty_in_stock: Optional[int] = Field(None, ge=0, le=10_000_000)
    reorder_threshold: Optional[int] = Field(None, ge=0, le=1_000_000)
    unit_price: Optional[float] = Field(None, ge=0, le=1_000_000)
    batch_no: Optional[str] = Field(None, max_length=60)
    expiry_date: Optional[str] = Field(None, max_length=40)


def create_pharmacy_router(db, get_current_user, is_provider, is_internal) -> APIRouter:
    r = APIRouter(prefix="/api/pharmacy-console")

    async def stores_for(current) -> List[Dict[str, Any]]:
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            if is_provider(current):
                uid = current.get("supabase_user_id") or current["id"]
                rows = await conn.fetch("""
                    WITH orgs AS (SELECT id FROM public.organisations WHERE master_admin_user_id = $1),
                         ents AS (SELECT entity_profile_id, entity_user_id FROM public.org_entities
                                   WHERE org_id IN (SELECT id FROM orgs) AND entity_kind = 'pharmacy' AND is_active IS NOT FALSE),
                         hp AS (SELECT id FROM public.hospital_profiles WHERE user_id = $1)
                    SELECT p.id, p.business_name AS name, p.city, p.user_id, p.associated_hospital_name,
                           CASE WHEN p.user_id = $1 THEN 'own'
                                WHEN p.associated_hospital_id = $1 OR p.associated_hospital_id IN (SELECT id FROM hp) THEN 'hospital'
                                ELSE 'branch' END AS kind
                      FROM public.pharmacy_providers p
                     WHERE p.user_id = $1 OR p.id IN (SELECT entity_profile_id FROM ents) OR p.user_id IN (SELECT entity_user_id FROM ents)
                        OR p.associated_hospital_id = $1 OR p.associated_hospital_id IN (SELECT id FROM hp)
                     ORDER BY (p.user_id = $1) DESC, p.business_name""", uid)
            elif is_internal(current) and (current.get("is_master_admin") or current.get("role") != "sales_rep"):
                rows = await conn.fetch("""SELECT id, business_name AS name, city, user_id, associated_hospital_name, 'network' AS kind
                                             FROM public.pharmacy_providers WHERE coalesce(is_demo, false) = false
                                            ORDER BY business_name LIMIT 500""")
            else:
                raise HTTPException(status_code=403, detail="Pharmacy console is for pharmacies, hospitals and Trata admins")
        out = [dict(x) for x in rows]
        if current.get("provider_type") == "hospital":
            for x in out:
                x["kind"] = "hospital" if x["kind"] == "branch" else x["kind"]
        return out

    async def pick(current, store: Optional[str]) -> List[Dict[str, Any]]:
        stores = await stores_for(current)
        if not stores:
            raise HTTPException(status_code=404, detail="No pharmacy is linked to this account yet")
        if store and store != "all":
            stores = [s for s in stores if s["id"] == store]
            if not stores:
                raise HTTPException(status_code=403, detail="This store is not part of your account")
        return stores

    @r.get("/stores")
    async def stores(current=Depends(get_current_user)):
        s = await stores_for(current)
        return {"stores": s, "can_pick_all": len(s) > 1}

    # ---------- Medicine orders (Patient app) ----------
    @r.get("/orders")
    async def orders(store: Optional[str] = None, status: Optional[str] = None, current=Depends(get_current_user)):
        ids = [s["id"] for s in await pick(current, store)]
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""SELECT {ORDER_COLS} FROM public.medicine_orders WHERE pharmacy_id = ANY($1::text[])
                                         AND ($2::text IS NULL OR status = $2) ORDER BY created_at DESC LIMIT 300""", ids, status)
        items = [_row(x) for x in rows]
        counts: Dict[str, int] = {}
        for o in items:
            counts[o["status"]] = counts.get(o["status"], 0) + 1
        return {"orders": items, "counts": counts}

    async def owned_order(current, oid: str):
        ids = [s["id"] for s in await pick(current, None)]
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            o = await conn.fetchrow("SELECT id, status, pharmacy_id, total_amount, rx_image_b64 FROM public.medicine_orders WHERE id = $1", oid)
        if not o or o["pharmacy_id"] not in ids:
            raise HTTPException(status_code=404, detail="Order not found")
        return o

    @r.get("/orders/{oid}/rx-image")
    async def rx_image(oid: str, current=Depends(get_current_user)):
        o = await owned_order(current, oid)
        return {"image": o["rx_image_b64"]}

    @r.post("/orders/{oid}/action")
    async def order_action(oid: str, body: OrderAction, current=Depends(get_current_user)):
        if body.action not in ACTIONS:
            raise HTTPException(status_code=400, detail="Unknown action")
        o = await owned_order(current, oid)
        allowed, new = ACTIONS[body.action]
        if o["status"] not in allowed:
            raise HTTPException(status_code=409, detail=f"Order is {o['status'].replace('_', ' ').lower()}; cannot {body.action.replace('_', ' ')}")
        if body.action == "reject" and not (body.reason or "").strip():
            raise HTTPException(status_code=400, detail="Please give a reason for rejecting")
        amount = body.total_amount if body.total_amount is not None else o["total_amount"]
        if body.action == "fulfil" and amount is None:
            raise HTTPException(status_code=400, detail="Enter the bill amount before marking fulfilled")
        note = {"accept": "Accepted by pharmacy", "reject": f"Rejected: {body.reason}", "fulfil": "Order fulfilled",
                "mark_paid": "Payment received"}[body.action] + (f" — {body.note}" if body.note else "")
        event = {"at": datetime.now(timezone.utc).isoformat(), "event": new or "PAID", "by": "pharmacy", "note": note,
                 "by_name": current.get("name"), "via": "crm"}
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                UPDATE public.medicine_orders SET status = coalesce($2, status), total_amount = $3,
                       is_paid = CASE WHEN $4 THEN true ELSE is_paid END,
                       rejection_reason = CASE WHEN $2 = 'REJECTED' THEN $5 ELSE rejection_reason END,
                       pharmacy_notes = coalesce($6, pharmacy_notes),
                       timeline = (coalesce(timeline::jsonb, '[]'::jsonb) || $7::jsonb)::json, updated_at = now()
                 WHERE id = $1 AND status = $8 RETURNING {ORDER_COLS}""",
                oid, new, amount, body.action == "mark_paid", body.reason, body.note, json.dumps([event]), o["status"])
        if not row:
            raise HTTPException(status_code=409, detail="Order changed meanwhile, refresh and try again")
        await db.audit_log.insert_one({"action": f"pharmacy.order.{body.action}", "order_id": oid, "by": current["id"],
                                       "at": event["at"], "from": o["status"], "to": new})
        return {"order": _row(row)}

    # ---------- Prescriptions inbox (Provider app API) ----------
    @r.get("/prescriptions")
    async def prescriptions(store: Optional[str] = None, current=Depends(get_current_user)):
        stores = await pick(current, store)
        res = await asyncio.gather(*[_provider_api("GET", f"/api/pharmacy/{s['id']}/prescriptions") for s in stores], return_exceptions=True)
        seen, out, errors = set(), [], 0
        for s, data in zip(stores, res):
            if isinstance(data, Exception):
                errors += 1
                continue
            for rx in data.get("prescriptions", []):
                if rx["id"] in seen:
                    continue
                seen.add(rx["id"])
                out.append({**rx, "store_id": rx.get("pharmacy_id") or s["id"], "store_name": s["name"], "rx_image_b64": None,
                            "has_rx_image": bool(rx.get("rx_image_b64"))})
        out.sort(key=lambda x: x.get("submitted_at") or "", reverse=True)
        return {"prescriptions": out, "unreachable_stores": errors}

    @r.put("/prescriptions/{rx_id}/status")
    async def rx_status(rx_id: str, body: RxStatus, current=Depends(get_current_user)):
        if body.status not in RX_STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status")
        ids = [s["id"] for s in await pick(current, None)]
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            rx = await conn.fetchrow("SELECT pharmacy_id FROM public.prescriptions WHERE id = $1", rx_id)
        if not rx or (rx["pharmacy_id"] and rx["pharmacy_id"] not in ids):
            raise HTTPException(status_code=404, detail="Prescription not found")
        if body.status == "rejected" and not (body.rejection_reason or "").strip():
            raise HTTPException(status_code=400, detail="Please give a reason for rejecting")
        out = await _provider_api("PUT", f"/api/pharmacy/prescription/{rx_id}/status", json=body.model_dump(exclude_none=True))
        await db.audit_log.insert_one({"action": f"pharmacy.rx.{body.status}", "rx_id": rx_id, "by": current["id"],
                                       "at": datetime.now(timezone.utc).isoformat()})
        return out

    # ---------- Stock (Provider app API) ----------
    @r.get("/inventory")
    async def inventory(store: Optional[str] = None, low_stock_only: bool = False, search: str = "", current=Depends(get_current_user)):
        stores = await pick(current, store)
        params = {"low_stock_only": str(low_stock_only).lower(), **({"search": search.strip()} if search.strip() else {})}
        res = await asyncio.gather(*[_provider_api("GET", f"/api/pharmacy/{s['id']}/inventory", params=params) for s in stores],
                                   return_exceptions=True)
        soon = (datetime.now(IST) + timedelta(days=60)).date().isoformat()
        items = []
        for s, data in zip(stores, res):
            if isinstance(data, Exception):
                continue
            for it in data.get("items", []):
                exp = (it.get("expiry_date") or "")[:10]
                items.append({**it, "store_id": s["id"], "store_name": s["name"],
                              "low_stock": (it.get("qty_in_stock") or 0) <= (it.get("reorder_threshold") or 0),
                              "expiring_soon": bool(exp) and exp <= soon, "expired": bool(exp) and exp < datetime.now(IST).date().isoformat()})
        return {"items": items, "low_stock": sum(i["low_stock"] for i in items), "expiring_soon": sum(i["expiring_soon"] for i in items)}

    async def owned_item(current, item_id: str):
        ids = [s["id"] for s in await pick(current, None)]
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            pid = await conn.fetchval("SELECT pharmacy_id FROM public.pharmacy_inventory_items WHERE id = $1", item_id)
        if pid not in ids:
            raise HTTPException(status_code=404, detail="Stock item not found")

    def stock_payload(body: StockItem) -> Dict[str, Any]:
        d = body.model_dump(exclude_none=True)
        if d.get("expiry_date"):
            try:
                d["expiry_date"] = datetime.fromisoformat(d["expiry_date"][:10]).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                raise HTTPException(status_code=400, detail="Expiry must be a date (YYYY-MM-DD)")
        return d

    @r.post("/inventory")
    async def add_item(body: StockItem, store: str, current=Depends(get_current_user)):
        s = (await pick(current, store))[0]
        if not (body.medicine_name or "").strip():
            raise HTTPException(status_code=400, detail="Medicine name is required")
        return await _provider_api("POST", f"/api/pharmacy/{s['id']}/inventory", json=stock_payload(body))

    @r.patch("/inventory/{item_id}")
    async def edit_item(item_id: str, body: StockItem, current=Depends(get_current_user)):
        await owned_item(current, item_id)
        return await _provider_api("PATCH", f"/api/pharmacy/inventory/{item_id}", json=stock_payload(body))

    @r.delete("/inventory/{item_id}")
    async def delete_item(item_id: str, current=Depends(get_current_user)):
        await owned_item(current, item_id)
        return await _provider_api("DELETE", f"/api/pharmacy/inventory/{item_id}")

    # ---------- Sales ----------
    @r.get("/sales")
    async def sales(store: Optional[str] = None, days: int = 30, current=Depends(get_current_user)):
        stores = await pick(current, store)
        ids, names = [s["id"] for s in stores], {s["id"]: s["name"] for s in stores}
        days = max(1, min(days, 365))
        since = datetime.now(timezone.utc) - timedelta(days=days)
        pool = await sb.get_pool()
        async with pool.acquire() as conn:
            orders = await conn.fetch("""SELECT pharmacy_id, status, total_amount, is_paid, items, created_at, updated_at
                                           FROM public.medicine_orders WHERE pharmacy_id = ANY($1::text[]) AND created_at >= $2""", ids, since)
            rxs = await conn.fetch("""SELECT pharmacy_id, status, total_amount, items, coalesce(fulfilled_at, updated_at, created_at) AS at
                                        FROM public.prescriptions WHERE pharmacy_id = ANY($1::text[]) AND coalesce(submitted_at, created_at) >= $2""",
                                   ids, since)
        series = {(datetime.now(IST) - timedelta(days=i)).date().isoformat(): {"revenue": 0.0, "orders": 0} for i in range(days - 1, -1, -1)}
        by_store = {i: {"store_id": i, "store_name": names[i], "revenue": 0.0, "orders": 0} for i in ids}
        meds: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}
        revenue = fulfilled = rejected = 0

        def add(pid, st, amount, items, at, done):
            nonlocal revenue, fulfilled, rejected
            status_counts[st] = status_counts.get(st, 0) + 1
            rejected += st in ("REJECTED", "rejected")
            if not done:
                return
            amt = float(amount or 0)
            revenue += amt
            fulfilled += 1
            day = at.astimezone(IST).date().isoformat()
            if day in series:
                series[day]["revenue"] += amt
                series[day]["orders"] += 1
            if pid in by_store:
                by_store[pid]["revenue"] += amt
                by_store[pid]["orders"] += 1
            for it in _j(items) or []:
                n = (it.get("name") or it.get("line") or "").strip() if isinstance(it, dict) else str(it)
                if n:
                    meds[n] = meds.get(n, 0) + 1

        for o in orders:
            add(o["pharmacy_id"], o["status"], o["total_amount"], o["items"], o["updated_at"] or o["created_at"], o["status"] == "FULFILLED")
        for x in rxs:
            add(x["pharmacy_id"], x["status"], x["total_amount"], x["items"], x["at"], x["status"] == "fulfilled")
        total = len(orders) + len(rxs)
        return {"days": days, "revenue": round(revenue, 2), "fulfilled": fulfilled, "total_requests": total,
                "avg_order_value": round(revenue / fulfilled, 2) if fulfilled else 0, "rejection_rate": round(rejected / total * 100, 1) if total else 0,
                "open_orders": sum(status_counts.get(k, 0) for k in OPEN + ("ACCEPTED", "submitted", "accepted", "ready_for_pickup")),
                "series": [{"date": k, **v} for k, v in series.items()], "by_store": sorted(by_store.values(), key=lambda x: -x["revenue"]),
                "top_medicines": [{"name": k, "count": v} for k, v in sorted(meds.items(), key=lambda kv: -kv[1])[:10]],
                "status_counts": status_counts}

    return r
