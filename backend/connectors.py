"""Explicit, read-only source pulls. Only this workspace's configuration is read."""
import base64
import http.client
import hashlib
import imaplib
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
from urllib.parse import urlsplit

from intake_sources import api_rows, email_ticket, zendesk_rows
from ticket_import import ImportError, MAX_UPLOAD, normalize_row

ROOT = Path(__file__).resolve().parents[1]
KEYS = ('ZENDESK_SUBDOMAIN', 'ZENDESK_OAUTH_TOKEN', 'ZENDESK_EMAIL', 'ZENDESK_API_TOKEN',
        'TICKET_API_URL', 'TICKET_API_TOKEN', 'MAIL_IMAP_HOST', 'MAIL_IMAP_USER', 'MAIL_IMAP_PASSWORD', 'MAIL_IMAP_FOLDER')


def config():
    values = {key: '' for key in KEYS}
    path = ROOT / '.env.local'
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            key, sep, value = line.strip().partition('=')
            if sep and key in values:
                values[key] = value.strip().strip('"\'')
    return values


def connection_status():
    values = config()
    return {'zendesk': bool(values['ZENDESK_SUBDOMAIN'] and (values['ZENDESK_OAUTH_TOKEN'] or (values['ZENDESK_EMAIL'] and values['ZENDESK_API_TOKEN']))),
            'api': bool(values['TICKET_API_URL']), 'email': all(values[k] for k in ('MAIL_IMAP_HOST', 'MAIL_IMAP_USER', 'MAIL_IMAP_PASSWORD'))}


def public_socket(host, port, timeout=15):
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?', host):
        raise ImportError('Invalid connection host.')
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ImportError('Connections to local or private networks are not supported.')
    # Pin the checked address for this connection; do not resolve again after validation.
    return socket.create_connection((addresses[0][4][0], port), timeout=timeout)


class PublicHTTPS(http.client.HTTPSConnection):
    def connect(self):
        raw = public_socket(self.host, self.port, self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close(); raise


class PublicIMAP(imaplib.IMAP4_SSL):
    def _create_socket(self, timeout):
        raw = public_socket(self.host, self.port, timeout or 15)
        try:
            return self.ssl_context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close(); raise


def json_get(url, authorization=''):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment:
        raise ImportError('Configure a public HTTPS API URL without embedded credentials.')
    if len(authorization) > 4096 or any(ord(c) < 32 for c in authorization):
        raise ImportError('Invalid API credential configuration.')
    connection = PublicHTTPS(parsed.hostname, timeout=15, context=ssl.create_default_context())
    try:
        headers = {'Accept': 'application/json'}
        if authorization:
            headers['Authorization'] = authorization
        connection.request('GET', (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''), headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            raise ImportError(f'Source returned HTTP {response.status}. Check the connection settings.')
        raw = response.read(MAX_UPLOAD + 1)
        if len(raw) > MAX_UPLOAD:
            raise ImportError('Source response exceeds 2 MB.')
        return json.loads(raw)
    except ImportError:
        raise
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        raise ImportError('Could not read the source. Check its connection settings.') from None
    finally:
        connection.close()


def pull_api(source):
    values = config()
    if source == 'zendesk':
        domain = values['ZENDESK_SUBDOMAIN']
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', domain):
            raise ImportError('Configure the Zendesk subdomain first.')
        if values['ZENDESK_OAUTH_TOKEN']:
            auth = 'Bearer ' + values['ZENDESK_OAUTH_TOKEN']
        elif values['ZENDESK_EMAIL'] and values['ZENDESK_API_TOKEN']:
            auth = 'Basic ' + base64.b64encode((values['ZENDESK_EMAIL'] + '/token:' + values['ZENDESK_API_TOKEN']).encode()).decode()
        else:
            raise ImportError('Configure Zendesk credentials first.')
        rows = zendesk_rows(json_get(f'https://{domain}.zendesk.com/api/v2/tickets.json?per_page=100&sort_by=updated_at&sort_order=desc', auth))
        for _, row, issue in rows:
            if not issue:
                row['source_id'] = domain + ':' + row['source_id']
        return 'Zendesk', rows
    if source == 'api':
        if not values['TICKET_API_URL']:
            raise ImportError('Configure the REST API connection first.')
        auth = 'Bearer ' + values['TICKET_API_TOKEN'] if values['TICKET_API_TOKEN'] else ''
        rows = api_rows(json_get(values['TICKET_API_URL'], auth))
        namespace = hashlib.sha256(values['TICKET_API_URL'].encode()).hexdigest()[:20]
        scoped = []
        for number, row, issue in rows:
            if not issue and row.get('source_id'):
                row['source_id'] = namespace + ':' + row['source_id']
                try:
                    row = normalize_row(row)
                except ImportError as exc:
                    row, issue = {}, str(exc)
            scoped.append((number, row, issue))
        return 'API', scoped
    raise ImportError('Unsupported API source.')


def pull_mail():
    values = config()
    if not all(values[k] for k in ('MAIL_IMAP_HOST', 'MAIL_IMAP_USER', 'MAIL_IMAP_PASSWORD')):
        raise ImportError('Configure the IMAP mailbox first.')
    client = None
    try:
        client = PublicIMAP(values['MAIL_IMAP_HOST'], port=993, ssl_context=ssl.create_default_context(), timeout=15)
        client.login(values['MAIL_IMAP_USER'], values['MAIL_IMAP_PASSWORD'])
        folder = values['MAIL_IMAP_FOLDER'] or 'INBOX'
        if len(folder) > 100 or any(ord(c) < 32 for c in folder):
            raise ImportError('Invalid mailbox folder.')
        if client.select(folder, readonly=True)[0] != 'OK':
            raise ImportError('Could not open the mailbox folder.')
        status, data = client.uid('search', None, 'ALL')
        if status != 'OK':
            raise ImportError('Could not list mailbox messages.')
        identities = data[0].split()[-20:]
        rows = []
        for number, identity in enumerate(reversed(identities), 1):
            status, parts = client.uid('fetch', identity, f'(BODY.PEEK[]<0.{MAX_UPLOAD + 1}>)')
            raw = next((part[1] for part in parts if isinstance(part, tuple) and isinstance(part[1], bytes)), b'')
            try:
                if status != 'OK':
                    raise ImportError('Could not read this email.')
                ticket = email_ticket(raw)
                if not ticket.get('source_id'):
                    raise ImportError('Email needs a Message-ID to sync safely.')
                rows.append((number, ticket, ''))
            except ImportError as exc:
                rows.append((number, {}, str(exc)))
        return 'Mailbox', rows
    except ImportError:
        raise
    except (OSError, imaplib.IMAP4.error, ValueError):
        raise ImportError('Could not read the mailbox. Check its connection settings.') from None
    finally:
        if client:
            try:
                client.logout()
            except (OSError, imaplib.IMAP4.error):
                pass
