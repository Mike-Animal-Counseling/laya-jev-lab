"""Shared verified local runtime and workspace-owned hosted credentials."""
from pathlib import Path
import threading

from ticket_engine import compare
from ticket_engine.artifacts import EXPECTED
from ticket_engine.jev import JevEngine
from ticket_engine.laya import LayaEngine
from ticket_engine.transport import DEFAULT_MODEL
from .errors import ServiceError


class Engines:
    def __init__(self, store, model_path=None):
        self.store, self.laya = store, None
        self.local_status = 'unconfigured'
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
        ready = bool(self.store.settings(workspace).get('jev_api_key'))
        return {'laya-ft': {'status': self.local_status, 'message': 'Laya V5 ready' if self.local_status == 'ready' else 'Install and verify Laya V5', 'model': 'laya-ticket-full-' + EXPECTED['checkpoint_sha256'][:12], 'offline': True, 'artifact_version': 5}, 'jev': {'status': 'ready' if ready else 'unconfigured', 'message': 'Jev ready' if ready else 'Configure your workspace Jev key', 'model': DEFAULT_MODEL, 'offline': False}}

    def classify(self, workspace, provider, ticket):
        if provider == 'laya-ft':
            if self.local_status != 'ready':
                raise ServiceError('The local model is not ready.', 503, 'model_not_ready')
            engine = self.laya
        elif provider == 'jev':
            engine = self.jev(workspace)
        else:
            raise ServiceError('Choose laya or jev.')
        return engine.classify(ticket.get('message'), subject=ticket.get('subject', ''))

    def compare(self, workspace, ticket):
        if self.local_status != 'ready':
            raise ServiceError('The local model is not ready.', 503, 'model_not_ready')
        return compare(self.laya, self.jev(workspace), ticket.get('message'), subject=ticket.get('subject', ''))
