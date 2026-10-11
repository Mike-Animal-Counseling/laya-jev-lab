"""Independent engine imports and safe HTTP/CLI integration boundaries."""
from io import BytesIO
import json
import subprocess
import sys
import unittest
from unittest.mock import Mock
from uuid import uuid4
from urllib.error import HTTPError

from ticket_engine import EngineError, ServiceClient


class AdapterContracts(unittest.TestCase):
    def test_jev_import_does_not_load_ml_or_web_dependencies(self):
        code = "import sys; from ticket_engine import JevEngine; e=JevEngine(api_key='synthetic-key'); assert not {'torch','transformers','cryptography','service','backend'} & set(sys.modules)"
        result = subprocess.run([sys.executable, '-c', code], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_cli_rejects_input_without_echoing_private_fields(self):
        result = subprocess.run([sys.executable, '-m', 'ticket_engine.cli', '--engine', 'jev'], input=b'{"message":"synthetic-private-body","extra":"synthetic-private-key"}', capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(result.stdout)
        self.assertNotIn(b'synthetic-private', result.stderr)
        self.assertEqual(json.loads(result.stderr)['error'], 'invalid_input')

    def test_client_uses_stable_key_and_never_retries_or_exposes_error_body(self):
        client = ServiceClient('https://tickets.example.com', 'synthetic-integration-key')
        client.opener = Mock()
        client.opener.open.side_effect = HTTPError(client.url, 502, 'failed', {}, BytesIO(b'synthetic-private-response'))
        identity = str(uuid4())
        with self.assertRaises(EngineError) as raised:
            client.classify('synthetic ticket', request_id=identity)
        self.assertNotIn('synthetic-private', str(raised.exception))
        client.opener.open.assert_called_once()
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.get_header('Idempotency-key'), identity)

    def test_request_status_never_sends_ticket_text(self):
        client = ServiceClient('http://127.0.0.1:5180', 'synthetic-integration-key')
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"status":"complete"}'
        client.opener = Mock()
        client.opener.open.return_value = response
        identity = str(uuid4())
        self.assertEqual(client.request_status(identity)['status'], 'complete')
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.method, 'GET')
        self.assertIsNone(request.data)

    def test_remote_plain_http_and_bad_ids_fail_before_transport(self):
        with self.assertRaises(EngineError):
            ServiceClient('http://tickets.example.com', 'synthetic-integration-key')
        client = ServiceClient('https://tickets.example.com', 'synthetic-integration-key')
        client.opener = Mock()
        with self.assertRaises(EngineError):
            client.classify('synthetic ticket', request_id='not-a-uuid')
        client.opener.open.assert_not_called()
