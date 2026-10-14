from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from sec_earnings_tables import reported_quarter_shares, supplement_msft_shares, supplement_reported_shares, mu_reported_quarter_shares
from refresh_daily_evidence import fundamental_row, fact_units

RAW = b'''<p>Microsoft INCOME STATEMENTS (In millions, except per share amounts)</p>
<table><tr><td></td><td>Three Months Ended June 30,</td><td>Twelve Months Ended June 30,</td></tr>
<tr><td></td><td>2026</td><td>2025</td><td>2026</td><td>2025</td></tr>
<tr><td>Weighted average shares outstanding:</td></tr>
<tr><td>Basic</td><td>8</td><td>9</td><td>10</td><td>11</td></tr>
<tr><td>Diluted</td><td>10</td><td>11</td><td>12</td><td>13</td></tr></table>'''

# Retains the actual MU Q4 2026 earnings statement's logical columns, mixed
# quarter/year dates, spacer cells and different GAAP/non-GAAP denominators.
MU_RAW = b'''<p>MICRON TECHNOLOGY, INC. CONSOLIDATED STATEMENTS OF OPERATIONS
(In millions, except per share amounts) (Unaudited)</p>
<table><tr><td></td><td>4th Qtr.</td><td>3rd Qtr.</td><td>4th Qtr.</td><td colspan="2">Year Ended</td></tr>
<tr><td></td><td>September 3,2026</td><td>May 28,2026</td><td>August 28,2025</td><td>September 3,2026</td><td>August 28,2025</td></tr>
<tr><td>Revenue</td><td>$</td><td>54,229</td><td></td><td>$</td><td>41,456</td><td></td><td>$</td><td>11,315</td><td></td><td>$</td><td>133,188</td><td></td><td>$</td><td>37,378</td><td></td></tr>
<tr><td>Earnings per share</td></tr><tr><td>Diluted</td><td>32.87</td><td>24.67</td><td>2.83</td><td>74.33</td><td>7.59</td></tr>
<tr><td>Number of shares used in per share calculations</td></tr>
<tr><td>Basic</td><td>1,130</td><td>1,128</td><td>1,120</td><td>1,127</td><td>1,116</td></tr>
<tr><td>Diluted</td><td>1,147</td><td></td><td>1,145</td><td></td><td>1,131</td><td></td><td>1,143</td><td></td><td>1,125</td><td></td></tr></table>
<p>MICRON TECHNOLOGY, INC. RECONCILIATION OF GAAP TO NON-GAAP MEASURES (In millions, except per share amounts)</p>
<table><tr><td>Non-GAAP weighted-average common shares outstanding - Diluted</td><td>1,149</td><td>1,149</td><td>1,145</td><td>1,149</td><td>1,143</td></tr></table>'''

MU_PERIODS = [
    {'start':'2026-05-29','end':'2026-09-03','val':54_229_000_000},
    {'start':'2025-05-30','end':'2025-08-28','val':11_315_000_000},
]


def mu_fixture():
    from test_financial_period_integrity import facts, duration
    report={'form':'10-K','report_date':'2026-09-03','filing_date':'2026-10-09',
        'accepted_at':'2026-10-09T12:00:00Z','accession_number':'0000723125-26-000023',
        'primary_document':'mu-20260903.htm'}
    earlier={**report,'form':'10-Q','report_date':'2026-05-28','filing_date':'2026-06-25',
        'accepted_at':'2026-06-25T20:00:00Z','accession_number':'0000723125-26-000015'}
    earnings={**report,'form':'8-K','items':'2.02,9.01','filing_date':'2026-09-30',
        'report_date':'2026-09-30','accepted_at':'2026-09-30T20:02:22Z',
        'accession_number':'0000723125-26-000018','primary_document':'mu-20260930.htm'}
    rev=[duration('2025-08-29','2026-09-03',133_188_000_000,report['filing_date'],form='10-K',accn=report['accession_number']),
         duration('2025-08-29','2026-05-28',78_959_000_000,earlier['filing_date'],accn=earlier['accession_number']),
         duration('2024-08-30','2025-08-28',37_378_000_000,report['filing_date'],form='10-K',accn=report['accession_number']),
         duration('2024-08-30','2025-05-29',26_063_000_000,earlier['filing_date'],accn=earlier['accession_number'])]
    shares=[{**r,'val':v} for r,v in zip([rev[0],rev[2]], [1_143_000_000,1_125_000_000])]
    return {'cik':723125,'facts':{'us-gaap':{'Revenues':facts(rev),
        'WeightedAverageNumberOfDilutedSharesOutstanding':facts(shares,'shares')}}}, [report, earlier, earnings]


class EarningsTablesTests(unittest.TestCase):
    def test_mu_actual_fiscal_q4_separates_14_and_13_weeks_from_year_and_nongaap(self):
        values=mu_reported_quarter_shares(MU_RAW,quarter_periods=MU_PERIODS)
        self.assertEqual([(v['start'],v['end'],v['val']) for v in values],
            [('2026-05-29','2026-09-03',1_147_000_000),('2025-05-30','2025-08-28',1_131_000_000)])
        self.assertEqual([v['_fact_id'].rsplit(':',1)[-1] for v in values],['0','2'])
        self.assertTrue(all(v['_period_support'] for v in values))

    def test_mu_cannot_invent_units_quarters_start_end_or_diluted_scope(self):
        for raw, periods in [(MU_RAW.replace(b'(In millions,',b'(In thousands,'),MU_PERIODS),
            (MU_RAW.replace(b'4th Qtr.',b'Year Ended'),MU_PERIODS),
            (MU_RAW.replace(b'Number of shares used in per share calculations',b'Number of employees'),MU_PERIODS),
            (MU_RAW, [MU_PERIODS[0]]), (MU_RAW,[{**MU_PERIODS[0],'start':'2025-08-29'},MU_PERIODS[1]]),
            (MU_RAW.replace(b'54,229',b'54,228'),MU_PERIODS),
            (MU_RAW,[{**MU_PERIODS[0],'end':'2026-09-04'},MU_PERIODS[1]])]:
            with self.subTest(raw=raw,periods=periods):
                with self.assertRaises(ValueError):mu_reported_quarter_shares(raw,quarter_periods=periods)

    def test_mu_changed_column_order_is_bound_to_dates_and_labels(self):
        raw=MU_RAW.replace(b'September 3,2026</td><td>May 28,2026</td><td>August 28,2025',
                           b'August 28,2025</td><td>May 28,2026</td><td>September 3,2026')
        raw=raw.replace(b'54,229',b'temp').replace(b'11,315',b'54,229').replace(b'temp',b'11,315')
        raw=raw.replace(b'1,147',b'temp').replace(b'1,131',b'1,147').replace(b'temp',b'1,131')
        self.assertEqual([v['val'] for v in mu_reported_quarter_shares(raw,quarter_periods=MU_PERIODS)], [1_147_000_000,1_131_000_000])

    def test_mu_adapter_actual_parent_description_link_changed_name_and_canonical_dilution(self):
        payload,filings=mu_fixture()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);calls=[]
            def fetch(url,agent,**kwargs):
                calls.append(url)
                return SimpleNamespace(raw_bytes=MU_RAW if url.endswith('changed-release.htm') else
                    b'<table><tr><td>99.1</td><td></td><td><a href="changed-release.htm">Press Release issued on September 30, 2026</a></td></tr></table>')
            options=dict(as_of=datetime(2026,10,14,tzinfo=timezone.utc),cache_root=root/'cache',fetcher=fetch,project_root=root)
            merged=supplement_reported_shares('MU',723125,payload,filings,'test',**options)
            self.assertEqual(len(calls),2)
            accepted={f['accession_number']:f['accepted_at'] for f in filings}
            row=fundamental_row('MU',723125,merged,'2026-10-14T00:00:00Z',acceptance_by_accession=accepted)
            self.assertEqual(row['diluted_shares_latest'],'1147000000.00')
            self.assertEqual(row['diluted_shares_prior_year'],'1131000000.00')
            self.assertEqual(row['share_dilution_pct'],'1.41')
            import json
            provenance=json.loads(row['field_provenance_json'])['diluted_shares_latest']
            self.assertEqual(provenance['period_support']['start'],'2026-05-29')
            self.assertEqual(provenance['source_accepted_at'],'2026-09-30T20:02:22Z')
            self.assertEqual(provenance['parent_source_url'].rsplit('/',1)[-1],'mu-20260930.htm')
            self.assertEqual(provenance['available_at_utc'],'2026-10-09T12:00:00+00:00')
            # Period support is not available on release day. A cached fact
            # cannot make the later annual/YTD boundaries available early.
            before=fact_units(merged,('WeightedAverageNumberOfDilutedSharesOutstanding',),'shares',
                as_of=datetime(2026,10,1,tzinfo=timezone.utc),acceptance_by_accession=accepted)
            self.assertFalse(any(v.get('form')=='8-K' for v in before))
            self.assertEqual(payload['facts']['us-gaap']['WeightedAverageNumberOfDilutedSharesOutstanding']['units']['shares'][0]['val'],1_143_000_000)
            self.assertEqual(supplement_reported_shares('MU',723125,payload,filings,'test',**options),merged)
            self.assertEqual(len(calls),2)
            bad=deepcopy(merged)
            bad['facts']['us-gaap']['WeightedAverageNumberOfDilutedSharesOutstanding']['units']['shares'][-1]['_source_cik']=789019
            self.assertFalse(any(v.get('form')=='8-K' and v['end']=='2025-08-28' for v in fact_units(bad,
                ('WeightedAverageNumberOfDilutedSharesOutstanding',),'shares',acceptance_by_accession=accepted)))

    def test_mu_complete_exact_quarters_skip_network_and_unsupported_periods_remain_missing(self):
        from unittest.mock import Mock
        payload,filings=mu_fixture()
        shares=payload['facts']['us-gaap']['WeightedAverageNumberOfDilutedSharesOutstanding']['units']['shares']
        shares.extend({**period,'form':'10-Q','filed':'2026-10-09','val':1_000_000_000} for period in MU_PERIODS)
        fetch=Mock(side_effect=AssertionError('No source fetch needed'))
        self.assertIs(supplement_reported_shares('MU',723125,payload,filings,'',as_of=datetime(2026,10,14,tzinfo=timezone.utc),cache_root=Path('/unused'),fetcher=fetch),payload)
        del payload['facts']['us-gaap']['Revenues']
        with self.assertRaisesRegex(ValueError,'fiscal_period_support_unverified'):
            supplement_reported_shares('MU',723125,payload,filings,'',as_of=datetime(2026,10,14,tzinfo=timezone.utc),cache_root=Path('/unused'),fetcher=fetch)
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
