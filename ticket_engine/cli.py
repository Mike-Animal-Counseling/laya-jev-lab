"""JSON in/out adapter for scripts; inputs are not persisted or logged."""
import argparse
import json
import os
import sys

from .engine import compare
from .errors import EngineError
from .jev import JevEngine
from .laya import LayaEngine


def main():
    parser = argparse.ArgumentParser(description='Classify one SaaS support ticket. JSON is read from stdin.')
    parser.add_argument('--engine', choices=('laya', 'jev', 'compare'), required=True)
    parser.add_argument('--model-path', help='Directory containing the reviewed Laya V5 files')
    parser.add_argument('--key-env', default='TYPESAFE_API_KEY', help='Environment variable explicitly used by this CLI for Jev')
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise ValueError('Input exceeds 16 KB')
        body = json.loads(raw)
        if not isinstance(body, dict) or set(body) - {'subject', 'message'}:
            raise ValueError('Expected subject and message fields')
        laya = LayaEngine(args.model_path) if args.engine != 'jev' else None
        jev = JevEngine(os.environ.get(args.key_env, '')) if args.engine != 'laya' else None
        result = compare(laya, jev, body.get('message'), subject=body.get('subject', '')) if args.engine == 'compare' else (laya or jev).classify(body.get('message'), subject=body.get('subject', ''))
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0
    except EngineError as exc:
        print(json.dumps({'error': exc.code, 'message': str(exc)}), file=sys.stderr)
    except (ValueError, TypeError, OSError):
        print(json.dumps({'error': 'invalid_input', 'message': 'Provide a valid bounded JSON ticket and explicit engine configuration.'}), file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
