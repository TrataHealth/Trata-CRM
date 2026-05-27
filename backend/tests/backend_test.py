"""TrataHealth CRM Backend API tests."""
import os
import pytest
import requests
from pathlib import Path

# Load REACT_APP_BACKEND_URL from frontend .env if not in env
_env_path = Path('/app/frontend/.env')
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        if line.startswith('REACT_APP_BACKEND_URL='):
            os.environ.setdefault('REACT_APP_BACKEND_URL', line.split('=', 1)[1].strip())

BASE_URL = os.environ['REACT_APP_BACKEND_URL'].rstrip('/')
MASTER_PHONE = '9873117605'
MASTER_OTP = '123456'


@pytest.fixture(scope='session')
def api():
    s = requests.Session()
    s.headers.update({'Content-Type': 'application/json'})
    return s


@pytest.fixture(scope='session')
def token(api):
    api.post(f'{BASE_URL}/api/auth/send-otp', json={'phone': MASTER_PHONE}, timeout=15)
    r = api.post(f'{BASE_URL}/api/auth/verify-otp', json={'phone': MASTER_PHONE, 'otp': MASTER_OTP}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get('success') is True
    assert data.get('token')
    assert data.get('is_master_admin') is True
    return data['token']


@pytest.fixture(scope='session')
def auth(api, token):
    api.headers.update({'Authorization': f'Bearer {token}'})
    return api


# -------------------- Auth --------------------
class TestAuth:
    def test_send_otp(self, api):
        r = api.post(f'{BASE_URL}/api/auth/send-otp', json={'phone': MASTER_PHONE}, timeout=15)
        assert r.status_code == 200
        assert r.json().get('success') is True

    def test_verify_invalid_otp(self, api):
        r = api.post(f'{BASE_URL}/api/auth/verify-otp', json={'phone': MASTER_PHONE, 'otp': '000000'}, timeout=15)
        assert r.status_code == 400

    def test_verify_unknown_phone(self, api):
        r = api.post(f'{BASE_URL}/api/auth/verify-otp', json={'phone': '9000000099', 'otp': MASTER_OTP}, timeout=15)
        assert r.status_code == 403

    def test_verify_master_admin(self, token):
        assert isinstance(token, str) and len(token) > 20

    def test_protected_requires_token(self, api):
        # use a fresh session without auth header
        s = requests.Session()
        r = s.get(f'{BASE_URL}/api/dashboard/stats', timeout=15)
        assert r.status_code == 401

    def test_protected_invalid_token(self):
        s = requests.Session()
        s.headers.update({'Authorization': 'Bearer invalid.token.here'})
        r = s.get(f'{BASE_URL}/api/dashboard/stats', timeout=15)
        assert r.status_code == 401


# -------------------- Dashboard --------------------
class TestDashboard:
    def test_stats(self, auth):
        r = auth.get(f'{BASE_URL}/api/dashboard/stats', timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ['users', 'cases', 'pipeline', 'revenue', 'tasks', 'growth_14d', 'activity_breakdown']:
            assert k in d, f'missing {k}'
        assert isinstance(d['growth_14d'], list)
        assert len(d['growth_14d']) == 14
        assert d['users']['total'] >= 0
        # by_type present for all 6 types
        for t in ['patient', 'doctor', 'hospital', 'paramedic', 'ambulance_provider', 'pathologist']:
            assert t in d['users']['by_type']

    def test_activity_feed(self, auth):
        r = auth.get(f'{BASE_URL}/api/dashboard/activity-feed?limit=10', timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json().get('items'), list)


# -------------------- Contacts --------------------
class TestContacts:
    def test_list_default(self, auth):
        r = auth.get(f'{BASE_URL}/api/contacts?limit=10', timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert 'items' in d and 'total' in d
        assert d['total'] > 0
        assert len(d['items']) <= 10

    def test_filter_by_type_doctor(self, auth):
        r = auth.get(f'{BASE_URL}/api/contacts?type=doctor&limit=50', timeout=15)
        assert r.status_code == 200
        items = r.json()['items']
        assert all(it['type'] == 'doctor' for it in items)

    def test_filter_by_stage(self, auth):
        r = auth.get(f'{BASE_URL}/api/contacts?pipeline_stage=verified&limit=20', timeout=15)
        assert r.status_code == 200
        items = r.json()['items']
        assert all(it['pipeline_stage'] == 'verified' for it in items)

    def test_filter_verified(self, auth):
        r = auth.get(f'{BASE_URL}/api/contacts?is_verified=true&limit=20', timeout=15)
        assert r.status_code == 200
        assert all(it['is_verified'] is True for it in r.json()['items'])

    def test_search_q(self, auth):
        r = auth.get(f'{BASE_URL}/api/contacts?q=Dr&limit=10', timeout=15)
        assert r.status_code == 200
        assert 'items' in r.json()

    def test_get_detail_and_update(self, auth):
        # get a doctor to update
        lst = auth.get(f'{BASE_URL}/api/contacts?type=doctor&limit=1', timeout=15).json()
        assert lst['items'], 'No doctors seeded'
        cid = lst['items'][0]['id']
        det = auth.get(f'{BASE_URL}/api/contacts/{cid}', timeout=15)
        assert det.status_code == 200
        body = det.json()
        for k in ['contact', 'activities', 'notes', 'tasks']:
            assert k in body
        assert body['contact']['id'] == cid

        # patch pipeline_stage and is_verified
        upd = auth.patch(f'{BASE_URL}/api/contacts/{cid}', json={'pipeline_stage': 'verified', 'is_verified': True}, timeout=15)
        assert upd.status_code == 200
        assert upd.json()['contact']['pipeline_stage'] == 'verified'
        assert upd.json()['contact']['is_verified'] is True
        # verify via GET
        det2 = auth.get(f'{BASE_URL}/api/contacts/{cid}', timeout=15).json()
        assert det2['contact']['pipeline_stage'] == 'verified'

    def test_get_404(self, auth):
        r = auth.get(f'{BASE_URL}/api/contacts/nonexistent-id-xyz', timeout=15)
        assert r.status_code == 404


# -------------------- Pipeline --------------------
class TestPipeline:
    def test_pipeline(self, auth):
        r = auth.get(f'{BASE_URL}/api/pipeline', timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d['stages'] == ['lead', 'contacted', 'kyc_submitted', 'verified', 'active', 'churned']
        assert 'items_by_stage' in d
        for s in d['stages']:
            assert s in d['items_by_stage']
        # patients should not appear
        for s, items in d['items_by_stage'].items():
            for it in items:
                assert it['type'] != 'patient'


# -------------------- Activities --------------------
class TestActivities:
    def test_list(self, auth):
        r = auth.get(f'{BASE_URL}/api/activities?limit=20', timeout=15)
        assert r.status_code == 200
        assert r.json()['total'] > 0

    def test_filter_category(self, auth):
        r = auth.get(f'{BASE_URL}/api/activities?category=emergency_case&limit=20', timeout=15)
        assert r.status_code == 200
        assert all(it['category'] == 'emergency_case' for it in r.json()['items'])

    def test_filter_status(self, auth):
        r = auth.get(f'{BASE_URL}/api/activities?category=emergency_case&status=COMPLETED&limit=10', timeout=15)
        assert r.status_code == 200
        for it in r.json()['items']:
            assert it['status'] == 'COMPLETED'


# -------------------- Tasks CRUD --------------------
class TestTasks:
    created_id = None

    def test_list(self, auth):
        r = auth.get(f'{BASE_URL}/api/tasks?limit=20', timeout=15)
        assert r.status_code == 200
        assert 'items' in r.json()

    def test_create(self, auth):
        payload = {'title': 'TEST_task_pytest', 'description': 'Auto', 'priority': 'high', 'status': 'open'}
        r = auth.post(f'{BASE_URL}/api/tasks', json=payload, timeout=15)
        assert r.status_code == 200
        t = r.json()['task']
        assert t['title'] == 'TEST_task_pytest'
        assert t['priority'] == 'high'
        assert 'id' in t
        TestTasks.created_id = t['id']

    def test_update(self, auth):
        assert TestTasks.created_id
        r = auth.patch(f'{BASE_URL}/api/tasks/{TestTasks.created_id}', json={'status': 'in_progress'}, timeout=15)
        assert r.status_code == 200
        assert r.json()['task']['status'] == 'in_progress'

    def test_delete(self, auth):
        assert TestTasks.created_id
        r = auth.delete(f'{BASE_URL}/api/tasks/{TestTasks.created_id}', timeout=15)
        assert r.status_code == 200
        assert r.json()['success'] is True


# -------------------- Notes --------------------
class TestNotes:
    def test_create_note(self, auth):
        c = auth.get(f'{BASE_URL}/api/contacts?type=doctor&limit=1', timeout=15).json()['items'][0]
        r = auth.post(f'{BASE_URL}/api/notes', json={'contact_id': c['id'], 'body': 'TEST_note pytest'}, timeout=15)
        assert r.status_code == 200
        note = r.json()['note']
        assert note['body'] == 'TEST_note pytest'
        # verify persisted via contact detail
        det = auth.get(f'{BASE_URL}/api/contacts/{c["id"]}', timeout=15).json()
        ids = [n['id'] for n in det['notes']]
        assert note['id'] in ids


# -------------------- Team --------------------
class TestTeam:
    created_id = None

    def test_list(self, auth):
        r = auth.get(f'{BASE_URL}/api/team', timeout=15)
        assert r.status_code == 200
        items = r.json()['items']
        assert len(items) >= 1
        # master admin must be present
        assert any(m.get('is_master_admin') for m in items)

    def test_create_member(self, auth):
        import uuid
        phone = f'9{str(uuid.uuid4().int)[:9]}'
        r = auth.post(f'{BASE_URL}/api/team', json={'name': 'TEST_member', 'phone': phone, 'email': 't@t.com', 'role': 'sales_rep'}, timeout=15)
        assert r.status_code == 200
        TestTeam.created_id = r.json()['member']['id']

    def test_delete_member(self, auth):
        assert TestTeam.created_id
        r = auth.delete(f'{BASE_URL}/api/team/{TestTeam.created_id}', timeout=15)
        assert r.status_code == 200


# -------------------- Analytics --------------------
class TestAnalytics:
    def test_overview(self, auth):
        r = auth.get(f'{BASE_URL}/api/analytics/overview', timeout=20)
        assert r.status_code == 200
        d = r.json()
        for k in ['cases_by_status', 'response_time_buckets', 'top_cities', 'revenue_30d']:
            assert k in d
        assert len(d['revenue_30d']) == 30


# -------------------- Export --------------------
class TestExport:
    def test_csv(self, auth):
        r = auth.get(f'{BASE_URL}/api/export/contacts.csv', timeout=30)
        assert r.status_code == 200
        assert 'text/csv' in r.headers.get('content-type', '')
        first = r.text.splitlines()[0]
        assert 'name' in first and 'phone' in first


# -------------------- Search --------------------
class TestSearch:
    def test_search(self, auth):
        r = auth.get(f'{BASE_URL}/api/search?q=Dr', timeout=15)
        assert r.status_code == 200
        d = r.json()
        for k in ['contacts', 'activities', 'tasks']:
            assert k in d


# -------------------- AI --------------------
class TestAI:
    def test_insight_summary(self, auth):
        c = auth.get(f'{BASE_URL}/api/contacts?type=doctor&limit=1', timeout=15).json()['items'][0]
        r = auth.post(f'{BASE_URL}/api/ai/insight', json={'contact_id': c['id'], 'mode': 'summary'}, timeout=60)
        # acceptable: HTTP 200 with text (success true or false fallback)
        assert r.status_code == 200
        d = r.json()
        assert 'text' in d and isinstance(d['text'], str) and len(d['text']) > 0
        assert d.get('mode') == 'summary'

    def test_insight_next_action(self, auth):
        c = auth.get(f'{BASE_URL}/api/contacts?type=hospital&limit=1', timeout=15).json()['items'][0]
        r = auth.post(f'{BASE_URL}/api/ai/insight', json={'contact_id': c['id'], 'mode': 'next_action'}, timeout=60)
        assert r.status_code == 200
        assert r.json().get('mode') == 'next_action'

    def test_insight_404(self, auth):
        r = auth.post(f'{BASE_URL}/api/ai/insight', json={'contact_id': 'nonexistent', 'mode': 'summary'}, timeout=15)
        assert r.status_code == 404
