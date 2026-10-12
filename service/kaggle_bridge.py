"""Isolated official SDK process. Never return SDK logs, credentials or ticket data."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


def download_result(api, path, reference):
    import requests
    from kagglesdk.kernels.types.kernels_api_service import ApiListKernelSessionOutputRequest
    from ticket_engine.adaptation import MAX_ADAPTER_BYTES
    owner, slug, _ = api.parse_kernel_string(reference)
    request = ApiListKernelSessionOutputRequest()
    request.user_name, request.kernel_slug, request.page_size = owner, slug, 20
    with api.build_kaggle_client() as client:
        response = client.kernels.kernels_api_client.list_kernel_session_output(request)
    files = [item for item in response.files or [] if item.file_name == 'result.zip']
    if len(files) != 1 or response.next_page_token:
        raise ValueError('Missing or ambiguous result file')
    url = urlsplit(files[0].url)
    if url.scheme != 'https' or not url.hostname or url.username or url.password:
        raise ValueError('Invalid result destination')
    # The CLI output helper downloads entire responses and always writes logs.
    # Stream only the model file with a hard bound; ignore all notebook logs.
    with requests.Session() as session:
        session.trust_env = False
        with session.get(files[0].url, stream=True, timeout=(20, 120), allow_redirects=False) as source:
            if source.status_code != 200 or int(source.headers.get('Content-Length', 0)) > MAX_ADAPTER_BYTES:
                raise ValueError('Invalid or oversized result response')
            destination = Path(path) / 'result.zip'
            total = 0
            try:
                with destination.open('wb') as output:
                    for chunk in source.iter_content(chunk_size=65536):
                        total += len(chunk)
                        if total > MAX_ADAPTER_BYTES:
                            raise ValueError('Oversized result response')
                        output.write(chunk)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise


def operation(action, path, reference):
    from kaggle import api
    actual = api.get_config_value('username')
    if actual and actual.casefold() != os.environ['KAGGLE_USERNAME'].casefold():
        raise ValueError('Account mismatch')
    if action == 'check':
        api.dataset_list(mine=True, page=1)
        return {'ok': True}
    if action == 'create':
        result = api.dataset_create_new(path, public=False, quiet=True, convert_to_csv=False)
        if getattr(result, 'error', None):
            raise ValueError('Dataset upload failed')
        return {'ok': True}
    if action == 'dataset':
        return {'status': str(api.dataset_status(reference)).lower().split('.')[-1]}
    if action == 'submit':
        result = api.kernels_push(path, timeout=14400, acc='NvidiaTeslaT4')
        if result is None or result.error:
            raise ValueError('Kernel submission failed')
        return {'ok': True}
    if action == 'status':
        result = api.kernels_status(reference)
        return {'status': str(result.status).lower().split('.')[-1]}
    if action == 'output':
        download_result(api, path, reference)
        return {'ok': True}
    raise ValueError('Unknown operation')


def main():
    try:
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            value = operation(*sys.argv[1:])
        print(json.dumps(value))
        return 0
    except Exception:
        print(json.dumps({'error': 'kaggle_request_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
