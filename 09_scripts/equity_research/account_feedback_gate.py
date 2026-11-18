"""Fail-closed publication barrier for unresolved owner-reported facts."""
import json
from pathlib import Path
import re
from uuid import UUID

RELATIVE = '06_execution_records/dashboard_feedback_pending.local.json'
LEGACY_SCHEMA = 'equity_dashboard_pending_v1'
SCHEMA = 'equity_dashboard_pending_v2'
LOCAL_SCOPE_KIND = 'single_ticker_fill'
UNRESOLVED = 'reported_account_feedback_unresolved'
INVALID = 'reported_account_feedback_invalid'


def feedback_scope(root: Path) -> tuple[str | None, set[str] | None]:
    """Keep a capital barrier and identify safely separable pending fills."""
    path = root / RELATIVE
    if not path.exists() and not path.is_symlink():
        return None, None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            raise ValueError('invalid_feedback_input')
        value = json.loads(path.read_text())
        if value.get('schema_version') not in {LEGACY_SCHEMA, SCHEMA} or not isinstance(value.get('records'), list):
            raise ValueError('invalid_feedback_schema')
    except (OSError, ValueError, AttributeError, TypeError):
        return INVALID, None
    records = value['records']
    if not records:
        return None, None

    # Legacy pending indexes cannot certify scope. The typed coordinator
    # projection supplies the exact source-bound record identity and semantics.
    if value['schema_version'] == LEGACY_SCHEMA:
        return UNRESOLVED, None
    tickers, identities = set(), set()
    broad = False
    for row in records:
        if (not isinstance(row, dict) or set(row) != {'id', 'ticker', 'stage', 'missing', 'revision', 'record_sha256', 'scope'}
                or not isinstance(row['id'], str)
                or not isinstance(row['ticker'], str) or row['stage'] not in ('pending', 'applying', 'recovery_conflict')
                or type(row['revision']) is not int or row['revision'] < 1
                or not isinstance(row['record_sha256'], str) or re.fullmatch(r'[a-f0-9]{64}', row['record_sha256']) is None
                or not isinstance(row['missing'], list) or any(not isinstance(item, str) for item in row['missing'])):
            return INVALID, None
        try:
            identity = UUID(row['id'])
        except ValueError:
            return INVALID, None
        if identity in identities:
            return INVALID, None
        identities.add(identity)
        scope = row['scope']
        if scope is None:
            broad = True
        elif (not isinstance(scope, dict) or set(scope) != {'kind', 'side', 'status'}
                or scope['kind'] != LOCAL_SCOPE_KIND or scope['side'] not in ('buy', 'sell')
                or scope['status'] not in ('filled', 'partial') or row['stage'] != 'pending' or not row['missing']
                or re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,11}', row['ticker']) is None):
            return INVALID, None
        else:
            tickers.add(row['ticker'])
    return UNRESOLVED, None if broad else tickers


def feedback_blocker(root: Path):
    return feedback_scope(root)[0]
