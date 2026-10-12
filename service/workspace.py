"""One shared inbox per workspace; all persistence queries carry its identity."""
import copy
from datetime import datetime, timezone
import json
import threading
from uuid import UUID

from ticket_engine.normalization import RUBRIC_ID, fingerprint
from ticket_engine.rules import CATEGORIES, TEAMS
from .errors import ServiceError
from .shared import batch_digest, classify_rows, empty_run, normalize_row, paired_summary, row_key

PROVIDERS = ('laya-ft', 'jev')
MAX_TICKETS = 1000


def request_id(value):
    try:
        return str(UUID(value))
    except (ValueError, AttributeError, TypeError):
        raise ServiceError('Provide a UUID request_id for safe retries.') from None


def project(ticket, provider):
    return {**copy.deepcopy(ticket), **copy.deepcopy(ticket['runs'][provider])}


def now():
    return datetime.now(timezone.utc).strftime('%m-%d %H:%M')


def ticket_by_id(items, identity):
    if not isinstance(identity, str):
        raise ServiceError('Invalid ticket ID.')
    for ticket in items:
        if ticket['id'] == identity:
            return ticket
    raise ServiceError('Ticket not found.', 404)


def history(run, label, actor):
    run['revision'] += 1
    run['history'] = (run['history'] + [{'label': label, 'time': now(), 'actor': actor}])[-100:]


class Workspace:
    def __init__(self, store, identity, engines):
        self.store, self.identity, self.engines = store, identity, engines
        self.inference_locks = {provider: threading.Lock() for provider in PROVIDERS}

    def list(self, provider):
        tickets = self.store.state(self.identity)
        models = {name: value.get('model') for name, value in self.engines.status(self.identity).items()}
        return {'tickets': [project(t, provider) for t in tickets], 'summary': paired_summary(tickets, 'laya-ft', models), 'rubric_id': RUBRIC_ID}

    def preview(self, sheet, rows):
        tickets = self.store.state(self.identity)
        classified = classify_rows(rows, tickets)
        return {'sheet': sheet, 'rows': classified, 'available': MAX_TICKETS - len(tickets), 'ready': sum(r['status'] == 'ready' for r in classified), 'duplicates': sum(r['status'] == 'duplicate' for r in classified), 'errors': sum(r['status'] == 'error' for r in classified)}

    def import_rows(self, raw, identity, actor, *, update=False, db=None):
        identity = request_id(identity)
        if not isinstance(raw, list) or not 1 <= len(raw) <= 100:
            raise ServiceError('Import between 1 and 100 tickets.')
        rows = [normalize_row(row) for row in raw]
        digest = batch_digest(rows) + (':update' if update else ':insert')
        if db is None:
            with self.store.transaction() as connection:
                return self.import_rows(rows, identity, actor, update=update, db=connection)
        previous = db.execute('SELECT kind,input_hash,result FROM requests WHERE workspace_id=? AND request_id=?', (self.identity, identity)).fetchone()
        if previous:
            if previous['kind'] != 'import' or previous['input_hash'] != digest:
                raise ServiceError('Request ID already used for different input.', 409)
            return json.loads(previous['result'])
        self.store.prune_requests(db, self.identity)
        items = self.store.state(self.identity, db)
        known = {row_key(t): t for t in items}
        number = max((int(t['id'].split('-')[1]) for t in items), default=1040)
        db.execute('INSERT OR IGNORE INTO ticket_sequences VALUES(?,?)', (self.identity, number))
        number = max(number, db.execute('SELECT value FROM ticket_sequences WHERE workspace_id=?', (self.identity,)).fetchone()[0])
        added, updated, skipped, ids = [], 0, 0, []
        for row in rows:
            key = row_key(row)
            old = known.get(key)
            if old:
                if update and any(old.get(k) != value for k, value in row.items()):
                    changed_input = old['subject'] != row['subject'] or old['message'] != row['message']
                    old.update(row)
                    if changed_input:
                        old['reference'] = None
                        for provider in PROVIDERS:
                            revision, events = old['runs'][provider]['revision'], old['runs'][provider]['history']
                            old['runs'][provider] = {**empty_run(now()), 'revision': revision + 1, 'history': (events + [{'label': 'Source updated', 'time': now(), 'actor': actor}])[-100:]}
                    updated += 1
                else:
                    skipped += 1
                ids.append(old['id'])
                continue
            number += 1
            ticket = {**row, 'id': f'TK-{number}', 'plan': 'LOCAL', 'avatar': 'IN', 'time': now(), 'reference': None, 'runs': {name: empty_run(now()) for name in PROVIDERS}}
            known[key] = ticket
            added.append(ticket)
            ids.append(ticket['id'])
        if len(items) + len(added) > MAX_TICKETS:
            raise ServiceError('Workspace capacity reached. Export and archive old tickets first.', 409, 'capacity_reached')
        result = {'imported': len(added), 'updated': updated, 'skipped': skipped, 'ids': ids, 'request_id': identity}
        if added or updated:
            self.store.save_state(db, self.identity, [*added, *items], actor, 'import')
        db.execute('UPDATE ticket_sequences SET value=? WHERE workspace_id=?', (number, self.identity))
        db.execute('INSERT INTO requests VALUES(?,?,?,?,?,?,?)', (self.identity, identity, 'import', digest, 'complete', json.dumps(result), self.store.clock()))
        return result

    def mutate(self, action, body, provider, actor):
        with self.store.transaction() as db:
            items = self.store.state(self.identity, db)
            ticket = ticket_by_id(items, body.get('id'))
            run = ticket['runs'][provider]
            expected = body.get('expected_revision')
            if type(expected) is not int or expected != run['revision']:
                raise ServiceError('Ticket changed. Refresh before trying again.', 409)
            if action == 'reference':
                category = body.get('category')
                if category is not None and (not isinstance(category, str) or category not in CATEGORIES):
                    raise ServiceError('Invalid reference category.')
                ticket['reference'] = {'category': category, 'source': 'human', 'updated_at': now()} if category else None
                history(run, 'Reference updated', actor)
            elif action == 'resolve':
                if run['status'] != 'done':
                    run['status'] = 'done'
                    history(run, 'Marked done', actor)
            elif action == 'reopen':
                if run['status'] not in ('done', 'assigned'):
                    raise ServiceError('Ticket is already open.', 409)
                run.update(status='analyzed' if run['analysis'] else 'pending', team=None)
                history(run, 'Ticket reopened', actor)
            elif action == 'assign':
                result = run['analysis']
                if not result or run['status'] == 'done':
                    raise ServiceError('Analyze an open ticket before assigning.', 409)
                model = self.engines.status(self.identity).get(provider, {}).get('model')
                if result.get('input_id') != fingerprint({'subject': ticket['subject'], 'message': ticket['message']}) or result.get('rubric_id') != RUBRIC_ID or result.get('model') != model:
                    raise ServiceError('Ticket, model or rules changed. Analyze again.', 409)
                team = body.get('team') or result['suggested_team']
                if result['confidence'] < .65 and not body.get('team'):
                    raise ServiceError('Choose a team manually.', 409)
                if not isinstance(team, str) or team not in set(TEAMS.values()) | {'客户成功'}:
                    raise ServiceError('Invalid team.')
                if run['status'] == 'assigned' and run['team'] != team:
                    raise ServiceError('Reopen before changing its team.', 409)
                if run['status'] != 'assigned':
                    run.update(status='assigned', team=team)
                    history(run, 'Assigned', actor)
            else:
                raise ServiceError('Not found.', 404)
            self.store.save_state(db, self.identity, items, actor, action, ticket['id'])
            return {'ticket': project(ticket, provider)}

    def analyze(self, body, provider, actor):
        lock = self.inference_locks[provider]
        if not lock.acquire(blocking=False):
            raise ServiceError('This model is busy in your workspace.', 409)
        try:
            items = self.store.state(self.identity)
            ticket = ticket_by_id(items, body.get('id'))
            run = ticket['runs'][provider]
            revision = run['revision']
            if type(body.get('expected_revision')) is not int or body['expected_revision'] != revision:
                raise ServiceError('Ticket changed. Refresh first.', 409)
            if run['status'] in ('assigned', 'done') and body.get('evaluation') is not True:
                raise ServiceError('Reopen the ticket before analyzing.', 409)
            state = {'subject': ticket['subject'], 'message': ticket['message']}
            result = self.engines.classify(self.identity, provider, state).to_dict()
            result['provider'] = provider
            result['field_sources'] = {name: provider for name in ('category', 'urgency', 'complaint', 'churn', 'refund')}
            with self.store.transaction() as db:
                items = self.store.state(self.identity, db)
                current = ticket_by_id(items, body['id'])
                current_run = current['runs'][provider]
                if (current_run['revision'] != revision or fingerprint({'subject': current['subject'], 'message': current['message']}) != result['input_id']
                        or self.engines.status(self.identity)[provider]['model'] != result['model']):
                    raise ServiceError('Ticket changed during analysis. Result was discarded.', 409)
                current_run['analysis'] = result
                if current_run['status'] not in ('done', 'assigned'):
                    current_run.update(status='analyzed', team=None)
                history(current_run, 'Analysis complete', actor)
                self.store.save_state(db, self.identity, items, actor, 'analyze', current['id'])
                return {'ticket': project(current, provider)}
        finally:
            lock.release()
