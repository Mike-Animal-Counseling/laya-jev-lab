"""Unified source intake, safe connectors and identities."""
from io import BytesIO
import json
from pathlib import Path
import socket
import tempfile
from unittest.mock import patch, Mock
from uuid import uuid4
import unittest

import connectors
import server
from intake_sources import parse_csv, email_ticket, zendesk_rows, api_rows
from ticket_import import ImportError, row_key
from test_ab import ServiceCase


class SourceAdapters(unittest.TestCase):
    def test_csv_bom_quoted_multiline_and_header_aliases(self):
        _, rows = parse_csv('\ufeffTitle,Description,Customer\r\nDemo,"Line one\nLine two",Demo user\r\n'.encode())
        self.assertEqual(rows[0][1]['message'], 'Line one\nLine two')
        self.assertEqual(rows[0][1]['channel'], 'CSV')

    def test_csv_errors_and_formulas_are_not_silently_imported(self):
        _, rows = parse_csv(b'Subject,Message\n=1+1,Demo\nDemo,\n')
        self.assertTrue(all(row[2] for row in rows))
        with self.assertRaises(ImportError): parse_csv(b'Unknown,Message\na,b\n')
        with self.assertRaises(ImportError): parse_csv(b'\xff\xfe')

    def test_email_plain_text_and_html_are_normalized_without_attachments_or_scripts(self):
        plain = b'From: Demo user <demo@example.invalid>\r\nSubject: Demo request\r\nMessage-ID: <demo@example.invalid>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nSynthetic message'
        row = email_ticket(plain)
        self.assertEqual((row['customer'], row['channel'], row['source_id']), ('Demo user', 'Email', '<demo@example.invalid>'))
        html = plain.replace(b'text/plain', b'text/html').replace(b'Synthetic message', b'<p>Hello</p><script>danger()</script><p>Demo request</p>')
        self.assertNotIn('danger', email_ticket(html)['message'])
        self.assertNotIn('<p>', email_ticket(html)['message'])

    def test_zendesk_and_generic_rest_map_to_shared_schema_and_stable_identity(self):
        _, row, issue = zendesk_rows({'tickets': [{'id': 123, 'subject': 'Demo', 'description': 'Feedback', 'requester_id': 7, 'via': {'channel': 'email'}}]})[0]
        self.assertFalse(issue)
        self.assertEqual(row['customer'], 'Requester 7')
        self.assertEqual(row_key(row), row_key({**row, 'message': 'Changed by source'}))
        _, row, issue = api_rows({'tickets': [{'id': 'a1', 'subject': 'Demo', 'message': 'Demo body'}]})[0]
        self.assertEqual(row['source_id'], 'a1')
        self.assertEqual(row['channel'], 'API')

    def test_config_never_uses_parent_or_environment_and_status_never_exposes_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'project'; root.mkdir()
            (root.parent/'.env.local').write_text('ZENDESK_SUBDOMAIN=parent\nZENDESK_OAUTH_TOKEN=parent-secret')
            with patch.object(connectors, 'ROOT', root), patch.dict('os.environ', ZENDESK_OAUTH_TOKEN='environment-secret'):
                self.assertFalse(connectors.connection_status()['zendesk'])
                (root/'.env.local').write_text('ZENDESK_SUBDOMAIN=demo\nZENDESK_OAUTH_TOKEN=example-secret')
                self.assertTrue(connectors.connection_status()['zendesk'])
                self.assertNotIn('secret', json.dumps(connectors.connection_status()))

    def test_zendesk_request_stays_on_fixed_https_domain_and_uses_oauth(self):
        values = {key: '' for key in connectors.KEYS}; values.update(ZENDESK_SUBDOMAIN='demo', ZENDESK_OAUTH_TOKEN='example-token')
        with patch.object(connectors, 'config', return_value=values), patch.object(connectors, 'json_get', return_value={'tickets': []}) as get:
            self.assertEqual(connectors.pull_api('zendesk'), ('Zendesk', []))
            self.assertTrue(get.call_args[0][0].startswith('https://demo.zendesk.com/api/v2/tickets.json?'))
            self.assertEqual(get.call_args[0][1], 'Bearer example-token')
        values['ZENDESK_SUBDOMAIN'] = 'demo.zendesk.com/other'
        with patch.object(connectors, 'config', return_value=values), self.assertRaises(ImportError):
            connectors.pull_api('zendesk')

    def test_private_networks_and_credential_urls_are_rejected(self):
        with patch.object(socket, 'getaddrinfo', return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]), self.assertRaises(ImportError):
            connectors.public_socket('example.invalid', 443)
        credential_url = 'https://' + 'user:pass' + '@example.invalid'
        for url in ('http://example.invalid', credential_url, 'https://example.invalid:8780'):
            with self.subTest(url=url), self.assertRaises(ImportError): connectors.json_get(url)

    def test_generic_identity_is_scoped_and_still_validated_before_preview(self):
        values = {key: '' for key in connectors.KEYS}; values['TICKET_API_URL'] = 'https://example.invalid/tickets'
        payload = [{'id': 'demo-1', 'subject': 'Demo', 'message': 'Synthetic request'},
                   {'id': 'x' * 256, 'subject': 'Demo', 'message': 'Synthetic request'}]
        with patch.object(connectors, 'config', return_value=values), patch.object(connectors, 'json_get', return_value=payload):
            _, rows = connectors.pull_api('api')
        self.assertTrue(rows[0][1]['source_id'].endswith(':demo-1'))
        self.assertEqual(rows[1][1], {})
        self.assertTrue(rows[1][2])

    def test_mailbox_is_read_only_and_fetch_does_not_mark_messages_read(self):
        values = {key: '' for key in connectors.KEYS}; values.update(MAIL_IMAP_HOST='mail.example.invalid', MAIL_IMAP_USER='demo', MAIL_IMAP_PASSWORD='example-password')
        client = Mock(); client.select.return_value = ('OK', [b'1'])
        raw = b'Subject: Demo\r\nFrom: Demo user\r\nMessage-ID: <demo@example.invalid>\r\n\r\nSynthetic request'
        client.uid.side_effect = [('OK', [b'1']), ('OK', [(b'header', raw)])]
        with patch.object(connectors, 'config', return_value=values), patch.object(connectors, 'PublicIMAP', return_value=client):
            self.assertEqual(connectors.pull_mail()[1][0][1]['subject'], 'Demo')
        client.select.assert_called_once_with('INBOX', readonly=True)
        self.assertIn('BODY.PEEK', client.uid.call_args[0][2])
        client.logout.assert_called_once()


class UnifiedIntake(ServiceCase):
    def test_connector_preview_never_saves_or_invokes_models(self):
        rows = api_rows([{'id': 1, 'subject': 'Demo API', 'message': 'Synthetic request'}])
        with patch.object(server, 'pull_api', return_value=('Zendesk', rows)):
            result = self.call('intake/preview', {'source': 'zendesk'})
        self.assertEqual(result['ready'], 1)
        self.assertEqual(len(server.tickets), 8)
        self.local_mock.assert_not_called(); self.remote_mock.assert_not_called()

    def test_recorded_external_identity_is_not_duplicated_when_source_text_changes(self):
        body = {'rows': [{'subject': 'Demo', 'message': 'Feedback', 'source': 'zendesk', 'source_id': 'demo:1'}], 'request_id': str(uuid4())}
        self.call('import', body, 201)
        body['request_id'] = str(uuid4()); body['rows'][0]['message'] = 'Updated at source'
        self.assertEqual(self.call('import', body, 201)['imported'], 0)
        self.assertEqual(len(server.tickets), 9)
