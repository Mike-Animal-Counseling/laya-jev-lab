"""Persisted incremental sync; ticket changes and cursor commit together."""
import json
import secrets
import threading
from uuid import NAMESPACE_URL, uuid5

from .errors import ServiceError
from .shared import zendesk_rows


class Scheduler:
    def __init__(self, store, zendesk, workspace):
        self.store, self.zendesk, self.workspace = store, zendesk, workspace
        self.stop_event = threading.Event()
        self.thread = None

    def status(self, workspace):
        with self.store.connect() as db:
            row = db.execute('SELECT enabled,interval,start_time,due,failures,result,lease_until FROM jobs WHERE workspace_id=?', (workspace,)).fetchone()
        if not row:
            raise ServiceError('Workspace not found.', 404)
        value = dict(row)
        value['enabled'] = bool(value['enabled'])
        value['running'] = value.pop('lease_until') > self.store.clock()
        value['last_run'] = json.loads(value.pop('result'))
        return value

    def configure(self, workspace, body):
        enabled, interval = body.get('enabled'), body.get('interval', 600)
        if type(enabled) is not bool or type(interval) is not int or not 60 <= interval <= 86400:
            raise ServiceError('Choose a sync interval from 60 seconds to one day.')
        if enabled and not self.store.settings(workspace).get('zendesk', {}).get('access_token'):
            raise ServiceError('Connect Zendesk before enabling synchronization.', 409)
        start = body.get('start_time')
        if start is not None and (type(start) is not int or not 0 <= start <= int(self.store.clock()) - 60):
            raise ServiceError('Start time must be at least one minute in the past.')
        with self.store.transaction() as db:
            row = db.execute('SELECT cursor FROM jobs WHERE workspace_id=?', (workspace,)).fetchone()
            if start is not None and row['cursor']:
                raise ServiceError('Start time cannot change after synchronization has begun.', 409)
            db.execute('UPDATE jobs SET enabled=?,interval=?,due=?,lease=NULL,lease_until=0 WHERE workspace_id=?', (int(enabled), interval, self.store.clock(), workspace))
            if start is not None:
                db.execute('UPDATE jobs SET start_time=? WHERE workspace_id=?', (start, workspace))
            self.store.audit(db, workspace, 'owner', 'sync_configured')
        return self.status(workspace)

    def claim(self, workspace=None, manual=False):
        clock = self.store.clock()
        with self.store.transaction() as db:
            if workspace:
                row = db.execute('SELECT * FROM jobs WHERE workspace_id=? AND lease_until<=?' + ('' if manual else ' AND enabled=1 AND due<=?'), (workspace, clock) if manual else (workspace, clock, clock)).fetchone()
            else:
                row = db.execute('SELECT * FROM jobs WHERE enabled=1 AND due<=? AND lease_until<=? ORDER BY due LIMIT 1', (clock, clock)).fetchone()
            if not row:
                return None
            lease = secrets.token_urlsafe(24)
            db.execute('UPDATE jobs SET lease=?,lease_until=? WHERE workspace_id=?', (lease, clock + 180, row['workspace_id']))
            return {**dict(row), 'lease': lease}

    def run(self, job):
        workspace = job['workspace_id']
        try:
            payload = self.zendesk.export(workspace, job['cursor'], job['start_time'])
            rows = zendesk_rows(payload)
            if any(issue for _, _, issue in rows):
                raise ServiceError('Source tickets need valid subjects and bounded descriptions. Cursor was retained.', 422, 'invalid_source_tickets')
            domain = self.store.settings(workspace)['zendesk']['subdomain']
            mapped = []
            for _, row, _ in rows:
                row['source_id'] = domain + ':' + row['source_id']
                mapped.append(row)
            identity = str(uuid5(NAMESPACE_URL, workspace + ':' + (job['cursor'] or str(job['start_time']))))
            with self.store.transaction() as db:
                current = db.execute('SELECT lease,enabled FROM jobs WHERE workspace_id=?', (workspace,)).fetchone()
                if not current or current['lease'] != job['lease'] or current['enabled'] != job['enabled']:
                    raise ServiceError('Synchronization settings changed. Page was not committed.', 409, 'sync_cancelled')
                result = self.workspace(workspace).import_rows(mapped, identity, 'sync', update=True, db=db) if mapped else {'imported': 0, 'updated': 0, 'skipped': 0}
                result = {k: result[k] for k in ('imported', 'updated', 'skipped')}
                result.update(at=self.store.clock(), status='success', caught_up=payload['end_of_stream'])
                # Never follow provider after_url; next request rebuilds the fixed endpoint.
                delay = job['interval'] if payload['end_of_stream'] else 60
                db.execute('UPDATE jobs SET cursor=?,due=?,lease=NULL,lease_until=0,failures=0,result=? WHERE workspace_id=? AND lease=?', (payload['after_cursor'], self.store.clock() + delay, json.dumps(result), workspace, job['lease']))
            return result
        except ServiceError as exc:
            self.failure(job, exc.code, getattr(exc, 'retry_after', 0))
            raise
        except Exception:
            self.failure(job, 'sync_failed')
            raise ServiceError('Synchronization failed. Cursor was retained.', 502, 'sync_failed') from None

    def failure(self, job, code, retry_after=0):
        failures = job['failures'] + 1
        delay = max(retry_after, min(3600, 60 * 2 ** min(failures - 1, 6)))
        result = {'at': self.store.clock(), 'status': 'error', 'code': code}
        with self.store.transaction() as db:
            db.execute('UPDATE jobs SET lease=NULL,lease_until=0,failures=?,due=?,result=? WHERE workspace_id=? AND lease=?', (failures, self.store.clock() + delay, json.dumps(result), job['workspace_id'], job['lease']))

    def run_now(self, workspace):
        job = self.claim(workspace, manual=True)
        if not job:
            raise ServiceError('Synchronization is already running.', 409)
        return self.run(job)

    def _loop(self):
        while not self.stop_event.is_set():
            job = self.claim()
            if job:
                try:
                    self.run(job)
                except ServiceError:
                    pass  # Safe code is persisted; credentials and ticket text are never logged.
            else:
                self.stop_event.wait(5)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True, name='ticket-sync')
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=25)
