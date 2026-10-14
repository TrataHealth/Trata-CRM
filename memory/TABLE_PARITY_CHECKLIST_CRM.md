# TABLE PARITY CHECKLIST — TEAM: Tratax-CRM (PC console + Master Admin)
DATE: 2026-06 (re-verified against CRM code + live shared Supabase schema/data)

## A) DISCOVERY
| # | Flow | PATIENT | CRM table | CRM filter/flags | R/W | Match |
|---|---|---|---|---|---|---|
| A1 | Find Hospital | hospital_profiles — verified + location | hospital_profiles | onboard 'pending', NO location; approve-all → 'approved' (not 'verified') | R+W | N |
| A2 | Find Doctor | doctors — is_active, is_verified | doctors | onboard is_active=true,is_verified=false; approve → is_verified=true | R+W | Y |
| A3 | Specialists | hospital_specialists | n/a | — | — | n/a |
| A4 | Labs / Diagnostic | labs + pathologists — is_active AND status='approved' + location | pathologists (W), labs (R only) | pathologists: is_active=true, status pending→approved, NO location; labs: never written | R+W | N |
| A5 | Pharmacies | none | pharmacy_profiles (legacy, dormant) | — | W | n/a |
| A6 | Paramedics | paramedic_profiles | paramedic_profiles (legacy, dormant) | — | W | Y |
| A7 | Nurses | none | n/a | — | — | n/a |
| A8 | Ambulance | ambulance_providers (+ambulances) | ambulance_providers (+ambulances R) | status pending→approved; business_lat/lng NOT written | R+W | Partial |

## B) BOOKINGS
| B1 teleconsultation_bookings | n/a | — | n/a |
| B2 consultation_bookings | appointments | R | N |
| B3 pathology_bookings | n/a | — | N |
| B4 at_home_care_bookings | n/a | — | n/a |
| B5 ambulance_bookings | ambulance_bookings | R | Y |
| B6 vaccination_bookings | n/a | — | n/a |
| B7 wellness_bookings | n/a | — | n/a |

## C) DOCUMENTS
| C1 ehr_share_requests | n/a | — | n/a |
| C2 consultation_ehr | n/a | — | n/a |
| C3 patient_admissions + admission_notes | same | R+W | Y |
| C4 discharge_summaries | n/a (status flip only) | — | N |
| C5 prescriptions JSON | n/a | — | n/a |
| C6 lab result files | ehr_records (count) | R | Partial |
| C7 ehr_records | ehr_records (count) | R | Partial |
| C8 consultation payments | n/a | — | n/a |

## D) EMERGENCY
| D1 emergency_cases | emergency_cases | R+W | Y |
| D2 ambulance_allocations | n/a (inferred from emergency_cases) | — | N |
| D3 admit trigger (REST) | direct DB write patient_admissions/admission_notes | W | Y (equivalent) |

## E) OTHER
E1–E5, E7–E9: n/a. E6 kyc_documents: R+W, Y. E10: hospital_beds + bed_status_logs R+W; hospital_bed_inventory never written → Partial.

## F) IDENTITY & ENUMS
| F1 | users | users (+Mongo crm_users for console login) | Y |
| F2 | OTP, no JWT | OTP + CRM JWT (console only) | N (joint work) |
| F3 | SUPABASE_JWT_SECRET | JWT_SECRET (CRM-local) | N |
| F4 | verified/pending | pending→approved | N |
| F5 | is_active + status='approved' | pathologists Y; labs has NO status column | N (contract conflict) |
| F6 | none | CRM-only SSE | Y (no cross-app impact) |

## Live schema facts contradicting contract
1. labs has no `status` and no `location` columns — only is_active, is_verified, latitude, longitude.
2. ambulance_providers has no `location` — uses business_lat / business_lng.
3. No table has an `is_demo` column yet.
4. Live hospitals: Xenon 'approved' (written by CRM), Sahayak 'verified', 2 pending — all 4 have location.
5. Row counts: consultation_bookings 3 vs appointments 1; pathology_bookings 2 (unread by CRM); discharge_summaries 0; ambulance_allocations 0; hospital_bed_inventory 0.


## CONVERGENCE APPLIED (2026-06, CRM side)
- A1 hospital_profiles: onboard writes location {lat,lng} + 'pending_review'; approve-all → 'verified' (+ users 'verified'). Live 'approved' rows migrated (0 left). Approval refuses without coords.
- A4 pathologists (status pending→approved, is_active, latitude/longitude/location) + labs branch row (pathologist_profile_id, is_active/is_verified false→true on approval).
- A8 ambulance_providers business_lat/business_lng on onboard + approval.
- A5 pharmacy_profiles code removed; reads use pharmacy_providers.
- B2 reads consultation_bookings (hospital_id there = hospital_profiles.id; scoped queries accept both ids). B3 reads pathology_bookings (patient detail + timeline).
- C4 discharge writes discharge_summaries row. D2 ambulance_allocations written on assign + status updates; read on ambulance dashboard.
- E10 hospital_bed_inventory recomputed on bed add/toggle/admit/discharge.
- Patients: patient app now uses role 'customer'/NULL (0 rows with role='patient') — CRM readers accept patient|customer|NULL.
- NOT done (per user): is_demo column — provider team owns. tratax_tenants: CRM never writes it.
