# TABLE PARITY CHECKLIST — TEAM: Tratax-CRM (PC console + master admin)
DATE: 2026-10-03 (filled against shared Supabase after full schema + code audit)

LEGEND: R/W = Read / Write · Match = Y when CRM uses the SAME table as the patient app for that flow.
Note: CRM = web PC console for providers + master admin. It authenticates against CRM-local Mongo (bcrypt JWT)
AND reads/writes the shared Supabase directly. "users" below = shared Supabase `public.users`.

================================================================
A) DISCOVERY (patient READS; we WRITE the provider record)
================================================================
| # | Flow | PATIENT table + filter (authoritative) | CRM table | CRM filter/flags | R/W | Match |
|---|---|---|---|---|---|---|
| A1 | Find Hospital | `hospital_profiles` — verified + location{lat,lng} | `hospital_profiles` | onboard: `verification_status='pending'`; approve-all → `'approved'` (should move to `'verified'`); **location NOT written** | R+W | ⚠️ PARTIAL — same table, but we never set `location` and use `'approved'` instead of target `'verified'`. Pending rows could leak into `nearby-hospitals` (which has NO status filter). |
| A2 | Find Doctor | `doctors` — is_active=true, is_verified | `doctors` | onboard: `is_active=true, is_verified=false`; approve-all → `is_verified=true` | R+W | Y |
| A3 | Specialists | `hospital_specialists` (+`doctors`) | n/a — CRM does not write specialists today | — | — | n/a (gap to build) |
| A4 | Path labs / Diagnostic centres | `labs` + `pathologists` — is_active=true AND status='approved' + location | `pathologists` only | onboard: `is_active=true, status='pending'`; approve-all → `status='approved'`; **location NOT written; `labs` never written** | R+W | ⚠️ PARTIAL — `pathologists` matches, but `labs` rows are never created, so diagnostic centres registered as pure labs are invisible in CRM; and without `location` our rows fail the distance query. |
| A5 | Pharmacies | (none today — Google Places only) | `pharmacy_profiles` (legacy onboard insert only; PC console blocked for pharmacies by product decision) | n/a | W (legacy) | n/a until patient team picks canonical pharmacy table |
| A6 | Paramedics (at-home) | `paramedic_profiles` | `paramedic_profiles` (legacy onboard insert only; PC console blocked for paramedics by product decision) | n/a | W (legacy) | Y (dormant) |
| A7 | Nurses (at-home) | (no provider directory today) | n/a | — | — | n/a |
| A8 | Ambulance providers | `ambulance_providers` (+`ambulances`) | `ambulance_providers` (+ `ambulances` read-only in command centre) | onboard: `status='pending'`; approve-all → `status='approved'`, `approved_at`; location NOT written | R+W | ⚠️ PARTIAL — same table; need location + confirm visibility flags with patient team before they see the row. |

================================================================
B) BOOKINGS (patient WRITES; we READ to fulfil)
================================================================
| # | Service | PATIENT writes table | CRM table | R/W | Match |
|---|---|---|---|---|---|
| B1 | Teleconsultation (video) | `teleconsultation_bookings` | n/a | — | n/a (gap) |
| B2 | In-person / OPD | `consultation_bookings` (note: `appointments` also exists) | `appointments` (patient-detail timeline + association queries) | R | **N — SYNC BREAK**: patient OPD bookings land in `consultation_bookings`; CRM reads `appointments`. We never see their OPD bookings. Converge: CRM should read `consultation_bookings`. |
| B3 | Lab / diagnostic test | `pathology_bookings` (note: `lab_bookings`, `lab_test_bookings` also exist) | n/a | — | **N — SYNC BREAK**: CRM never reads `pathology_bookings`; lab orders invisible on PC console. |
| B4 | At-home care | `at_home_care_bookings` (note: `nurse_bookings` also exists) | n/a | — | n/a (gap) |
| B5 | Ambulance | `ambulance_bookings` | `ambulance_bookings` (patient detail timeline) | R | Y |
| B6 | Vaccination | `vaccination_bookings` | n/a | — | n/a (gap) |
| B7 | Wellness / retreat | `wellness_bookings` | n/a | — | n/a (gap) |

================================================================
C) DOCUMENTS / REPORTS (bidirectional)
================================================================
| # | Flow | PATIENT table | CRM table | R/W | Match |
|---|---|---|---|---|---|
| C1 | Patient → Doctor: share reports | `ehr_share_requests` | n/a | — | n/a (gap) |
| C2 | Doctor → Patient: notes/EHR | `consultation_ehr` | n/a | — | n/a (gap) |
| C3 | Hospital → Patient: admission docs | `patient_admissions` + `admission_notes` | `patient_admissions` + `admission_notes` (command-centre admit flow writes both) | R+W | Y |
| C4 | Hospital → Patient: discharge summary | `discharge_summaries` | n/a (discharge only flips status on `patient_admissions` + frees bed) | W (indirect) | **N — SYNC BREAK**: we never write `discharge_summaries`, so discharged patients see no summary on their app. |
| C5 | Prescriptions | JSON column (NO `prescriptions` table) | n/a | — | n/a |
| C6 | Lab result files | `pathology_bookings` / `ehr_records` | `ehr_records` (health-check count only) | R (count) | ⚠️ partial — no real reads of result payloads |
| C7 | General EHR / health docs | `ehr_records` | `ehr_records` (count only) | R (count) | ⚠️ partial |
| C8 | Consultation payments | (no table on patient side) | n/a | — | n/a |

================================================================
D) EMERGENCY / SOS
================================================================
| # | Flow | PATIENT table | CRM table | R/W | Match |
|---|---|---|---|---|---|
| D1 | Emergency SOS case | `emergency_cases` | `emergency_cases` (command centre list, accept/reject/complete, SSE stream) | R+W | Y |
| D2 | Ambulance allocation / live tracking | `ambulance_allocations` | n/a (CRM reads allocation info off `emergency_cases.ambulance_provider_id` + `ambulances`) | R (indirect) | **N — SYNC BREAK**: should read/write `ambulance_allocations` for live tracking parity. |
| D3 | Hospital admit trigger | REST to provider API (not a DB table) | Direct DB write — `admit_from_case` inserts `patient_admissions` + `admission_notes` + `hospital_cases` (the PC console IS the provider surface the patient app calls) | R+W | Y (equivalent effect) |

================================================================
E) OTHER CROSS-APP SERVICES
================================================================
| # | Flow | PATIENT table | CRM table | R/W | Match |
|---|---|---|---|---|---|
| E1 | Second opinion | `second_opinion_records` | n/a | — | n/a (gap) |
| E2 | Health camps | `health_camps`, `health_camp_participants` | n/a | — | n/a (gap) |
| E3 | Corporate health | `companies`, `company_employees`, `corporate_emergencies` | n/a | — | n/a (gap) |
| E4 | Insurance documents | `insurance_documents` | n/a | — | n/a (gap) |
| E5 | Hospital reviews | `hospital_reviews` | n/a | — | n/a (gap) |
| E6 | KYC documents | `kyc_documents` | `kyc_documents` (provider self-upload + admin proxy-upload + one-click approve; `uploaded_by_role`/`[Admin]` name tag distinguishes origin) | R+W | Y |
| E7 | Subscriptions & payments | `subscription_plans`, `user_subscriptions` | n/a | — | n/a (gap) |
| E8 | Post-discharge recovery | `recovery_plans`, `recovery_checkins`, `treatment_activities` | n/a | — | n/a (gap) |
| E9 | Maternal / mom-baby | `maternal_journeys`, `journey_milestones` | n/a | — | n/a (gap) |
| E10 | Bed availability | `hospital_beds`, `hospital_bed_inventory`, `bed_status_logs` | `hospital_beds` (create/update/delete) + `bed_status_logs` (audit trail) | R+W | ⚠️ PARTIAL — we never write `hospital_bed_inventory`; if patient app renders aggregated availability from that table it will not reflect our bed CRUD. |

================================================================
F) IDENTITY & ENUMS
================================================================
| # | Item | PATIENT reality | CRM value | Match |
|---|---|---|---|---|
| F1 | Users table | `users` | shared Supabase `users` (+ CRM-local Mongo `crm_users` for CRM console login) | Y |
| F2 | Auth / token | OTP + user_id param; NO JWT middleware | OTP (Twilio mock `123456` in dev) + bcrypt password + HMAC JWT for CRM console sessions | ⚠️ divergent — as patient team notes, shared JWT is net-new joint work |
| F3 | JWT secret env | none on patient; others use SUPABASE_JWT_SECRET | `JWT_SECRET` (CRM console) — will align to `SUPABASE_JWT_SECRET` when joint identity lands | ⚠️ |
| F4 | verification_status enum | writes 'verified'/'pending'; reads 'verified'/'approved' | writes 'pending' → 'approved' (onboard + approve-all) | **N — converge**: switch approve-all to write `'verified'` (target enum). Patient browse already accepts legacy 'approved' so this is safe to migrate. |
| F5 | lab/pharmacy visibility enum | is_active (bool) + status='approved' | pathologists: `is_active=true` + `status='pending'→'approved'` | Y for pathologists; `labs` rows never created (see A4) |
| F6 | Realtime | none (REST/polling) | FastAPI SSE push for command centre (`/api/provider/command-center-stream`) | ⚠️ CRM-side only; no impact on patient app. Agree REST/polling as the cross-app contract. |

================================================================
SYNC BREAKS SUMMARY (Match=N — converge BEFORE the affected flow is built)
================================================================
1. **B2 — OPD bookings**: patient writes `consultation_bookings`, CRM reads `appointments`. FIX: CRM reads `consultation_bookings` (patient table wins).
2. **B3 — Lab bookings**: CRM never reads `pathology_bookings`. FIX: add to provider dashboard + patient timeline.
3. **C4 — Discharge summaries**: CRM discharge flow must write `discharge_summaries` (currently only flips admission status + frees bed).
4. **D2 — Ambulance allocation**: CRM must read/write `ambulance_allocations` instead of inferring from `emergency_cases.ambulance_provider_id`.
5. **F4 — verification enum**: switch CRM approve-all to `'verified'` (keep reading 'approved' during transition).
6. **A4 — Diagnostic centres**: CRM writes `pathologists` only; patient discovery reads `labs` + `pathologists`. FIX: onboard pathology also INSERTs a `labs` row (is_active=true, status='approved' after KYC, with location) — **this is also why "Diagnostic Centre" never appears as a user type in the CRM** (no `labs` rows synced).
7. **A1/A4/A8 — location**: onboarded hospitals/labs/ambulances must carry `location={lat,lng}` — pending hospitals without location leak into `nearby-hospitals` (which has NO status filter) and approved labs without location never pass the distance query.
8. **E10 — bed inventory**: mirror bed counts into `hospital_bed_inventory` on every bed CRUD so patient-side availability stays accurate.

================================================================
ADDITIONAL CRM-SIDE NOTES FOR PATIENT TEAM
================================================================
- `crm_provider_leads` is a CRM-owned mirror table (safe to ignore; tratax_*-style).
- CRM archives test users with `is_archived=true` + `archived_reason='test_user_cleanup'`; both mobile apps should keep honouring `is_archived` / a future `is_demo` flag (per your enum standard) in discovery queries.
- CRM writes `hospital_staff` (care team) and `hospital_cases` + `case_chats` (command centre) — patient team: confirm if these tables have patient-side readers; if not, mark as provider-internal.
- `paramedic_profiles` + `pharmacy_profiles` legacy onboard inserts exist in CRM code but are dormant (paramedics/pharmacies are mobile-app-only by product decision).
