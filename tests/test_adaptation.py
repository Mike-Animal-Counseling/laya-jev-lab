"""Adapters never modify the encoder, unlabelled decisions or the default V5 identity."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from ticket_engine.adaptation import DecisionAdapter
from ticket_engine.artifacts import EXPECTED, full_rubric_id
from ticket_engine.rules import QUESTIONS
from ticket_engine import LayaEngine, EngineError


@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('safetensors'), 'Optional local inference dependencies')
class AdapterTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.model = torch.nn.Module()
        self.model.head = torch.nn.Linear(2, 2)
        self.model.type_emb = torch.nn.Embedding(3, 2)
        self.model.scorer = torch.nn.Linear(2, 1)
        self.model.encoder = torch.nn.Linear(2, 2)
        self.calls = []
        self.agent = Mock(model=self.model, temperature=[1.7, 1.5, 3.4])
        def predict(state, questions):
            self.calls.append((set(questions), self.model.head.weight.detach().clone()))
            return {'answers': {key: 'synthetic' for key in questions}, 'usage': {'input_tokens': len(questions), 'output_tokens': 0}}
        self.agent.predict.side_effect = predict
        self.base = {key: value.clone() for key, value in self.model.state_dict().items()}

    def tearDown(self):
        self.temp.cleanup()

    def artifact(self, *, malicious=False, nan=False):
        import torch
        from safetensors.torch import save_file
        values = {key: value.clone() + .25 for key, value in self.base.items() if not key.startswith('encoder.')}
        if malicious:
            values['encoder.weight'] = self.base['encoder.weight']
        if nan:
            values['head.weight'][0, 0] = float('nan')
        save_file(values, str(self.root / 'adapter.safetensors'))
        metadata = {'schema_version': 1, 'method': 'decision-head-v1', 'initial_checkpoint_sha256': EXPECTED['checkpoint_sha256'],
                    'rubric_id': full_rubric_id(QUESTIONS), 'trained_fields': ['category'], 'temperatures': {'category': 2},
                    'dataset_sha256': '0' * 64, 'adapter_sha256': hashlib.sha256((self.root / 'adapter.safetensors').read_bytes()).hexdigest()}
        (self.root / 'adapter.json').write_text(json.dumps(metadata))

    def test_unlabelled_fields_and_base_weights_are_exactly_preserved(self):
        import torch
        self.artifact()
        adapter = DecisionAdapter(self.agent, self.root)
        result = adapter.predict(self.agent, {'message': 'synthetic'}, QUESTIONS)
        self.assertEqual(self.calls[0][0], set(QUESTIONS) - {'category'})
        self.assertTrue(torch.equal(self.calls[0][1], self.base['head.weight']))
        self.assertFalse(torch.equal(self.calls[1][1], self.base['head.weight']))
        self.assertEqual(set(result['answers']), set(QUESTIONS))
        self.assertEqual(self.agent.temperature, [1.7, 1.5, 3.4])
        for key, value in self.model.state_dict().items():
            self.assertTrue(torch.equal(value, self.base[key]))

    def test_failure_restores_original_weights(self):
        import torch
        self.artifact()
        adapter = DecisionAdapter(self.agent, self.root)
        self.agent.predict.side_effect = [ {'answers': {}, 'usage': {'input_tokens': 0}}, RuntimeError('synthetic') ]
        with self.assertRaises(RuntimeError):
            adapter.predict(self.agent, {}, QUESTIONS)
        self.assertTrue(torch.equal(self.model.head.weight, self.base['head.weight']))

    def test_encoder_replacement_and_nan_tensors_are_rejected(self):
        for kwargs in ({'malicious': True}, {'nan': True}):
            self.artifact(**kwargs)
            with self.assertRaises(ValueError):
                DecisionAdapter(self.agent, self.root)

    def test_failed_adapter_load_never_silently_falls_back_on_retry(self):
        engine = LayaEngine(self.root, adapter_path=self.root / 'missing')
        with patch('ticket_engine.engine.verify_checkpoint'), patch('ticket_engine.engine.load_agent', return_value=self.agent) as load:
            for _ in range(2):
                with self.assertRaises(EngineError):
                    engine.prepare()
            self.assertEqual(load.call_count, 2)
            self.assertIsNone(engine._agent)

    def test_manifest_cannot_smuggle_unexpected_content_into_downloads(self):
        self.artifact()
        path = self.root / 'adapter.json'
        value = json.loads(path.read_text())
        value['raw_tickets'] = 'synthetic-private-message'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'metadata'):
            DecisionAdapter(self.agent, self.root)

    def test_calibration_changes_identity_and_workspace_cache_does_not_reuse_other_jobs(self):
        from service.engines import Engines
        from service.errors import ServiceError
        from ticket_engine.adaptation import adapter_identity
        self.artifact()
        first = self.root
        second = self.root / 'second'
        second.mkdir()
        for name in ('adapter.json', 'adapter.safetensors'):
            (second / name).write_bytes((first / name).read_bytes())
        metadata = json.loads((second / 'adapter.json').read_text())
        old_identity = adapter_identity(metadata)
        metadata['temperatures']['category'] = 4
        (second / 'adapter.json').write_text(json.dumps(metadata))
        self.assertNotEqual(old_identity, adapter_identity(metadata))
        engines = Engines(Mock())
        engines.local_status = 'ready'
        engines.laya = Mock(_agent=self.agent, _lock=threading.RLock())
        a = engines.prepare_adapter('workspace', first, metadata['adapter_sha256'], old_identity)
        b = engines.prepare_adapter('workspace', second, metadata['adapter_sha256'], adapter_identity(metadata))
        self.assertIsNot(a, b)
        self.assertEqual(a.record['temperatures']['category'], 2)
        self.assertEqual(b.record['temperatures']['category'], 4)
        with self.assertRaises(ServiceError):
            engines.prepare_adapter('other-workspace', second, metadata['adapter_sha256'], old_identity)
