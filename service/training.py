"""Durable workspace-owned Kaggle jobs. Uncertain submissions are never replayed."""
from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
import stat
import threading
import zipfile

from ticket_engine.adaptation import MAX_ADAPTER_BYTES, verify_adapter
from ticket_engine.artifacts import EXPECTED
from ticket_engine.rules import QUESTIONS
from training.bundle import build
from training.data import DataError, encoded, parse_upload
from training.metrics import classification, recommendation
from .errors import ServiceError
from .kaggle_provider import KaggleProvider, configuration
from .workspace import request_id

ACTIVE = ('queued', 'working', 'running', 'uncertain', 'paused')


class Training:
    def __init__(self, store, engines, provider=None):
        self.store, self.engines = store, engines
        self.provider = provider or KaggleProvider()
        self.event, self.thread = threading.Event(), None
        self.lock = threading.Lock()
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS training_data (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), ciphertext BLOB NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS training_jobs (id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL REFERENCES workspaces(id), dataset_id TEXT NOT NULL REFERENCES training_data(id), status TEXT NOT NULL, phase TEXT NOT NULL, record TEXT NOT NULL, created REAL NOT NULL, due REAL NOT NULL, lease_until REAL NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS training_due ON training_jobs(status,due);
            ''')

    def folder(self, workspace, job):
        workspace, job = request_id(workspace), request_id(job)
        path = self.store.directory / 'training' / workspace / job
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in [path, *path.parents]):
            raise ServiceError('Linked training directories are not supported.', 503)
        return path

    def rows(self, workspace, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.rows(workspace, connection)
        return db.execute('SELECT * FROM training_jobs WHERE workspace_id=? ORDER BY created DESC', (workspace,)).fetchall()

    def public_job(self, row):
        record = json.loads(row['record'])
        return {'id': row['id'], 'status': row['status'], 'phase': row['phase'], 'created': row['created'],
                'summary': record['summary'], 'evaluation': record.get('evaluation'), 'error': record.get('error'),
                'kernel_url': 'https://www.kaggle.com/code/' + record['kernel_ref'],
                'dataset_url': 'https://www.kaggle.com/datasets/' + record['dataset_ref']}

    def status(self, workspace):
        connection = self.store.settings(workspace).get('kaggle', {})
        return {'connector_available': self.provider.available(), 'connected': bool(connection.get('api_token')),
                'username': connection.get('username', ''), 'active_model': self.store.settings(workspace).get('laya_adapter', {}).get('job_id'),
                'jobs': [self.public_job(row) for row in self.rows(workspace)]}

    def credentials(self, workspace):
        values = self.store.settings(workspace).get('kaggle')
        if not values:
            raise ServiceError('Connect your Kaggle account first.', 409, 'kaggle_not_configured')
        return values

    def connect(self, workspace, body, actor):
        values = configuration(body)
        if any(row['status'] in ACTIVE for row in self.rows(workspace)):
            raise ServiceError('Finish the current training job before changing Kaggle credentials.', 409)
        self.provider.call(values, 'check', timeout=20)
        with self.store.transaction() as db:
            if any(row['status'] in ACTIVE for row in self.rows(workspace, db)):
                raise ServiceError('Finish the current training job before changing Kaggle credentials.', 409)
            settings = self.store.settings(workspace, db)
            settings['kaggle'] = values
            self.store.save_settings(workspace, settings, db)
            self.store.audit(db, workspace, actor, 'kaggle_connected')
        return {'connected': True}

    def preview(self, workspace, raw, content_type):
        try:
            value = parse_upload(raw, content_type)
        except DataError as error:
            raise ServiceError(str(error), 400, 'invalid_training_data') from None
        except Exception:
            raise ServiceError('Could not read this training file.', 400, 'invalid_training_data') from None
        from uuid import uuid4
        identity = str(uuid4())
        with self.store.transaction() as db:
            db.execute('DELETE FROM training_data WHERE workspace_id=? AND id NOT IN (SELECT dataset_id FROM training_jobs) AND created<?',
                       (workspace, self.store.clock() - 86400))
            count = db.execute('SELECT COUNT(*) FROM training_data WHERE workspace_id=?', (workspace,)).fetchone()[0]
            if count >= 30:
                raise ServiceError('Training data capacity reached. Ask your operator to archive old jobs.', 429)
            db.execute('INSERT INTO training_data VALUES(?,?,?,?)', (identity, workspace, self.store.encrypt(workspace, value), self.store.clock()))
        return {'dataset_id': identity, 'summary': value['summary']}

    def dataset(self, workspace, identity, db=None):
        if db is None:
            with self.store.connect() as connection:
                return self.dataset(workspace, identity, connection)
        row = db.execute('SELECT * FROM training_data WHERE workspace_id=? AND id=?', (workspace, request_id(identity))).fetchone()
        if not row:
            raise ServiceError('Training data not found.', 404)
        return self.store.decrypt(workspace, row['ciphertext'])

    def start_job(self, workspace, body, actor):
        identity, dataset_id = request_id(body.get('request_id')), request_id(body.get('dataset_id'))
        if body.get('confirm_upload') is not True:
            raise ServiceError('Confirm that these tickets may be uploaded to your private Kaggle dataset.')
        if not self.provider.available():
            raise ServiceError('Ask your operator to install the Kaggle connector.', 503, 'kaggle_dependency_missing')
        credentials = self.credentials(workspace)
        with self.store.transaction() as db:
            previous = db.execute('SELECT * FROM training_jobs WHERE id=?', (identity,)).fetchone()
            if previous:
                if previous['workspace_id'] != workspace or previous['dataset_id'] != dataset_id:
                    raise ServiceError('Request ID already used.', 409)
                return self.public_job(previous)
            if any(row['status'] in ACTIVE for row in self.rows(workspace, db)):
                raise ServiceError('Your workspace already has an active training job.', 409)
            if len(self.rows(workspace, db)) >= 20:
                raise ServiceError('Training history capacity reached. Ask your operator to archive old jobs.', 429)
            value = self.dataset(workspace, dataset_id, db)
            stem = 'laya-train-' + identity.replace('-', '')[:24]
            record = {'summary': value['summary'], 'dataset_sha256': value['dataset_sha256'],
                      'dataset_ref': credentials['username'] + '/' + stem, 'kernel_ref': credentials['username'] + '/' + stem,
                      'failures': 0, 'actor': actor}
            db.execute('INSERT INTO training_jobs VALUES(?,?,?,?,?,?,?,?,0)',
                       (identity, workspace, dataset_id, 'queued', 'upload', encoded(record).decode(), self.store.clock(), 0))
            self.store.audit(db, workspace, actor, 'training_requested', identity)
        self.event.set()
        return next(self.public_job(row) for row in self.rows(workspace) if row['id'] == identity)

    def job(self, workspace, identity):
        identity = request_id(identity)
        row = next((row for row in self.rows(workspace) if row['id'] == identity), None)
        if not row:
            raise ServiceError('Training job not found.', 404)
        return row

    def retry(self, workspace, identity):
        row = self.job(workspace, identity)
        if row['status'] not in ('uncertain', 'paused'):
            raise ServiceError('This job does not need a status check.', 409)
        record = json.loads(row['record'])
        record.update(failures=0, error=None)
        self.save(row, 'working', row['phase'], record, delay=0)
        self.event.set()
        return {'checking': True}

    def abandon(self, workspace, identity, body, actor):
        if body.get('confirm_remote_stopped') is not True:
            raise ServiceError('Stop the private task on Kaggle before ending local tracking.')
        with self.store.transaction() as db:
            row = next((row for row in self.rows(workspace, db) if row['id'] == request_id(identity)), None)
            if not row:
                raise ServiceError('Training job not found.', 404)
            if row['status'] not in ('paused', 'uncertain'):
                raise ServiceError('Only a paused or uncertain job can end tracking.', 409)
            record = json.loads(row['record'])
            record['error'] = 'Tracking ended by the owner. Remote tasks and datasets must be removed on Kaggle.'
            db.execute("UPDATE training_jobs SET status='abandoned',record=?,lease_until=0 WHERE id=? AND workspace_id=?",
                       (encoded(record).decode(), row['id'], workspace))
            self.store.audit(db, workspace, actor, 'training_tracking_ended', row['id'])
        return {'abandoned': True}

    def disconnect(self, workspace, actor):
        with self.store.transaction() as db:
            if any(row['status'] in ACTIVE for row in self.rows(workspace, db)):
                raise ServiceError('Finish or end tracking for your active job first.', 409)
            settings = self.store.settings(workspace, db)
            settings.pop('kaggle', None)
            self.store.save_settings(workspace, settings, db)
            self.store.audit(db, workspace, actor, 'kaggle_disconnected')
        return {'connected': False}

    def save(self, row, status, phase, record, *, delay=60):
        with self.store.transaction() as db:
            db.execute('UPDATE training_jobs SET status=?,phase=?,record=?,due=?,lease_until=0 WHERE workspace_id=? AND id=?',
                       (status, phase, encoded(record).decode(), self.store.clock() + delay, row['workspace_id'], row['id']))

    def import_result(self, row, record, source):
        folder = self.folder(row['workspace_id'], row['id']) / 'adapter'
        folder.mkdir(parents=True, exist_ok=True)
        if source.stat().st_size > MAX_ADAPTER_BYTES:
            raise ValueError('Oversized result archive')
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            allowed = {'adapter.json', 'adapter.safetensors', 'evaluation.json'}
            if len(entries) != 3 or {item.filename for item in entries} != allowed or any(stat.S_ISLNK(item.external_attr >> 16) or item.flag_bits & 1 for item in entries):
                raise ValueError('Unexpected result archive members')
            if sum(item.file_size for item in entries) > MAX_ADAPTER_BYTES or any(item.file_size > 128 * 1024 for item in entries if item.filename.endswith('.json')):
                raise ValueError('Oversized result files')
            for item in entries:
                (folder / item.filename).write_bytes(archive.read(item))
        adapter = verify_adapter(folder)
        report = json.loads((folder / 'evaluation.json').read_text())
        if (adapter['dataset_sha256'] != record['dataset_sha256'] or report.get('dataset_sha256') != record['dataset_sha256']
                or adapter['trained_fields'] != record['summary']['trained_fields']):
            raise ValueError('Result does not belong to this dataset or training plan')
        dataset = self.dataset(row['workspace_id'], row['dataset_id'])
        fields = adapter['trained_fields']
        checked = {}
        for name in ('baseline', 'candidate'):
            checked[name] = {}
            if set(report[name]) != set(fields):
                raise ValueError('Unexpected evaluation fields')
            for field in fields:
                from training.runner import options
                labels = list(range(len(options(field))))
                expected = Counter(options(field).index(ticket['labels'][field]) for ticket in dataset['splits']['test'] if field in ticket['labels'])
                matrix = report[name][field]['confusion_matrix']
                if set(matrix) != {str(label) for label in labels}:
                    raise ValueError('Unexpected evaluation classes')
                gold, prediction = [], []
                for label in labels:
                    values = matrix[str(label)]
                    if set(values) != set(matrix) or any(type(count) is not int or not 0 <= count <= 2000 for count in values.values()) or sum(values.values()) != expected[label]:
                        raise ValueError('Evaluation counts do not match the held-out dataset')
                    for other in labels:
                        count = values[str(other)]
                        gold.extend([label] * count)
                        prediction.extend([other] * count)
                checked[name][field] = classification(gold, prediction, labels)
        result = {'schema_version': 1, 'dataset_sha256': record['dataset_sha256'], **checked,
                  'recommended': recommendation(checked['baseline'], checked['candidate']),
                  'test_tickets': len(dataset['splits']['test']), 'trained_fields': fields}
        # Pin downloaded content independently of the manifest supplied by the remote job.
        record.update(evaluation=result, adapter_sha256=adapter['adapter_sha256'], error=None, failures=0)
        (folder / 'evaluation.json').write_bytes(encoded(result))

    def download(self, workspace, identity):
        row = self.job(workspace, identity)
        if row['status'] != 'ready':
            raise ServiceError('This candidate is not ready.', 409)
        record = json.loads(row['record'])
        folder = self.folder(workspace, row['id']) / 'adapter'
        value = verify_adapter(folder)
        if value['adapter_sha256'] != record['adapter_sha256']:
            raise ServiceError('Candidate model changed.', 409)
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('adapter.json', 'adapter.safetensors'):
                archive.write(folder / name, name)
            archive.writestr('evaluation.json', encoded(record['evaluation']))
        return buffer.getvalue()

    def step(self):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            with self.store.transaction() as db:
                row = db.execute("SELECT * FROM training_jobs WHERE status IN ('queued','working','running') AND due<=? AND lease_until<=? ORDER BY due LIMIT 1",
                                 (self.store.clock(), self.store.clock())).fetchone()
                if not row:
                    return False
                # Persist before external writes; recovered submissions reconcile status, never submit twice.
                db.execute('UPDATE training_jobs SET lease_until=? WHERE id=?', (self.store.clock() + 300, row['id']))
            record = json.loads(row['record'])
            phase = row['phase']
            try:
                credentials = self.credentials(row['workspace_id'])
                folder = self.folder(row['workspace_id'], row['id'])
                if phase == 'upload':
                    paths = build(folder, self.dataset(row['workspace_id'], row['dataset_id']), credentials['username'], row['id'])
                    self.save(row, 'working', 'dataset', record, delay=0)
                    self.provider.call(credentials, 'create', path=paths['input_dir'])
                    self.save(row, 'working', 'dataset', record)
                elif phase == 'dataset':
                    state = self.provider.call(credentials, 'dataset', reference=record['dataset_ref'])['status']
                    if state == 'ready':
                        self.save(row, 'working', 'submit', record, delay=0)
                    elif state in ('error', 'failed'):
                        raise ServiceError('Kaggle could not prepare the private dataset.', 502, 'kaggle_dataset_failed')
                    else:
                        self.save(row, 'working', phase, record)
                elif phase == 'submit':
                    self.save(row, 'working', 'poll', record, delay=60)
                    # Exactly one submission attempt. Timeout/restart moves to status reconciliation.
                    self.provider.call(credentials, 'submit', path=folder / 'kernel')
                    self.save(row, 'running', 'poll', record)
                elif phase == 'poll':
                    state = self.provider.call(credentials, 'status', reference=record['kernel_ref'])['status']
                    if state == 'complete':
                        self.save(row, 'working', 'download', record, delay=0)
                    elif state in ('error', 'failed', 'cancelled', 'canceled'):
                        record['error'] = 'Kaggle training failed. Check GPU access or the private task on Kaggle.'
                        self.save(row, 'failed', phase, record)
                    elif state in ('queued', 'running'):
                        self.save(row, 'running', phase, record)
                    else:
                        raise ServiceError('Kaggle returned an unknown task state.', 502, 'kaggle_invalid_response')
                elif phase == 'download':
                    downloads = folder / 'download'
                    downloads.mkdir(parents=True, exist_ok=True)
                    self.provider.call(credentials, 'output', path=downloads, reference=record['kernel_ref'])
                    self.import_result(row, record, downloads / 'result.zip')
                    self.save(row, 'ready', 'complete', record)
                else:
                    raise ValueError('Unknown training phase')
            except ServiceError as exc:
                record['error'] = str(exc)
                record['failures'] = record.get('failures', 0) + 1
                phase = 'poll' if phase == 'submit' else 'dataset' if phase == 'upload' else phase
                status = 'uncertain' if row['phase'] == 'submit' else 'paused' if record['failures'] >= 3 else 'working'
                self.save(row, status, phase, record, delay=min(900, 60 * 2 ** min(record['failures'], 4)))
            except Exception:
                record['error'] = 'Training result or local files failed verification. The active model was kept.'
                if phase == 'submit':
                    self.save(row, 'uncertain', 'poll', record)
                elif phase == 'upload':
                    self.save(row, 'paused', 'dataset', record)
                else:
                    self.save(row, 'failed', phase, record)
            return True
        finally:
            self.lock.release()

    def use_model(self, workspace, identity, actor):
        row = self.job(workspace, identity)
        record = json.loads(row['record'])
        if row['status'] != 'ready' or not record.get('evaluation', {}).get('recommended'):
            raise ServiceError('Only an improved, verified candidate can be enabled.', 409)
        path = self.folder(workspace, identity) / 'adapter'
        value = verify_adapter(path)
        if value['adapter_sha256'] != record['adapter_sha256']:
            raise ServiceError('Candidate model changed. Keep the current model.', 409)
        self.engines.prepare_adapter(workspace, str(path), record['adapter_sha256'])
        with self.store.transaction() as db:
            settings = self.store.settings(workspace, db)
            settings['laya_adapter'] = {'job_id': row['id'], 'adapter_sha256': record['adapter_sha256'],
                'identity': hashlib.sha256((EXPECTED['checkpoint_sha256'] + ':' + record['adapter_sha256']).encode()).hexdigest()}
            self.store.save_settings(workspace, settings, db)
            self.store.audit(db, workspace, actor, 'training_model_enabled', row['id'])
        return {'active_model': row['id']}

    def restore(self, workspace, actor):
        with self.store.transaction() as db:
            settings = self.store.settings(workspace, db)
            settings.pop('laya_adapter', None)
            self.store.save_settings(workspace, settings, db)
            self.store.audit(db, workspace, actor, 'training_model_restored')
        return {'active_model': None}

    def _loop(self):
        while not getattr(self, 'stopping', False):
            try:
                worked = self.step()
            except Exception:
                worked = False  # Never log private SDK exceptions.
            if not worked:
                self.event.wait(5)
                self.event.clear()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._loop, daemon=True, name='laya-training')
            self.thread.start()

    def stop(self):
        self.stopping = True
        self.event.set()
        if self.thread:
            self.thread.join(timeout=25)
