"""Provider Ledger & invoicing — API regression tests (live shared Supabase, TEST_probe data only).
Pre: `python ledger_probe_fixtures.py setup` (writes /tmp/ledger_probe_state.json). Post: `... cleanup`.
Tests are ordered and share state via module-level dict S."""
import asyncio
import json
import os

import asyncpg
import pytest
import requests

from live_probe_fixtures import BASE_URL, DSN, ENV
from ledger_probe_fixtures import PATIENT_ID, STATE_FILE

ST = json.load(open(STATE_FILE))
XENON = "2d71f195-7f5a-454b-962d-ee944cebe8cf"
A, B = ST["uid_a"], ST["uid_b"]
H_ADM = {"Authorization": f"Bearer {ST['tok_admin']}"}
H_A = {"Authorization": f"Bearer {ST['tok_a']}"}
H_B = {"Authorization": f"Bearer {ST['tok_b']}"}
BILL = "/app/backend/tests/sample_bill.pdf"
MONTH, SDATE = "2025-12", "2025-12-10"
S = {}


def api(m, path, h=H_ADM, **kw):
    return requests.request(m, f"{BASE_URL}/api{path}", headers=h, timeout=120, **kw)


def upload(uid, content=None, name="bill.pdf", ctype="application/pdf", h=H_ADM, prov=False):
    data = content if content is not None else open(BILL, "rb").read()
    path = "/provider/ledger/files" if prov else f"/ledger/providers/{uid}/files"
    return api("POST", path, h=h, files={"file": (name, data, ctype)})


def svc_body(fids, **over):
    b = {"patient_id": PATIENT_ID, "category": "surgery", "title": "TEST_probe Appendectomy",
         "service_date": SDATE, "amount": 70000, "proof_file_ids": fids, "source": "manual",
         "line_items": [{"description": "OT", "amount": 70000}]}
    b.update(over)
    return b


# ── Access control ──
class TestAccess:
    @pytest.mark.parametrize("m,p", [("GET", "/ledger/providers"), ("GET", "/ledger/settings"),
                                     ("GET", "/ledger/review-queue"), ("GET", "/ledger/invoices"),
                                     ("GET", f"/ledger/providers/{XENON}"),
                                     ("POST", f"/ledger/providers/{A}/promotions")])
    def test_provider_forbidden_on_admin(self, m, p):
        r = api(m, p, h=H_A, json={"title": "x", "amount": 1, "charge_date": SDATE})
        assert r.status_code == 403, (p, r.status_code, r.text)

    def test_unauthenticated(self):
        assert api("GET", "/ledger/providers", h={}).status_code in (401, 403)


# ── Provider list & detail ──
class TestProviders:
    def test_list_has_xenon_2_patients(self):
        r = api("GET", "/ledger/providers?month=" + MONTH)
        assert r.status_code == 200
        d = r.json()
        assert d["month"] == MONTH and {"providers", "patients", "pending_review", "month_billable"} <= set(d["totals"])
        x = next(p for p in d["providers"] if p["id"] == XENON)
        assert x["patients"] == 2
        assert all(p["id"] != A for p in d["providers"])  # TEST_ names filtered from list

    def test_xenon_detail(self):
        r = api("GET", f"/ledger/providers/{XENON}")
        assert r.status_code == 200
        d = r.json()
        assert len(d["patients"]) == 2 and all(p["services"] for p in d["patients"])
        assert "billing_profile" in d and "promotions" in d and "invoices" in d

    def test_probe_detail_one_patient(self):
        d = api("GET", f"/ledger/providers/{A}").json()
        assert [p["key"] for p in d["patients"]] == [PATIENT_ID]
        assert d["patients"][0]["services"][0]["kind"] == "sos"

    def test_unknown_provider_404(self):
        assert api("GET", "/ledger/providers/nope-0000").status_code == 404


# ── Files ──
class TestFiles:
    def test_reject_txt(self):
        r = upload(A, b"hello", "a.txt", "text/plain")
        assert r.status_code == 400

    def test_reject_over_15mb(self):
        r = upload(A, b"%PDF" + b"0" * (15 * 1024 * 1024 + 10))
        assert r.status_code == 400

    def test_admin_upload_and_stream(self):
        r = upload(A)
        assert r.status_code == 200, r.text
        S["fa"] = r.json()["id"]
        g = api("GET", f"/ledger/files/{S['fa']}")
        assert g.status_code == 200 and g.headers["content-type"].startswith("application/pdf")
        assert g.content[:4] == b"%PDF"

    def test_png_ok_and_query_token(self):
        r = upload(A, open("/app/backend/tests/sample_invoice.png", "rb").read(), "x.png", "image/png")
        assert r.status_code == 200
        g = requests.get(f"{BASE_URL}/api/ledger/files/{r.json()['id']}?token={ST['tok_admin']}", timeout=60)
        assert g.status_code == 200 and g.headers["content-type"].startswith("image/png")

    def test_owner_provider_can_fetch(self):
        assert api("GET", f"/ledger/files/{S['fa']}", h=H_A).status_code == 200

    def test_other_provider_forbidden(self):
        assert api("GET", f"/ledger/files/{S['fa']}", h=H_B).status_code == 403

    def test_provider_upload(self):
        r = upload(None, h=H_A, prov=True)
        assert r.status_code == 200
        S["fa_prov"] = r.json()["id"]
        r = upload(None, h=H_B, prov=True)
        S["fb_prov"] = r.json()["id"]


# ── AI extraction ──
class TestAI:
    def test_ai_extract_bill(self):
        r = api("POST", f"/ledger/ai-extract/{S['fa']}")
        assert r.status_code == 200, r.text
        e = r.json()["extracted"]
        S["ai"] = e
        assert "appendectomy" in (e.get("title") or "").lower()
        assert float(e.get("amount")) == 70000
        assert e.get("category") == "surgery"
        assert len(e.get("line_items") or []) >= 1

    def test_ai_extract_other_provider_forbidden(self):
        assert api("POST", f"/ledger/ai-extract/{S['fa']}", h=H_B).status_code == 403


# ── Services ──
class TestServices:
    def test_missing_proof(self):
        r = api("POST", f"/ledger/providers/{A}/services", json=svc_body([]))
        assert r.status_code == 400 and "proof" in r.text.lower()

    def test_unknown_patient(self):
        r = api("POST", f"/ledger/providers/{A}/services", json=svc_body([S["fa"]], patient_id="no-such"))
        assert r.status_code == 400

    def test_bad_date(self):
        r = api("POST", f"/ledger/providers/{A}/services", json=svc_body([S["fa"]], service_date="10/12/2025"))
        assert r.status_code == 400

    def test_bad_category(self):
        r = api("POST", f"/ledger/providers/{A}/services", json=svc_body([S["fa"]], category="spa"))
        assert r.status_code == 400

    def test_foreign_proof_rejected(self):
        r = api("POST", f"/ledger/providers/{A}/services", json=svc_body([S["fb_prov"]]))
        assert r.status_code == 400

    def test_admin_add_approved(self):
        r = api("POST", f"/ledger/providers/{A}/services", json=svc_body([S["fa"]], source="ai", ai_extracted=S.get("ai")))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "approved" and d["source"] == "ai" and d["amount"] == 70000
        S["svc_admin"] = d["id"]
        det = api("GET", f"/ledger/providers/{A}").json()
        svcs = det["patients"][0]["services"]
        assert any(s["key"] == f"manual:{d['id']}" and s["proofs"] for s in svcs)

    def test_provider_add_pending(self):
        r = api("POST", "/provider/ledger/services", h=H_A,
                json=svc_body([S["fa_prov"]], category="icu_stay", title="TEST_probe ICU", amount=20000))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "pending_review"
        S["svc_p1"] = r.json()["id"]
        r = api("POST", "/provider/ledger/services", h=H_A,
                json=svc_body([S["fa_prov"]], category="implant", title="TEST_probe Implant", amount=5000))
        S["svc_p2"] = r.json()["id"]
        r = api("POST", "/provider/ledger/services", h=H_A,
                json=svc_body([S["fa_prov"]], category="other", title="TEST_probe ToDelete", amount=1))
        S["svc_p3"] = r.json()["id"]

    def test_review_queue(self):
        items = api("GET", "/ledger/review-queue").json()["items"]
        ids = {i["id"] for i in items}
        assert {S["svc_p1"], S["svc_p2"]} <= ids

    def test_reject_needs_reason(self):
        assert api("POST", f"/ledger/services/{S['svc_p2']}/review", json={"action": "reject"}).status_code == 400
        r = api("POST", f"/ledger/services/{S['svc_p2']}/review", json={"action": "reject", "reason": "TEST_probe dup"})
        assert r.status_code == 200 and r.json()["status"] == "rejected"

    def test_approve_with_amount(self):
        r = api("POST", f"/ledger/services/{S['svc_p1']}/review", json={"action": "approve", "amount": 18000})
        assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["amount"] == 18000

    def test_provider_delete_pending_own(self):
        assert api("DELETE", f"/ledger/services/{S['svc_p3']}", h=H_B).status_code == 403
        assert api("DELETE", f"/ledger/services/{S['svc_p3']}", h=H_A).status_code == 200
        assert api("DELETE", f"/ledger/services/{S['svc_p1']}", h=H_A).status_code == 403  # approved

    def test_provider_ledger_view(self):
        r = api("GET", "/provider/ledger", h=H_A)
        assert r.status_code == 200
        d = r.json()
        assert "billing_profile" not in d and "promotions" not in d
        keys = {s["key"] for s in d["patients"][0]["services"]}
        assert f"manual:{S['svc_p1']}" in keys and f"manual:{S['svc_p3']}" not in keys


# ── Promotions / billing / settings ──
class TestConfig:
    def test_promo_add_delete(self):
        r = api("POST", f"/ledger/providers/{A}/promotions", json={"title": "TEST_probe banner", "amount": 5000, "charge_date": SDATE})
        assert r.status_code == 200
        S["promo"] = r.json()["id"]
        r2 = api("POST", f"/ledger/providers/{A}/promotions", json={"title": "TEST_probe del", "amount": 100, "charge_date": SDATE})
        assert api("DELETE", f"/ledger/promotions/{r2.json()['id']}").status_code == 200
        promos = api("GET", f"/ledger/providers/{A}").json()["promotions"]
        assert [p["id"] for p in promos] == [S["promo"]]

    def test_promo_bad(self):
        assert api("POST", f"/ledger/providers/{A}/promotions", json={"title": "TEST_probe", "amount": 0, "charge_date": SDATE}).status_code == 422
        assert api("POST", f"/ledger/providers/{A}/promotions", json={"title": "TEST_probe", "amount": 5, "charge_date": "x"}).status_code == 400

    def test_settings_save(self):
        S["orig_settings"] = api("GET", "/ledger/settings").json()
        body = {**{k: v for k, v in S["orig_settings"].items() if k not in ("id", "updated_at")},
                "legal_name": "Trata Health Pvt. Ltd.", "address": "TEST addr", "state": "Maharashtra",
                "gstin": "27AAAAA0000A1Z5", "bank_name": "HDFC", "default_sac": "998599", "invoice_prefix": "TH",
                "payment_terms_days": 15}
        r = api("PUT", "/ledger/settings", json=body)
        assert r.status_code == 200
        assert api("GET", "/ledger/settings").json()["state"] == "Maharashtra"

    def test_billing_profile(self):
        assert api("PUT", f"/ledger/providers/{A}/billing", json={"fee_pct": 10, "category_fee_pct": {"bogus": 5}}).status_code == 400
        assert api("PUT", f"/ledger/providers/{A}/billing", json={"fee_pct": 101}).status_code == 422
        r = api("PUT", f"/ledger/providers/{A}/billing", json={
            "fee_pct": 10, "category_fee_pct": {"icu_stay": 5}, "legal_name": "TEST_probe Legal",
            "gstin": "27BBBBB0000B1Z5", "state": "maharashtra ", "billing_address": "TEST addr"})
        assert r.status_code == 200
        bp = api("GET", f"/ledger/providers/{A}").json()["billing_profile"]
        assert bp["fee_pct"] == 10 and bp["category_fee_pct"] == {"icu_stay": 5}


# ── Invoices ──
class TestInvoice:
    def test_requires_sac_and_month(self):
        assert api("POST", f"/ledger/providers/{A}/invoices", json={"month": MONTH, "sac_code": "  "}).status_code == 400
        assert api("POST", f"/ledger/providers/{A}/invoices", json={"month": "2025-13", "sac_code": "998599"}).status_code == 400
        assert api("POST", f"/ledger/providers/{A}/invoices", json={"month": "2019-01", "sac_code": "998599"}).status_code == 400

    def test_create_cgst_sgst(self):
        r = api("POST", f"/ledger/providers/{A}/invoices", json={"month": MONTH, "sac_code": "998599"})
        assert r.status_code == 200, r.text
        inv = r.json()
        S["inv"] = inv["id"]
        # 70000*10% + 18000*5% = 7900 + promo 5000 = 12900; GST 2322 split
        assert inv["service_fee"] == 7900 and inv["promotion_fee"] == 5000 and inv["taxable_value"] == 12900
        assert inv["cgst"] == 1161 and inv["sgst"] == 1161 and inv["igst"] == 0
        assert inv["grand_total"] == 15222 and inv["status"] == "issued"
        assert len(inv["lines"]) == 3 and inv["sac_code"] == "998599"

    def test_duplicate_blocked(self):
        assert api("POST", f"/ledger/providers/{A}/invoices", json={"month": MONTH, "sac_code": "998599"}).status_code == 400

    def test_items_locked(self):
        assert api("DELETE", f"/ledger/services/{S['svc_admin']}").status_code == 400
        assert api("DELETE", f"/ledger/promotions/{S['promo']}").status_code == 400
        assert api("POST", f"/ledger/services/{S['svc_p1']}/review", json={"action": "approve", "amount": 1}).status_code == 400

    def test_pdf(self):
        r = api("GET", f"/ledger/invoices/{S['inv']}/pdf")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"

    def test_provider_cannot_see_issued(self):
        assert api("GET", f"/ledger/invoices/{S['inv']}", h=H_A).status_code == 403
        assert api("GET", "/provider/ledger", h=H_A).json()["invoices"] == []

    def test_share(self):
        r = api("POST", f"/ledger/invoices/{S['inv']}/share")
        assert r.status_code == 200 and r.json()["status"] == "shared"
        assert api("GET", f"/ledger/invoices/{S['inv']}", h=H_A).status_code == 200
        assert api("GET", f"/ledger/invoices/{S['inv']}/pdf", h=H_A).status_code == 200
        assert api("GET", f"/ledger/invoices/{S['inv']}", h=H_B).status_code == 403
        assert [i["id"] for i in api("GET", "/provider/ledger", h=H_A).json()["invoices"]] == [S["inv"]]

        async def q():
            c = await asyncpg.connect(DSN, statement_cache_size=0)
            try:
                return await c.fetch("SELECT title FROM public.notifications WHERE user_id=$1 AND notification_type='invoice'", A)
            finally:
                await c.close()
        assert len(asyncio.run(q())) == 1

    def test_paid_then_void_unlocks(self):
        r = api("POST", f"/ledger/invoices/{S['inv']}/status?status=paid")
        assert r.status_code == 200
        assert api("GET", f"/ledger/invoices/{S['inv']}").json()["status"] == "paid"
        assert api("POST", f"/ledger/invoices/{S['inv']}/status?status=bogus").status_code == 400
        assert api("POST", f"/ledger/invoices/{S['inv']}/status?status=void").status_code == 200
        assert api("POST", f"/ledger/invoices/{S['inv']}/status?status=void").status_code == 400
        det = api("GET", f"/ledger/providers/{A}").json()
        m = next(s for s in det["patients"][0]["services"] if s["key"] == f"manual:{S['svc_admin']}")
        assert m["invoice_id"] is None

    def test_reinvoice_igst(self):
        api("PUT", f"/ledger/providers/{A}/billing", json={"fee_pct": 10, "category_fee_pct": {"icu_stay": 5}, "state": "Karnataka"})
        r = api("POST", f"/ledger/providers/{A}/invoices", json={"month": MONTH, "sac_code": "998311"})
        assert r.status_code == 200, r.text
        inv = r.json()
        S["inv2"] = inv["id"]
        assert inv["igst"] == 2322 and inv["cgst"] == 0 and inv["grand_total"] == 15222
        assert inv["number"] != api("GET", f"/ledger/invoices/{S['inv']}").json()["number"]
        assert api("GET", f"/ledger/invoices/{S['inv2']}/pdf").status_code == 200

    def test_restore_settings(self):
        o = S["orig_settings"]
        body = {k: v for k, v in o.items() if k not in ("id", "updated_at")}
        assert api("PUT", "/ledger/settings", json=body).status_code == 200
