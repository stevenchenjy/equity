"""Reported quarterly shares from Microsoft's actual furnished earnings exhibit.

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
from urllib.parse import urljoin

from daily_common import ROOT, atomic_write_json, read_json
from refresh_sec_filing_artifacts import atomic_write_bytes, fetch_sec_document

SHARES_TAG = 'WeightedAverageNumberOfDilutedSharesOutstanding'
MAX_BYTES = 5 * 1024 * 1024


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


def supplement_msft_shares(payload: dict, filings: list[dict], user_agent: str, *,
                           as_of: datetime, cache_root: Path, fetcher=fetch_sec_document,
                           project_root: Path = ROOT) -> dict:
    reports = [r for r in filings if r.get('form') in {'10-K', '10-Q'}
               and r.get('report_date') and datetime.fromisoformat(r['accepted_at'].replace('Z', '+00:00')) <= as_of]
    if not reports: return payload
    report = max(reports, key=lambda r: (r['report_date'], r['accepted_at']))
    end = date.fromisoformat(report['report_date'])
    existing = payload.get('facts', {}).get('us-gaap', {}).get(SHARES_TAG, {}).get('units', {}).get('shares', [])
    # Ordinary 10-Q facts usually already report both exact quarter averages.
    # Do not add an avoidable network dependency to an otherwise complete row.
    if end.month in {3, 6, 9, 12}:
        required = {(date(y, end.month - 2, 1).isoformat(), date(y, end.month, end.day).isoformat()) for y in (end.year, end.year - 1)}
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
    base = f'https://www.sec.gov/Archives/edgar/data/789019/{accession.replace("-", "")}/'
    directory = cache_root / 'MSFT' / accession

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
                    'ticker':'MSFT','cik':789019,'accession':accession,'accepted_at':filing['accepted_at'],
                    'source_url':url,'raw_sha256':hashlib.sha256(raw).hexdigest(),'fetched_at':as_of.isoformat()})
                receipt = read_json(receipt_path)
            if (len(raw) > MAX_BYTES or receipt.get('source_url') != url
                    or receipt.get('accepted_at') != filing['accepted_at']
                    or receipt.get('raw_sha256') != hashlib.sha256(raw).hexdigest()):
                raise ValueError('earnings_retained_source_unverified')
            return raw, path
        raw = fetcher(url, user_agent, max_bytes=MAX_BYTES).raw_bytes
        atomic_write_bytes(path, raw)
        atomic_write_json(receipt_path, {'schema_version': 'equity_reported_earnings_source_v1',
            'ticker': 'MSFT', 'cik': 789019, 'accession': accession, 'accepted_at': filing['accepted_at'],
            'source_url': url, 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'fetched_at': as_of.isoformat()})
        return raw, path

    primary, _ = retained(base + document, 'earnings_primary.raw')
    links = Tables(); links.feed(primary.decode('utf-8'))
    exhibit_urls = {urljoin(base, h) for h in links.links if re.fullmatch(r'msft-ex99_1\.htm', h, re.I)}
    if len(exhibit_urls) != 1 or not all(u.startswith(base) for u in exhibit_urls):
        raise ValueError('earnings_exhibit_link_unverified')
    url = exhibit_urls.pop()
    raw, path = retained(url, 'earnings_exhibit99_1.raw')
    facts = reported_quarter_shares(raw, period_end=end.isoformat())
    try: locator = str(path.resolve().relative_to(project_root.resolve()))
    except ValueError: raise ValueError('earnings_source_outside_project') from None
    merged = deepcopy(payload)
    array = merged.setdefault('facts', {}).setdefault('us-gaap', {}).setdefault(SHARES_TAG, {}).setdefault('units', {}).setdefault('shares', [])
    for fact in facts:
        fact.update(form='8-K', filed=filing['filing_date'], accn=accession,
                    _source_kind='sec_earnings_exhibit', _source_url=url, _raw_path=locator,
                    _raw_sha256=hashlib.sha256(raw).hexdigest())
        existing = [f for f in array if f.get('start') == fact['start'] and f.get('end') == fact['end'] and f.get('accn') == accession]
        if any(f.get('val') != fact['val'] for f in existing): raise ValueError('earnings_share_value_conflict')
        if not existing: array.append(fact)
    return merged
