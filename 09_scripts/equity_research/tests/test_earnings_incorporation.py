from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import canonical_sha256, read_csv
from earnings_incorporation import (assess_company, retain_sec_response, write_selection_receipt,
                                    CACHE_REL, build_earnings_incorporation, reconcile_cached_financial_selections)
from latest_report_facts import inline_report_facts, supplement_cached_latest_report
from refresh_daily_evidence import recent_filings, fundamental_row

NOW = datetime(2026, 9, 24, 21, tzinfo=timezone.utc)
ACC = '0000000001-26-000002'
OLD = '0000000001-26-000001'
XML = b'''<html xmlns:xbrli="http://www.xbrl.org/2003/instance"
xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:us-gaap="http://fasb.org/us-gaap/2025">
<xbrli:context id="quarter"><xbrli:entity><xbrli:identifier>0000000001</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="segment"><xbrli:entity><xbrli:identifier>0000000001</xbrli:identifier><xbrli:segment/></xbrli:entity>
<xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
<ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="quarter">June 30, 2026</ix:nonNumeric>
<ix:nonFraction name="us-gaap:Revenues" contextRef="quarter" unitRef="usd" scale="3" format="ixt:num-dot-decimal" id="rev">341,871</ix:nonFraction>
<ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="quarter" unitRef="usd" scale="3" sign="-" format="ixt:num-dot-decimal">5,000</ix:nonFraction>
<ix:nonFraction name="us-gaap:Revenues" contextRef="segment" unitRef="usd" scale="3" format="ixt:num-dot-decimal">999,999</ix:nonFraction>
</html>'''


class IncorporationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.sub = {'cik': '0000000001', 'filings': {'recent': {
            'accessionNumber': [ACC], 'form': ['10-Q'], 'reportDate': ['2026-06-30'],
            'filingDate': ['2026-08-01'], 'acceptanceDateTime': ['2026-08-01T20:00:00Z'],
            'items': [''], 'primaryDocument': ['report.htm']}}}
        self.fund = {'ticker': 'ABC', 'latest_period_end': '2026-06-30', 'data_quality': 'ok',
            'field_provenance_json': json.dumps({'revenue_latest': {'accn': ACC, 'end': '2026-06-30'}})}
        self.receipt = self.save_receipt()

    def save_receipt(self):
        sub = retain_sec_response(json.dumps(self.sub).encode(), url='https://data.sec.gov/submissions/CIK0000000001.json',
            retrieved_at=NOW.isoformat(), root=self.root)
        facts = retain_sec_response(b'{"cik":1,"facts":{}}', url='https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json',
            retrieved_at=NOW.isoformat(), root=self.root)
        with patch('earnings_incorporation.iso_now', return_value=NOW.isoformat()):
            write_selection_receipt(ticker='ABC', cik=1, fundamental=self.fund, filings=[],
                submissions_receipt=sub, companyfacts_receipt=facts, diagnostic={}, root=self.root)
        return json.loads((self.root / CACHE_REL / 'ABC.selection.json').read_text())

    def assess(self, **kwargs):
        return assess_company('ABC', kwargs.pop('fundamental', self.fund), kwargs.pop('receipt', self.receipt),
            root=self.root, now=kwargs.pop('now', NOW), ledger=kwargs.pop('ledger', []), news=kwargs.pop('news', {}))

    def test_current_numerical_selection_is_separate_from_thesis_completion(self):
        row = self.assess()
        self.assertEqual(row['status'], 'incorporated')
        self.assertTrue(row['positive_decision_eligible'])
        self.assertTrue(row['thesis_review_separate'])
        self.assertEqual(row['latest_report_period_end'], '2026-06-30')
        self.assertEqual(row['latest_material_published_at'], '2026-08-01T20:00:00+00:00')
        self.assertEqual(row['retrieved_at'], NOW.isoformat())
        self.assertEqual(row['incorporated_at'], NOW.isoformat())

    def test_fresh_download_with_old_financial_period_is_blocked(self):
        self.fund.update(latest_period_end='2026-03-31', field_provenance_json=json.dumps({'revenue_latest': {'accn': OLD}}))
        self.receipt = self.save_receipt()
        row = self.assess()
        self.assertFalse(row['positive_decision_eligible'])
        self.assertIn('latest_earnings_pending_incorporation', row['blocking_reasons'])
        self.assertEqual(row['incorporated_at'], '')

    def test_economic_fingerprint_changes_for_values_but_not_poll_timestamp(self):
        first = self.assess()['financial_economic_sha256']
        self.fund['fetched_at'] = NOW.isoformat()
        self.assertEqual(first, self.assess()['financial_economic_sha256'])
        self.fund['revenue_latest'] = '123.00'
        self.assertNotEqual(first, self.assess()['financial_economic_sha256'])

    def test_raw_tampering_and_selection_drift_cannot_reuse_a_pass(self):
        (self.root / self.receipt['companyfacts']['raw_path']).write_text('{"cik":1}')
        self.assertIn('raw_source_snapshot_unverified', self.assess()['blocking_reasons'])
        self.fund['data_quality'] = 'insufficient'
        self.assertIn('financial_selection_receipt_mismatch', self.assess()['blocking_reasons'])

    def test_newer_earnings_8k_waits_for_incorporation(self):
        recent = self.sub['filings']['recent']
        for key, val in {'accessionNumber': '0000000001-26-000003', 'form': '8-K', 'reportDate':'2026-09-24',
                         'filingDate':'2026-09-24','acceptanceDateTime':'2026-09-24T20:00:00Z',
                         'items':'2.02,9.01','primaryDocument':'earnings.htm'}.items(): recent[key].insert(0,val)
        self.receipt=self.save_receipt()
        row=self.assess()
        self.assertIn('newer_earnings_release_pending_incorporation', row['blocking_reasons'])
        self.assertEqual(row['latest_material_accession'], '0000000001-26-000003')

    def test_old_receipt_after_new_ledger_or_results_news_is_blocked(self):
        ledger=[{'ticker':'ABC','form':'8-K','items':'2.02','filing_date':'2026-09-24','accession_number':'new'}]
        self.assertIn('material_ledger_ahead_of_verified_submission',self.assess(ledger=ledger)['blocking_reasons'])
        event={'ticker':'ABC','title':'Reports third quarter results','published_at':NOW.isoformat()}
        self.assertIn('newer_official_results_news_pending_review',self.assess(news={'events':[event]})['blocking_reasons'])
        event['title']='To announce third quarter results conference call'
        self.assertEqual(self.assess(news={'events':[event]})['status'],'incorporated')

    def install_news(self, published):
        from official_news import load_manifest, refresh_news
        import csv
        manifest=load_manifest()
        manifest['sources']=[{'source_id':'issuer','ticker':'ABC','url':'https://ir.example.com/feed',
            'allowed_hosts':['ir.example.com'],'format':'rss_atom','required':True}]
        mp=self.root/'01_policies/official_news_sources.json';mp.parent.mkdir(parents=True);mp.write_text(json.dumps(manifest))
        directory=self.root/'03_source_data/equity_research';directory.mkdir(parents=True,exist_ok=True)
        with (directory/'daily_fundamentals.csv').open('w',newline='') as out:
            writer=csv.DictWriter(out,fieldnames=list(self.fund));writer.writeheader();writer.writerow(self.fund)
        raw=f'<rss><channel><item><title>Reports quarterly results</title><link>https://ir.example.com/results</link><pubDate>{published.isoformat()}</pubDate></item></channel></rss>'.encode()
        return refresh_news(now=NOW,manifest_path=mp,
            status_path=directory/'official_news_status.local.json',events_path=directory/'official_news_events.local.json',
            fetcher=lambda *a,**k:raw)

    def test_historical_feed_archive_does_not_reopen_current_financial_selection(self):
        # The same-day press release follows the incorporated SEC report, but
        # is months old when this issuer's feed is first configured.
        self.install_news(datetime(2026,8,1,20,25,tzinfo=timezone.utc))
        raw=json.loads((self.root/'03_source_data/equity_research/official_news_events.local.json').read_text())
        self.assertEqual(len(raw['events']),1)
        result=build_earnings_incorporation(root=self.root,now=NOW)['companies']['ABC']
        self.assertEqual(result['status'],'incorporated')
        self.assertEqual(len(json.loads((self.root/'03_source_data/equity_research/official_news_events.local.json').read_text())['events']),1)

    def test_retained_unresolved_results_do_not_expire_with_feed_window(self):
        from issuer_news_queue import merge_news_context
        news=self.install_news(NOW-timedelta(hours=1))
        (self.root/'04_research/company_research').mkdir(parents=True)
        merge_news_context(news,root=self.root,current=NOW,persist=True)
        current=build_earnings_incorporation(root=self.root,now=NOW)['companies']['ABC']
        later=build_earnings_incorporation(root=self.root,now=NOW+timedelta(days=8))['companies']['ABC']
        self.assertIn('newer_official_results_news_pending_review',current['blocking_reasons'])
        self.assertIn('newer_official_results_news_pending_review',later['blocking_reasons'])

    def test_missing_or_future_financial_period_cannot_claim_incorporation(self):
        self.sub['filings']['recent']['reportDate']=['']
        self.receipt=self.save_receipt()
        self.assertIn('latest_report_period_unknown',self.assess()['blocking_reasons'])
        row=self.assess(now=NOW+timedelta(hours=37))
        self.assertIn('companyfacts_retrieval_stale_or_missing',row['blocking_reasons'])
        self.assertFalse(row['positive_decision_eligible'])

    def test_retrieval_is_not_retroactively_incorporated(self):
        self.receipt['selected_at']=(NOW-timedelta(minutes=5)).isoformat()
        self.assertIn('incorporation_timestamp_unverified',self.assess()['blocking_reasons'])

    def test_cik_identity_and_paths_are_verified(self):
        with self.assertRaises(ValueError):
            retain_sec_response(b'{"cik":2}',url='https://data.sec.gov/submissions/CIK0000000001.json',
                retrieved_at=NOW.isoformat(),root=self.root)
        self.receipt['companyfacts']['raw_path']='../../elsewhere.json'
        self.assertIn('raw_source_snapshot_unverified',self.assess()['blocking_reasons'])

    def test_new_holding_without_financial_row_is_visible_unknown(self):
        path=self.root/'05_risk_and_positions/current_positions.local.csv';path.parent.mkdir(parents=True)
        path.write_text('ticker\nNEW\nSPY\n')
        result=build_earnings_incorporation(root=self.root,now=NOW)
        self.assertEqual(result['held_pending_tickers'],['NEW'])
        self.assertEqual(result['companies']['NEW']['status'],'unknown')


class InlineFallbackTests(unittest.TestCase):
    def test_amazon_ppe_label_is_bound_to_the_actual_tagged_row(self):
        raw = XML.replace(b'0000000001', b'0001018724').replace(b'</html>', b'''<table><tr>
        <td>Purchases of property and equipment</td><td><ix:nonFraction
        name="us-gaap:PaymentsToAcquireProductiveAssets" contextRef="quarter" unitRef="usd"
        scale="6" format="ixt:num-dot-decimal" id="ppe">54,208</ix:nonFraction></td></tr></table></html>''')
        facts, _ = inline_report_facts(raw, artifact=self.artifact, cik=1018724,
            filing=self.filing, allowed_tags={'PaymentsToAcquireProductiveAssets'})
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['val'], 54_208_000_000)
        self.assertEqual(facts[0]['_reported_label'], 'Purchases of property and equipment')
        other, _ = inline_report_facts(raw.replace(b'Purchases of property and equipment', b'Purchases of productive assets and intangibles'),
            artifact=self.artifact, cik=1018724, filing=self.filing, allowed_tags={'PaymentsToAcquireProductiveAssets'})
        self.assertNotIn('_reported_label', other[0])

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.filing={'accession_number':ACC,'form':'10-Q','filing_date':'2026-08-01',
            'accepted_at':'2026-08-01T20:00:00Z','report_date':'2026-06-30','primary_document':'report.htm'}
        self.artifact={'ticker':'ABC','accession':ACC,'form':'10-Q','cik':'1','url':
            'https://www.sec.gov/Archives/edgar/data/1/'+ACC.replace('-','')+'/report.htm',
            'raw_path':'02_filings/report.raw','raw_sha256':hashlib.sha256(XML).hexdigest()}
        path=self.root/self.artifact['raw_path'];path.parent.mkdir(parents=True);path.write_bytes(XML)
        index=self.root/'03_source_data/equity_research/sec_filing_artifact_index.json';index.parent.mkdir(parents=True)
        index.write_text(json.dumps({'artifacts':[self.artifact]}))

    def test_actual_context_and_scale_prevent_segment_or_unit_mix(self):
        facts,period=inline_report_facts(XML,artifact=self.artifact,cik=1,filing=self.filing,
                                       allowed_tags={'Revenues','NetIncomeLoss'})
        self.assertEqual(period,'2026-06-30')
        self.assertEqual({f['_tag']:f['val'] for f in facts},{'Revenues':341871000,'NetIncomeLoss':-5000000})
        self.assertTrue(all(f['_raw_sha256']==self.artifact['raw_sha256'] for f in facts))

    def test_current_cover_date_does_not_hide_missing_current_statement_fields(self):
        payload={'cik':1,'facts':{'dei':{'EntityCommonStockSharesOutstanding':{'units':{'shares':[
            {'end':'2026-07-23','filed':'2026-08-01','form':'10-Q','accn':ACC,'val':100}]}}}}}
        merged,diagnostic=supplement_cached_latest_report(payload,ticker='ABC',cik=1,
            filings=[self.filing],root=self.root,as_of=NOW,allowed_tags={'Revenues','NetIncomeLoss'})
        self.assertEqual(diagnostic['status'],'verified_inline_report_supplement')
        row=fundamental_row('ABC',1,merged,NOW.isoformat())
        self.assertEqual(row['revenue_latest'],'341871000.00')
        self.assertEqual(row['net_income_latest'],'-5000000.00')
        self.assertEqual(payload['facts'].keys(),{'dei'})

    def test_companyfacts_endpoint_lag_is_repaired_from_verified_report(self):
        merged,diagnostic=supplement_cached_latest_report({'cik':1,'facts':{}},ticker='ABC',cik=1,
            filings=[self.filing],root=self.root,as_of=NOW,allowed_tags={'Revenues','NetIncomeLoss'})
        row=fundamental_row('ABC',1,merged,NOW.isoformat(),acceptance_by_accession={ACC:self.filing['accepted_at']})
        self.assertEqual(diagnostic['status'],'verified_inline_report_supplement')
        self.assertEqual(row['latest_period_end'],'2026-06-30')
        self.assertEqual(row['revenue_latest'],'341871000.00')
        self.assertEqual(row['debt_latest'],'')  # Never manufacture complete valuation.
        provenance=json.loads(row['field_provenance_json'])['revenue_latest']
        self.assertEqual(provenance['raw_sha256'],self.artifact['raw_sha256'])

    def test_same_cycle_document_arrival_advances_period_offline_without_fabricating_quality(self):
        from daily_common import atomic_write_csv
        from refresh_daily_evidence import FUNDAMENTAL_FIELDS
        old = {'ticker':'ABC', 'cik':'1', 'fetched_at':NOW.isoformat(),
               'latest_period_end':'2026-03-31', 'data_quality':'ok', 'field_provenance_json':'{}'}
        sub = {'cik':1, 'filings':{'recent':{'accessionNumber':[ACC], 'form':['10-Q'],
            'filingDate':['2026-08-01'], 'reportDate':['2026-06-30'],
            'acceptanceDateTime':['2026-08-01T20:00:00Z'], 'primaryDocument':['report.htm'], 'items':['']}}}
        sr=retain_sec_response(json.dumps(sub).encode(),url='https://data.sec.gov/submissions/CIK0000000001.json',
            retrieved_at=NOW.isoformat(),root=self.root)
        fr=retain_sec_response(b'{"cik":1,"facts":{}}',url='https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json',
            retrieved_at=NOW.isoformat(),root=self.root)
        path=self.root/'03_source_data/equity_research/daily_fundamentals.csv'
        atomic_write_csv(path,FUNDAMENTAL_FIELDS,[old])
        # Receipt binds the actual CSV row, including its intentionally empty fields.
        import csv
        old=read_csv(path)[0]
        with patch('earnings_incorporation.iso_now',return_value=NOW.isoformat()):
            write_selection_receipt(ticker='ABC',cik=1,fundamental=old,filings=[self.filing],
                submissions_receipt=sr,companyfacts_receipt=fr,diagnostic={},root=self.root)
            self.assertEqual(reconcile_cached_financial_selections(root=self.root,now=NOW),['ABC'])
        row=read_csv(path)[0]
        self.assertEqual(row['latest_period_end'],'2026-06-30')
        self.assertEqual(row['revenue_latest'],'341871000.00')
        self.assertEqual(reconcile_cached_financial_selections(root=self.root,now=NOW),[])
        self.assertFalse(build_earnings_incorporation(root=self.root,now=NOW)['companies']['ABC']['positive_decision_eligible'])
        self.assertGreaterEqual(len(list((self.root/CACHE_REL/'selections').glob('*.json'))),2)

    def test_changed_report_hash_wrong_period_and_no_cache_fail_closed(self):
        (self.root/self.artifact['raw_path']).write_bytes(XML+b' ')
        merged,diagnostic=supplement_cached_latest_report({'cik':1,'facts':{}},ticker='ABC',cik=1,
            filings=[self.filing],root=self.root,as_of=NOW,allowed_tags={'Revenues'})
        self.assertEqual(diagnostic['status'],'report_cache_hash_mismatch')
        self.assertEqual(merged['facts'],{})
        with self.assertRaisesRegex(ValueError,'period_identity_conflict'):
            inline_report_facts(XML,artifact=self.artifact,cik=1,filing=self.filing|{'report_date':'2026-07-31'},allowed_tags={'Revenues'})

    def test_ambiguous_duplicate_fact_is_not_admitted(self):
        duplicate=XML.replace(b'</html>',b'<ix:nonFraction name="us-gaap:Revenues" contextRef="quarter" unitRef="usd" scale="3" format="ixt:num-dot-decimal">999</ix:nonFraction></html>')
        facts,_=inline_report_facts(duplicate,artifact=self.artifact,cik=1,filing=self.filing,allowed_tags={'Revenues'})
        self.assertEqual(facts,[])


if __name__=='__main__': unittest.main()
