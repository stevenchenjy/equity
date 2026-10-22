"""Purpose-bound daily briefs and explicit action/research-priority alerts.

This contract does not create investment eligibility, alter account facts or send
mail. Callers retain the existing publication, delivery and execution fences.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
import hashlib
import html
import json
from pathlib import Path
import re

from daily_common import (ET, ExclusiveFileLock, atomic_write_json, canonical_sha256,
    is_us_market_session_date, read_json, sha256_file)
from investment_plans import regular_close
from opportunity_contract import AUTHORITY, inside, require, validate_receipts
from workflow_evaluation import aware

CONFIG_REL = Path('00_project_control/active_production_config.json')
STORE_REL = Path('04_research/company_research/priority_reviews.local.json')
PRIORITY_STORE_REL = STORE_REL
PRIORITY_BASE = Path('04_research/company_research/priority_reviews.local')
DECISION_REL = Path('04_research/company_research/daily_decision.json')
ARCHIVE_REL = Path('07_automation/email_delivery/sent_decisions.local')
REFRESH_REL = Path('00_project_control/run_logs/daily_refresh_state.local.json')
PURPOSE_MARKER = 'delivery_purpose_v1='
MEANING_MARKER = 'action_priority_v1='
HEX = re.compile(r'[a-f0-9]{64}')
TICKER = re.compile(r'[A-Z][A-Z0-9.\-]{0,9}')
MODES = {'scheduled_brief', 'intraday_alert'}
PRIORITY_INPUTS = (
    '03_source_data/equity_research/market_data_snapshot.csv',
    '05_risk_and_positions/current_account_state.local.json',
    '05_risk_and_positions/current_positions.local.csv',
    '05_risk_and_positions/current_open_orders.local.json',
    '05_risk_and_positions/investment_plans.local.json',
    '04_research/company_research/thesis_dossiers.local.json',
    '04_data/equity_research/valuation_research_inputs.local.json',
    '04_data/equity_research/company_valuation_admissions.local.json',
    '03_source_data/equity_research/official_news_events.local.json',
    '03_source_data/equity_research/official_news_status.local.json',
    '03_source_data/equity_research/earnings_events.local.json',
    '03_source_data/equity_research/earnings_events_status.local.json',
)
REQUIRED_PRIORITY_INPUTS = set(PRIORITY_INPUTS[:6])
CLOCK_CODES = {'review_due', 'scheduled_company_review_due', 'company_model_requires_reassessment',
    'company_review_requires_reassessment', 'maintained_company_research_incomplete',
    'order_snapshot_requires_recheck', 'expired_pending_verification', 'time_exit_due_pending_verification'}


def _text(value, maximum=1600):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum,
        'priority_review_text_invalid')
    return ' '.join(value.split())


def delivery_policy_context(root: Path) -> dict:
    n = read_json(root / CONFIG_REL, {}).get('notifications', {})
    p = {'effective_from': n.get('delivery_assessment_effective_from'),
        'mandatory_daily_briefs': n.get('mandatory_daily_briefs') is True,
        'intraday_alerts_enabled': n.get('intraday_alerts_enabled') is True}
    return {'schema_version': 'equity_assessment_delivery_policy_v1', **p,
        'policy_sha256': canonical_sha256(p)}


def _source_meaning(relative: str, raw: bytes, *, root: Path, current: datetime):
    """Ignore only explicitly named collection clocks, never economic fields."""
    if relative.endswith('official_news_events.local.json'):
        value = json.loads(raw)
        return {'schema_version': value.get('schema_version'),
            'events': [{k: v for k, v in e.items() if k != 'last_seen_at'} for e in value.get('events', [])]}
    if relative.endswith('official_news_status.local.json'):
        value = json.loads(raw)
        keys = ('source_id', 'ticker', 'required', 'last_attempt_status', 'reason',
            'observed_event_count')
        events_path = root / '03_source_data/equity_research/official_news_events.local.json'
        require(events_path.is_file() and value.get('events_sha256') == canonical_sha256(read_json(events_path)),
            'priority_news_current_events_unverified')
        return {'manifest_sha256': value.get('manifest_sha256'),
            'sources': [{k: e.get(k) for k in keys} for e in value.get('sources', [])]}
    if relative.endswith('earnings_events.local.json'):
        # The index contains immutable scan references, not inline date rows.
        # Validate their source bytes before comparing the latest logical row
        # for each date; an identical repoll must not invalidate a review.
        from earnings_events import validated_scans
        dates = {}
        for scan in validated_scans(root, current=current):
            for row in scan.get('dates', []):
                dates[row['date']] = {**{k: row.get(k) for k in ('status', 'reason', 'quarantine')},
                    'events': _calendar_priority_events(row.get('events', []))}
        return {'schema_version': json.loads(raw).get('schema_version'), 'latest_dates': dates}
    if relative.endswith('earnings_events_status.local.json'):
        value = json.loads(raw)
        coverage = value.get('coverage', {})
        return {'status': value.get('status'),
            'coverage': {k: coverage.get(k) for k in ('status', 'scope', 'horizon_start', 'horizon_end',
                'days_requested', 'days_verified', 'failed_dates', 'full_market_coverage', 'issuer_confirmation')},
            'events': _calendar_priority_events(value.get('events', []),
                ignore={'last_observed_at', 'sources'})}
    return hashlib.sha256(raw).hexdigest()


def _calendar_priority_events(events: list, *, ignore=frozenset()) -> list:
    """Ignore provider ordering only after validated_scans checks original rows.

    row_sha256 remains effective: changes to market cap, earnings expectations,
    estimate count or any other original company field require reassessment.
    Quarantined rows and actual schedule/review state are not normalized away.
    """
    return sorted([{k: v for k, v in event.items() if k not in {'row_index', *ignore}}
        for event in events], key=lambda event: (str(event.get('event_id')), canonical_sha256(event)))


def priority_input_bindings(root: Path, *, current: datetime) -> dict:
    result = {}
    for relative in PRIORITY_INPUTS:
        path = root / relative
        if not path.is_file():
            require(relative not in REQUIRED_PRIORITY_INPUTS, 'priority_current_input_missing')
            result[relative] = None
            continue
        raw = path.read_bytes()
        result[relative] = {'sha256': hashlib.sha256(raw).hexdigest(),
            'meaning_sha256': canonical_sha256(_source_meaning(relative, raw, root=root, current=current))}
    return result


def _bindings_meaning(bindings):
    return {path: value['meaning_sha256'] if value else None for path, value in bindings.items()}


def _priority_meaning(entries):
    return [{'ticker': e['ticker'], 'reason': ' '.join(e['reason'].split()),
        'next_step': ' '.join(e['next_step'].split())} for e in entries]


def _priority_store(root: Path, current: datetime) -> dict:
    value = read_json(root / STORE_REL, {'schema_version': 'equity_priority_review_store_v1',
        'records': [], **AUTHORITY})
    require(value.get('schema_version') == 'equity_priority_review_store_v1'
        and all(value.get(k) is False for k in AUTHORITY), 'priority_store_invalid')
    previous, last = '', None
    for version, record in enumerate(value.get('records', []), 1):
        stamp = aware(record['recorded_at'])
        require(record['version'] == version and record['previous_hash'] == previous
            and record['record_sha256'] == canonical_sha256({k: v for k, v in record.items() if k != 'record_sha256'})
            and (last is None or last <= stamp) and stamp <= current
            and all(record.get(k) is False for k in AUTHORITY), 'priority_history_invalid')
        require(aware(record['reviewed_at']) <= stamp, 'priority_history_clock_invalid')
        for entry in record['entries']:
            validate_receipts(entry['sources'], root=root, current=aware(record['reviewed_at']))
        previous, last = record['record_sha256'], stamp
    return value


def validate_priority_proposal(root: Path, proposal: dict, *, current: datetime) -> dict:
    require(proposal.get('schema_version') == 'equity_research_priority_review_v1'
        and all(proposal.get(k) is False for k in AUTHORITY), 'priority_proposal_authority_invalid')
    reviewed, next_review = aware(proposal['reviewed_at']), aware(proposal['next_review_at'])
    require(reviewed <= current < next_review <= reviewed + timedelta(hours=48), 'priority_review_clock_invalid')
    _text(proposal.get('reviewer'), 160)
    require(proposal.get('change_basis') in {'new_primary_evidence', 'completed_analysis', 'risk_reassessment',
        'source_bound_event_change', 'unchanged_review'}, 'priority_review_basis_invalid')
    _text(proposal.get('review_summary'))
    entries = proposal.get('entries')
    require(isinstance(entries, list) and 1 <= len(entries) <= 3, 'priority_review_entries_invalid')
    require(len({e.get('ticker') for e in entries}) == len(entries), 'priority_review_duplicate_ticker')
    for entry in entries:
        require(TICKER.fullmatch(str(entry.get('ticker', ''))), 'priority_review_ticker_invalid')
        _text(entry.get('reason')); _text(entry.get('next_step'))
        validate_receipts(entry.get('sources'), root=root, current=reviewed)
    require(HEX.fullmatch(str(proposal.get('basis_decision_sha256', '')))
        and sha256_file(root / DECISION_REL) == proposal['basis_decision_sha256'], 'priority_basis_decision_changed')
    priority_input_bindings(root, current=current)
    return proposal


def _retain(root: Path, source: dict) -> dict:
    raw = inside(root, source['path']).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    require(digest == source['sha256'], 'priority_source_changed_before_admission')
    path = PRIORITY_BASE / 'inputs' / digest
    dest = root / path
    if dest.exists():
        require(sha256_file(dest) == digest, 'priority_retained_source_corrupt')
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(raw); stream.flush()
            import os
            os.fsync(stream.fileno())
    return {**source, 'path': str(path), 'original_locator': source['path']}


def apply_priority_review(root: Path, proposal: dict, *, current: datetime, apply=False) -> dict:
    """Caller owns runtime/pipeline locks; this writer serializes its own store."""
    with ExclusiveFileLock(root / PRIORITY_BASE / 'store.lock'):
        old = _priority_store(root, current)
        proposal_hash = canonical_sha256(proposal)
        accepted = next((record for record in old['records'] if record.get('proposal_sha256') == proposal_hash), None)
        if accepted:
            return {'status': 'already_recorded', 'record_sha256': accepted['record_sha256'], **AUTHORITY}
        validate_priority_proposal(root, proposal, current=current)
        previous = old['records'][-1] if old['records'] else None
        if not apply:
            return {'status': 'validated', **AUTHORITY}
        record = deepcopy(proposal)
        for entry in record['entries']:
            entry['sources'] = [_retain(root, source) for source in entry['sources']]
        record.update(version=len(old['records']) + 1, previous_hash=previous['record_sha256'] if previous else '',
            recorded_at=current.isoformat(), proposal_sha256=proposal_hash,
            input_bindings=priority_input_bindings(root, current=current))
        record['record_sha256'] = canonical_sha256(record)
        new = {**deepcopy(old), 'records': [*old['records'], record]}
        require(read_json(root / STORE_REL, old) == old, 'priority_store_changed_before_publication')
        atomic_write_json(root / PRIORITY_BASE / 'history' / (record['record_sha256'] + '.json'), record)
        atomic_write_json(root / STORE_REL, new)
        return {'status': 'recorded', 'record_sha256': record['record_sha256'], 'version': record['version'], **AUTHORITY}


def priority_review_context(root: Path, current: datetime) -> dict:
    base = {'schema_version': 'equity_priority_review_context_v1', 'entries': [], **AUTHORITY}
    try:
        store = _priority_store(root, current)
        if not store['records']:
            return {**base, 'status': 'absent'}
        record = store['records'][-1]
        context = {**base, 'record_sha256': record['record_sha256'], 'version': record['version'],
            'reviewed_at': record['reviewed_at'], 'next_review_at': record['next_review_at'],
            'basis_decision_sha256': record['basis_decision_sha256'], 'change_basis': record['change_basis'],
            'review_summary': record['review_summary'], 'entries': deepcopy(record['entries']),
            'priority_meaning_sha256': canonical_sha256(_priority_meaning(record['entries']))}
        if current >= aware(record['next_review_at']):
            return {**context, 'status': 'review_due'}
        if _bindings_meaning(record['input_bindings']) != _bindings_meaning(priority_input_bindings(root, current=current)):
            return {**context, 'status': 'inputs_changed'}
        return {**context, 'status': 'current'}
    except (ValueError, KeyError, TypeError, OSError):
        return {**base, 'status': 'unverified'}


def validate_priority_context(decision: dict, *, root: Path, current: datetime) -> None:
    require(decision.get('analyst_priority_review') == priority_review_context(root, current),
        'published_priority_review_changed')


def market_session_open(current: datetime) -> bool:
    local = current.astimezone(ET)
    return (is_us_market_session_date(local.date())
        and datetime.combine(local.date(), time(9, 30), ET) <= local < regular_close(local.date().isoformat()))


def _actions(decision: dict) -> list:
    result = []
    ignored = {'account_value', 'portfolio_weight_before', 'portfolio_weight_after', 'cash_before',
        'estimated_cash_after', 'price_basis', 'cost_assumption'}
    for row in decision.get('capital_decision', {}).get('decisions', []):
        draft = row.get('order_draft')
        if not draft or row.get('decision') not in {'ACTIONABLE_BUY', 'ACTIONABLE_ADD', 'REDUCE_REVIEW', 'EXIT_REVIEW'}:
            continue
        require(float(row.get('shares', 0)) > 0, 'alert_positive_draft_quantity_missing')
        result.append({'ticker': row['ticker'], 'decision': row['decision'], 'shares': row['shares'],
            'order_draft': {k: v for k, v in draft.items() if k not in ignored},
            'strategy_source': row.get('strategy_source')})
    return sorted(result, key=lambda row: row['ticker'])


def advice_projection(decision: dict) -> dict:
    priority = decision.get('analyst_priority_review', {})
    return {'actions': _actions(decision), 'priority': _priority_meaning(priority.get('entries', []))
        if priority.get('status') == 'current' else []}


def advice_meaning_key(decision: dict) -> str:
    return MEANING_MARKER + canonical_sha256(advice_projection(decision))


def _receipt_rows(rows, current):
    from delivery_continuity import RECEIPTS
    result = []
    for index, row in enumerate(rows):
        if row.get('status') not in RECEIPTS:
            continue
        try:
            stamp = aware(row['timestamp'])
            if stamp <= current:
                result.append((stamp, index, row))
        except (ValueError, KeyError, TypeError):
            continue
    return sorted(result, key=lambda r: (r[0], r[1]))


def _attempt(row):
    digests = tuple(row.get(k, '') for k in ('decision_sha256', 'brief_text_sha256', 'brief_html_sha256'))
    if not all(HEX.fullmatch(digest) for digest in digests):
        return None
    scope = tuple(p for p in row.get('reason', '').split(';') if p.startswith((PURPOSE_MARKER, 'scheduled_slot=', 'owner_request_sha256=')))
    prefix = row.get('status', '').removesuffix('send_claimed').removesuffix('sent')
    return (prefix, *digests, scope)


def _pending_delivery(rows, current):
    receipts = _receipt_rows(rows, current)
    today = current.astimezone(ET).date()
    for index, (stamp, _, row) in enumerate(receipts):
        if stamp.astimezone(ET).date() != today and row.get('cycle_date') != today.isoformat():
            continue
        if str(row['status']).endswith('delivery_unknown'):
            return 'delivery_unknown'
        if str(row['status']).endswith('send_claimed') and not (_attempt(row) is not None and any(
            str(later['status']).endswith('sent') and _attempt(later) == _attempt(row)
            for _, _, later in receipts[index + 1:])):
            return 'send_claimed'
    return None


def _archived_receipt_baseline(row: dict, *, root: Path) -> dict:
    digest = row.get('decision_sha256', '')
    if not HEX.fullmatch(digest):
        return {'status': 'unverified', 'receipt_sha256': canonical_sha256(row)}
    try:
        raw = (root / ARCHIVE_REL / (digest + '.json')).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == digest, 'baseline_archive_hash_mismatch')
        old = json.loads(raw)
        bodies = []
        for key, suffix in (('brief_text_sha256', '.txt'), ('brief_html_sha256', '.html')):
            body_digest = row.get(key, '')
            require(HEX.fullmatch(body_digest), 'baseline_body_digest_missing')
            body = (root / ARCHIVE_REL / (body_digest + suffix)).read_bytes()
            require(hashlib.sha256(body).hexdigest() == body_digest, 'baseline_body_hash_mismatch')
            bodies.append(body.decode('utf-8'))
        if old.get('schema_version') == 'equity_mandatory_status_brief_v1':
            require(tuple(bodies) == render_failure_brief(old)[1:], 'baseline_status_render_mismatch')
            return {'status': 'status_only', 'receipt_sha256': canonical_sha256(row)}
        projection = advice_projection(old)
        if old.get('delivery_assessment'):
            validate_envelope(old)
            require(tuple(bodies) == render_intraday_alert(old)[1:], 'baseline_alert_render_mismatch')
            canonical_digest = old['delivery_assessment']['canonical_decision_sha256']
            canonical = (root / ARCHIVE_REL / (canonical_digest + '.json')).read_bytes()
            require(hashlib.sha256(canonical).hexdigest() == canonical_digest
                and canonical_sha256(json.loads(canonical)) == old['delivery_assessment']['canonical_content_sha256'],
                'baseline_alert_canonical_reference_unverified')
        else:
            from capital_presentation import action_lines
            text, document = bodies
            document_text = ' '.join(html.unescape(re.sub(r'<[^>]+>', '', document)).split())
            displayed = lambda value: value in text and ' '.join(value.split()) in document_text
            for action in projection['actions']:
                candidate = next(r for r in old['capital_decision']['decisions'] if r['ticker'] == action['ticker'])
                label = {'ACTIONABLE_BUY': 'BUY', 'ACTIONABLE_ADD': 'ADD',
                    'REDUCE_REVIEW': 'REDUCE REVIEW', 'EXIT_REVIEW': 'EXIT REVIEW'}[candidate['decision']]
                require(displayed(label + ' — ' + candidate['ticker']) and all(displayed(line) for line in action_lines(candidate)),
                    'baseline_action_not_displayed')
            if not all(displayed(entry['ticker']) and displayed(entry['reason']) and displayed(entry['next_step'])
                    for entry in projection['priority']):
                projection['priority'] = []
        return {'status': 'verified', 'receipt_sha256': canonical_sha256(row),
            'decision_sha256': digest, 'projection': projection}
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'unverified', 'receipt_sha256': canonical_sha256(row)}


def latest_receipt_baseline(rows, *, root: Path, current: datetime) -> dict:
    receipts = _receipt_rows(rows, current)
    if not receipts:
        return {'status': 'absent'}
    latest = canonical_sha256(receipts[-1][2])
    # A truthful status-only checkpoint does not retract or acknowledge any
    # prior economic advice. Verify every contiguous status archive, then use
    # the immediately preceding substantive receipt; never search all history
    # for matching advice or step past an unverified/unknown delivery.
    for index in range(len(receipts) - 1, -1, -1):
        row = receipts[index][2]
        if str(row.get('status', '')).endswith('send_claimed') and _attempt(row) is not None and any(
                str(later['status']).endswith('sent') and _attempt(later) == _attempt(row)
                for _, _, later in receipts[index + 1:]):
            continue
        if not str(row.get('status', '')).endswith('sent'):
            return {'status': 'unverified', 'receipt_sha256': latest}
        baseline = _archived_receipt_baseline(row, root=root)
        if baseline['status'] == 'status_only':
            continue
        return {**baseline, 'advice_receipt_sha256': baseline['receipt_sha256'], 'receipt_sha256': latest}
    return {'status': 'absent', 'receipt_sha256': latest}


def validate_current_publication(decision: dict, *, root: Path, current: datetime):
    from workflow_integrity import validate_published_workflow
    validate_published_workflow(decision, root=root, current=current)
    validate_priority_context(decision, root=root, current=current)


def _current_policy(decision, root, current):
    policy = delivery_policy_context(root)
    require(decision.get('assessment_delivery_policy') == policy, 'assessment_delivery_policy_changed')
    effective = policy['effective_from']
    require(isinstance(effective, str) and current.astimezone(ET).date().isoformat() >= effective,
        'assessment_delivery_not_active')
    return policy


def delivery_eligibility(decision: dict, *, root: Path, current: datetime, rows: list,
                         mode: str, scheduled_slot: str | None = None) -> dict:
    require(mode in MODES, 'assessment_delivery_mode_invalid')
    base = {'eligible': False, 'mode': mode, 'reason': '', 'meaning_key': advice_meaning_key(decision),
        'purpose_key': '', 'baseline_status': 'not_checked', 'action_changed': False,
        'priority_changed': False, 'changed_action_tickers': [], 'removed_action_tickers': [],
        'purpose_completed': False}
    try:
        policy = _current_policy(decision, root, current)
        local = current.astimezone(ET)
        require(is_us_market_session_date(local.date()), 'non_market_session')
        pending = _pending_delivery(rows, current)
        require(pending is None, 'existing_' + str(pending))
        if mode == 'scheduled_brief':
            require(policy['mandatory_daily_briefs'], 'mandatory_briefs_disabled')
            from delivery_schedule import active_delivery_window
            window = active_delivery_window(read_json(root / CONFIG_REL)['notifications'], current)
            require(window and window['id'] == scheduled_slot, 'outside_delivery_window')
            purpose = 'brief:' + local.date().isoformat() + ':' + str(scheduled_slot)
            for stamp, _, row in _receipt_rows(rows, current):
                if stamp.astimezone(ET).date() != local.date() or not str(row['status']).endswith('sent'):
                    continue
                reasons = row.get('reason', '').split(';')
                if PURPOSE_MARKER + purpose in reasons or (row.get('status') == 'sent'
                        and 'scheduled_slot=' + str(scheduled_slot) in reasons):
                    return {**base, 'purpose_key': purpose, 'purpose_completed': True,
                        'reason': 'mandatory_brief_already_sent'}
            if decision.get('schema_version') == 'equity_mandatory_status_brief_v1':
                validate_failure_brief(decision, root=root, current=current)
            else:
                validate_current_publication(decision, root=root, current=current)
            return {**base, 'eligible': True, 'purpose_key': purpose, 'reason': 'mandatory_brief_due'}
        require(policy['intraday_alerts_enabled'], 'intraday_alerts_disabled')
        require(market_session_open(current), 'outside_regular_market_session')
        require(decision.get('schema_version') != 'equity_mandatory_status_brief_v1', 'status_brief_not_action_alert')
        validate_current_publication(decision, root=root, current=current)
        baseline = latest_receipt_baseline(rows, root=root, current=current)
        if baseline['status'] != 'verified':
            return {**base, 'baseline_status': baseline['status'], 'reason': 'initial_alert_baseline_quiet'
                if baseline['status'] == 'absent' else 'latest_delivery_archive_unverified'}
        before, after = baseline['projection'], advice_projection(decision)
        old_actions = {row['ticker']: row for row in before['actions']}
        new_actions = {row['ticker']: row for row in after['actions']}
        changed = sorted(t for t, row in new_actions.items() if old_actions.get(t) != row)
        removed = sorted(set(old_actions) - set(new_actions))
        # Expiry alone is a local status update, not another action email.
        actual_rows = {row['ticker']: row for row in decision.get('capital_decision', {}).get('decisions', [])}
        removed = [t for t in removed if not set(actual_rows.get(t, {}).get('blockers', [])) <= CLOCK_CODES]
        priority_context = decision.get('analyst_priority_review', {})
        priority_changed = (priority_context.get('status') == 'current'
            and priority_context.get('change_basis') != 'unchanged_review' and before['priority'] != after['priority'])
        action_changed = bool(changed or removed)
        purpose = 'alert:' + local.date().isoformat() + ':' + base['meaning_key'].removeprefix(MEANING_MARKER) + ':' + baseline['receipt_sha256']
        return {**base, 'eligible': action_changed or priority_changed,
            'reason': 'eligible_action_or_priority_change' if action_changed or priority_changed else 'unchanged_action_and_priority',
            'purpose_key': purpose, 'baseline_status': 'verified', 'baseline_receipt_sha256': baseline['receipt_sha256'],
            'action_changed': action_changed, 'priority_changed': priority_changed,
            'changed_action_tickers': changed, 'removed_action_tickers': removed}
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return {**base, 'reason': str(exc) or 'assessment_delivery_unverified'}


def build_failure_brief(root: Path, current: datetime, scheduled_slot: str, reason: str) -> dict:
    require(scheduled_slot in {'morning', 'afternoon'}, 'status_brief_slot_invalid')
    require(isinstance(reason, str) and re.fullmatch(r'[a-zA-Z0-9_:.-]{1,180}', reason), 'status_brief_reason_invalid')
    path = root / REFRESH_REL
    raw = path.read_bytes() if path.is_file() else None
    try:
        state = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        state = {}
    cycle = current.astimezone(ET).date().isoformat()
    from delivery_schedule import delivery_window_by_id
    window = delivery_window_by_id(read_json(root / CONFIG_REL)['notifications'], scheduled_slot)
    require(window is not None, 'status_brief_window_unconfigured')
    cutoff = datetime.fromisoformat(cycle + 'T' + window['refresh_not_before']).replace(tzinfo=ET)
    try:
        started = aware(state['started_at'])
        current_attempt = state.get('cycle_date') == cycle and cutoff <= started <= current
    except (ValueError, KeyError, TypeError):
        current_attempt = False
    observed = {'path': str(REFRESH_REL), 'sha256': hashlib.sha256(raw).hexdigest() if raw else None}
    status = ('missing_current_window_handoff' if not current_attempt else
        'current_refresh_pending' if not state.get('completed_at') else
        'current_refresh_failed' if state.get('outcome') not in {'passed', 'degraded_decision_created'} else
        'current_publication_unverified')
    summary = {'missing_current_window_handoff': 'No validated research handoff is available for this delivery window. No current refresh attempt is asserted.',
        'current_refresh_pending': 'The current research refresh has not completed. A current trading instruction is unavailable.',
        'current_refresh_failed': 'The current refresh did not establish a validated trading plan. Its failure remains recorded.',
        'current_publication_unverified': 'A refresh receipt exists, but a current safe trading publication could not be verified.'}[status]
    result = {'schema_version': 'equity_mandatory_status_brief_v1', 'cycle_date': cycle,
        'generated_at': current.isoformat(), 'scheduled_slot': scheduled_slot,
        'headline': 'Research status — no current trading instruction', 'failure_reason': reason,
        'status': status, 'status_summary': summary, 'observed_source': observed,
        'refresh_observation': {'current_window_attempt_observed': current_attempt,
            'observed_cycle_date': state.get('cycle_date'), 'observed_started_at': state.get('started_at'),
            'observed_completed_at': state.get('completed_at'), 'observed_outcome': state.get('outcome')},
        'assessment_delivery_policy': delivery_policy_context(root),
        'verification_scope': 'This status brief verifies neither market prices nor account facts. It contains no order, quantity or reused trading level.',
        'automatic_action_allowed': False,
        'boundaries': {'broker_connected': False, 'broker_account_read': False, 'order_code_created': False, 'trade_placed': False}}
    result['decision_fingerprint'] = canonical_sha256({k: v for k, v in result.items() if k != 'generated_at'})
    return result


def validate_failure_brief(artifact: dict, *, root: Path, current: datetime) -> dict:
    stamp = aware(artifact['generated_at'])
    require(stamp <= current and stamp.astimezone(ET).date() == current.astimezone(ET).date(), 'status_brief_clock_invalid')
    expected = build_failure_brief(root, stamp, artifact['scheduled_slot'], artifact['failure_reason'])
    require(artifact == expected, 'status_brief_source_or_content_changed')
    return artifact


def validate_failure_brief_archive(artifact: dict) -> dict:
    """Pure historical type/content proof; never reread today's refresh state."""
    fields = {'schema_version', 'cycle_date', 'generated_at', 'scheduled_slot', 'headline',
        'failure_reason', 'status', 'status_summary', 'observed_source', 'refresh_observation',
        'assessment_delivery_policy', 'verification_scope', 'automatic_action_allowed', 'boundaries',
        'decision_fingerprint'}
    summaries = {'missing_current_window_handoff': 'No validated research handoff is available for this delivery window. No current refresh attempt is asserted.',
        'current_refresh_pending': 'The current research refresh has not completed. A current trading instruction is unavailable.',
        'current_refresh_failed': 'The current refresh did not establish a validated trading plan. Its failure remains recorded.',
        'current_publication_unverified': 'A refresh receipt exists, but a current safe trading publication could not be verified.'}
    require(set(artifact) == fields and artifact.get('schema_version') == 'equity_mandatory_status_brief_v1'
        and artifact.get('scheduled_slot') in {'morning', 'afternoon'}
        and artifact.get('headline') == 'Research status — no current trading instruction'
        and re.fullmatch(r'[a-zA-Z0-9_:.-]{1,180}', str(artifact.get('failure_reason', '')))
        and artifact.get('status') in summaries
        and artifact.get('status_summary') == summaries[artifact['status']]
        and artifact.get('verification_scope') == 'This status brief verifies neither market prices nor account facts. It contains no order, quantity or reused trading level.'
        and artifact.get('automatic_action_allowed') is False
        and artifact.get('boundaries') == {'broker_connected': False, 'broker_account_read': False,
            'order_code_created': False, 'trade_placed': False}, 'status_brief_archive_type_invalid')
    stamp = aware(artifact['generated_at'])
    require(artifact['cycle_date'] == stamp.astimezone(ET).date().isoformat()
        and artifact['decision_fingerprint'] == canonical_sha256({k: v for k, v in artifact.items()
            if k not in {'generated_at', 'decision_fingerprint'}}), 'status_brief_archive_fingerprint_invalid')
    source = artifact['observed_source']
    require(set(source) == {'path', 'sha256'} and source['path'] == str(REFRESH_REL)
        and (source['sha256'] is None or HEX.fullmatch(str(source['sha256']))), 'status_brief_archive_source_invalid')
    observation = artifact['refresh_observation']
    require(set(observation) == {'current_window_attempt_observed', 'observed_cycle_date',
        'observed_started_at', 'observed_completed_at', 'observed_outcome'}
        and type(observation['current_window_attempt_observed']) is bool
        and observation['current_window_attempt_observed'] == (artifact['status'] != 'missing_current_window_handoff'),
        'status_brief_archive_observation_invalid')
    policy = artifact['assessment_delivery_policy']
    require(set(policy) == {'schema_version', 'effective_from', 'mandatory_daily_briefs',
        'intraday_alerts_enabled', 'policy_sha256'}
        and policy['schema_version'] == 'equity_assessment_delivery_policy_v1'
        and all(type(policy[k]) is bool for k in ('mandatory_daily_briefs', 'intraday_alerts_enabled'))
        and policy['policy_sha256'] == canonical_sha256({k: v for k, v in policy.items()
            if k not in {'schema_version', 'policy_sha256'}}), 'status_brief_archive_policy_invalid')
    return artifact


def render_failure_brief(artifact: dict) -> tuple[str, str, str]:
    validate_failure_brief_archive(artifact)
    from equity_naming import subject_prefix
    lines = [artifact['headline'], 'Observed: ' + artifact['generated_at'], artifact['status_summary'],
        artifact['verification_scope'], 'No earlier price, DAY order or trading quantity is renewed by this status update.',
        'Next: await a validated research publication; unresolved data and research requirements remain effective.']
    plain = '\n\n'.join(lines) + '\n'
    document = ('<!doctype html><html lang="en"><head><meta charset="utf-8"></head><body>'
        + ''.join('<p>' + html.escape(line) + '</p>' for line in lines) + '</body></html>\n')
    return subject_prefix() + ' ' + artifact['headline'] + ' — ' + artifact['cycle_date'], plain, document


def delivery_envelope(decision: dict, eligibility: dict, *, canonical_decision_sha256: str,
                       mode: str | None = None) -> dict:
    require(eligibility.get('eligible') is True and eligibility.get('mode') == 'intraday_alert', 'alert_envelope_not_eligible')
    require(mode in {None, 'intraday_alert'} and HEX.fullmatch(canonical_decision_sha256), 'alert_canonical_archive_reference_invalid')
    result = {k: deepcopy(eligibility[k]) for k in ('mode', 'purpose_key', 'meaning_key', 'action_changed',
        'priority_changed', 'changed_action_tickers', 'removed_action_tickers')}
    result.update(schema_version='equity_intraday_delivery_envelope_v1',
        canonical_decision_sha256=canonical_decision_sha256,
        canonical_content_sha256=canonical_sha256({k: v for k, v in decision.items() if k != 'delivery_assessment'}))
    result['envelope_sha256'] = canonical_sha256(result)
    return result


def validate_envelope(decision: dict) -> dict:
    envelope = decision['delivery_assessment']
    allowed = {'schema_version', 'canonical_decision_sha256', 'canonical_content_sha256', 'envelope_sha256',
        'mode', 'purpose_key', 'meaning_key', 'action_changed', 'priority_changed',
        'changed_action_tickers', 'removed_action_tickers'}
    require(envelope.get('schema_version') == 'equity_intraday_delivery_envelope_v1'
        and set(envelope) == allowed
        and envelope.get('mode') == 'intraday_alert'
        and HEX.fullmatch(str(envelope.get('canonical_decision_sha256', '')))
        and re.fullmatch(r'alert:\d{4}-\d{2}-\d{2}:[a-f0-9]{64}:[a-f0-9]{64}', str(envelope.get('purpose_key', '')))
        and re.fullmatch(MEANING_MARKER + r'[a-f0-9]{64}', str(envelope.get('meaning_key', '')))
        and envelope.get('envelope_sha256') == canonical_sha256({k: v for k, v in envelope.items() if k != 'envelope_sha256'})
        and envelope.get('canonical_content_sha256') == canonical_sha256({k: v for k, v in decision.items() if k != 'delivery_assessment'})
        and envelope.get('meaning_key') == advice_meaning_key(decision), 'alert_envelope_invalid')
    positives = {row['ticker'] for row in _actions(decision)}
    for key in ('changed_action_tickers', 'removed_action_tickers'):
        tickers = envelope.get(key)
        require(isinstance(tickers, list) and len(tickers) == len(set(tickers))
            and all(TICKER.fullmatch(str(ticker)) for ticker in tickers), 'alert_envelope_tickers_invalid')
    changed, removed = set(envelope['changed_action_tickers']), set(envelope['removed_action_tickers'])
    require(changed <= positives and not (removed & positives) and not (changed & removed)
        and type(envelope.get('action_changed')) is bool and type(envelope.get('priority_changed')) is bool
        and envelope['action_changed'] == bool(changed or removed)
        and (envelope['action_changed'] or envelope['priority_changed']), 'alert_envelope_scope_invalid')
    if envelope['priority_changed']:
        require(decision.get('analyst_priority_review', {}).get('status') == 'current'
            and bool(decision['analyst_priority_review'].get('entries')), 'alert_envelope_priority_invalid')
    return envelope


def render_intraday_alert(decision: dict, eligibility: dict | None = None) -> tuple[str, str, str]:
    envelope = eligibility if eligibility is not None else validate_envelope(decision)
    subject = '[Equity] Action update' if envelope.get('action_changed') else '[Equity] Research priority update'
    lines = [subject, 'Generated: ' + str(decision.get('generated_at', '')) + ' · dated reference data, not live.']
    lines.append('Reference market session: ' + str(decision.get('capital_decision', {}).get('market_data_timestamp', 'unverified')))
    changed = set(envelope.get('changed_action_tickers', []))
    for row in decision.get('capital_decision', {}).get('decisions', []):
        draft = row.get('order_draft')
        if row.get('ticker') not in changed or not draft:
            continue
        from capital_presentation import action_lines
        label = {'ACTIONABLE_BUY': 'BUY', 'ACTIONABLE_ADD': 'ADD',
            'REDUCE_REVIEW': 'REDUCE REVIEW', 'EXIT_REVIEW': 'EXIT REVIEW'}[row['decision']]
        lines += ['', label + ' — ' + row['ticker'], *action_lines(row)]
    for ticker in envelope.get('removed_action_tickers', []):
        lines += ['', ticker + ' — previous eligible instruction withdrawn; do not resubmit its earlier quantity.']
    if envelope.get('priority_changed'):
        lines += ['', 'Research priorities — no trade eligibility is implied.']
        for rank, entry in enumerate(decision.get('analyst_priority_review', {}).get('entries', []), 1):
            lines += [f"{rank}. {entry['ticker']}: {entry['reason']}", 'Next research step: ' + entry['next_step']]
            for url in dict.fromkeys(source.get('source_url', '') for source in entry.get('sources', [])):
                if isinstance(url, str) and url.startswith('https://'):
                    lines.append('Evidence: ' + url)
    if not envelope.get('action_changed'):
        lines += ['', 'No new or repeated trading instruction. Existing quantities are not reissued.']
    lines += ['', 'Human execution only. Verify executable quotes, available shares/funds and unrecorded changes; no order or fill is assumed.']
    link = decision.get('dashboard_link', {})
    url = link.get('url', '') if isinstance(link, dict) else ''
    if isinstance(url, str) and re.fullmatch(r'https://[a-z0-9][a-z0-9.-]*\.ts\.net/\?publication=[a-f0-9]{64}', url):
        lines += ['', 'Private dashboard: ' + url]
    plain = '\n'.join(lines) + '\n'
    body = '<html><body>' + ''.join('<p>' + html.escape(line) + '</p>' for line in lines if line) + '</body></html>'
    return subject, plain, body


def main():
    import argparse
    from daily_common import ROOT, now_et
    parser = argparse.ArgumentParser(description='Validate or append an explicit source-bound research priority review; no email or trade.')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = apply_priority_review(args.root, read_json(args.input), current=now_et(), apply=args.apply)
    print('priority_review=' + result['status'] + ' canonical_effect=false email_sent=false')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
