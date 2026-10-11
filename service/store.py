"""Workspace-scoped SQLite storage and authenticated credential encryption."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken
from .errors import ServiceError

SCOPES = {'tickets:read', 'tickets:write', 'classify'}
ROLES = {'owner', 'member', 'viewer'}


class Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


def token_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ServiceError('Use a password of 12 to 128 characters.')
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024)
    return salt + ':' + derived.hex()


def password_matches(password, stored):
    try:
        salt, _ = stored.split(':', 1)
        return secrets.compare_digest(password_hash(password, salt), stored)
    except (ValueError, TypeError, ServiceError):
        return False


def username(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{1,31}', value):
        raise ServiceError('Use a lowercase username of 2 to 32 characters.')
    return value


class Store:
    def __init__(self, directory, key_file=None, *, clock=time.time):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / 'service.sqlite3'
        self.clock = clock
        key_path = Path(key_file) if key_file else self.directory / 'master.key'
        try:
            self.fernet = Fernet(key_path.read_bytes().strip())
        except (OSError, ValueError):
            raise ServiceError('Initialize the service encryption key before starting.', 503, 'not_initialized') from None
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL DEFAULT '[]', revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), username TEXT NOT NULL, role TEXT NOT NULL, password TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, UNIQUE(workspace_id,username));
                CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS invites (hash TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), username TEXT NOT NULL, role TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS api_keys (hash TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), name TEXT NOT NULL, scopes TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id), ciphertext BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS oauth_states (hash TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), user_id TEXT NOT NULL REFERENCES users(id), session_hash TEXT NOT NULL, ciphertext BLOB NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id), enabled INTEGER NOT NULL DEFAULT 0, interval INTEGER NOT NULL DEFAULT 600, start_time INTEGER NOT NULL, cursor TEXT, due REAL NOT NULL DEFAULT 0, lease TEXT, lease_until REAL NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, result TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE IF NOT EXISTS requests (workspace_id TEXT NOT NULL REFERENCES workspaces(id), request_id TEXT NOT NULL, kind TEXT NOT NULL, input_hash TEXT NOT NULL, status TEXT NOT NULL, result TEXT, created REAL NOT NULL, PRIMARY KEY(workspace_id,request_id));
                CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), actor TEXT NOT NULL, action TEXT NOT NULL, object_id TEXT, at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS audit_workspace ON audit(workspace_id,id);
                CREATE TABLE IF NOT EXISTS ticket_sequences (workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id), value INTEGER NOT NULL);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10, factory=Connection)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        return db

    @contextmanager
    def transaction(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def encrypt(self, workspace, value):
        return self.fernet.encrypt(json.dumps({'workspace': workspace, 'value': value}, separators=(',', ':')).encode())

    def decrypt(self, workspace, cipher):
        try:
            value = json.loads(self.fernet.decrypt(cipher))
            if value['workspace'] != workspace:
                raise ValueError('scope')
            return value['value']
        except (InvalidToken, ValueError, KeyError, TypeError):
            raise ServiceError('Stored connection configuration could not be decrypted.', 503, 'invalid_configuration') from None

    def create_workspace(self, slug, owner, password, name=None):
        username(slug); username(owner)
        hashed = password_hash(password)
        workspace, user = uuid4().hex, uuid4().hex
        try:
            with self.transaction() as db:
                db.execute('INSERT INTO workspaces(id,slug,name) VALUES(?,?,?)', (workspace, slug, name or slug))
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,1)', (user, workspace, owner, 'owner', hashed))
                db.execute('INSERT INTO jobs(workspace_id,start_time) VALUES(?,?)', (workspace, int(self.clock()) - 3600))
        except sqlite3.IntegrityError:
            raise ServiceError('That workspace already exists.', 409) from None
        return workspace

    def login(self, slug, login, password):
        with self.connect() as db:
            row = db.execute('SELECT u.*,w.slug,w.name FROM users u JOIN workspaces w ON w.id=u.workspace_id WHERE w.slug=? AND u.username=? AND u.enabled=1', (slug, login)).fetchone()
        # Spend the same KDF work for nonexistent users, preventing cheap enumeration.
        stored = row['password'] if row else '00' * 16 + ':' + '00' * 64
        if not password_matches(password, stored) or not row:
            raise ServiceError('Invalid workspace, username or password.', 401, 'invalid_credentials')
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.transaction() as db:
            if db.execute('SELECT COUNT(*) FROM sessions WHERE user_id=?', (row['id'],)).fetchone()[0] >= 20:
                db.execute('DELETE FROM sessions WHERE hash IN (SELECT hash FROM sessions WHERE user_id=? ORDER BY expires LIMIT 1)', (row['id'],))
            db.execute('DELETE FROM sessions WHERE expires<=?', (self.clock(),))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (token_hash(token), row['id'], csrf, self.clock() + 28800))
        return token, csrf

    def session(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            return None
        with self.connect() as db:
            row = db.execute('SELECT u.id,u.workspace_id,u.username,u.role,w.slug,w.name,s.csrf,s.hash FROM sessions s JOIN users u ON s.user_id=u.id JOIN workspaces w ON w.id=u.workspace_id WHERE s.hash=? AND s.expires>? AND u.enabled=1', (token_hash(token), self.clock())).fetchone()
        return dict(row) if row else None

    def logout(self, token):
        self.logout_hash(token_hash(token))

    def logout_hash(self, identity):
        with self.transaction() as db:
            db.execute('DELETE FROM sessions WHERE hash=?', (identity,))

    def members(self, workspace):
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,username,role,enabled FROM users WHERE workspace_id=? ORDER BY username', (workspace,))]

    def invite(self, workspace, login, role):
        username(login)
        if role not in {'member', 'viewer'}:
            raise ServiceError('Choose member or viewer.')
        token = secrets.token_urlsafe(32)
        with self.transaction() as db:
            if db.execute('SELECT 1 FROM users WHERE workspace_id=? AND username=?', (workspace, login)).fetchone():
                raise ServiceError('That username already exists.', 409)
            db.execute('DELETE FROM invites WHERE expires<=? OR (workspace_id=? AND username=?)', (self.clock(), workspace, login))
            if db.execute('SELECT COUNT(*) FROM users WHERE workspace_id=?', (workspace,)).fetchone()[0] + db.execute('SELECT COUNT(*) FROM invites WHERE workspace_id=?', (workspace,)).fetchone()[0] >= 100:
                raise ServiceError('Workspace member capacity reached.', 409)
            db.execute('INSERT INTO invites VALUES(?,?,?,?,?)', (token_hash(token), workspace, login, role, self.clock() + 86400))
        return token

    def join(self, token, password):
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            raise ServiceError('Invalid or expired invitation.', 400)
        hashed = password_hash(password)
        with self.transaction() as db:
            row = db.execute('SELECT * FROM invites WHERE hash=? AND expires>?', (token_hash(token), self.clock())).fetchone()
            if not row:
                raise ServiceError('Invalid or expired invitation.', 400)
            try:
                db.execute('INSERT INTO users VALUES(?,?,?,?,?,1)', (uuid4().hex, row['workspace_id'], row['username'], row['role'], hashed))
            except sqlite3.IntegrityError:
                raise ServiceError('Invitation already used.', 409) from None
            db.execute('DELETE FROM invites WHERE hash=?', (row['hash'],))
            slug = db.execute('SELECT slug FROM workspaces WHERE id=?', (row['workspace_id'],)).fetchone()[0]
        return {'workspace': slug, 'username': row['username']}

    def disable_member(self, workspace, user_id):
        with self.transaction() as db:
            row = db.execute('SELECT role FROM users WHERE workspace_id=? AND id=?', (workspace, user_id)).fetchone()
            if not row:
                raise ServiceError('Member not found.', 404)
            if row['role'] == 'owner':
                raise ServiceError('An owner cannot be disabled here.', 409)
            db.execute('UPDATE users SET enabled=0 WHERE workspace_id=? AND id=?', (workspace, user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))

    def create_api_key(self, workspace, name, scopes, days=90):
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) for s in scopes) or set(scopes) - SCOPES or type(days) is not int or not 1 <= days <= 365:
            raise ServiceError('Provide a name, supported scopes and an expiry of 1 to 365 days.')
        token = secrets.token_urlsafe(32)
        with self.transaction() as db:
            db.execute('DELETE FROM api_keys WHERE expires<=?', (self.clock(),))
            if db.execute('SELECT COUNT(*) FROM api_keys WHERE workspace_id=?', (workspace,)).fetchone()[0] >= 100:
                raise ServiceError('Workspace integration key capacity reached.', 409)
            db.execute('INSERT INTO api_keys VALUES(?,?,?,?,?)', (token_hash(token), workspace, name.strip(), json.dumps(sorted(set(scopes))), self.clock() + days * 86400))
        return token

    def api_key(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 200:
            return None
        with self.connect() as db:
            row = db.execute('SELECT * FROM api_keys WHERE hash=? AND expires>?', (token_hash(token), self.clock())).fetchone()
        if not row:
            return None
        return {'workspace_id': row['workspace_id'], 'id': row['hash'], 'username': 'integration', 'role': 'api', 'scopes': json.loads(row['scopes'])}

    def api_keys(self, workspace):
        with self.connect() as db:
            return [{**dict(r), 'scopes': json.loads(r['scopes'])} for r in db.execute('SELECT hash AS id,name,scopes,expires FROM api_keys WHERE workspace_id=?', (workspace,))]

    def revoke_api_key(self, workspace, key_id):
        with self.transaction() as db:
            db.execute('DELETE FROM api_keys WHERE workspace_id=? AND hash=?', (workspace, key_id))

    def settings(self, workspace, db=None):
        if db is None:
            with self.connect() as connection:
                return self.settings(workspace, connection)
        row = db.execute('SELECT ciphertext FROM settings WHERE workspace_id=?', (workspace,)).fetchone()
        return self.decrypt(workspace, row[0]) if row else {}

    def save_settings(self, workspace, settings, db=None):
        if db is None:
            with self.transaction() as connection:
                return self.save_settings(workspace, settings, connection)
        db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(workspace_id) DO UPDATE SET ciphertext=excluded.ciphertext', (workspace, self.encrypt(workspace, settings)))

    def audit(self, db, workspace, actor, action, object_id=None):
        db.execute('INSERT INTO audit(workspace_id,actor,action,object_id,at) VALUES(?,?,?,?,?)', (workspace, actor, action, object_id, self.clock()))
        db.execute('DELETE FROM audit WHERE workspace_id=? AND id NOT IN (SELECT id FROM audit WHERE workspace_id=? ORDER BY id DESC LIMIT 5000)', (workspace, workspace))

    def prune_requests(self, db, workspace):
        db.execute("DELETE FROM requests WHERE workspace_id=? AND status!='pending' AND created<?", (workspace, self.clock() - 7 * 86400))
        if db.execute('SELECT COUNT(*) FROM requests WHERE workspace_id=?', (workspace,)).fetchone()[0] >= 10000:
            raise ServiceError('Request history capacity reached. Contact your operator.', 429, 'request_capacity')

    def state(self, workspace, db=None):
        if db is None:
            with self.connect() as connection:
                return self.state(workspace, connection)
        row = db.execute('SELECT state FROM workspaces WHERE id=?', (workspace,)).fetchone()
        if not row:
            raise ServiceError('Workspace not found.', 404)
        return json.loads(row[0])

    def save_state(self, db, workspace, items, actor, action, object_id=None):
        changed = db.execute('UPDATE workspaces SET state=?,revision=revision+1 WHERE id=?', (json.dumps(items, ensure_ascii=False, allow_nan=False), workspace)).rowcount
        if not changed:
            raise ServiceError('Workspace not found.', 404)
        self.audit(db, workspace, actor, action, object_id)

    def backup(self, destination):
        target = Path(destination)
        if target.exists():
            raise ServiceError('Backup destination already exists.', 409)
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        source, copy = self.connect(), sqlite3.connect(target)
        try:
            source.backup(copy)
        finally:
            source.close(); copy.close()
