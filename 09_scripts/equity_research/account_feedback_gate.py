"""Fail-closed publication barrier for unresolved owner-reported facts."""
import json
from pathlib import Path

RELATIVE = '06_execution_records/dashboard_feedback_pending.local.json'


def feedback_blocker(root: Path):
    path=root/RELATIVE
    if not path.exists() and not path.is_symlink(): return None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>2_000_000: raise ValueError('invalid_feedback_input')
        value=json.loads(path.read_text())
        if value.get('schema_version')!='equity_dashboard_pending_v1' or not isinstance(value.get('records'),list): raise ValueError('invalid_feedback_schema')
        return 'reported_account_feedback_unresolved' if value['records'] else None
    except (OSError,ValueError,AttributeError): return 'reported_account_feedback_invalid'
