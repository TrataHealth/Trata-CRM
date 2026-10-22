"""Seed TEST_probe invoices for iter16 UI checks (after ledger_probe_fixtures.py setup). Writes /tmp/ledger_ui_iter16.json"""
import asyncio
import json
import sys
from datetime import timedelta

import asyncpg

sys.path.insert(0, "/app/backend/tests")
from live_probe_fixtures import DSN  # noqa: E402
import test_ledger_receipts_statement as t  # noqa: E402


async def null_emails():
    c = await asyncpg.connect(DSN, statement_cache_size=0)
    await c.execute("UPDATE public.users SET email=NULL WHERE phone = ANY($1::text[])", ["9999900021", "9999900022"])
    await c.close()

asyncio.run(null_emails())
out = {"a1": t.make_invoice(t.A, t.M1, 1000), "a2": t.make_invoice(t.A, t.M2, 2000), "a3": t.make_invoice(t.A, t.MONTH, 3000)}
t.setinv(out["a1"], issue_date=f"{t.M1}-10", due_date=f"{t.M1}-25")
t.setinv(out["a2"], issue_date=f"{t.M2}-10", due_date=(t.TODAY - timedelta(days=4)).isoformat())
t.setinv(out["a3"], due_date=(t.TODAY + timedelta(days=9)).isoformat())
r = t.post(f"/ledger/invoices/{out['a1']}/status?status=paid", json={"paid_on": f"{t.M2}-02", "mode": "cheque", "reference": "TEST_CHQ1"})
assert r.status_code == 200, r.text
out.update(uid_a=t.A, uid_b=t.B, numbers={k: t.inv(v)["number"] for k, v in out.items() if k.startswith("a")},
           totals={k: t.inv(v)["grand_total"] for k, v in out.items() if k.startswith("a")})
json.dump(out, open("/tmp/ledger_ui_iter16.json", "w"))
print(json.dumps(out, indent=1))
