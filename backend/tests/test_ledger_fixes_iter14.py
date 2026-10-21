"""Provider Ledger iter-14 retest: race-safe invoicing, billable statuses, review guard, promo double-delete,
GST state-code logic + place_of_supply. Uses TEST_probe hospital A, month 2025-11 (main suite uses 2025-12).
Pre: `python ledger_probe_fixtures.py setup`."""
import concurrent.futures as cf
import json

import requests

from live_probe_fixtures import BASE_URL
from ledger_probe_fixtures import PATIENT_ID, STATE_FILE

ST = json.load(open(STATE_FILE))
XENON = "2d71f195-7f5a-454b-962d-ee944cebe8cf"
A = ST["uid_a"]
H_ADM = {"Authorization": f"Bearer {ST['tok_admin']}"}
H_A = {"Authorization": f"Bearer {ST['tok_a']}"}
MONTH, SDATE = "2025-11", "2025-11-05"
S = {}


def api(m, path, h=H_ADM, **kw):
    return requests.request(m, f"{BASE_URL}/api{path}", headers=h, timeout=120, **kw)


def inv_post(sac="998599"):
    return api("POST", f"/ledger/providers/{A}/invoices", json={"month": MONTH, "sac_code": sac})


# ── Billable statuses (Xenon PENDING_HOSPITAL consultations) ──
class TestBillable:
    def test_xenon_rows_not_billable(self):
        d = api("GET", f"/ledger/providers/{XENON}").json()
        svcs = [s for p in d["patients"] for s in p["services"]]
        assert svcs and all(s["billable"] is False for s in svcs if s.get("status") == "PENDING_HOSPITAL")
        assert all(p["total_amount"] == 0 for p in d["patients"])

    def test_xenon_month_billable_zero(self):
        for m in ("2026-08", "2026-10"):
            x = next(p for p in api("GET", f"/ledger/providers?month={m}&fresh=true").json()["providers"] if p["id"] == XENON)
            assert x["month_auto_amount"] == 0 and x["month_billable"] == 0, (m, x)

    def test_xenon_invoice_nothing_billable(self):
        r = api("POST", f"/ledger/providers/{XENON}/invoices", json={"month": "2026-10", "sac_code": "998599"})
        if r.status_code == 200:  # cleanup if bug
            api("POST", f"/ledger/invoices/{r.json()['id']}/status?status=void")
        assert r.status_code == 400 and "Nothing billable" in r.text, r.text


# ── Setup data + review guard + promo double delete ──
class TestGuards:
    def test_setup_service_and_promo(self):
        f = api("POST", f"/ledger/providers/{A}/files",
                files={"file": ("b.pdf", open("/app/backend/tests/sample_bill.pdf", "rb").read(), "application/pdf")})
        assert f.status_code == 200, f.text
        S["fid"] = f.json()["id"]
        r = api("POST", f"/ledger/providers/{A}/services", json={
            "patient_id": PATIENT_ID, "category": "surgery", "title": "TEST_probe14 Surgery", "service_date": SDATE,
            "amount": 10000, "proof_file_ids": [S["fid"]]})
        assert r.status_code == 200 and r.json()["status"] == "approved"
        S["svc"] = r.json()["id"]
        S["patient_on_svc"] = r.json().get("patient_name") or r.json().get("patient_phone")
        r = api("POST", f"/ledger/providers/{A}/promotions", json={"title": "TEST_probe14 promo", "amount": 1000, "charge_date": SDATE})
        assert r.status_code == 200
        S["promo"] = r.json()["id"]

    def test_review_non_pending_400(self):
        r = api("POST", f"/ledger/services/{S['svc']}/review", json={"action": "approve"})
        assert r.status_code == 400 and "pending" in r.text.lower()
        # provider-submitted → reject → re-approve blocked
        p = api("POST", "/provider/ledger/files", h=H_A,
                files={"file": ("b.pdf", open("/app/backend/tests/sample_bill.pdf", "rb").read(), "application/pdf")})
        sv = api("POST", "/provider/ledger/services", h=H_A, json={
            "patient_id": PATIENT_ID, "category": "other", "title": "TEST_probe14 pend", "service_date": "2025-10-01",
            "amount": 5, "proof_file_ids": [p.json()["id"]]}).json()
        assert api("POST", f"/ledger/services/{sv['id']}/review", json={"action": "reject", "reason": "TEST"}).status_code == 200
        assert api("POST", f"/ledger/services/{sv['id']}/review", json={"action": "approve"}).status_code == 400

    def test_promo_double_delete_400(self):
        r = api("POST", f"/ledger/providers/{A}/promotions", json={"title": "TEST_probe14 del", "amount": 5, "charge_date": "2025-10-02"})
        pid = r.json()["id"]
        assert api("DELETE", f"/ledger/promotions/{pid}").status_code == 200
        assert api("DELETE", f"/ledger/promotions/{pid}").status_code == 400


# ── Concurrency + GST state code ──
class TestInvoiceRace:
    def test_settings_maharashtra(self):
        S["orig"] = api("GET", "/ledger/settings").json()
        body = {**{k: v for k, v in S["orig"].items() if k not in ("id", "updated_at")},
                "address": S["orig"].get("address") or "TEST", "state": "Maharashtra", "gstin": "27AAAAA0000A1Z5"}
        assert api("PUT", "/ledger/settings", json=body).status_code == 200

    def test_concurrent_create_exactly_one(self):
        # Buyer: GSTIN 27 but state text says Karnataka → GSTIN code wins → same state (CGST/SGST)
        api("PUT", f"/ledger/providers/{A}/billing", json={"fee_pct": 10, "gstin": "27BBBBB0000B1Z5", "state": "Karnataka"})
        with cf.ThreadPoolExecutor(6) as ex:
            rs = list(ex.map(lambda _: inv_post(), range(6)))
        codes = sorted(r.status_code for r in rs)
        ok = [r.json() for r in rs if r.status_code == 200]
        S["all_ids"] = [o["id"] for o in ok]
        assert codes.count(200) == 1 and codes.count(400) == 5, codes
        inv = ok[0]
        S["inv"] = inv["id"]
        assert inv["service_fee"] == 1000 and inv["promotion_fee"] == 1000 and inv["taxable_value"] == 2000
        assert inv["cgst"] == 180 and inv["sgst"] == 180 and inv["igst"] == 0
        assert inv["place_of_supply"] == "Maharashtra (27)"
        lines = inv["lines"]
        assert len(lines) == 2 and all(ln["patient"] for ln in lines)
        svc_line = next(ln for ln in lines if ln["type"] == "service")
        assert svc_line["patient"] != "—", svc_line

    def test_db_single_active(self):
        items = [i for i in api("GET", f"/ledger/invoices?month={MONTH}").json()["items"] if i["provider_user_id"] == A]
        assert len([i for i in items if i["status"] != "void"]) == 1, items

    def test_pdf_place_of_supply(self):
        r = api("GET", f"/ledger/invoices/{S['inv']}/pdf")
        assert r.status_code == 200 and r.content[:4] == b"%PDF"

    def test_void_then_reinvoice_state_name_igst(self):
        assert api("POST", f"/ledger/invoices/{S['inv']}/status?status=void").status_code == 200
        # No GSTIN, state name Karnataka → code 29 ≠ 27 → IGST
        api("PUT", f"/ledger/providers/{A}/billing", json={"fee_pct": 10, "gstin": "", "state": "Karnataka"})
        r = inv_post()
        assert r.status_code == 200, r.text
        inv = r.json()
        S["inv2"] = inv["id"]
        assert inv["igst"] == 360 and inv["cgst"] == 0 and inv["place_of_supply"] == "Karnataka (29)"

    def test_state_name_same_state(self):
        assert api("POST", f"/ledger/invoices/{S['inv2']}/status?status=void").status_code == 200
        api("PUT", f"/ledger/providers/{A}/billing", json={"fee_pct": 10, "gstin": "", "state": "Maharashtra"})
        r = inv_post()
        assert r.status_code == 200, r.text
        inv = r.json()
        assert inv["cgst"] == 180 and inv["igst"] == 0
        api("POST", f"/ledger/invoices/{inv['id']}/status?status=void")

    def test_restore_settings(self):
        body = {k: v for k, v in S["orig"].items() if k not in ("id", "updated_at")}
        assert api("PUT", "/ledger/settings", json=body).status_code == 200
