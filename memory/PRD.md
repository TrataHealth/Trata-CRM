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

### Iter 25 (2026-06-12) — Network section: live mirror of Trata Admin App
- **Backend** (no admin-app changes needed — all read-only proxy):
  - `admin_bridge.fetch_cases()`, `fetch_network_stats()`, `fetch_ambulance_providers()`
  - `GET /api/upstream/cases?status=&case_type=` — live emergency-case board with by-status / by-type counts
  - `GET /api/upstream/cases/{id}` — single case (timeline, vitals, patient profile, location)
  - `GET /api/upstream/patients?q=` — derived from cases (dedupe by patient_id/customer_phone) — Admin App has no standalone patients endpoint
  - `GET /api/upstream/network-stats` — pass-through to admin `/api/admin/stats`
  - `GET /api/upstream/kyc-overview` — cross-references admin /users with CRM contact + per-doc reviews + AI prescreen summary, sorted with pending KYC first
- **Frontend** new `/network` route (admin-only) — `Network.jsx` 4-tab layout (Emergency cases · Patients · KYC manager · Network stats). Filter pills with live counts, click-to-detail drawer for cases (timeline, vitals, location, patient profile), search on patients, status-aware KYC table with "Open" deep-links to CRM contact, 8 KPI tiles on stats. New sidebar entry "Network" with Network icon.
- **Note**: "Appointments/bookings" was requested but the Admin App doesn't expose a separate appointments endpoint — emergency cases ARE the bookings. They're surfaced via the Emergency cases tab with `case_type` filter (`emergency_ambulance` vs `phone_call_emergency`).
- **Verified live**: Playwright screenshots confirm all 4 tabs render with real upstream data (18 cases, 3 patients incl. Siddharth Gupta with 16 cases, 4 providers in KYC overview with mixed verification states, 13-user / 10-patient stats).

### Iter 24 (2026-06-12) — Onboarding + AI insights opened to staff
- **Backend permissions**: `POST /admin/onboard-provider` now allows all internal staff (admin, manager, sales reps, ops reps). When a sales rep onboards a provider, the new contact is auto-assigned to that rep (instead of territory-pick).
- **Backend** `/api/agent/dashboard?range=…` — same 6 range options as the master dashboard (`7d`, `30d`, `3m`, `6m`, `12m`, `all`). KPIs are now windowed: `onboarded_in_window`, `window_activities`. Stale-leads remains a fixed 7-day SLA.
- **Backend** `POST /api/agent/ai-insights` — Claude Sonnet 4.6-powered coaching briefing scoped to the agent's window. Reuses the agent dashboard as source-of-truth. Returns markdown with 4 sections (Headline · What's working · What's at risk · Do next). Admin/manager can pass `agent_id` to inspect any rep; sales reps see only themselves.
- **Frontend** `AgentDashboard.jsx` — range pill (7D/30D/3M/6M/12M/All), purple "AI insight" button, full AI coach drawer with markdown rendering. KPI label updates to reflect the selected window. Testids: `agent-range-filter`, `agent-range-{key}`, `agent-ai-insights-{btn,panel,content}`.
- **Frontend** `AgentLeads.jsx` — "Onboard provider" button (testid `agent-leads-onboard-btn`) added to the page header. Reuses the existing `OnboardProviderModal`.
- **Refactor**: extracted the markdown renderer + RANGE_OPTIONS into shared `/app/frontend/src/lib/insights.jsx` so both dashboards use the same helper.
- Verified end-to-end via curl + Playwright screenshots — Claude returned a sharp, agent-specific coaching briefing for Rohan; My Leads onboard modal opens with full form; sales-rep onboarding auto-assigns the new lead to the rep.

### Iter 23 (2026-06-12) — Onboard new provider from CRM
- **Backend** `POST /api/admin/onboard-provider` — admin/manager-only. Validates role (must be one of ambulance_provider, hospital, doctor, paramedic, pathologist, pharmacy), 10-digit phone, and name. Duplicate-phone returns 409. Creates a CRM contact with `pipeline_stage="contacted"`, `kyc_status="pending"`, auto-assigns by territory, logs a `provider_onboarded` activity, and emits the outbound `crm.lead.created` event so the Trata Admin App webhook handler sees it.
- **Frontend** `OnboardProviderModal.jsx` — sleek modal with role-chip grid + common fields (name, phone, email, city, state, address, PAN, GST) + per-role extras (ambulance: vehicle count/reg/licence; hospital: legal name/specialities/licence; doctor: specialisation/MCI #; paramedic, pathologist, pharmacy variants). "Onboard provider" button (testid `contacts-onboard-btn`) added to Trata Users page header, visible to admin/manager only.
- **Sync status** transparency — success panel shows a 3-line sync status: ✓ added to CRM, ✓ outbound `crm.lead.created` delivered to Trata Admin App (HTTP 200), ⚠ **honest disclosure**: today the Trata Admin App's webhook handler only *logs* `lead.created` events (`{result: {logged: true}}`) and does not yet auto-create users from them. Provider-App OTP-login will work end-to-end once the Admin App is upgraded to upsert users on inbound `lead.created`.
- Tested live end-to-end: created "Dr. Test Doctor" via the UI → contact appeared in CRM, outbound event status=sent (HTTP 200) → cleanup verified. Test contacts removed; DB is back to real-data-only (Abhishek + Tathastu + 2 fresh upstream syncs).

### Iter 22 (2026-06-12) — Dashboard range filter + AI insights
- **Backend**: `/api/dashboard/stats?range=7d|30d|3m|6m|12m|all` — time-windowed counts for cases, revenue and activity_breakdown. Growth chart adaptively buckets (always ≤14 points) so the chart looks right across all windows. Pipeline/users/tasks stay all-time snapshots.
- **Backend**: new `POST /api/dashboard/ai-insights` (body `{range}`) — reuses the same stats endpoint as source of truth, sends a compact JSON snapshot + recent activity titles to **Claude Sonnet 4.6** (via emergentintegrations + EMERGENT_LLM_KEY), returns structured markdown with 4 sections (Headline · What's working · What's at risk · Do next). Internal-only.
- **Frontend**: Dashboard header now renders a pill segmented-control (testids `dashboard-range-filter` + `dashboard-range-{7d|30d|3m|6m|12m|all}`) + purple gradient "Generate AI insight" button (testid `dashboard-ai-insights-btn`). Range change refetches stats; AI panel (testid `dashboard-ai-insights-panel`) renders the markdown via a tiny purpose-built parser (handles `## headings`, `- bullets`, `**bold**`).
- Bug fix during build: shadowing Python's `range` builtin in the FastAPI signature caused `'str' object not callable`. Fixed by aliasing `range_key: str = Query("7d", alias="range")`.
- Verified end-to-end via curl + live Playwright screenshot — Claude returned a sharp, number-citing briefing for the 30D window.

### Iter 21 (2026-06-12) — Multi-provider type sync (hospitals, labs, doctors, etc.)
- `admin_bridge.sync_users_from_admin` now syncs **all healthcare provider roles** (ambulance_provider, hospital, doctor, paramedic, lab/pathologist, pharmacy) instead of ambulance-only.
- Upstream role → CRM contact type 1:1 (with `lab` → `pathologist` alias). Existing contacts get a `type` correction if it had drifted.
- Escalation loop broadened to flag stale leads across all provider types.
- Verified: forced sync now imports Tathastu Institute of Medical Sciences & Hospital alongside Abhishek Ambulance. UI "Trata Users" tab shows both rows correctly tagged HOSPITAL and AMBULANCE.

### Iter 20 (2026-06-12) — Apply AI-extracted fields to contact (one-click)
- New endpoint `POST /api/contacts/{id}/apply-extracted-fields` body `{fields?: string[]}`. Empty body = apply all. Strict whitelist (`AI_FIELD_TO_CONTACT_FIELD`) — only the 13 vetted KYC keys map to contact fields. Length-capped at 200 chars per value. Internal-only; sales reps gated to their own leads. Logs a `type='note', outcome='ai_fields_applied'` activity for the audit trail.
- Frontend: aggregated "AI-extracted fields" panel now has a "Apply all to contact" button (testid `kyc-apply-all-fields-btn`) plus per-field "Apply" links (testid `kyc-apply-{field}`). When the contact already has the same value, the link is replaced with a green "✓ applied" badge (testid `kyc-applied-{field}`). Optimistic update — the green checkmarks appear instantly after apply.
- Tested via curl: 4-field bulk apply succeeds end-to-end (name, pan_number, vehicle_reg, address all written to the real contact). Single-field apply works. 400 when nothing to apply. UI screenshot confirms panel renders with applied badges.

### Iter 19 (2026-06-12) — AI KYC Field Extraction (delta on iter 18)
- `_ai_screen_doc` now also requests an `extracted` JSON sub-object from Gemini with a 13-field whitelist (document_number, name, father_name, dob, pan_number, gst_number, aadhaar_last4, vehicle_reg, vehicle_make_model, issue_date, expiry_date, address, issuing_authority).
- Per-doc fields persist on `ai_doc_prescreens[doc_id].extracted`. Approved-doc fields aggregate up to `contact.ai_extracted_fields = {field_name: {value, source_doc_id, source_kind}}` (first-non-empty wins per run; later runs overwrite).
- Fixed `_parse_ai_json` to correctly strip ```json … ``` markdown fences — previous iteration was silently swallowing perfectly-valid Gemini JSON and falling back to 'unclear'.
- Frontend: new purple aggregated panel `kyc-extracted-fields` between header and Checklist/Docs (hidden when empty); per-doc AI pill now includes an Extracted: line with key:value pairs.
- Tested: 6/6 pytest pass + 100% Playwright. New regression test `test_parser_handles_fenced_json` guards the fence bug.

### Iter 18 (2026-06-12) — AI KYC Pre-screening (P0)
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
