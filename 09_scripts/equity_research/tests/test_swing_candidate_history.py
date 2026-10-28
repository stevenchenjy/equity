from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ExclusiveFileLock, atomic_write_json, sha256_file
import market_backup as backup
import market_data_adapter as primary
import market_discovery as md
import swing_candidate_history as history

NOW = datetime(2026, 10, 27, 22, tzinfo=md.ET)
END = date(2026, 10, 27)


def price_bars(start, end):
    return [dict(session_date=str(day), open=100., high=102., low=99., close=101., volume=1_000_000.)
            for day in backup.sessions(start, end)]


def massive_payload(ticker, start, end):
    rows=[]
    for bar in price_bars(start,end):
        stamp=int(datetime.fromisoformat(bar['session_date']).replace(tzinfo=md.ET).timestamp()*1000)
        rows.append(dict(t=stamp, **{alias:bar[name] for alias,name in [('o','open'),('h','high'),('l','low'),('c','close'),('v','volume')]}))
    return dict(status='DELAYED', ticker=ticker, adjusted=False, resultsCount=len(rows), results=rows)


def nasdaq_payload(ticker,start,end):
    rows=[dict(date=datetime.fromisoformat(bar['session_date']).strftime('%m/%d/%Y'),
               **{k:('1,000,000' if k=='volume' else '$'+str(bar[k])) for k in backup.FIELDS})
          for bar in reversed(price_bars(start,end))]
    return dict(status=dict(rCode=200,bCodeMessage=None), data=dict(symbol=ticker,totalRecords=len(rows),
        tradesTable=dict(headers={'close':'Close/Last'},rows=rows)))


def targets(root, tickers=('AAA','BBB','CCC')):
    rel=md.CACHE_RELATIVE/f'metadata-{END}.local.json'
    payload=dict(session=str(END),complete=True,rows={ticker:dict(ticker=ticker,name=ticker+' Company',type='CS',
        primary_exchange='XNYS',currency_name='usd') for ticker in tickers})
    md._cache_write(root/rel,payload)
    return [dict(ticker=ticker,name=ticker+' Company',discovery_session='2026-10-26',first_seen_at='2026-10-26T20:00:00-04:00',
                 dated_screen_rank=i+1,observation_id='retained-'+ticker,metadata_path=str(rel),metadata_sha256=sha256_file(root/rel))
            for i,ticker in enumerate(tickers)]


class FakeMassive:
    def __init__(self,root,end=END,change=lambda p:p):
        self.end,self.change,self.calls=end,change,[]
        self.archiver=md.DiscoveryClient('fixture-key',state_path=root/history.BASE/'request-pacing.local.json',
            http_get=self._get,clock=lambda:NOW.timestamp(),sleep=lambda n:None)
        self.client=primary.MassiveBasicEODClient('fixture-key',http_get=lambda path,*a:self.archiver.request(path),sleep=lambda n:None)
    @property
    def receipts(self):return self.archiver.http_receipts
    def _get(self,path,*args):
        ticker=path.split('/')[4];start=date.fromisoformat(path.split('/')[8]);self.calls.append(ticker)
        payload=self.change(massive_payload(ticker,start,self.end))
        raw=json.dumps(payload,separators=(',',':')).encode()
        return md._HTTPPayload(payload,raw,200)
    def fetch_daily_bars(self,*a,**kw):return self.client.fetch_daily_bars(*a,**kw)


class CandidateHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/"equity";self.root.mkdir()
        for name in ('MIN_COMMON_STOCKS','MIN_ETFS'):
            handle=patch.object(md,name,0);handle.start();self.addCleanup(handle.stop)
        self.targets=targets(self.root)
        for rel in ('03_source_data/equity_research/market_data_snapshot.csv','03_source_data/equity_research/universe_seed.csv',
                    '03_source_data/equity_research/market_feed.local/current.local.json',
                    '05_risk_and_positions/current_positions.local.csv','04_research/company_research/opportunities.local/journal.jsonl'):
            path=self.root/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('original canonical/account/journal')
        self.protected={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def run_collect(self, client=None, **kw):
        return history.collect(self.root,NOW,massive=client or FakeMassive(self.root),targets=self.targets,clock=lambda:NOW,**kw)
    def assert_protected(self):
        for rel,raw in self.protected.items():self.assertEqual((self.root/rel).read_bytes(),raw)
    def nasdaq(self, change=lambda p:p):
        def get(url):
            path=urlparse(url);q=parse_qs(path.query);ticker=path.path.split('/')[3]
            value=change(nasdaq_payload(ticker,date.fromisoformat(q['fromdate'][0]),date.fromisoformat(q['todate'][0])))
            return json.dumps(value).encode()
        return backup.NasdaqHistoricalClient(self.root,get=get,sleep=lambda n:None)

    def test_current_original_unadjusted_history_is_readonly_admitted_bounded_and_not_capital(self):
        client=FakeMassive(self.root);result=self.run_collect(client)
        self.assertEqual(result['attempted'],2);self.assertEqual(client.calls,['AAA','BBB'])
        value=history.admitted(self.root,NOW);self.assertEqual(set(value['histories']),{'AAA','BBB'})
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for item in value['histories'].values():
            self.assertGreaterEqual(len(item['bars']),251);self.assertEqual(item['bars'][-1]['session_date'],str(END))
            self.assertEqual(item['price_basis'],'unadjusted');self.assertFalse(item['capital_authority'])
            self.assertFalse(item['canonical_admission']);self.assertEqual(item['actionable_quantity'],0)
            self.assertEqual(item['discovery_session'],'2026-10-26')
            self.assertTrue(any('/current/' in rel for rel in item['source_bindings']))
            for rel,digest in item['source_bindings'].items():self.assertEqual(sha256_file(self.root/rel),digest)
        self.assertEqual({str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()},before)
        self.assert_protected()

    def test_reuse_and_global_daily_budget_prevent_repeated_network_or_unbounded_rotation(self):
        client=FakeMassive(self.root);self.run_collect(client)
        result=self.run_collect(client)
        self.assertEqual(result['attempted'],0);self.assertEqual(result['reused'],2);self.assertEqual(client.calls,['AAA','BBB'])
        self.assertEqual(result['attempts'][-1]['status'],'daily_focused_collection_budget_exhausted')
        self.assert_protected()

    def test_exact_two_close_nasdaq_extension_preserves_unadjusted_baseline(self):
        client=FakeMassive(self.root,end=date(2026,10,26))
        with patch.object(backup,'now_et',return_value=NOW):result=self.run_collect(client,nasdaq=self.nasdaq(),max_candidates=1)
        self.assertEqual(result['attempts'][0]['status'],'admitted_current_research_history')
        item=history.admitted(self.root,NOW)['histories']['AAA']
        self.assertEqual(item['data_source'],'massive_unadjusted_history_nasdaq_eod_extension_research')
        self.assertEqual(item['bars'],price_bars(END-timedelta(weeks=52),END));self.assert_protected()

    def test_overlap_conflict_is_failed_without_old_history_revival_or_second_attempt(self):
        def conflict(value):
            value['data']['tradesTable']['rows'][-1].update(open='$98',high='$102',low='$97',close='$98')
            return value
        client=FakeMassive(self.root,end=date(2026,10,26))
        with patch.object(backup,'now_et',return_value=NOW):
            first=self.run_collect(client,nasdaq=self.nasdaq(conflict),max_candidates=1)
            again=self.run_collect(client,nasdaq=self.nasdaq(),max_candidates=1)
        self.assertEqual(first['attempts'][0]['failure_code'],'outside_history_overlap_price_basis_conflict')
        self.assertNotIn('AAA',history.admitted(self.root,NOW)['histories'])
        self.assertEqual(client.calls,['AAA','BBB'])
        self.assertEqual(again['attempts'][0]['status'],'already_attempted_same_source_and_date')
        self.assert_protected()

    def test_adjusted_missing_and_stale_primary_sources_remain_exact_dependencies(self):
        changes=[lambda p:{**p,'adjusted':True},lambda p:{**p,'results':p['results'][:5],'resultsCount':5}]
        for change in changes:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);tt=targets(root);client=FakeMassive(root,change=change)
                result=history.collect(root,NOW,massive=client,targets=tt,clock=lambda:NOW,max_candidates=1)
                self.assertEqual(result['status'],'completed_with_dependencies')
                self.assertEqual(history.admitted(root,NOW)['histories'],{})
                self.assertEqual(result['attempted'],1)
        old=FakeMassive(self.root,end=date(2026,10,16));result=self.run_collect(old,max_candidates=1)
        self.assertEqual(result['attempts'][0]['failure_code'],'outside_history_primary_baseline_stale')

    def test_original_raw_http_metadata_pointer_and_clock_tampering_fail_closed(self):
        self.run_collect(max_candidates=1)
        pointer=self.root/history.BASE/'current/AAA.json';value=json.loads(pointer.read_text())
        record_path=self.root/value['history_path'];record=json.loads(record_path.read_text())
        for rel in (record['primary_response_path'],record['primary_http_receipt_path'],record['metadata_path']):
            path=self.root/rel;before=path.read_bytes();path.write_bytes(before+b' ')
            self.assertNotIn('AAA',history.admitted(self.root,NOW)['histories']);path.write_bytes(before)
        self.assertEqual(history.admitted(self.root,NOW-timedelta(seconds=1))['histories'],{})
        atomic_write_json(pointer,dict(status='failed',source_session=str(END),failure_code='endpoint_denied'))
        self.assertNotIn('AAA',history.admitted(self.root,NOW)['histories'])
        self.assert_protected()

    def test_earlier_session_or_missing_original_http_cannot_become_current(self):
        self.run_collect(max_candidates=1)
        later=NOW+timedelta(days=1)
        self.assertEqual(history.admitted(self.root,later)['histories'],{})
        path=self.root/history.BASE/'current/AAA.json';pointer=json.loads(path.read_text());record=json.loads((self.root/pointer['history_path']).read_text())
        (self.root/record['primary_http_receipt_path']).unlink()
        self.assertEqual(history.admitted(self.root,NOW)['histories'],{})

    def test_coordinator_requires_both_real_locks_and_parent_pipeline_ownership(self):
        runtime=self.root.parent/'.locks/equity-research-runtime.lock';pipeline=self.root/'00_project_control/run_logs/daily_pipeline.lock'
        with self.assertRaises(OSError):history._verify_coordinator(self.root)
        with ExclusiveFileLock(runtime),ExclusiveFileLock(pipeline):
            with patch.object(os,'getppid',return_value=os.getpid()):history._verify_coordinator(self.root)
            with patch.object(os,'getppid',return_value=999999),self.assertRaisesRegex(ValueError,'parent_unverified'):
                history._verify_coordinator(self.root)
        with self.assertRaisesRegex(ValueError,'not_held'):history._verify_coordinator(self.root)

    def test_active_short_claim_suppresses_standalone_collection_without_network(self):
        rel='00_project_control/run_logs/short_assessment.local.json'
        atomic_write_json(self.root/rel,dict(slots={'slot':dict(status='claimed',expires_at=(NOW+timedelta(minutes=1)).isoformat())}))
        self.assertTrue(history._active_claim(self.root,NOW))
        with patch('sys.argv',['run','--root',str(self.root),'--collect']),patch.object(history,'now_et',return_value=NOW),patch.object(history,'collect') as run:
            history.main();run.assert_not_called()
        self.assertFalse(history._active_claim(self.root,NOW+timedelta(minutes=2)))


if __name__=='__main__':unittest.main()
