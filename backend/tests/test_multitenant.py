"""Multi-tenant CRM tests: 3-step auth, role enforcement, scoping, provider endpoints."""
import os
import pytest
import requests
from pathlib import Path

# Load REACT_APP_BACKEND_URL from frontend .env
_env_path = Path('/app/frontend/.env')
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        if line.startswith('REACT_APP_BACKEND_URL='):
            os.environ.setdefault('REACT_APP_BACKEND_URL', line.split('=', 1)[1].strip())

BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
OTP = '123456'
MASTER_PHONE = '9873117605'
MASTER_PASSWORD = 'Master@123'
PROVIDERS = {
    'hospital':  {'phone': '9000020001', 'password': 'Trata@123'},
    'clinic':    {'phone': '9000020002', 'password': 'Trata@123'},
    'ambulance': {'phone': '9000020003', 'password': 'Trata@123'},
    'pathology': {'phone': '9000020004', 'password': 'Trata@123'},
}


def _req():
    s = requests.Session()
    s.headers.update({'Content-Type': 'application/json'})
    return s


def _verify(phone):
    s = _req()
    s.post(f'{BASE_URL}/api/auth/send-otp', json={'phone': phone}, timeout=15)
    r = s.post(f'{BASE_URL}/api/auth/verify-otp', json={'phone': phone, 'otp': OTP}, timeout=15)
    return r


def _login(phone, password):
    """Full flow: send-otp -> verify-otp -> login-password (or set-password if first time)."""
    r = _verify(phone)
    assert r.status_code == 200, f'verify failed {r.status_code}: {r.text}'
    body = r.json()
    temp = body['temp_token']
    s = _req()
    s.headers.update({'Authorization': f'Bearer {temp}'})
    if body.get('needs_password_setup'):
        rp = s.post(f'{BASE_URL}/api/auth/set-password', json={'password': password}, timeout=15)
    else:
        rp = s.post(f'{BASE_URL}/api/auth/login-password', json={'password': password}, timeout=15)
    assert rp.status_code == 200, f'password step failed {rp.status_code}: {rp.text}'
    data = rp.json()
    return data['token'], data['user']


# -------------------- session-level setup: ensure master admin password set --------------------
@pytest.fixture(scope='session')
def admin_token():
    token, user = _login(MASTER_PHONE, MASTER_PASSWORD)
    assert user.get('is_master_admin') is True
    assert user.get('role') == 'admin'
    return token


@pytest.fixture(scope='session')
def provider_tokens():
    out = {}
    for ptype, creds in PROVIDERS.items():
        token, user = _login(creds['phone'], creds['password'])
        out[ptype] = {'token': token, 'user': user}
    return out


def _h(token):
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


# ============================================================
# 1. 3-step auth flow
# ============================================================
class TestAuthFlow:
    def test_send_otp_ok(self):
        s = _req()
        r = s.post(f'{BASE_URL}/api/auth/send-otp', json={'phone': MASTER_PHONE}, timeout=10)
        assert r.status_code == 200
        assert r.json()['success'] is True

    def test_verify_invalid_otp(self):
        s = _req()
        r = s.post(f'{BASE_URL}/api/auth/verify-otp', json={'phone': MASTER_PHONE, 'otp': '000000'}, timeout=10)
        assert r.status_code == 400

    def test_verify_unknown_phone(self):
        r = _req().post(f'{BASE_URL}/api/auth/verify-otp', json={'phone': '9999999999', 'otp': OTP}, timeout=10)
        assert r.status_code == 403

    def test_verify_returns_temp_token(self):
        r = _verify(PROVIDERS['hospital']['phone'])
        assert r.status_code == 200
        d = r.json()
        assert 'temp_token' in d
        assert 'needs_password_setup' in d
        assert 'user' in d
        assert d['user']['phone'] == PROVIDERS['hospital']['phone']

    def test_wrong_password(self):
        # use temp token then send wrong password
        r = _verify(PROVIDERS['hospital']['phone'])
        temp = r.json()['temp_token']
        s = _req()
        s.headers.update({'Authorization': f'Bearer {temp}'})
        rp = s.post(f'{BASE_URL}/api/auth/login-password', json={'password': 'WRONGPASS'}, timeout=10)
        assert rp.status_code == 401

    def test_invalid_temp_token(self):
        s = _req()
        s.headers.update({'Authorization': 'Bearer invalid.temp.token'})
        rp = s.post(f'{BASE_URL}/api/auth/login-password', json={'password': 'x'}, timeout=10)
        assert rp.status_code == 401

    def test_no_temp_token(self):
        rp = _req().post(f'{BASE_URL}/api/auth/login-password', json={'password': 'x'}, timeout=10)
        assert rp.status_code == 401

    def test_master_admin_logs_in(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_master_admin_subsequent_login_not_needs_setup(self):
        # after setup happened, verify-otp should return needs_password_setup=false
        r = _verify(MASTER_PHONE)
        assert r.status_code == 200
        assert r.json().get('needs_password_setup') is False


# ============================================================
# 2. Provider login - 4 types
# ============================================================
class TestProviderLogin:
    @pytest.mark.parametrize('ptype', list(PROVIDERS.keys()))
    def test_each_provider_logs_in(self, provider_tokens, ptype):
        info = provider_tokens[ptype]
        u = info['user']
        assert u['role'] == 'provider_owner', f"{ptype} role: {u.get('role')}"
        assert u['provider_type'] == ptype, f"{ptype} provider_type: {u.get('provider_type')}"
        assert u.get('provider_id'), f"{ptype} missing provider_id"


# ============================================================
# 3. Internal-only endpoints must 403 for providers
# ============================================================
INTERNAL_ENDPOINTS = [
    ('GET', '/api/dashboard/stats'),
    ('GET', '/api/dashboard/activity-feed'),
    ('GET', '/api/pipeline'),
    ('GET', '/api/analytics/overview'),
    ('GET', '/api/team'),
    ('GET', '/api/export/contacts.csv'),
]


class TestInternalOnlyEnforcement:
    @pytest.mark.parametrize('method,path', INTERNAL_ENDPOINTS)
    def test_provider_blocked(self, provider_tokens, method, path):
        token = provider_tokens['hospital']['token']
        r = requests.request(method, f'{BASE_URL}{path}', headers=_h(token), timeout=15)
        assert r.status_code == 403, f'{path} expected 403 got {r.status_code}'

    def test_provider_patch_contacts_blocked(self, provider_tokens, admin_token):
        # pick any contact id as admin
        lst = requests.get(f'{BASE_URL}/api/contacts?limit=1', headers=_h(admin_token), timeout=10).json()
        cid = lst['items'][0]['id']
        token = provider_tokens['hospital']['token']
        r = requests.patch(f'{BASE_URL}/api/contacts/{cid}',
                           json={'pipeline_stage': 'verified'}, headers=_h(token), timeout=10)
        assert r.status_code == 403

    def test_admin_can_call_internal(self, admin_token):
        for m, p in INTERNAL_ENDPOINTS:
            r = requests.request(m, f'{BASE_URL}{p}', headers=_h(admin_token), timeout=20)
            assert r.status_code == 200, f'admin {p} -> {r.status_code}'


# ============================================================
# 4. Scoped endpoints for providers
# ============================================================
class TestProviderScoping:
    def test_contacts_scoped_to_self_only(self, provider_tokens):
        for ptype, info in provider_tokens.items():
            r = requests.get(f'{BASE_URL}/api/contacts?limit=200', headers=_h(info['token']), timeout=15)
            assert r.status_code == 200
            items = r.json()['items']
            assert len(items) == 1, f'{ptype} sees {len(items)} contacts, expected 1'
            assert items[0]['id'] == info['user']['provider_id']

    def test_activities_scoped(self, provider_tokens, admin_token):
        # admin sees all
        admin_total = requests.get(f'{BASE_URL}/api/activities?limit=1', headers=_h(admin_token), timeout=15).json()['total']
        for ptype, info in provider_tokens.items():
            r = requests.get(f'{BASE_URL}/api/activities?limit=500', headers=_h(info['token']), timeout=15)
            assert r.status_code == 200
            items = r.json()['items']
            assert r.json()['total'] <= admin_total
            pid = info['user']['provider_id']
            for it in items:
                pids = it.get('provider_ids') or []
                assert pid in pids, f'{ptype} got activity without their pid: {it.get("id")}'

    def test_other_contact_forbidden(self, provider_tokens):
        a = provider_tokens['hospital']
        b = provider_tokens['clinic']
        r = requests.get(f'{BASE_URL}/api/contacts/{b["user"]["provider_id"]}',
                         headers=_h(a['token']), timeout=10)
        assert r.status_code == 403

    def test_own_contact_ok(self, provider_tokens):
        info = provider_tokens['hospital']
        r = requests.get(f'{BASE_URL}/api/contacts/{info["user"]["provider_id"]}',
                         headers=_h(info['token']), timeout=10)
        assert r.status_code == 200

    def test_search_scoped(self, provider_tokens, admin_token):
        admin_res = requests.get(f'{BASE_URL}/api/search?q=a', headers=_h(admin_token), timeout=15).json()
        prov_res = requests.get(f'{BASE_URL}/api/search?q=a', headers=_h(provider_tokens['hospital']['token']), timeout=15).json()
        # provider contact count should be at most 1
        assert len(prov_res.get('contacts', [])) <= 1
        # provider's results <= admin's
        assert len(prov_res.get('activities', [])) <= len(admin_res.get('activities', []))


# ============================================================
# 5. Provider-only endpoints
# ============================================================
class TestProviderEndpoints:
    def test_provider_me(self, provider_tokens):
        for ptype, info in provider_tokens.items():
            r = requests.get(f'{BASE_URL}/api/provider/me', headers=_h(info['token']), timeout=10)
            assert r.status_code == 200, f'{ptype}: {r.text}'
            d = r.json()
            assert 'contact' in d or 'user' in d
            if 'contact' in d:
                assert d['contact']['id'] == info['user']['provider_id']

    def test_provider_dashboard_kpis_and_extras(self, provider_tokens):
        expected_extras = {
            'hospital': ['total_beds', 'available_beds', 'occupancy_pct', 'incoming_today'],
            'ambulance': ['fleet_size', 'avg_response_min', 'live_trips', 'trips_completed'],
            'clinic': ['appointments_today', 'no_show_rate_pct'],
            'pathology': ['samples_collected', 'reports_ready', 'pending_bookings'],
        }
        for ptype, info in provider_tokens.items():
            r = requests.get(f'{BASE_URL}/api/provider/dashboard', headers=_h(info['token']), timeout=15)
            assert r.status_code == 200, f'{ptype}: {r.status_code} {r.text}'
            d = r.json()
            kpis = d.get('kpis', d)
            for k in ['total_activities', 'active', 'completed', 'revenue']:
                assert (k in kpis) or (k in d), f'{ptype} missing kpi {k}; got {list(kpis.keys())}'
            for ek in expected_extras[ptype]:
                # extras may be under d, d['extras'], or nested under kpis
                assert (ek in d) or (ek in d.get('extras', {})) or (ek in kpis), \
                    f'{ptype} missing extra {ek}; got d-keys {list(d.keys())}, kpi-keys {list(kpis.keys())}'

    def test_provider_activities(self, provider_tokens):
        for ptype, info in provider_tokens.items():
            r = requests.get(f'{BASE_URL}/api/provider/activities', headers=_h(info['token']), timeout=15)
            assert r.status_code == 200
            items = r.json().get('items', [])
            pid = info['user']['provider_id']
            for it in items:
                assert pid in (it.get('provider_ids') or [])

    def test_admin_blocked_from_provider_endpoints(self, admin_token):
        for path in ['/api/provider/me', '/api/provider/dashboard', '/api/provider/activities']:
            r = requests.get(f'{BASE_URL}{path}', headers=_h(admin_token), timeout=10)
            assert r.status_code == 403, f'admin {path} -> {r.status_code}'
