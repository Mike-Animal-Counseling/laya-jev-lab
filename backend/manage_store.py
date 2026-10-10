"""Local backup/restore utility. Restore requires the API service to be stopped."""
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain import migrate

DATA = Path(__file__).resolve().parents[1] / "var/tickets.json"
from storage import TicketStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('backup', help='Replace the latest manual SQLite backup')
    restore = commands.add_parser('restore', help='Validate and restore a SQLite backup while the API is stopped')
    restore.add_argument('source', type=Path)
    args = parser.parse_args()
    store = TicketStore(DATA)
    if args.command == 'backup':
        if not store.path.exists():
            parser.error('Start the upgraded service once to initialize the database.')
        print(store.backup('manual'))
        return
    try:
        with socket.create_connection(('127.0.0.1', 8780), timeout=.5):
            parser.error('Stop the API service on port 8780 before restoring.')
    except OSError:
        pass
    source = args.source.resolve(strict=True)
    if source == store.path.resolve():
        parser.error('Source must be a backup, not the current database.')
    connection = sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)
    try:
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            parser.error('Backup failed the SQLite integrity check.')
        row = connection.execute('SELECT payload FROM state WHERE id=1').fetchone()
        if row is None:
            parser.error('Backup contains no ticket state.')
        restored = migrate(json.loads(row[0]))
    finally:
        connection.close()
    if store.path.exists():
        store.backup('before-restore')
    store.save(restored, 'restore')
    print(f'Restored {len(restored)} tickets. Restart the API to load them.')


if __name__ == '__main__':
    main()
