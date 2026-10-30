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

### Iter 46 (2026-10) — Diagnostic Centres + Cross-app Table Parity Sheet
- **Cross-app parity audit completed** against the patient app's authoritative table list (shareable at `/app/memory/TABLE_PARITY_CHECKLIST_CRM.md`). Filled rows A1–A8, B1–B7, C1–C8, D1–D3, E1–E10, F1–F6 with CRM's actual table, filter, R/W, and Match Y/N. **8 sync breaks flagged** for the joint convergence call: B2 OPD (`consultation_bookings` vs CRM's `appointments`), B3 lab bookings (`pathology_bookings` unread), C4 discharge summaries (never written), D2 `ambulance_allocations`, F4 enum (`verified` vs `approved`), A4 labs coverage, A1/A4/A8 missing `location`, E10 `hospital_bed_inventory`.
- **Diagnostic Centres user type added** — the shared `labs` table (8 centres: Dr. Lal PathLabs, SRL Diagnostics, Metropolis, Thyrocare, Max Lab, Apollo Diagnostics, City X-Ray, Orange City Path) has NO `users` rows, so the CRM user-sync never saw them. `list_all_users_for_crm_sync` now mirrors active `labs` rows as contacts of type `diagnostic_centre` (source `supabase_labs_sync`, `supabase_lab_id` tracked, phone fallback `lab-{id8}` so re-syncs are idempotent). Test-name filter applies here too.
- **Frontend**: new "Diagnostic Centres" tab on Trata Users (`CONTACT_TYPES` constant) and matching Dashboard tile (`by_type` loop extended). Dashboard: 28→36 total users, 7→15 verified.

### Iter 45 (2026-02) — Preview↔Production number mismatch · deep fix
- **Root cause**: new test users were being created in the shared Supabase upstream (by QA teams on the mobile apps). The CRM's 60-second auto-sync faithfully brought them in because `list_all_users_for_crm_sync()` filtered by `is_archived` but didn't look at the name pattern. The `/dashboard/stats` KPI tiles also counted every Mongo contact, including legacy test rows that pre-dated my purge.
- **Three-layer defence** against test-row pollution:
  1. **Supabase sync** (`supabase_db.list_all_users_for_crm_sync`) — now skips names matching `test / probe / it84 / demo hospital / dr test` + exact matches for `Sunrise Care Hospital`, `Metro Ambulance Ltd`, `UI Tester` at the source. New upstream test fixtures never reach CRM.
  2. **Admin-bridge sync** (`admin_bridge.sync_users_from_admin`) — same filter already applied in Iter 41, verified still active on the 5-min upstream pull.
  3. **Read path** (`/api/contacts` + `/api/dashboard/stats`) — belt-and-braces regex filter so any legacy test rows in Mongo stay hidden from users even before a purge runs.
- **Verified on preview**: Dashboard went from `33 total / 7 verified / 26 pending` → `28 total / 7 verified / 21 pending`. Role tiles reconciled with Trata Users roster. `/contacts?q=test` returns 0.
- **For production**: redeploy will apply the same filter and the Dashboard KPIs will drop from 73→~26 on their own. The master-admin "Purge test users" button (Iter 44) is still available for a one-click hard cleanup if preferred.

### Iter 44 (2026-02) — Purge Test Users button (master admin)
- **New "Purge test users" button** on the Trata Users toolbar (`/contacts`), visible only to master admins (`is_master_admin: true`). Red-tinted to signal destructive action.
- **Two-step confirmation** — first click runs `POST /api/admin/purge-test-users` with `dry_run: true` to preview count + sample of matched names; a native `confirm()` shows the count and up to 5 example names before the actual sweep runs. Master-admin accounts always preserved (their names never match the test patterns).
- **Wired to existing purge endpoint** — no new backend work. Same sweep patterns (`test`, `probe`, `it84`, `demo hospital`, `dr test` + exact matches for Sunrise Care, Metro Ambulance, UI Tester). Same soft-archive strategy in Supabase (preserves FK integrity) + hard-delete in Mongo.
- **Ships preview→production**: preview stays clean (26 users, verified this session), production currently at 66 users (46 test) — user will click the button once after next deploy to clean production.

### Iter 43 (2026-02) — Timeline Filters + CRM ↔ Trataxone Bidirectional Sync
- **Timeline Filters**: pill filter on the patient detail timeline — `All / Admissions / Appointments / SOS / Rides`. Each pill shows a live per-kind count, greys out to disabled at count=0, and the active pill is tinted with its kind's colour (blue admission / purple appointment / red SOS / amber ride). Choice is remembered in `sessionStorage` (`patient-timeline-filter`) so tab-switches don't reset the view. "All" filter includes discharge sub-events under Admissions so hospital reviewers see the full arc.
- **CRM → Supabase bidirectional sync** (Trataxone DB): new `upsert_user_from_crm()` helper mirrors CRM contact edits back into shared Supabase — `name` + `email` go to `users`, `city` + `state` + `address` go to the vertical profile (`hospital_profiles` / `ambulance_providers` / `doctors` / `pathologists`). Runs on every `PATCH /api/contacts/:id`. Matches by `supabase_user_id` first, falls back to phone (10-digit and `+91` variants). Never touches phone/role — those are identity.
- **`ContactStatusUpdate` model extended** to accept `name`, `email`, `city`, `state`, `address` — the CRM edit UI can now push identity + location fields, and every edit auto-mirrors upstream.
- **Verified end-to-end**: patched Xenon Multispeciality Hospital via CRM `PATCH /contacts/{id}` with `{"city": "MUMBAI-MIRROR", "email": "crm-sync@xenon.in", "state": "MH-MIRROR"}` → Supabase `users.email` and `hospital_profiles.city/state` updated instantly. The mobile Provider App reading Xenon's profile now sees the change without any manual push.
- Timeline filter verified: clicking `Rides 2` on Rahul Sharma's timeline shows only the 2 ambulance rides and hides everything else; disabled pills (`Admissions 0`, `SOS 0`) can't be clicked.

### Iter 42 (2026-02) — Patient Timeline (unified chronological feed)
- **New `TimelineFeed` component** on the patient detail page (`/admin/patients/:userId` and `/provider/patients/:userId`) merging Admissions, Appointments, SOS emergencies, and Ambulance rides into one chronological feed (newest first).
- **Visual design**: color-coded pill per event kind (blue admission / purple appointment / red SOS / amber ride / green discharge), timeline rail with iconised nodes, priority chips (RED / CRITICAL) for triage-priority events, SOS badge for emergency rides, fare shown for completed rides, absolute + relative timestamps ("10 Sept 2026, 10:34 am · 5h ago"), status chip on the right.
- **Data source**: already came from `fetch_patient_detail` — pure frontend flatten & sort by `at` timestamp (`triage_time`, `appointment_date`, `created_at`, `scheduled_time`) → renders in one `<ol>` with a vertical rail.
- **Also fixed**: `list_all_patients_admin` now filters `is_archived=FALSE` so archived test patients don't show in the Patients tab any more.
- Verified with 6 seeded events on Rahul Sharma (1 admission · 1 appointment · 2 SOS · 2 rides) — all render correctly, sorted newest first, with proper priority + SOS + status chips.

### Iter 41 (2026-02) — Test User Purge · Trata Users cleaned
- **Bulk cleanup of 71 test users** from both shared Supabase and CRM Mongo. Trata Users went from 66 → 26 real users; Patients tab now shows the single real patient (Rahul Sharma) instead of 7 test rows.
- Matches names against `test`, `probe`, `it84`, `demo hospital`, `dr test` (case-insensitive) plus exact matches for `Sunrise Care Hospital`, `Metro Ambulance Ltd`, `UI Tester`. Master admin phones (`9873117605`, `9161108882`) are always protected.
- **Strategy**: soft-archive in Supabase (`is_archived=TRUE, is_active=FALSE, archived_reason='test_user_cleanup'`) because 100+ FK tables reference `users`. Existing sync filter already excludes archived users so they vanish from CRM and any mobile view that honours the flag.
- Vertical profile tables + kyc_documents + hospital_staff + crm_provider_leads are hard-deleted. Mongo `contacts`, `crm_users`, and activities are hard-deleted by phone + name pattern.
- **Also patched** the background `sync_users_from_admin` loop so test-named users can never sneak back in from the upstream Trata Admin App on the 5-min tick.
- New endpoint `POST /api/admin/purge-test-users` (accepts `{"dry_run": true}` for preview). Idempotent — re-runnable to sweep any new test users going forward.

### Iter 38 (2026-02) — Patients section (fully synced with mobile Provider App)
- **New Patients section for two personas**, both reading directly from shared Supabase:
   - **Master admin** at `/admin/patients` — Trata-wide roster of every `users` row where `role='patient'`, with rollup counts (cases · appointments · admissions) per row + summary tiles. Search by name or phone.
   - **Providers (hospitals)** at `/provider/patients` — hospital-scoped roster from `hospital_patients` filtered by the caller's `hospital_id`. Same clinical fields the mobile Provider App shows: age, sex, blood group, allergies, chronic conditions, diagnosis, admission/discharge dates, status. Other verticals return a "coming soon" scope message (mobile app is still primary there).
- **Shared patient detail page** at `/admin/patients/:userId` and `/provider/patients/:userId` — clinical profile grid (12 fields) + four association panels: **Admissions** (patient_admissions), **Appointments** (appointments), **Emergency cases** (emergency_cases), **Ambulance rides** (ambulance_bookings). Provider view is automatically scoped so hospitals only see rows tied to their own `hospital_id` — no cross-hospital leaking.
- **New backend endpoints**: `GET /admin/patients` (+ search), `GET /admin/patients/{user_id}`, `GET /provider/patients` (+ search), `GET /provider/patients/{user_id}`. All backed by new Supabase helpers `list_all_patients_admin`, `list_hospital_patients_for_provider`, `fetch_patient_detail`, `_fetch_patient_associations` in `supabase_db.py`.
- **Sidebar**: master admin gets a new **Patients** entry (HeartPulse icon) between Onboarding and KYC Final Approval; hospital providers get it inside the provider nav next to Staff.
- **Realtime sync**: writes go straight to the shared Trata Supabase — any admission/discharge/appointment created from the mobile Provider App or Trata Admin App appears on the PC console instantly.
- **Verified**: master admin roster shows all 6 patients with activity counts + tiles; City Care Hospital provider view shows 2 seeded hospital-scoped patients (Anita Verma ADMITTED · Suresh Kumar DISCHARGED) with the full clinical grid.

### Iter 37 (2026-02, previous session) — Master Admin · Direct Provider Onboarding + One-click KYC Approval
- **New admin flow `/admin/onboarding`** — sidebar entry (UserPlus icon) available to master admin + admins. Two-step workflow: (1) Onboard provider form (vertical picker for Hospital/Ambulance/Doctor/Pathology + name + phone + city/state/email/address). Writes go directly to shared **Supabase `users` + vertical profile** table so the mobile Provider App and Trata Admin App see the new account in real time. Password intentionally left blank — provider sets it on first OTP login. Also mirrors into CRM `crm_users` (so the phone can log in on the PC console) + `contacts` (so pipeline / KYC queue reflect it). (2) Redirects to per-provider KYC uploader.
- **Per-provider KYC uploader `/admin/onboarding/:userId`** — vertical-aware checklist (9-10 items per vertical) with per-row Upload buttons (image/PDF ≤ 4 MB, base64 client-side). Each admin-side upload is tagged `[Admin] …` in the doc name so reviewers instantly see the origin, and it writes to shared `kyc_documents` so the mobile app + admin app show it live as `submitted`.
- **One-click "Approve all & activate" button** — bulk marks every submitted/pending kyc_documents row as approved, sets `users.verification_status='approved'` and the vertical profile's verified flag (`hospital_profiles.verification_status`, `ambulance_providers.status/approved_at`, `doctors.is_verified`, `pathologists.status/is_verified/approved_at`). Refuses to run if any *required* doc is missing (returns 400 with the missing keys), so admins can't accidentally approve incomplete profiles. Also mirrors the approval into Mongo `contacts.kyc_status='approved'` for CRM parity.
- **New backend endpoints** (`server.py`): `POST /admin/onboarding/providers`, `GET /admin/onboarding/providers` (roster w/ KYC progress), `GET /admin/onboarding/providers/{user_id}/kyc`, `POST /admin/onboarding/providers/{user_id}/kyc/upload`, `POST /admin/onboarding/providers/{user_id}/approve-all`. All gated behind `_require_admin(current)` (master admin / admin only) and 503 if Supabase is offline.
- **New Supabase helpers** (`supabase_db.py`): `create_provider_from_admin` (idempotent on phone, one transaction so mid-flight failures never leave orphan users), `admin_upload_kyc_document`, `approve_all_provider_kyc`, `fetch_provider_summary`, `list_admin_onboarded_providers`.
- **BUG FIX (side-effect discovery)** — `upsert_provider_lead()` was silently broken in the previous session too: its function body had been accidentally sliced by an inserted comment, so every dual-write to Postgres `crm_provider_leads` was returning `None` on the success path. Reassembled the function into one contiguous block; dual-write to Postgres now correctly persists.
- **Verified end-to-end**: created `Sunrise Care Hospital` (hospital) → uploaded 7 required docs → one-click approved (7 docs → approved, verification_status → approved). Created `Metro Ambulance Ltd` (ambulance) → 10-item checklist renders, approve button correctly gated at 0/9 until required docs are uploaded, missing-doc gate returns 400 with the exact list.

### Iter 36 (2026-02, previous session) — Hospital Staff Roster · Bug fixes
- **`/provider/staff` verified end-to-end**. `HospitalStaff.jsx` (`City Care Hospital · Staff`) renders KPI tiles (Total staff / On duty / Active / Top role), an inline Add-staff form (name / role / dept / specialization / phone / email / shift / salary), roster table with search + role filter + duty toggle + delete. Backend CRUD: `GET/POST /api/hospital/staff`, `POST /api/hospital/staff/{id}/duty`, `DELETE /api/hospital/staff/{id}` — all writing to shared `hospital_staff` Postgres table (mirror of mobile app's roster). Sidebar exposes a new "Staff" link for hospital verticals only.
- **BUG FIX · `fetch_full_provider_profile` was silently returning None**. The previous session accidentally left the `return out` statement in the wrong function (moved into `delete_hospital_staff` as dead code) when the staff CRUD block was inserted. Every call to `/api/provider/me` returned `profile: null`, breaking the Provider Profile page for all verticals. Return statement restored; profile fetch now correctly hydrates the 47-field vertical profile.
- **BUG FIX · `Layout.jsx` failed to compile** — `UserCog` was double-imported after the "Staff" nav item was added, breaking the entire SPA with a red overlay ("Identifier 'UserCog' has already been declared"). Duplicate import removed.

### Iter 35 (2026-02, previous session) — Pharmacy Removed (mobile-only, mirroring paramedic)
- **Pharmacy PC access disabled**: `SUPABASE_ROLE_TO_PROVIDER_TYPE` no longer maps `pharmacy` / `pharmacist`. `PHARMACY_MOBILE_ONLY_MESSAGE` added, and every branch of `/auth/verify-otp` (staff · provider · legacy) now returns 403 *"Pharmacy accounts must sign in on the Trata Provider mobile app, not the PC console."* for either fresh Supabase lookups or existing crm_user rows with `provider_type=pharmacy`.
- **`SUPPORTED_PROVIDER_TYPES`** now excludes `pharmacy` (in addition to the already-excluded `paramedic`).
- **Demo seed cleanup**: removed 9000020008 (MedPlus Corner Pharmacy) from `DEMO_ACCOUNTS`, dropped it from `PROVIDER_TYPE_TO_SB_ROLE`, and hard-deleted the leftover `crm_users` + `contacts` rows so the seed endpoint no longer resurrects pharmacy data. Pharmacy vertical also dropped from the KYC checklist.
- **Login page copy**: hero description now reads *"Hospitals, ambulances, doctors and labs"* (pharmacy dropped); role selector subtitle updated; demo panel now shows only 4 provider phones; footer note switched to *"Paramedics + pharmacies: please use the Trata Provider mobile app"*.
- **ProviderKyc `supportedByPortal`** now excludes both paramedic and pharmacy.
- **Verified**: pharmacy phone → 403 with mobile-only message; ambulance / hospital demos unchanged and still return `success:True` with correct `provider_type`.


- **New role selector on the login screen** — two-card toggle "Healthcare Provider" vs "Trata Staff" with icon, description and localStorage persistence (`trata_login_as`). Phone placeholder + helper text swap based on selection. Choice is passed to `/auth/send-otp` + `/auth/verify-otp` as `login_as`.
- **`/auth/verify-otp` completely rewritten** into 3 branches:
   - `login_as=provider` — Supabase `users` table is the source of truth. Not found → `404 PROVIDER_ONBOARD_MISSING_MESSAGE` ("sign up on the mobile app first"). Found + paramedic → 403 mobile-only. Found + unsupported role (admin/patient/etc.) → 403 with wrong-role message. Found + supported vertical → materialise **and refresh** the crm_users row (name / provider_type / supabase_user_id / supabase_role drift is corrected in-place before any password check).
   - `login_as=staff` — crm_users only; block provider_owner rows with a "pick Healthcare Provider" message.
   - No hint (legacy path) — preserves backward compat but now also auto-refreshes provider rows from Supabase so stale vertical/name never shadows the real record.
- **Duplicate-Supabase-row hygiene**: `_try_supabase_provider_lookup` + refresh queries now `ORDER BY` (supported role first, then exact 10-digit phone) so a `+91…` duplicate can't leak a stale vertical.
- **Idempotency on materialisation**: `_try_supabase_provider_lookup` re-reads crm_users before inserting, so parallel calls never duplicate.
- **Bug fix for `7678218261`**: cleaned up the stale ambulance-era crm_user; verify-otp on provider branch now returns `needs_password_setup: True` with `provider_type: hospital`, feeding directly into set-password + security-questions flow. Same phone on staff branch is properly rejected.
- **auth.jsx** & Login.jsx pass `login_as` through both `sendOtp` + `verifyOtp` helpers.


- **New `/provider/kyc` page** (ProviderKyc.jsx) — the KYC uploader that used to live inside the Hospital Command Centre now has its own dedicated tab. Full-progress ring + required/optional split + per-row hint copy + submitted/approved/rejected status chips + upload-history table.
- **Vertical-aware KYC checklist** shipped on the backend (`kyc_checklist_for()` in server.py). Doc keys are byte-identical to the mobile app's `tratax_kyc_documents.doc_key` so PC uploads land in the same admin review queue. Verticals: hospital (9 items), ambulance (10), doctor (8), pathology (9), pharmacy (7) — all share 5 common docs (`pan_card`, `address_proof`, `signatory_photo`, `authorized_signatory_id`, `gst_certificate`).
- **New endpoints**: `GET /api/provider/kyc/checklist` (returns checklist + upload status per item), `GET /api/provider/kyc/documents`, `POST /api/provider/kyc/upload`. Legacy `/api/hospital/kyc/*` retained via delegation for backward compat.
- **Command Centre trimmed**: KYC uploader removed, replaced with a small "Complete your KYC checklist →" CTA card linking to `/provider/kyc`.
- **Profile page (`/provider/profile`) trimmed** to identity + metadata only. KYC badge is now a link that jumps to the new KYC tab. Header renamed "Profile & KYC" → "Profile".
- **Sidebar**: single "Profile & KYC" item split into two — "Profile" (IdCard icon) and "KYC" (ShieldCheck icon). Available to every provider vertical.
- **Verified**: hospital checklist 9 items, ambulance checklist 10 items, upload lands in kyc_documents with `status='submitted'` and reflects on the next checklist fetch. Screenshot confirms PAN card = SUBMITTED chip + Re-upload flow.


- **Paramedic PC console fully removed**: paramedic accounts (both from Supabase and any legacy CRM row) are now rejected at `/auth/verify-otp` with a clear "use the mobile Provider App" message. `SUPABASE_ROLE_TO_PROVIDER_TYPE` no longer maps `paramedic`, and a runtime guard in `verify_otp` blocks existing paramedic `provider_type` crm_users too.
- Removed the paramedic demo (9000020007 · Ravi Paramedic Services) from `DEMO_ACCOUNTS` and cleaned out the existing Mongo `crm_users` + `contacts` rows.
- Login-page demo panel updated: paramedic line removed, footer copy switched to "Paramedics: please use the Trata Provider mobile app".
- **Bed management moved to its own tab** — new page `HospitalBeds.jsx` at `/provider/beds` with 4 KPI tiles (Total / Free / Occupied / Bed types), free-vs-occupied filter chips, per-type filter dropdown, grouped-by-type grid with ward labels, and inline Add-bed form. Auto-refreshes every 5s.
- Command Centre keeps the "Beds free X/Y" KPI tile + the admit-form bed picker, but the full grid is gone — replaced by a small "Manage the full ward grid →" CTA. Sidebar gets a new "Beds" nav item (BedDouble icon) shown only to hospital providers.

### Iter 31 (2026-02, previous) — Dual-Write · KYC Uploader · Push Realtime
- **Phase B.2 · CRM Contacts ↔ Postgres dual-write LIVE**. `supabase_db.upsert_provider_lead()` maps every Mongo `contacts` doc → `crm_provider_leads` schema (JSON-serialising jsonb cols, coercing ISO strings → datetime for asyncpg timestamp binding). `_mirror_contact()` helper in server.py fires post-write on `PATCH /contacts/{id}` and `PATCH /contacts/{id}/assign`. Best-effort — swallow failures so Mongo stays authoritative during cutover. Seed-demo endpoint now also mirrors every seeded contact automatically.
- **New `POST /api/admin/mirror-contacts-to-postgres`** — master-admin one-shot backfill. 26/26 contacts mirrored on first run.
- **Phase C · Hospital KYC Uploader shipped**. New endpoints `GET /api/hospital/kyc/documents` + `POST /api/hospital/kyc/upload` — writes to shared `kyc_documents` table with `provider_type='hospital'`, base64 file_data (≤ 4 MB), matches the mobile KYC review pattern (already reads file_data). 10 canonical hospital doc types.
- **Frontend KYC panel** added inline to `HospitalCommandCenter.jsx` — dropdown for doc type, display-name input, file picker (image/PDF ≤ 4 MB with base64 encoding on client), submitted-docs table with status chips + reviewer comments.
- **Phase A · Push Realtime via SSE**. New `GET /api/hospital/command-center/stream?token=<jwt>` streams a hashed-fingerprint snapshot every 1.5s only when data actually changes (heartbeat every 20s). Auth via query param (browsers can't set Authorization on EventSource). Frontend swapped `setInterval(3s)` → EventSource with automatic polling fallback if SSE gets blocked/dropped. Live-push badge now reads "Live push · updated just now".
- **New auth helper `get_current_user_from_query()`** in server.py so SSE endpoints can extract JWT from `?token=` param (never used for writes).
- **Verified**: 
  - Backfill: 26/26 contacts → Postgres.
  - Live PATCH: Mongo pipeline_stage change reflected instantly in Postgres.
  - KYC upload: base64 PNG persisted, list endpoint returns it with `status='submitted'`.
  - SSE: `curl -N` streams snapshot event within 200ms of connect.
  - UI screenshot: KYC section renders with uploaded doc, "Live push" badge visible, bed grid + incoming SOS still working.


### Iter 30 (2026-02, previous) — Hospital Emergency Command Centre (P0 shipped)- **New `/api/hospital/*` endpoints** (server.py:4611+): `GET /hospital/command-center`, `POST /hospital/emergencies/{id}/accept`, `POST .../decline`, `POST .../admit`, `POST /hospital/admissions/{id}/discharge`, `POST /hospital/beds/{id}/toggle`, `POST /hospital/beds`, `GET/POST /hospital/case-chat/{case_id}`. All backed by asyncpg writes against the shared Supabase tables the mobile Hospital Provider App writes to.
- **Schema discovery**: hospital_id on emergency_cases, hospital_beds, patient_admissions all FK to `users.id` (not hospital_profiles.id); case_chats FKs to hospital_cases.id. `_hospital_owner_user_id()` helper wraps this, and `accept_emergency_case` lazily inserts a `hospital_cases` lifecycle row so chats/admissions link correctly.
- **Walk-in patient synthesis**: admissions require patient_id → users.id. When the source SOS was placed without a signed-in patient, the admit endpoint creates a synthetic `role='patient'` walk-in user so the admission still records cleanly (emergency_cases.patient_id is varchar(20) so we intentionally don't back-link the full-UUID walk-in there).
- **New page `/provider/command-center`** (HospitalCommandCenter.jsx, ~360 lines) with 5 KPI tiles + Incoming + Active + inline Chat + inline Admit form + Bed Grid (per bed_type, click-to-toggle) + Admissions table with inline Discharge. Polls every 3s for near-realtime.
- **Sidebar**: "Command Center" item now appears above "My Activities" for hospital provider owners only (`hospitalOnly` flag on the nav config).
- **CTA on Hospital PC dashboard**: gradient banner links to the Command Centre.
- **Demo seed**: `/api/admin/seed-demo-accounts` now also inserts 8 beds (General 101–104, ICU 201–202, Ventilator 301, ER 401) + one demo incoming SOS (critical cardiac case for Rahul Sharma at MG Road, Bengaluru with vitals) targeting the demo hospital, so the workflow is playable out-of-the-box.
- **Verified end-to-end**: curl full lifecycle passes — Accept → Chat send/receive → Admit-with-bed → Discharge → KPIs update, no regressions.
- **Realtime**: 3s polling for MVP. WebSocket-based Supabase Realtime remains a Phase 4 follow-up (needs either Supabase JS SDK+RLS or FastAPI SSE backed by PG LISTEN/NOTIFY).


- **Extended `/api/provider/pc-dashboard` from ambulance-only → all 6 verticals** (hospital, paramedic, doctor, pathology, pharmacy) via `fetch_generic_provider_dashboard` in `supabase_db.py`.
- **Added `pharmacist` + `lab_tech` role mappings** to `SUPABASE_ROLE_TO_PROVIDER_TYPE` (server.py:306) and generalised profile_id lookup across all 6 vertical tables in `_try_supabase_provider_lookup`.
- **Paramedic case-count KPIs** now wired through `paramedic_id` on `emergency_cases`.
- **`ProviderDashboard.jsx`** — Fleet section, lifetime-earnings strip and ambulance-specific KPIs all gated on `vertical === 'ambulance'`.
- **Demo accounts extended from 3 → 6 provider verticals** (added Doctor 9000020006, Paramedic 9000020007, Pharmacy 9000020008). `POST /api/admin/seed-demo-accounts` now also mirrors each demo into shared Supabase (`users` + vertical profile table) using deterministic uuid5 IDs so `/pc-dashboard` shows real data end-to-end. Pre-fills `recovery_email` + `security_questions` so demo users skip the /security-setup detour and land straight on their PC console.
- **`Login.jsx` copy** updated (all verticals welcome) + demo-accounts panel now lists all 6 provider phones with `Trata@123`.
- **Verified**: 12/12 pytest green, curl E2E for demo hospital 9000020004 + demo doctor 9000020006 + demo pharmacy 9000020008 + real hospital 9310018056 + real paramedic 9939971813 + real ambulance 7678218261 all return correct vertical + payload. UI screenshot confirms Dr. Meera Clinic demo lands directly on doctor PC console without error.



### Iter 28 (2026-08-18) — Provider PC Console (Phase 1 auth + Phase 2 Ambulance)
- **Phase 1 (auth unification)**: `verify-otp` now falls back to Supabase `public.users` when a phone isn't in the CRM's `crm_users`. If it's a healthcare-provider vertical (ambulance, hospital, doctor, paramedic, pathologist, pharmacy), a `crm_users` row is materialized on-the-fly with `role=provider_owner`, mapped `provider_type`, and `supabase_user_id` linked to the shared row. First login triggers password setup; subsequent logins use the standard 3-step flow. New helper: `_try_supabase_provider_lookup`.
- **Phase 2 (Ambulance PC dashboard)**: new `GET /api/provider/pc-dashboard` reads directly from shared Postgres tables (`ambulance_providers`, `emergency_cases`, `ambulances`, `kyc_documents`). Zero sync — same 100ms data the mobile app sees. Returns: provider profile · KPI tiles (active trips, trips today/week, fleet avail/total, KYC approved/pending) · lifetime bookings/completed/earnings strip · 10 most recent cases · full fleet.
- **Frontend**: `ProviderDashboard.jsx` fully rewritten. 4 KPI tiles + business summary strip + two-column recent cases / fleet. Live-badge indicator shows the shared-DB status. Testids: `provider-dashboard`, `provider-kpis`, `provider-tile-*`, `provider-lifetime-strip`, `provider-recent-cases`, `provider-fleet`, `provider-shared-db-badge`.
- **Live verification (screenshot confirmed)**: Abhishek (`7678218261`, real ambulance owner already in Supabase `users` with an `ambulance_providers` profile) logged in with the exact same phone he uses on his mobile Provider App → landed on the "Trata Ambulance Service" PC console showing his business name, city (Mumbai Suburban), status (`pending`), and empty-state prompts pointing back to the mobile app for adding vehicles.

### Not in this iter (deferred)
- **Provider verticals other than Ambulance**: `/provider/pc-dashboard` currently returns 501 for hospital/doctor/pathology/paramedic/pharmacy. Extending is a copy-of-pattern per vertical.
- **Write actions**: PC dashboard is read-only. Accept case / upload doc / request payout live on the mobile app.
- **Realtime**: still using page-load reads. Postgres LISTEN/NOTIFY subscription is Phase 4.

### Iter 27 (2026-07-30) — Supabase migration Phase B.1 (schema + data backfill + read parity)
- **New Postgres table** `public.crm_provider_leads` (46 columns + 5 indexes) — the only CRM-owned table that didn't already exist in the shared schema. Everything else (`sanjeevani_agents`, `agent_activities`, `agent_tasks`, `notifications`) was already provisioned by the Patient/Provider/Admin apps.
- **DDL script** `/app/backend/tools/create_crm_tables.py` — idempotent, safe to re-run.
- **Migration script** `/app/backend/tools/migrate_mongo_to_postgres.py` — one-shot backfill from Mongo → Postgres for `contacts`, `crm_users`, `activities`, `tasks`. Handles: JSONB serialization, datetime coercion, FK dedupe (master admin phone already in shared `users` gets linked instead of re-created), ON CONFLICT DO UPDATE for idempotency, best-effort `agent_id` FK enforcement.
- **Backfill results (verified)**: 18 provider leads, 4 staff (incl. Master Admin), 4 activities all migrated. Empty tables (`tasks`, `notes`, `notifications`) skipped cleanly.
- **New Postgres-backed reads** in `supabase_db.py`: `fetch_crm_contacts`, `fetch_crm_contact`. Exposed as `GET /api/supabase/contacts?type=&stage=&q=` and `GET /api/supabase/contacts/{id}`. Response shape matches `/api/contacts` so the frontend can drop-in swap.
- **Verified parity**: `/api/supabase/contacts?type=hospital` returns the exact same 9 rows in the exact same order as `/api/contacts?type=hospital` — identical name/phone/pipeline_stage/assigned_agent.

### Not in Phase B.1 (moved to Phase B.2)
- **Write-path cutover**: every POST/PATCH that touches `contacts`/`activities`/`tasks` still writes only to MongoDB. Next session: dual-write to both stores, then flip primary to Postgres.
- **Frontend flip**: `Contacts.jsx` still calls `/api/contacts`. Once Phase B.2 dual-write is stable, we swap to `/api/supabase/contacts` and Mongo becomes a read-only fallback.
- `activities`/`tasks` endpoints (agent-side reads) are still Mongo-only.

### Iter 26 (2026-07-30) — Supabase migration Phase A (shared-Postgres read layer)
- **New shared Supabase project** `wpjttwbolrpodrnyriym.supabase.co` (Patient / Provider / Admin apps + CRM all read/write here). Schema already provisioned — 141 tables including `users`, `sanjeevani_agents` (=CRM staff), `agent_activities`, `agent_tasks`, `emergency_cases`, `ambulance_providers`, `hospital_profiles`, `kyc_documents`, `customer_profiles`, `notifications`, `webhook_outbox`, etc.
- **Backend**:
  - New `/app/backend/supabase_db.py` — asyncpg pool via Transaction Pooler (`statement_cache_size=0`, URL-encoded password) + read helpers `fetch_emergency_cases`, `fetch_case`, `fetch_patients`, `fetch_network_stats`, `fetch_kyc_overview`, `fetch_ambulance_providers`.
  - Env vars added: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY`, `DATABASE_URL` (Transaction Pooler DSN).
  - New endpoints (parity with `/upstream/*`): `/api/supabase/status`, `/api/supabase/cases`, `/api/supabase/cases/{id}`, `/api/supabase/patients`, `/api/supabase/network-stats`, `/api/supabase/kyc-overview`. All internal-only, all read-only in Phase A.
- **Frontend** — Network page gets a **data-source toggle** (testid `network-source-toggle` + `network-source-{supabase|restapi}`) that persists to localStorage. Child tabs accept a `prefix` prop and hit either `/supabase/*` or `/upstream/*` accordingly. Fallback to REST if Supabase health-check fails. Field-name normalization on stats tab (Supabase snake_case vs REST camelCase).
- **Verified live**: `/api/supabase/status` returns `connected: true`, network-stats returns 2 users (matches Supabase seed data), all 5 endpoints return 200. Toggle screenshot confirms both data sources render side-by-side.

**What Phase A does NOT include (deferred to Phase B/C):**
- Writes to Supabase (all CRM writes still land in MongoDB).
- Migration of `contacts` / `activities` / `tasks` / `notifications` from MongoDB to Postgres.
- Auth cutover (still on custom JWT + bcrypt; Supabase Auth cutover is Phase C).
- Removal of `admin_bridge.py` webhook queue (still active for admin-app REST parity).

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

## Iter 41 (2026-06) — Canonical-table convergence (Patient-App READ Contract)
- Onboarding requires lat/lng (manual + "Look up from address" via /api/admin/geocode, OSM Nominatim) for hospital/ambulance/pathology; writes users + canonical profile (user_id=users.id). Never writes tratax_tenants.
- Hospital: location json + 'pending_review' → approve-all 'verified'. Pathology: pathologists + labs branch. Ambulance: business_lat/lng. Approval blocks without coords (UI prompts lat,lng).
- consultation_bookings + pathology_bookings read in patient detail/timeline (Lab tests pill); discharge_summaries written on discharge; ambulance_allocations assign/status endpoints (/api/provider/ambulance/...); hospital_bed_inventory synced on bed changes; pharmacy_profiles → pharmacy_providers.
- Patient readers accept role patient|customer|NULL (patient app no longer writes 'patient'); test-name filter on admin patient roster.
- Tests: backend/tests/test_admin_onboarding_v2.py (16 pass). Report iteration_11.json.
- Pending: is_demo column (provider team); ambulance assign UI on PC dashboard; discharge form fields (final diagnosis / follow-up) in UI.

## Iter 42 (2026-06) — Dispatch, discharge summary, live updates
- Ambulance PC dashboard: Assign vehicle per case (only cases with ambulance_provider_id = provider), Dispatches panel (assigned→dispatched→arrived→completed, strict transitions), vehicle status on_trip/available, writes ambulance_allocations + emergency_cases.
- Hospital discharge form: final diagnosis required, condition + follow-up optional → discharge_summaries row.
- Live updates: /api/live/stream SSE (shared notifications by users.id + Mongo payouts) → bell unread badge + panel + toasts; dashboard/earnings refetch on events. /api/live/notifications, /read-all.
- Tests: tests/test_dispatch_discharge_live.py (19 pass, auto-cleans probe rows). Report iteration_12.json.
- Known gap: most providers have no CRM provider_id → payout events only fire for providers with payouts docs (payouts collection currently empty).

## Iter 43 (2026-06) — Provider Ledger & monthly invoicing
- Admin menu "Provider Ledger" (/admin/ledger): provider list (patients served via Patient App, app services, extended services, month billable, promos, invoice status) → provider page tabs: Patients & services (all patient-app details per service), Invoices, Promotions, Billing terms. Review queue /admin/ledger/review, Trata invoice settings /admin/ledger/settings.
- Provider console "Trata Patients & Billing" (/provider/ledger): add extended services (pending review), see shared invoices.
- Extended services: manual or AI-filled from bill (Gemini 2.5 Flash), proof docs mandatory (Emergent Object Storage, ledger_files). Admin entries auto-approved; provider entries need admin approval (amount adjustable).
- Fees: % per provider + per-category overrides; flat promotion fees; only completed app services are billable. Invoice: SAC (manual), 18% GST (CGST+SGST same state via GSTIN code/state else IGST), place of supply, branded PDF (xhtml2pdf), share → provider console + Supabase notification, paid, void (not for paid). One active invoice per provider-month (unique index); sequential numbers.
- Data: Mongo ledger_* + billing_profiles; Supabase read-only (ledger_sb.py bulk parallel queries, ~4s, cached 45s).
- Tests: tests/test_provider_ledger.py + test_ledger_fixes_iter14.py (59 pass). Reports iteration_13/14.

## Iter 44 (2026-06) — Billing automation + Lab split prep
- Email (Emergent managed Resend, emailer.py): invoice email on Share (summary + "View & download" link; managed email has no attachment support); delivery log on invoice.
- Overdue reminders: shared invoices past due (IST) → CRM notification + email every 3 days until paid (cron daily 10:00 IST, /api/cron/invoice-reminders; manual /api/ledger/run/reminders).
- Monthly auto-raise: 1st of month 06:00 IST → DRAFT invoices for last month (/api/cron/monthly-invoices; manual /api/ledger/run/monthly-drafts). Drafts get number on "Issue & share"; Discard = void. Needs default SAC in settings.
- Revenue dashboard /admin/ledger/revenue: month-by-month fees, CGST/SGST/IGST, invoiced/paid/unpaid/overdue, outstanding by provider, drafts list.
- Crons: /app/.emergent/crons.yml (WEBHOOK_CRON_SECRET, idempotent via cron_runs.run_id).
- Lab split: onboarding offers Lab Partner / Imaging & Diagnostics (vertical=pathology + lab_kind). sb.lab_split_live() auto-detects the 4 new tables (10-min cache) → writes path_lab_profiles/diagnostic_centre_profiles + branches, approves via is_verified, ledger + patient timeline read path_lab_bookings/diagnostic_bookings. Split SQL paths UNTESTED until tables exist. Ack + 8 schema concerns: /app/memory/LAB_SPLIT_CRM_ACK.md.
- Tests: tests/test_ledger_billing_addons.py (27 pass) + previous ledger suites. Report iteration_15.json.

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

## Iteration 16 — Receipts, Collections Forecast, Statements (Oct 2026)
- Mark paid → Record-payment dialog (date ≥ invoice date & ≤ today, mode, UTR ref, note). Stores `invoice.payment` (receipt_no `RCPT/<inv no>`), auto-sends branded receipt email (Resend) + CRM notification (`invoice_receipt`). Receipt PDF: `GET /api/ledger/invoices/{id}/receipt`.
- Official Trata Health logo (`backend/assets/trata-logo.png`, web copy `/brand/trata-doc-logo.png`) on invoice, receipt and statement PDFs + all billing emails (`ledger_docs.py`).
- Revenue dashboard: Collections forecast (`GET /api/ledger/forecast?days=30`) with Weekly / Day-by-day / Total toggle + overdue.
- Statement (`GET /api/ledger/statement[?uid=&from=&to=]`, `/statement/pdf`): running balance, opening/closing, date filter, PDF; provider console tab + admin per-provider tab.
- Fixed: split-lab onboarding 500 (asyncpg param casts in `supabase_db.create_provider_from_admin`).
- Tests: `tests/test_ledger_receipts_statement.py` (21/21), addons suite updated for split lab tables.

### Backlog
- P1: Partial payments / credit notes; PUBLIC_APP_URL env for email links
- P2: Phase 9 Manager Intelligence; split server.py & ledger.py into routers
- P3: Patient App webhooks; shared JWT identity

## Iteration 17 — ABDM Milestone 1 (ABHA) (Oct 2026)
- `backend/abdm.py` router `/api/abdm/*`: gateway session (cached), RSA-OAEP(SHA-1) encryption with ABHA public cert, ABHA creation via Aadhaar OTP (+ comm. mobile verify, address suggestions/creation), ABHA verification by ABHA number / ABHA address / mobile (multi-account pick) / Aadhaar, ABHA card PNG/PDF, per-owner `abha_records`, `abdm_audit` log, `abdm_txns` (server-side X-tokens, 2h TTL index). Aadhaar/OTP never stored.
- ALL ABDM traffic goes via India egress proxy `ABDM_PROXY_URL` (user's DigitalOcean squid) — ABDM geo-blocks non-Indian IPs. Env: ABDM_CLIENT_ID, ABDM_CLIENT_SECRET, ABDM_GATEWAY_URL, ABDM_ABHA_URL, ABDM_CM_ID=sbx.
- Access: providers (own records) + Trata internal staff (shared 'trata' pool; master admin sees all). Sales reps 403.
- Frontend `/abha` page (nav "ABHA (ABDM)" for admin + providers): Create wizard w/ NHA consent text, Verify wizard, records table.
- Verified against live ABDM sandbox with fake values (UIDAI/ABDM errors returned) — real happy path needs a real Aadhaar/ABHA with OTP (user to test).
### ABDM backlog
- P0 after deploy: register bridge URL (PATCH /bridge/url) + add HIP services per facility (HFR IDs) — needed for M2
- P1: M2 HIP — care-context linking, consent notify, FHIR bundles (discharge summary, diagnostic report, OP consult/prescription, invoice)
- P2: M3 HIU; scan-and-share (ABHA QR) at front desk

## Iteration 18 — ABDM M2 (HIP) + ABHA QR check-in + ABHA badges (Oct 2026)
- Option-B architecture (see /app/memory/ABDM_OPTION_B_CRM.md): CRM = facility IN0910034478; callbacks forwarded from api.tratahealth.com to crm.tratahealth.com /api/v3/*; outbound stamped X-HIP-ID/X-HIU-ID via India proxy. Never change bridge URL.
- `backend/abdm_hip.py`: record sweep from Supabase (discharge_summaries, consultation_bookings COMPLETED, path_lab/diagnostic bookings with reports, prescriptions, paid bills) → `abdm_care_contexts`; HIP-initiated linking (generate-token → on-generate-token → link/carecontext → link/on_carecontext); user-initiated discover/init/confirm (OTP shown to staff — SMS MOCKED); consent notify (stored, on-notify ack); HI request → FHIR bundles (`abdm_fhir.py`, NRCES profiles) encrypted with abdm-ecdh (Fidelius-compatible) → push to dataPushUrl → notify. Consent enforced (status, hiTypes, date ranges, dataEraseAt, patient match). Inbound callbacks verified with ABDM gateway JWT (JWKS cached in Mongo `abdm_meta`).
- Auto-link: on discharge (hook), on ABHA↔patient link, cron every 15 min (`/api/abdm/cron/sync`), and "Sync now".
- QR: html5-qrcode camera scanner (`AbhaQrScanner`) on /abha, Hospital Command Center (admit form + admissions ABHA column), provider Add-extended-service form; `/api/abdm/records/from-qr` (not OTP-verified, never downgrades).
- ABHA badge + per-patient shared-records panel on PatientDetail; admissions table ABHA column.
- Tests: tests/test_abdm_m2_hip.py (49 pass, signed test JWTs).
### Blockers / next
- India proxy 68.183.247.212:3128 currently timing out → no live ABDM round trips; needs CRM proxy user from Trata ABDM admin.
- Deploy at https://crm.tratahealth.com for gateway forwarding; ask Patient team to send a test callback.
- SMS provider for patient-initiated link OTP; M3 HIU flows.

## Iteration 19 — Bulk suspend/delete, Network→Activities merge, live badge (Oct 2026)
- Trata Users (/contacts): master-admin checkboxes + bulk bar (Suspend / Restore access / Delete) with reason dialog; "Deleted users" view with Restore and days-left. Backend `user_admin.py`: POST /api/admin/users/bulk, GET /api/admin/users/archived, cron POST /api/admin/cron/erase-archived (daily; erases 30 days after delete: profile rows removed, users row deleted or anonymised if FK history).
- Supabase users new columns: is_suspended, suspended_at, suspended_reason, suspended_by, purge_after. Contract for Provider/TrataX: /app/memory/SUSPENSION_CONTRACT.md.
- CRM enforcement: suspended providers get 423 on every API except /auth/me|logout|refresh; frontend shows full-screen SuspendedScreen (reason, auto-refresh). Deleted users blocked at login with clear message. /auth/me reads back Supabase is_suspended. Emails on suspend/restore (Resend).
- Network page merged into Activities (Live chips: Emergency cases, Patients, KYC manager, Network stats; admin only); /network redirects.
- Header badge now shows LIVE · shared DB (was misleading "DEMO DATA" tied to unused legacy Admin-App REST sync).
- Tests: tests/test_user_admin_bulk.py (27 pass), test_user_admin_erase_cron.py.

## Iteration 20 — Unified Provider-app onboarding + Internal Entities (Jun 2026)
- New dropdown onboarding modal (`ProviderAppOnboardModal.jsx`) replaces the old one on Contacts AND Agent Leads; all Provider-app roles with their own sign-up forms.
- `provider_onboard.py`: onboarding runs as a background job (`POST /api/admin/provider-app/onboard` → poll `GET .../onboard/{job_id}`) because hospital sign-ups take ~50s upstream. Any CRM staff can onboard; sales agents get auto-assigned. Account = Pending KYC (Provider app self-signup). Welcome email via Resend when an email is given. Contact name = business name, `contact_person` = person.
- Internal entities: `EntitiesPanel.jsx` on ContactDetail (master admin + assigned agent; `/api/admin/provider-app/contact-entities?contact_id=`) and provider portal "My Entities" (`/provider/entities`, `/api/provider/entities`). Proxies Provider app `/api/org/*`; org lookups cached in memory.
- Tested: iteration_20.json (backend 16/16, frontend pass); minor follow-ups fixed (remove busy/error state, task refs + stale-job timeout, business-name contacts, "Pharmacie" label).
- Backlog unchanged: Phase 9 Manager Intelligence (P2), Patient App webhooks (P3), shared JWT identity (P3), split server.py.

- ABDM rule: CRM must never change the shared bridge callback URL (Patient app owns it) — see ABDM_OPTION_B_CRM.md

## Iteration 21 — Bulk Entity Import (Jun 2026)
- "Bulk import" on EntitiesPanel (contact page for master admin/assigned agent + provider "My Entities"). Excel/CSV parsed in-browser (SheetJS 0.20.3 from cdn.sheetjs.com), template download (headers sheet + separate example sheet), friendly header/type aliases.
- Editable preview with live validation (required fields, phone, pincode, email, allowed types, duplicate phones in file / already used), visible Problems column; "Import N ready, save M to Pending".
- Backend (`provider_onboard.py` `_entity_routes`): `POST {base}/bulk` (re-validates + dupes server-side, background job), `GET {base}/bulk/{job_id}` (stale guard 180s), Pending CRUD `GET/PUT/DELETE {base}/pending[/{id}]`, `POST {base}/pending/{id}/import`. Mongo: `entity_import_jobs`, `entity_import_pending`. Upstream-rejected rows auto-go to Pending.
- Tested: iteration_21.json; all follow-ups fixed (422 on bad rows, server dupe checks, friendly errors, inline problems, template example separated).

## Iteration 22 — ABDM Scan & Share, facility side (Jun 2026)
- `abdm_share.py`: inbound `POST /api/v3/hip/patient/share` (gateway JWT verified, 200 ack) → saves profile → `on-share` with token (sequential per hospital per IST day, valid till IST midnight, same ABHA same day = same token; atomic + per-ABHA lock). Unknown counter → on-share error.
- One QR per hospital: `GET /api/abdm/share/qr` (counter code `TH…` in `abdm_share_counters`; QR URL `ABDM_SHARE_QR_BASE?hip-id=IN0910034478&counter-id=…`). `GET /api/abdm/share/profiles?date=` (hospital own / staff all).
- Shared profile upserts Mongo `abha_records` (owner=hospital) + Supabase `hospital_patients` (match by ABHA no/address or phone+name, status 'registered', abha_kyc merged). No queue UI (user choice).
- UI: `ScanShareCard.jsx` on /abha (QR + print poster + today's shares; admin sees all hospitals).
- Tested iteration_22 (backend 11/11, frontend pass); poster size + token race fixed after.

## Iteration 23–24 — Pharmacy as full provider CRM, entity logins + summaries (Jun 2026)
- Pharmacy logins unblocked (Supabase role pharmacy/pharmacist → provider_type pharmacy). Pharmacy side menu: My Dashboard (PharmacyDashboard via ProviderHome), Medicine Orders, Prescriptions, Stock, Sales (`/pharmacy/:tab`), My Entities (chains). Admin/hospital have NO pharmacy menu; `/api/pharmacy-console/*` is pharmacy-provider only (own store + chain branches; store picker when >1).
- `pharmacy.py`: orders = Supabase `medicine_orders` (PENDING_PHARMACY/PREORDER_PENDING→ACCEPTED→FULFILLED, REJECTED; timeline events via crm); prescriptions & stock proxied to Provider app `/api/pharmacy/*`; open prescriptions (pharmacy_id NULL) are claimed atomically on accept; sales KPIs.
- Entities: CRM-created entities mirror into contacts (kyc pending, parent link, inherited agent) + master-admin notification `entity_onboarded` + welcome email; Provider-app signups notify via contacts sync; removed entity phones blocked at login; removal flags contact `entity_removed`. Child units cannot run their own chain (403 + nav hidden via `parent_org_name` on /auth/me). Ambulance providers can now have entities (root 'ambulance'). Doctors: Provider app rejects root_kind 'doctor' — needs Provider app change.
- My Entities: entity name opens `/provider/entities/:id` summary dashboard (metrics by kind, KYC, login, activity). Section renamed "My Entities".
- Headings use `business_name` (from /auth/me) not the person's name. Notifications filtered by role.
- Tested: iteration_23/24 (backend 20/20, frontend pass); follow-ups fixed.

## Iteration 25 — Pharmacy new-order alerts + expiry/reorder lists (Jun 2026)
- `NewOrderAlerts.jsx` (mounted in Layout for pharmacy providers): polls `GET /api/pharmacy-console/orders/new?since=` every 10s (first call returns DB clock), pop-up card bottom-right + 3-note chime (WebAudio), View order / dismiss, mute toggle (localStorage `trata_order_alert_muted`), dispatches `trata:new-order` so the dashboard/orders refresh. Medicine orders only (user choice).
- `GET /api/pharmacy-console/stock-actions?days=60`: expiring list (days left, value at risk) + reorder list (suggested = last-30-day sales + reorder level − stock; no sales → 2× reorder level), est. cost; `unreachable_stores` surfaced in UI. Stock page sub-tabs All / Expiring soon / Reorder list (+ CSV download).
- Tested iteration_25 (backend 11/11, frontend pass); follow-ups fixed (immediate poll, DB clock, retry + warnings, exact name match, malformed expiry guard).

## Iteration 26 — Gap-free change capture (Step 1 of full sync) (Jun 2026)
- `audit_log.py`: installs schema `trata_audit` on the SHARED Supabase: `activity_log` (bigserial id, txid xid8, table, op, row_id, app, db_role, old/new jsonb diff, changed[]), `clean()` masks secrets/blobs/sensitive text, SECURITY DEFINER `capture()` AFTER trigger (never blocks app writes). Attached to 12 key tables: users, emergency_cases, consultation_bookings, medicine_orders, prescriptions, kyc_documents, user_consents, consultation_payments, pathology_bookings, ambulance_bookings, patient_admissions, at_home_care_bookings.
- API (master admin): `GET /api/admin/activity-log` (newest page / `after_txid` catch-up that walks finished txns below pg_snapshot_xmin → no skipped slow commits), `/health` (covered tables, 24h counts, untracked tables with data, source apps), `POST /install {tables}` (idempotent).
- UI `/admin/audit` "Live Audit": Sync health + one-click "track" for untracked tables, live feed (10s), filters, expandable old→new diff.
- App attribution: Supavisor hides application_name → source "unknown" unless apps run `SET LOCAL trata.app = '<app>'` (or use Supabase client roles). Next steps: extend to all tables + auto-attach on new tables, app events outbox table, nightly reconciliation, monthly partitioning/retention, alerts.
- Tested: curl + screenshot (testing agent not yet run).


## 2026-06 — Audit recorder everywhere + app-scoped admin menu
- Recorder auto-attached to every public table (~271) except noisy/secret ones (NOISY_RE in `audit_log.py`: kv caches, callback/outbox queues, chats/messages, OTP/token stores, GPS pings).
- Postgres event trigger `trata_audit_auto_attach` tracks any new table the moment any app creates it; startup sweep in `server.py` attaches anything missed.
- Feed `GET /api/admin/activity-log?scope=patient|provider` (table classification PROVIDER_RE; `users` in both); repeatable-read snapshot for gap-free cursor.
- Master admin sidebar grouped: Patient app (Patient Activity, Patients, ABHA) / Provider app (Provider Activity, Onboarding, KYC, Ledger) / Sales & team.
- Retention: keep forever (no cleanup job).
- PARKED by user: shared app event log (logins, OTP attempts, failed payments).
- Still pending: PWA push notifications + sound alerts for master admin.

## 2026-06 — Master-admin alerts, record history, morning digest
- Push alerts (`admin_alerts.py`): Web Push using app-generated signing keys (VAPID_* in backend/.env); subscriptions in Mongo `push_subscriptions` with per-device prefs (kyc/signup/order/sos). A watcher follows the audit cursor (Mongo `alert_state`) every 10s, groups each batch by type and pushes. SW: `public/push-sw.js` (imported by service-worker.js; registered on its own in dev). In-console chime + toast (`AlertListener`). Settings card `AlertSettingsCard` (master only).
- Record history: `activity_log.refs` (all id-like values, GIN index) + `GET /api/admin/activity-log/record/{id}` oldest-first with one hop via profile rows. History tab on /admin/patients/:id and /admin/onboarding/:id (master only).
- Morning digest: cron `admin-morning-digest` 8:00 IST -> `POST /api/cron/admin-digest`; GPT-5.4 via Emergent LLM key; Mongo `admin_digests`; dashboard card `MorningDigest` (Yesterday / Today so far buttons).
- Audit/activity nav items hidden from non-master admins.
- Tests: backend/tests/test_admin_alerts_digest_history.py (26 pass), report iteration_26.

## 2026-06 — Split user directories
- /contacts = "All Users"; /users/patients = "Trata Patient Users" (Patient app section, no type tabs/onboard); /users/providers = "Trata Providers" (Provider app section, provider type tabs). Backend `audience=patient|provider` on GET /api/contacts and /api/export/contacts.csv.

- Digest highlights now counted from source tables by created_at: signups (patient/customer users), doctor_appointments, pathlab_bookings, diagnostics_bookings, pharmacy_orders, sos (DIGEST_METRICS in admin_alerts.py).

- Digest: day-over-day arrows (stats.previous), chips link to /admin/summary/:metric?date= (DigestRecords page, GET /api/admin/digest/records). "Patients" nav removed from Patient app section (route kept; patient contact detail links to /admin/patients/:supabase_user_id).

## 2026-06 — Rename + provider access requests
- All UI/API/email text "Master Admin" -> "Trata Health Admin" (Mongo history migrated; crm_users name updated). Dashboard heading "Admin Dashboard".
- access_requests.py: public GET /api/public/providers/search, POST /api/public/access-requests (name, phone, role provider_admin|provider_staff, provider entity, note; dup-pending 409, 5/h per IP (3rd-from-right XFF hop) + 60/h global). Creates Mongo notifications (audience master_admin, kind access_request) + push kind "access".
- Notification Centre /admin/notifications (master only): All feed with read state (read_by), Access requests tab with Approve/Decline/Open provider. Bell links to it. Approve only marks the request; account creation is still done on the provider page.

## 2026-06 — Doctor dashboard fix
- Root cause: demo provider rows (users + doctors etc.) for 900002000x were removed from shared Supabase before audit tracking began; re-ran POST /api/admin/seed-demo-accounts to restore. Generic provider dashboard now falls back to the users row (profile_incomplete banner) when the vertical profile row is missing.
- Known: pathology demo mirror fails (pathologists table is now read-only; canonical path_lab_* tables).

## 2026-06 — Doctor appointments
- doctor_appointments.py: GET /api/provider/doctor/appointments (doctor_appointments, consultation_bookings, teleconsultation_bookings, appointments; doctor_id matches users.id or doctors.id), POST .../{source}/{id}/status (completed|no_show|cancelled, atomic), GET .../patients/{pid}/visits. UI: DoctorAppointments on doctor dashboard + /provider/appointments (doctorOnly nav) with patient side sheet.
- My Activities tabs filtered per vertical (VERTICAL_ACTIVITY_CATEGORIES).
- TEST rows for Dr. Meera (9000020006) in doctor_appointments with reason "TEST — fever and cough".

## 2026-06 — Doctor consultation notes & prescriptions
- Stored ONLY in shared Supabase consultation_ehr (contract: memory/CONSULTATION_EHR_CONTRACT.md). One row per appointment (uuid5), falls back to a Provider-app-created row (non-v5 id) for same patient+doctor+IST day. status draft -> signed on Share; private notes in `notes`; Share inserts Supabase notifications (consultation) for the patient if a users row exists.
- Endpoints GET/PUT /api/provider/doctor/appointments/{source}/{id}/consult, POST .../consult/share. UI ConsultEditor (Save / Save & mark completed / Share / Print), print page /provider/rx/:source/:id (no layout).
- Patient app must show only status=signed rows and never `notes` (needs Patient app dev work).

## 2026-06 — User directories from shared users table
- /users/providers = ProviderDirectory (GET /api/admin/directory/providers; one row per account, same-name placeholder accounts merged as linked_accounts; KYC filter groups). Row -> /admin/onboarding/:id which now shows ProviderDetailsCard (account, vertical profile, TrataX KYC application, documents); staff roles show no checklist (kyc_enabled false).
- /users/patients = Patients page (Supabase users, one per account) -> /admin/patients/:id. Both nav items master-only. Contacts-based audience lists no longer used in nav.
