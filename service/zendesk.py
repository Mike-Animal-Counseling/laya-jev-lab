"""PKCE, one-use state, encrypted tokens, refresh rotation and cursor export."""
import base64
import hashlib
import re
import secrets
import threading
from urllib.parse import urlencode

from .errors import ServiceError
from .store import token_hash
from .transport import request


def configuration(body, previous=None):
    if not isinstance(body, dict):
        raise ServiceError('Invalid Zendesk configuration.')
    domain = body.get('subdomain', '')
    client = body.get('client_id', '')
    secret = body.get('client_secret', '')
    if not isinstance(domain, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', domain):
        raise ServiceError('Enter a valid Zendesk subdomain.')
    if not isinstance(client, str) or not 1 <= len(client) <= 256 or any(ord(c) < 33 for c in client):
        raise ServiceError('Enter the OAuth client identifier.')
    if not isinstance(secret, str) or len(secret) > 4096 or any(ord(c) < 32 for c in secret):
        raise ServiceError('Invalid OAuth client configuration.')
    same = previous and previous.get('subdomain') == domain and previous.get('client_id') == client
    result = dict(previous) if same else {}
    result.update(subdomain=domain, client_id=client)
    if secret:
        result['client_secret'] = secret
    return result


class Zendesk:
    def __init__(self, store, public_url, *, requester=request):
        self.store, self.public_url, self.request = store, public_url, requester
        self._locks, self._lock = {}, threading.Lock()

    def lock(self, workspace):
        with self._lock:
            return self._locks.setdefault(workspace, threading.RLock())

    def begin(self, user):
        workspace = user['workspace_id']
        settings = self.store.settings(workspace).get('zendesk', {})
        if not settings.get('client_id') or not settings.get('subdomain'):
            raise ServiceError('Save a Zendesk OAuth client first.', 409)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        record = {'verifier': verifier, 'subdomain': settings['subdomain'], 'client_id': settings['client_id']}
        with self.store.transaction() as db:
            db.execute('DELETE FROM oauth_states WHERE expires<=? OR (workspace_id=? AND user_id=?)', (self.store.clock(), workspace, user['id']))
            db.execute('INSERT INTO oauth_states VALUES(?,?,?,?,?,?)', (token_hash(state), workspace, user['id'], user['hash'], self.store.encrypt(workspace, record), self.store.clock() + 600))
        query = urlencode({'response_type': 'code', 'client_id': settings['client_id'], 'redirect_uri': self.public_url + '/api/oauth/zendesk/callback', 'scope': 'tickets:read', 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256', 'expires_in': 1800, 'refresh_token_expires_in': 2592000})
        return f"https://{settings['subdomain']}.zendesk.com/oauth/authorizations/new?{query}"

    def callback(self, user, state, code, error=False):
        if not isinstance(state, str) or not 20 <= len(state) <= 200:
            raise ServiceError('Invalid or expired authorization state.', 400)
        with self.store.transaction() as db:
            row = db.execute('SELECT * FROM oauth_states WHERE hash=? AND workspace_id=? AND user_id=? AND session_hash=? AND expires>?', (token_hash(state), user['workspace_id'], user['id'], user['hash'], self.store.clock())).fetchone()
            if not row:
                raise ServiceError('Invalid or expired authorization state.', 400)
            db.execute('DELETE FROM oauth_states WHERE hash=?', (row['hash'],))
            record = self.store.decrypt(user['workspace_id'], row['ciphertext'])
        if error:
            raise ServiceError('Zendesk authorization was declined.', 400, 'authorization_declined')
        if not isinstance(code, str) or not 1 <= len(code) <= 2048:
            raise ServiceError('Invalid authorization code.')
        workspace = user['workspace_id']
        with self.lock(workspace):
            settings = self.store.settings(workspace)
            config = settings.get('zendesk', {})
            if any(config.get(k) != record[k] for k in ('subdomain', 'client_id')):
                raise ServiceError('Connection settings changed. Connect again.', 409)
            body = {'grant_type': 'authorization_code', 'code': code, 'client_id': config['client_id'], 'redirect_uri': self.public_url + '/api/oauth/zendesk/callback', 'code_verifier': record['verifier'], 'expires_in': 1800, 'refresh_token_expires_in': 2592000}
            if config.get('client_secret'):
                body['client_secret'] = config['client_secret']
            tokens = self.request(f"https://{config['subdomain']}.zendesk.com/oauth/tokens", method='POST', body=body)
            self.save_tokens(workspace, tokens)

    def save_tokens(self, workspace, tokens):
        if not isinstance(tokens, dict) or not isinstance(tokens.get('access_token'), str) or not isinstance(tokens.get('refresh_token'), str) or not 1 <= len(tokens['access_token']) <= 4096 or not 1 <= len(tokens['refresh_token']) <= 4096:
            raise ServiceError('Zendesk returned an invalid token response.', 502, 'invalid_token_response')
        if any(ord(c) < 33 for k in ('access_token', 'refresh_token') for c in tokens[k]):
            raise ServiceError('Zendesk returned an invalid token response.', 502, 'invalid_token_response')
        expiry = tokens.get('expires_in')
        if type(expiry) is not int or not 60 <= expiry <= 172800:
            raise ServiceError('Zendesk must return expiring tokens with refresh support.', 502, 'invalid_token_response')
        # Save rotating refresh credentials atomically before any further requests.
        with self.store.transaction() as db:
            settings = self.store.settings(workspace, db)
            settings['zendesk'].update(access_token=tokens['access_token'], refresh_token=tokens['refresh_token'], expires_at=self.store.clock() + expiry)
            self.store.save_settings(workspace, settings, db)

    def access_token(self, workspace, force=False):
        with self.lock(workspace):
            config = self.store.settings(workspace).get('zendesk', {})
            if not config.get('access_token'):
                raise ServiceError('Connect Zendesk first.', 409, 'not_connected')
            if not force and config.get('expires_at', 0) > self.store.clock() + 60:
                return config['access_token'], config['subdomain']
            body = {'grant_type': 'refresh_token', 'refresh_token': config['refresh_token'], 'client_id': config['client_id'], 'expires_in': 1800, 'refresh_token_expires_in': 2592000}
            if config.get('client_secret'):
                body['client_secret'] = config['client_secret']
            tokens = self.request(f"https://{config['subdomain']}.zendesk.com/oauth/tokens", method='POST', body=body)
            self.save_tokens(workspace, tokens)
            return tokens['access_token'], config['subdomain']

    def api(self, workspace, path):
        token, domain = self.access_token(workspace)
        try:
            return self.request(f'https://{domain}.zendesk.com{path}', token=token)
        except ServiceError as exc:
            if exc.code != 'source_unauthorized':
                raise
        token, domain = self.access_token(workspace, force=True)
        return self.request(f'https://{domain}.zendesk.com{path}', token=token)

    def export(self, workspace, cursor, start_time):
        query = {'per_page': 100, 'exclude_deleted': 'true'}
        if cursor:
            query['cursor'] = cursor
        else:
            query['start_time'] = start_time
        payload = self.api(workspace, '/api/v2/incremental/tickets/cursor.json?' + urlencode(query))
        if not isinstance(payload, dict) or not isinstance(payload.get('tickets'), list) or len(payload['tickets']) > 100 or not isinstance(payload.get('after_cursor'), str) or not 1 <= len(payload['after_cursor']) <= 2048 or type(payload.get('end_of_stream')) is not bool:
            raise ServiceError('Zendesk returned an invalid incremental page.', 502, 'invalid_page')
        return payload

    def disconnect(self, workspace):
        revoked = False
        with self.lock(workspace):
            config = self.store.settings(workspace).get('zendesk', {})
            if config.get('access_token'):
                try:
                    token, domain = self.access_token(workspace)
                    self.request(f'https://{domain}.zendesk.com/api/v2/oauth/tokens/current', method='DELETE', token=token)
                    revoked = True
                except ServiceError:
                    pass
            with self.store.transaction() as db:
                settings = self.store.settings(workspace, db)
                config = settings.get('zendesk', {})
                for name in ('access_token', 'refresh_token', 'expires_at'):
                    config.pop(name, None)
                self.store.save_settings(workspace, settings, db)
                db.execute('DELETE FROM oauth_states WHERE workspace_id=?', (workspace,))
                db.execute('UPDATE jobs SET enabled=0,lease=NULL,lease_until=0 WHERE workspace_id=?', (workspace,))
        return {'disconnected': True, 'provider_revoked': revoked}
