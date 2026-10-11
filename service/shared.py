"""Explicit repository-service access to shared intake and ticket contracts."""
from pathlib import Path
import sys

BACKEND = Path(__file__).resolve().parents[1] / 'backend'
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from classification import paired_summary  # noqa: E402
from domain import empty_run  # noqa: E402
from intake_sources import api_rows, parse_csv, parse_eml, zendesk_rows  # noqa: E402
from ticket_import import normalize_row, row_key, batch_digest, classify_rows, parse_excel, template_bytes, ImportError as IntakeError  # noqa: E402

__all__ = ['paired_summary', 'empty_run', 'api_rows', 'parse_csv', 'parse_eml', 'zendesk_rows', 'normalize_row', 'row_key', 'batch_digest', 'classify_rows', 'parse_excel', 'template_bytes', 'IntakeError']
