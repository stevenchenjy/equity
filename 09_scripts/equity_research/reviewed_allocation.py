"""Source-bound company allocation judgments; no inferred size from volatility.

The owner removed fixed per-name percentage caps. A reviewed target is an
analyst judgment, bounded by shared capital, aggregate stock exposure and the
core minimum. It is not execution authority or experiment promotion.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
import math


def validate_allocation(row: dict) -> None:
    value = row.get('reviewed_allocation')
    if value is None:
        return
    from investment_plans import _bound_sources, _required_text, stamp
    if row.get('role') != 'long_term_growth' or row.get('strategy_horizon') != 'long_term_growth':
        raise ValueError('allocation_requires_long_term_growth_purpose')
    _required_text(value, ('rationale', 'downside_case', 'portfolio_overlap', 'alternatives', 'reviewed_at'), 'allocation_review')
    _bound_sources(value, row, 'allocation_review')
    for key in ('target_position_pct', 'maximum_entry_price', 'invalidation_price', 'reassessment_price'):
        if type(value.get(key)) not in (int, float) or not math.isfinite(value[key]):
            raise ValueError('allocation_numeric_invalid:' + key)
    if not 0 < value['target_position_pct'] <= 100:
        raise ValueError('allocation_target_invalid')
    if not 0 < value['invalidation_price'] < value['maximum_entry_price'] < value['reassessment_price']:
        raise ValueError('allocation_price_order_invalid')
    if stamp(value['reviewed_at']) > stamp(row['recorded_at']):
        raise ValueError('allocation_review_after_recording')
    if not row.get('valid_until') or stamp(row['valid_until']) <= stamp(row['recorded_at']):
        raise ValueError('allocation_bounded_validity_required')


def current_allocations(root: Path, current: datetime) -> dict[str, dict]:
    from daily_common import read_json
    from investment_plans import RELATIVE_PATH, validate_ledger, stamp
    payload = read_json(root / RELATIVE_PATH, {})
    if not payload:
        return {}
    try:
        latest = validate_ledger(payload, root=root)
    except (ValueError, OSError, KeyError):
        return {}  # Existing plan diagnostics carry the integrity failure.
    result = {}
    active_counts = {}
    from investment_plans import TERMINAL
    for row in latest.values():
        if row['state'] not in TERMINAL:
            active_counts[row['ticker']] = active_counts.get(row['ticker'], 0) + 1
    for row in latest.values():
        if (row.get('reviewed_allocation') and row['state'] == 'maintained'
                and row.get('setup_status') not in {'failed', 'expired', 'unverified'}
                and active_counts.get(row['ticker']) == 1
                and stamp(row['recorded_at']) <= current
                and stamp(row['effective_at']) <= current < min(stamp(row['review_at']), stamp(row['valid_until']))):
            result[row['ticker']] = row
    return result
