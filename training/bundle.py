"""Build a self-contained private Kaggle job from explicitly allowed public code."""
import hashlib
import json
from pathlib import Path
import zipfile

from .data import encoded

ROOT = Path(__file__).resolve().parents[1]
TRAINING_FILES = ('training/__init__.py', 'training/data.py', 'training/metrics.py', 'training/runner.py', 'training/requirements.lock')


def build(directory, dataset, owner, identity):
    directory = Path(directory)
    data_dir, kernel_dir = directory / 'input', directory / 'kernel'
    data_dir.mkdir(parents=True, exist_ok=True)
    kernel_dir.mkdir(parents=True, exist_ok=True)
    stem = 'laya-train-' + identity.replace('-', '')[:24]
    reference = owner + '/' + stem
    allowlist = json.loads((ROOT / 'release-files.json').read_text())
    names = [name for name in allowlist if name.startswith('ticket_engine/') and name.endswith(('.py', '.json', 'LICENSE'))]
    names += list(TRAINING_FILES) + ['LICENSE', 'NOTICE.md', 'licenses/mmbert-MIT.txt']
    if any(name not in allowlist for name in names):
        raise ValueError('Training source must pass the release allowlist')
    with zipfile.ZipFile(data_dir / 'runtime.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            source = ROOT / name
            if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction()) for p in [source, *source.parents]):
                raise ValueError('Linked training code is not accepted')
            archive.writestr(name, source.read_bytes())
    digest = hashlib.sha256((data_dir / 'runtime.zip').read_bytes()).hexdigest()
    (data_dir / 'dataset.json').write_bytes(encoded(dataset))
    (data_dir / 'dataset-metadata.json').write_bytes(encoded({'id': reference, 'title': 'Laya Train ' + identity.replace('-', '')[:24],
                                                            'licenses': [{'name': 'other'}]}))
    source = (ROOT / 'training/kaggle_bootstrap.py').read_text(encoding='utf-8').replace('__DATASET_SLUG__', stem).replace('__BUNDLE_SHA__', digest)
    (kernel_dir / 'train.py').write_text(source, encoding='utf-8')
    (kernel_dir / 'kernel-metadata.json').write_bytes(encoded({'id': reference, 'title': 'Laya Train ' + identity.replace('-', '')[:24],
        'code_file': 'train.py', 'language': 'python', 'kernel_type': 'script', 'is_private': True,
        'enable_gpu': True, 'enable_internet': True, 'dataset_sources': [reference],
        'competition_sources': [], 'kernel_sources': [], 'model_sources': []}))
    return {'dataset_ref': reference, 'kernel_ref': reference, 'input_dir': data_dir, 'kernel_dir': kernel_dir}
