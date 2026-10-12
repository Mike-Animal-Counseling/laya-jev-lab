"""Authenticated same-origin inbox and scoped REST integration service."""
from collections import OrderedDict, deque
from http.cookies import SimpleCookie
from http import HTTPStatus
import json
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from wsgiref.headers import Headers

from ticket_engine import EngineError
from ticket_engine.engine import validate_input
from ticket_engine.normalization import RUBRIC_ID, fingerprint
from ticket_engine.rules import QUESTIONS
from .errors import ServiceError
from .scheduler import Scheduler
from .shared import IntakeError, api_rows, parse_csv, parse_eml, parse_excel, template_bytes, zendesk_rows
from .store import token_hash
from .workspace import Workspace, project, request_id, ticket_by_id
from .zendesk import Zendesk, configuration
from .training import Training


@dataclass
class Download:
    body: bytes
    content_type: str
    filename: str


class Limiter:
    def __init__(self, clock=time.monotonic):
        self.clock, self.rows, self.lock = clock, OrderedDict(), threading.Lock()

    def check(self, key, limit, window=60):
        with self.lock:
            now = self.clock()
            times = self.rows.pop(key, deque())
            while times and times[0] <= now - window:
                times.popleft()
            self.rows[key] = times
            while len(self.rows) > 4096:
                self.rows.popitem(last=False)
            if len(times) >= limit:
                raise ServiceError('Too many requests. Try again later.', 429, 'rate_limited')
            times.append(now)


class Application:
    def __init__(self, store, engines, public_url, *, zendesk=None, training=None):
        parsed = urlsplit(public_url)
        if parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment or not parsed.hostname or parsed.scheme not in ('http', 'https') or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1')):
            raise ServiceError('Configure one HTTPS public origin, or HTTP localhost for development.', 503, 'invalid_configuration')
        self.public_url = public_url.rstrip('/')
        self.cookie_name = '__Host-laya-session' if parsed.scheme == 'https' else 'laya-session'
        self.secure_cookie = parsed.scheme == 'https'
        self.store, self.engines = store, engines
        self.zendesk = zendesk or Zendesk(store, self.public_url)
        self.scheduler = Scheduler(store, self.zendesk, self.workspace)
        self.training = training or Training(store, engines)
        self.workspaces, self.workspace_lock = {}, threading.Lock()
        self.limiter = Limiter()

    def workspace(self, identity):
        with self.workspace_lock:
            return self.workspaces.setdefault(identity, Workspace(self.store, identity, self.engines))

    def cookie(self, value, clear=False):
        return self.cookie_name + '=' + value + '; Path=/; HttpOnly; SameSite=Lax; Max-Age=' + ('0' if clear else '28800') + ('; Secure' if self.secure_cookie else '')

    def session(self, headers):
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get('Cookie', ''))
            value = cookie.get(self.cookie_name)
            return self.store.session(value.value) if value else None
        except (ValueError, TypeError):
            return None

    def browser_origin(self, headers):
        if headers.get('Origin') != self.public_url or headers.get('Sec-Fetch-Site') == 'cross-site':
            raise ServiceError('Request origin is not allowed.', 403, 'forbidden_origin')

    def require(self, user, role='member'):
        if not user:
            raise ServiceError('Sign in to continue.', 401, 'unauthorized')
        allowed = {'owner'} if role == 'owner' else {'owner', 'member'} if role == 'member' else {'owner', 'member', 'viewer'}
        if user['role'] not in allowed:
            raise ServiceError('Your role cannot perform this action.', 403, 'forbidden')

    def body(self, environ, upload=False):
        length = environ.get('CONTENT_LENGTH', '')
        large = upload or environ.get('PATH_INFO') in ('/api/import', '/v1/tickets')
        if len(length) > 12 or not length.isdecimal() or not 0 < int(length) <= (2 * 1024 * 1024 if large else 24576):
            raise ServiceError('Request body is empty or too large.', 413)
        raw = environ['wsgi.input'].read(int(length))
        if len(raw) != int(length):
            raise ServiceError('Incomplete request body.')
        if upload:
            return raw
        if environ.get('CONTENT_TYPE', '').split(';')[0].strip().lower() != 'application/json':
            raise ServiceError('JSON body required.', 415)
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError('shape')
            return body
        except (ValueError, UnicodeError):
            raise ServiceError('Expected a JSON object.') from None

    def provider(self, value):
        if value not in ('laya-ft', 'jev'):
            raise ServiceError('Choose laya-ft or jev.')
        return value

    def connection_status(self, workspace):
        settings = self.store.settings(workspace)
        values = settings.get('connections', {})
        return {'zendesk': bool(settings.get('zendesk', {}).get('access_token')), 'api': bool(values.get('TICKET_API_URL')), 'email': all(values.get(k) for k in ('MAIL_IMAP_HOST', 'MAIL_IMAP_USER', 'MAIL_IMAP_PASSWORD'))}

    def settings_view(self, workspace):
        settings = self.store.settings(workspace)
        zendesk = settings.get('zendesk', {})
        return {'connections': self.connection_status(workspace), 'zendesk': {'subdomain': zendesk.get('subdomain', ''), 'client_id': zendesk.get('client_id', ''), 'has_client_secret': bool(zendesk.get('client_secret')), 'expires_at': zendesk.get('expires_at')}, 'jev_configured': bool(settings.get('jev_api_key')), 'sync': self.scheduler.status(workspace), 'members': self.store.members(workspace), 'api_keys': self.store.api_keys(workspace)}

    def pull(self, workspace, source):
        if source == 'zendesk':
            payload = self.zendesk.api(workspace, '/api/v2/tickets.json?per_page=100&sort_by=updated_at&sort_order=desc')
            rows = zendesk_rows(payload)
            domain = self.store.settings(workspace)['zendesk']['subdomain']
            for _, row, issue in rows:
                if not issue:
                    row['source_id'] = domain + ':' + row['source_id']
            return 'Zendesk', rows
        from connectors import KEYS, pull_api, pull_mail
        values = {key: '' for key in KEYS}
        values.update(self.store.settings(workspace).get('connections', {}))
        if source == 'api':
            return pull_api('api', values)
        if source == 'email':
            return pull_mail(values)
        raise ServiceError('Choose Zendesk, API or email.')

    def inbox(self, method, path, user, provider, body, environ):
        workspace = self.workspace(user['workspace_id'])
        if method == 'GET':
            if path == '/api/session':
                return {'csrf_token': user['csrf']}
            if path == '/api/health':
                providers = self.engines.status(user['workspace_id'])
                return {**providers[provider], 'providers': providers, 'rubric_id': RUBRIC_ID, 'mode': 'cloud-workspace', 'release': '0.2.0'}
            if path in ('/api/tickets', '/api/export'):
                return workspace.list(provider)
            if path == '/api/rubric':
                return {'questions': QUESTIONS, 'rubric_id': RUBRIC_ID}
            if path == '/api/import/template':
                return template_bytes()
            if path == '/api/intake/status':
                return self.connection_status(user['workspace_id'])
            raise ServiceError('Not found.', 404)
        if path == '/api/import/preview':
            parsers = {'text/csv': parse_csv, 'message/rfc822': parse_eml, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': parse_excel}
            parser = parsers.get(environ.get('CONTENT_TYPE', '').split(';')[0].strip().lower())
            if not parser:
                raise ServiceError('Choose .xlsx, .csv or .eml.', 415)
            return workspace.preview(*parser(body))
        if path == '/api/intake/preview':
            return workspace.preview(*self.pull(user['workspace_id'], body.get('source')))
        if path == '/api/import':
            result = workspace.import_rows(body.get('rows'), body.get('request_id'), user['username'])
            return {**workspace.list(provider), **result}
        if path == '/api/tickets':
            identity = request_id(body.get('request_id'))
            row = {'subject': body.get('subject'), 'message': body.get('message'), 'customer': user['username'], 'company': user['name'], 'channel': 'Manual'}
            result = workspace.import_rows([row], identity, user['username'])
            ticket = ticket_by_id(self.store.state(user['workspace_id']), result['ids'][0])
            return {'ticket': project(ticket, provider)}
        if path == '/api/analyze':
            return workspace.analyze(body, provider, user['username'])
        if path in ('/api/assign', '/api/reference', '/api/resolve', '/api/reopen'):
            return workspace.mutate(path.rsplit('/', 1)[-1], body, provider, user['username'])
        raise ServiceError('Not found.', 404)

    def admin(self, path, user, body):
        workspace = user['workspace_id']
        if path == '/api/settings/jev':
            key = body.get('api_key')
            if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 33 for c in key):
                raise ServiceError('Invalid Jev API key.')
            with self.store.transaction() as db:
                settings = self.store.settings(workspace, db)
                settings['jev_api_key'] = key
                self.store.save_settings(workspace, settings, db)
                self.store.audit(db, workspace, user['username'], 'jev_configured')
            return {'configured': bool(key)}
        if path == '/api/settings/zendesk':
            with self.zendesk.lock(workspace):
                with self.store.transaction() as db:
                    settings = self.store.settings(workspace, db)
                    old = settings.get('zendesk', {})
                    config = configuration(body, old)
                    if old.get('subdomain') != config['subdomain'] or old.get('client_id') != config['client_id']:
                        db.execute('UPDATE jobs SET cursor=NULL,enabled=0,start_time=?,lease=NULL,lease_until=0 WHERE workspace_id=?', (int(self.store.clock()) - 3600, workspace))
                        db.execute('DELETE FROM oauth_states WHERE workspace_id=?', (workspace,))
                    settings['zendesk'] = config
                    self.store.save_settings(workspace, settings, db)
                    self.store.audit(db, workspace, user['username'], 'zendesk_configured')
            return {'saved': True}
        if path == '/api/settings/connections':
            from connectors import KEYS
            allowed = set(KEYS) - {'ZENDESK_SUBDOMAIN', 'ZENDESK_OAUTH_TOKEN', 'ZENDESK_EMAIL', 'ZENDESK_API_TOKEN'}
            values = body.get('values')
            if not isinstance(values, dict) or set(values) - allowed or any(not isinstance(v, str) or len(v) > 4096 or any(ord(c) < 32 for c in v) for v in values.values()):
                raise ServiceError('Invalid source settings.')
            with self.store.transaction() as db:
                settings = self.store.settings(workspace, db)
                settings.setdefault('connections', {}).update(values)
                self.store.save_settings(workspace, settings, db)
                self.store.audit(db, workspace, user['username'], 'sources_configured')
            return {'saved': True}
        if path == '/api/oauth/zendesk/start':
            return {'url': self.zendesk.begin(user)}
        if path == '/api/oauth/zendesk/disconnect':
            return self.zendesk.disconnect(workspace)
        if path == '/api/sync/configure':
            return self.scheduler.configure(workspace, body)
        if path == '/api/sync/run':
            return self.scheduler.run_now(workspace)
        if path == '/api/members/invite':
            token = self.store.invite(workspace, body.get('username'), body.get('role'))
            return {'url': self.public_url + '/join#token=' + token}
        if path == '/api/members/disable':
            self.store.disable_member(workspace, body.get('id'))
            return {'disabled': True}
        if path == '/api/keys/create':
            token = self.store.create_api_key(workspace, body.get('name'), body.get('scopes'), body.get('days', 90))
            return {'token': token, 'message': 'Save this key now. It will not be shown again.'}
        if path == '/api/keys/revoke':
            self.store.revoke_api_key(workspace, body.get('id'))
            return {'revoked': True}
        if path == '/api/tickets/archive':
            ids = body.get('ids')
            if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) for i in ids) or body.get('confirm') is not True:
                raise ServiceError('Confirm up to 100 ticket IDs to permanently archive.')
            with self.store.transaction() as db:
                items = self.store.state(workspace, db)
                remaining = [t for t in items if t['id'] not in set(ids)]
                self.store.save_state(db, workspace, remaining, user['username'], 'archive')
            return {'archived': len(items) - len(remaining)}
        raise ServiceError('Not found.', 404)

    def rest(self, method, path, user, query, body, headers):
        workspace = user['workspace_id']
        scope = 'tickets:read' if method == 'GET' else 'classify' if path in ('/v1/classify', '/v1/compare') or path.endswith('/classify') else 'tickets:write'
        if scope not in user['scopes']:
            raise ServiceError('Integration key lacks the required scope.', 403, 'insufficient_scope')
        if method == 'GET':
            if path == '/v1/tickets':
                try:
                    offset = int(query.get('offset', ['0'])[0])
                    limit = int(query.get('limit', ['100'])[0])
                    if not 0 <= offset <= 1000 or not 1 <= limit <= 100:
                        raise ValueError('bounds')
                except ValueError:
                    raise ServiceError('Use offset 0 to 1000 and limit 1 to 100.') from None
                items = self.store.state(workspace)
                return {'tickets': items[offset:offset+limit], 'next_offset': offset + limit if offset + limit < len(items) else None}
            if re.fullmatch(r'/v1/tickets/TK-\d+', path):
                return {'ticket': ticket_by_id(self.store.state(workspace), path.rsplit('/', 1)[-1])}
            if path.startswith('/v1/requests/'):
                identity = request_id(path.rsplit('/', 1)[-1])
                with self.store.connect() as db:
                    row = db.execute('SELECT status,result FROM requests WHERE workspace_id=? AND request_id=?', (workspace, identity)).fetchone()
                if not row:
                    raise ServiceError('Request not found.', 404)
                return {'request_id': identity, 'status': row['status'], 'result': json.loads(row['result']) if row['result'] else None}
            raise ServiceError('Not found.', 404)
        identity = request_id(headers.get('Idempotency-Key') or body.get('request_id'))
        if path == '/v1/tickets':
            if type(body.get('update', False)) is not bool:
                raise ServiceError('The update flag must be a boolean.')
            return self.workspace(workspace).import_rows(body.get('tickets'), identity, 'integration', update=body.get('update') is True)
        if re.fullmatch(r'/v1/tickets/TK-\d+/classify', path):
            provider = self.provider('laya-ft' if body.get('engine', 'laya') == 'laya' else body.get('engine'))
            ticket = ticket_by_id(self.store.state(workspace), path.split('/')[3])
            if 'tickets:write' not in user['scopes']:
                raise ServiceError('Saving ticket results also requires tickets:write.', 403)
            digest = fingerprint({'subject': ticket['subject'], 'message': ticket['message']}) + ':' + ticket['id'] + ':' + provider + ':' + str(body.get('expected_revision'))
            return self.idempotent(workspace, identity, 'ticket_classify', digest, lambda: self.workspace(workspace).analyze({'id': ticket['id'], 'expected_revision': body.get('expected_revision')}, provider, 'integration'))
        if path not in ('/v1/classify', '/v1/compare'):
            raise ServiceError('Not found.', 404)
        engine = 'compare' if path == '/v1/compare' else body.get('engine', 'laya')
        if engine not in (('compare',) if path == '/v1/compare' else ('laya', 'jev')):
            raise ServiceError('Choose laya or jev, or use the compare endpoint.')
        state = validate_input(body.get('message'), body.get('subject', ''))
        digest = fingerprint(state) + ':' + engine
        self.limiter.check(('classification', workspace), 30)
        return self.idempotent(workspace, identity, 'classify', digest, lambda: {'request_id': identity, 'result': (self.engines.compare(workspace, state) if engine == 'compare' else self.engines.classify(workspace, 'laya-ft' if engine == 'laya' else 'jev', state)).to_dict()})

    def idempotent(self, workspace, identity, kind, digest, action):
        with self.store.transaction() as db:
            previous = db.execute('SELECT * FROM requests WHERE workspace_id=? AND request_id=?', (workspace, identity)).fetchone()
            if previous:
                if previous['kind'] != kind or previous['input_hash'] != digest:
                    raise ServiceError('Request ID already used for different input.', 409)
                if previous['status'] == 'pending':
                    raise ServiceError('Request is pending or its outcome is uncertain. Check its status; it will not be retried automatically.', 409, 'request_pending')
                cached = json.loads(previous['result'])
                if previous['status'] == 'failed':
                    raise ServiceError(cached['message'], cached['status'], cached['code'])
                return cached
            self.store.prune_requests(db, workspace)
            db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)', (workspace, identity, kind, digest, 'pending', None, self.store.clock()))
        try:
            result = action()
        except (EngineError, ServiceError) as exc:
            failure = {'message': str(exc), 'code': exc.code, 'status': exc.status if isinstance(exc, ServiceError) else 502}
            with self.store.transaction() as db:
                db.execute('UPDATE requests SET status=?,result=? WHERE workspace_id=? AND request_id=?', ('failed', json.dumps(failure), workspace, identity))
            raise
        with self.store.transaction() as db:
            db.execute('UPDATE requests SET status=?,result=? WHERE workspace_id=? AND request_id=?', ('complete', json.dumps(result), workspace, identity))
            self.store.audit(db, workspace, 'integration', 'classify', identity)
        return result

    def dispatch(self, environ, headers):
        method, path = environ.get('REQUEST_METHOD', 'GET'), environ.get('PATH_INFO', '/')
        if method not in ('GET', 'POST'):
            raise ServiceError('Method not allowed.', 405)
        try:
            host = urlsplit('http://' + headers.get('Host', ''))
            allowed = {urlsplit(self.public_url).hostname, 'localhost', '127.0.0.1', '::1', 'api'}
            if host.hostname not in allowed or host.username or host.password or host.path or host.query or host.fragment:
                raise ValueError('host')
            _ = host.port
        except ValueError:
            raise ServiceError('Request host is not allowed.', 403, 'forbidden_host') from None
        query = parse_qs(environ.get('QUERY_STRING', ''))
        if method == 'GET' and path == '/healthz':
            return 200, {'status': 'ok', 'release': '0.2.0'}, []
        if method == 'GET' and path == '/v1/openapi.json':
            from .openapi import document
            return 200, document(self.public_url), []
        if path.startswith('/v1/'):
            auth = headers.get('Authorization', '')
            user = self.store.api_key(auth[7:]) if auth.startswith('Bearer ') else None
            if not user:
                raise ServiceError('Provide a valid scoped integration key.', 401, 'unauthorized')
            self.limiter.check(('api', user['workspace_id']), 120)
            body = self.body(environ) if method == 'POST' else None
            return 200, self.rest(method, path, user, query, body, headers), []
        user = self.session(headers)
        if path == '/api/auth/status' and method == 'GET':
            exposed = {k: user[k] for k in ('username', 'role', 'slug', 'name')} if user else None
            return 200, {'mode': 'cloud', 'authenticated': bool(user), 'user': exposed}, []
        if path in ('/api/auth/login', '/api/auth/join') and method == 'POST':
            self.browser_origin(headers)
            self.limiter.check(('login', environ.get('REMOTE_ADDR', '')), 20)
            body = self.body(environ)
            if path.endswith('/join'):
                return 201, self.store.join(body.get('token'), body.get('password')), []
            if any(not isinstance(body.get(k), str) for k in ('workspace', 'username', 'password')):
                raise ServiceError('Provide workspace, username and password.')
            self.limiter.check(('account', token_hash(body['workspace'] + ':' + body['username'])), 5, 300)
            token, _ = self.store.login(body['workspace'], body['username'], body['password'])
            return 200, {'authenticated': True}, [('Set-Cookie', self.cookie(token))]
        self.require(user, 'viewer')
        if method == 'GET' and path == '/api/oauth/zendesk/callback':
            self.require(user, 'owner')
            try:
                self.zendesk.callback(user, query.get('state', [''])[0], query.get('code', [''])[0], error=bool(query.get('error')))
                outcome = 'connected'
            except ServiceError:
                outcome = 'failed'
            return 303, {'status': outcome}, [('Location', self.public_url + '/settings?zendesk=' + outcome)]
        body = None
        if method == 'POST':
            self.browser_origin(headers)
            if not secrets.compare_digest(headers.get('X-CSRF-Token', ''), user['csrf']):
                raise ServiceError('Session expired. Refresh and retry.', 403, 'csrf_failed')
            self.limiter.check(('write', user['workspace_id']), 120)
            body = self.body(environ, upload=path in ('/api/import/preview', '/api/training/preview'))
            if path == '/api/auth/logout':
                self.store.logout_hash(user['hash'])
                return 200, {'authenticated': False}, [('Set-Cookie', self.cookie('', clear=True))]
            self.require(user)
        if path.startswith('/api/training'):
            self.require(user, 'owner')
            workspace = user['workspace_id']
            if method == 'GET' and path == '/api/training':
                return 200, self.training.status(workspace), []
            if method == 'GET' and path == '/api/training/template':
                from training.data import template
                return 200, Download(template().encode(), 'text/csv; charset=utf-8', 'training-template.csv'), []
            if method == 'GET' and path == '/api/training/model':
                value = self.training.download(workspace, query.get('id', [''])[0])
                return 200, Download(value, 'application/zip', 'laya-adapter.zip'), []
            if method == 'POST':
                if path == '/api/training/connect':
                    value = self.training.connect(workspace, body, user['username'])
                elif path == '/api/training/disconnect':
                    value = self.training.disconnect(workspace, user['username'])
                elif path == '/api/training/preview':
                    value = self.training.preview(workspace, body, environ.get('CONTENT_TYPE', '').split(';')[0].strip().lower())
                elif path == '/api/training/start':
                    value = self.training.start_job(workspace, body, user['username'])
                elif path == '/api/training/check':
                    value = self.training.retry(workspace, body.get('id'))
                elif path == '/api/training/abandon':
                    value = self.training.abandon(workspace, body.get('id'), body, user['username'])
                elif path == '/api/training/use':
                    value = self.training.use_model(workspace, body.get('id'), user['username'])
                elif path == '/api/training/restore':
                    value = self.training.restore(workspace, user['username'])
                else:
                    raise ServiceError('Not found.', 404)
                return 200, value, []
            raise ServiceError('Not found.', 404)
        if path == '/api/settings' and method == 'GET':
            self.require(user, 'owner')
            return 200, self.settings_view(user['workspace_id']), []
        if path.startswith(('/api/settings/', '/api/oauth/', '/api/sync/', '/api/members/', '/api/keys/')) or path == '/api/tickets/archive':
            self.require(user, 'owner')
            if method != 'POST':
                raise ServiceError('Method not allowed.', 405)
            return 200, self.admin(path, user, body), []
        provider = self.provider((body.get('provider') if isinstance(body, dict) else None) or query.get('provider', ['laya-ft'])[0])
        if query.get('provider') and query['provider'][0] != provider:
            raise ServiceError('Model parameters do not match.')
        return 200, self.inbox(method, path, user, provider, body, environ), []

    def __call__(self, environ, start_response):
        identity = uuid4().hex
        headers = Headers([(key[5:].replace('_', '-'), value) for key, value in environ.items() if key.startswith('HTTP_')])
        try:
            status, value, extra = self.dispatch(environ, headers)
        except (ServiceError, IntakeError) as exc:
            status = exc.status if isinstance(exc, ServiceError) else 400
            value, extra = {'error': str(exc), 'code': getattr(exc, 'code', 'invalid_import'), 'request_id': identity}, []
        except EngineError as exc:
            status, value, extra = 502, {'error': str(exc), 'code': exc.code, 'request_id': identity}, []
        except (ValueError, TypeError, KeyError, sqlite3.Error, OSError):
            status, value, extra = 503, {'error': 'Service could not complete the request.', 'code': 'service_error', 'request_id': identity}, []
        except Exception:
            status, value, extra = 500, {'error': 'Request failed safely.', 'code': 'internal_error', 'request_id': identity}, []
        if isinstance(value, Download):
            raw, content_type = value.body, value.content_type
            extra.append(('Content-Disposition', f'attachment; filename="{value.filename}"'))
        elif isinstance(value, bytes):
            raw, content_type = value, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            extra.append(('Content-Disposition', 'attachment; filename="tickets.xlsx"'))
        else:
            raw, content_type = json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), 'application/json; charset=utf-8'
        response = [('Content-Type', content_type), ('Content-Length', str(len(raw))), ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'), ('Referrer-Policy', 'no-referrer'), ('X-Request-Id', identity), *extra]
        start_response(f'{status} {HTTPStatus(status).phrase}', response)
        return [raw]
