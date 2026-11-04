_Snapshot taken before the switch (2026-11-04). Legacy table frozen since then._

# Phase D parity report (§10)

## 1. Legacy rows without a users row: **0** PASS

## 2. Legacy rows without a canonical row
- hospital → hospital_profiles: 3 legacy rows, 0 missing PASS
- pathologist → path_lab_profiles: 1 legacy rows, 0 missing PASS
- doctor → doctors: 1 legacy rows, 0 missing PASS
- pharmacy → pharmacy_providers: 0 legacy rows, 0 missing PASS
- ambulance_provider → ambulance_providers: 1 legacy rows, 0 missing PASS

## 3. Column spot-check (up to 5 per type)
- hospital · City Care Hospital: DIFF → email: legacy='crm-sync@tratahealth.com' canonical=None; city: legacy='Bengaluru (mirrored via CRM)' canonical='Bengaluru'
- hospital · Tathastu Institute of Medical Sciences & Hospital emergency urologist/laparoscopic/Ortho/Gynecologist: DIFF → name: legacy='Tathastu Institute of Medical Sciences & Hospital emergency urologist/laparoscopic/Ortho/Gynecologist' canonical='Tathastu Institute of Medical Sciences & Hospital'; city: legacy=None canonical='Basti'; state: legacy=None canonical='Uttar Pradesh '
- hospital · Trata Ambulance Service: DIFF → name: legacy='Trata Ambulance Service' canonical='Xenon Multispeciality Hospital'; email: legacy='crm-sync@xenon.in' canonical=None; city: legacy='MUMBAI-MIRROR' canonical='Mumbai'; state: legacy='MH-MIRROR' canonical='Maharashtra'
- pathologist · Zenith Diagnostics: DIFF → city: legacy='Pune' canonical=None; state: legacy='Maharashtra' canonical=None
- doctor · Dr. Meera Clinic: match
- ambulance_provider · Sanjay Ambulance Fleet: match

## 4. Verified counts (legacy is_verified vs canonical)
- hospital: legacy 3 vs canonical 5 DIFF
- pathologist: legacy 1 vs canonical 1 PASS
- doctor: legacy 1 vs canonical 2 DIFF
- pharmacy: legacy 0 vs canonical 0 PASS
- ambulance_provider: legacy 1 vs canonical 2 DIFF
