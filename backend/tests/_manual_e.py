import asyncio
import os
import time

import asyncpg
from dotenv import load_dotenv

from _login_helper import B, login

load_dotenv('/app/backend/.env')


async def q(sql, *a):
    c = await asyncpg.connect(os.environ['DATABASE_URL'], statement_cache_size=0)
    try:
        return await c.fetch(sql, *a)
    finally:
        await c.close()


s = login('9873117605', 'Master@123')
print(s.post(B + '/api/admin/sales-leads/backfill').json())
time.sleep(25)
print([tuple(x) for x in asyncio.run(q('select pipeline_stage,source,count(*) from crm_sales_leads group by 1,2 order by 3 desc'))])
print('due', s.get(B + '/api/sales/followups-due').json())
print('bad stage', s.patch(B + '/api/contacts/x', json={'pipeline_stage': 'bogus'}).status_code)
