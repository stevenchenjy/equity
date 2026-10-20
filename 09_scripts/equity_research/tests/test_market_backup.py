import copy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import ExitStack

from _support import SCRIPT_DIR  # noqa: F401
import market_backup as backup
import run_full_universe_market_data as b2
from daily_common import sha256_file, atomic_write_json

END = date(2026, 10, 19)
BASE = date(2026, 10, 16)


def bars(start, end):
    return [dict(session_date=str(d), open=100., high=102., low=99., close=101., volume=1000.)
            for d in backup.sessions(start, end)]


def bundle(tickers):
    return dict(schema_version=backup.SCHEMA, market_session=str(BASE), generated_at='2026-10-19T08:00:00-04:00',
        data_source=backup.PRIMARY, price_basis='unadjusted', tickers={t:dict(source_url='https://api.massive.com/retained',
            bars=bars(BASE-timedelta(weeks=52), BASE)) for t in tickers})


def payload(ticker, start, end):
    rows=[dict(date=datetime.fromisoformat(b['session_date']).strftime('%m/%d/%Y'),
               **{k:'1,000' if k=='volume' else '$'+str(b[k]) for k in backup.FIELDS})
          for b in reversed(bars(start,end))]
    return dict(status=dict(rCode=200,bCodeMessage=None),data=dict(symbol=ticker,totalRecords=len(rows),
        tradesTable=dict(headers={'close':'Close/Last'},rows=rows)))


class MarketBackupTests(unittest.TestCase):
    def baseline(self, root, tickers):
        value=bundle(tickers)
        atomic_write_json(root/backup.CURRENT,backup.pointer_for(root,value,'a'*64))
        return value

    def client(self, root, transform=lambda value:value):
        def get(url):
            from urllib.parse import urlparse,parse_qs
            p=urlparse(url);q=parse_qs(p.query);t=p.path.split('/')[3]
            return json.dumps(transform(payload(t,date.fromisoformat(q['fromdate'][0]),date.fromisoformat(q['todate'][0])))).encode()
        return backup.NasdaqHistoricalClient(root,get=get,sleep=lambda _:None,monotonic=lambda:0)

    def test_complete_universe_preserves_all_original_overlap_bars(self):
        tickers=sorted(b2.APPROVED_CANDIDATE_TICKERS)+['IOT']
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=self.baseline(root,tickers);before=(root/backup.CURRENT).read_bytes()
            result=backup.recover(root,tickers,{t:'etf' if t in {'QQQ','QQQM','XLK','XLI','SPY'} else 'stocks' for t in tickers},END,client=self.client(root))
            self.assertEqual(result['data_source'],backup.SOURCE)
            self.assertEqual(set(result['tickers']),set(tickers))
            for t in tickers:
                expected=[b for b in base['tickers'][t]['bars'] if b['session_date']>='2025-10-20']
                self.assertEqual(result['tickers'][t]['bars'][:-1],expected)
                self.assertEqual(result['tickers'][t]['bars'][-1]['session_date'],str(END))
            self.assertEqual(len(result['observations']),32)
            self.assertEqual((root/backup.CURRENT).read_bytes(),before)

    def test_adjusted_overlap_or_genuine_close_conflict_rejects_whole_batch(self):
        def changed(p):
            p['data']['tradesTable']['rows'][-1].update(close='$50',open='$49',low='$48',high='$52')
            return p
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.baseline(root,['SPY','QQQM']);before=(root/backup.CURRENT).read_bytes()
            with self.assertRaisesRegex(backup.BackupError,'overlap'):
                backup.recover(root,['SPY','QQQM'],{'SPY':'etf','QQQM':'etf'},END,client=self.client(root,changed))
            self.assertEqual((root/backup.CURRENT).read_bytes(),before)

    def test_missing_ticker_does_not_expand_baseline_or_call_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.baseline(root,['SPY']);client=self.client(root)
            with self.assertRaisesRegex(backup.BackupError,'scope'):
                backup.recover(root,['SPY','QQQM'],{'SPY':'etf','QQQM':'etf'},END,client=client)
            self.assertEqual(client.receipts,[])

    def test_bad_schema_dates_numeric_values_and_pagination_rejected(self):
        start=date(2026,10,15);p=payload('SPY',start,END)
        changes=[lambda x:x['data'].update(symbol='WRONG'),lambda x:x['data'].update(totalRecords=100),
            lambda x:x['data']['tradesTable']['rows'].pop(),
            lambda x:x['data']['tradesTable']['rows'].reverse(),
            lambda x:x['data']['tradesTable']['rows'][0].update(date='10/20/2026'),
            lambda x:x['data']['tradesTable']['rows'][0].update(close='NaN'),
            lambda x:x['data']['tradesTable']['rows'][0].update(close=True),
            lambda x:x['data']['tradesTable']['rows'][0].update(volume='-1'),
            lambda x:x['data']['tradesTable']['rows'][0].update(low='$103'),
            lambda x:x['status'].update(rCode=429)]
        for change in changes:
            bad=copy.deepcopy(p);change(bad)
            with self.subTest(change=change),self.assertRaises(backup.BackupError):backup.normalize(bad,'SPY',start,END)

    def test_missing_duplicate_and_disordered_historical_sessions_reject(self):
        for kind in ['missing','duplicate','order']:
            p=bundle(['SPY']);rows=p['tickers']['SPY']['bars']
            if kind=='missing':rows.pop(30)
            elif kind=='duplicate':rows[30]=rows[29]
            else:rows[29],rows[30]=rows[30],rows[29]
            with self.subTest(kind=kind),self.assertRaises(backup.BackupError):backup.checked_bundle(p,['SPY'])

    def test_caught_publication_failure_rolls_back_every_written_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);snapshot=root/'03_source_data/equity_research/market_data_snapshot.csv';snapshot.parent.mkdir(parents=True);snapshot.write_text('before')
            real=backup.atomic_write_text
            def failed(path,text):
                if path==root/backup.CURRENT:raise OSError('simulated disk failure')
                return real(path,text)
            with patch.object(backup,'atomic_write_text',side_effect=failed),self.assertRaises(OSError):
                backup.publish(root,{snapshot:b'after'},bundle(['SPY']),snapshot)
            self.assertEqual(snapshot.read_text(),'before')
            self.assertFalse((root/backup.CURRENT).exists())

    def test_interrupted_publication_is_restored_without_clobbering_new_input(self):
        for conflict in [False,True]:
            with self.subTest(conflict=conflict),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);snapshot=root/'03_source_data/equity_research/market_data_snapshot.csv';snapshot.parent.mkdir(parents=True);snapshot.write_text('before')
                real=backup.atomic_write_text
                def crash(path,text):
                    if path==root/backup.CURRENT:raise KeyboardInterrupt()
                    return real(path,text)
                with patch.object(backup,'atomic_write_text',side_effect=crash),self.assertRaises(KeyboardInterrupt):backup.publish(root,{snapshot:b'after'},bundle(['SPY']),snapshot)
                if conflict:
                    snapshot.write_text('new owner input')
                    with self.assertRaisesRegex(backup.BackupError,'input_changed'):backup.recover_interrupted_publications(root)
                    self.assertEqual(snapshot.read_text(),'new owner input')
                else:
                    backup.recover_interrupted_publications(root);self.assertEqual(snapshot.read_text(),'before')

    def test_retained_response_tamper_invalidates_backup_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.baseline(root,['SPY']);v=backup.recover(root,['SPY'],{'SPY':'etf'},END,client=self.client(root))
            atomic_write_json(root/backup.CURRENT,backup.pointer_for(root,v,'b'*64))
            rows=[dict(ticker='SPY',market_session_date=str(END),last_price='101.0000')]
            self.assertTrue(backup.verify_binding(root,['SPY'],rows,'b'*64))
            (root/v['observations'][0]['path']).write_text('changed')
            self.assertFalse(backup.verify_binding(root,['SPY'],rows,'b'*64))

    def test_changed_original_unadjusted_baseline_invalidates_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);self.baseline(root,['SPY']);old=json.loads((root/backup.CURRENT).read_text())
            v=backup.recover(root,['SPY'],{'SPY':'etf'},END,client=self.client(root))
            atomic_write_json(root/backup.CURRENT,backup.pointer_for(root,v,'b'*64))
            (root/backup.REL/old['history_path']).write_text('changed original')
            rows=[dict(ticker='SPY',market_session_date=str(END),last_price='101.0000')]
            self.assertFalse(backup.verify_binding(root,['SPY'],rows,'b'*64))

    def test_latest_close_target_covers_evening_and_pre_0800_without_redating(self):
        from daily_common import latest_published_market_session
        for raw,expected in [('2026-10-19T16:14:59-04:00','2026-10-16'),('2026-10-19T16:15:00-04:00','2026-10-19'),('2026-10-20T07:00:00-04:00','2026-10-19')]:
            self.assertEqual(str(latest_published_market_session(datetime.fromisoformat(raw))),expected)

    def test_real_collector_path_admits_only_whole_backup_and_reuses_current_recovery(self):
        from test_market_refresh_failure_commit import B2MarketRefreshFailureCommitTests, B2_TICKERS, _seed, _quality_row, _candidate_row, UNIVERSE_TICKERS
        from market_data_adapter import MassiveB2Error, AUTH_MISSING_CODE
        from daily_common import now_et
        for failed in (False, True):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);fixture=B2MarketRefreshFailureCommitTests();paths=fixture._paths(root)
                seeds=[_seed(t) for t in UNIVERSE_TICKERS]
                base=bundle(B2_TICKERS)
                normalized=[{**b,'session_date':date.fromisoformat(b['session_date'])} for b in base['tickers']['SPY']['bars']]
                old_now=datetime.fromisoformat('2026-10-19T08:00:00-04:00')
                rows=[b2.market_row_from_massive_bars(t,normalized,old_now.isoformat(),old_now) for t in B2_TICKERS]
                by={r['ticker']:r for r in rows}
                b2.write_csv(paths['data']/'universe_seed.csv',seeds,list(seeds[0]))
                b2.write_csv(paths['positions'],[{'ticker':'IOT'},{'ticker':'RBRK'}],['ticker'])
                b2.write_csv(paths['snapshot'],rows,b2.MARKET_FIELDS)
                b2.write_csv(paths['quality'],[_quality_row(r) for r in rows],b2.QUALITY_FIELDS)
                b2.write_csv(paths['candidates'],[_candidate_row(s,by[s['ticker']]) for s in seeds],b2.CANDIDATE_FIELDS)
                policy=Path(SCRIPT_DIR).parents[1]/'01_policies/market_data_feeds.json'
                (root/'01_policies').mkdir();(root/'01_policies/market_data_feeds.json').write_bytes(policy.read_bytes())
                atomic_write_json(root/backup.CURRENT,backup.pointer_for(root,base,sha256_file(paths['snapshot'])))
                old=fixture._trio_bytes(paths);pointer=(root/backup.CURRENT).read_bytes()
                def change(p):
                    if failed and p['data']['symbol']=='RBRK':p['data']['symbol']='WRONG'
                    return p
                client=self.client(root,change)
                with ExitStack() as stack:
                    fixture._patch_paths(stack,paths)
                    stack.enter_context(patch.object(b2.MassiveBasicEODClient,'from_environment',side_effect=MassiveB2Error(AUTH_MISSING_CODE)))
                    stack.enter_context(patch.object(backup,'NasdaqHistoricalClient',return_value=client))
                    self.assertEqual(b2.main(),1 if failed else 0)
                    if failed:
                        self.assertEqual(fixture._trio_bytes(paths),old)
                        self.assertEqual((root/backup.CURRENT).read_bytes(),pointer)
                    else:
                        quoted=b2.read_csv(paths['snapshot'])
                        self.assertEqual({r['market_session_date'] for r in quoted},{'2026-10-19'})
                        self.assertEqual({r['data_source'] for r in quoted},{backup.SOURCE})
                        self.assertTrue(backup.verify_binding(root,B2_TICKERS,quoted,sha256_file(paths['snapshot'])))
                        recovered=fixture._trio_bytes(paths)
                        with patch.object(backup,'NasdaqHistoricalClient',side_effect=AssertionError('already-current backup must not request again')):
                            self.assertEqual(b2.main(),0)
                        self.assertEqual(fixture._trio_bytes(paths),recovered)


if __name__=='__main__':unittest.main()
