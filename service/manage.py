"""Operator-only initialization and backup; passwords are entered interactively."""
import argparse
import getpass
import os
from pathlib import Path
import secrets

from cryptography.fernet import Fernet
from .errors import ServiceError
from .store import Store, password_hash


def main():
    parser = argparse.ArgumentParser(description='Manage a self-hosted workspace. Never publish runtime storage or keys.')
    parser.add_argument('--data-dir', default=os.environ.get('SERVICE_DATA_DIR', 'var/cloud'))
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init')
    init.add_argument('--workspace', required=True)
    init.add_argument('--owner', default='admin')
    init.add_argument('--name')
    backup = sub.add_parser('backup')
    backup.add_argument('destination')
    reset = sub.add_parser('reset-password')
    reset.add_argument('--workspace', required=True)
    reset.add_argument('--username', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    directory = Path(args.data_dir)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Path(os.environ.get('SERVICE_KEY_FILE', str(directory / 'master.key')))
    try:
        if args.action == 'init' and not key.exists():
            key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(key, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(Fernet.generate_key())
        store = Store(directory, key)
        if args.action == 'backup':
            store.backup(args.destination)
            print('Backup created. Keep the encryption key separately and protect both.')
            return 0
        password = getpass.getpass('Password (12+ characters): ')
        confirm = getpass.getpass('Repeat password: ')
        if not secrets.compare_digest(password, confirm):
            raise ServiceError('Passwords do not match.')
        if args.action == 'init':
            store.create_workspace(args.workspace, args.owner, password, args.name)
            print('Workspace created. Start the service and sign in with the chosen workspace and username.')
        else:
            hashed = password_hash(password)
            with store.transaction() as db:
                user = db.execute('SELECT u.id FROM users u JOIN workspaces w ON w.id=u.workspace_id WHERE w.slug=? AND u.username=?', (args.workspace, args.username)).fetchone()
                if not user:
                    raise ServiceError('User not found.', 404)
                db.execute('UPDATE users SET password=? WHERE id=?', (hashed, user['id']))
                db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
            print('Password reset and existing sessions revoked.')
        return 0
    except (ServiceError, OSError) as exc:
        print(str(exc) if isinstance(exc, ServiceError) else 'Storage could not be accessed safely.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
