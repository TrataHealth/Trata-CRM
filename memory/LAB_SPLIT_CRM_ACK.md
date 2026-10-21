# Trata CRM — Acknowledgement: Path Lab / Diagnostic Centre split
Team: Trata CRM (PC console + Master Admin) · Status: COMMITTED to cut over by D3 (already built, auto-switches)

## What the CRM has shipped (ready before D0)
- Auto-detect: CRM checks every 10 min whether path_lab_profiles, path_lab_bookings, diagnostic_centre_profiles, diagnostic_bookings all exist. When they do it switches reads/writes automatically — no CRM deploy needed on D1/D3.
- Onboarding (Master Admin): two separate heads — "Lab Partner" (path_lab) and "Imaging & Diagnostics Partner" (diagnostic_centre).
  - Before split: writes legacy pathologists + labs (labs.lab_type = path_lab | diagnostic_centre).
  - After split: writes users row + path_lab_profiles / diagnostic_centre_profiles (user_id = users.id, lat/lng, is_active=true, is_verified=false, is_demo=false) + one *_branches row. Never writes legacy tables after the switch.
- KYC approve-all after split: profile + branches → is_verified=true, is_active=true, needs_admin_review=false, coordinates kept.
- Reads after split: Provider Ledger and invoicing read path_lab_bookings / diagnostic_bookings (legacy pathology_bookings ignored, since migration preserves ids). The patient timeline reads both new booking tables.
- UI terms: "Lab Partners" / "Imaging & Diagnostics Partners".

## Schema concerns (please resolve before D0)
1. **Type mismatch:** users.id and organisations.id are VARCHAR in the live DB, not UUID, so `user_id UUID REFERENCES users(id)` will fail. Use VARCHAR/TEXT for user_id, organisation_id and patient_id (and the *_profile_id columns if legacy ids are not all valid UUIDs).
2. **Wrong migration source:** the live data sits in `pathologists` (68 rows), not `pathologist_profiles` (2 rows). pathology_bookings.pathologist_id and labs.pathologist_profile_id point to `pathologists.id`. The script must migrate from `pathologists`.
3. **labs.lab_type has more values than the plan expects:** pathology, path_lab, standalone_lab, hospital_lab → Path Lab? and diagnostic_centre, diagnostic_chain → Diagnostic Centre? Please confirm the mapping. Some labs rows have NULL pathologist_profile_id; say where those go.
4. **Booking status enum:** live pathology_bookings use 'pending' (not in the new CHECK). Please confirm a mapping such as pending→requested and completed→reported. Billing treats 'reported' as the billable final state.
5. **Booking columns dropped:** the new booking tables lose payment_status, booking_ref/booking_id, patient name/phone snapshot, home_collection_fee, discount_amount and collection_address. The CRM's monthly invoicing and the patient timeline use them. Please keep payment_status, a human booking ref, and fee/discount breakdown columns.
6. **Patient visibility rule:** please confirm it is is_active AND is_verified AND NOT is_demo AND valid lat/lng. The old contract used pathologists.status='approved', and the new tables have no status column.
7. **users.role for the new heads:** today it is 'pathologist' for both. Will it stay, or become 'path_lab' / 'diagnostic_centre'? The CRM identifies heads by table, so either works, but other apps' role checks may not.
8. **Write ownership:** the tables are "owned by Provider app". The CRM will write NEW onboarding rows directly (agreed earlier: CRM owns new org onboarding). Please make sure the D2 read-only triggers apply only to the legacy tables.
