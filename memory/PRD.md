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

### Iter 15 (2026-06-12) — SLA timer + ops metric
- New `SlaChip` component with auto-update every minute; color-coded urgency: green <12h, yellow 12-24h, red OVERDUE ≥24h.
- Wired into 3 places: each KYC queue row, sales-rep review state in `KycMirrorCard`, master-admin awaiting-final state in `KycMirrorCard`.
- KYC queue page shows ops summary: "Avg time-pending: 18.4h · ⚠ 2 overdue (>24h)" at the top.
- Pure frontend (`slaInfo` helper in `constants.js` + `SlaChip.jsx` ~25 LOC). No backend changes needed — uses existing `created_at` and `kyc_agent_completed_at` timestamps.

### Iter 14 (2026-06-12) — Phase 6.5 Two-tier KYC workflow (sales rep → master admin)
- **Per-document review by sales rep**: new endpoint `POST /api/contacts/{id}/kyc-doc-review` accepts `{doc_id, decision, notes}`, persists per-doc decisions on `contact.agent_doc_reviews`, emits `crm.kyc.doc_reviewed`. UI: each KYC doc gets inline ✓ Approve / ✗ Reject buttons + optional notes; once decided, shows the agent's verdict in green/red.
- **Sales rep submission**: `POST /api/contacts/{id}/kyc-submit-for-admin` marks the lead `kyc_status='agent_reviewed'`, sets `kyc_agent_completed_at` + `kyc_agent_summary{approved,rejected,total}`, emits `crm.kyc.agent_completed` (maps to admin app's `kyc.review_requested`). "Submit to Master Admin" button is disabled until all docs are decided.
- **Master admin final approval**: `POST /api/contacts/{id}/kyc-admin-final` accepts `{decision: verified|rejected, notes}`. On `verified`, pipeline → `verified`. Emits `crm.kyc.admin_verified`.
- **Master admin queue + sidebar badge**: `GET /api/admin/kyc-queue` lists every lead with `kyc_status='agent_reviewed'`, `GET /api/admin/kyc-queue-count` is the cheap badge counter (polled every 30s from the sidebar). New page `/admin/kyc-queue` with a list view sorted by oldest-submitted first.
- **Master admin notification**: every inbound `provider.signed_up` webhook now creates an in-app notification with the assigned agent name so admins see new signups.
- **Outbound field rename fix**: admin app's note schema uses `text` + `author_phone` (we were sending `notes` + `reviewer_phone`); now sending both naming conventions for safety. Round-trip confirmed: latest note in upstream KYC shows `text='MASTER ADMIN FINAL: VERIFIED — ...' author_phone='9873117605' role='admin'`. Old events stuck with empty text are historical only.
- **9 outbound events live** (was 6): `crm.lead.created`, `crm.lead.assigned`, `crm.activity.logged`, `crm.kyc.reviewed`, `crm.kyc.doc_reviewed`, `crm.kyc.agent_completed`, `crm.kyc.admin_verified`, `crm.deal.closed`, `crm.note.added` — all delivering 200 OK.
- Verified end-to-end: Rohan reviewed Abhishek's doc → submitted → queue showed 1 item with badge=1 → Master Admin verified → pipeline=`verified`, badge=0.

### Iter 13 (2026-06-12) — Phase 6 KYC Mirror (read-side complete)
- Admin team shipped 3 endpoints we needed: `GET /api/admin/users` (✅), `GET /api/admin/users/{id}/kyc` (✅, full payload as spec'd, includes kyc_id), and `kyc.note_added` now accepts `phone` fallback (✅). User-detail GET still 500s but isn't needed since KYC payload returns the upstream `user_id`.
- New backend helpers in `admin_bridge.py`: `admin_api_get`, `find_admin_user_by_phone` (with role priority — provider > customer when phones collide), `fetch_kyc`.
- New endpoint `GET /api/contacts/{id}/kyc?refresh=true|false` — proxies to admin app, caches `upstream_user_id` + `kyc_id` + `kyc_upstream_status` + `kyc_synced_at` on the contact; resolves relative doc URLs to absolute upstream URLs.
- `crm.kyc.reviewed` outbound now carries the cached `kyc_id` and `upstream_user_id`, plus `phone` as a fallback — admin app deduplicates on whichever they prefer.
- New frontend `KycMirrorCard.jsx` mounted on `/contacts/:id` for `ambulance_provider` contacts. Shows: status pill, kyc_id, last reviewed by, progress bar + checklist with required flags, uploaded docs (clickable "View document" links to upstream), review history timeline, and 3 decision buttons (Approve / Needs more info / Reject) that POST to `/api/contacts/{id}/kyc-review`.
- Verified end-to-end with Abhishek's record on the live admin app — 1 approved doc, 7-item checklist, kyc_id `74b7c2bf...`, outbound `crm.kyc.reviewed` payload now carries the real kyc_id.

### Iter 12 (2026-06-12) — Trata Admin App ⇄ CRM two-way bridge
- New module `/app/backend/admin_bridge.py`: HMAC sign+verify, lazy-env, async outbound queue with exponential backoff (max 6 attempts, capped at 5min), idempotency dedupe by `event.id`, background dispatcher loop polling every 30s.
- New backend endpoints:
  - `POST /api/webhooks/admin-app` — receives 7 inbound event types (provider.signed_up, .first_use, .kyc.submitted, .kyc.updated, .deactivated, .profile.updated, payout.processed). HMAC-verified. Replays return `409 duplicate_event`.
  - `GET /api/admin/bridge/events` — admin/manager dashboard data (inbound + outbound + counts + config).
  - `POST /api/admin/bridge/test-send` — queue a signed outbound event with one click.
  - `POST /api/admin/bridge/retry/{id}` — manual retry of failed/retrying outbound.
  - `POST /api/contacts/{id}/kyc-review` — Phase 6 sales-agent KYC decision; emits `crm.kyc.reviewed`.
- Outbound emission hooked into existing flows: PATCH /contacts (deal.closed), PATCH /contacts/{id}/assign (lead.assigned), POST /agent/quick-log (activity.logged + deal.closed), POST /notes (note.added), POST /contacts/{id}/kyc-review (kyc.reviewed).
- Loop prevention: inbound-created contacts get `source: 'trata_admin_webhook'` and outbound deal.closed is suppressed for those leads.
- `.env`: TRATA_ADMIN_API_URL, TRATA_ADMIN_API_KEY (admin team to provide), TRATA_ADMIN_WEBHOOK_URL, ADMIN_CRM_WEBHOOK_SECRET=`trata-admin-crm-bridge-2026-r7Qx4n9Lm2pK8sVj`.
- Frontend: new `AdminBridgePanel` on the Master Dashboard with HMAC status badges, live counters, outbound test sender, retry-now button on failed events, full inbound event log auto-refreshing every 8s.
- Curl-verified: bad sig → 401, good sig → 200, replay → 409, KYC update → 200 + stage bump, outbound dispatcher fires + reports HTTP 404 from upstream (expected until admin team ships `/api/integrations/crm/webhook` per the spec we sent them).

### Iter 11 (2026-06-12) — Phase 9 Org hierarchy + clickable member detail
- New strict hierarchy: Master Admin → National Manager → Regional Manager → Zonal Manager → Area Manager → Sales Rep/Ops Rep. Each role can ONLY report to the role immediately above (validated server-side with cycle detection).
- New endpoint `GET /api/team/{id}` returns: profile, reports_chain (climbing to root), direct_reports[], providers_handled count, performance{} (self for sales rep / team-rollup for managers), recent_activities[], feedback[]. New `PATCH /api/team/{id}` for admins to update name/email/role/reports_to/territories. New `POST /api/team/{id}/feedback` + DELETE for manager-rated 1-5 + note feedback.
- Frontend: `Team.jsx` rewritten — tier-grouped clickable cards with role-coloured pills, reports_to dropdown filters to valid parent-tier candidates. New `/team/:id` page with inline-edit, hierarchy chain, drill-down direct reports, stat cards, territory chips, activity timeline, manager feedback compose + list.
- Legacy 'manager' role auto-migrated to 'regional_manager' on startup.
- Tested: 18/18 backend pytest in `test_team_hierarchy.py`. Frontend visually verified via screenshots (Team page tier grouping + detail page sections all rendering correctly).

### Iter 10 (2026-06-11) — Phase 7 Password recovery + Security questions (Resend)
- New backend endpoints: `/auth/security-questions`, `/auth/security-status`, `/auth/security-setup`, `/auth/forgot/start`, `/auth/forgot/request-code`, `/auth/forgot/reset`.
- 8 preset security questions. User picks 2; answers hashed with bcrypt (case-insensitive, whitespace-trimmed). Reset flow requires only 1-of-2 correct.
- 6-digit code, hashed at rest, 15-min expiry, 30s rate-limit between sends.
- Email via **Resend** SDK (key in `.env`). When delivery fails (e.g. test-mode recipient restriction) the API surfaces `dev_code` so QA/dev can complete the flow without inbox access.
- `_safe_user` redacts `password_hash`, `security_questions`, `reset_code_*` fields and adds `has_recovery_email`, `has_security_questions`, `security_setup_required`.
- Frontend: new pages `/forgot` (3-step), `/security-setup` (forced after first password set), `/settings` (overview + update). Login page now has `Forgot password?` link. Sidebar shows `Account settings` link. Post-login redirect honours `security_setup_required`.
- Tests: 23/23 backend pytest + 100% playwright frontend.
- Known UX note: Master Admin and Provider Owner must complete `/security-setup` once on next login.

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
