"""V5 decision-head continuation. Test tickets never select an epoch or temperature."""
import argparse
import json
from pathlib import Path
import random
import time
import zipfile

from ticket_engine.adaptation import PREFIXES
from ticket_engine.artifacts import EXPECTED, digest, full_rubric_id, verify_checkpoint
from ticket_engine.rules import QUESTIONS
from .data import checksum, encoded
from .metrics import classification, recommendation


def options(field):
    q = QUESTIONS[field]
    return list(q['criteria']) if q['type'] == 'choice' else list(range(4)) if q['type'] == 'score' else [False, True]


def validate_dataset(value):
    splits = value['splits']
    if set(splits) != {'train', 'validation', 'test'} or checksum(splits) != value['dataset_sha256']:
        raise ValueError('Training split integrity failed')
    groups = [{row['group'] for row in rows} for rows in splits.values()]
    if any(not group for group in groups) or any(groups[i] & groups[j] for i in range(3) for j in range(i)):
        raise ValueError('Conversation groups overlap across splits')
    return value


def items(rows, tokenizer, config, fields):
    from ticket_engine._vendor.laya.common import QTYPES, build_sequence
    values = []
    for row in rows:
        for field in fields:
            if field not in row['labels']:
                continue
            q = QUESTIONS[field]
            ids, markers = build_sequence(tokenizer, {key: row[key] for key in ('subject', 'message')},
                                          {'t': q['type'], 'ins': q['instructions'], 'crit': q.get('criteria')},
                                          config['max_len'], config['head_max_len'])
            if len(markers) != len(options(field)):
                raise ValueError('Truncated decision options')
            values.append({'ids': ids, 'markers': markers, 'qtype': QTYPES[q['type']],
                           'field': field, 'label': options(field).index(row['labels'][field])})
    return values


def collate(rows, pad_id, device):
    import torch
    count, length, width = len(rows), max(len(row['ids']) for row in rows), max(len(row['markers']) for row in rows)
    ids = torch.full((count, length), pad_id, dtype=torch.long, device=device)
    attention = torch.zeros_like(ids)
    markers = torch.zeros((count, width), dtype=torch.long, device=device)
    mask = torch.zeros((count, width), dtype=torch.bool, device=device)
    for index, row in enumerate(rows):
        ids[index, :len(row['ids'])] = torch.tensor(row['ids'], device=device)
        attention[index, :len(row['ids'])] = 1
        markers[index, :len(row['markers'])] = torch.tensor(row['markers'], device=device)
        mask[index, :len(row['markers'])] = True
    return {'input_ids': ids, 'attention_mask': attention, 'marker_pos': markers, 'marker_mask': mask,
            'qtype': torch.tensor([row['qtype'] for row in rows], device=device)}


def logits_for(model, rows, pad_id, device):
    import torch
    model.eval()
    result = {}
    with torch.no_grad():
        for row in rows:
            logits = model(**collate([row], pad_id, device))[0][0, :len(row['markers'])].float().cpu()
            if not torch.isfinite(logits).all():
                raise ValueError('Non-finite evaluation output')
            result.setdefault(row['field'], []).append((row['label'], logits))
    return result


def measured(values):
    return {field: classification([pair[0] for pair in pairs], [int(pair[1].argmax()) for pair in pairs], list(range(len(options(field)))))
            for field, pairs in values.items()}


def calibrate(values):
    import torch
    from torch.nn.functional import cross_entropy
    fitted = {}
    for field, pairs in values.items():
        scores = torch.stack([pair[1] for pair in pairs])
        gold = torch.tensor([pair[0] for pair in pairs])
        fitted[field] = min([1 + index / 10 for index in range(41)], key=lambda t: float(cross_entropy(scores / t, gold)))
    return fitted


def run(base, dataset, output, *, device='auto', epochs=3):
    import torch
    from safetensors.torch import save_file
    from ticket_engine.runtime import load_agent
    random.seed(42)
    torch.manual_seed(42)
    torch.set_num_threads(min(4, torch.get_num_threads()))
    verify_checkpoint(base, QUESTIONS)
    value = validate_dataset(json.loads(Path(dataset).read_text(encoding='utf-8')))
    fields = value['summary']['trained_fields']
    if not fields or 'category' not in fields or any(field not in QUESTIONS for field in fields) or not 1 <= epochs <= 3:
        raise ValueError('Invalid training plan')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any((output / name).exists() for name in ('adapter.json', 'adapter.safetensors', 'result.zip')):
        raise ValueError('Choose an empty output directory')
    target = 'cuda' if device == 'auto' and torch.cuda.is_available() else 'cpu' if device == 'auto' else device
    if target not in ('cpu', 'cuda') or (target == 'cuda' and not torch.cuda.is_available()):
        raise ValueError('Requested training device is unavailable')
    agent = load_agent(Path(base))
    model = agent.model.to(target)
    for name, parameter in model.named_parameters():
        parameter.requires_grad_(name.startswith(PREFIXES))
    # No encoder activation cache persists customer text or fills host memory.
    train = items(value['splits']['train'], agent.tok, agent.cfg, fields)
    validation = items(value['splits']['validation'], agent.tok, agent.cfg, fields)
    test = items(value['splits']['test'], agent.tok, agent.cfg, fields)
    baseline_test = logits_for(model, test, agent.tok.pad_token_id, target)
    initial_validation = measured(logits_for(model, validation, agent.tok.pad_token_id, target))
    best_score = sum(v['macro_f1'] for v in initial_validation.values()) / len(fields)
    best = {key: tensor.detach().cpu().clone() for key, tensor in model.state_dict().items() if key.startswith(PREFIXES)}
    selected, updates, started = 0, 0, time.monotonic()
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-5, weight_decay=.01)
    for epoch in range(epochs):
        random.Random(42 + epoch).shuffle(train)
        model.train()
        model.encoder.eval()
        model.act_head.eval()
        optimizer.zero_grad(set_to_none=True)
        for index, row in enumerate(train):
            if time.monotonic() - started > 3 * 3600:
                raise ValueError('Training time limit reached; use a smaller dataset')
            scores = model(**collate([row], agent.tok.pad_token_id, target))[0]
            loss = torch.nn.functional.cross_entropy(scores, torch.tensor([row['label']], device=target))
            if not torch.isfinite(loss):
                raise ValueError('Non-finite training loss')
            remaining = len(train) - (index // 8) * 8
            (loss / min(8, remaining)).backward()
            if (index + 1) % 8 == 0 or index + 1 == len(train):
                torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0, error_if_nonfinite=True)
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)
                updates += 1
        scores = measured(logits_for(model, validation, agent.tok.pad_token_id, target))
        mean = sum(v['macro_f1'] for v in scores.values()) / len(fields)
        if mean > best_score:
            best_score, selected = mean, epoch + 1
            best = {key: tensor.detach().cpu().clone() for key, tensor in model.state_dict().items() if key.startswith(PREFIXES)}
        print(json.dumps({'epoch': epoch + 1, 'updates': updates, 'validation_macro_f1': mean}), flush=True)
    model.load_state_dict(best, strict=False)
    temperatures = calibrate(logits_for(model, validation, agent.tok.pad_token_id, target))
    baseline, candidate = measured(baseline_test), measured(logits_for(model, test, agent.tok.pad_token_id, target))
    save_file({key: tensor.float().contiguous() for key, tensor in best.items()}, str(output / 'adapter.safetensors'))
    metadata = {'schema_version': 1, 'method': 'decision-head-v1', 'initial_checkpoint_sha256': EXPECTED['checkpoint_sha256'],
                'rubric_id': full_rubric_id(QUESTIONS), 'trained_fields': fields, 'temperatures': temperatures,
                'dataset_sha256': value['dataset_sha256'], 'adapter_sha256': digest(output / 'adapter.safetensors')}
    report = {'schema_version': 1, 'dataset_sha256': value['dataset_sha256'], 'baseline': baseline, 'candidate': candidate,
              'recommended': recommendation(baseline, candidate), 'selected_epoch': selected, 'updates': updates,
              'test_tickets': len(value['splits']['test']), 'trained_fields': fields,
              'limitations': ['Small held-out evaluation; not a production accuracy guarantee',
                              'Only labelled fields are adapted; all other fields use unchanged V5 decisions']}
    for name, record in (('adapter.json', metadata), ('evaluation.json', report)):
        (output / name).write_bytes(encoded(record))
    with zipfile.ZipFile(output / 'result.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('adapter.json', 'adapter.safetensors', 'evaluation.json'):
            archive.write(output / name, name)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--data', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--device', choices=('auto', 'cpu', 'cuda'), default='auto')
    parser.add_argument('--epochs', type=int, choices=(1, 2, 3), default=3)
    args = parser.parse_args()
    try:
        result = run(args.base, args.data, args.output, device=args.device, epochs=args.epochs)
    except Exception:
        print('Training failed. Check GPU availability, dependencies and the validated dataset; no ticket text is logged.', flush=True)
        return 1
    print(json.dumps({'complete': True, 'recommended': result['recommended']}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
