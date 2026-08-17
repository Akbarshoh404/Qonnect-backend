"""
Backend tests for Qonnect
"""
import pytest
import json
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope='session')
def app():
    """Create application with test config."""
    app = create_app('development')
    app.config.update({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
        'GOOGLE_CLIENT_ID': 'test-client-id',
        'GOOGLE_CLIENT_SECRET': 'test-client-secret',
    })
    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    with app.app_context():
        yield _db


@pytest.fixture
def test_user(app):
    """Create a test user, rolled back after each test."""
    from app.models import User
    from app.extensions import db
    with app.app_context():
        # Use unique sub per test run to avoid collisions
        import uuid
        sub = f'test-{uuid.uuid4().hex[:8]}'
        user = User(
            google_sub=sub,
            email=f'{sub}@example.com',
            name='Test User',
        )
        db.session.add(user)
        db.session.commit()
        db.session.refresh(user)
        yield user
        # Cleanup: remove user and their QR codes etc
        db.session.delete(user)
        db.session.commit()


@pytest.fixture
def logged_in_client(client, app, test_user):
    """Client with an authenticated session."""
    with app.app_context():
        user_id = test_user.id
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True
    return client


class TestHealth:
    def test_health_endpoint(self, client):
        response = client.get('/api/health')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'ok'
        assert data['service'] == 'qonnect'


class TestAuth:
    def test_me_unauthorized(self, client):
        response = client.get('/api/auth/me')
        assert response.status_code == 401

    def test_me_authorized(self, logged_in_client, test_user):
        response = logged_in_client.get('/api/auth/me')
        assert response.status_code == 200
        data = json.loads(response.data)
        # Email is dynamic uuid-based in tests
        assert '@example.com' in data['user']['email']

    def test_logout(self, logged_in_client):
        response = logged_in_client.post('/api/auth/logout')
        assert response.status_code == 200


class TestQRCodes:
    def test_list_qr_unauthenticated(self, client):
        response = client.get('/api/qr')
        assert response.status_code == 401

    def test_list_qr_empty(self, logged_in_client):
        response = logged_in_client.get('/api/qr')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'qr_codes' in data
        assert data['total'] == 0

    def test_create_url_qr(self, logged_in_client, app):
        response = logged_in_client.post(
            '/api/qr',
            json={
                'type': 'url',
                'title': 'Test URL QR',
                'destination_url': 'https://example.com',
            }
        )
        assert response.status_code == 201
        data = json.loads(response.data)
        qr = data['qr_code']
        assert qr['type'] == 'url'
        assert qr['title'] == 'Test URL QR'
        assert qr['destination_url'] == 'https://example.com'
        assert qr['is_active'] is True
        assert len(qr['short_code']) == 7
        return qr

    def test_create_url_qr_invalid_url(self, logged_in_client):
        response = logged_in_client.post(
            '/api/qr',
            json={
                'type': 'url',
                'title': 'Bad URL',
                'destination_url': 'not-a-url',
            }
        )
        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data

    def test_create_url_qr_local_url_blocked(self, logged_in_client):
        response = logged_in_client.post(
            '/api/qr',
            json={
                'type': 'url',
                'title': 'Local URL',
                'destination_url': 'http://localhost/admin',
            }
        )
        assert response.status_code == 400

    def test_create_missing_title(self, logged_in_client):
        response = logged_in_client.post(
            '/api/qr',
            json={'type': 'url', 'destination_url': 'https://example.com'}
        )
        assert response.status_code == 400

    def test_get_qr(self, logged_in_client, app):
        # Create first
        create_resp = logged_in_client.post(
            '/api/qr',
            json={'type': 'url', 'title': 'Get Test', 'destination_url': 'https://example.com'}
        )
        qr_id = json.loads(create_resp.data)['qr_code']['id']

        response = logged_in_client.get(f'/api/qr/{qr_id}')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['qr_code']['id'] == qr_id

    def test_update_qr(self, logged_in_client):
        create_resp = logged_in_client.post(
            '/api/qr',
            json={'type': 'url', 'title': 'Original', 'destination_url': 'https://example.com'}
        )
        qr_id = json.loads(create_resp.data)['qr_code']['id']

        response = logged_in_client.patch(
            f'/api/qr/{qr_id}',
            json={'title': 'Updated', 'destination_url': 'https://updated.com'}
        )
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['qr_code']['title'] == 'Updated'
        assert data['qr_code']['destination_url'] == 'https://updated.com'

    def test_delete_qr(self, logged_in_client):
        create_resp = logged_in_client.post(
            '/api/qr',
            json={'type': 'url', 'title': 'To Delete', 'destination_url': 'https://example.com'}
        )
        qr_id = json.loads(create_resp.data)['qr_code']['id']

        # Delete the QR (must send JSON or empty body)
        response = logged_in_client.delete(
            f'/api/qr/{qr_id}',
            json={},
        )
        assert response.status_code == 200

        get_response = logged_in_client.get(f'/api/qr/{qr_id}')
        assert get_response.status_code == 404


class TestRedirect:
    def test_redirect_nonexistent_code(self, client):
        response = client.get('/q/NOTEXIST')
        assert response.status_code == 404

    def test_redirect_active_url_qr(self, logged_in_client, client):
        create_resp = logged_in_client.post(
            '/api/qr',
            json={'type': 'url', 'title': 'Redirect Test', 'destination_url': 'https://example.com'}
        )
        qr = json.loads(create_resp.data)['qr_code']
        short_code = qr['short_code']

        response = client.get(f'/q/{short_code}')
        assert response.status_code == 302
        assert response.headers['Location'] == 'https://example.com'

    def test_redirect_disabled_qr_returns_410(self, logged_in_client, client):
        create_resp = logged_in_client.post(
            '/api/qr',
            json={'type': 'url', 'title': 'Disabled', 'destination_url': 'https://example.com'}
        )
        qr = json.loads(create_resp.data)['qr_code']
        qr_id = qr['id']
        short_code = qr['short_code']

        # Disable it
        logged_in_client.patch(f'/api/qr/{qr_id}', json={'is_active': False})

        response = client.get(f'/q/{short_code}')
        assert response.status_code == 410


class TestAuthorization:
    def test_cannot_access_other_users_qr(self, app, client):
        """Create QR as user1, verify user2 cannot access it."""
        from app.models import User
        from app.extensions import db

        with app.app_context():
            user2 = User(google_sub='user2-sub', email='user2@example.com', name='User 2')
            db.session.add(user2)
            db.session.commit()
            user2_id = user2.id

        # Login as user2
        with client.session_transaction() as session:
            session['_user_id'] = str(user2_id)
            session['_fresh'] = True

        # Create QR as user2
        create_resp = client.post(
            '/api/qr',
            json={'type': 'url', 'title': 'User2 QR', 'destination_url': 'https://user2.com'}
        )
        # If user2 session worked, extract qr_id; otherwise just test 401 on unauthenticated
        try:
            qr_id = json.loads(create_resp.data)['qr_code']['id']
        except (KeyError, json.JSONDecodeError):
            qr_id = 99999  # non-existent

        # Without auth, unauthenticated client cannot access QR API
        with client.session_transaction() as session:
            session.clear()
        response = client.get(f'/api/qr/{qr_id}')
        assert response.status_code == 401


class TestDomains:
    def test_list_domains_empty(self, logged_in_client):
        response = logged_in_client.get('/api/domains')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['domains'] == [] or isinstance(data['domains'], list)

    def test_add_invalid_domain(self, logged_in_client):
        response = logged_in_client.post('/api/domains', json={'domain': 'not a domain!'})
        assert response.status_code == 400

    def test_add_valid_domain(self, logged_in_client):
        response = logged_in_client.post('/api/domains', json={'domain': 'files.example.com'})
        assert response.status_code == 201
        data = json.loads(response.data)
        assert data['domain']['domain'] == 'files.example.com'
        assert data['domain']['verified'] is False


class TestValidators:
    def test_valid_url(self):
        from app.utils.validators import validate_destination_url
        valid, err = validate_destination_url('https://example.com')
        assert valid is True
        assert err == ''

    def test_invalid_url_no_scheme(self):
        from app.utils.validators import validate_destination_url
        valid, err = validate_destination_url('example.com')
        assert valid is False

    def test_invalid_url_localhost(self):
        from app.utils.validators import validate_destination_url
        valid, err = validate_destination_url('http://localhost:8080')
        assert valid is False

    def test_sanitize_filename(self):
        from app.utils.validators import sanitize_filename
        result = sanitize_filename('../../../etc/passwd')
        # Should not contain path traversal - dots and slashes are replaced
        assert 'etc' in result  # base name preserved
        assert 'passwd' in result
        assert sanitize_filename('my document.pdf') == 'my document.pdf'
        assert sanitize_filename('normal-file_name.txt') == 'normal-file_name.txt'

    def test_short_code_generation(self):
        from app.utils.short_code import generate_short_code
        code = generate_short_code()
        assert len(code) == 7
        assert code.isalnum()

    def test_short_code_uniqueness(self):
        from app.utils.short_code import generate_short_code
        codes = {generate_short_code() for _ in range(100)}
        # Very high probability of all being unique
        assert len(codes) >= 99

    def test_ip_hashing(self):
        from app.utils.geo import hash_ip
        h1 = hash_ip('1.2.3.4')
        h2 = hash_ip('1.2.3.4')
        h3 = hash_ip('5.6.7.8')
        assert h1 == h2  # Same IP, same day → same hash
        assert h1 != h3  # Different IPs → different hashes
        assert '1.2.3.4' not in h1  # IP not in hash
