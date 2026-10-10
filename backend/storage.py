"""Transactional local persistence; legacy JSON is retained as a migration backup."""
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


class TicketStore:
    def __init__(self, legacy_path):
        self.legacy_path = Path(legacy_path)
        self.path = self.legacy_path.with_suffix('.sqlite3')

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('PRAGMA busy_timeout=5000')
        connection.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, event TEXT NOT NULL, ticket_id TEXT, provider TEXT)')
        connection.commit()
        return connection

    def load(self):
        if self.path.exists():
            db = self.connect()
            try:
                row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            finally:
                db.close()
            if row is None:
                raise ValueError('Database has no ticket state; restore a verified backup.')
            return json.loads(row[0])
        if self.legacy_path.exists():
            return json.loads(self.legacy_path.read_text(encoding='utf-8'))
        return None

    def save(self, tickets, event='save', ticket_id=None, provider=None):
        payload = json.dumps(tickets, ensure_ascii=False, allow_nan=False)
        db = self.connect()
        try:
            with db:
                db.execute('INSERT INTO state VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (payload,))
                db.execute('INSERT INTO audit (at,event,ticket_id,provider) VALUES (?,?,?,?)',
                           (datetime.now(timezone.utc).isoformat(), event, ticket_id, provider))
                # Bounded metadata log; no customer text or credentials in audit rows.
                db.execute('DELETE FROM audit WHERE id <= (SELECT COALESCE(MAX(id),0)-5000 FROM audit)')
        finally:
            db.close()

    def backup(self, label='before-reset'):
        """Use SQLite's backup API; copying a live database file is unsafe."""
        if label not in ('before-reset', 'before-restore', 'manual'):
            raise ValueError('Invalid backup label')
        target = self.path.with_suffix(f'.{label}.sqlite3')
        source = self.connect()
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        return target
