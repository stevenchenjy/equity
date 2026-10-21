"""Independent, source-bound upcoming-earnings attention; never capital authority.

Nasdaq's public calendar has no confirmation flag or completeness guarantee.
Every returned lead is retained independently of momentum and candidate membership.
Public GETs occur only through the explicit refresh entry point. A failed date,
stale receipt, changed source, or calendar absence cannot manufacture no events,
issuer confirmation, cancellation, an analyst review, or entry eligibility.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable

from daily_common import ET, ROOT, atomic_write_json, canonical_sha256, read_json, sha256_file

POLICY_REL = Path('01_policies/earnings_event_policy.json')
EVENTS_REL = Path('03_source_data/equity_research/earnings_events.local.json')
STATUS_REL = Path('03_source_data/equity_research/earnings_events_status.local.json')
BASE_REL = Path('03_source_data/equity_research/earnings_events.local')
LOCK_REL = Path('00_project_control/run_logs/earnings_events.lock')
AUTHORITY = {'capital_authority': False, 'canonical_admission': False,
             'automatic_action_allowed': False, 'execution_authority': False}
ENDPOINT = 'https://api.nasdaq.com/api/calendar/earnings'
SESSIONS = {'time-after-hours': 'after_close', 'time-pre-market': 'before_open',
            'time-not-supplied': 'time_unknown'}
TICKER = re.compile(r'[A-Z][A-Z0-9.\-]{0,9}')
HEX = re.compile(r'[a-f0-9]{64}')


class EarningsError(ValueError):
    """Finite failure codes; arbitrary remote content is never executable."""


def require(condition, reason: str) -> None:
    if not condition:
        raise EarningsError(reason)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def aware(value) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        require(result.tzinfo is not None, 'earnings_time_zone_missing')
        return result
    except (ValueError, TypeError):
        raise EarningsError('earnings_time_invalid') from None


def inside(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and relative and not Path(relative).is_absolute(), 'earnings_path_invalid')
    result = (root / relative).resolve()
    require(result.is_relative_to(root.resolve()), 'earnings_path_escape')
    return result


def validate_policy(p: dict) -> dict:
    require(p.get('schema_version') == 'equity_earnings_event_policy_v1'
        and p.get('endpoint') == ENDPOINT and p.get('provider') == 'nasdaq_public_earnings_calendar', 'earnings_policy_invalid')
    bounds = {'horizon_calendar_days': (1, 31), 'max_age_hours': (1, 48),
              'request_timeout_seconds': (1, 15), 'maximum_response_bytes': (1024, 2097152),
              'maximum_rows_per_date': (1, 5000)}
    for key, (low, high) in bounds.items():
        require(type(p.get(key)) is int and low <= p[key] <= high, 'earnings_policy_bounds')
    require(p.get('maximum_attempts_per_date') == 1 and p.get('redirects_allowed') is False
        and p.get('requested_days') == 'weekdays' and p.get('date_confidence') == 'exchange_calendar_estimate'
        and all(p.get(key) is False for key in AUTHORITY), 'earnings_policy_authority_or_request_bounds')
    return p


def load_policy(root: Path) -> dict:
    return validate_policy(read_json(root / POLICY_REL))


def requested_dates(current: datetime, policy: dict) -> list[date]:
    start = current.astimezone(ET).date()
    return [d for i in range(policy['horizon_calendar_days'])
            if (d := start + timedelta(days=i)).weekday() < 5]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise EarningsError('earnings_redirect_forbidden')


def fetch_date(day: date, policy: dict, *, opener=None) -> bytes:
    """One bounded anonymous HTTPS GET; no redirects or automatic retry."""
    url = ENDPOINT + '?date=' + day.isoformat()
    request = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Accept': 'application/json', 'Accept-Encoding': 'identity',
        'Origin': 'https://www.nasdaq.com', 'Referer': 'https://www.nasdaq.com/'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect())).open(
                request, timeout=policy['request_timeout_seconds']) as response:
            require(response.status == 200, 'earnings_http_status')
            require(response.geturl() == url, 'earnings_response_url_changed')
            payload = response.read(policy['maximum_response_bytes'] + 1)
            require(len(payload) <= policy['maximum_response_bytes'], 'earnings_response_too_large')
            return payload
    except urllib.error.HTTPError as exc:
        raise EarningsError('earnings_http_rate_limited' if exc.code == 429 else 'earnings_http_error') from None
    except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
        raise EarningsError('earnings_network_unavailable') from None


def parse_date(payload: bytes, day: date, policy: dict) -> tuple[list[dict], list[dict]]:
    require(isinstance(payload, bytes) and len(payload) <= policy['maximum_response_bytes'], 'earnings_response_too_large')
    try:
        doc = json.loads(payload)
        data = doc['data']
        require(doc['status']['rCode'] == 200 and isinstance(data, dict), 'earnings_provider_status_invalid')
        require(datetime.strptime(data['asOf'], '%a, %b %d, %Y').date() == day, 'earnings_response_date_mismatch')
        rows = data['rows']
        # A structurally valid null rows response means observed empty for this
        # provider/date, never no earnings across the market.
        require(rows is None or isinstance(rows, list), 'earnings_rows_invalid')
        rows = rows or []
        require(len(rows) <= policy['maximum_rows_per_date'], 'earnings_row_bound_exceeded')
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, EarningsError):
            raise
        raise EarningsError('earnings_document_invalid') from None
    events, quarantine, seen = [], [], set()
    for index, row in enumerate(rows):
        try:
            require(isinstance(row, dict), 'earnings_row_invalid')
            ticker, name = row.get('symbol'), row.get('name')
            require(isinstance(ticker, str) and TICKER.fullmatch(ticker), 'earnings_ticker_invalid')
            require(isinstance(name, str) and 0 < len(name.strip()) <= 300
                and all(ord(c) >= 32 for c in name), 'earnings_company_name_invalid')
            session = SESSIONS.get(row.get('time'))
            require(session is not None, 'earnings_session_invalid')
            fiscal = row.get('fiscalQuarterEnding')
            require(isinstance(fiscal, str) and 1 <= len(fiscal) <= 30, 'earnings_fiscal_period_missing')
            # Fiscal quarter month is an identity hint, not a fabricated exact
            # quarter-end date. Keep the provider's original value verbatim.
            identity = {'ticker': ticker, 'event_date': day.isoformat(), 'fiscal_period_label': fiscal}
            event = {**identity, 'company_name': name.strip(), 'session': session,
                'event_id': canonical_sha256(identity), 'event_at': None,
                'research_deadline_at': datetime.combine(day, time(16) if session == 'after_close' else time(), ET).isoformat(),
                'date_confidence': 'exchange_calendar_estimate', 'source_type': 'exchange_earnings_calendar',
                'row_index': index, 'row_sha256': canonical_sha256(row), **AUTHORITY}
            event['schedule_version'] = canonical_sha256({**identity, 'session': session})
            marker = (event['event_id'], event['schedule_version'])
            if marker not in seen:
                events.append(event); seen.add(marker)
        except (ValueError, TypeError):
            quarantine.append({'row_index': index, 'reason': 'earnings_row_quarantined',
                               'row_sha256': canonical_sha256(row)})
    return events, quarantine


def immutable(root: Path, directory: str, raw: bytes) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    relative = BASE_REL / directory / (digest + '.json')
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(sha256_file(path) == digest, 'earnings_immutable_source_corrupt')
    else:
        with path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return {'path': str(relative), 'sha256': digest}


def empty_store() -> dict:
    return {'schema_version': 'equity_earnings_event_store_v1', 'scans': [], **AUTHORITY}


def validated_scans(root: Path, *, current: datetime) -> list[dict]:
    store = read_json(root / EVENTS_REL, empty_store())
    require(store.get('schema_version') == 'equity_earnings_event_store_v1'
        and all(store.get(k) is False for k in AUTHORITY) and isinstance(store.get('scans'), list), 'earnings_store_invalid')
    result, prior_time = [], None
    for ref in store['scans']:
        require(HEX.fullmatch(str(ref.get('sha256', ''))) is not None, 'earnings_scan_hash_invalid')
        path = inside(root, ref['path'])
        require(sha256_file(path) == ref['sha256'], 'earnings_scan_changed')
        scan = read_json(path)
        require(scan.get('schema_version') == 'equity_earnings_event_scan_v1', 'earnings_scan_schema_invalid')
        policy_ref = scan['policy_source']
        policy_path = inside(root, policy_ref['path'])
        require(sha256_file(policy_path) == policy_ref['sha256'] == scan.get('policy_sha256'), 'earnings_scan_policy_changed')
        policy = validate_policy(read_json(policy_path))
        stamp = aware(scan['completed_at'])
        require(stamp <= current and (prior_time is None or stamp >= prior_time), 'earnings_scan_clock_invalid')
        require(aware(ref['available_at']) == stamp and aware(scan['started_at']) <= stamp, 'earnings_scan_receipt_clock_invalid')
        require(isinstance(scan.get('dates'), list) and len(scan['dates']) <= 31, 'earnings_scan_dates_invalid')
        expected = {d.isoformat() for d in requested_dates(aware(scan['started_at']), policy)}
        require({r['date'] for r in scan['dates']} == expected and len(scan['dates']) == len(expected), 'earnings_scan_date_coverage_invalid')
        for row in scan['dates']:
            observed = aware(row['observed_at'])
            require(aware(scan['started_at']) <= observed <= stamp, 'earnings_observation_clock_invalid')
            if row['status'] in {'verified', 'partial'}:
                source = row['source']
                require(source['source_url'] == ENDPOINT + '?date=' + row['date']
                    and aware(source['available_at']) == observed, 'earnings_source_identity_invalid')
                rawpath = inside(root, source['path'])
                require(sha256_file(rawpath) == source['sha256'], 'earnings_source_changed')
                events, quarantine = parse_date(rawpath.read_bytes(), date.fromisoformat(row['date']), policy)
                require(events == row['events'] and quarantine == row['quarantine'], 'earnings_parsed_source_changed')
                require(row['status'] == ('partial' if quarantine else 'verified'), 'earnings_partial_status_invalid')
            else:
                require(row['status'] == 'failed' and not row['events'], 'earnings_failed_date_invalid')
        result.append(scan); prior_time = stamp
    return result


def refresh_events(root: Path = ROOT, *, current: datetime | None = None,
                   fetcher: Callable | None = None, clock: Callable = utc_now) -> dict:
    """Explicit public-network operation. Caller owns the documented short lock."""
    started = clock()
    policy = load_policy(root)
    if current is not None:
        require(aware(current.isoformat()).astimezone(ET).date() == started.astimezone(ET).date(), 'earnings_refresh_clock_date_mismatch')
    previous = read_json(root / EVENTS_REL, empty_store())
    validated_scans(root, current=started)
    days = []
    for day in requested_dates(started, policy):
        row = {'date': day.isoformat(), 'events': [], 'quarantine': []}
        try:
            payload = (fetcher or fetch_date)(day, policy)
            observed = clock()
            source = {**immutable(root, 'sources', payload), 'available_at': observed.isoformat(),
                      'source_url': ENDPOINT + '?date=' + day.isoformat()}
            row['source'] = source
            events, quarantine = parse_date(payload, day, policy)
            row.update(status='partial' if quarantine else 'verified', events=events, quarantine=quarantine,
                       reason='malformed_rows_quarantined' if quarantine else 'provider_date_observed')
        except (EarningsError, OSError, ValueError, TypeError) as exc:
            observed = clock()
            row.update(status='failed', reason=str(exc) if isinstance(exc, EarningsError) else 'earnings_fetch_or_parse_failed')
        row['observed_at'] = observed.isoformat(); days.append(row)
    completed = clock()
    policy_ref = immutable(root, 'policies', (root / POLICY_REL).read_bytes())
    scan = {'schema_version': 'equity_earnings_event_scan_v1', 'started_at': started.isoformat(),
        'completed_at': completed.isoformat(), 'policy_sha256': sha256_file(root / POLICY_REL),
        'policy_source': policy_ref, 'dates': days, **AUTHORITY}
    raw = (json.dumps(scan, indent=2, sort_keys=True) + '\n').encode()
    ref = {**immutable(root, 'scans', raw), 'available_at': completed.isoformat()}
    store = copy.deepcopy(previous)
    # A byte-identical replay at the same actual time cannot append duplicates.
    if ref not in store['scans']:
        store['scans'].append(ref)
    require(read_json(root / EVENTS_REL, empty_store()) == previous, 'earnings_store_changed_before_publish')
    immutable(root, 'history', (json.dumps(previous, indent=2, sort_keys=True) + '\n').encode())
    atomic_write_json(root / EVENTS_REL, store)
    result = summary(root, current=completed)
    atomic_write_json(root / STATUS_REL, result)
    return result


def event_observations(root: Path, *, current: datetime) -> tuple[list[dict], dict]:
    """Read only; validate original bytes, identity, actual clocks and coverage."""
    policy = load_policy(root)
    requested = requested_dates(current, policy)
    start, end = requested[0].isoformat(), requested[-1].isoformat()
    coverage = {'scope': policy['coverage_scope'], 'horizon_start': start, 'horizon_end': end,
        'days_requested': len(requested), 'days_verified': 0, 'failed_dates': [],
        'events_detected': 0, 'latest_fetch_at': None, 'full_market_coverage': False,
        'issuer_confirmation': False, 'status': 'missing'}
    try:
        scans = validated_scans(root, current=current)
    except (OSError, ValueError, KeyError, TypeError):
        coverage['status'] = 'unverified'; coverage['failed_dates'] = [d.isoformat() for d in requested]
        return [], coverage
    if not scans:
        coverage['failed_dates'] = [d.isoformat() for d in requested]
        return [], coverage
    coverage['latest_fetch_at'] = scans[-1]['completed_at']
    latest, first, variants, all_events = {}, {}, {}, {}
    for scan in scans:
        for row in scan['dates']:
            latest[row['date']] = row
            if row['status'] not in {'verified', 'partial'}:
                continue
            for event in row['events']:
                identity = event['event_id']
                first.setdefault(identity, row['observed_at'])
                variants.setdefault(identity, set()).add(event['schedule_version'])
                all_events[identity] = (event, row)
    for day in requested:
        row = latest.get(day.isoformat())
        fresh = row and current - aware(row['observed_at']) <= timedelta(hours=policy['max_age_hours'])
        if row and row['status'] == 'verified' and fresh:
            coverage['days_verified'] += 1
        else:
            coverage['failed_dates'].append(day.isoformat())
    age = current - aware(scans[-1]['completed_at'])
    coverage['status'] = ('stale' if age > timedelta(hours=policy['max_age_hours']) else
        'ready' if coverage['days_verified'] == len(requested) else 'partial')
    result, period_dates = [], {}
    # Retain elapsed unreviewed events for seven days so a missed session is
    # visible; an absence is explicitly not interpreted as cancellation.
    lower = current.astimezone(ET).date() - timedelta(days=7)
    upper = current.astimezone(ET).date() + timedelta(days=policy['horizon_calendar_days']-1)
    for identity, (original, row) in all_events.items():
        day = date.fromisoformat(original['event_date'])
        if not lower <= day <= upper:
            continue
        event = copy.deepcopy(original)
        source = row['source']
        latest_row = latest.get(event['event_date'], {})
        row_present = any(e['event_id'] == identity for e in latest_row.get('events', []))
        fresh = current - aware(row['observed_at']) <= timedelta(hours=policy['max_age_hours'])
        blocked = []
        if not fresh:
            blocked.append('earnings_calendar_receipt_stale')
        if latest_row.get('status') not in {'verified', 'partial'}:
            blocked.append('earnings_calendar_latest_date_fetch_failed')
        if not row_present:
            blocked.append('event_absent_on_latest_scan_not_cancelled')
        if len(variants[identity]) > 1:
            blocked.append('event_session_changed_requires_confirmation')
        deadline = aware(event['research_deadline_at'])
        event.update(first_detected_at=first[identity], last_observed_at=row['observed_at'],
            sources=[source], timing=('pre_event' if current < deadline else
                'post_event' if aware(first[identity]) >= deadline else 'elapsed'),
            status='detected', research_state='not_started', blockers=blocked,
            next_step='Verify issuer schedule; research expectations, company valuation, countercase and event downside before the conservative deadline.',
            investment_signal=False)
        period_dates.setdefault((event['ticker'], event['fiscal_period_label']), set()).add(event['event_date'])
        result.append(event)
    for event in result:
        if len(period_dates[(event['ticker'], event['fiscal_period_label'])]) > 1:
            event['blockers'].append('possible_reschedule_or_conflicting_dates_requires_issuer_confirmation')
        if any('changed' in b or 'conflicting' in b for b in event['blockers']):
            event['status'] = 'schedule_conflict'
        elif event['timing'] in {'elapsed', 'post_event'}:
            event['status'] = 'elapsed_unreviewed'
        elif event['blockers']:
            event['timing'] = 'unverified'
    result.sort(key=lambda e: (e['research_deadline_at'], e['ticker'], e['event_id']))
    coverage['events_detected'] = len(result)
    marker = read_json(root / BASE_REL / 'last_run.json', {})
    if marker:
        try:
            require(aware(marker['started_at']) <= current, 'earnings_run_from_future')
            finished = marker.get('completed_at')
            require(finished and aware(marker['started_at']) <= aware(finished) <= current
                and marker.get('exit_code') == 0, 'earnings_latest_run_incomplete')
            coverage['last_run_status'] = 'completed'
        except (ValueError, KeyError, TypeError):
            coverage['last_run_status'] = 'failed_or_incomplete'
            coverage['status'] = 'partial' if coverage['status'] == 'ready' else coverage['status']
            for event in result:
                event['blockers'].append('earnings_latest_run_failed_or_incomplete')
    return result, coverage


def validate_event_review(review: dict, event: dict, *, root: Path, current: datetime,
                          assessed_at: str, admitted_sources: list[dict] | None = None) -> None:
    """Explicit event-specific research; neither a dossier nor generic assessment."""
    require(isinstance(review, dict) and review.get('event_id') == event['event_id'], 'earnings_review_event_mismatch')
    for key in ('expectations_case', 'priced_in_assessment', 'valuation_case', 'downside_case', 'recheck_condition'):
        require(isinstance(review.get(key), str) and 1 <= len(review[key].strip()) <= 20000, 'earnings_review_case_missing')
    stamp = aware(assessed_at)
    require(aware(event['first_detected_at']) <= stamp < aware(event['research_deadline_at'])
        and stamp <= current, 'earnings_review_clock_invalid')
    receipts = review.get('sources')
    require(isinstance(receipts, list) and bool(receipts), 'earnings_review_sources_missing')
    bound_sources = [*event['sources'], *(admitted_sources or [])]
    observed_hashes = {s['sha256'] for s in bound_sources}
    review_hashes = {s.get('sha256') for s in receipts if isinstance(s, dict)}
    matching_hashes = observed_hashes & review_hashes
    require(bool(matching_hashes), 'earnings_review_event_source_missing')
    # A whole-calendar refetch may change other issuers. Retain a completed
    # case only when its actual original receipt still contains this same
    # issuer row and schedule; changed own EPS/timing/identity needs reassessment.
    row_bound = False
    for source in bound_sources:
        if source['sha256'] not in matching_hashes:
            continue
        try:
            require(source.get('source_url') == ENDPOINT + '?date=' + event['event_date'], 'earnings_review_calendar_source_invalid')
            require(sha256_file(inside(root, source['path'])) == source['sha256'], 'earnings_review_source_changed')
            original_rows, _ = parse_date(inside(root, source['path']).read_bytes(), date.fromisoformat(event['event_date']), load_policy(root))
            if any(row['event_id'] == event['event_id'] and row['row_sha256'] == event['row_sha256']
                    and row['schedule_version'] == event['schedule_version'] for row in original_rows):
                row_bound = True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    require(row_bound, 'earnings_review_current_row_changed')
    for receipt in receipts:
        require(isinstance(receipt, dict) and HEX.fullmatch(str(receipt.get('sha256', ''))) is not None,
                'earnings_review_source_invalid')
        require(aware(receipt['available_at']) <= stamp and sha256_file(inside(root, receipt['path'])) == receipt['sha256'],
                'earnings_review_source_changed_or_future')


def _event_assessment(item: dict, event: dict, *, root: Path, current: datetime) -> dict | None:
    assessment = item.get('assessment', {})
    try:
        admitted = [source for observation in item.get('observations', [])
            if (observation.get('evidence', {}).get('event', {}).get('event_id') == event['event_id']
                and observation.get('evidence', {}).get('event', {}).get('row_sha256') == event['row_sha256']
                and observation.get('evidence', {}).get('event', {}).get('schedule_version') == event['schedule_version'])
            for source in observation.get('sources', [])]
        validate_event_review(assessment.get('earnings_event_review'), event, root=root,
            current=current, assessed_at=assessment['assessed_at'], admitted_sources=admitted)
        require(aware(assessment['assessed_at']) < aware(assessment['next_review_at'])
            <= aware(event['research_deadline_at']), 'earnings_assessment_review_date_invalid')
        return assessment
    except (OSError, ValueError, KeyError, TypeError):
        return None


def summary(root: Path, *, current: datetime, capital: dict | None = None) -> dict:
    events, coverage = event_observations(root, current=current)
    items = []
    try:
        # Lazy import avoids a collector/intake circular dependency. This reader
        # replays and validates the existing research source receipts first.
        from research_opportunities import read_report
        items = read_report(root, current=current)['opportunities']
    except (OSError, ValueError, KeyError, TypeError, ImportError):
        pass
    by_ticker = {item['ticker']: item for item in items}
    capital_valid = False
    if capital:
        try:
            from capital_decision import validate as validate_capital
            validate_capital(capital, current=current, root=root)
            capital_valid = True
        except (OSError, ValueError, KeyError, TypeError):
            pass
    capital_rows = (capital or {}).get('decisions', [])
    if isinstance(capital_rows, dict):
        capital_rows = list(capital_rows.values())
    for event in events:
        item = by_ticker.get(event['ticker'])
        if not item:
            if event['status'] == 'detected':
                event['status'] = 'awaiting_research'
            continue
        matching = [p for p in item.get('observations', [])
            if p.get('evidence', {}).get('event', {}).get('event_id') == event['event_id']]
        if not matching:
            continue
        event['research_state'] = item['state']
        event['blockers'] = list(dict.fromkeys([*event['blockers'], *item.get('blockers', [])]))
        assessment = _event_assessment(item, event, root=root, current=current)
        if assessment and event['status'] != 'schedule_conflict':
            event['status'] = 'reviewed_without_entry'
            event['assessment_at'] = assessment['assessed_at']
            event['assessment_sha256'] = canonical_sha256(assessment)
            event['event_review'] = assessment['earnings_event_review']
            event['next_step'] = assessment['earnings_event_review']['recheck_condition']
            event['review_conclusion'] = assessment.get('conclusion')
            event['valuation_status'] = assessment.get('valuation_status')
            if current >= aware(assessment['next_review_at']):
                event['blockers'].append('earnings_event_review_due')
            row = next((r for r in capital_rows if isinstance(r, dict) and r.get('ticker') == event['ticker']), {})
            draft = row.get('order_draft')
            if (capital_valid and assessment.get('conclusion') == 'supported'
                and assessment.get('valuation_status') == 'reviewed'
                and coverage['status'] == 'ready' and not event['blockers'] and event['timing'] == 'pre_event'
                and row.get('decision') in {'ACTIONABLE_BUY', 'ACTIONABLE_ADD'}
                and type(row.get('shares')) is int and row['shares'] > 0
                and isinstance(draft, dict)
                and all(draft.get(k) is not None for k in ('entry_limit', 'time_in_force'))):
                event['status'] = 'eligible_conditional_plan'
                event['next_step'] = 'Review the existing production conditional plan; event detection does not authorize execution.'
        elif event['status'] not in {'schedule_conflict', 'elapsed_unreviewed'}:
            event['status'] = 'research_in_progress' if item.get('research_started_at') else 'awaiting_research'
    return {'schema_version': 'equity_earnings_event_view_v1', 'generated_at': current.isoformat(),
        'status': coverage['status'], 'coverage': coverage, 'events': events, **AUTHORITY}


def notification_meaning(view: dict) -> list[dict]:
    """Stable completed advice only; collection clocks/countdowns are not advice."""
    if view.get('status') != 'ready':
        return []
    return [{k: event.get(k) for k in ('event_id', 'ticker', 'status', 'assessment_sha256', 'next_step', 'blockers')}
            for event in view.get('events', []) if event.get('timing') == 'pre_event'
            and event.get('status') in {'reviewed_without_entry', 'eligible_conditional_plan'}
            and event.get('assessment_sha256')]


def publication_meaning(view: dict) -> dict:
    """Stable evidence/attention state checked again at publication and send.

    The live reader already validates every actual receipt clock and raw hash.
    Refetch timestamps and regenerated countdowns do not alter this projection;
    changed source bytes, date coverage, review state or a passed deadline do.
    This is a publication consistency check, not an account-wide capital gate.
    """
    coverage = view.get('coverage', {})
    return {'schema_version': view.get('schema_version'), 'status': view.get('status'),
        'coverage': {key: coverage.get(key) for key in ('scope', 'horizon_start', 'horizon_end',
            'days_requested', 'days_verified', 'failed_dates', 'full_market_coverage', 'issuer_confirmation')},
        'events': sorted([{**{key: event.get(key) for key in ('event_id', 'ticker', 'company_name',
                'schedule_version', 'event_date', 'session', 'event_at', 'research_deadline_at',
                'first_detected_at', 'date_confidence', 'timing', 'status', 'research_state',
                'blockers', 'next_step', 'assessment_sha256')},
            'sources': sorted([{key: source.get(key) for key in ('path', 'sha256', 'source_url')}
                for source in event.get('sources', [])], key=lambda source: (str(source['path']), str(source['sha256'])))}
            for event in view.get('events', [])], key=lambda event: str(event['event_id']))}
