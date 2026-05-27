# TrataHealth Master Admin CRM — PRD

## Original Problem Statement
User shared `https://github.com/TrataHealth` (existing healthcare emergency platform — SanjeevaniX) and asked for a full-fledged CRM at the master admin level with a detailed outlook of activities happening across the app. Same master-admin phone+OTP login flow as their existing admin app. Follow-up: connect to live TrataHealth Supabase/Postgres DB via the existing Trata-admin FastAPI backend as upstream.

## Personas
- **Master Admin** — full control over contacts, pipeline, activities, tasks, team & roles, AI insights.
- **Manager / Sales Rep / Ops Rep** — added by master admin (role-based label only in v1).

## Architecture
- **Backend** — FastAPI (single `server.py`) + `upstream_sync.py`, MongoDB via Motor, JWT auth (PyJWT). Anthropic Claude Sonnet via Emergentintegrations. `httpx` for upstream calls.
- **Frontend** — React 19 + Tailwind + Shadcn primitives + Recharts + lucide-react. Custom Chivo (headings) + IBM Plex Sans (body) typography. Swiss high-contrast design.
- **DB** — `tratacrm_db` (MongoDB local). Collections: `contacts`, `activities`, `tasks`, `notes`, `notifications`, `crm_users` (team), `sync_status`.
- **Live Sync** — controlled by `UPSTREAM_API_URL` env var. When set, the CRM hits `/api/admin/users`, `/api/admin/recently-onboarded`, `/api/admin/cases` on the existing Trata-admin backend, maps the data into CRM shape, and writes to MongoDB. Background loop refreshes every `UPSTREAM_SYNC_INTERVAL_MIN` minutes (default 5).

## Auth
- `POST /api/auth/send-otp` (mock; always returns success).
- `POST /api/auth/verify-otp` — accepts master admin phone (`9873117605`) with OTP `123456`. Other phones must already exist in `crm_users`.
- All other endpoints require `Authorization: Bearer <jwt>`.

## What's Implemented

### Iteration 1 (2026-05-27) — MVP
- Login (split-screen).
- Dashboard with KPIs, user-type tiles, 14-day velocity, activity-mix donut, pipeline bar, live activity feed.
- Contacts module (filter by type/stage/verified, search, CSV export).
- Contact Detail (AI panel, activity/tasks/notes tabs, inline note creation, stage/verification edit).
- Pipeline Kanban with drag-and-drop across 6 stages.
- Activities module (categories: emergency cases, appointments, ambulance bookings, lab bookings, pathology bookings, KYC).
- Tasks (CRUD + assignment).
- Analytics (cases by status, response-time histogram, 30-day revenue, top cities).
- Team & Roles management.
- Global search.
- AI Insights via Claude Sonnet 4.6.
- Auto-seed on first boot: 182 contacts, ~520 activities, 25 tasks.
- 33/33 backend tests passed, full frontend E2E verified.

### Iteration 2 (2026-05-27) — Live upstream sync
- `upstream_sync.py` module with `UpstreamSync` class.
- Endpoints: `GET /api/admin/sync/status`, `POST /api/admin/sync/run`.
- Background task: refreshes every `UPSTREAM_SYNC_INTERVAL_MIN` minutes when `UPSTREAM_API_URL` is set.
- Top-bar `DataSourceBadge` shows `DEMO DATA` (yellow) or `LIVE · synced Xm ago` (green) with a manual **Sync** button.
- Auto-login to upstream via OTP if `UPSTREAM_LOGIN_PHONE`/`UPSTREAM_LOGIN_OTP` provided; or static `UPSTREAM_ADMIN_TOKEN`.
- Falls back to demo seed if upstream returns no data on first boot.
- Activation guide: `/app/memory/UPSTREAM_SYNC.md`.
- Sync mapping verified end-to-end with a mocked upstream (5 users + 1 case mapped correctly).

## Backlog / Next Tasks
- **P1** Sync appointments / lab bookings / ambulance bookings from upstream (add endpoints in CRM mapper when corresponding admin endpoints are exposed by Trata-admin).
- **P1** Hook real-time activity stream (WebSocket from SanjeevaniX backend) — push new emergency cases the moment they're created instead of waiting 5 min.
- **P2** Map view for active emergency cases (geographic heatmap).
- **P2** Email/WhatsApp send from the AI "Draft message" panel.
- **P2** SLA / response-time alerts (auto-create high-priority task when paramedic not assigned in N mins).
- **P2** Bulk actions on the contacts table (assign, change stage, message).
- **P3** Custom dashboards / saved views per user.
- **P3** Audit log of admin actions.

## Notes / Mocks
- OTP is MOCKED — any send-otp returns success; verify only accepts `123456` for master admin.
- Until `UPSTREAM_API_URL` is filled in `/app/backend/.env`, the CRM operates on SEEDED mirror data; badge says `DEMO DATA`.
- AI uses Emergent LLM key (Claude Sonnet 4.6) — already configured.
