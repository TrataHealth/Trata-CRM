# TrataHealth CRM — PRD

## Original Problem Statement
User shared `https://github.com/TrataHealth` (healthcare emergency platform — SanjeevaniX) and asked for a full-fledged CRM at the master-admin level. Then asked to evolve into a multi-tenant activity tracker for providers (phone+OTP+password as the unique key), then pivoted again to make the CRM a **Sales Agent driver tool** for onboarding healthcare providers (Ambulance fleet partners) onto the Trata Provider App.

## Personas
- **Master Admin / Manager** — full network view + Leaderboard + final KYC approval.
- **Sales Agent (sales_rep)** — primary persona. Onboards ambulance providers.
- **Provider Owner (Ambulance)** — sees only their own fleet, earnings, KYC.

## Architecture
- **Backend** — FastAPI (`/app/backend/server.py` ~3650 lines) + `upstream_sync.py` + `admin_bridge.py`, MongoDB (Motor), JWT (PyJWT) access (30d) + temp (10m) tokens, bcrypt password hashing. Claude Sonnet 4.6 + Gemini 2.5 Flash via `emergentintegrations`.
- **Frontend** — React 19 + Tailwind + Shadcn UI + Recharts + lucide-react + react-leaflet. 3-step login (phone → OTP → password). Role-aware sidebar/router. PWA-installable.
- **DB** — `tratacrm_db`. Collections: `contacts`, `activities`, `tasks`, `notes`, `notifications`, `crm_users`, `sync_status`, `targets`, `fleet`, `admin_bridge_events`, `admin_bridge_outbound`, `webhook_events`.

## What's Implemented (Latest first)

### Iter 18 (2026-06-12) — AI KYC Pre-screening (P0 — current)
- New endpoint `POST /api/contacts/{id}/kyc-ai-prescreen` (internal-only; sales reps gated to their own leads).
- Downloads each uploaded KYC doc from Trata Admin (with Bearer auth) into `/tmp`, then sends to **Gemini 2.5 Flash** via `emergentintegrations.LlmChat` with `FileContentWithMimeType` attachment.
- Structured-JSON prompt returns `{recommendation: approve|reject|unclear, reason, confidence}` per doc.
- Results persist on `contact.ai_doc_prescreens` + `contact.ai_prescreen_summary` (`{approve, reject, unclear, total, model}`).
- New outbound event `crm.kyc.ai_prescreened` → maps to admin app's `kyc.note_added`.
- Frontend: `KycMirrorCard` gets an "AI pre-screen" / "Re-scan with AI" button (purple gradient), a summary banner ("AI suggests: X approve · Y reject · Z unclear"), and per-doc pills showing `AI: Approve/Reject/Unclear (NN% conf)` with reasoning. A "Use suggestion" link opens the inline review form with notes pre-filled from the AI reason. Optimistic state update prevents flicker on re-scan.
- Tested: 5/5 pytest pass (`test_kyc_ai_prescreen.py`) + Playwright E2E confirmed end-to-end on Rohan + Master Admin.

### Iter 17 (2026-06-12) — Production data only (demo wipe)
- Hard-deleted all seeded contacts (182), activities (522), tasks (28), payouts (2), notifications (30), bridge audit (16+9), webhook_events test rows (12), and `9000020003` provider_owner.
- **Auto-seed at startup is now DISABLED**. The CRM starts with whatever is in MongoDB and never re-creates demo data on restart.
- **Final state**: 1 real provider (Abhishek Ambulance) + 4 staff. Every future contact comes only from real signups via `/api/webhooks/admin-app`, `/api/webhooks/provider-app`, or the 5-min `/api/admin/users` sync.
- To re-enable demo seeding for local dev: `POST /api/admin/seed`.

### Iter 16 (2026-06-12) — Periodic admin-user sync + auto-escalation
- New `admin_bridge.sync_users_from_admin()` — pulls `/api/admin/users` every 5 min, upserts ambulance providers into CRM contacts (matches by normalized phone). Never overwrites pipeline stage/agent/KYC.
- New `escalation_loop` background task (15min): >36h with no KYC → notify manager; >24h in admin queue → notify + Resend email to master admin.

### Iter 15 (2026-06-12) — SLA timer + ops metric
- `SlaChip` component (green <12h / yellow 12-24h / red OVERDUE ≥24h). Wired into KYC queue and `KycMirrorCard`.

### Iter 14 (2026-06-12) — Two-tier KYC workflow
- Sales rep per-doc approve/reject → submit → master admin final approval queue.
- Endpoints: `POST /contacts/{id}/kyc-doc-review`, `POST /contacts/{id}/kyc-submit-for-admin`, `POST /contacts/{id}/kyc-admin-final`, `GET /admin/kyc-queue`, `GET /admin/kyc-queue-count`.
- 9 outbound events live, all delivering 200 OK.

### Iter 13 (2026-06-12) — Phase 6 KYC Mirror
- `GET /contacts/{id}/kyc?refresh=` proxies live KYC payload from Trata Admin App and caches `upstream_user_id` + `kyc_id` on the contact.
- `KycMirrorCard.jsx` with checklist, docs, review history.

### Iter 12 (2026-06-12) — Trata Admin App ⇄ CRM two-way bridge
- New `admin_bridge.py` with HMAC sign+verify, async outbound queue with exponential backoff, idempotency dedupe.
- 7 inbound events + 9 outbound events.

### Iter 11 (2026-06-12) — Org hierarchy + clickable team detail
### Iter 10 (2026-06-11) — Password recovery + security questions (Resend)
### Iter 9 (2026-06-11) — Provider-App webhook bridge
### Iter 8 (2026-06-11) — Agent Leaderboard + AI Digest + GPS QuickLog
### Iter 7 (2026-06-10) — Sales Agent pivot
### Earlier (Iter 1-6) — Master admin CRM MVP, live upstream sync, PWA, multi-tenant providers, earnings, Ambulance-only scope.

## Backlog / Next

### P1
- **Manager intelligence (Phase 9)**: Funnel conversion per agent, time-in-stage, stale-lead alerts, territory heat-map, AI coaching nudges.
- Federate OTP through live Trata-admin backend (`UPSTREAM_API_URL`).
- Voice notes on QuickLogModal.

### P2
- Parallelize AI doc scans with `asyncio.gather` (currently sequential; ~3-8s per doc).
- Expose per-doc AI scan failure count on `ai_prescreen_summary` so the rep sees if a doc didn't get scanned.
- Patient App webhook receivers (if CRM ever expands beyond providers).

### P3 — Tech debt / refactor
- Split `server.py` (~3650 lines) into `routers/{auth,agent,kyc,bridge,team,admin}.py` + extract AI helpers into `/app/backend/ai_kyc_prescreen.py`.
- Tighten `/api/admin/webhooks/test-send` + `/api/admin/webhooks/events` from `require_internal` to admin/manager only.
- Add `internalOnly` guard on `/agent` route in `App.js`.
- Add upstream-doc size cap in `_download_admin_doc` to prevent disk-fill.
- Defensive try/catch in AgentDashboard.load().

## Critical Info
- **Data Reality**: App runs purely on real data from `admin_bridge.py` sync + webhooks. Do NOT re-implement seeding.
- **Master Admin password**: `Master@123` (capital M). Not `Trata@123`.
- **EMERGENT_LLM_KEY** is loaded in `/app/backend/.env` and used for both AI Digest (Claude Sonnet 4.6) and AI KYC Pre-screening (Gemini 2.5 Flash).

## Critical seed (4 staff + 1 real provider)
- Master Admin `9873117605` · `Master@123`
- Sales Manager (Priya) `9000000001` · `Trata@123`
- Sales Agent (Rohan) `9000000002` · `Trata@123`
- Ops Rep — see test_credentials.md
- Real provider: Abhishek Ambulance `7678218261` (no CRM login — comes from upstream admin app)
