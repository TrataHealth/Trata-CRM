"""Deletes test providers onboarded with phones 90000990xx (testing only)."""
import asyncio, os, asyncpg
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
load_dotenv('/app/backend/.env')
T=['hospital_profiles','doctors','paramedic_profiles','ambulance_providers','pharmacy_providers','dental_clinics','nutritionists','wellness_professionals','vet_clinics','blood_banks','ambulance_driver_profiles','wellness_event_providers']
async def m():
    c=await asyncpg.connect(os.environ['DATABASE_URL'], statement_cache_size=0)
    uids=[r[0] for r in await c.fetch("select id from users where phone like '90000990%' or phone like '+9190000990%' or phone_key like '90000990%'")]
    print('users',len(uids))
    for kind,(t,b,fk) in {'d':('diagnostic_centre_profiles','diagnostic_centre_branches','diagnostic_centre_profile_id'),'p':('path_lab_profiles','path_lab_branches','path_lab_profile_id')}.items():
        await c.execute(f"delete from {b} where {fk} in (select id from {t} where user_id = any($1))", uids)
        print(t, await c.execute(f"delete from {t} where user_id = any($1)", uids))
    for t in T: print(t, await c.execute(f"delete from {t} where user_id = any($1)", uids))
    for t in ['kyc_documents','auth_otp_tokens']: await c.execute(f"delete from {t} where user_id = any($1)", uids)
    print(await c.execute("delete from users where id = any($1)", uids))
    db=AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    print((await db.crm_users.delete_many({"phone":{"$regex":"^90000990"}})).deleted_count, (await db.contacts.delete_many({"phone":{"$regex":"^90000990"}})).deleted_count)
asyncio.run(m())
