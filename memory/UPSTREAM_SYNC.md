# Connecting the CRM to the Live TrataHealth Backend

The CRM is built to either run on locally-seeded demo data, **or** mirror your live
Trata-admin (Supabase/Postgres) backend into MongoDB on a 5-minute interval.
The same UI is used in both modes; the topbar badge says either `DEMO DATA` or `LIVE · synced Xm ago`.

## How it works
- Reads from `/api/admin/users`, `/api/admin/recently-onboarded`, `/api/admin/cases`
  on the upstream Trata-admin FastAPI backend.
- Maps:
  - upstream `User.role` → CRM `contact.type` (`customer→patient`, `doctor`, `paramedic`, `hospital`, `ambulance_provider`, `pathologist`)
  - upstream `verification_status` → CRM `is_verified` and `pipeline_stage`
  - upstream `EmergencyCase` → CRM `activity` (category `emergency_case`)
- Local-only fields preserved: **tasks, notes, pipeline_stage overrides done in CRM, team members**.
- On every sync, contacts + activities + notifications are wiped and replaced with the live data; the CRM's tasks/notes/team are NOT touched.

## To activate

Edit `/app/backend/.env`:

```env
UPSTREAM_API_URL=https://api.tratahealth.com           # your deployed Trata-admin FastAPI base URL
UPSTREAM_ADMIN_TOKEN=eyJhbGciOi...                     # OPTIONAL: paste a long-lived admin JWT
# --- OR --- let the CRM auto-login on each cycle:
UPSTREAM_LOGIN_PHONE=9873117605
UPSTREAM_LOGIN_OTP=123456
UPSTREAM_SYNC_INTERVAL_MIN=5
```

Then restart the backend:

```bash
sudo supervisorctl restart backend
```

The badge will flip to **LIVE** within a few seconds.
You can also press the **Sync** button in the top bar to trigger an immediate refresh.

## Endpoints (CRM side)
- `GET  /api/admin/sync/status` — returns mode (`live` | `seeded`), last sync timestamp, counts.
- `POST /api/admin/sync/run` — master admin only; runs sync immediately.

## Troubleshooting
- 401 from upstream: token expired → set `UPSTREAM_LOGIN_PHONE` + `UPSTREAM_LOGIN_OTP` so the CRM re-logs in.
- 0 contacts after sync: the upstream `/api/admin/users` returned nothing — verify endpoints respond with the JSON shape `{ users: [...], total: N }`.
- Falls back to demo seed automatically if upstream returns empty on first boot.
