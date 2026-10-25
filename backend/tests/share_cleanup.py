# Cleanup TEST_ Scan & Share data (Supabase hospital_patients + Mongo)
import asyncio, os, sys
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient
import supabase_db as sb
HID = "7254d4be-941d-4999-a5e3-c04664ab3a6e"
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

async def main():
    pool = await sb.get_pool()
    async with pool.acquire() as conn:
        print("HP deleted:", await conn.execute("DELETE FROM public.hospital_patients WHERE hospital_id=$1 AND name LIKE 'TEST_Share%'", HID))
    rx = {"$regex": "^test\\..*@sbx$"}
    print("shares:", (await db.abdm_profile_shares.delete_many({"counter": "THJ7J8LG", "abha_address": rx})).deleted_count)
    print("abha_records:", (await db.abha_records.delete_many({"abha_address": rx})).deleted_count)
    print("seq:", (await db.abdm_share_seq.delete_many({"_id": {"$regex": "^THJ7J8LG:"}})).deleted_count)

asyncio.run(main())
