"""Bounded labelled imports, basic redaction and deterministic group splits."""
from collections import Counter, defaultdict
import csv
import hashlib
from io import BytesIO, StringIO
import json
import re
import unicodedata
import zipfile

from ticket_engine.engine import validate_input
from ticket_engine.rules import CATEGORIES, QUESTIONS

class DataError(ValueError):
    """Safe, authored messages; parser exceptions must never be echoed."""


MAX_ROWS = 2000
EMAIL = re.compile(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}')
PHONE = re.compile(r'(?<!\w)(?:\+\d[\d ()-]{8,}\d|1[3-9]\d{9})(?!\w)')
SECRET = re.compile(r'\b(?:sk-|hf_|ghp_|github_pat_)[A-Za-z0-9_-]{20,}\b')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def checksum(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def redact(value):
    return SECRET.sub('[credential]', PHONE.sub('[phone]', EMAIL.sub('[email]', value)))


def parse_upload(raw, content_type):
    if not 0 < len(raw) <= 2 * 1024 * 1024:
        raise DataError('Choose a CSV or Excel file up to 2 MB.')
    if content_type == 'text/csv':
        text = raw.decode('utf-8-sig')
        reader = csv.DictReader(StringIO(text))
        if not reader.fieldnames or len(reader.fieldnames) > 12 or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise DataError('Use unique column headers.')
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS or None in row or any(value is None for value in row.values()):
                raise DataError('Use at most 2,000 complete rows.')
            rows.append(row)
        return prepare(rows)
    if content_type != 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        raise DataError('Choose .csv or .xlsx.')
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) > 200 or sum(item.file_size for item in entries) > 16 * 1024 * 1024:
            raise DataError('Excel file expands beyond the supported size.')
        if any('vba' in item.filename.lower() or 'externallinks/' in item.filename.lower() for item in entries):
            raise DataError('Macros and external links are not supported.')
    import openpyxl
    workbook = openpyxl.load_workbook(BytesIO(raw), read_only=True, data_only=False, keep_links=False)
    try:
        sheet = workbook.worksheets[0]
        if sheet.max_row > MAX_ROWS + 1 or sheet.max_column > 12:
            raise DataError('Use at most 2,000 rows and 12 columns.')
        rows = sheet.iter_rows()
        cells = next(rows, ())
        headers = [str(cell.value or '').strip() for cell in cells]
        if not headers or len(set(headers)) != len(headers):
            raise DataError('Use unique column headers.')
        values = []
        for cells in rows:
            if len(values) >= MAX_ROWS or any(cell.data_type == 'f' for cell in cells):
                raise DataError('Excel formulas are not supported.')
            if any(cell.value is not None for cell in cells):
                values.append(dict(zip(headers, (cell.value for cell in cells))))
        return prepare(values)
    finally:
        workbook.close()


def prepare(rows):
    if not isinstance(rows, list) or not 20 <= len(rows) <= MAX_ROWS:
        raise DataError('Provide 20 to 2,000 labelled tickets.')
    clean, seen, groups = [], set(), {}
    redactions = 0
    counts = Counter()
    for number, row in enumerate(rows, 2):
        if not isinstance(row, dict):
            raise DataError('Invalid training row.')
        try:
            state = validate_input(row.get('message'), row.get('subject') or '')
        except Exception:
            raise DataError(f'Row {number}: provide a subject and message within the supported limits.') from None
        labels = {'category': row.get('category')}
        if labels['category'] not in CATEGORIES:
            raise DataError(f'Row {number}: category must be refund, technical, sales, account or other.')
        for field in QUESTIONS.keys() - {'category'}:
            value = row.get(field)
            if value in (None, ''):
                continue  # Unknown labels never become false targets.
            if field == 'urgency':
                if str(value) not in ('0', '1', '2', '3'):
                    raise DataError(f'Row {number}: urgency must be 0 to 3.')
                labels[field] = int(value)
            else:
                mapping = {'true': True, 'false': False, '1': True, '0': False}
                if str(value).lower() not in mapping:
                    raise DataError(f'Row {number}: {field} must be true, false, 1 or 0.')
                labels[field] = mapping[str(value).lower()]
        safe = {key: redact(value) for key, value in state.items()}
        redactions += sum(safe[key] != state[key] for key in state)
        text_key = checksum({key: re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).casefold() for key, value in safe.items()})
        if text_key in seen:
            raise DataError(f'Row {number}: duplicate ticket after redaction. Remove duplicates first.')
        seen.add(text_key)
        group = row.get('group_id') or row.get('ticket_id') or text_key
        if not isinstance(group, (str, int)) or len(str(group)) > 256:
            raise DataError(f'Row {number}: invalid group_id.')
        group = hashlib.sha256(str(group).encode()).hexdigest()
        if group in groups and groups[group] != labels['category']:
            raise DataError('One conversation group has conflicting categories. Review its labels.')
        groups[group] = labels['category']
        clean.append({**safe, 'labels': labels, 'group': group})
        counts[labels['category']] += 1
    by_category = defaultdict(dict)
    for row in clean:
        by_category[row['labels']['category']].setdefault(row['group'], []).append(row)
    if len(by_category) < 2 or any(len(values) < 10 for values in by_category.values()):
        raise DataError('Provide at least two categories, each with 10 distinct conversation groups.')
    splits = {name: [] for name in ('train', 'validation', 'test')}
    for values in by_category.values():
        ordered = sorted(values, key=lambda group: hashlib.sha256(('laya-split-42:' + group).encode()).hexdigest())
        held = max(2, len(ordered) // 5)
        for index, group in enumerate(ordered):
            name = 'test' if index < held else 'validation' if index < held * 2 else 'train'
            splits[name].extend(values[group])
    fields = [field for field in QUESTIONS if all(any(field in row['labels'] for row in split) for split in splits.values())]
    # Auxiliary fields need both outcomes (or at least two urgency levels) in every split.
    fields = [field for field in fields if field == 'category' or all(len({row['labels'][field] for row in split if field in row['labels']}) >= 2 for split in splits.values())]
    for split in splits.values():
        for row in split:
            row['labels'] = {field: value for field, value in row['labels'].items() if field in fields}
    summary = {'tickets': len(clean), 'categories': dict(counts), 'splits': {name: len(values) for name, values in splits.items()},
               'trained_fields': fields, 'unchanged_fields': [field for field in QUESTIONS if field not in fields],
               'redacted_fields': redactions, 'missing_categories': sorted(CATEGORIES.keys() - counts.keys())}
    return {'schema_version': 1, 'splits': splits, 'summary': summary, 'dataset_sha256': checksum(splits)}


def template():
    return 'subject,message,category,group_id,urgency,complaint,churn,refund\nDuplicate charge,Please refund the extra charge.,refund,billing-1,1,false,false,true\n'
