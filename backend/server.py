"""Single-user loopback service: bounded HTTP workers, transactional state, isolated models."""
import copy
from collections import deque
from datetime import datetime, timezone
from http import HTTPStatus
import json
import logging
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from wsgiref.headers import Headers

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from projects.jev import provider as jev_provider
from projects.laya_ft import provider as finetuned_provider
from domain import MAX_TICKETS, empty_run, seed_tickets, migrate
from rubric import CATEGORIES, QUESTIONS, TEAMS
from classification import RUBRIC_ID, fingerprint, normalize, paired_summary
from storage import TicketStore

DATA = PROJECT / 'var/tickets.json'
PROVIDERS = {'jev': jev_provider, 'laya-ft': finetuned_provider}
PROVIDER_NAMES = {'jev': 'Jev', 'laya-ft': 'Laya 客服版'}
state_lock = threading.RLock()
inference_locks = {name: threading.Lock() for name in PROVIDERS}
generation = 0
CSRF_TOKEN = secrets.token_urlsafe(32)
MAX_BODY = 24576
ORIGINS = {f'http://{host}:{port}' for host in ('localhost', '127.0.0.1') for port in (5180, 8780)}
logger = logging.getLogger('model_lab')


class RequestError(Exception):
    def __init__(self, message, status=400):
        self.status = status
        super().__init__(message)



_stored = TicketStore(DATA).load()
tickets = migrate(_stored) if _stored is not None else seed_tickets()


def save():
    TicketStore(DATA).save(tickets)


def commit(next_tickets, event, ticket_id=None, provider=None):
    """Caller holds state_lock. Publish memory only after the database commit succeeds."""
    global tickets
    TicketStore(DATA).save(next_tickets, event, ticket_id, provider)
    tickets = next_tickets


def project(ticket, provider):
    return {**ticket, **ticket['runs'][provider]}


def statuses():
    return {'jev': jev_provider.status(),
            'laya-ft': dict(finetuned_provider.model_status)}


def get_provider(name):
    if not isinstance(name, str) or name not in PROVIDERS:
        raise RequestError('无效模型')
    return name


def find_ticket(items, ticket_id):
    if not isinstance(ticket_id, str):
        raise RequestError('无效工单编号')
    ticket = next((item for item in items if item['id'] == ticket_id), None)
    if ticket is None:
        raise RequestError('工单不存在', 404)
    return ticket


def check_revision(run, body):
    expected = body.get('expected_revision')
    if expected is not None and (type(expected) is not int or expected != run.get('revision', 0)):
        raise RequestError('工单结果已在其他窗口更新，请刷新后再操作。', 409)


def append_history(run, label, now):
    run['revision'] = run.get('revision', 0) + 1
    run['history'] = (run['history'] + [{'label': label, 'time': now}])[-100:]


class WriteLimiter:
    def __init__(self):
        self.times = deque()
        self.lock = threading.Lock()

    def check(self):
        with self.lock:
            now = time.monotonic()
            while self.times and self.times[0] <= now - 60:
                self.times.popleft()
            if len(self.times) >= 120:
                raise RequestError('操作过于频繁，请稍后重试。', 429)
            self.times.append(now)


limiter = WriteLimiter()


def guard(headers, method):
    try:
        host = urlsplit('http://' + headers.get('Host', ''))
        if host.hostname not in ('localhost', '127.0.0.1', '::1') or host.username or host.password or host.path or host.query or host.fragment:
            raise ValueError('host')
        _ = host.port
    except ValueError:
        raise RequestError('Only localhost is allowed', 403) from None
    origin = headers.get('Origin')
    if origin and origin not in ORIGINS:
        raise RequestError('Origin is not allowed', 403)
    if headers.get('Sec-Fetch-Site') == 'cross-site':
        raise RequestError('Cross-site requests are not allowed', 403)
    if method == 'POST':
        token = headers.get('X-CSRF-Token', '')
        if not secrets.compare_digest(token, CSRF_TOKEN):
            raise RequestError('安全会话已过期，请刷新后重试。', 403)
        limiter.check()


def route_get(path, provider):
    if path == '/api/session':
        return 200, {'csrf_token': CSRF_TOKEN}
    if path == '/api/health':
        providers = statuses()
        return 200, {**providers[provider], 'providers': providers, 'rubric_id': RUBRIC_ID, 'mode': 'local-single-user', 'release': 'laya-jev-public-v1'}
    if path == '/api/rubric':
        return 200, {'questions': QUESTIONS, 'rubric_id': RUBRIC_ID}
    if path in ('/api/tickets', '/api/export'):
        with state_lock:
            snapshot = copy.deepcopy(tickets)
        current_models = {name: status.get('model') for name, status in statuses().items() if name in PROVIDERS}
        return 200, {'tickets': [project(t, provider) for t in snapshot],
                     'summary': paired_summary(snapshot, 'laya-ft', current_models), 'rubric_id': RUBRIC_ID}
    raise RequestError('Not found', 404)


def route_post(path, body, provider):
    global generation
    now = datetime.now().astimezone().strftime('%m-%d %H:%M')
    if path == '/api/tickets':
        subject, message = body.get('subject', ''), body.get('message', '')
        if not isinstance(subject, str) or not isinstance(message, str) or not 1 <= len(subject.strip()) <= 120 or not 1 <= len(message.strip()) <= 3000:
            raise RequestError('标题需要 1–120 字，正文需要 1–3000 字')
        request_id = body.get('request_id')
        if request_id is not None:
            try:
                request_id = str(UUID(request_id))
            except (ValueError, AttributeError, TypeError):
                raise RequestError('无效请求编号') from None
        with state_lock:
            if request_id:
                existing = next((t for t in tickets if t.get('request_id') == request_id), None)
                if existing:
                    if existing['subject'] != subject.strip() or existing['message'] != message.strip():
                        raise RequestError('同一请求编号不能用于不同内容。', 409)
                    return 200, {'ticket': project(copy.deepcopy(existing), provider)}
            if len(tickets) >= MAX_TICKETS:
                raise RequestError('本地工作空间最多保留 100 条工单，请先导出备份。', 409)
            number = max((int(t['id'].split('-')[1]) for t in tickets), default=1040) + 1
            ticket = {'id': f'TK-{number}', 'subject': subject.strip(), 'message': message.strip(),
                      'customer': '本地用户', 'company': '自定义工单', 'channel': '手动创建', 'plan': 'LOCAL',
                      'avatar': 'YOU', 'time': now, 'reference': None, 'request_id': request_id,
                      'runs': {name: empty_run(now) for name in PROVIDERS}}
            commit([ticket, *tickets], 'create', ticket['id'], provider)
            return 201, {'ticket': project(copy.deepcopy(ticket), provider)}
    if path == '/api/reset':
        with state_lock:
            store = TicketStore(DATA)
            if store.path.exists():
                store.backup()
            commit(seed_tickets(), 'reset')
            generation += 1
            return 200, {'tickets': [project(copy.deepcopy(t), provider) for t in tickets]}
    if path not in ('/api/analyze', '/api/assign', '/api/reference', '/api/reopen'):
        raise RequestError('Not found', 404)
    if path != '/api/analyze':
        with state_lock:
            next_tickets = copy.deepcopy(tickets)
            ticket = find_ticket(next_tickets, body.get('id'))
            run = ticket['runs'][provider]
            check_revision(run, body)
            if path == '/api/reference':
                category = body.get('category')
                if category is not None and (not isinstance(category, str) or category not in CATEGORIES):
                    raise RequestError('无效分类')
                ticket['reference'] = {'category': category, 'source': 'human', 'updated_at': now} if category else None
            else:
                if inference_locks[provider].locked():
                    raise RequestError('请等待分析完成', 409)
                if path == '/api/reopen':
                    if run['status'] != 'assigned':
                        raise RequestError('工单当前无需重新打开', 409)
                    run.update(status='analyzed' if run['analysis'] else 'pending', team=None)
                    append_history(run, '已重新打开，等待复核', now)
                else:
                    analysis = run['analysis']
                    if not analysis:
                        raise RequestError('请先分析工单', 409)
                    expected_model = statuses().get(provider, {}).get('model')
                    if analysis.get('rubric_id') != RUBRIC_ID or analysis.get('input_id') != fingerprint({'subject': ticket['subject'], 'message': ticket['message']}) or (expected_model and analysis.get('model') != expected_model):
                        raise RequestError('工单内容、模型或规则已更新，请重新分析。', 409)
                    if analysis['confidence'] < .65 and not body.get('team'):
                        raise RequestError('请根据原文手动选择团队', 409)
                    team = body.get('team', analysis['suggested_team'])
                    if not isinstance(team, str) or team not in set(TEAMS.values()) | {'客户成功'}:
                        raise RequestError('无效团队')
                    if run['status'] == 'assigned':
                        if run['team'] != team:
                            raise RequestError('请先重新打开工单，再调整分配。', 409)
                        return 200, {'ticket': project(ticket, provider)}
                    run.update(team=team, status='assigned')
                    append_history(run, '已分配给 ' + team, now)
            commit(next_tickets, path.rsplit('/', 1)[-1], ticket['id'], provider)
            return 200, {'ticket': project(copy.deepcopy(ticket), provider)}

    # Acquire the inference lock while holding the state lock, closing the
    # assignment/reset race between validating input and starting inference.
    lock = inference_locks[provider]
    with state_lock:
        ticket = find_ticket(tickets, body.get('id'))
        run = ticket['runs'][provider]
        check_revision(run, body)
        if run['status'] == 'assigned' and body.get('evaluation') is not True:
            raise RequestError('请先重新打开已分配的工单，再分析。', 409)
        if statuses().get(provider, {}).get('status') != 'ready':
            raise RequestError('所选模型尚未就绪，请检查模型状态。', 503)
        if not lock.acquire(blocking=False):
            raise RequestError('该模型正在分析，请稍后重试。', 409)
        current_generation = generation
        state = {'subject': ticket['subject'], 'message': ticket['message']}
    try:
        started = time.perf_counter()
        prediction = PROVIDERS[provider].predict(copy.deepcopy(state), copy.deepcopy(QUESTIONS))
        try:
            analysis = normalize(prediction, provider, round((time.perf_counter() - started) * 1000), state, now)
            if provider == 'laya-ft':
                analysis['field_sources'] = prediction.get('field_sources', {})
                analysis['checkpoint_sha256'] = prediction.get('checkpoint_sha256')
        except (ValueError, KeyError, TypeError, AttributeError):
            raise RequestError('模型返回结果不完整，未保存。请重试。', 502) from None
        with state_lock:
            if current_generation != generation:
                raise RequestError('工单已重置，旧分析结果已丢弃。', 409)
            next_tickets = copy.deepcopy(tickets)
            updated = find_ticket(next_tickets, body['id'])
            result = updated['runs'][provider]
            result['analysis'] = analysis
            if result['status'] != 'assigned':
                result.update(status='analyzed', team=None)
            append_history(result, PROVIDER_NAMES[provider] + ' 已完成分析', now)
            commit(next_tickets, 'analyze', updated['id'], provider)
            return 200, {'ticket': project(copy.deepcopy(updated), provider)}
    finally:
        lock.release()


def dispatch(method, path, headers, stream):
    guard(headers, method)
    url = urlsplit(path)
    query_provider = parse_qs(url.query).get('provider', [None])[0]
    if method == 'GET':
        return route_get(url.path, get_provider(query_provider or 'laya-ft'))
    if method != 'POST':
        raise RequestError('Method not allowed', 405)
    if headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/json':
        raise RequestError('JSON body required', 415)
    length = headers.get('Content-Length', '')
    if not length.isdecimal():
        raise RequestError('Invalid content length')
    size = int(length)
    if not 0 < size <= MAX_BODY:
        raise RequestError('Request is too large or empty', 413)
    raw = stream.read(size)
    if len(raw) != size:
        raise RequestError('Incomplete request body')
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise RequestError('Expected an object')
    provider = get_provider(body.get('provider', query_provider or 'laya-ft'))
    if query_provider and query_provider != provider:
        raise RequestError('模型参数不一致')
    return route_post(url.path, body, provider)


def application(environ, start_response):
    request_id = uuid4().hex
    headers = Headers([(key[5:].replace('_', '-'), value) for key, value in environ.items() if key.startswith('HTTP_')])
    for name in ('CONTENT_TYPE', 'CONTENT_LENGTH'):
        if name in environ:
            headers[name.replace('_', '-').title()] = environ[name]
    path = environ.get('PATH_INFO', '/')
    if environ.get('QUERY_STRING'):
        path += '?' + environ['QUERY_STRING']
    try:
        status, value = dispatch(environ['REQUEST_METHOD'], path, headers, environ['wsgi.input'])
    except (RequestError, jev_provider.ProviderError) as exc:
        status, value = exc.status, {'error': str(exc)}
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        status, value = 400, {'error': '请求格式无效'}
    except (OSError, sqlite3.Error):
        logger.error('storage_failure request_id=%s', request_id)
        status, value = 503, {'error': '数据未保存，请检查磁盘空间与访问权限后重试。'}
    except Exception as exc:
        logger.error('request_failure request_id=%s type=%s', request_id, type(exc).__name__)
        status, value = 500, {'error': '操作失败，请刷新后重试。'}
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
    response_headers = [('Content-Type', 'application/json; charset=utf-8'), ('Content-Length', str(len(payload))),
                        ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                        ('X-Frame-Options', 'DENY'), ('Referrer-Policy', 'no-referrer'),
                        ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'"), ('X-Request-ID', request_id)]
    if status == 429:
        response_headers.append(('Retry-After', '60'))
    if status == 405:
        response_headers.append(('Allow', 'GET, POST'))
    start_response(f'{status} {HTTPStatus(status).phrase}', response_headers)
    return [payload]


def load_local_models():
    finetuned_provider.load(QUESTIONS)


if __name__ == '__main__':
    from waitress import create_server
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    # Bind before any migration/write: a second process must not overwrite state
    # before discovering that the workspace is already served by another process.
    http = create_server(application, host='127.0.0.1', port=8780, threads=8, connection_limit=32,
                         max_request_header_size=8192, max_request_body_size=MAX_BODY, channel_timeout=30,
                         expose_tracebacks=False, clear_untrusted_proxy_headers=True, ident='ModelLab')
    try:
        save()
        threading.Thread(target=load_local_models, daemon=True).start()
        print('Model Lab API: http://127.0.0.1:8780 (Waitress, single user)', flush=True)
        http.run()
    finally:
        http.close()
        http.task_dispatcher.shutdown()
