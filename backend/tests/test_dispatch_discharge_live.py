"""Iter 12 — Ambulance assign/dispatch, hospital discharge summary, live SSE (notifications + payouts).
SHARED PRODUCTION DB: all rows come from live_probe_fixtures (phones 99999000 11/12/13, TEST_probe names).
Fixtures persist in /tmp/live_probe_state.json; run `python live_probe_fixtures.py cleanup` (or PROBE_CLEANUP=1) to wipe.
"""
import asyncio
import json
import os
import queue
import threading
import time
import uuid

import asyncpg
import pytest
import requests

import live_probe_fixtures as F

BASE = F.BASE_URL


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


async def q(sql, *a, fetch="row"):
    c = await asyncpg.connect(F.DSN, statement_cache_size=0)
    try:
        if fetch == "row":
            return await c.fetchrow(sql, *a)
        if fetch == "val":
            return await c.fetchval(sql, *a)
        return await c.execute(sql, *a)
    finally:
        await c.close()


@pytest.fixture(scope="module")
def S():
    if os.path.exists(F.STATE_FILE):
        s = json.load(open(F.STATE_FILE))
    else:
        s = F.setup()
    yield s
    if os.environ.get("PROBE_KEEP") != "1":
        F.cleanup()
        if os.path.exists(F.STATE_FILE):
            os.remove(F.STATE_FILE)


def H(tok):
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


# ── Ambulance assign ────────────────────────────────────────────────────────
class TestAmbulanceAssign:
    def test_non_ambulance_forbidden(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/cases/{S['case_ok']}/assign",
                          json={"ambulance_id": S["veh_a"]}, headers=H(S["tok_hosp"]), timeout=30)
        assert r.status_code == 403, r.text

    def test_case_with_null_provider_rejected(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/cases/{S['case_null']}/assign",
                          json={"ambulance_id": S["veh_a"]}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 400 and r.json()["detail"] == "case_not_sent_to_you", r.text

    def test_case_of_other_provider_rejected(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/cases/{S['case_other']}/assign",
                          json={"ambulance_id": S["veh_a"]}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 400 and r.json()["detail"] == "case_not_sent_to_you", r.text

    def test_closed_case_rejected(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/cases/{S['case_closed']}/assign",
                          json={"ambulance_id": S["veh_a"]}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 400 and r.json()["detail"] == "case_closed", r.text

    def test_foreign_vehicle_rejected(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/cases/{S['case_ok']}/assign",
                          json={"ambulance_id": S["veh_b"]}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 400 and r.json()["detail"] == "ambulance_not_in_fleet", r.text

    def test_unknown_case_400(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/cases/{uuid.uuid4()}/assign",
                          json={"ambulance_id": S["veh_a"]}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 400 and r.json()["detail"] == "case_not_found", r.text

    def test_assign_success_and_db(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/cases/{S['case_ok']}/assign",
                          json={"ambulance_id": S["veh_a"]}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["success"] and d["allocation_id"]
        S["alloc"] = d["allocation_id"]
        a = run(q("SELECT * FROM public.ambulance_allocations WHERE id=$1", d["allocation_id"]))
        assert a["status"] == "assigned" and a["ambulance_id"] == S["veh_a"] and a["ambulance_provider_id"] == S["pa"]
        assert a["allocated_at"] is not None and a["assigned_by"] == S["amb_uid"]
        c = run(q("SELECT status, ambulance_id FROM public.emergency_cases WHERE id=$1", S["case_ok"]))
        assert c["status"] == "AMBULANCE_ASSIGNED" and c["ambulance_id"] == S["veh_a"]

    def test_dashboard_has_allocations(self, S):
        r = requests.get(f"{BASE}/api/provider/pc-dashboard", headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert any(a["id"] == S["alloc"] and a["vehicle_number"] == "TEST-PROBE-VEH_A" for a in d["allocations"])
        rc = {c["id"]: c for c in d["recent_cases"]}
        assert rc[S["case_ok"]]["ambulance_id"] == S["veh_a"]
        assert S["case_null"] not in rc and S["case_other"] not in rc


class TestAllocationStatus:
    def test_invalid_status(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/allocations/{S['alloc']}/status",
                          json={"status": "flying"}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 400 and r.json()["detail"] == "invalid_status"

    def test_other_provider_cannot_update(self, S):
        r = requests.post(f"{BASE}/api/provider/ambulance/allocations/{S['alloc']}/status",
                          json={"status": "dispatched"}, headers=H(S["tok_ambB"]), timeout=30)
        assert r.status_code == 400 and r.json()["detail"] == "allocation_not_found"

    @pytest.mark.parametrize("st,col,case_st", [("dispatched", "dispatched_at", "EN_ROUTE"),
                                               ("arrived", "arrived_at", "ARRIVED"),
                                               ("completed", "completed_at", "COMPLETED")])
    def test_advance(self, S, st, col, case_st):
        r = requests.post(f"{BASE}/api/provider/ambulance/allocations/{S['alloc']}/status",
                          json={"status": st}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 200, r.text
        a = run(q("SELECT * FROM public.ambulance_allocations WHERE id=$1", S["alloc"]))
        assert a["status"] == st and a[col] is not None
        if st == "arrived":
            assert a["response_time_minutes"] is not None and a["response_time_minutes"] >= 0
        c = run(q("SELECT status FROM public.emergency_cases WHERE id=$1", S["case_ok"]))
        assert c["status"] == case_st


# ── Discharge ───────────────────────────────────────────────────────────────
class TestDischarge:
    def test_requires_final_diagnosis(self, S):
        for body in ({}, {"final_diagnosis": "   "}):
            r = requests.post(f"{BASE}/api/hospital/admissions/{S['adm_api']}/discharge",
                              json={"notes": "x", **body}, headers=H(S["tok_hosp"]), timeout=30)
            assert r.status_code == 400 and "Final diagnosis is required" in r.json()["detail"], r.text

    def test_non_hospital_forbidden(self, S):
        r = requests.post(f"{BASE}/api/hospital/admissions/{S['adm_api']}/discharge",
                          json={"final_diagnosis": "x"}, headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 403

    def test_discharge_writes_summary(self, S):
        body = {"final_diagnosis": "TEST_probe Acute gastritis", "condition_at_discharge": "stable",
                "follow_up_instructions": "Review in 7 days", "notes": "IV fluids, PPI"}
        r = requests.post(f"{BASE}/api/hospital/admissions/{S['adm_api']}/discharge",
                          json=body, headers=H(S["tok_hosp"]), timeout=30)
        assert r.status_code == 200, r.text
        sid = r.json()["discharge_summary_id"]
        ds = run(q("SELECT * FROM public.discharge_summaries WHERE id=$1", sid))
        assert ds["admission_id"] == S["adm_api"]
        assert ds["final_diagnosis"] == body["final_diagnosis"]
        assert ds["condition_at_discharge"] == "stable"
        assert ds["follow_up_instructions"] == "Review in 7 days"
        assert ds["treatment_given"] == "IV fluids, PPI"
        assert ds["admission_diagnosis"] == "TEST_probe chest pain"
        adm = run(q("SELECT status, discharge_time FROM public.patient_admissions WHERE id=$1", S["adm_api"]))
        assert adm["status"] == "discharged" and adm["discharge_time"] is not None


# ── Live SSE ────────────────────────────────────────────────────────────────
def _sse_reader(tok, out, stop, seconds=25):
    try:
        with requests.get(f"{BASE}/api/live/stream", params={"token": tok}, stream=True, timeout=(10, seconds + 10)) as r:
            out.put(("status", r.status_code))
            ev = None
            t0 = time.time()
            for line in r.iter_lines(decode_unicode=True):
                if stop.is_set() or time.time() - t0 > seconds:
                    break
                if line and line.startswith("event:"):
                    ev = line[6:].strip()
                elif line and line.startswith("data:"):
                    out.put((ev, json.loads(line[5:].strip())))
    except Exception as e:  # noqa
        out.put(("error", str(e)))


def _collect(out, want, timeout):
    got = []
    end = time.time() + timeout
    while time.time() < end:
        try:
            item = out.get(timeout=0.5)
            got.append(item)
            if want(got):
                break
        except queue.Empty:
            pass
    return got


class TestLive:
    def test_stream_requires_token(self):
        r = requests.get(f"{BASE}/api/live/stream", timeout=15)
        assert r.status_code in (401, 403)

    def test_notifications_list_and_stream_and_read_all(self, S):
        out, stop = queue.Queue(), threading.Event()
        th = threading.Thread(target=_sse_reader, args=(S["tok_amb"], out, stop, 30), daemon=True)
        th.start()
        got = _collect(out, lambda g: any(e == "counters" for e, _ in g), 20)
        assert ("status", 200) in got, got
        init = [d for e, d in got if e == "counters"][0]
        assert "unread" in init and "payouts" in init
        nid = str(uuid.uuid4())
        time.sleep(1)
        run(q("""INSERT INTO public.notifications (id, user_id, title, message, notification_type, is_read, created_at)
                 VALUES ($1,$2,'TEST_probe title','TEST_probe msg','test',FALSE,now())""", nid, S["amb_uid"], fetch="exec"))
        got2 = _collect(out, lambda g: any(e == "notification" for e, _ in g) and any(e == "counters" for e, _ in g), 15)
        stop.set()
        notifs = [d for e, d in got2 if e == "notification"]
        assert any(n["id"] == nid for n in notifs), got2
        cnt = [d for e, d in got2 if e == "counters"]
        assert cnt and cnt[-1]["unread"] == init["unread"] + 1, got2
        r = requests.get(f"{BASE}/api/live/notifications", headers=H(S["tok_amb"]), timeout=30)
        d = r.json()
        assert r.status_code == 200 and any(i["id"] == nid for i in d["items"]) and d["unread"] >= 1
        r = requests.post(f"{BASE}/api/live/notifications/read-all", headers=H(S["tok_amb"]), timeout=30)
        assert r.status_code == 200 and r.json()["updated"] >= 1
        d = requests.get(f"{BASE}/api/live/notifications", headers=H(S["tok_amb"]), timeout=30).json()
        assert d["unread"] == 0 and all(i["is_read"] for i in d["items"])

    def test_payout_event(self, S):
        """No real provider in CRM has provider_id+payouts, so give the TEST_probe ambulance crm_user a
        TEST provider_id, insert a TEST_probe payout doc, assert SSE 'payout' event, then delete."""
        from motor.motor_asyncio import AsyncIOMotorClient
        pid = "TEST_probe_pid_" + S["pa"][:8]

        async def setpid():
            cl = AsyncIOMotorClient(F.ENV["MONGO_URL"])
            await cl[F.ENV["DB_NAME"]].crm_users.update_one({"phone": F.PHONE_AMB}, {"$set": {"provider_id": pid}})
            cl.close()
        run(setpid())
        tok = S["tok_amb"]
        out, stop = queue.Queue(), threading.Event()
        th = threading.Thread(target=_sse_reader, args=(tok, out, stop, 30), daemon=True)
        th.start()
        got = _collect(out, lambda g: any(e == "counters" for e, _ in g), 20)
        init = [d for e, d in got if e == "counters"][0]
        payout_id = "TEST_probe_payout_" + uuid.uuid4().hex[:8]

        async def ins(op):
            cl = AsyncIOMotorClient(F.ENV["MONGO_URL"])
            db = cl[F.ENV["DB_NAME"]]
            if op == "ins":
                await db.payouts.insert_one({"id": payout_id, "provider_id": pid, "status": "pending", "net": 4321,
                                             "period_end": "2026-01-10T00:00:00+00:00", "currency": "INR"})
            else:
                await db.payouts.delete_many({"id": payout_id})
            cl.close()
        time.sleep(1)
        run(ins("ins"))
        try:
            got2 = _collect(out, lambda g: any(e == "payout" for e, _ in g) and any(e == "counters" for e, _ in g), 15)
        finally:
            stop.set()
            run(ins("del"))
        pays = [d for e, d in got2 if e == "payout"]
        assert any(p["id"] == payout_id and p["change"] == "new" and p["net"] == 4321 for p in pays), got2
        cnt = [d for e, d in got2 if e == "counters"]
        assert cnt and cnt[-1]["payouts"] == init["payouts"] + 1
