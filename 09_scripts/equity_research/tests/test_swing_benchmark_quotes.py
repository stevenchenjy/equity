from __future__ import annotations

from copy import deepcopy
import csv
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from _support import SCRIPT_DIR
from daily_common import ExclusiveFileLock
import test_intraday_prices as fixture
import intraday_prices as feed
import market_backup as backup
import swing_benchmark_quotes as pairs
import swing_candidate_quotes as stocks
import swing_research as old
import swing_research_v2 as study


class BenchmarkQuoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'equity';self.root.mkdir()
        self.current=fixture.moment('2026-10-22T10:00:12-04:00')
        path=self.root/feed.BASELINE;path.parent.mkdir(parents=True)
        with path.open('w') as stream:
            writer=csv.DictWriter(stream,fieldnames=['ticker','last_price','market_session_date','data_quality_label','data_timestamp'])
            writer.writeheader();writer.writerows([dict(ticker=t,last_price=p,market_session_date='2026-10-21',data_quality_label='ok',data_timestamp='2026-10-21T16:30:00-04:00')
                for t,p in [('MSFT','510'),('SPY','770'),('QQQM','200')]])
        fixture.seed_admitted_history(self.root)
        active=self.root/'00_project_control/active_decision_state.yaml';active.parent.mkdir(parents=True)
        active.write_text(json.dumps(dict(current_workflow='daily_decision',active_pipeline='phase5r_daily',broker_connection_allowed='no',order_code_allowed='no',manual_execution_only='yes')))
        inhibit=self.root/'07_automation/scheduler/maintenance_inhibit.local.json';inhibit.parent.mkdir(parents=True)
        inhibit.write_text(json.dumps(dict(active=False,allowed_pipeline='phase5r_daily')))
        self.observation=dict(observation_id='original',source_session='2026-10-21',valid_session='2026-10-22',
            review_windows=[dict(id='morning',starts_at='2026-10-22T09:45:00-04:00',ends_at='2026-10-22T10:45:00-04:00')])
        self.entry=dict(kind='window_evaluation',record_hash='a'*64,observation_id='original',ticker='MSFT',window_id='morning',
            state='condition_observed',first_qualifying_entry=True,recorded_at='2026-10-22T10:00:11-04:00',entry_method='observed_owner_window_mark_not_fill',
            quote_observation=dict(price=510.,trade_at='2026-10-22T10:00:05-04:00',observed_at='2026-10-22T10:00:10-04:00'))
        self.entries={self.entry['record_hash']:self.entry};self.observations={'original':self.observation}
        self.guard={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def tearDown(self):self.temp.cleanup()
    def client(self,values=None):
        values=values or {t:fixture.payload(t,price=price,change='0',pct='0%',stamp='Oct 22, 2026 10:00:10 AM ET',asset='ETF')
                         for t,price in [('SPY','$770'),('QQQM','$200')]}
        return feed.NasdaqIntradayClient(self.root,get=lambda url:json.dumps(values[url.split('/quote/')[1].split('/')[0]]).encode(),sleep=lambda _:None,now=lambda:self.current)
    def collect(self,**kw):
        with patch.object(pairs,'_entries',return_value=(self.entries,self.observations)):
            return pairs.collect(self.root,current=self.current,clock=lambda:self.current,remaining_seconds=60,client=kw.pop('client',None) or self.client(),**kw)
    def read(self,current=None):
        with patch.object(pairs,'_entries',return_value=(self.entries,self.observations)):
            return pairs.admitted_pairs(self.root,current or self.current)
    def unchanged(self):
        for relative,raw in self.guard.items():self.assertEqual((self.root/relative).read_bytes(),raw)
        self.assertFalse((self.root/feed.CURRENT).exists());self.assertFalse((self.root/stocks.CURRENT).exists())

    def test_real_etf_sources_pair_to_entry_and_do_not_mutate_account_or_held_current(self):
        result=self.collect();self.assertEqual(result['request_count'],2);self.assertEqual(result['paired_entries'],1)
        view=self.read();self.assertEqual(view['status'],'paired');self.assertEqual(len(view['pairs']),1)
        pair=view['pairs'][0]
        self.assertEqual(pair['entry_observation_record_hash'],self.entry['record_hash']);self.assertEqual(set(pair['benchmarks']),{'SPY','QQQM'})
        self.assertEqual(pair['pair_max_span_seconds'],5);self.assertEqual(pair['stock_quote'],self.entry['quote_observation'])
        self.assertFalse(pair['capital_authority']);self.assertEqual(pair['actionable_quantity'],0);self.assertFalse(pair['execution_quote'])
        self.unchanged()
        no_network=Mock();again=self.collect(client=no_network);no_network.fetch.assert_not_called()
        self.assertEqual(again['request_count'],0);self.assertEqual(again['status'],'no_new_entry_observations')

    def test_no_genuine_entry_no_window_no_budget_and_active_claim_make_zero_requests(self):
        no_network=Mock()
        with patch.object(pairs,'_entries',return_value=({},{})):
            self.assertEqual(pairs.collect(self.root,current=self.current,clock=lambda:self.current,remaining_seconds=60,client=no_network)['status'],'no_new_entry_observations')
        self.assertEqual(pairs.collect(self.root,current=self.current,remaining_seconds=10,client=no_network)['status'],'deferred_remaining_worker_budget')
        self.assertEqual(pairs.collect(self.root,current=self.current.replace(hour=12),remaining_seconds=60,client=no_network)['status'],'outside_review_window')
        path=self.root/'00_project_control/run_logs/short_assessment.local.json'
        path.write_text(json.dumps({'slots':{'active':{'status':'claimed','expires_at':(self.current+timedelta(minutes=1)).isoformat()}}}))
        self.assertEqual(self.collect(client=no_network)['status'],'deferred_changed_window_or_active_claim')
        no_network.fetch.assert_not_called()

    def test_runtime_lock_defers_without_waiting_or_touching_claim(self):
        with ExclusiveFileLock(self.root.parent/'.locks/equity-research-runtime.lock'):
            self.assertEqual(self.collect()['status'],'deferred_mutation_lock')
        self.unchanged()

    def test_delayed_dateonly_partial_and_wrong_asset_are_not_pairs_and_never_refetched(self):
        good={t:fixture.payload(t,price=price,change='0',pct='0%',stamp='Oct 22, 2026 10:00:10 AM ET',asset='ETF') for t,price in [('SPY','$770'),('QQQM','$200')]}
        for mode in ('delayed','dateonly','asset'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as directory:
                # A fresh namespace permits a separate deterministic attempt.
                saved=self.root;self.root=Path(directory)/'equity';self.root.mkdir()
                for rel,raw in self.guard.items():
                    p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
                values=deepcopy(good)
                if mode=='delayed':values['QQQM']['data']['primaryData']['isRealTime']=False
                elif mode=='dateonly':values['QQQM']['data']['primaryData']['lastTradeTimestamp']='Oct 22, 2026'
                else:values['QQQM']['data']['assetClass']='STOCKS'
                result=self.collect(client=self.client(values));self.assertEqual(result['paired_entries'],0)
                self.assertEqual(self.read()['pairs'],[])
                client=Mock();self.collect(client=client);client.fetch.assert_not_called();self.root=saved

    def test_trade_skew_or_late_stock_observation_is_a_dependency_without_open_substitution(self):
        values={t:fixture.payload(t,price=price,change='0',pct='0%',stamp='Oct 22, 2026 9:57:30 AM ET',asset='ETF') for t,price in [('SPY','$770'),('QQQM','$200')]}
        self.assertEqual(self.collect(client=self.client(values))['paired_entries'],0)
        self.assertIn('stock_benchmark_trade_clocks_not_matched',self.read()['dependencies'][0]['reason'])
        self.current+=timedelta(minutes=4);client=Mock();self.collect(client=client);client.fetch.assert_not_called()
        self.assertNotIn('open',self.read()['dependencies'][0]['reason'])

    def test_historical_pair_survives_later_current_pointer_and_account_changes(self):
        self.collect();before=self.read()['pairs']
        (self.root/feed.BASELINE).write_text('next session current CSV')
        (self.root/backup.CURRENT).write_text('next session pointer')
        (self.root/'05_risk_and_positions').mkdir(exist_ok=True)
        (self.root/'05_risk_and_positions/current_positions.local.csv').write_text('later account update')
        after=self.read(self.current+timedelta(days=2))
        self.assertEqual(after['pairs'],before)
        self.assertFalse(after['pairs'][0]['execution_quote'])

    def test_original_http_raw_and_archived_baseline_tampering_are_rejected(self):
        self.collect();view=self.read();value=pairs._read(self.root,view['pairs'][0]['source'],'snapshots')
        paths=[value['rows']['SPY']['source']['path'],value['rows']['SPY']['source']['response']['path'],value['baseline']['input_archives'][0]['archive_path']]
        for relative in paths:
            path=self.root/relative;before=path.read_bytes();path.write_bytes(before+b' ')
            self.assertEqual(self.read()['pairs'],[]);path.write_bytes(before)
        self.assertEqual(len(self.read()['pairs']),1)

    def test_multiple_genuine_window_and_delay_entries_share_only_two_etf_requests(self):
        delayed=deepcopy(self.entry);delayed.update(kind='delay_evaluation',record_hash='b'*64,delay_minutes=3,entry_method='observed_owner_window_delay_3_minutes_mark_not_fill')
        self.entries[delayed['record_hash']]=delayed
        result=self.collect();self.assertEqual(result['request_count'],2);self.assertEqual(result['paired_entries'],2)
        self.assertEqual({p['delay_minutes'] for p in self.read()['pairs']},{None,3})

    def test_v2_source_verification_failure_prevents_network_and_pair_admission(self):
        client=Mock()
        with patch.object(study,'_load',return_value=[]),patch.object(study,'_verify',side_effect=ValueError('bad original source')):
            with self.assertRaises(ValueError):pairs.collect(self.root,current=self.current,clock=lambda:self.current,remaining_seconds=60,client=client)
            self.assertEqual(pairs.admitted_pairs(self.root,self.current)['status'],'unavailable')
        client.fetch.assert_not_called()


    def test_supplemental_poll_persists_budget_defer_and_failure_without_rewriting_observer(self):
        original=dict(status='observed',started_at=self.current.isoformat(),completed_at=self.current.isoformat(),study_version='frozen-v2')
        pairs.observer._receipt(self.root,original)
        original_pointer=(self.root/f'{pairs.observer.REL}/current.json').read_bytes()
        result=pairs.after_observer(self.root,current=self.current,clock=lambda:self.current,remaining_seconds=5,observer_result=original)
        self.assertEqual(result['status'],'deferred_remaining_worker_budget')
        self.assertEqual(result['observer_source_status'],'verified')
        self.assertEqual(pairs.read_poll(self.root,self.current),result)
        self.assertEqual((self.root/f'{pairs.observer.REL}/current.json').read_bytes(),original_pointer)
        failed=pairs.after_observer(self.root,current=self.current,clock=lambda:self.current,remaining_seconds=50,observer_result=original,
            collector=Mock(side_effect=ValueError('source unavailable')))
        self.assertEqual(failed['status'],'unavailable');self.assertIsNone(failed['request_count'])
        self.assertEqual(pairs.read_poll(self.root,self.current),failed)
        self.assertEqual(len(list((self.root/pairs.REL/'polls').glob('*.json'))),2)

    def test_public_provider_cadence_is_kept_between_stock_and_first_etf_request(self):
        self.entry['recorded_at']=self.current.isoformat()
        with patch.object(pairs.time,'sleep') as sleep:
            self.assertEqual(self.collect()['paired_entries'],1)
        sleep.assert_called_once_with(1.0)

    def test_actual_frozen_v2_qualifying_entry_is_required_end_to_end(self):
        # Construct real source-bound V2 captures in a temporary root; neither
        # the V2 ledger reader nor its quote proof is mocked in this regression.
        (self.root/old.UNIVERSE).write_text('ticker,sector,is_benchmark\nMSFT,Technology,no\nSPY,ETF,yes\nQQQM,ETF,yes\n')
        holdings=self.root/old.HOLDINGS;holdings.parent.mkdir(parents=True);holdings.write_text('ticker,shares_optional\nMSFT,1\n')
        for policy in (old.POLICY,study.POLICY):
            path=self.root/policy;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((SCRIPT_DIR.parents[1]/policy).read_bytes())
        pointer=json.loads((self.root/backup.CURRENT).read_text());bundle=json.loads((self.root/backup.REL/pointer['history_path']).read_text())
        bars=bundle['tickers']['MSFT']['bars']
        for row in bars[:-1]:row.update(open=500.,high=501.,low=499.,close=500.)
        bars[-1].update(open=509.,high=511.,low=509.,close=510.,volume=3000.)
        raw=json.dumps({'synthetic_test_provider':'MSFT','bars':bars}).encode();digest=hashlib.sha256(raw).hexdigest()
        relative=f'{backup.REL}/responses/{digest}.json';(self.root/relative).write_bytes(raw)
        bundle['observations'][0]={'path':relative,'sha256':digest}
        backup.atomic_write_json(self.root/backup.CURRENT,backup.pointer_for(self.root,bundle,hashlib.sha256((self.root/feed.BASELINE).read_bytes()).hexdigest()))
        first=self.current.replace(second=0)
        with patch.object(study,'_outside',return_value={'histories':{}}):
            view=study.build(self.root,first,capture=True);self.assertEqual(view['status'],'experimental_current')
            stock_clock=first+timedelta(seconds=10)
            stock_client=feed.NasdaqIntradayClient(self.root,get=lambda url:json.dumps(fixture.payload('MSFT',price='$510',change='0',pct='0%',stamp='Oct 22, 2026 10:00:05 AM ET')).encode(),sleep=lambda _:None,now=lambda:stock_clock)
            context=stocks.collect(self.root,current=stock_clock,claim_id='real-stock-proof',client=stock_client,symbols={'MSFT':'stocks'})
            view=study.build(self.root,first+timedelta(seconds=11),capture=True,candidate_quote_context=context)
            entries,observations=pairs._entries(self.root,self.current)
            self.assertEqual(len(entries),1)
            original=(self.root/study.OUTPUT/'ledger.jsonl').read_bytes()
            result=pairs.collect(self.root,current=self.current,clock=lambda:self.current,remaining_seconds=60,client=self.client())
            self.assertEqual(result['paired_entries'],1)
            self.assertEqual(len(pairs.admitted_pairs(self.root,self.current)['pairs']),1)
            self.assertEqual((self.root/study.OUTPUT/'ledger.jsonl').read_bytes(),original)


if __name__=='__main__':unittest.main()
