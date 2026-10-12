"""Explicit decision-layer adapters anchored to the reviewed V5 checkpoint."""
import hashlib
import json
import math
from pathlib import Path
import re

from .artifacts import EXPECTED, digest, full_rubric_id
from .rules import QUESTIONS

PREFIXES = ('head.', 'type_emb.', 'scorer.')
MAX_ADAPTER_BYTES = 128 * 1024 * 1024


def adapter_identity(record):
    """Pin weights, calibration, labelled fields and data provenance together."""
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def verify_adapter(directory):
    directory = Path(directory)
    for name in ('adapter.json', 'adapter.safetensors'):
        path = directory / name
        if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in [path, *path.parents]):
            raise ValueError('Linked adapter files are not accepted')
    metadata = directory / 'adapter.json'
    tensor = directory / 'adapter.safetensors'
    if metadata.stat().st_size > 16384 or not 8 <= tensor.stat().st_size <= MAX_ADAPTER_BYTES:
        raise ValueError('Adapter size exceeds the supported limits')
    value = json.loads(metadata.read_text(encoding='utf-8'))
    allowed = {'schema_version', 'method', 'initial_checkpoint_sha256', 'rubric_id',
               'trained_fields', 'temperatures', 'dataset_sha256', 'adapter_sha256'}
    if not isinstance(value, dict) or set(value) != allowed:
        raise ValueError('Unexpected adapter metadata fields')
    fields = value.get('trained_fields')
    temperatures = value.get('temperatures')
    if (type(value.get('schema_version')) is not int or value.get('schema_version') != 1 or value.get('method') != 'decision-head-v1'
            or value.get('initial_checkpoint_sha256') != EXPECTED['checkpoint_sha256']
            or value.get('rubric_id') != full_rubric_id(QUESTIONS)
            or not isinstance(fields, list) or not fields or any(not isinstance(field, str) for field in fields) or len(fields) != len(set(fields))
            or any(field not in QUESTIONS for field in fields) or 'category' not in fields
            or not isinstance(temperatures, dict) or set(temperatures) != set(fields)
            or any(type(t) not in (int, float) or not math.isfinite(t) or not 1 <= t <= 5 for t in temperatures.values())
            or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('dataset_sha256', '')))
            or not re.fullmatch(r'[a-f0-9]{64}', str(value.get('adapter_sha256', '')))
            or digest(tensor) != value['adapter_sha256']):
        raise ValueError('Adapter identity, task rules or file integrity do not match')
    return value


class DecisionAdapter:
    def __init__(self, agent, directory):
        self.record = verify_adapter(directory)
        import torch
        from safetensors.torch import load_file
        values = load_file(str(Path(directory) / 'adapter.safetensors'), device='cpu')
        original = agent.model.state_dict()
        expected = {key for key in original if key.startswith(PREFIXES)}
        if set(values) != expected or any(values[key].shape != original[key].shape or not values[key].is_floating_point()
                                          or not torch.isfinite(values[key]).all() for key in values):
            raise ValueError('Adapter tensors do not match the V5 decision layers')
        self.base = {key: original[key].detach().clone() for key in expected}
        self.values = values
        self.identity = adapter_identity(self.record)

    def predict(self, agent, state, questions):
        # Unlabelled fields use the exact original decision weights and temperatures.
        trained = self.record['trained_fields']
        untouched = {key: value for key, value in questions.items() if key not in trained}
        result = agent.predict(state, untouched) if untouched else {'answers': {}, 'usage': {'input_tokens': 0, 'output_tokens': 0}}
        old_temperatures = list(agent.temperature)
        try:
            agent.model.load_state_dict(self.values, strict=False)
            for field in trained:
                primitive = {'choice': 0, 'score': 1, 'noul': 2}[questions[field]['type']]
                agent.temperature[primitive] = self.record['temperatures'][field]
                part = agent.predict(state, {field: questions[field]})
                result['answers'].update(part['answers'])
                result['usage']['input_tokens'] += part['usage']['input_tokens']
        finally:
            agent.model.load_state_dict(self.base, strict=False)
            agent.temperature = old_temperatures
        return result
