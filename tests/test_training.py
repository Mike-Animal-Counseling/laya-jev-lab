"""Private training data, durable external submissions and workspace boundaries."""
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4
import zipfile

from cryptography.fernet import Fernet
from service.app import Application
from service.errors import ServiceError
from service.kaggle_provider import KaggleProvider
from service.kaggle_bridge import download_result, operation, status_name
from service.store import Store
from service.training import Training
from ticket_engine.artifacts import EXPECTED, full_rubric_id
from ticket_engine.rules import QUESTIONS
from training.bundle import build
from training.data import prepare, parse_upload, encoded
from training.metrics import classification


def tickets():
    return [{'subject': f'Synthetic {category} {index}', 'message': f'Synthetic request {category} number {index}.',
             'category': category, 'group_id': f'{category}-{index}', 'customer': 'private-contact@example.com'}
            for category in ('refund', 'account') for index in range(10)]


class DataTests(unittest.TestCase):
    def test_groups_stay_together_and_unknown_labels_stay_unknown(self):
        rows = tickets()
        rows.append({**rows[0], 'message': 'Second message in the same conversation.'})
        value = prepare(rows)
        groups = [{row['group'] for row in values} for values in value['splits'].values()]
        self.assertFalse(groups[0] & groups[1] or groups[0] & groups[2] or groups[1] & groups[2])
        self.assertEqual(value['summary']['trained_fields'], ['category'])
        self.assertNotIn(b'private-contact', encoded(value))
        self.assertTrue(all(set(row['labels']) == {'category'} for split in value['splits'].values() for row in split))

    def test_redacts_before_dedup_and_drops_identity_columns(self):
        rows = tickets()
        rows[0]['message'] = 'Contact synthetic@example.com or +1 (555) 123-4567.'
        value = prepare(rows)
        self.assertNotIn(b'synthetic@example.com', encoded(value))
        self.assertNotIn(b'555', encoded(value))
        self.assertEqual(value['summary']['redacted_fields'], 1)
        rows[1].update(subject=rows[0]['subject'], message='Contact different@example.net or +1 (555) 765-4321.')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            prepare(rows)

    def test_rejects_conflicting_conversation_labels(self):
        rows = tickets()
        rows[-1]['group_id'] = rows[0]['group_id']
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            prepare(rows)

    def test_csv_and_excel_labels_and_formula_rejection(self):
        import csv
        from io import StringIO
        import openpyxl
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=['subject', 'message', 'category', 'group_id', 'urgency'])
        writer.writeheader()
        writer.writerows([{key: row.get(key, '') for key in writer.fieldnames} for row in tickets()])
        self.assertEqual(parse_upload(buffer.getvalue().encode(), 'text/csv')['summary']['tickets'], 20)
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(['subject', 'message', 'category', 'group_id'])
        for row in tickets():
            sheet.append([row[key] for key in ('subject', 'message', 'category', 'group_id')])
        raw = BytesIO()
        workbook.save(raw)
        mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        self.assertEqual(parse_upload(raw.getvalue(), mime)['summary']['tickets'], 20)
        sheet['B2'] = '=1+1'
        raw = BytesIO()
        workbook.save(raw)
        with self.assertRaisesRegex(ValueError, 'formulas'):
            parse_upload(raw.getvalue(), mime)


class ProviderTests(unittest.TestCase):
    @unittest.skipUnless(__import__('importlib').util.find_spec('kagglesdk'), 'optional Kaggle connector')
    def test_official_task_states_include_cancellation_and_initial_script(self):
        from kagglesdk.kernels.types.kernels_enums import KernelWorkerStatus
        expected = {'QUEUED': 'queued', 'RUNNING': 'running', 'COMPLETE': 'complete', 'ERROR': 'error',
                    'CANCEL_REQUESTED': 'running', 'CANCEL_ACKNOWLEDGED': 'cancelled', 'NEW_SCRIPT': 'queued'}
        for value in KernelWorkerStatus:
            self.assertEqual(status_name(value), expected[value.name])

    def test_credentials_are_explicit_not_ambient_or_command_line(self):
        provider = KaggleProvider()
        values = {'username': 'synthetic-user', 'api_token': 'synthetic-private-token-value'}
        with patch.dict(os.environ, {'KAGGLE_KEY': 'ambient-value', 'OTHER_API_KEY': 'ambient-other'}), \
                patch.object(provider, 'available', return_value=True), \
                patch('service.kaggle_provider.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout=b'{"ok":true}')) as child:
            self.assertEqual(provider.call(values, 'check'), {'ok': True})
            command, = child.call_args.args
            environment = child.call_args.kwargs['env']
            self.assertNotIn(values['api_token'], ' '.join(command))
            self.assertNotIn('KAGGLE_KEY', environment)
            self.assertNotIn('OTHER_API_KEY', environment)
            self.assertEqual(environment['KAGGLE_API_TOKEN'], values['api_token'])
            self.assertFalse(Path(environment['KAGGLE_CONFIG_DIR']).exists())

    def test_official_upload_and_submission_are_private_and_explicit(self):
        api = Mock()
        api.get_config_value.return_value = 'synthetic-user'
        api.dataset_create_new.return_value = SimpleNamespace(error=None)
        api.kernels_push.return_value = SimpleNamespace(error=None)
        with patch.dict('sys.modules', {'kaggle': SimpleNamespace(api=api)}), \
                patch.dict(os.environ, {'KAGGLE_USERNAME': 'synthetic-user'}):
            operation('create', 'private-folder', '')
            operation('submit', 'private-kernel', '')
            api.dataset_create_new.assert_called_once_with('private-folder', public=False, quiet=True, convert_to_csv=False)
            api.kernels_push.assert_called_once_with('private-kernel', timeout=14400, acc='NvidiaTeslaT4')
            api.get_config_value.return_value = 'other-user'
            with self.assertRaises(ValueError):
                operation('create', 'private-folder', '')
            self.assertEqual(api.dataset_create_new.call_count, 1)

    @unittest.skipUnless(__import__('importlib').util.find_spec('kagglesdk'), 'optional Kaggle connector')
    def test_download_streams_only_result_and_bounds_size(self):
        from unittest.mock import MagicMock
        api = MagicMock()
        api.parse_kernel_string.return_value = ('synthetic-user', 'synthetic-job', None)
        client = api.build_kaggle_client.return_value.__enter__.return_value
        client.kernels.kernels_api_client.list_kernel_session_output.return_value = SimpleNamespace(
            files=[SimpleNamespace(file_name='result.zip', url='https://example.com/private-result')],
            next_page_token=None, log='ignored-private-log')
        with tempfile.TemporaryDirectory() as path, patch('requests.Session') as session_class, \
                patch('ticket_engine.adaptation.MAX_ADAPTER_BYTES', 64):
            source = session_class.return_value.__enter__.return_value.get.return_value.__enter__.return_value
            source.status_code, source.headers = 200, {}
            source.iter_content.return_value = [b'synthetic-model']
            download_result(api, path, 'synthetic-user/synthetic-job')
            self.assertEqual([file.name for file in Path(path).iterdir()], ['result.zip'])
            self.assertEqual((Path(path) / 'result.zip').read_bytes(), b'synthetic-model')
            api.kernels_output.assert_not_called()
            source.iter_content.return_value = [b'x' * 65]
            with self.assertRaises(ValueError):
                download_result(api, path, 'synthetic-user/synthetic-job')
            self.assertFalse((Path(path) / 'result.zip').exists())


class Provider:
    def __init__(self):
        self.calls = []
        self.timeout_submit = False
        self.result = None

    def available(self):
        return True

    def call(self, credentials, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == 'submit' and self.timeout_submit:
            raise ServiceError('Kaggle timed out.', 502, 'kaggle_timeout')
        if action == 'dataset':
            return {'status': 'ready'}
        if action == 'status':
            return {'status': 'complete'}
        if action == 'output':
            (Path(kwargs['path']) / 'result.zip').write_bytes(self.result)
        return {'ok': True}


class JobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root / 'master.key').write_bytes(Fernet.generate_key())
        self.clock = time.time()
        self.store = Store(root, clock=lambda: self.clock)
        self.workspace = self.store.create_workspace('acme', 'admin', 'synthetic-test-password')
        self.other = self.store.create_workspace('beta', 'admin', 'synthetic-test-password')
        self.engines = Mock()
        self.provider = Provider()
        self.training = Training(self.store, self.engines, self.provider)
        self.training.connect(self.workspace, {'username': 'synthetic-user', 'api_token': 'synthetic-private-token-value'}, 'admin')
        value = prepare(tickets())
        self.dataset = str(uuid4())
        with self.store.transaction() as db:
            db.execute('INSERT INTO training_data VALUES(?,?,?,?)', (self.dataset, self.workspace, self.store.encrypt(self.workspace, value), self.clock))
        self.value = value
        self.identity = str(uuid4())
        self.body = {'dataset_id': self.dataset, 'request_id': self.identity, 'confirm_upload': True}

    def tearDown(self):
        self.temp.cleanup()

    def step(self):
        self.clock += 601
        self.assertTrue(self.training.step())

    def result_zip(self, *, wrong_dataset=False, wrong_counts=False):
        tensor = b'synthetic-tensor-test-fixture'
        metadata = {'schema_version': 1, 'method': 'decision-head-v1', 'initial_checkpoint_sha256': EXPECTED['checkpoint_sha256'],
                    'rubric_id': full_rubric_id(QUESTIONS), 'trained_fields': ['category'], 'temperatures': {'category': 1},
                    'dataset_sha256': '0' * 64 if wrong_dataset else self.value['dataset_sha256'],
                    'adapter_sha256': hashlib.sha256(tensor).hexdigest()}
        gold = [list(QUESTIONS['category']['criteria']).index(row['labels']['category']) for row in self.value['splits']['test']]
        if wrong_counts:
            gold.append(0)
        report = {'dataset_sha256': metadata['dataset_sha256'], 'baseline': {'category': classification(gold, [1] * len(gold), list(range(5)))},
                  'candidate': {'category': classification(gold, gold, list(range(5)))}, 'recommended': False}
        data = BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('adapter.safetensors', tensor)
            archive.writestr('adapter.json', encoded(metadata))
            archive.writestr('evaluation.json', encoded(report))
        return data.getvalue()

    def test_start_is_idempotent_and_workspace_scoped(self):
        first = self.training.start_job(self.workspace, self.body, 'admin')
        self.assertEqual(first, self.training.start_job(self.workspace, self.body, 'admin'))
        self.assertEqual(len(self.training.rows(self.workspace)), 1)
        with self.assertRaises(ServiceError):
            self.training.start_job(self.other, {**self.body, 'request_id': str(uuid4())}, 'admin')
        with self.assertRaises(ServiceError):
            self.training.job(self.other, self.identity)
        with self.assertRaises(ServiceError):
            self.training.start_job(self.workspace, {**self.body, 'request_id': str(uuid4())}, 'admin')

    def test_submission_timeout_and_restart_never_replay_gpu(self):
        self.training.start_job(self.workspace, self.body, 'admin')
        self.step()
        self.step()
        self.provider.timeout_submit = True
        self.step()
        self.assertEqual(self.training.job(self.workspace, self.identity)['status'], 'uncertain')
        self.training = Training(self.store, self.engines, self.provider)
        self.training.retry(self.workspace, self.identity)
        self.step()
        self.assertEqual(sum(action == 'submit' for action, _ in self.provider.calls), 1)
        self.assertEqual(self.training.job(self.workspace, self.identity)['phase'], 'download')

    def test_full_job_recomputes_metrics_enables_only_owner_workspace_and_restores(self):
        self.provider.result = self.result_zip()
        self.training.start_job(self.workspace, self.body, 'admin')
        for _ in range(5):
            self.step()
        status = self.training.status(self.workspace)
        self.assertEqual(status['jobs'][0]['status'], 'ready')
        self.assertTrue(status['jobs'][0]['evaluation']['recommended'])
        with zipfile.ZipFile(BytesIO(self.training.download(self.workspace, self.identity))) as archive:
            self.assertEqual(set(archive.namelist()), {'adapter.json', 'adapter.safetensors', 'evaluation.json'})
            self.assertTrue(json.loads(archive.read('evaluation.json'))['recommended'])
        with self.assertRaises(ServiceError):
            self.training.download(self.other, self.identity)
        self.assertNotIn('synthetic-private-token-value', json.dumps(status))
        self.assertNotIn(b'synthetic-private-token-value', self.store.path.read_bytes())
        self.training.use_model(self.workspace, self.identity, 'admin')
        self.assertEqual(self.store.settings(self.workspace)['laya_adapter']['job_id'], self.identity)
        self.assertNotIn('laya_adapter', self.store.settings(self.other))
        self.training.restore(self.workspace, 'admin')
        self.assertNotIn('laya_adapter', self.store.settings(self.workspace))

    def test_end_tracking_needs_confirmation_and_disconnect_keeps_model(self):
        self.training.start_job(self.workspace, self.body, 'admin')
        with self.assertRaises(ServiceError):
            self.training.disconnect(self.workspace, 'admin')
        self.step()
        self.step()
        self.provider.timeout_submit = True
        self.step()
        with self.assertRaises(ServiceError):
            self.training.abandon(self.workspace, self.identity, {}, 'admin')
        with self.assertRaises(ServiceError):
            self.training.abandon(self.other, self.identity, {'confirm_remote_stopped': True}, 'admin')
        self.training.abandon(self.workspace, self.identity, {'confirm_remote_stopped': True}, 'admin')
        self.assertEqual(self.training.job(self.workspace, self.identity)['status'], 'abandoned')
        self.training.disconnect(self.workspace, 'admin')
        self.assertNotIn('kaggle', self.store.settings(self.workspace))
        self.assertEqual(sum(action == 'submit' for action, _ in self.provider.calls), 1)

    def test_parser_exception_never_echoes_imported_values(self):
        with patch('service.training.parse_upload', side_effect=ValueError('synthetic-private-message')):
            with self.assertRaises(ServiceError) as caught:
                self.training.preview(self.workspace, b'fixture', 'text/csv')
        self.assertNotIn('synthetic-private-message', str(caught.exception))

    def test_calibration_tampering_blocks_enable_and_download(self):
        self.provider.result = self.result_zip()
        self.training.start_job(self.workspace, self.body, 'admin')
        for _ in range(5):
            self.step()
        path = self.training.folder(self.workspace, self.identity) / 'adapter/adapter.json'
        value = json.loads(path.read_text())
        value['temperatures']['category'] = 3
        path.write_text(json.dumps(value))
        for operation in (self.training.download, lambda workspace, identity: self.training.use_model(workspace, identity, 'admin')):
            with self.assertRaises(ServiceError):
                operation(self.workspace, self.identity)
        self.engines.prepare_adapter.assert_not_called()

    def test_foreign_or_inflated_results_fail_without_switching(self):
        for bad in (self.result_zip(wrong_dataset=True), self.result_zip(wrong_counts=True)):
            identity = str(uuid4())
            self.provider.result = bad
            self.training.start_job(self.workspace, {**self.body, 'request_id': identity}, 'admin')
            for _ in range(5):
                self.step()
            self.assertEqual(self.training.job(self.workspace, identity)['status'], 'failed')
            self.assertNotIn('laya_adapter', self.store.settings(self.workspace))

    def test_bundle_is_private_and_contains_no_credentials(self):
        root = Path(self.temp.name) / 'bundle'
        paths = build(root, self.value, 'synthetic-user', self.identity)
        metadata = json.loads((paths['kernel_dir'] / 'kernel-metadata.json').read_text())
        self.assertTrue(metadata['is_private'])
        self.assertTrue(metadata['enable_gpu'])
        self.assertNotIn(b'synthetic-private-token-value', (paths['input_dir'] / 'runtime.zip').read_bytes())
        self.assertNotIn('private-contact', (paths['input_dir'] / 'dataset.json').read_text())

    def test_training_routes_require_owner_and_csrf(self):
        token, csrf = self.store.login('acme', 'admin', 'synthetic-test-password')
        app = Application(self.store, self.engines, 'http://127.0.0.1:5180', training=self.training)
        raw = encoded(self.body)
        environ = {'REQUEST_METHOD': 'POST', 'PATH_INFO': '/api/training/start', 'HTTP_HOST': '127.0.0.1:5180',
                   'HTTP_ORIGIN': app.public_url, 'HTTP_COOKIE': 'laya-session=' + token, 'wsgi.input': BytesIO(raw),
                   'CONTENT_LENGTH': str(len(raw)), 'CONTENT_TYPE': 'application/json'}
        statuses = []
        app(environ, lambda status, headers: statuses.append(status))
        self.assertTrue(statuses[-1].startswith('403'))
        environ['HTTP_X_CSRF_TOKEN'] = csrf
        environ['wsgi.input'] = BytesIO(raw)
        with self.store.transaction() as db:
            db.execute("UPDATE users SET role='member' WHERE workspace_id=?", (self.workspace,))
        app(environ, lambda status, headers: statuses.append(status))
        self.assertTrue(statuses[-1].startswith('403'))
