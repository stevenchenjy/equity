"""Reported quarterly shares from verified MSFT and MU earnings exhibits.

The annual 10-K denominator is never disaggregated as if it were a quarterly
average. This issuer format adapter follows Exhibit 99.1 in an accepted Item
2.02 8-K, retains original bytes, and reads the reported quarter/year columns.
No missing value, basic-share substitute, forecast, or order is admitted.
"""
from __future__ import annotations

from calendar import monthrange
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re

from daily_common import ROOT, atomic_write_json, read_json
from refresh_sec_filing_artifacts import atomic_write_bytes, exhibit_rows, fetch_sec_document

SHARES_TAG = 'WeightedAverageNumberOfDilutedSharesOutstanding'
MAX_BYTES = 5 * 1024 * 1024
ISSUERS = {'MSFT': 789019, 'MU': 723125}


class Tables(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.tables, self.links, self.table_prefixes, self.outside = [], [], [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'table':
            self.stack.append({'rows': [], 'row': None, 'cell': None,
                               'prefix': ' '.join(self.outside)[-1024:]})
        elif self.stack:
            active = self.stack[-1]
            if tag == 'tr': active['row'] = []
            elif tag in {'td', 'th'} and active['row'] is not None: active['cell'] = []

    def handle_data(self, text):
        if self.stack and self.stack[-1]['cell'] is not None:
            self.stack[-1]['cell'].append(text)
        elif not self.stack:
            self.outside.append(text)
            if len(self.outside) > 40: self.outside = self.outside[-20:]

    def handle_endtag(self, tag):
        if not self.stack: return
        active = self.stack[-1]
        if tag in {'td', 'th'} and active['cell'] is not None:
            active['row'].append(' '.join(''.join(active['cell']).split()))
            active['cell'] = None
        elif tag == 'tr' and active['row'] is not None:
            active['rows'].append(active['row']); active['row'] = None
        elif tag == 'table':
            table = self.stack.pop()
            self.tables.append(table['rows']); self.table_prefixes.append(table['prefix'])


def reported_quarter_shares(raw: bytes, *, period_end: str) -> list[dict]:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('earnings_exhibit_size_invalid')
    end = date.fromisoformat(period_end)
    if end.month not in {3, 6, 9, 12} or end.day != monthrange(end.year, end.month)[1]:
        raise ValueError('earnings_quarter_period_invalid')
    parser = Tables(); parser.feed(raw.decode('utf-8'))
    month_day = end.strftime('%B ') + str(end.day)
    matches = []
    for table_index, rows in enumerate(parser.tables):
        text = parser.table_prefixes[table_index] + ' ' + ' '.join(cell for row in rows for cell in row)
        if 'Weighted average shares outstanding:' not in text:
            continue
        quarter = text.find('Three Months Ended')
        if (quarter < 0 or month_day not in text
                or not re.search(r'\bmillions\b', text, re.I)):
            continue
        years = [cell for row in rows for cell in row if re.fullmatch(r'20\d\d', cell)]
        if years[:2] != [str(end.year), str(end.year - 1)]:
            continue
        weighted = False
        for row_index, row in enumerate(rows):
            cells = [cell for cell in row if cell]
            if cells and cells[0] == 'Weighted average shares outstanding:': weighted = True
            if not weighted or not cells or cells[0] != 'Diluted': continue
            if len(cells) not in {3, 5} or not all(re.fullmatch(r'\d[\d,]*(?:\.\d+)?', n) for n in cells[1:]):
                raise ValueError('earnings_diluted_share_columns_invalid')
            values = [Decimal(n.replace(',', '')) * 1_000_000 for n in cells[1:]]
            if any(not n.is_finite() or n <= 0 for n in values):
                raise ValueError('earnings_diluted_share_value_invalid')
            matches.append((values[:2], table_index, row_index))
    if not matches or any(values != matches[0][0] for values, _, _ in matches):
        raise ValueError('earnings_reported_quarter_shares_unverified')
    values, table_index, row_index = matches[0]
    return [{'start': date(year, end.month - 2, 1).isoformat(),
             'end': date(year, end.month, end.day).isoformat(), 'val': float(value),
             '_fact_id': f'table:{table_index}:row:{row_index}:quarter_column:{column}',
             '_context_id': f'reported-quarter-{year}-{end.month:02d}',
             '_reported_label': 'Weighted average shares outstanding: Diluted; in millions'}
            for column, (year, value) in enumerate(zip((end.year, end.year - 1), values))]


def mu_reported_quarter_shares(raw: bytes, *, quarter_periods: list[dict]) -> list[dict]:
    """Read GAAP MU fiscal-quarter columns, using independently bound periods.

    Fiscal Q4 may contain 14 weeks. Revenue's exact direct/derived duration
    anchors establish the start/end; the shares themselves are never derived.
    The exhibit's date, quarter labels and revenue must agree with those anchors.
    """
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('earnings_exhibit_size_invalid')
    if len(quarter_periods) != 2:
        raise ValueError('earnings_fiscal_period_support_unverified')
    for period in quarter_periods:
        start, end = date.fromisoformat(period['start']), date.fromisoformat(period['end'])
        if not 60 <= (end - start).days <= 130 or period.get('val', 0) <= 0:
            raise ValueError('earnings_fiscal_period_support_unverified')
    current_end, prior_end = (date.fromisoformat(period['end']) for period in quarter_periods)
    if not 350 <= (current_end - prior_end).days <= 380:
        raise ValueError('earnings_fiscal_period_support_unverified')
    parser = Tables(); parser.feed(raw.decode('utf-8'))
    matches = []
    for table_index, rows in enumerate(parser.tables):
        # The nearest issuer/title distinguishes the GAAP statement from the
        # later reconciliation, whose diluted denominator may be different.
        prefix = parser.table_prefixes[table_index].rsplit('MICRON TECHNOLOGY, INC.', 1)[-1]
        if not re.search(r'CONSOLIDATED\s+STATEMENTS\s+OF\s+OPERATIONS', prefix, re.I):
            continue
        if not re.search(r'\(In millions, except per share amounts\)', prefix, re.I):
            continue
        labels, dates = None, None
        for row in rows:
            cells = [cell for cell in row if cell]
            if cells and all(re.fullmatch(r'(?:[1-4](?:st|nd|rd|th) Qtr\.|Year Ended)', c) for c in cells):
                if labels is not None: raise ValueError('earnings_fiscal_columns_ambiguous')
                labels = cells
            elif cells and all(re.fullmatch(r'[A-Z][a-z]+ \d{1,2},\s*20\d\d', c) for c in cells):
                if dates is not None: raise ValueError('earnings_fiscal_columns_ambiguous')
                dates = [datetime.strptime(re.sub(r',\s*', ', ', c), '%B %d, %Y').date().isoformat() for c in cells]
        if labels is None or dates is None:
            continue
        # Annual comparison covers two adjacent columns. Do not treat it as
        # another fiscal quarter or infer position from the first numeric cell.
        if labels.count('Year Ended') == 1 and labels[-1] == 'Year Ended' and len(dates) == len(labels) + 1:
            labels = labels[:-1] + ['Year Ended', 'Year Ended']
        if len(labels) != len(dates):
            raise ValueError('earnings_fiscal_columns_ambiguous')
        columns = []
        for period in quarter_periods:
            found = [i for i, (label, end) in enumerate(zip(labels, dates)) if end == period['end'] and label != 'Year Ended']
            if len(found) != 1: raise ValueError('earnings_fiscal_columns_unverified')
            columns.append(found[0])
        if labels[columns[0]] != labels[columns[1]]:
            raise ValueError('earnings_fiscal_quarters_not_comparable')
        weighted, values, revenues = False, None, None
        for row_index, row in enumerate(rows):
            cells = [cell for cell in row if cell and cell != '$']
            if not cells: continue
            if cells[0] == 'Revenue':
                revenues = cells[1:]
            if cells[0] == 'Number of shares used in per share calculations':
                weighted = True
            if not weighted or cells[0] != 'Diluted': continue
            if values is not None or len(cells) != len(dates) + 1 or not all(re.fullmatch(r'\d[\d,]*(?:\.\d+)?', n) for n in cells[1:]):
                raise ValueError('earnings_diluted_share_columns_invalid')
            values = [Decimal(n.replace(',', '')) * 1_000_000 for n in cells[1:]]
            if any(not n.is_finite() or n <= 0 for n in values):
                raise ValueError('earnings_diluted_share_value_invalid')
            diluted_row = row_index
        if values is None or revenues is None or len(revenues) != len(dates):
            continue
        for period, column in zip(quarter_periods, columns):
            if Decimal(revenues[column].replace(',', '')) * 1_000_000 != Decimal(str(period['val'])):
                raise ValueError('earnings_fiscal_revenue_period_conflict')
        facts = [{
            'start': period['start'], 'end': period['end'], 'val': float(values[column]),
            '_fact_id': f'table:{table_index}:row:{diluted_row}:quarter_column:{column}',
            '_context_id': f'MU-reported-{labels[column]}-{period["start"]}-{period["end"]}',
            '_reported_label': 'GAAP Number of shares used in per share calculations: Diluted; in millions',
            '_period_support': deepcopy(period), '_fiscal_quarter_label': labels[column],
        } for period, column in zip(quarter_periods, columns)]
        matches.append(facts)
    if not matches or any([(f['start'], f['end'], f['val']) for f in facts] != [(f['start'], f['end'], f['val']) for f in matches[0]] for facts in matches):
        raise ValueError('earnings_reported_quarter_shares_unverified')
    return matches[0]


def _mu_quarter_periods(payload: dict, *, period_end: str, filings: list[dict], as_of: datetime) -> list[dict]:
    # Reuse the canonical selector: direct quarter facts or actual fiscal-YTD
    # boundaries, approved revenue aliases/units and acceptance availability.
    from refresh_daily_evidence import REVENUE_TAGS, quarterly_values, _prior_period
    values = quarterly_values(payload, REVENUE_TAGS, as_of=as_of,
        acceptance_by_accession={r['accession_number']: r['accepted_at'] for r in filings})
    current = [v for v in values if v['end'] == period_end]
    if len(current) != 1:
        raise ValueError('earnings_fiscal_period_support_unverified')
    prior = _prior_period(values, current[0])
    if prior is None:
        raise ValueError('earnings_fiscal_period_support_unverified')
    return [current[0], prior]


def supplement_msft_shares(payload: dict, filings: list[dict], user_agent: str, **kwargs) -> dict:
    return supplement_reported_shares('MSFT', 789019, payload, filings, user_agent, **kwargs)


def supplement_reported_shares(ticker: str, cik: int, payload: dict, filings: list[dict], user_agent: str, *,
                           as_of: datetime, cache_root: Path, fetcher=fetch_sec_document,
                           project_root: Path = ROOT) -> dict:
    if ISSUERS.get(ticker) != cik or payload.get('cik', cik) != cik:
        raise ValueError('earnings_issuer_identity_conflict')
    reports = [r for r in filings if r.get('form') in {'10-K', '10-Q'}
               and r.get('report_date') and datetime.fromisoformat(r['accepted_at'].replace('Z', '+00:00')) <= as_of]
    if not reports: return payload
    report = max(reports, key=lambda r: (r['report_date'], r['accepted_at']))
    end = date.fromisoformat(report['report_date'])
    existing = payload.get('facts', {}).get('us-gaap', {}).get(SHARES_TAG, {}).get('units', {}).get('shares', [])
    quarter_periods = _mu_quarter_periods(payload, period_end=end.isoformat(), filings=filings, as_of=as_of) if ticker == 'MU' else None
    # Ordinary 10-Q facts usually already report both exact quarter averages.
    # Do not add an avoidable network dependency to an otherwise complete row.
    if quarter_periods is not None or end.month in {3, 6, 9, 12}:
        required = {(p['start'], p['end']) for p in quarter_periods} if quarter_periods else {(date(y, end.month - 2, 1).isoformat(), date(y, end.month, end.day).isoformat()) for y in (end.year, end.year - 1)}
        available = {(f.get('start'), f.get('end')) for f in existing
            if f.get('form') in {'10-K','10-Q'} and isinstance(f.get('val'), (int,float)) and f['val'] > 0
            and f.get('filed') and date.fromisoformat(f['filed']) <= as_of.date()}
        if required <= available: return payload
    earnings = [r for r in filings if r.get('form') == '8-K' and '2.02' in r.get('items', '').split(',')
                and 0 <= (date.fromisoformat(r['filing_date']) - end).days <= 70
                and datetime.fromisoformat(r['accepted_at'].replace('Z', '+00:00')) <= as_of]
    if not earnings: return payload
    filing = max(earnings, key=lambda r: r['accepted_at'])
    accession = filing['accession_number']
    if not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession): raise ValueError('earnings_accession_invalid')
    document = filing['primary_document']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', document): raise ValueError('earnings_document_invalid')
    base = f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/'
    directory = cache_root / ticker / accession

    def retained(url, filename):
        path, receipt_path = directory / filename, directory / (filename + '.receipt.json')
        receipt = read_json(receipt_path, {})
        if path.exists():
            raw = path.read_bytes()
            if not receipt:
                # Recover an interrupted first publication only after an
                # actual fresh source response proves these exact old bytes.
                fresh = fetcher(url, user_agent, max_bytes=MAX_BYTES).raw_bytes
                if fresh != raw: raise ValueError('earnings_unclaimed_source_conflict')
                atomic_write_json(receipt_path, {'schema_version':'equity_reported_earnings_source_v1',
                    'ticker':ticker,'cik':cik,'accession':accession,'accepted_at':filing['accepted_at'],
                    'source_url':url,'raw_sha256':hashlib.sha256(raw).hexdigest(),'fetched_at':as_of.isoformat()})
                receipt = read_json(receipt_path)
            from sec_acceptance_corrections import retained_receipt_clock_valid
            if (not raw or len(raw) > MAX_BYTES
                    or receipt.get('schema_version') != 'equity_reported_earnings_source_v1'
                    or receipt.get('ticker') != ticker or receipt.get('cik') != cik
                    or receipt.get('accession') != accession or receipt.get('source_url') != url
                    or not retained_receipt_clock_valid(receipt=receipt,
                        canonical_accepted_at=filing['accepted_at'], ticker=ticker, cik=cik,
                        accession=accession, root=project_root, as_of=as_of)
                    or receipt.get('raw_sha256') != hashlib.sha256(raw).hexdigest()):
                raise ValueError('earnings_retained_source_unverified')
            return raw, path
        raw = fetcher(url, user_agent, max_bytes=MAX_BYTES).raw_bytes
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError('earnings_exhibit_size_invalid')
        atomic_write_bytes(path, raw)
        atomic_write_json(receipt_path, {'schema_version': 'equity_reported_earnings_source_v1',
            'ticker': ticker, 'cik': cik, 'accession': accession, 'accepted_at': filing['accepted_at'],
            'source_url': url, 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'fetched_at': as_of.isoformat()})
        return raw, path

    primary, _ = retained(base + document, 'earnings_primary.raw')
    children = exhibit_rows({'form':'8-K', 'ticker':ticker, 'cik':str(cik),
        'accession':accession, 'primary_document':document, 'url':base+document,
        'source_id':f'{ticker}-{accession}-earnings-primary'}, primary, 'utf-8')
    exhibit_urls = {child['url'] for child in children if child['exhibit_number'] == '99.1'}
    if len(exhibit_urls) != 1 or not all(u.startswith(base) for u in exhibit_urls):
        raise ValueError('earnings_exhibit_link_unverified')
    url = exhibit_urls.pop()
    raw, path = retained(url, 'earnings_exhibit99_1.raw')
    facts = mu_reported_quarter_shares(raw, quarter_periods=quarter_periods) if quarter_periods else reported_quarter_shares(raw, period_end=end.isoformat())
    try: locator = str(path.resolve().relative_to(project_root.resolve()))
    except ValueError: raise ValueError('earnings_source_outside_project') from None
    merged = deepcopy(payload)
    array = merged.setdefault('facts', {}).setdefault('us-gaap', {}).setdefault(SHARES_TAG, {}).setdefault('units', {}).setdefault('shares', [])
    for fact in facts:
        fact.update(form='8-K', filed=filing['filing_date'], accn=accession,
                    _source_kind='sec_earnings_exhibit', _source_url=url, _raw_path=locator,
                    _raw_sha256=hashlib.sha256(raw).hexdigest(), _source_ticker=ticker,
                    _source_cik=cik, _source_accepted_at=filing['accepted_at'],
                    _parent_raw_sha256=hashlib.sha256(primary).hexdigest(), _parent_source_url=base+document)
        existing = [f for f in array if f.get('start') == fact['start'] and f.get('end') == fact['end'] and f.get('accn') == accession]
        if any(f.get('val') != fact['val'] for f in existing): raise ValueError('earnings_share_value_conflict')
        if not existing: array.append(fact)
    return merged
