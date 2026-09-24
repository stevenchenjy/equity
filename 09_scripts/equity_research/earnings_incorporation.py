"""Hash-bound financial selection receipts and offline incorporation gate.

Collection, numerical incorporation and analyst thesis review are different
states. A fresh download does not establish that the latest results informed
research. This module checks financial selection; a thesis must additionally
acknowledge the exact material accessions it reviewed.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from daily_common import ROOT, atomic_write_json, canonical_sha256, read_csv, read_json, iso_now

STATUS_REL = Path('03_source_data/equity_research/earnings_incorporation_status.local.json')
CACHE_REL = Path('02_filings/companyfacts_snapshots.local')
SCHEMA_VERSION = 'earnings_incorporation_v1'
REPORT_FORMS = {'10-Q', '10-K', '20-F', '40-F', '10-Q/A', '10-K/A', '20-F/A', '40-F/A'}
MAX_AGE_HOURS = 36


class SecPayload(dict):
    """JSON object with out-of-band raw-byte receipt (never inserted in facts)."""
    receipt: dict[str, Any]


def retain_sec_response(raw: bytes, *, url: str, retrieved_at: str, root: Path = ROOT) -> dict[str, Any]:
    match = re.fullmatch(r'https://data.sec.gov/(?:api/xbrl/companyfacts|submissions)/CIK(\d{10})\.json', url)
    if not match:
        return {}
    value = json.loads(raw)
    if str(value.get('cik', '')).lstrip('0') != str(int(match[1])):
        raise ValueError('SEC raw response CIK identity conflict')
    digest = hashlib.sha256(raw).hexdigest()
    kind = 'companyfacts' if '/companyfacts/' in url else 'submissions'
    relative = CACHE_REL / match[1] / f'{kind}-{digest}.json'
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('SEC raw snapshot hash conflict')
    else:
        # Content-addressed immutable write. A concurrent same-content writer
        # is harmless; mismatch can never be accepted at the verified read.
        with path.open('xb') as stream:
            stream.write(raw)
    return {'kind': kind, 'source_url': url, 'raw_sha256': digest,
            'raw_path': relative.as_posix(), 'retrieved_at': retrieved_at, 'cik': int(match[1])}


def write_selection_receipt(*, ticker: str, cik: int, fundamental: dict[str, Any],
        filings: list[dict[str, str]], submissions_receipt: dict[str, Any],
        companyfacts_receipt: dict[str, Any], diagnostic: dict[str, Any],
        root: Path = ROOT) -> None:
    if not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', ticker):
        raise ValueError('invalid selection ticker')
    receipt = {'schema_version': 'financial_selection_receipt_v1', 'ticker': ticker,
               'cik': cik, 'submissions': submissions_receipt, 'companyfacts': companyfacts_receipt,
               'filings': filings, 'selection_diagnostics': diagnostic,
               'financial_selection_sha256': canonical_sha256(fundamental),
               'financial_selection': fundamental,
               'selected_period_end': fundamental.get('latest_period_end', ''),
               'selected_at': iso_now()}
    digest = canonical_sha256(receipt)
    atomic_write_json(root / CACHE_REL / 'selections' / f'{ticker}-{digest}.json', receipt)
    atomic_write_json(root / CACHE_REL / f'{ticker}.selection.json', receipt)


def _time(value: str) -> datetime | None:
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, AttributeError, TypeError):
        return None


def _verified_raw(root: Path, receipt: dict[str, Any]) -> dict[str, Any] | None:
    locator = receipt.get('raw_path', '')
    kind = receipt.get('kind')
    if kind not in {'companyfacts', 'submissions'} or type(receipt.get('cik')) is not int:
        return None
    endpoint = 'api/xbrl/companyfacts' if kind == 'companyfacts' else 'submissions'
    if receipt.get('source_url') != f"https://data.sec.gov/{endpoint}/CIK{receipt['cik']:010d}.json":
        return None
    path = (root / locator).resolve()
    if not locator or Path(locator).is_absolute() or not path.is_relative_to((root / CACHE_REL).resolve()):
        return None
    try:
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt.get('raw_sha256'):
            return None
        value = json.loads(raw)
        if int(value.get('cik', -1)) != receipt.get('cik'):
            return None
        if not isinstance(value.get('facts' if kind == 'companyfacts' else 'filings'), dict):
            return None
        return value
    except (OSError, ValueError, TypeError):
        return None


def _accessions(value: Any) -> set[str]:
    if isinstance(value, list):
        return set().union(*(_accessions(v) for v in value)) if value else set()
    if isinstance(value, dict):
        return ({value['accn']} if value.get('accn') else set()) | _accessions(value.get('components', []))
    return set()


def assess_company(ticker: str, fundamental: dict[str, Any], receipt: dict[str, Any], *,
        root: Path, now: datetime, ledger: list[dict[str, Any]], news: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    selected = fundamental.get('latest_period_end', '')
    result = {'ticker': ticker, 'status': 'unknown', 'selected_period_end': selected,
              'financial_selection_sha256': canonical_sha256(fundamental),
              'financial_economic_sha256': canonical_sha256({k:v for k,v in fundamental.items() if k != 'fetched_at'}),
              'latest_report_period_end': '', 'latest_material_accession': '',
              'latest_material_published_at': '', 'retrieved_at': '', 'incorporated_at': '',
              'positive_decision_eligible': False, 'blocking_reasons': reasons,
              'thesis_review_separate': True}
    if not fundamental or not selected:
        reasons.append('selected_financial_period_missing')
    if receipt.get('schema_version') != 'financial_selection_receipt_v1' or receipt.get('ticker') != ticker:
        reasons.append('raw_selection_receipt_missing')
    elif receipt.get('financial_selection_sha256') != canonical_sha256(fundamental):
        reasons.append('financial_selection_receipt_mismatch')
    sub = _verified_raw(root, receipt.get('submissions', {}))
    facts = _verified_raw(root, receipt.get('companyfacts', {}))
    if sub is None or facts is None:
        reasons.append('raw_source_snapshot_unverified')
    retrieved = receipt.get('companyfacts', {}).get('retrieved_at', '')
    sub_retrieved = receipt.get('submissions', {}).get('retrieved_at', '')
    result['retrieved_at'] = retrieved
    incorporated = _time(receipt.get('selected_at', ''))
    if incorporated is None or incorporated > now or (_time(retrieved) and incorporated < _time(retrieved)):
        reasons.append('incorporation_timestamp_unverified')
    for label, value in [('companyfacts', retrieved), ('submissions', sub_retrieved)]:
        time = _time(value)
        if time is None or not timedelta(0) <= now-time <= timedelta(hours=MAX_AGE_HOURS):
            reasons.append(label+'_retrieval_stale_or_missing')
    # Reconstruct report metadata from verified raw submissions, not an editable
    # receipt's convenient filing summary.
    filings = []
    if sub:
        recent = sub.get('filings', {}).get('recent', {})
        for i, accession in enumerate(recent.get('accessionNumber', [])):
            def at(k: str) -> str:
                arr = recent.get(k, [])
                return str(arr[i]) if i < len(arr) else ''
            form, items = at('form'), at('items')
            accepted = _time(at('acceptanceDateTime'))
            if accepted and accepted <= now and (form in REPORT_FORMS or (form in {'8-K', '8-K/A'} and '2.02' in items)):
                filings.append({'accession_number': accession, 'form': form, 'report_date': at('reportDate'),
                                'accepted_at': accepted.isoformat(), 'filing_date': at('filingDate')})
    # A changed filing ledger cannot be hidden by a formerly valid source receipt.
    known_accessions = {r['accession_number'] for r in filings}
    latest_scan_day = (_time(sub_retrieved).date().isoformat() if _time(sub_retrieved) else '')
    for row in ledger:
        if row.get('ticker') != ticker or row.get('accession_number') in known_accessions:
            continue
        if row.get('form') in REPORT_FORMS or (row.get('form') in {'8-K', '8-K/A'} and '2.02' in row.get('items', '')):
            if row.get('filing_date', '') >= latest_scan_day:
                reasons.append('material_ledger_ahead_of_verified_submission')
    # Legacy records still reveal an unincorporated newer filing even before
    # the first auditable raw response has been collected.
    if not filings:
        filings = [{'accession_number': r.get('accession_number', ''), 'form': r.get('form', ''),
                    'report_date': '', 'accepted_at': '', 'filing_date': r.get('filing_date', '')}
                   for r in ledger if r.get('ticker') == ticker and (r.get('form') in REPORT_FORMS
                   or (r.get('form') in {'8-K', '8-K/A'} and '2.02' in r.get('items', '')))]
    reports = [r for r in filings if r['form'] in REPORT_FORMS]
    latest_report = max(reports, key=lambda r: (r['report_date'], r['filing_date']), default={})
    latest = max(filings, key=lambda r: (r['filing_date'], r['accepted_at']), default={})
    result.update(latest_report_period_end=latest_report.get('report_date', ''),
                  latest_material_accession=latest.get('accession_number', ''),
                  latest_material_published_at=latest.get('accepted_at', ''),
                  latest_report_accession=latest_report.get('accession_number', ''),
                  selection_diagnostics=receipt.get('selection_diagnostics', {}))
    if not latest_report:
        reasons.append('latest_report_unknown')
    elif not latest_report.get('report_date'):
        reasons.append('latest_report_period_unknown')
    elif selected < latest_report['report_date']:
        reasons.append('latest_earnings_pending_incorporation')
    elif selected > latest_report['report_date']:
        reasons.append('selected_period_newer_than_verified_report')
    try:
        provenance = json.loads(fundamental.get('field_provenance_json', '{}'))
    except (ValueError, TypeError):
        provenance = {}
    revenue_sources = _accessions(provenance.get('revenue_latest', {}))
    if latest_report and latest_report.get('accession_number') not in revenue_sources:
        reasons.append('latest_report_not_used_by_selected_revenue')
    if latest and latest_report and latest['accession_number'] != latest_report['accession_number']:
        # An earnings release after the selected 10-Q must be incorporated by a
        # source-bound review/selection before numerical or thesis clearance.
        reasons.append('newer_earnings_release_pending_incorporation')
    if fundamental.get('data_quality') != 'ok':
        reasons.append('selected_financial_data_incomplete')
    # Headlines are only a conservative pending-review trigger, never a claim
    # of reported values or a direction-of-trade signal.
    latest_published = _time(result['latest_material_published_at'])
    for event in news.get('events', []):
        if event.get('ticker') != ticker:
            continue
        published = _time(event.get('published_at'))
        title = event.get('title', '').lower()
        earnings_result = bool(re.search(r'\b(results|earnings)\b', title)) and not re.search(
            r'to (announce|report)|conference call|will (announce|report)|scheduled|date', title)
        if earnings_result and published and (latest_published is None or published > latest_published):
            reasons.append('newer_official_results_news_pending_review')
    reasons[:] = sorted(set(reasons))
    result['status'] = 'incorporated' if not reasons else 'pending_incorporation' if latest else 'unknown'
    result['positive_decision_eligible'] = not reasons
    if not reasons:
        result['incorporated_at'] = receipt.get('selected_at', '')
    return result


def build_earnings_incorporation(*, root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('incorporation check requires timezone-aware time')
    fundamentals = read_csv(root / '03_source_data/equity_research/daily_fundamentals.csv')
    ledger = read_csv(root / '03_source_data/equity_research/daily_evidence_ledger.csv')
    news = read_json(root / '03_source_data/equity_research/official_news_events.local.json', {})
    companies = {}
    for row in fundamentals:
        ticker = row.get('ticker', '')
        if not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', ticker):
            continue
        receipt = read_json(root / CACHE_REL / f'{ticker}.selection.json', {})
        companies[ticker] = assess_company(ticker, row, receipt, root=root, now=now, ledger=ledger, news=news)
    # Known benchmark ETFs have no issuer financial thesis; an unfamiliar
    # holding remains visible as unknown instead of disappearing from coverage.
    held = sorted({r.get('ticker') for r in read_csv(root / '05_risk_and_positions/current_positions.local.csv')
                   if r.get('ticker') and r.get('ticker') not in {'SPY', 'QQQ', 'QQQM', 'XLK', 'XLI', 'XBI'}})
    for ticker in held:
        if ticker not in companies:
            companies[ticker] = assess_company(ticker, {}, {}, root=root, now=now, ledger=ledger, news=news)
    return {'schema_version': SCHEMA_VERSION, 'generated_at': now.isoformat(), 'companies': companies,
            'held_company_tickers': held, 'held_pending_tickers': [t for t in held if not companies[t]['positive_decision_eligible']],
            'fundamentals_sha256': canonical_sha256(fundamentals), 'ledger_sha256': canonical_sha256(ledger),
            'news_sha256': canonical_sha256(news), 'scope': 'financial_selection_not_analyst_thesis_completion'}


def read_earnings_incorporation_status(*, root: Path = ROOT, now: datetime | None = None) -> dict[str, Any]:
    # Re-evaluate receipt hashes and source/current-selection freshness offline.
    # Merely hashing a saved PASS report would miss tampered raw inputs.
    return build_earnings_incorporation(root=root, now=now)


def reconcile_cached_financial_selections(*, root: Path = ROOT, now: datetime | None = None) -> list[str]:
    """Finish numerical incorporation after this cycle caches a newer report.

    The public evidence refresh precedes SEC document retrieval. This bounded
    offline pass avoids waiting another day when companyfacts lags and the
    document became available only later in the same cycle. It only advances a
    financial period using verified supported inline facts; never repairs by
    copying unverified values or overwriting a current selection.
    """
    from daily_common import atomic_write_csv
    from latest_report_facts import supplement_cached_latest_report
    from refresh_daily_evidence import FUNDAMENTAL_FIELDS, approved_inline_tags, fundamental_row, recent_filings
    now = now or datetime.now(timezone.utc)
    path = root / '03_source_data/equity_research/daily_fundamentals.csv'
    rows = read_csv(path)
    changes = []
    receipts = []
    for i, row in enumerate(rows):
        ticker = row.get('ticker', '')
        if not re.fullmatch(r'[A-Z][A-Z0-9.]{0,9}', ticker):
            continue
        receipt = read_json(root / CACHE_REL / f'{ticker}.selection.json', {})
        if receipt.get('financial_selection_sha256') != canonical_sha256(row):
            continue
        sub = _verified_raw(root, receipt.get('submissions', {}))
        facts = _verified_raw(root, receipt.get('companyfacts', {}))
        retrieved = _time(receipt.get('companyfacts', {}).get('retrieved_at', ''))
        sub_retrieved = _time(receipt.get('submissions', {}).get('retrieved_at', ''))
        as_of = _time(row.get('fetched_at', ''))
        if sub is None or facts is None or as_of is None or any(t is None or not timedelta(0) <= now-t <= timedelta(hours=MAX_AGE_HOURS) for t in [retrieved, sub_retrieved]):
            continue
        cik = int(row['cik'])
        filings = recent_filings(sub, as_of=now.date())
        merged, diagnostic = supplement_cached_latest_report(facts, ticker=ticker, cik=cik,
            filings=filings, root=root, as_of=as_of, allowed_tags=approved_inline_tags())
        if diagnostic.get('status') != 'verified_inline_report_supplement':
            continue
        selected = fundamental_row(ticker, cik, merged, row['fetched_at'], acceptance_by_accession={
            f['accession_number']: f['accepted_at'] for f in filings})
        if selected.get('latest_period_end', '') <= row.get('latest_period_end', ''):
            continue
        rows[i] = selected
        changes.append(ticker)
        receipts.append(dict(ticker=ticker, cik=cik, fundamental=selected, filings=filings,
            submissions_receipt=receipt['submissions'], companyfacts_receipt=receipt['companyfacts'],
            diagnostic=diagnostic))
    if changes:
        # A crash between these publications produces a hash mismatch and a
        # pending gate, never a false PASS. The next evidence cycle repairs it.
        atomic_write_csv(path, FUNDAMENTAL_FIELDS, rows)
        for receipt in receipts:
            write_selection_receipt(**receipt, root=root)
    return changes
