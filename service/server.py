"""One service replica with bounded workers and a persisted synchronization loop."""
import os
from pathlib import Path

from .app import Application
from .engines import Engines
from .errors import ServiceError
from .store import Store


def main():
    os.umask(0o077)
    root = Path(__file__).resolve().parents[1]
    try:
        store = Store(os.environ.get('SERVICE_DATA_DIR', str(root / 'var/cloud')), os.environ.get('SERVICE_KEY_FILE'))
        application = Application(store, Engines(store, os.environ.get('SERVICE_MODEL_PATH', str(root / 'models/ticket-finetuned-v5'))), os.environ.get('SERVICE_PUBLIC_URL', 'http://127.0.0.1:5180'))
        application.scheduler.start()
        application.training.start()
        from waitress import serve
        print('Workspace service ready. Connection credentials and ticket text are not logged.', flush=True)
        try:
            serve(application, host=os.environ.get('SERVICE_BIND', '127.0.0.1'), port=int(os.environ.get('SERVICE_PORT', '8780')), threads=8, max_request_body_size=2 * 1024 * 1024, channel_timeout=180, ident='ticket-service')
        finally:
            application.scheduler.stop()
            application.training.stop()
        return 0
    except (ServiceError, ValueError):
        print('Service configuration is invalid or not initialized. See docs/DEPLOYMENT.md.', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
