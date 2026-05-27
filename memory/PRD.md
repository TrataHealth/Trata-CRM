# TrataHealth Master Admin CRM — PRD

## Original Problem Statement
User shared `https://github.com/TrataHealth` (existing healthcare emergency platform — SanjeevaniX) and asked for a full-fledged CRM at the master admin level with a detailed outlook of activities happening across the app. Same master-admin phone+OTP login flow as their existing admin app.

## Personas
- **Master Admin** — full control over contacts, pipeline, activities, tasks, team & roles, AI insights.
- **Manager / Sales Rep / Ops Rep** — added by master admin (role-based label only in v1).

## Architecture
- **Backend** — FastAPI (single `server.py`), MongoDB via Motor, JWT auth (PyJWT). Anthropic Claude Sonnet via Emergentintegrations.
- **Frontend** — React 19 + Tailwind + Shadcn primitives + Recharts + lucide-react. Custom Chivo (headings) + IBM Plex Sans (body) typography. Swiss high-contrast design.
- **DB** — `tratacrm_db` (MongoDB local). Collections: `contacts`, `activities`, `tasks`, `notes`, `notifications`, `crm_users` (team).

## Auth
- `POST /api/auth/send-otp` (mock; always returns success).
- `POST /api/auth/verify-otp` — accepts master admin phone (`9873117605`) with OTP `123456`. Other phones must already exist in `crm_users` (added by master admin).
- All other endpoints require `Authorization: Bearer <jwt>`.

## What's Implemented (2026-05-27)
- **Login** (split-screen hero + form, prefilled with master admin creds for demo).
- **Dashboard** — 4 KPIs (Users, Active Cases, Revenue, Open Tasks), 6 user-type tiles, 14-day platform velocity area chart, activity-mix donut, pipeline horizontal bar, live activity feed.
- **Contacts** — paginated/filterable table across all 6 user types (Patients, Doctors, Hospitals, Paramedics, Ambulance Providers, Pathology Labs). Type tabs, stage filter, status filter, search, CSV export.
- **Contact Detail** — header card with quick stage / verification edit, gradient AI Insights panel (Summarize / Next action / Draft message via Claude Sonnet 4.6), Activity / Tasks / Notes tabs, inline note creation.
- **Pipeline (Kanban)** — 6 stages (lead → contacted → kyc_submitted → verified → active → churned), drag-and-drop between columns, only providers shown.
- **Activities** — list view across emergency cases / appointments / ambulance bookings / lab bookings / pathology bookings / KYC; category chip filters, status colors, amount, drill-through to contact.
- **Tasks** — inline create form (title/assignee/priority/due), tabs (all/open/in_progress/done), inline status change, delete.
- **Analytics** — Cases by status (bar), response-time distribution (bar), 30-day revenue trend (area), top cities list.
- **Team & Roles** — add/list/remove members with admin/manager/sales_rep/ops_rep roles (master admin cannot be removed).
- **Global Search** — top bar searches contacts + activities + tasks with live dropdown.
- **AI Insights** — Claude Sonnet 4.6 via Emergent LLM key (graceful fallback on errors).
- **Seeding** — auto-seeds on first boot with 182 contacts, ~520 activities, 25 tasks, 15 notifications using realistic Indian names, cities, healthcare schema modeled after `TrataHealth/Trata-admin`.
- **All interactive elements** have `data-testid`.

## Tested
- Backend: 33/33 pytest pass (auth, dashboard, contacts CRUD+filters, pipeline, activities filters, tasks CRUD, notes, team, analytics, CSV export, search, AI insight).
- Frontend: login → dashboard → contacts → detail → AI button → pipeline → activities → tasks → analytics → team → search → logout — all verified by testing subagent.

## Backlog / Next Tasks
- **P1** Connect to the live Supabase/Postgres TrataHealth DB (currently uses standalone MongoDB with seeded mirror data). Likely via the existing Trata-admin backend as an upstream API.
- **P1** Hook real-time activity stream (WebSocket) from the SanjeevaniX backend.
- **P2** Map view for emergency cases (geographic heatmap).
- **P2** Email integration to actually send Claude-drafted messages.
- **P2** SLA / response-time alerts (push when > X mins).
- **P2** Bulk actions on the contacts table (assign, change stage).
- **P3** Custom dashboards / saved views per user.
- **P3** Audit log of admin actions.

## Notes / Mocks
- OTP is MOCKED — any send-otp returns success; verify only accepts `123456` for the master admin phone.
- Activity data is currently SEEDED — not pulled live from the existing TrataHealth Supabase DB.
- AI uses Emergent LLM key (Claude Sonnet 4.6) — already configured.
