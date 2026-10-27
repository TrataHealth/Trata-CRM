"""Insert (or delete) a TEST medicine order for the hospital-pharmacy test store, to exercise the new-order pop-up.
Usage: python3 tests/make_test_order.py [create|cleanup]"""
import asyncio
import json
import sys
import uuid

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")
import supabase_db as sb  # noqa: E402

STORE = "6e4d8e86-8769-4c99-a1ba-37fa9b188cf5"


async def main(cmd: str):
    pool = await sb.get_pool()
    async with pool.acquire() as c:
        if cmd == "cleanup":
            print(await c.execute("DELETE FROM public.medicine_orders WHERE pharmacy_id = $1 AND patient_name LIKE 'TEST_%'", STORE))
            return
        oid = str(uuid.uuid4())
        await c.execute("""INSERT INTO public.medicine_orders (id, order_number, patient_name, patient_phone, pharmacy_id, pharmacy_name, items,
                           delivery_mode, status, timeline, created_at, updated_at, payment_method, is_preorder)
                           VALUES ($1, $2, 'TEST_Alert Patient', '9000000999', $3, 'TEST Hosp Pharmacy', $4::json, 'pickup', 'PENDING_PHARMACY',
                           '[]'::json, now(), now(), 'cash', false)""",
                        oid, "RXT" + oid[:7].upper(), STORE, json.dumps([{"name": "TEST_Dolo 650", "quantity": "2"}]))
        print(oid)


asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "create"))
