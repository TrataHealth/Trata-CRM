import asyncio, os, sys, json
sys.path.insert(0, "/app/backend")
from dotenv import load_dotenv; load_dotenv("/app/backend/.env")
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import APIRouter
import abdm_share
db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
sent = []
async def respond(path, body): sent.append((path, body)); return True
linked = []
async def main():
    reg = abdm_share.register(APIRouter(), APIRouter(), db, None, None, respond, lambda r: linked.append(r["id"]), asyncio.create_task, None, None, None)
    code = sys.argv[1]
    b = {"intent": "PROFILE_SHARE", "metaData": {"hipId": "IN0910034478", "context": code},
         "profile": {"patient": {"abhaNumber": "91-9999-8888-7777", "abhaAddress": "test.share@sbx", "name": "TEST_Share Patient",
                                 "gender": "F", "yearOfBirth": "1992", "monthOfBirth": "5", "dayOfBirth": "9",
                                 "address": {"line": "1 Test Rd", "district": "Delhi", "state": "Delhi", "pincode": "110001"}, "phoneNumber": "9000011111"}}}
    await reg["process"](b, "req-1"); await reg["process"](b, "req-2")
    b2 = json.loads(json.dumps(b)); b2["profile"]["patient"].update(abhaAddress="test.share2@sbx", abhaNumber="91-9999-8888-7776", name="TEST_Share Two", phoneNumber="9000011112")
    await reg["process"](b2, "req-3")
    await reg["process"]({"metaData": {"context": "NOPE"}, "profile": {"patient": {"abhaAddress": "x@sbx"}}}, "req-4")
    for p, x in sent: print(p, json.dumps(x)[:220])
    print(await db.abdm_profile_shares.find({"counter": code}, {"_id": 0, "token": 1, "name": 1, "share_count": 1, "hospital_patient_id": 1, "save_error": 1}).to_list(10))
asyncio.run(main())
