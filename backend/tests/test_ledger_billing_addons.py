"""Iter15 — Ledger billing add-ons: monthly drafts, share (number + email), reminders, cron guard,
revenue dashboard, lab-split onboarding (legacy path).
Pre: `python ledger_probe_fixtures.py setup` (writes /tmp/ledger_probe_state.json). Post: `... cleanup`.
SHARED PRODUCTION Supabase: only TEST_probe providers are shared/reminded; real-provider drafts are hard-deleted."""
import asyncio
import io
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
import requests
from dotenv import dotenv_values

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import BASE_URL, DSN  # noqa: E402
from ledger_probe_fixtures import STATE_FILE  # noqa: E402

ST = json.load(open(STATE_FILE))
A, B = ST["uid_a"], ST["uid_b"]
ADM = {"Authorization": f"Bearer {ST['tok_admin']}"}
PA = {"Authorization": f"Bearer {ST['tok_a']}"}
BENV = dotenv_values("/app/backend/.env")
SECRET = BENV["WEBHOOK_CRON_SECRET"]
MONTH = datetime.now(timezone.utc).strftime("%Y-%m")
LAB_PHONES = ["9999900031", "9999900032"]
CTX = {}
T0 = datetime.now(timezone.utc).isoformat()


def _mongo():
    from motor.motor_asyncio import AsyncIOMotorClient
    return AsyncIOMotorClient(BENV["MONGO_URL"])[BENV["DB_NAME"]]


def mrun(fn):
    async def go():
        db = _mongo()
        try:
            return await fn(db)
        finally:
            db.client.close()
    return asyncio.run(go())


def sbrun(sql, *args, fetch=True):
    async def go():
        c = await asyncpg.connect(DSN, statement_cache_size=0)
        try:
            return await (c.fetch(sql, *args) if fetch else c.execute(sql, *args))
        finally:
            await c.close()
    return asyncio.run(go())


def inv(iid):
    return mrun(lambda db: db.ledger_invoices.find_one({"id": iid}, {"_id": 0}))


@pytest.fixture(scope="module", autouse=True)
def teardown_module_data():
    yield
    # hard-delete every invoice created during this run for NON-probe providers (drafts from runs/cron)
    async def clean(db):
        await db.ledger_invoices.delete_many({"created_at": {"$gte": T0}, "provider_user_id": {"$nin": [A, B]}})
        await db.billing_profiles.update_many({"provider_user_id": {"$in": [A, B]}}, {"$set": {"billing_email": None}})
        await db.crm_users.delete_many({"phone": {"$in": LAB_PHONES}})
        await db.contacts.delete_many({"phone": {"$in": LAB_PHONES}})
    mrun(clean)
    ids = [r["id"] for r in sbrun("SELECT id FROM public.users WHERE phone = ANY($1::text[])", LAB_PHONES)]
    if ids:
        sbrun("DELETE FROM public.labs WHERE pathologist_profile_id IN (SELECT id FROM public.pathologists WHERE user_id = ANY($1::text[]))", ids, fetch=False)
        sbrun("DELETE FROM public.pathologists WHERE user_id = ANY($1::text[])", ids, fetch=False)
        for tbl, btbl, fk in (("path_lab_profiles", "path_lab_branches", "path_lab_profile_id"),
                              ("diagnostic_centre_profiles", "diagnostic_centre_branches", "diagnostic_centre_profile_id")):
            if sbrun("SELECT to_regclass($1) AS t", f"public.{tbl}")[0]["t"]:
                sbrun(f"DELETE FROM public.{btbl} WHERE {fk} IN (SELECT id FROM public.{tbl} WHERE user_id = ANY($1::text[]))", ids, fetch=False)
                sbrun(f"DELETE FROM public.{tbl} WHERE user_id = ANY($1::text[])", ids, fetch=False)
        sbrun("DELETE FROM public.notifications WHERE user_id = ANY($1::text[])", ids, fetch=False)
        sbrun("DELETE FROM public.kyc_documents WHERE user_id = ANY($1::text[])", ids, fetch=False)
        sbrun("DELETE FROM public.users WHERE id = ANY($1::text[])", ids, fetch=False)


def post(path, **kw):
    return requests.post(f"{BASE_URL}/api{path}", headers=kw.pop("headers", ADM), timeout=120, **kw)


def get(path, **kw):
    return requests.get(f"{BASE_URL}/api{path}", headers=kw.pop("headers", ADM), timeout=120, **kw)


# ── Monthly drafts ───────────────────────────────────────────────────────────
class TestMonthlyDrafts:
    def test_missing_default_sac_error(self):
        s = get("/ledger/settings").json()
        CTX["settings"] = s
        r = requests.put(f"{BASE_URL}/api/ledger/settings", headers=ADM, timeout=30, json={**s, "default_sac": ""})
        assert r.status_code == 200
        try:
            r = post(f"/ledger/run/monthly-drafts?month={MONTH}")
            assert r.status_code == 200
            d = r.json()
            assert d["created"] == 0 and "SAC" in d.get("error", ""), d
        finally:
            rr = requests.put(f"{BASE_URL}/api/ledger/settings", headers=ADM, timeout=30, json=s)
            assert rr.status_code == 200 and get("/ledger/settings").json()["default_sac"] == s["default_sac"]

    def test_requires_admin(self):
        assert post(f"/ledger/run/monthly-drafts?month={MONTH}", headers=PA).status_code == 403
        assert post("/ledger/run/reminders", headers=PA).status_code == 403
        assert get("/ledger/revenue", headers=PA).status_code == 403

    def test_seed_promotions(self):
        # probe SOS rows have amount 0 → seed a billable flat promo fee per probe for MONTH
        for uid, amt in ((A, 1000), (B, 500)):
            r = post(f"/ledger/providers/{uid}/promotions", json={"title": "TEST_probe iter15 promo", "amount": amt,
                                                                  "charge_date": f"{MONTH}-05"})
            assert r.status_code == 200, r.text

    def test_run_creates_drafts_for_probes(self):
        r = post(f"/ledger/run/monthly-drafts?month={MONTH}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["month"] == MONTH and d["created"] >= 2, d
        docs = mrun(lambda db: db.ledger_invoices.find({"provider_user_id": {"$in": [A, B]}, "month": MONTH,
                                                         "status": "draft"}, {"_id": 0}).to_list(10))
        by = {x["provider_user_id"]: x for x in docs}
        assert set(by) == {A, B}
        for x in by.values():
            assert x["number"] is None and x["sac_code"] == CTX["settings"]["default_sac"] and x["lines"]
        CTX["draft_a"], CTX["draft_b"] = by[A]["id"], by[B]["id"]

    def test_rerun_is_idempotent(self):
        d = post(f"/ledger/run/monthly-drafts?month={MONTH}").json()
        ids = {x["id"] for x in d["invoices"]}
        assert CTX["draft_a"] not in ids
        assert not [x for x in d["invoices"] if inv(x["id"])["provider_user_id"] in (A, B)]
        n = mrun(lambda db: db.ledger_invoices.count_documents({"provider_user_id": A, "month": MONTH, "status": {"$ne": "void"}}))
        assert n == 1

    def test_draft_hidden_from_provider(self):
        r = get("/provider/ledger", headers=PA)
        assert r.status_code == 200
        assert CTX["draft_a"] not in [i["id"] for i in r.json()["invoices"]]
        assert get(f"/ledger/invoices/{CTX['draft_a']}", headers=PA).status_code == 403
        assert get(f"/ledger/invoices/{CTX['draft_a']}/pdf", headers=PA).status_code == 403

    def test_draft_pdf_shows_draft(self):
        r = get(f"/ledger/invoices/{CTX['draft_a']}/pdf")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        assert "DRAFT-" in r.headers.get("content-disposition", "")
        from pypdf import PdfReader
        txt = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
        assert "DRAFT" in txt

    def test_paid_on_draft_400(self):
        r = post(f"/ledger/invoices/{CTX['draft_a']}/status?status=paid")
        assert r.status_code == 400 and "draft" in r.json()["detail"].lower()

    def test_status_filter_draft(self):
        items = get("/ledger/invoices", params={"status": "draft"}).json()["items"]
        assert items and all(i["status"] == "draft" for i in items)
        assert {CTX["draft_a"], CTX["draft_b"]} <= {i["id"] for i in items}
        assert all("lines" not in i for i in items)

    def test_discard_draft_then_reraise(self):
        r = post(f"/ledger/invoices/{CTX['draft_b']}/status?status=void")
        assert r.status_code == 200 and inv(CTX["draft_b"])["status"] == "void"
        d = post(f"/ledger/run/monthly-drafts?month={MONTH}").json()
        new = [x for x in d["invoices"] if inv(x["id"])["provider_user_id"] == B]
        assert len(new) == 1, d
        CTX["draft_b"] = new[0]["id"]


# ── Share (number + email) ───────────────────────────────────────────────────
class TestShare:
    def test_set_billing_email_a(self):
        bp = get(f"/ledger/providers/{A}").json()["billing_profile"]
        body = {k: bp.get(k) for k in ("fee_pct", "category_fee_pct", "legal_name", "gstin", "pan", "billing_address", "state")}
        body["billing_email"] = "delivered@resend.dev"
        r = requests.put(f"{BASE_URL}/api/ledger/providers/{A}/billing", headers=ADM, timeout=30, json=body)
        assert r.status_code == 200 and r.json()["billing_email"] == "delivered@resend.dev"

    def test_share_draft_a_sent(self):
        before = mrun(lambda db: db.ledger_counters.find_one({"id": f"inv-{MONTH}"}, {"_id": 0})) or {"n": 0}
        r = post(f"/ledger/invoices/{CTX['draft_a']}/share", headers={**ADM, "Origin": BASE_URL})
        assert r.status_code == 200, r.text
        d = r.json()
        exp = f"{CTX['settings'].get('invoice_prefix') or 'TH'}/{MONTH.replace('-', '')}/{before['n'] + 1:04d}"
        assert d["status"] == "shared" and d["number"] == exp, (d, exp)
        assert d["delivery"]["crm"] is True and d["delivery"]["email"] == "delivered@resend.dev"
        assert d["delivery"]["email_status"] == "sent", d
        x = inv(CTX["draft_a"])
        assert x["number"] == exp and x["status"] == "shared" and x["app_url"] == BASE_URL
        assert x["issue_date"] == datetime.now(timezone(timedelta(hours=5, minutes=30))).date().isoformat() and x["due_date"] > x["issue_date"]
        assert x["deliveries"][-1]["kind"] == "shared"

    def test_share_notification_row(self):
        rows = sbrun("SELECT title, notification_type, data::text AS d FROM public.notifications WHERE user_id=$1", A)
        mine = [r for r in rows if CTX["draft_a"] in r["d"]]
        assert mine and mine[0]["notification_type"] == "invoice"

    def test_provider_sees_shared(self):
        ids = [i["id"] for i in get("/provider/ledger", headers=PA).json()["invoices"]]
        assert CTX["draft_a"] in ids
        assert get(f"/ledger/invoices/{CTX['draft_a']}/pdf", headers=PA).status_code == 200

    def test_share_b_no_email(self):
        sbrun("UPDATE public.users SET email=NULL WHERE id=$1", B, fetch=False)
        mrun(lambda db: db.billing_profiles.update_one({"provider_user_id": B}, {"$unset": {"billing_email": ""}}))
        mrun(lambda db: db.ledger_invoices.update_many({"provider_user_id": B}, {"$set": {"provider_email": None}}))
        d = post(f"/ledger/invoices/{CTX['draft_b']}/share").json()
        assert d["status"] == "shared" and d["number"]
        assert d["delivery"]["crm"] is True and d["delivery"]["email_status"] == "no_email_on_file", d


# ── Reminders ────────────────────────────────────────────────────────────────
class TestReminders:
    def test_not_due_not_reminded(self):
        d = post("/ledger/run/reminders").json()
        assert CTX["draft_a"] not in [i["id"] for i in d["items"]]

    def test_overdue_reminded_once(self):
        mrun(lambda db: db.ledger_invoices.update_one({"id": CTX["draft_a"]}, {"$set": {"due_date": "2026-01-01"}}))
        d = post("/ledger/run/reminders").json()
        it = [i for i in d["items"] if i["id"] == CTX["draft_a"]]
        assert len(it) == 1 and it[0]["crm"] is True and it[0]["email_status"] == "sent", d
        x = inv(CTX["draft_a"])
        assert x["reminder_count"] == 1 and x["last_reminder_at"] and x["deliveries"][-1]["kind"] == "reminder"
        rows = sbrun("SELECT notification_type FROM public.notifications WHERE user_id=$1 AND data::text LIKE $2", A, f"%{CTX['draft_a']}%")
        assert "invoice_reminder" in [r["notification_type"] for r in rows]
        d2 = post("/ledger/run/reminders").json()
        assert CTX["draft_a"] not in [i["id"] for i in d2["items"]]

    def test_reminded_again_after_3_days(self):
        old = (datetime.now(timezone.utc) - timedelta(days=3, minutes=5)).isoformat()
        mrun(lambda db: db.ledger_invoices.update_one({"id": CTX["draft_a"]}, {"$set": {"last_reminder_at": old}}))
        d = post("/ledger/run/reminders").json()
        assert CTX["draft_a"] in [i["id"] for i in d["items"]]
        assert inv(CTX["draft_a"])["reminder_count"] == 2

    def test_paid_never_reminded(self):
        assert post(f"/ledger/invoices/{CTX['draft_b']}/status?status=paid").status_code == 200
        mrun(lambda db: db.ledger_invoices.update_one({"id": CTX["draft_b"]}, {"$set": {"due_date": "2026-01-01"}}))
        d = post("/ledger/run/reminders").json()
        assert CTX["draft_b"] not in [i["id"] for i in d["items"]]
        assert not inv(CTX["draft_b"]).get("reminder_count")


# ── Revenue ──────────────────────────────────────────────────────────────────
class TestRevenue:
    def test_revenue_aggregates(self):
        d = get("/ledger/revenue").json()
        allinv = get("/ledger/invoices").json()["items"]
        live = [i for i in allinv if i["status"] not in ("draft", "void")]
        assert d["drafts"] == sum(1 for i in allinv if i["status"] == "draft")
        m = next(x for x in d["months"] if x["month"] == MONTH)
        mine = [i for i in live if i["month"] == MONTH]
        assert m["invoices"] == len(mine)
        assert abs(m["invoiced"] - sum(i["grand_total"] for i in mine)) < 0.05
        assert abs(m["paid"] - sum(i["grand_total"] for i in mine if i["status"] == "paid")) < 0.05
        assert abs(m["unpaid"] + m["paid"] - m["invoiced"]) < 0.05
        assert abs(m["gst"] - (m["cgst"] + m["sgst"] + m["igst"])) < 0.05
        assert m["overdue"] >= inv(CTX["draft_a"])["grand_total"] - 0.01
        assert abs(d["totals"]["invoiced"] - sum(x["invoiced"] for x in d["months"])) < 0.05
        o = next(x for x in d["outstanding"] if x["provider_user_id"] == A)
        assert o["overdue"] > 0 and o["oldest_due"] == "2026-01-01"
        assert B not in [x["provider_user_id"] for x in d["outstanding"]] or \
            next(x for x in d["outstanding"] if x["provider_user_id"] == B)["invoices"] >= 1


# ── Cron guard ───────────────────────────────────────────────────────────────
class TestCron:
    @pytest.mark.parametrize("ep", ["invoice-reminders", "monthly-invoices"])
    def test_unauthorized(self, ep):
        assert requests.post(f"{BASE_URL}/api/cron/{ep}", timeout=30).status_code == 401
        assert requests.post(f"{BASE_URL}/api/cron/{ep}", headers={"Authorization": "Bearer nope"}, timeout=30).status_code == 401

    def test_reminders_cron_idempotent(self):
        rid = f"TEST_probe-{uuid.uuid4()}"
        h = {"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": rid}
        r1 = requests.post(f"{BASE_URL}/api/cron/invoice-reminders", headers=h, json={}, timeout=30)
        r2 = requests.post(f"{BASE_URL}/api/cron/invoice-reminders", headers=h, json={}, timeout=30)
        assert r1.status_code == 200 and r1.json() == {"accepted": True}
        assert r2.status_code == 200 and r2.json() == {"accepted": True}
        assert mrun(lambda db: db.cron_runs.count_documents({"run_id": rid})) == 1
        mrun(lambda db: db.cron_runs.delete_many({"run_id": rid}))

    def test_monthly_cron_runs_in_background(self):
        rid = f"TEST_probe-{uuid.uuid4()}"
        r = requests.post(f"{BASE_URL}/api/cron/monthly-invoices",
                          headers={"Authorization": f"Bearer {SECRET}", "X-Webhook-Id": rid}, timeout=30)
        assert r.status_code == 200 and r.json() == {"accepted": True}
        assert mrun(lambda db: db.cron_runs.find_one({"run_id": rid}, {"_id": 0}))["name"] == "monthly-invoices"
        time.sleep(25)
        n = mrun(lambda db: db.ledger_invoices.count_documents({"created_by.id": "cron", "created_at": {"$gte": T0}}))
        print(f"cron drafts created: {n}")
        mrun(lambda db: db.cron_runs.delete_many({"run_id": rid}))


# ── Onboarding lab split prep ────────────────────────────────────────────────
class TestLabOnboarding:
    BASE = {"vertical": "pathology", "city": "Mumbai", "state": "Maharashtra", "address": "TEST_probe lab",
            "lat": 19.07, "lng": 72.87}

    def test_pathology_without_kind_400(self):
        r = post("/admin/onboarding/providers", json={**self.BASE, "phone": LAB_PHONES[0], "name": "TEST_probe Lab X"})
        assert r.status_code == 400 and "Lab Partner" in r.json()["detail"]
        r = post("/admin/onboarding/providers", json={**self.BASE, "phone": LAB_PHONES[0], "name": "TEST_probe Lab X", "lab_kind": "xray"})
        assert r.status_code == 400

    @pytest.mark.parametrize("i,kind", [(0, "path_lab"), (1, "diagnostic_centre")])
    def test_create_legacy_rows(self, i, kind):
        r = post("/admin/onboarding/providers", json={**self.BASE, "phone": LAB_PHONES[i], "lab_kind": kind,
                                                      "name": f"TEST_probe Lab {kind}"})
        assert r.status_code == 200, r.text
        uid = r.json()["user_id"]
        tbl = {"path_lab": "path_lab_profiles", "diagnostic_centre": "diagnostic_centre_profiles"}[kind]
        if sbrun("SELECT to_regclass($1) AS t", f"public.{tbl}")[0]["t"]:
            rows = sbrun(f"SELECT id FROM public.{tbl} WHERE user_id=$1", uid)
            assert len(rows) == 1
        else:
            rows = sbrun("""SELECT l.lab_type FROM public.pathologists p JOIN public.labs l ON l.pathologist_profile_id = p.id
                            WHERE p.user_id=$1""", uid)
            assert [x["lab_type"] for x in rows] == [kind]
