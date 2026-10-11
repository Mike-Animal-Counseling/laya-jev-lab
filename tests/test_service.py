"""Security and integration contracts using isolated synthetic workspaces."""
from io import BytesIO
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from cryptography.fernet import Fernet
from service.app import Application
from service.errors import ServiceError
from service.store import Store
from service.zendesk import Zendesk
from ticket_engine.normalization import RUBRIC_ID, fingerprint
from ticket_engine.transport import DEFAULT_MODEL


class FakeEngines:
    def __init__(self):
        self.calls = 0

    def status(self, workspace):
        return {name: {'status': 'ready', 'model': DEFAULT_MODEL if name == 'jev' else 'test-laya'} for name in ('laya-ft', 'jev')}

    def classify(self, workspace, provider, state):
        self.calls += 1
        value = {'provider': provider, 'category': 'refund', 'category_label': 'Billing', 'suggested_team': '财务支持', 'priority': 'P1', 'urgency': .9, 'complaint': .6, 'churn': .7, 'refund': .9, 'confidence': .9, 'probabilities': {'refund': .9}, 'needs_review': False, 'elapsed_ms': 1, 'input_tokens': 20, 'analyzed_at': '2026-01-01T00:00:00Z', 'rubric_id': RUBRIC_ID, 'input_id': fingerprint(state), 'review_reasons': [], 'checkpoint_sha256': None, 'schema_version': 1, 'model': self.status(workspace)[provider]['model']}
        return SimpleNamespace(to_dict=lambda: value)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        (directory / 'master.key').write_bytes(Fernet.generate_key())
        self.clock = time.time()
        self.store = Store(directory, clock=lambda: self.clock)
        self.a = self.store.create_workspace('acme', 'admin', 'synthetic-test-password')
        self.b = self.store.create_workspace('beta', 'admin', 'synthetic-test-password')
        self.engines = FakeEngines()
        self.app = Application(self.store, self.engines, 'http://127.0.0.1:5180')
        self.token, self.csrf = self.store.login('acme', 'admin', 'synthetic-test-password')
        self.user = self.store.session(self.token)

    def tearDown(self):
        self.temp.cleanup()

    def call(self, path, body=None, *, method=None, token=None, bearer=None, origin=True, csrf=True):
        raw = json.dumps(body).encode() if body is not None else b''
        environ = {'REQUEST_METHOD': method or ('POST' if body is not None else 'GET'), 'PATH_INFO': path, 'QUERY_STRING': '', 'HTTP_HOST': '127.0.0.1:8780', 'wsgi.input': BytesIO(raw), 'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json', 'REMOTE_ADDR': 'test-client'}
        if token is not False:
            environ['HTTP_COOKIE'] = 'laya-session=' + (token or self.token)
        if bearer:
            environ['HTTP_AUTHORIZATION'] = 'Bearer ' + bearer
        if body is not None and origin:
            environ['HTTP_ORIGIN'] = self.app.public_url
        if body is not None and csrf:
            session = self.store.session(token or self.token) if token is not False else None
            environ['HTTP_X_CSRF_TOKEN'] = session['csrf'] if session else self.csrf
        response = {}
        def start(status, headers):
            response.update(status=int(status.split()[0]), headers=dict(headers))
        output = b''.join(self.app(environ, start))
        return response['status'], json.loads(output), response['headers']

    def key(self, workspace=None, scopes=None):
        return self.store.create_api_key(workspace or self.a, 'test integration', scopes or ['classify', 'tickets:write', 'tickets:read'])

    def ticket(self, text='Synthetic invoice problem'):
        return {'subject': text, 'message': 'Please refund the duplicate synthetic payment.', 'source': 'api', 'source_id': 'example-01'}

    def test_anonymous_cannot_read_tickets(self):
        self.assertEqual(self.call('/api/tickets', token=False)[0], 401)
        self.assertEqual(self.call('/api/auth/status', token=False)[1]['mode'], 'cloud')

    def test_archive_does_not_reuse_ticket_identity(self):
        first = self.app.workspace(self.a).import_rows([self.ticket()], str(uuid4()), 'admin')
        self.assertEqual(self.call('/api/tickets/archive', {'ids': first['ids'], 'confirm': True})[0], 200)
        second = self.ticket('Another synthetic ticket')
        second['source_id'] = 'example-02'
        result = self.app.workspace(self.a).import_rows([second], str(uuid4()), 'admin')
        self.assertNotEqual(first['ids'], result['ids'])

    def test_login_cookie_and_logout_revoke_session(self):
        status, _, headers = self.call('/api/auth/login', {'workspace': 'acme', 'username': 'admin', 'password': 'synthetic-test-password'}, token=False)
        self.assertEqual(status, 200)
        self.assertIn('HttpOnly', headers['Set-Cookie'])
        self.assertIn('SameSite=Lax', headers['Set-Cookie'])
        self.assertEqual(self.call('/api/auth/logout', {})[0], 200)
        self.assertIsNone(self.store.session(self.token))

    def test_https_requires_secure_host_cookie(self):
        app = Application(self.store, self.engines, 'https://tickets.example.com')
        self.assertTrue(app.cookie('test').startswith('__Host-'))
        self.assertIn('; Secure', app.cookie('test'))
        with self.assertRaises(ServiceError):
            Application(self.store, self.engines, 'http://tickets.example.com')

    def test_session_expiry(self):
        self.clock += 28801
        self.assertEqual(self.call('/api/tickets')[0], 401)

    def test_csrf_and_origin_required_for_writes(self):
        self.assertEqual(self.call('/api/settings/jev', {'api_key': 'synthetic-value'}, csrf=False)[0], 403)
        self.assertEqual(self.call('/api/settings/jev', {'api_key': 'synthetic-value'}, origin=False)[0], 403)

    def test_invites_are_one_time_and_viewer_has_no_write_rights(self):
        invitation = self.store.invite(self.a, 'reader', 'viewer')
        self.store.join(invitation, 'synthetic-viewer-password')
        with self.assertRaises(ServiceError):
            self.store.join(invitation, 'synthetic-viewer-password')
        token, _ = self.store.login('acme', 'reader', 'synthetic-viewer-password')
        self.assertEqual(self.call('/api/tickets', token=token)[0], 200)
        self.assertEqual(self.call('/api/settings', token=token)[0], 403)
        self.assertEqual(self.call('/api/tickets', {'subject': 'Synthetic', 'message': 'Test', 'request_id': str(uuid4())}, token=token)[0], 403)
        self.assertEqual(self.call('/api/auth/logout', {}, token=token)[0], 200)

    def test_disabling_member_revokes_sessions_and_cannot_target_other_workspace(self):
        invitation = self.store.invite(self.a, 'agent', 'member')
        self.store.join(invitation, 'synthetic-member-password')
        token, _ = self.store.login('acme', 'agent', 'synthetic-member-password')
        member = self.store.session(token)
        with self.assertRaises(ServiceError):
            self.store.disable_member(self.b, member['id'])
        self.store.disable_member(self.a, member['id'])
        self.assertIsNone(self.store.session(token))

    def test_credentials_encrypted_and_never_returned(self):
        key = 'synthetic-private-key-for-this-test'
        self.assertEqual(self.call('/api/settings/jev', {'api_key': key})[0], 200)
        _, value, _ = self.call('/api/settings')
        self.assertNotIn(key, json.dumps(value))
        with self.store.connect() as db:
            cipher = db.execute('SELECT ciphertext FROM settings WHERE workspace_id=?', (self.a,)).fetchone()[0]
        self.assertNotIn(key.encode(), cipher)
        with self.assertRaises(ServiceError):
            self.store.decrypt(self.b, cipher)

    def test_workspace_and_key_scope_isolation(self):
        a, b = self.key(), self.key(self.b)
        self.assertEqual(self.call('/v1/tickets', {'tickets': [self.ticket()], 'request_id': str(uuid4())}, bearer=a)[0], 200)
        self.assertEqual(self.call('/v1/tickets', bearer=b)[1]['tickets'], [])
        self.assertEqual(self.call('/v1/tickets/TK-1041', bearer=b)[0], 404)
        read_only = self.key(scopes=['tickets:read'])
        self.assertEqual(self.call('/v1/classify', {'message': 'Synthetic test', 'request_id': str(uuid4())}, bearer=read_only)[0], 403)

    def test_api_rejects_browser_session_without_bearer(self):
        self.assertEqual(self.call('/v1/tickets')[0], 401)

    def test_expired_and_revoked_integration_keys(self):
        key = self.key()
        key_id = self.store.api_keys(self.a)[0]['id']
        self.store.revoke_api_key(self.b, key_id)
        self.assertIsNotNone(self.store.api_key(key))
        self.store.revoke_api_key(self.a, key_id)
        self.assertIsNone(self.store.api_key(key))
        key = self.key()
        self.clock += 91 * 86400
        self.assertIsNone(self.store.api_key(key))

    def test_classify_retry_is_cached_and_different_input_conflicts(self):
        key, identity = self.key(), str(uuid4())
        body = {'subject': 'Synthetic', 'message': 'Synthetic refund please', 'engine': 'jev', 'request_id': identity}
        first = self.call('/v1/classify', body, bearer=key)
        second = self.call('/v1/classify', body, bearer=key)
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(self.engines.calls, 1)
        self.assertEqual(self.call('/v1/classify', {**body, 'message': 'Different synthetic input'}, bearer=key)[0], 409)
        self.assertEqual(self.call('/api/tickets')[1]['tickets'], [])

    def test_pending_request_is_never_automatically_replayed(self):
        key, identity = self.key(), str(uuid4())
        state = {'subject': '', 'message': 'Synthetic request'}
        with self.store.transaction() as db:
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)', (self.a, identity, 'classify', fingerprint(state) + ':jev', 'pending', None, self.clock))
        self.assertEqual(self.call('/v1/classify', {**state, 'engine': 'jev', 'request_id': identity}, bearer=key)[0], 409)
        self.assertEqual(self.engines.calls, 0)

    def test_import_is_atomic_and_retry_safe(self):
        key, identity = self.key(), str(uuid4())
        bad = {'tickets': [self.ticket(), {'subject': 'Invalid'}], 'request_id': identity}
        self.assertEqual(self.call('/v1/tickets', bad, bearer=key)[0], 400)
        self.assertEqual(self.store.state(self.a), [])
        good = {'tickets': [self.ticket()], 'request_id': identity}
        first, second = self.call('/v1/tickets', good, bearer=key), self.call('/v1/tickets', good, bearer=key)
        self.assertEqual(first[1], second[1])
        self.assertEqual(len(self.store.state(self.a)), 1)

    def test_source_update_invalidates_saved_analysis(self):
        workspace = self.app.workspace(self.a)
        result = workspace.import_rows([self.ticket()], str(uuid4()), 'test')
        identity = result['ids'][0]
        workspace.analyze({'id': identity, 'expected_revision': 0}, 'laya-ft', 'test')
        workspace.import_rows([{**self.ticket(), 'message': 'Changed synthetic question'}], str(uuid4()), 'sync', update=True)
        run = self.store.state(self.a)[0]['runs']['laya-ft']
        self.assertIsNone(run['analysis'])
        self.assertEqual(run['status'], 'pending')
        self.assertEqual(run['revision'], 2)

    def test_ticket_classification_api_retry_does_not_repeat_call(self):
        key = self.key()
        self.app.workspace(self.a).import_rows([self.ticket()], str(uuid4()), 'test')
        body = {'engine': 'jev', 'expected_revision': 0, 'request_id': str(uuid4())}
        first = self.call('/v1/tickets/TK-1041/classify', body, bearer=key)
        second = self.call('/v1/tickets/TK-1041/classify', body, bearer=key)
        self.assertEqual(first[0], 200)
        self.assertEqual(first[1], second[1])
        self.assertEqual(self.engines.calls, 1)

    def oauth(self):
        self.store.save_settings(self.a, {'zendesk': {'subdomain': 'example', 'client_id': 'example-client'}})
        requester = Mock(return_value={'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh', 'expires_in': 1800})
        zendesk = Zendesk(self.store, self.app.public_url, requester=requester)
        self.app.zendesk = self.app.scheduler.zendesk = zendesk
        return zendesk, requester

    def test_oauth_pkce_state_is_bound_to_session_and_one_use(self):
        zendesk, requester = self.oauth()
        query = parse_qs(urlsplit(zendesk.begin(self.user)).query)
        self.assertEqual(query['code_challenge_method'], ['S256'])
        state = query['state'][0]
        other, _ = self.store.login('acme', 'admin', 'synthetic-test-password')
        with self.assertRaises(ServiceError):
            zendesk.callback(self.store.session(other), state, 'synthetic-code')
        zendesk.callback(self.user, state, 'synthetic-code')
        with self.assertRaises(ServiceError):
            zendesk.callback(self.user, state, 'synthetic-code')
        self.assertEqual(requester.call_count, 1)
        self.assertIn('code_verifier', requester.call_args.kwargs['body'])

    def test_oauth_expiry_refresh_rotation_and_disconnect(self):
        zendesk, requester = self.oauth()
        state = parse_qs(urlsplit(zendesk.begin(self.user)).query)['state'][0]
        zendesk.callback(self.user, state, 'synthetic-code')
        self.clock += 1800
        requester.return_value = {'access_token': 'synthetic-next-access', 'refresh_token': 'synthetic-next-refresh', 'expires_in': 1800}
        token, _ = zendesk.access_token(self.a)
        self.assertEqual(token, 'synthetic-next-access')
        self.assertEqual(self.store.settings(self.a)['zendesk']['refresh_token'], 'synthetic-next-refresh')
        requester.return_value = {}
        self.assertTrue(zendesk.disconnect(self.a)['provider_revoked'])
        self.assertEqual(requester.call_args.kwargs['method'], 'DELETE')
        self.assertNotIn('access_token', self.store.settings(self.a)['zendesk'])

    def test_oauth_expired_state_does_not_exchange_code(self):
        zendesk, requester = self.oauth()
        state = parse_qs(urlsplit(zendesk.begin(self.user)).query)['state'][0]
        self.clock += 601
        with self.assertRaises(ServiceError):
            zendesk.callback(self.user, state, 'synthetic-code')
        requester.assert_not_called()

    def sync(self):
        self.store.save_settings(self.a, {'zendesk': {'subdomain': 'example', 'access_token': 'synthetic'}})
        self.app.scheduler.zendesk = SimpleNamespace(export=Mock(return_value={'tickets': [{'id': 1, 'subject': 'Synthetic invoice', 'description': 'Synthetic refund request', 'requester_id': 1}], 'after_cursor': 'synthetic-cursor', 'end_of_stream': True}))
        self.app.scheduler.configure(self.a, {'enabled': True, 'interval': 600})

    def test_sync_commits_cursor_and_tickets_together_without_ai(self):
        self.sync()
        self.app.scheduler.run_now(self.a)
        self.assertEqual(len(self.store.state(self.a)), 1)
        self.assertEqual(self.engines.calls, 0)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT cursor FROM jobs WHERE workspace_id=?', (self.a,)).fetchone()[0], 'synthetic-cursor')

    def test_sync_storage_failure_keeps_cursor_and_retries_with_backoff(self):
        self.sync()
        with patch.object(self.store, 'save_state', side_effect=sqlite3.OperationalError('synthetic failure')):
            with self.assertRaises(ServiceError):
                self.app.scheduler.run_now(self.a)
        self.assertEqual(self.store.state(self.a), [])
        with self.store.connect() as db:
            job = db.execute('SELECT * FROM jobs WHERE workspace_id=?', (self.a,)).fetchone()
        self.assertIsNone(job['cursor'])
        self.assertGreater(job['due'], self.clock)
        self.app.scheduler.run_now(self.a)
        self.assertEqual(len(self.store.state(self.a)), 1)

    def test_sync_pause_invalidates_inflight_lease(self):
        self.sync()
        job = self.app.scheduler.claim(self.a, manual=True)
        self.app.scheduler.configure(self.a, {'enabled': False, 'interval': 600})
        with self.assertRaises(ServiceError):
            self.app.scheduler.run(job)
        self.assertEqual(self.store.state(self.a), [])

    def test_sync_validation_failure_keeps_cursor(self):
        self.sync()
        self.app.scheduler.zendesk.export.return_value['tickets'][0]['description'] = 'x' * 3001
        with self.assertRaises(ServiceError):
            self.app.scheduler.run_now(self.a)
        self.assertEqual(self.store.state(self.a), [])
        with self.store.connect() as db:
            self.assertIsNone(db.execute('SELECT cursor FROM jobs WHERE workspace_id=?', (self.a,)).fetchone()[0])

    def test_backup_preserves_isolated_store(self):
        self.app.workspace(self.a).import_rows([self.ticket()], str(uuid4()), 'test')
        target = Path(self.temp.name) / 'synthetic-backup.sqlite3'
        self.store.backup(target)
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(len(json.loads(db.execute('SELECT state FROM workspaces WHERE id=?', (self.a,)).fetchone()[0])), 1)
        with self.assertRaises(ServiceError):
            self.store.backup(target)


if __name__ == '__main__':
    unittest.main()
