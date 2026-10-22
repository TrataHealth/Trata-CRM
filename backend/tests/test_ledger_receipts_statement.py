"""Iter16 — Paid receipts (record payment body, receipt PDF, CRM notification), collections forecast,
provider statement (running balance, date filters, PDF).
Pre: `python ledger_probe_fixtures.py setup`. Post: `... cleanup`. Only TEST_probe providers are touched."""
import asyncio
import json
import sys
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
PB = {"Authorization": f"Bearer {ST['tok_b']}"}
BENV = dotenv_values("/app/backend/.env")
IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date()
MONTH = TODAY.strftime("%Y-%m")
M1 = (TODAY.replace(day=1) - timedelta(days=40)).strftime("%Y-%m")
M2 = (TODAY.replace(day=1) - timedelta(days=10)).strftime("%Y-%m")
CTX = {}


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


def sbrun(sql, *args):
    async def go():
        c = await asyncpg.connect(DSN, statement_cache_size=0)
        try:
            return await c.fetch(sql, *args)
        finally:
            await c.close()
    return asyncio.run(go())


def setinv(iid, **fields):
    mrun(lambda db: db.ledger_invoices.update_one({"id": iid}, {"$set": fields}))


def inv(iid):
    return mrun(lambda db: db.ledger_invoices.find_one({"id": iid}, {"_id": 0}))


def post(path, **kw):
    return requests.post(f"{BASE_URL}/api{path}", headers=kw.pop("headers", ADM), timeout=120, **kw)


def get(path, **kw):
    return requests.get(f"{BASE_URL}/api{path}", headers=kw.pop("headers", ADM), timeout=120, **kw)


def make_invoice(uid, month, amount):
    r = post(f"/ledger/providers/{uid}/promotions", json={"title": f"TEST_probe promo {month}", "amount": amount,
                                                          "charge_date": f"{month}-05"})
    assert r.status_code == 200, r.text
    r = post(f"/ledger/providers/{uid}/invoices", json={"month": month, "sac_code": "998599"})
    assert r.status_code == 200, r.text
    iid = r.json().get("id") or r.json().get("invoice", {}).get("id")
    assert iid, r.json()
    r = post(f"/ledger/invoices/{iid}/share")
    assert r.status_code == 200, r.text
    return iid


# ---------- setup: 3 invoices for A, 1 for B ----------
class TestSetup:
    def test_create_invoices(self):
        CTX["a1"] = make_invoice(A, M1, 1000)
        CTX["a2"] = make_invoice(A, M2, 2000)
        CTX["a3"] = make_invoice(A, MONTH, 3000)
        CTX["b1"] = make_invoice(B, MONTH, 500)
        for k in ("a1", "a2", "a3", "b1"):
            assert inv(CTX[k])["status"] == "shared"
        setinv(CTX["a1"], issue_date=f"{M1}-10")
        setinv(CTX["a2"], issue_date=f"{M2}-10")


# ---------- mark paid with payment body ----------
class TestMarkPaid:
    def test_future_date_400(self):
        fut = (TODAY + timedelta(days=2)).isoformat()
        r = post(f"/ledger/invoices/{CTX['a1']}/status?status=paid", json={"paid_on": fut, "mode": "upi"})
        assert r.status_code == 400 and "past date" in r.json()["detail"]

    def test_bad_format_and_mode_400(self):
        assert post(f"/ledger/invoices/{CTX['a1']}/status?status=paid", json={"paid_on": "21-10-2026"}).status_code == 400
        assert post(f"/ledger/invoices/{CTX['a1']}/status?status=paid", json={"paid_on": "2026-02-30"}).status_code == 400
        r = post(f"/ledger/invoices/{CTX['a3']}/status?status=paid", json={"paid_on": (TODAY - timedelta(days=1)).isoformat()})
        assert r.status_code == 400 and "before the invoice date" in r.json()["detail"]
        assert get("/ledger/statement?from=2026-13-45", headers=PA).status_code == 400
        r = post(f"/ledger/invoices/{CTX['a1']}/status?status=paid", json={"mode": "bitcoin"})
        assert r.status_code == 400 and "mode" in r.json()["detail"].lower()
        assert inv(CTX["a1"])["status"] == "shared"

    def test_provider_cannot_mark_paid(self):
        assert post(f"/ledger/invoices/{CTX['a1']}/status?status=paid", headers=PA, json={}).status_code == 403

    def test_paid_with_body(self):
        paid_on = (TODAY - timedelta(days=3)).isoformat()
        r = post(f"/ledger/invoices/{CTX['a1']}/status?status=paid",
                 json={"paid_on": paid_on, "mode": "upi", "reference": "TEST_UTR123", "note": "TEST_probe note"})
        assert r.status_code == 200, r.text
        d = r.json()
        number = inv(CTX["a1"])["number"]
        assert d["success"] and d["status"] == "paid"
        assert d["receipt_no"] == "RCPT/" + number.replace("/", "-")
        assert d["delivery"]["kind"] == "receipt"
        assert d["delivery"]["crm"] is True
        p = inv(CTX["a1"])["payment"]
        assert p["paid_on"] == paid_on and p["mode"] == "upi" and p["reference"] == "TEST_UTR123"
        assert p["note"] == "TEST_probe note" and p["amount"] == inv(CTX["a1"])["grand_total"]
        assert p["amount_words"]
        CTX["paid_on_a1"] = paid_on

    def test_crm_notification_row(self):
        rows = sbrun("SELECT title, notification_type FROM public.notifications WHERE user_id=$1 "
                     "AND notification_type='invoice_receipt'", A)
        assert rows, "no invoice_receipt notification"
        assert "receipt" in rows[0]["title"].lower()

    def test_already_paid_and_void_paid_400(self):
        r = post(f"/ledger/invoices/{CTX['a1']}/status?status=paid", json={})
        assert r.status_code == 400 and r.json()["detail"] == "Invoice already paid"
        r = post(f"/ledger/invoices/{CTX['a1']}/status?status=void")
        assert r.status_code == 400

    def test_paid_without_body_defaults(self):
        r = post(f"/ledger/invoices/{CTX['a2']}/status?status=paid")
        assert r.status_code == 200, r.text
        p = inv(CTX["a2"])["payment"]
        assert p["paid_on"] == TODAY.isoformat() and p["mode"] == "bank_transfer"
        assert p["reference"] is None


# ---------- receipt PDF ----------
class TestReceiptPdf:
    def test_admin_and_owner(self):
        for h in (ADM, PA):
            r = get(f"/ledger/invoices/{CTX['a1']}/receipt", headers=h)
            assert r.status_code == 200 and r.headers["content-type"].startswith("application/pdf")
            assert r.content[:4] == b"%PDF" and "RCPT-" in r.headers.get("content-disposition", "")

    def test_query_token(self):
        r = requests.get(f"{BASE_URL}/api/ledger/invoices/{CTX['a1']}/receipt?token={ST['tok_a']}", timeout=60)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_other_provider_403_unpaid_400(self):
        assert get(f"/ledger/invoices/{CTX['a1']}/receipt", headers=PB).status_code == 403
        assert get(f"/ledger/invoices/{CTX['a3']}/receipt").status_code == 400

    def test_invoice_pdf_still_works(self):
        r = get(f"/ledger/invoices/{CTX['a1']}/pdf")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"


# ---------- forecast ----------
class TestForecast:
    def test_provider_403(self):
        assert get("/ledger/forecast", headers=PA).status_code == 403

    def test_shape(self):
        d = get("/ledger/forecast?days=30").json()
        assert len(d["daily"]) == 30 and d["daily"][0]["date"] == TODAY.isoformat()
        assert [w["label"] for w in d["weekly"]] == ["This week", "Next week", "Days 15–21", "Days 22–28", "Days 29–30"]
        assert abs(sum(w["amount"] for w in d["weekly"]) - d["upcoming"]["amount"]) < 0.01
        assert abs(d["expected_total"] - d["upcoming"]["amount"] - d["overdue"]["amount"]) < 0.01
        CTX["fc0"] = d

    def test_buckets_reflect_due_dates(self):
        base = CTX["fc0"]
        a3, b1 = inv(CTX["a3"]), inv(CTX["b1"])
        # move a3 to due in 10 days (Next week), b1 to overdue, check deltas
        old = {k: inv(CTX[k])["due_date"] for k in ("a3", "b1")}
        CTX["old_due"] = old
        due_a3 = (TODAY + timedelta(days=10)).isoformat()
        setinv(CTX["a3"], due_date=due_a3)
        setinv(CTX["b1"], due_date=(TODAY - timedelta(days=5)).isoformat())
        d = get("/ledger/forecast?days=30").json()
        ids = {i["id"]: i for i in d["items"]}
        assert CTX["a3"] in ids and ids[CTX["a3"]]["overdue"] is False
        assert CTX["b1"] in ids and ids[CTX["b1"]]["overdue"] is True
        assert CTX["a1"] not in ids and CTX["a2"] not in ids  # paid excluded
        day = next(x for x in d["daily"] if x["date"] == due_a3)
        assert day["amount"] >= a3["grand_total"]
        assert d["weekly"][1]["amount"] >= a3["grand_total"]
        assert d["overdue"]["amount"] >= b1["grand_total"]
        # independent recompute from Mongo
        async def agg(db):
            return await db.ledger_invoices.find({"status": {"$in": ["issued", "shared"]}}, {"_id": 0, "due_date": 1, "grand_total": 1}).to_list(5000)
        rows = mrun(agg)
        t = TODAY.isoformat()
        ov = sum(r["grand_total"] for r in rows if (r.get("due_date") or "") < t)
        assert abs(d["overdue"]["amount"] - round(ov, 2)) < 0.02
        _ = base

    def test_days_param(self):
        d = get("/ledger/forecast?days=14").json()
        assert len(d["daily"]) == 14 and len(d["weekly"]) == 2


# ---------- statement ----------
class TestStatement:
    def test_auth_rules(self):
        assert get(f"/ledger/statement?uid={A}", headers=PA).status_code == 403
        assert get("/ledger/statement").status_code == 403
        assert get("/ledger/statement?from=2026/01/01", headers=PA).status_code == 400
        assert get("/ledger/statement?to=abc", headers=PA).status_code == 400

    def test_running_balance(self):
        # deterministic dates on probe invoices
        setinv(CTX["a1"], issue_date=f"{M1}-10")
        setinv(CTX["a2"], issue_date=f"{M2}-10")
        d = get("/ledger/statement", headers=PA).json()
        g1, g2, g3 = (inv(CTX[k])["grand_total"] for k in ("a1", "a2", "a3"))
        assert d["provider_user_id"] == A and d["opening_balance"] == 0
        assert len(d["entries"]) == 5  # 3 invoices + 2 payments
        bal = 0
        for e in d["entries"]:
            bal = round(bal + e["debit"] - e["credit"], 2)
            assert e["balance"] == bal
        assert d["closing_balance"] == round(g3, 2)
        assert d["total_debit"] == round(g1 + g2 + g3, 2) and d["total_credit"] == round(g1 + g2, 2)
        dates = [e["date"] for e in d["entries"]]
        assert dates == sorted(dates)
        pay = [e for e in d["entries"] if e["type"] == "payment"]
        assert any(e["ref"].startswith("RCPT/") and "UPI" in e["description"] for e in pay)
        # admin sees same
        da = get(f"/ledger/statement?uid={A}").json()
        assert da["closing_balance"] == d["closing_balance"] and len(da["entries"]) == 5

    def test_date_filter_opening(self):
        frm = f"{M2}-01"
        d = get(f"/ledger/statement?from={frm}", headers=PA).json()
        g1 = inv(CTX["a1"])["grand_total"]
        # a1 invoice (M1-10) is before 'from'; a1 payment (paid 3 days ago) is inside
        assert d["opening_balance"] == round(g1, 2)
        assert all(e["date"] >= frm for e in d["entries"])
        full = get("/ledger/statement", headers=PA).json()
        assert d["closing_balance"] == full["closing_balance"]
        to = f"{M2}-28"
        d2 = get(f"/ledger/statement?from={frm}&to={to}", headers=PA).json()
        assert all(frm <= e["date"] <= to for e in d2["entries"])

    def test_other_provider_isolated(self):
        d = get("/ledger/statement", headers=PB).json()
        assert d["provider_user_id"] == B
        assert all(e["invoice_id"] == CTX["b1"] for e in d["entries"])

    def test_pdf(self):
        r = get("/ledger/statement/pdf", headers=PA)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
        r = requests.get(f"{BASE_URL}/api/ledger/statement/pdf?uid={A}&from={M2}-01&token={ST['tok_admin']}", timeout=60)
        assert r.status_code == 200 and r.content[:4] == b"%PDF"
        assert requests.get(f"{BASE_URL}/api/ledger/statement/pdf?uid={A}&token={ST['tok_b']}", timeout=60).status_code == 403
        assert requests.get(f"{BASE_URL}/api/ledger/statement/pdf", timeout=60).status_code in (401, 403)
