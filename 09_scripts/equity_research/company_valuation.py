"""Explicitly admitted company models, reprojected without changing assumptions.

The research bundle remains research-only. A separate versioned admission binds
one reviewed model to production; every refresh rechecks the original evidence.
Neither admission nor a complete valuation grants shares or execution authority.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

from daily_common import canonical_sha256, read_json, read_csv, sha256_file, latest_published_market_session
from thesis_evidence import _inside, validate_store as validate_theses, STORE_REL as THESIS_REL
from valuation_input_bundle import validate_and_materialize_bundle, _verified_source

POLICY_REL = '01_policies/company_valuation_admission.json'
STORE_REL = '04_data/equity_research/company_valuation_admissions.local.json'
REPORT_REL = '04_data/equity_research/company_valuation_admission_status.local.json'
OBSERVATIONS_REL = '04_data/equity_research/company_valuation_observations.local'
SCHEMA = 'equity_company_valuation_admissions_v1'
RECORD_SCHEMA = 'equity_company_valuation_admission_v1'
FIELDS = {'schema_version', 'ticker', 'version', 'case_id', 'reviewer', 'reviewed_at',
          'next_review_at', 'supersedes_sha256', 'record_sha256', 'review_record_sha256',
          'model_relative_path', 'model_sha256', 'financial_period_end', 'fact_values',
          'method', 'horizon', 'scenario_prices', 'case_citations', 'rationale',
          'countercase', 'allocation_judgment'}
FACTS = {'diluted_shares': 'diluted_shares_latest', 'cash_and_equivalents': 'cash_latest',
         'total_debt': 'debt_latest', 'revenue_ttm': 'ttm_revenue',
         'free_cash_flow_ttm': 'ttm_free_cash_flow'}


def require(ok: bool, code: str) -> None:
    if not ok:
        raise ValueError(code)


def stamp(value) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'company_model_aware_clock_required')
    return parsed


def number(value) -> Decimal:
    try:
        require(not isinstance(value, bool), 'company_model_numeric_invalid')
        result = Decimal(str(value))
        require(result.is_finite(), 'company_model_numeric_invalid')
        return result
    except InvalidOperation as exc:
        raise ValueError('company_model_numeric_invalid') from exc


def seal(record: dict) -> dict:
    result = deepcopy(record)
    result['record_sha256'] = canonical_sha256({k: v for k, v in result.items() if k != 'record_sha256'})
    return result


def validate_store(store: dict) -> dict[str, dict]:
    require(isinstance(store, dict) and set(store) == {'schema_version', 'records'}
            and store['schema_version'] == SCHEMA and isinstance(store['records'], list),
            'company_model_store_invalid')
    latest, ids = {}, set()
    for record in store['records']:
        require(isinstance(record, dict) and set(record) == FIELDS
                and record['schema_version'] == RECORD_SCHEMA and seal(record) == record,
                'company_model_history_integrity_invalid')
        ticker = record['ticker']
        require(isinstance(ticker, str) and re.fullmatch(r'[A-Z][A-Z0-9.-]{0,14}', ticker)
                and record['case_id'] not in ids, 'company_model_identity_invalid')
        previous = latest.get(ticker)
        require(type(record['version']) is int and record['version'] == (previous['version'] + 1 if previous else 1)
                and record['supersedes_sha256'] == (previous['record_sha256'] if previous else ''),
                'company_model_version_chain_invalid')
        if previous:
            require(stamp(record['reviewed_at']) >= stamp(previous['reviewed_at']), 'company_model_clock_regression')
        latest[ticker] = record
        ids.add(record['case_id'])
    return latest


def current_views(root: Path, tickers: set[str], current: datetime) -> dict:
    from workflow_integrity import current_thesis_views
    from earnings_incorporation import read_earnings_incorporation_status
    return current_thesis_views({}, root=root, current=current,
        incorporation=read_earnings_incorporation_status(root=root, now=current),
        candidate_tickers=tickers)


def pointer_value(document, pointer: str):
    require(isinstance(pointer, str) and pointer.startswith('/'), 'company_model_case_pointer_invalid')
    parent = None
    for token in pointer.split('/')[1:]:
        parent = document
        token = token.replace('~1', '/').replace('~0', '~')
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document, parent


def validate_record(record: dict, *, root: Path, current: datetime, view: dict,
                    fact: dict, quote: dict, policy: dict) -> dict:
    """Return verified immutable prices; reject each issuer independently."""
    require(set(record) == FIELDS and seal(record) == record and record['schema_version'] == RECORD_SCHEMA,
            'company_model_record_invalid')
    require(policy.get('schema_version') == 'equity_company_valuation_policy_v1'
            and policy.get('enabled') is True and policy.get('owner_authorized_on') == '2026-10-12',
            'company_model_route_not_adopted')
    require(current.date().isoformat() >= policy['owner_authorized_on'], 'company_model_policy_not_yet_effective')
    require(policy.get('immutable_assumptions') is True
            and all(policy.get(k) is False for k in ('automatic_action_allowed', 'broker_connected', 'trade_placed')),
            'company_model_authority_boundary_invalid')
    reviewed, due = stamp(record['reviewed_at']), stamp(record['next_review_at'])
    require(reviewed <= current < due and 0 < (due - reviewed).total_seconds() <= 31 * 86400,
            'company_model_review_due_or_clock_invalid')
    for key in ('case_id', 'reviewer', 'method', 'horizon', 'rationale', 'countercase', 'allocation_judgment'):
        require(isinstance(record[key], str) and len(record[key].strip()) >= 8, 'company_model_text_missing:' + key)
    from workflow_integrity import company_review_complete
    require(company_review_complete(view), 'company_model_company_review_not_current:' +
            ','.join(view.get('reopen_reasons', []) + view.get('validation_errors', [])))
    thesis = view['review_record']
    require(thesis['ticker'] == record['ticker'], 'company_model_ticker_mismatch')
    require(thesis['record_sha256'] == record['review_record_sha256'], 'company_model_thesis_version_changed')
    require(due <= stamp(thesis['next_review_at']), 'company_model_outlives_company_review')
    model = thesis['valuation_model']
    require(model['relative_path'] == record['model_relative_path'] and model['sha256'] == record['model_sha256'],
            'company_model_reviewed_model_mismatch')
    path = _inside(root, record['model_relative_path'])
    require(record['model_relative_path'].startswith('04_data/equity_research/')
            and sha256_file(path) == record['model_sha256'], 'company_model_original_changed')
    bundle = read_json(path)
    receipts, _ = validate_and_materialize_bundle(bundle, packet_as_of=thesis['reviewed_at'],
                                                  active_tickers={record['ticker']}, project_root=root)
    require(len(receipts) == 1 and receipts[0]['sufficiency']['valuation_sufficient'], 'company_model_inputs_incomplete')
    original = next(r for r in bundle['records'] if r['ticker'] == record['ticker'])
    inputs = original['inputs']
    period = record['financial_period_end']
    require(period == thesis['financial_period_end'] == fact.get('latest_period_end') == fact.get('ttm_period_end'),
            'company_model_financial_period_changed')
    require(fact.get('data_quality') == 'ok' and fact.get('valuation_input_quality') == 'complete'
            and fact.get('selection_version') == 'period_bound_companyfacts_v2', 'company_model_financial_selection_incomplete')
    require(set(record['fact_values']) == set(FACTS), 'company_model_fact_binding_missing')
    for name, field in FACTS.items():
        require(number(inputs[name]['value']) == number(record['fact_values'][name]) == number(fact.get(field)),
                'company_model_financial_value_changed:' + name)
    # Reuse the existing strict current canonical financial provenance gate.
    from refresh_valuation_scenarios import valuation_input_issues
    issues = valuation_input_issues(fact, quote, current.isoformat())
    require(not issues, 'company_model_current_inputs_unverified:' + ','.join(issues))
    require(quote.get('data_quality_label') == 'ok' and quote.get('market_session_date') ==
            latest_published_market_session(current).isoformat(), 'company_model_current_quote_unverified')
    require(stamp(quote['data_timestamp']) <= current, 'company_model_future_quote')
    require(set(record['scenario_prices']) == set(record['case_citations']) == {'bear', 'base', 'bull'},
            'company_model_three_cases_required')
    prices = {k: number(v) for k, v in record['scenario_prices'].items()}
    require(Decimal(0) <= prices['bear'] < prices['base'] <= prices['bull'], 'company_model_price_order_invalid')
    require(abs(prices['bear'] - number(inputs['downside_price_assumption']['value'])) <= Decimal('.01')
            and abs(prices['base'] - number(inputs['target_price_assumption']['value'])) <= Decimal('.01'),
            'company_model_reviewed_prices_changed')
    sources = {s['source_id']: s for s in original['sources']}
    for case, citation in record['case_citations'].items():
        require(isinstance(citation, dict) and set(citation) == {'source_id', 'json_pointer'}, 'company_model_case_citation_invalid')
        source = sources[citation['source_id']]
        require(source['source_type'] == 'human_valuation_scenario', 'company_model_case_not_authored')
        verified_source, _ = _verified_source(source, ticker=record['ticker'], packet_as_of=stamp(thesis['reviewed_at']), project_root=root)
        value, parent = pointer_value(json.loads(verified_source['excerpt_text']), citation['json_pointer'])
        require(isinstance(parent, dict) and parent.get('case') == case
                and abs(number(value) - prices[case]) <= Decimal('.01'), 'company_model_case_source_mismatch:' + case)
    return {'prices': prices, 'thesis': thesis, 'original': original}


def append(store: dict, record: dict, *, root: Path, current: datetime) -> dict:
    validate_store(store)
    updated = deepcopy(store)
    updated['records'].append(record)
    validate_store(updated)
    facts = {r['ticker']: r for r in read_csv(root/'03_source_data/equity_research/daily_fundamentals.csv')}
    quotes = {r['ticker']: r for r in read_csv(root/'03_source_data/equity_research/market_data_snapshot.csv')}
    coverage = {r['ticker']: r for r in read_csv(root/'04_research/company_research/current_research_baseline.csv')}
    require(record['ticker'] in coverage and coverage[record['ticker']].get('research_role')
            not in {'etf_research_candidate', 'core_allocation_candidate'}, 'company_model_operating_company_required')
    validate_record(record, root=root, current=current,
        view=current_views(root, {record['ticker']}, current)[record['ticker']],
        fact=facts.get(record['ticker'], {}), quote=quotes.get(record['ticker'], {}), policy=read_json(root/POLICY_REL))
    return updated


def apply_company_models(*, root: Path, scenarios: list[dict], baseline: list[dict],
                         fundamentals: dict, market: dict, current: datetime) -> tuple[list[dict], dict]:
    """Replace only explicitly opted-in models; never fall back on failed opt-ins."""
    report = {'schema_version': 'equity_company_valuation_projection_v1', 'generated_at': current.isoformat(),
              'status': 'absent', 'records': [], 'automatic_action_allowed': False}
    path = root/STORE_REL
    if not path.exists():
        return scenarios, report
    try:
        latest = validate_store(read_json(path))
        policy = read_json(root/POLICY_REL)
        views = current_views(root, set(latest), current)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # A broken shared ledger has no trustworthy issuer scope; fail all
        # company projections while preserving their baseline comparisons.
        latest = {r['ticker']: {} for r in scenarios}
        policy, views = {}, {}
        report['shared_failure'] = str(exc)
    by_ticker = {r['ticker']: deepcopy(r) for r in scenarios}
    rows = {r['ticker']: r for r in baseline}
    report.update(status='ok', store_sha256=sha256_file(path),
                  policy_sha256=sha256_file(root/POLICY_REL) if (root/POLICY_REL).is_file() else '')
    for ticker, record in latest.items():
        if ticker not in rows:
            report['records'].append({'ticker': ticker, 'status': 'outside_current_coverage'})
            continue
        comparator = deepcopy(by_ticker.get(ticker, {}))
        try:
            require(rows[ticker].get('research_role') not in {'etf_research_candidate', 'core_allocation_candidate'},
                    'company_model_operating_company_required')
            verified = validate_record(record, root=root, current=current, view=views.get(ticker, {}),
                fact=fundamentals.get(ticker, {}), quote=market.get(ticker, {}), policy=policy)
            prices = verified['prices']
            price = number(market[ticker]['last_price'])
            ratio = max(Decimal(0), prices['base'] - price) / max(Decimal('.01'), price - prices['bear']) if prices['bear'] < price else Decimal(99)
            upside = (prices['base']/price-1)*100
            score = 9 if price <= prices['bear'] else 7 if price <= prices['base'] else 5 if price <= prices['bull'] else 3
            proof = {'case_id': record['case_id'], 'version': record['version'], 'record_sha256': record['record_sha256'],
                     'model_sha256': record['model_sha256'], 'review_record_sha256': record['review_record_sha256'],
                     'policy_sha256': report['policy_sha256'], 'financial_period_end': record['financial_period_end'],
                     'current_quote_sha256': canonical_sha256(market[ticker]), 'immutable_assumptions': True}
            by_ticker[ticker] = {'ticker': ticker, 'status': 'complete', 'as_of_market_session': market[ticker]['market_session_date'],
                'current_price': float(price), 'scenario_prices': {k: float(v) for k,v in prices.items()},
                'expected_upside_pct': round(float(upside), 2), 'base_scenario_gap_pct': round(float(upside), 2),
                'bear_downside_pct': round(float((prices['bear']/price-1)*100), 2), 'reward_to_risk': round(float(ratio), 2),
                'valuation_score_0_to_10': score, 'company_model_admission': proof, 'policy_comparator': comparator,
                'metric_interpretation': {'method_status': 'admitted_source_bound_company_model', 'method': record['method'],
                    'horizon': record['horizon'], 'expected_upside_pct': 'base_scenario_gap_not_probability_weighted_expected_return',
                    'reward_to_risk': 'scenario_distance_ratio_not_calibrated_expected_payoff', 'scenario_probabilities': 'not_estimated'},
                'fundamental_source_url': fundamentals[ticker].get('source_url', ''),
                'strongest_positive_evidence': record['rationale'], 'strongest_negative_evidence': record['countercase'],
                'allocation_judgment': record['allocation_judgment'], 'automatic_action_allowed': False}
            rows[ticker]['valuation_reasonableness_score'] = str(score)
            rows[ticker]['valuation_check'] = f"admitted_company_model:{record['case_id']}; bear/base/bull=" + '/'.join(str(prices[k]) for k in ('bear','base','bull'))
            report['records'].append({'ticker': ticker, 'status': 'admitted_current', **proof})
        except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            code = 'company_model_admission_unverified:' + str(exc)
            by_ticker[ticker] = {'ticker': ticker, 'status': 'insufficient', 'missing_inputs': [],
                'input_limitations': [code], 'policy_comparator': comparator, 'automatic_action_allowed': False}
            rows[ticker]['valuation_reasonableness_score'] = '2.0'
            rows[ticker]['valuation_check'] = code
            report['records'].append({'ticker': ticker, 'status': 'unverified', 'reason': str(exc)})
            report['status'] = 'degraded'
    return list(by_ticker.values()), report


def retain_observations(*, root: Path, scenarios: list[dict], report: dict, current: datetime) -> None:
    """Retain same-close comparisons, including failed/expired opted-in cases.

    Observations are input-identical deduplicated snapshots, never backdated
    trades, fills, net returns or independent performance trials.
    """
    from daily_common import atomic_write_json
    records = {r['ticker']: r for r in scenarios}
    history = root/OBSERVATIONS_REL
    for admission in report['records']:
        row = records.get(admission['ticker'], {})
        if admission['status'] == 'outside_current_coverage':
            continue
        payload = {'schema_version': 'equity_company_valuation_observation_v1',
            'admission': admission, 'admission_store_sha256': report.get('store_sha256'),
            'policy_sha256': report.get('policy_sha256'), 'projection': row,
            'costs_and_execution': 'no assumed trade; later manual drafts use existing cost and whole-share rules',
            'performance_evidence': 'not_established', 'automatic_action_allowed': False}
        identity = canonical_sha256(payload)
        path = history/(identity+'.json')
        if path.exists():
            old = read_json(path)
            require(old.get('observation_sha256') == identity
                    and {k: v for k, v in old.items() if k not in {'observed_at', 'observation_sha256'}} == payload,
                    'company_model_observation_history_invalid')
        else:
            atomic_write_json(path, {**payload, 'observed_at': current.isoformat(), 'observation_sha256': identity})


def template(root: Path, ticker: str, current: datetime) -> dict:
    thesis = validate_theses(read_json(root/THESIS_REL))[ticker]
    latest = validate_store(read_json(root/STORE_REL, {'schema_version': SCHEMA, 'records': []})).get(ticker)
    model = thesis['valuation_model']
    inputs = next(r for r in read_json(root/model['relative_path'])['records'] if r['ticker'] == ticker)['inputs']
    return {'schema_version': RECORD_SCHEMA, 'ticker': ticker, 'version': latest['version']+1 if latest else 1,
        'case_id': '', 'reviewer': '', 'reviewed_at': current.isoformat(), 'next_review_at': thesis['next_review_at'],
        'supersedes_sha256': latest['record_sha256'] if latest else '', 'record_sha256': '',
        'review_record_sha256': thesis['record_sha256'], 'model_relative_path': model['relative_path'],
        'model_sha256': model['sha256'], 'financial_period_end': thesis['financial_period_end'],
        'fact_values': {k: inputs[k]['value'] for k in FACTS}, 'method': '', 'horizon': '',
        'scenario_prices': {'bear': inputs['downside_price_assumption']['value'], 'base': inputs['target_price_assumption']['value'], 'bull': ''},
        'case_citations': {k: {'source_id': '', 'json_pointer': ''} for k in ('bear','base','bull')},
        'rationale': model['assumptions_reason'], 'countercase': model['countercase_reason'], 'allocation_judgment': ''}


def compose_admitted_inputs(bundle: dict, scenarios: list[dict], *, root: Path, market: dict) -> dict:
    """Publish current-price packet evidence for the same admitted models.

    Original bundle bytes and scenario sources stay unchanged. Only the derived
    price observation is replaced with its actual current canonical row. Failed
    opt-ins remove their generic receipt so it cannot masquerade as this case.
    """
    from valuation_input_bundle import seal_bundle
    from refresh_valuation_scenarios import line_excerpt, utc_text
    records = {r['ticker']: deepcopy(r) for r in bundle['records']}
    for scenario in scenarios:
        ticker = scenario['ticker']
        proof = scenario.get('company_model_admission')
        if not proof:
            if any(str(x).startswith('company_model_admission_unverified:') for x in scenario.get('input_limitations', [])):
                records.pop(ticker, None)
            continue
        admitted = next(r for r in validate_store(read_json(root/STORE_REL)).values()
                        if r['record_sha256'] == proof['record_sha256'])
        path = _inside(root, admitted['model_relative_path'])
        require(sha256_file(path) == proof['model_sha256'], 'company_model_changed_during_composition')
        original = deepcopy(next(r for r in read_json(path)['records'] if r['ticker'] == ticker))
        original['sources'] = [s for s in original['sources'] if s['source_type'] != 'public_market_valuation_observation']
        relative = '03_source_data/equity_research/market_data_snapshot.csv'
        start, end, text = line_excerpt(root/relative, ticker)
        sid = f"company-valuation-market:{ticker}:{proof['record_sha256']}:{market[ticker]['market_session_date']}"
        available = utc_text(market[ticker]['data_timestamp'])
        import hashlib
        original['sources'].append({'source_id': sid, 'ticker': ticker, 'source_type': 'public_market_valuation_observation',
            'accepted_at_utc': available, 'source_url': '', 'relative_path': relative, 'char_start': start, 'char_end': end,
            'content_sha256': hashlib.sha256(text.encode()).hexdigest(), 'field': 'last_price', 'authority': 'secondary_public_market_context'})
        original['inputs']['share_price'] = {'value': market[ticker]['last_price'], 'unit': 'USD_per_share',
            'period': market[ticker]['market_session_date'], 'available_at_utc': available, 'source_ids': [sid], 'evidence_kind': 'observation'}
        records[ticker] = original
    return seal_bundle({**bundle, 'records': list(records.values())})
