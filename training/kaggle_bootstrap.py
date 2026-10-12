"""Generated Kaggle entry point. Credentials and customer text are never in code."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


def main():
    mounted = Path('/kaggle/input/__DATASET_SLUG__')
    bundle = mounted / 'runtime.zip'
    if hashlib.sha256(bundle.read_bytes()).hexdigest() != '__BUNDLE_SHA__':
        raise ValueError('Training code integrity failed')
    with tempfile.TemporaryDirectory(prefix='laya-training-') as scratch:
        root = Path(scratch)
        with zipfile.ZipFile(bundle) as archive:
            if any(Path(item.filename).is_absolute() or '..' in Path(item.filename).parts for item in archive.infolist()):
                raise ValueError('Unsafe training code bundle')
            archive.extractall(root)
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet', '--require-hashes', '--index-url',
                        'https://pypi.org/simple', '-r', str(root / 'training/requirements.lock')], check=True)
        import torch
        if not torch.cuda.is_available() or tuple(int(v) for v in torch.__version__.split('+')[0].split('.')[:2]) < (2, 6):
            raise ValueError('A CUDA PyTorch 2.6+ environment is required')
        checkpoint = root / 'v5.zip'
        request = urllib.request.Request('https://github.com/Mike-Animal-Counseling/laya-jev-lab/releases/download/v0.1.0/laya-v5-inference.zip')
        with urllib.request.urlopen(request, timeout=120) as response, checkpoint.open('wb') as target:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > 599688968:
                    raise ValueError('Oversized V5 archive')
                target.write(chunk)
        with checkpoint.open('rb') as stream:
            value = hashlib.file_digest(stream, 'sha256').hexdigest()
        if value != '3be56e2273a9c1b1c7cb59ea42e4c2926ef0c3a86ea1c0ef6cee050d8270e12b':
            raise ValueError('V5 archive integrity failed')
        base = root / 'base'
        base.mkdir()
        # The immutable archive hash authenticates its exact reviewed member list.
        with zipfile.ZipFile(checkpoint) as archive:
            archive.extractall(base)
        subprocess.run([sys.executable, '-m', 'training.runner', '--base', str(base), '--data',
                        str(mounted / 'dataset.json'), '--output', str(root / 'output'), '--device', 'cuda'], cwd=root, check=True)
        shutil.copyfile(root / 'output/result.zip', '/kaggle/working/result.zip')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Laya training failed. Check GPU access and dependencies. Ticket contents and credentials are not logged.', flush=True)
        raise SystemExit(1) from None
