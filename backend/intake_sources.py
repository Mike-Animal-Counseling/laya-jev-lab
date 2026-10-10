"""Source adapters converge on the same validated ticket rows; no persistence or models."""
import csv
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from html.parser import HTMLParser
from io import StringIO
import json

from ticket_import import ALIASES, MAX_ROWS, MAX_UPLOAD, ImportError, normalize_row


def validated_rows(items):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ROWS:
        raise ImportError('Use between 1 and 100 tickets.')
    result = []
    for number, item in enumerate(items, 1):
        try:
            result.append((number, normalize_row(item), ''))
        except ImportError as exc:
            result.append((number, {}, str(exc)))
    return result


def parse_csv(raw):
    if not 0 < len(raw) <= MAX_UPLOAD:
        raise ImportError('Choose a UTF-8 CSV file under 2 MB.')
    try:
        text = raw.decode('utf-8-sig')
        reader = csv.reader(StringIO(text, newline=''))
        headers = next(reader)
        mapping = [ALIASES.get(header.strip().lower()) for header in headers]
        if None in mapping or len(mapping) != len(set(mapping)) or not {'subject', 'message'} <= set(mapping):
            raise ImportError('Use unique Subject, Message, Customer, Company or Channel columns.')
        rows = []
        for number, values in enumerate(reader, 2):
            if not values or not any(v.strip() for v in values):
                continue
            if len(rows) >= MAX_ROWS:
                raise ImportError('Use at most 100 rows per import.')
            issue = ''
            if len(values) != len(mapping):
                issue = 'Column count does not match the header.'
            if any(value.lstrip().startswith(('=', '+', '-', '@')) for value in values):
                issue = 'Formula-like cells are not supported.'
            item = dict(zip(mapping, values))
            item.setdefault('channel', 'CSV')
            if not issue:
                try:
                    item = normalize_row(item)
                except ImportError as exc:
                    issue = str(exc)
            rows.append((number, item if not issue else {}, issue))
        if not rows:
            raise ImportError('The CSV has no tickets.')
        return 'CSV', rows
    except (UnicodeError, csv.Error, StopIteration):
        raise ImportError('Use a valid UTF-8 CSV with a header row.') from None


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('p', 'br', 'div', 'li') and not self.hidden:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def email_ticket(raw):
    if not 0 < len(raw) <= MAX_UPLOAD:
        raise ImportError('Email exceeds the 2 MB limit.')
    try:
        message = BytesParser(policy=policy.default).parsebytes(raw)
        part = message.get_body(preferencelist=('plain', 'html'))
        if part is None:
            raise ImportError('Email has no readable message body.')
        body = part.get_content()
        if not isinstance(body, str):
            raise ImportError('Email body must be text.')
        if part.get_content_type() == 'text/html':
            html = PlainHTML(); html.feed(body); body = ''.join(html.parts).strip()
        name, address = parseaddr(str(message.get('From', '')))
        item = {'subject': str(message.get('Subject', '')), 'message': body, 'customer': name or address or 'Email customer',
                'company': 'Email inbox', 'channel': 'Email', 'source': 'email'}
        identity = str(message.get('Message-ID', '')).strip()
        if identity:
            item['source_id'] = identity
        return normalize_row(item)
    except ImportError:
        raise
    except (ValueError, UnicodeError, KeyError, TypeError, LookupError, RecursionError):
        raise ImportError('Invalid email message.') from None


def parse_eml(raw):
    return 'Email', [(1, email_ticket(raw), '')]


def zendesk_rows(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('tickets'), list):
        raise ImportError('Zendesk returned an invalid ticket list.')
    if not payload['tickets']:
        return []
    items = []
    for ticket in payload['tickets'][:MAX_ROWS]:
        if not isinstance(ticket, dict):
            items.append({}); continue
        identity = ticket.get('id')
        if type(identity) is not int or identity < 1:
            items.append({}); continue
        via = ticket.get('via') if isinstance(ticket.get('via'), dict) else {}
        requester = ticket.get('requester_id')
        customer = f'Requester {requester}' if type(requester) is int else 'Zendesk requester'
        items.append({'subject': ticket.get('subject', ''), 'message': ticket.get('description', ''), 'customer': customer,
                      'company': 'Zendesk', 'channel': str(via.get('channel') or 'Zendesk'),
                      'source': 'zendesk', 'source_id': str(identity)})
    return validated_rows(items)


def api_rows(payload):
    items = payload.get('tickets') if isinstance(payload, dict) else payload
    if not isinstance(items, list) or len(items) > MAX_ROWS:
        raise ImportError('API must return up to 100 tickets as an array or a tickets field.')
    if not items:
        return []
    rows = []
    for item in items:
        if not isinstance(item, dict):
            rows.append({}); continue
        row = {key: item[key] for key in ('subject', 'message', 'customer', 'company', 'channel') if key in item}
        row.setdefault('channel', 'API')
        row['source'] = 'api'
        if isinstance(item.get('id'), (str, int)) and not isinstance(item.get('id'), bool):
            row['source_id'] = str(item['id'])
        rows.append(row)
    return validated_rows(rows)
