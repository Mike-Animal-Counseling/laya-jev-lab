"""Ticket schema and legacy migration, independent of HTTP and model loading."""
from fixtures import SEEDS
from classification import fingerprint

PROVIDERS = ('laya-ft', 'jev')
MAX_TICKETS = 100


def empty_run(now):
    return {'analysis': None, 'team': None, 'status': 'pending', 'revision': 0,
            'history': [{'label': '工单已收到', 'time': now}]}


def seed_tickets():
    return [{'id': f'TK-{1048-i}', 'subject': s, 'message': m, 'customer': c, 'company': co,
             'channel': ch, 'plan': p, 'avatar': av, 'time': t, 'reference': None,
             'runs': {name: empty_run(t) for name in PROVIDERS}}
            for i, (s, m, c, co, ch, p, av, t) in enumerate(SEEDS)]


def migrate(items):
    if not isinstance(items, list) or len(items) > MAX_TICKETS:
        raise ValueError('Invalid ticket store; original data has not been overwritten.')
    seen = set()
    for ticket in items:
        if not isinstance(ticket, dict) or not isinstance(ticket.get('id'), str) or ticket['id'] in seen:
            raise ValueError('Invalid or duplicate ticket identity')
        seen.add(ticket['id'])
        for key in ('subject', 'message', 'customer', 'company', 'channel', 'time'):
            if not isinstance(ticket.get(key), str):
                raise ValueError('Invalid ticket field: ' + key)
        if not isinstance(ticket.get('runs'), dict) or set(ticket['runs']) - set(PROVIDERS):
            raise ValueError('Only this demo workspace format is accepted')
        ticket.setdefault('reference', None)
        for name in PROVIDERS:
            run = ticket['runs'].setdefault(name, empty_run(ticket['time']))
            run.setdefault('revision', 0)
            if run.get('status') not in ('pending', 'analyzed', 'assigned') or not isinstance(run.get('history'), list):
                raise ValueError('Invalid model run')
    return items

