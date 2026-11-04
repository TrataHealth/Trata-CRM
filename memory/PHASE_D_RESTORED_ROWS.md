# Phase D — rows restored after the overwrite incident

Overwrite window: 2026-11-04 ~10:05–10:19 UTC (CRM users-mirror echoing display fields). Restored 2026-11-04 10:23 UTC from trata_audit.activity_log (earliest old_data in the window).

| Table | Row id | user_id | Name now | Restored fields (restored value ← overwritten value) |
|---|---|---|---|---|
| hospital_profiles | 7f8ae047-a46d-4930-826a-ada8e215bea0 | 2d71f195-7f5a-454b-962d-ee944cebe8cf | Xenon Multispeciality Hospital | city: 'Mumbai' ← 'Mumbai Suburban'; name: 'Xenon Multispeciality Hospital' ← 'Trata Ambulance Service'; email: None ← 'crm-sync@xenon.in'; address: 'Om Sai Charan CHS Ltd, Link Rd, opposite Aura Restaurant, Yogi Nagar, Borivali West, Mumbai, Maharashtra 400091, India' ← 'Dahanukar Wadi, Kandivali, Kandivali West' |
| path_lab_profiles | 6c151e39-18e5-5d6d-bfbc-fb5922163b63 | a44545ac-6cc6-5f39-b86c-9d3a66e134a8 | New S S Diagnostic Centre | email: 'newssdcbst@gmail.com' ← None |
| path_lab_profiles | 47f577ed-6964-53f2-9f0d-b76a1153fcab | d4f9bf08-44a8-5429-8daa-65c3fa9613cd | JK Labs | address: '' ← None |
| path_lab_profiles | a8449658-1620-584b-aa71-39bac0aa08e4 | bb98a51b-ec5c-56b2-bd71-f42379c28e8f | BASTI DIAGNOSTIC CENTER | address: '' ← None |
| pharmacy_providers | 6e4d8e86-8769-4c99-a1ba-37fa9b188cf5 | 60f2d4cc-8157-4ff8-99c2-e08ab9488000 | TEST Hosp Pharmacy 9392934300 | city: 'Delhi' ← None; address: '2 Test Rd' ← None; business_name: 'TEST Hosp Pharmacy 9392934300' ← 'Pharma Admin' |
| hospital_profiles | 528523dc-12b2-4a49-80c4-974ec49810c6 | 6f2cff28-9b72-40a9-a1e9-2c3a94e7faf5 | Siddharth Gupta's workspace | is_active: False ← True |
| pharmacy_providers | 5c487399-bcca-4e0b-83f7-6392bdb4d27a | 3d07d1ba-d1a5-4dcd-99f5-70ebb38b6a72 | Ravi Kumar | is_active: False ← True |
| hospital_profiles | 34162833-768f-43da-b5ac-7e8ec0cd3bb7 | 1b945702-aace-4a8f-9f94-759de0d4a396 | Sahayak multispeciality Hospital | is_active: False ← True |
| path_lab_profiles | c2be2fc2-9aa1-4000-b78b-efc2d68811d1 | 54acfc31-423c-45b2-b9b5-766071de5f92 | Basti Diagnostic Centre | email: 'sidmessy@gmail.com' ← None |
| doctors | df1bd992-1c2d-40ae-8a51-34337c38145b | 5cc1d26c-1b4a-4921-bcb1-865979d9a180 | Dr Jay | email: '' ← None |
| hospital_profiles | 5cbbb8f9-d360-40b1-9530-96b3e35ca5a2 | fe06d279-ccef-400b-8ebe-77a7922a157f | Trata Demo Hospital | name: 'Trata Demo Hospital' ← 'Dr. Siddharth Gupta'; email: None ← 'business.sanjeevanix@gmail.com'; address: 'Vipin Khand, Gomti Nagar, Lucknow' ← 'Hazratganj, Lucknow'; is_active: True ← False |
