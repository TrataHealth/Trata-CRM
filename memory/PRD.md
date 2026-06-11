# TrataHealth CRM — PRD

## Original Problem Statement
User shared `https://github.com/TrataHealth` (healthcare emergency platform — SanjeevaniX) and asked for a full-fledged CRM at the master-admin level. Then asked to evolve into a multi-tenant activity tracker for providers (phone+OTP+password as the unique key), then pivoted again to make the CRM a **Sales Agent driver tool** for onboarding healthcare providers (Ambulance fleet partners) onto the Trata Provider App.

## Personas
- **Master Admin / Manager** — full network view + Leaderboard.
- **Sales Agent (sales_rep)** — primary persona. Onboards ambulance providers.
- **Provider Owner (Ambulance)** — sees only their own fleet, earnings, KYC.

## Architecture
- **Backend** — FastAPI (`/app/backend/server.py` ~1949 lines) + `upstream_sync.py`, MongoDB (Motor), JWT (PyJWT) access (30d) + temp (10m) tokens, bcrypt password hashing. Anthropic Claude (Sonnet 4.6) via `emergentintegrations` for AI digest.
- **Frontend** — React 19 + Tailwind + Shadcn UI + Recharts + lucide-react + react-leaflet. 3-step login (phone → OTP → password). Role-aware sidebar/router. PWA-installable.
- **DB** — `tratacrm_db`. Collections: `contacts`, `activities`, `tasks`, `notes`, `notifications`, `crm_users`, `sync_status`, `targets`, `fleet`.

## Auth (3-step)
1. `POST /api/auth/send-otp {phone}` — mock; only `123456` accepted
2. `POST /api/auth/verify-otp {phone, otp}` → `{temp_token, needs_password_setup, user}`
3a. `POST /api/auth/set-password` (first time) or `POST /api/auth/login-password` (returning) with `Authorization: Bearer <temp_token>`

## What's Implemented

### Iter 1 (2026-05-27) — Master-admin CRM MVP
Login, Dashboard, Contacts, Pipeline, Activities, Tasks, Analytics, Team, AI insights, seeded data, mobile responsive. 33/33 tests pass.

### Iter 2 (2026-05-27) — Live upstream sync
`upstream_sync.py` + `/api/admin/sync/*` + DataSourceBadge. Activates via `UPSTREAM_API_URL`.

### Iter 3 (2026-06-01) — Mobile UX + PWA
Hamburger drawer, condensed top bar, Kanban horizontal-scroll, manifest + service worker + install prompt.

### Iter 4 (2026-06-01) — Multi-tenant provider portal
Roles `admin / manager / sales_rep / ops_rep / provider_owner` + `provider_type` + `provider_id`. Scope filters on all endpoints. Provider dashboard with type-themed KPIs.

### Iter 5 (2026-06-01) — Earnings & Payouts
`/api/provider/earnings`, `/api/provider/payouts`, `/api/provider/invoice/{id}`. 15% platform fee. Weekly Monday payouts. PDF invoice download.

### Iter 6 (2026-06-08) — Scope narrowed to Ambulance only
Removed Hospital/Clinic/Pathology provider portals. Live Fleet Map (Leaflet) added (`/provider`).

### Iter 7 (2026-06-10) — Sales Agent pivot
- `AgentDashboard` (`/agent`) with KPI strip, funnel by stage, map of my leads, today's tasks, hot/stale lead cards.
- `QuickLogModal` — typed activities (cold_call, pitch_meeting, site_visit, demo, kyc_collection, app_training, follow_up, whatsapp, email, note) + outcome-driven stage auto-advance.
- New endpoints: `/api/agent/dashboard`, `/api/agent/leads`, `/api/agent/leads/map`, `/api/agent/quick-log`.
- New seed: 3 sales agents (Rohan / Priya manager / one more), leads assigned, activities seeded.

### Iter 8 (2026-06-11) — Phase 8 Agent toolkit (current)
- `/agent/leads` — full filterable My Leads list page (search, stage, type, last-touched filters).
- `/agent/leaderboard` — admin/manager-only monthly leaderboard (calls/meetings/onboarded/leads).
- **AI Digest** — `POST /api/agent/digest` (Claude Sonnet) renders end-of-day workday summary card on AgentDashboard.
- **GPS Check-in** — Browser Geolocation API capture inside QuickLogModal, shown only for `site_visit` activities. Persisted as `activity.gps {lat,lng}`.
- **Targets** — `GET /api/agent/targets` returns month-to-date actuals vs targets.
- Tested: 23/23 backend pytest + 17/17 frontend playwright (after fixing /agent route guard).

### Iter 9 (2026-06-11) — Phase 5 Provider-App webhook bridge
- New: `POST /api/webhooks/provider-app` — HMAC-SHA256 signed (`X-Trata-Signature` header, `PROVIDER_WEBHOOK_SECRET` in `.env`).
- Events: `provider.signed_up` → stage `verified`; `provider.first_use` → stage `active`.
- Match by normalized phone (strips +91/spaces). Unknown phone → auto-create lead, assign by territory round-robin (Rohan: Delhi/Gurugram/Noida; Priya: Mumbai/Bengaluru/Pune; fallback: global RR).
- Logs activity `category='webhook_sync'` + `webhook_events` collection. Bad signatures → 401 + rejected event recorded.
- Admin-only endpoints: `GET /api/admin/webhooks/events` + `POST /api/admin/webhooks/test-send` (admin/manager only; sales_rep gets 403).
- Frontend: `WebhookBridgePanel` on Master Dashboard with signed test sender + live event feed.
- Tested: 22/22 backend pytest + 100% frontend playwright (after tightening role guard).

## Backlog / Next

### P1
- **Phase 5 — Provider-App bridge**: Webhook from Trata Provider App that auto-advances pipeline stage to `verified` / `active` when an onboarded provider signs up on the app.
- Federate OTP through live Trata-admin backend (`UPSTREAM_API_URL`).
- Voice notes on QuickLogModal (skipped this iteration per user choice).

### P2
- **Phase 6 — KYC docs upload**: Attach PDFs/images per lead, admin review + approval flow.
- **Phase 9 — Manager intelligence**: Funnel conversion per agent, time-in-stage, stale-lead alerts, territory heat-map, AI coaching nudges.
- Offline PWA queue for quick-log when network drops.
- Push notifications for stale leads / today's tasks.

### P3
- Split `server.py` into `routers/{auth,agent,provider,admin}.py` + `db/seed.py`.
- Defensive try/catch in AgentDashboard.load() against transient 403s.
- Pydantic GPS sub-model for stricter quick-log validation.

## Notes / Mocks
- OTP is MOCKED — only `123456` works.
- Provider data is SEEDED — set `UPSTREAM_API_URL` to mirror live.
- AI uses Emergent LLM key (Claude Sonnet 4.6) for `/api/agent/digest`.

## Critical seed
- Master Admin `9873117605` (needs first-time pw set).
- Sales Agent (Rohan) `9000000002` · `Trata@123`.
- Sales Manager (Priya) `9000000001` · `Trata@123`.
- Ambulance Owner `9000020003` · `Trata@123`.
