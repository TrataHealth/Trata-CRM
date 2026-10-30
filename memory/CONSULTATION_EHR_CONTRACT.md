# Doctor consultation record — shared data contract (Admin Console ⇄ Provider app ⇄ Patient app)

All three apps read/write the **same row** in the shared Supabase table `public.consultation_ehr`. Nothing about a doctor's notes or prescription is stored only in the Admin Console.

## One row per appointment
| Field | Meaning | Who sees it |
|---|---|---|
| `id` | Admin Console uses `uuid5(2b1f6a52-3c1e-4d1a-9a77-7d0c0e5a1e01, "<source>:<appointment_id>")`. If the Provider app already created a row for the same `patient_id` + `doctor_id` + consultation day (IST), the console edits **that** row instead. | — |
| `patient_id` | Patient-app `users.id` (from the booking's `patient_id` / `user_id`) | — |
| `doctor_id` | Doctor's `users.id` | — |
| `consultation_date` | Appointment day (IST midnight) | doctor, patient |
| `consultation_type` | `in-person` / `video` / booking mode | doctor, patient |
| `chief_complaint` | text | doctor, patient |
| `vitals` | json `{bp, pulse, temp, spo2, weight}` (strings) | doctor, patient |
| `diagnosis` | json array of strings; `primary_diagnosis` = first item | doctor, patient |
| `prescriptions` | json array `[{name, dosage, frequency, duration, instructions}]` | doctor, patient (after share) |
| `treatment_plan` | advice for the patient | doctor, patient (after share) |
| `investigations` | json array of test names | doctor, patient (after share) |
| `follow_up_date`, `follow_up_notes` | follow-up | doctor, patient (after share) |
| `notes` | **PRIVATE doctor notes — never show to the patient** | doctor only |
| `status` | `draft` = doctor still working, **not visible to patient**; `signed` = shared with patient | — |
| `signed_at`, `signed_by` | when / by whom it was shared | patient |
| `updated_at` | if `updated_at > signed_at` the doctor edited after sharing (console shows "share again") | — |

## Rules for the Patient app
- Show a consultation/prescription only when `status = 'signed'`.
- Never display `notes`.
- On share, the console inserts `public.notifications` → `notification_type='consultation'`, `data = {"kind":"prescription","consultation_ehr_id": <id>, "doctor_id": <id>}`. Deep-link to that record.

## Rules for the Provider app (doctor)
- List/edit rows by `doctor_id = <doctor users.id>`; same fields as above. Edits made in either app appear in the other immediately (same row).
- Appointment status changes (completed / no_show / cancelled) are written directly on the booking row (`doctor_appointments`, `consultation_bookings`, `teleconsultation_bookings`, `appointments`). For `consultation_bookings` / `teleconsultation_bookings` an entry `{status, at, by:"doctor", via:"admin_console"}` is appended to `status_history`.
