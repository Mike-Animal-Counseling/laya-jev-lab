"""Dependency-free client for an explicitly configured self-hosted service."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from uuid import UUID

from .engine import validate_input
from .errors import EngineError


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ServiceClient:
    def __init__(self, base_url, api_key, *, timeout=120):
        if not isinstance(base_url, str) or not isinstance(api_key, str):
            raise EngineError('invalid_config', 'Provide an explicit service URL and integration key')
        try:
            url = urlsplit(base_url)
            _ = url.port
        except ValueError:
            raise EngineError('invalid_config', 'Provide a valid service URL') from None
        if not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ('', '/') or url.scheme not in ('https', 'http') or (url.scheme == 'http' and url.hostname not in ('127.0.0.1', 'localhost', '::1')) or not 20 <= len(api_key) <= 200 or any(ord(c) < 33 for c in api_key) or type(timeout) not in (int, float) or not 1 <= timeout <= 180:
            raise EngineError('invalid_config', 'Use HTTPS (or HTTP localhost), a scoped integration key and a bounded timeout')
        self.url, self._key, self.timeout = base_url.rstrip('/'), api_key, timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    @staticmethod
    def _identity(identity):
        try:
            return str(UUID(identity))
        except (ValueError, TypeError, AttributeError):
            raise EngineError('invalid_input', 'Pass a UUID request_id and reuse it only for identical retries') from None

    def _request(self, path, body=None, identity=None):
        headers = {'Authorization': 'Bearer ' + self._key}
        raw = None
        if body is not None:
            headers.update({'Content-Type': 'application/json', 'Idempotency-Key': self._identity(identity)})
            try:
                raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            except (ValueError, TypeError):
                raise EngineError('invalid_input', 'Provide JSON-compatible ticket fields') from None
            if len(raw) > 2 * 1024 * 1024:
                raise EngineError('invalid_input', 'Request exceeds 2 MB')
        request = urllib.request.Request(self.url + path, data=raw, headers=headers, method='POST' if raw is not None else 'GET')
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                data = response.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('size')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError('shape')
            return value
        except urllib.error.HTTPError as exc:
            raise EngineError('service_error', 'Service request failed with HTTP ' + str(exc.code)) from None
        except (urllib.error.URLError, OSError, ValueError, UnicodeError):
            raise EngineError('service_unavailable', 'Service outcome may be uncertain. Check request status before retrying with the same request_id') from None

    def classify(self, message, *, subject='', engine='laya', request_id):
        state = validate_input(message, subject)
        if engine not in ('laya', 'jev'):
            raise EngineError('invalid_input', 'Choose laya or jev')
        return self._request('/v1/classify', {**state, 'engine': engine}, request_id)

    def compare(self, message, *, subject='', request_id):
        return self._request('/v1/compare', validate_input(message, subject), request_id)

    def import_tickets(self, tickets, *, request_id, update=False):
        if not isinstance(tickets, list) or not 1 <= len(tickets) <= 100 or type(update) is not bool:
            raise EngineError('invalid_input', 'Provide 1 to 100 tickets and an explicit update flag')
        return self._request('/v1/tickets', {'tickets': tickets, 'update': update}, request_id)

    def request_status(self, request_id):
        """Requires tickets:read scope; never automatically repeats a paid call."""
        return self._request('/v1/requests/' + self._identity(request_id))
