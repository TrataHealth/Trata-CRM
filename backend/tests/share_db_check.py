# Verify Scan & Share side-effects in Supabase hospital_patients + Mongo abha_records; also matching by phone+name
import asyncio, os, sys, json
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from datetime import datetime, timedelta, timezone
from motor.motor_asyncio import AsyncIOMotorClient
import supabase_db as sb
import abdm_share
HID = "7254d4be-941d-4999-a5e3-c04664ab3a6e"
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

async def rows(conn):
    return await conn.fetch("SELECT id, name, status, phone, age, sex, abha_number, abha_address, abha_kyc IS NOT NULL kyc, address FROM public.hospital_patients WHERE hospital_id=$1 AND name LIKE 'TEST_Share%' ORDER BY created_at", HID)

async def main():
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        for r in await rows(conn): print("HP", dict(r))
    for r in await db.abha_records.find({"abha_address": {"$regex": "^test\\..*@sbx$"}}, {"_id": 0, "owner": 1, "abha_number": 1, "abha_address": 1, "last_verified_via": 1, "created_via": 1}).to_list(10):
        print("AR", r)
    print("SEQ", await db.abdm_share_seq.find({"_id": {"$regex": "^THJ7J8LG"}}).to_list(5))
    # phone+name match with no abha number and new address
    if len(sys.argv) > 1:
        rid = await abdm_share._upsert_hospital_patient(HID, {"name": "TEST_Share Two", "phoneNumber": "9000011112", "abhaAddress": "test.share3@sbx", "gender": "F", "yearOfBirth": "1990"}, None, None)
        print("MATCH id", rid)
        async with pool.acquire() as conn:
            for r in await rows(conn): print("HP2", dict(r))

asyncio.run(main())
