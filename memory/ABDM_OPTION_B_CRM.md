# ABDM Option-B (central callback gateway) — CRM identity
- Single sandbox bridge SBXID_062279 shared by 4 Trata apps; bridge callback URL = https://api.tratahealth.com (Patient backend). NEVER change bridge URL / create bridge or facility.
- Gateway routes callbacks by X-HIP-ID / X-HIU-ID header to owning app, preserving path/method/body/headers.
- CRM facility (HIP+HIU) ID: IN0910034478 ; CRM base URL (callbacks forwarded here): https://crm.tratahealth.com
- Outbound: session via shared client id/secret; stamp X-HIP-ID/X-HIU-ID = IN0910034478 on every request; any URL in payloads (dataPushUrl etc.) must be https://api.tratahealth.com/... ; all outbound via India proxy 68.183.247.212:3128 (own proxy user).
- Inbound endpoints to expose (respond <3s):
  HIP: POST /api/v3/hip/token/on-generate-token (200), /api/v3/hip/patient/care-context/discover (202), /api/v3/hip/link/care-context/init (202), /api/v3/hip/link/care-context/confirm (200), /api/v3/hip/health-information/request (202)
  HIU: /api/v3/hiu/consent/request/on-init (200), /api/v3/hiu/consent/on-notify (200), /api/v3/hiu/consent/on-fetch (200), /api/v3/hiu/health-information/on-request (200), /api/v3/hiu/health-information/transfer (202)
  Consent: /api/v3/consent/request/hip/notify (200)
- Env: ABDM_ENV, ABDM_CLIENT_ID, ABDM_CLIENT_SECRET, ABDM_X_CM_ID, ABDM_GATEWAY_BASE, ABDM_ABHA_BASE, ABDM_CALLBACK_BASE, ABDM_HIP_ID, ABDM_HIU_ID, ABDM_HTTP_PROXY
- Sandbox flaky: ABDM-1206 (Aadhaar verify), 303001 SUSPENDED (sessions) → treat 5xx as outage, retry.

## RULE: Bridge callback URL is owned by the Patient app (Jun 2026)
- The ABDM bridge callback URL is shared global state for the whole Trata gateway. ONLY the Patient app (gateway owner) may change it.
- The CRM must NEVER call `POST /api/abdm/bridge/register-url` (or any ABDM bridge/URL registration API). The Patient app is gating that endpoint behind an admin token.
- CRM only reads `ABDM_CALLBACK_BASE` (env) for display in the callbacks view (`abdm_hip.py`); inbound callbacks keep arriving via api.tratahealth.com routed by `X-HIP-ID`.
- Audit Jun 2026: no CRM code calls register-url/bridge endpoints.

## Scan & Share (M1, facility side) — Jun 2026
- Inbound `/api/v3/hip/patient/share` routed by gateway via X-HIP-ID IN0910034478; counter-id = per-hospital code (`abdm_share_counters`). Outbound `/patient-share/v3/on-share` via hiecm_post. Real e2e needs a real ABHA app scan of the hospital QR.
