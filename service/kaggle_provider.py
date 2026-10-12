"""Workspace-owned Kaggle API credentials; no ambient account discovery or shell."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from .errors import ServiceError


def configuration(body):
    owner, token = body.get('username'), body.get('api_token')
    if not isinstance(owner, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{2,29}', owner):
        raise ServiceError('Use your lowercase Kaggle username.')
    if not isinstance(token, str) or not 16 <= len(token) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ServiceError('Provide your Kaggle API token.')
    return {'username': owner, 'api_token': token}


class KaggleProvider:
    def available(self):
        return importlib.util.find_spec('kaggle') is not None

    def call(self, credentials, action, *, path='', reference='', timeout=120):
        if not self.available():
            raise ServiceError('Ask your operator to install the Kaggle connector.', 503, 'kaggle_dependency_missing')
        with tempfile.TemporaryDirectory(prefix='laya-kaggle-auth-') as isolated:
            # Explicit token wins; the empty config directory prevents fallback to host accounts.
            environment = {key: value for key, value in os.environ.items() if key.upper() in
                           {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}}
            environment.update(KAGGLE_API_TOKEN=credentials['api_token'], KAGGLE_USERNAME=credentials['username'],
                               KAGGLE_CONFIG_DIR=isolated, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
            try:
                result = subprocess.run([sys.executable, '-m', 'service.kaggle_bridge', action, str(path), reference],
                                        cwd=Path(__file__).resolve().parents[1], env=environment,
                                        capture_output=True, timeout=timeout, check=False)
            except subprocess.TimeoutExpired:
                raise ServiceError('Kaggle timed out. A submitted job may still be running.', 502, 'kaggle_timeout') from None
            if result.returncode or len(result.stdout) > 16384:
                raise ServiceError('Kaggle request failed. Check account access, GPU quota or connectivity.', 502, 'kaggle_request_failed')
            try:
                value = json.loads(result.stdout)
                if not isinstance(value, dict) or set(value) - {'ok', 'status'}:
                    raise ValueError('shape')
                return value
            except (ValueError, UnicodeError):
                raise ServiceError('Kaggle returned an unexpected response.', 502, 'kaggle_invalid_response') from None
