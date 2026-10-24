# Account suspension & deletion — contract for Provider app and TrataX teams
Source of truth: shared Supabase `public.users` (CRM master admin writes it).

## Suspension (new columns, added by CRM)
| column | type | meaning |
|---|---|---|
| is_suspended | boolean NOT NULL DEFAULT false | true = account suspended |
| suspended_at | timestamptz | when |
| suspended_reason | text | reason — SHOW THIS TO THE USER |
| suspended_by | text | admin name (internal) |

Required behaviour in every app when `is_suspended = true`:
1. Allow sign-in, but immediately show a full-screen notice: "Your account has been suspended" + `suspended_reason` + "contact your Trata relationship manager".
2. Disable/hide every other screen and action; backend must reject writes for that user (HTTP 423 recommended).
3. Re-check on app resume / every ≤60s and restore the normal app when it becomes false.

## Deletion (existing columns)
- `is_archived = true`, `is_active = false`, `archived_reason LIKE 'admin_deleted:%'`, `purge_after` = archived_at + 30 days.
- Treat as deleted: block sign-in, hide from all lists. Admin can restore within 30 days (columns reset).
- After `purge_after`, the CRM cron erases the account: profile rows deleted; the users row is deleted, or anonymised (`name='Deleted user'`, phone `del-<id>`, `archived_reason='erased'`) when history rows reference it.
