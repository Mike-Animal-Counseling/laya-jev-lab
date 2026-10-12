"""Shared verified local runtime and workspace-owned hosted credentials."""
from pathlib import Path
from collections import OrderedDict
import threading

from ticket_engine.artifacts import EXPECTED
from ticket_engine.jev import JevEngine
from ticket_engine.laya import LayaEngine
from ticket_engine.transport import DEFAULT_MODEL
from .errors import ServiceError


class Engines:
    def __init__(self, store, model_path=None):
        self.store, self.laya = store, None
        self.local_status = 'unconfigured'
        self.adapters = OrderedDict()
        self.adapter_lock = threading.RLock()
        if model_path and (Path(model_path) / 'training_manifest.json').is_file():
            self.laya = LayaEngine(model_path)
            self.local_status = 'loading'
            threading.Thread(target=self._prepare, daemon=True, name='laya-loader').start()

    def _prepare(self):
        try:
            import torch
            import os
            torch.set_num_threads(min(4, os.cpu_count() or 1))
            self.laya.prepare()
            self.local_status = 'ready'
        except Exception:
            self.local_status = 'error'

    def jev(self, workspace):
        key = self.store.settings(workspace).get('jev_api_key', '')
        if not key:
            raise ServiceError('Configure your workspace Jev key first.', 503, 'not_configured')
        return JevEngine(key)

    def status(self, workspace):
        settings = self.store.settings(workspace)
        ready = bool(settings.get('jev_api_key'))
        adapted = settings.get('laya_adapter')
        identity = 'laya-ticket-adapted-' + adapted['identity'][:12] if adapted else 'laya-ticket-full-' + EXPECTED['checkpoint_sha256'][:12]
        message = ('Your Laya model ready' if adapted else 'Laya V5 ready') if self.local_status == 'ready' else 'Install and verify Laya V5'
        return {'laya-ft': {'status': self.local_status, 'message': message, 'model': identity, 'offline': True, 'artifact_version': 5}, 'jev': {'status': 'ready' if ready else 'unconfigured', 'message': 'Jev ready' if ready else 'Configure your workspace Jev key', 'model': DEFAULT_MODEL, 'offline': False}}

    def prepare_adapter(self, workspace, path, expected_hash, expected_identity=None):
        if self.local_status != 'ready':
            raise ServiceError('Install and load the original V5 before enabling a candidate.', 409)
        from ticket_engine.adaptation import DecisionAdapter
        with self.adapter_lock, self.laya._lock:
            key = (workspace, str(Path(path).resolve()), expected_identity or expected_hash)
            adapter = self.adapters.pop(key, None)
            if adapter is None:
                adapter = DecisionAdapter(self.laya._agent, path)
            if adapter.record['adapter_sha256'] != expected_hash or (expected_identity and adapter.identity != expected_identity):
                raise ServiceError('Candidate model integrity failed.', 409)
            self.adapters[key] = adapter
            while len(self.adapters) > 4:
                self.adapters.popitem(last=False)
            return adapter

    def local_classify(self, workspace, ticket):
        if self.local_status != 'ready':
            raise ServiceError('The local model is not ready.', 503, 'model_not_ready')
        with self.adapter_lock, self.laya._lock:
            settings = self.store.settings(workspace).get('laya_adapter')
            if not settings:
                return self.laya.classify(ticket.get('message'), subject=ticket.get('subject', ''))
            from .workspace import request_id
            path = self.store.directory / 'training' / request_id(workspace) / request_id(settings['job_id']) / 'adapter'
            adapter = self.prepare_adapter(workspace, path, settings['adapter_sha256'], settings['identity'])
            previous = self.laya._adapter, self.laya._local_sha
            try:
                self.laya._adapter, self.laya._local_sha = adapter, adapter.identity
                return self.laya.classify(ticket.get('message'), subject=ticket.get('subject', ''))
            finally:
                self.laya._adapter, self.laya._local_sha = previous

    def classify(self, workspace, provider, ticket):
        if provider == 'laya-ft':
            return self.local_classify(workspace, ticket)
        elif provider == 'jev':
            engine = self.jev(workspace)
        else:
            raise ServiceError('Choose laya or jev.')
        return engine.classify(ticket.get('message'), subject=ticket.get('subject', ''))

    def compare(self, workspace, ticket):
        if self.local_status != 'ready':
            raise ServiceError('The local model is not ready.', 503, 'model_not_ready')
        from ticket_engine.engine import ComparisonResult
        left = self.local_classify(workspace, ticket)
        right = self.jev(workspace).classify(ticket.get('message'), subject=ticket.get('subject', ''))
        differences = tuple(field for field in ('category', 'priority', 'complaint', 'churn', 'refund')
                            if (getattr(left, field) >= .5 if field in ('complaint', 'churn', 'refund') else getattr(left, field))
                            != (getattr(right, field) >= .5 if field in ('complaint', 'churn', 'refund') else getattr(right, field)))
        return ComparisonResult(left, right, differences)
