"""Keep outcome prices for unfinished observations outside current coverage.

These prices never enter the canonical universe, scoring or new experiment
capture. The existing public market collector supplies normalized, dated
observation receipts; unavailable series remain explicit missing evidence.
"""
from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
import re

from daily_common import atomic_write_json, canonical_sha256, latest_published_market_session

PATH = Path('03_source_data/equity_research/momentum_outcome_prices.local.json')
LEDGER = Path('08_reviews/momentum_experiment.local/ledger.jsonl')
SCHEMA = 'equity_momentum_outcome_prices_v1'


def pending_outside_coverage(root, canonical_tickers, current):
    from momentum_experiment import validate_chain
    path = root / LEDGER
    raw = path.read_bytes() if path.exists() else b''
    records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    validate_chain(records, current)
    done = {row['observation_id'] for row in records if row['kind'] == 'outcome'}
    pending = [row for row in records if row['kind'] == 'observation'
               and row['observation_id'] not in done and row['ticker'] not in canonical_tickers]
    tickers = sorted({row['ticker'] for row in pending})
    if len(tickers) > 60 or any(re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', t) is None for t in tickers):
        raise ValueError('experiment_outcome_coverage_scope_invalid')
    return tickers, pending, hashlib.sha256(raw).hexdigest()


def collect_outcome_prices(root, canonical_tickers, current, fetch):
    """At most one existing-provider fetch per retired, unfinished ticker.

    Called only by the network-enabled market collector. Reuse mode never
    calls this function. fetch returns (verified market row, history, reason).
    """
    tickers, pending, ledger_digest = pending_outside_coverage(root, set(canonical_tickers), current)
    session = latest_published_market_session(current).isoformat()
    path = root / PATH
    previous = json.loads(path.read_bytes()) if path.exists() else None
    reusable = (previous is not None and previous.get('schema_version') == SCHEMA
                and previous.get('market_session') == session
                and previous.get('automatic_action_allowed') is False
                and canonical_sha256(previous.get('market', [])) == previous.get('market_sha256'))
    previous_rows = {r['ticker']: r for r in previous['market']} if reusable else {}
    previous_series = previous.get('history', {}).get('tickers', {}) if reusable else {}
    market, series, failures = [], {}, {}
    for ticker in tickers:
        if ticker in previous_rows and ticker in previous_series:
            row, bars, reason = previous_rows[ticker], previous_series[ticker], 'none'
        else:
            row, bars, reason = fetch(ticker)
        if reason == 'none' and row is not None and bars is not None:
            market.append(row)
            series[ticker] = bars
        else:
            failures[ticker] = reason
    digest = canonical_sha256(market)
    receipt = {'schema_version': SCHEMA, 'scope': 'outcomes_only_no_capture_or_candidate_admission',
        'automatic_action_allowed': False, 'canonical_effect': False,
        'generated_at': current.isoformat(), 'market_session': session,
        'ledger_sha256_at_request': ledger_digest,
        'observation_ids': [r['observation_id'] for r in pending],
        'requested_tickers': tickers, 'missing': failures,
        'snapshot_format': 'canonical_json_market_rows', 'market_sha256': digest, 'market': market,
        'history': {'schema_version': 'phase5r_tactical_price_history_v1', 'validated': True,
            'data_source': 'massive_stocks_basic_eod', 'generated_at': current.isoformat(),
            'market_session': session, 'snapshot_sha256': digest, 'tickers': series},
        'evidence_kind': 'normalized_public_provider_observation_receipt_not_original_response_bytes'}
    atomic_write_json(path, receipt)
    return receipt


def load_outcome_prices(raw, current):
    value = json.loads(raw)
    market, history = value.get('market'), value.get('history')
    if (value.get('schema_version') != SCHEMA or value.get('canonical_effect') is not False
            or value.get('automatic_action_allowed') is not False
            or value.get('scope') != 'outcomes_only_no_capture_or_candidate_admission'
            or value.get('snapshot_format') != 'canonical_json_market_rows'
            or not isinstance(market, list) or not isinstance(history, dict)
            or canonical_sha256(market) != value.get('market_sha256')
            or history.get('snapshot_sha256') != value['market_sha256']
            or history.get('market_session') != value.get('market_session')
            or len({r.get('ticker') for r in market}) != len(market)
            or set(history.get('tickers', {})) != {r.get('ticker') for r in market}):
        raise ValueError('experiment_outcome_coverage_invalid')
    observed = date.fromisoformat(value['market_session'])
    expected = latest_published_market_session(current)
    if observed > expected:
        raise ValueError('experiment_outcome_coverage_invalid')
    return value, observed == expected
