# TrataHealth Master Admin CRM + Provider Portal — PRD

## Original Problem Statement
User shared `https://github.com/TrataHealth` (healthcare emergency platform — SanjeevaniX) and asked for a full-fledged CRM at the master-admin level. Then asked to evolve it into a multi-tenant activity tracker so Ambulance / Clinic / Hospital / Pathology owners can each log in and see only their own world, with phone + OTP + password as the unique key linking this CRM to the Trata Provider app.

## Personas
- **Master Admin** — full network view.
- **Internal team** (Manager / Sales Rep / Ops Rep) — full read-only / pipeline control across providers.
- **Provider Owner** (NEW) — Hospital / Clinic / Ambulance / Pathology owner; sees ONLY their own contact, activities, KYC, and a type-tailored dashboard.

## Architecture
- **Backend** — FastAPI (`server.py`) + `upstream_sync.py`, MongoDB via Motor, JWT (PyJWT) with **access** (30d) + **temp** (10m) token types, bcrypt password hashing, server-side scope filter on every endpoint. Anthropic Claude Sonnet via Emergentintegrations.
- **Frontend** — React 19 + Tailwind + Recharts + lucide-react. 3-step login (phone → OTP → password). Role-aware sidebar / router. PWA-installable. Service worker registered in production.
- **DB** — `tratacrm_db`. Collections: `contacts`, `activities` (with `provider_ids` array linking to providers), `tasks`, `notes`, `notifications`, `crm_users` (now with `role`, `provider_type`, `provider_id`, `password_hash`), `sync_status`.

## Auth (3-step)
1. `POST /api/auth/send-otp {phone}` → mock OK
2. `POST /api/auth/verify-otp {phone, otp}` → `{temp_token, needs_password_setup, user}` (or 400/403)
3a. First time: `POST /api/auth/set-password {password}` with `Authorization: Bearer <temp>`
3b. Returning: `POST /api/auth/login-password {password}` with `Authorization: Bearer <temp>`
→ returns final access JWT + user.

## What's Implemented

### Iteration 1 (2026-05-27) — MVP
Login, Dashboard, Contacts/Detail, Pipeline, Activities, Tasks, Analytics, Team, AI insights, auto-seeded data, mobile-responsive.

### Iteration 2 (2026-05-27) — Live upstream sync
`upstream_sync.py` + `/api/admin/sync/*` endpoints + `DataSourceBadge` UI. Activates via `UPSTREAM_API_URL` env var.

### Iteration 3 (2026-06-01) — Mobile UX + PWA
Hamburger drawer, condensed top bar, horizontal-scroll Kanban, manifest.json + service worker + install prompt (Chrome banner + iOS Add-to-Home tip).

### Iteration 4 (2026-06-01) — Multi-tenant provider portal ✨
- **Roles**: `admin` / `manager` / `sales_rep` / `ops_rep` / `provider_owner`. New `provider_type` (`hospital|clinic|ambulance|pathology`) + `provider_id` linkage.
- **Auth**: 3-step phone+OTP+password; bcrypt; access vs temp token types.
- **Scope enforcement**: `require_internal` dep on admin endpoints (`/dashboard/*`, `/pipeline`, `/team`, `/analytics/*`, `/export/*`, `PATCH /contacts/{id}`, `/admin/*`). Scope filter on `/contacts` (provider sees only self), `/activities` (only where `provider_ids` contains their id), `/search` (results filtered), `/contacts/{id}` (403 if not owner), `/activities/{id}` (403 if not linked).
- **Provider endpoints**: `GET /api/provider/me`, `GET /api/provider/dashboard` (with type-tailored extras), `GET /api/provider/activities`.
- **Provider Dashboard UI**: type-themed gradient banner, 4 generic KPIs, type-specific cards:
  - Hospital → beds (available/total) + occupancy bar + incoming ambulances
  - Ambulance → fleet size + avg response time + live trips + completed trips
  - Clinic → appointments today + no-show rate
  - Pathology → pending bookings / samples collected / reports ready
  - 14-day activity area chart, activity-mix donut, live feed (30-sec polling).
- **Provider Activities** page — scoped table with category filters.
- **Provider Profile & KYC** page — verified/pending badge, meta grid (license, beds/fleet/experience…), KYC history timeline.
- **Role-aware Layout/Sidebar** — provider sees only 4 nav items; admin sees 7. DataSourceBadge hidden for providers.
- **Route guards** — provider hitting `/contacts`/`/pipeline`/etc. → redirect to `/provider`. Admin hitting `/provider` → redirect to `/`.
- **Seed** — 4 demo provider owners with `password=Trata@123` linked to verified contacts (Hospital / Clinic / Ambulance / Pathology). `provider_ids` populated on every activity at seed time.

## Tested
- **Iteration 1**: 33/33 backend tests pass.
- **Iteration 4**: 30/30 multi-tenant backend tests pass + 15/16 frontend playwright (single FE failure was test-script artifact, not product bug).
- Total: zero open product issues.

## Backlog / Next
- **P1** Wire federated OTP through upstream Trata-admin backend (`UPSTREAM_API_URL` + auto-forward `/auth/*` calls).
- **P1** Per-provider scoped sync from upstream (`/api/hospital/{id}/cases`, `/api/ambulance/{id}/bookings`, etc.) instead of one-shot full sync.
- **P2** WebSocket / SSE for sub-second SOS push to provider dashboards (replace 30s poll).
- **P2** Web Push notifications (uses installed PWA) for CRITICAL emergencies.
- **P2** Bulk actions for HQ (assign tasks to multiple providers, bulk KYC approval).
- **P3** Staff sub-role (driver / paramedic / doctor under a provider) — defer.
- **P3** Medical Store & Diagnostic Centre provider types — defer.
- **P3** Split `server.py` into module files (`auth.py`, `provider.py`, `internal.py`, `seed.py`) — code-organization.

## Notes / Mocks
- OTP is MOCKED — only `123456` works. Set `UPSTREAM_API_URL` to federate.
- Provider data still SEEDED — set upstream URL to mirror live.
- AI uses Emergent LLM key (Claude Sonnet 4.6).
