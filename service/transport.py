"""Bounded public-only HTTPS; no redirects, implicit proxy or error-body echo."""
import http.client
import json
import ssl
from urllib.parse import urlsplit

from .errors import ServiceError


def request(url, *, method='GET', token='', body=None):
    # Shared adapter is imported only by the optional repository service.
    from connectors import PublicHTTPS
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.port not in (None, 443) or parsed.username or parsed.password or parsed.fragment:
        raise ServiceError('Use a public HTTPS endpoint without embedded credentials.')
    if not isinstance(token, str) or len(token) > 4096 or any(ord(c) < 32 for c in token):
        raise ServiceError('Invalid source credential configuration.')
    connection = PublicHTTPS(parsed.hostname, timeout=20, context=ssl.create_default_context())
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        data = json.dumps(body, separators=(',', ':')).encode()
        headers['Content-Type'] = 'application/json'
    try:
        connection.request(method, (parsed.path or '/') + ('?' + parsed.query if parsed.query else ''), body=data, headers=headers)
        response = connection.getresponse()
        if response.status == 429:
            try:
                delay = max(60, min(3600, int(response.getheader('Retry-After', '60'))))
            except ValueError:
                delay = 60
            error = ServiceError('Source rate limited. Synchronization will retry later.', 429, 'source_rate_limited')
            error.retry_after = delay
            raise error
        if response.status not in (200, 201, 204):
            code = 'source_unauthorized' if response.status in (401, 403) else 'source_error'
            if response.status == 401:
                # Refresh only when the provider confirms an invalid token.
                # Other authorization failures need corrected permissions.
                raw = response.read(8193)
                if len(raw) <= 8192:
                    try:
                        payload = json.loads(raw)
                    except (ValueError, UnicodeError):
                        payload = None
                    if isinstance(payload, dict) and payload.get('error') == 'invalid_token':
                        code = 'source_invalid_token'
            raise ServiceError('Source request failed. Check connection permissions.', 502, code)
        if response.status == 204:
            return {}
        raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ServiceError('Source response exceeds 2 MB.', 502, 'source_error')
        result = json.loads(raw)
        if not isinstance(result, (dict, list)):
            raise ValueError('shape')
        return result
    except ServiceError:
        raise
    except (OSError, http.client.HTTPException, ValueError, UnicodeError):
        raise ServiceError('Could not reach the source securely.', 502, 'source_error') from None
    finally:
        connection.close()
