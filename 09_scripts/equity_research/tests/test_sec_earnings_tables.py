from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from sec_earnings_tables import reported_quarter_shares, supplement_msft_shares
from refresh_daily_evidence import fundamental_row

RAW = b'''<p>Microsoft INCOME STATEMENTS (In millions, except per share amounts)</p>
<table><tr><td></td><td>Three Months Ended June 30,</td><td>Twelve Months Ended June 30,</td></tr>
<tr><td></td><td>2026</td><td>2025</td><td>2026</td><td>2025</td></tr>
<tr><td>Weighted average shares outstanding:</td></tr>
<tr><td>Basic</td><td>8</td><td>9</td><td>10</td><td>11</td></tr>
<tr><td>Diluted</td><td>10</td><td>11</td><td>12</td><td>13</td></tr></table>'''


class EarningsTablesTests(unittest.TestCase):
    def test_reported_quarter_is_not_the_annual_or_basic_denominator(self):
        values = reported_quarter_shares(RAW, period_end='2026-06-30')
        self.assertEqual([(r['start'], r['end'], r['val']) for r in values],
            [('2026-04-01', '2026-06-30', 10_000_000), ('2025-04-01', '2025-06-30', 11_000_000)])

    def test_units_period_and_missing_diluted_row_cannot_be_invented(self):
        for raw, period in [(RAW.replace(b'millions', b'thousands'), '2026-06-30'),
                            (RAW.replace(b'Diluted', b'Unknown'), '2026-06-30'),
                            (RAW, '2026-09-30')]:
            with self.subTest(period=period, raw=raw):
                with self.assertRaises(ValueError): reported_quarter_shares(raw, period_end=period)

    def test_conflicting_tables_are_rejected(self):
        with self.assertRaises(ValueError):
            reported_quarter_shares(RAW + RAW.replace(b'<td>10</td><td>11</td>', b'<td>20</td><td>21</td>'), period_end='2026-06-30')

    def test_quarter_only_statement_does_not_require_an_annual_average(self):
        raw=RAW.replace(b'<td>Twelve Months Ended June 30,</td>',b'').replace(b'<td>2026</td><td>2025</td><td>2026</td><td>2025</td>',b'<td>2026</td><td>2025</td>').replace(b'<td>12</td><td>13</td>',b'')
        self.assertEqual(reported_quarter_shares(raw,period_end='2026-06-30')[0]['val'],10_000_000)

    def test_complete_current_quarter_companyfacts_needs_no_exhibit_fetch(self):
        from unittest.mock import Mock
        report={'form':'10-Q','report_date':'2026-06-30','accepted_at':'2026-07-29T20:00:00Z'}
        data={'facts':{'us-gaap':{'WeightedAverageNumberOfDilutedSharesOutstanding':{'units':{'shares':[
            {'form':'10-Q','filed':'2026-07-29','start':f'{y}-04-01','end':f'{y}-06-30','val':100} for y in (2026,2025)]}}}}}
        fetch=Mock(side_effect=AssertionError('No source fetch needed'))
        self.assertIs(supplement_msft_shares(data,[report],'',as_of=datetime(2026,7,30,tzinfo=timezone.utc),cache_root=Path('/unused'),fetcher=fetch),data)

    def test_ordinary_8k_fact_is_not_accepted_as_verified_reported_shares(self):
        from test_financial_period_integrity import fixture, row, facts, duration
        payload = fixture()
        payload['facts']['us-gaap']['WeightedAverageNumberOfDilutedSharesOutstanding'] = facts([
            duration('2026-04-01', '2026-06-30', 100, form='8-K')], 'shares')
        self.assertEqual(row(payload)['diluted_shares_latest'], '')

    def test_actual_exhibit_link_cache_hash_and_acceptance_are_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            filing = {'form':'8-K','items':'2.02,9.01','filing_date':'2026-07-29',
                'accepted_at':'2026-07-29T20:00:00Z','accession_number':'0001193125-26-323632',
                'primary_document':'msft-20260729.htm'}
            report = {**filing, 'form':'10-K','report_date':'2026-06-30'}
            calls=[]
            def fetch(url, agent, **kwargs):
                calls.append(url)
                return SimpleNamespace(raw_bytes=RAW if url.endswith('msft-ex99_1.htm') else b'<a href="msft-ex99_1.htm">99.1</a>')
            options=dict(as_of=datetime(2026,7,30,tzinfo=timezone.utc),cache_root=root/'cache',fetcher=fetch,project_root=root)
            first=supplement_msft_shares({'cik':789019,'facts':{}},[report,filing],'public-agent',**options)
            self.assertEqual(len(calls),2)
            values=first['facts']['us-gaap']['WeightedAverageNumberOfDilutedSharesOutstanding']['units']['shares']
            self.assertTrue(all(r['form']=='8-K' and r['_source_kind']=='sec_earnings_exhibit' and len(r['_raw_sha256'])==64 for r in values))
            supplement_msft_shares({'cik':789019,'facts':{}},[report,filing],'public-agent',**options)
            self.assertEqual(len(calls),2)
            # A crash after bytes but before their first receipt can recover
            # only by re-observing and comparing the actual source bytes.
            cached=root/values[0]['_raw_path']
            cached.with_name(cached.name+'.receipt.json').unlink()
            recovered=supplement_msft_shares({'cik':789019,'facts':{}},[report,filing],'public-agent',**options)
            self.assertEqual(len(calls),3)
            self.assertEqual(recovered,first)
            path=root/values[0]['_raw_path'];path.write_bytes(b'tampered')
            with self.assertRaisesRegex(ValueError,'retained_source_unverified'):
                supplement_msft_shares({'cik':789019,'facts':{}},[report,filing],'public-agent',**options)
