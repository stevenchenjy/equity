import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from feedback import Store, FeedbackError, ACCOUNT, POSITIONS, ORDERS, LEDGER, CONFIRMED, RECONCILED, PENDING, MARKET, encoded, rows, version


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=Store(self.root,self.root/'runtime.lock',refresh=False)
        self.put(ACCOUNT,dict(account_total_value=1200,prior_account_value=1200,new_external_cash=0,cash_available=1000,cash_reserved=0,
            investment_horizon_years=5,cash_needed_within_three_years='no',core_allocation_target_pct=50,active_stock_target_pct=30,
            active_stock_hard_cap_pct=40,cash_target_pct=20,single_stock_default_cap_pct=10,single_stock_hard_cap_pct=20,
            last_updated='2026-09-29T15:00:00-04:00',cash_basis='owner_recorded'))
        self.put(POSITIONS,'ticker,entry_date,entry_price,position_pct,shares_optional,thesis,horizon_class,planned_review_date,invalidation_rule\nABC,2026-09-01,100,20,2,Test,long_horizon,2026-10-01,Test\n')
        self.put(ORDERS,dict(schema_version='phase5r_open_orders_v1',as_of='2026-09-29T15:00:00-04:00',complete=True,orders=[]))
        self.put(MARKET,'ticker,last_price,data_quality_label,market_session_date\nABC,100,ok,2026-09-29\nXYZ,50,ok,2026-09-29\n')

    def put(self,rel,value):
        p=self.root/rel; p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(value.encode() if isinstance(value,str) else encoded(value))

    def payload(self,**changes):
        f=dict(ticker='ABC',side='buy',status='filled',shares='1',amount='100',amount_mode='price',fee_status='known',fees='0',
               date='2026-09-29',time='14:00',notes='',order_type='LIMIT',order_price='',stop_price='',time_in_force='DAY',remaining='',
               linked_order='',prior_partial=False,cash='',holdings=[],inventory_complete=False,not_in_account=True,
               account_observed=False,no_open_orders=False,terminal_confirmed=False,partial_recorded=False)
        f.update(changes)
        return dict(request_id=str(uuid.uuid4()),feedback=f,account_version=version(self.root),snapshot_id=None,plan=None)

    def submit(self,p):
        preview=self.store.preview(p)
        p['preview_hash']=preview['preview_hash']
        return self.store.submit(p)

    def simple_payload(self, **changes):
        p=self.payload(time='')
        for key in ('amount_mode','fee_status','fees','time'):
            p['feedback'].pop(key)
        p['feedback'].update(entry_mode='simple', **changes)
        return p

    def test_compact_fill_uses_owner_zero_fee_price_and_date_only_contract(self):
        p=self.simple_payload(amount='123.45')
        r=self.submit(p)
        self.assertEqual(r['stage'],'applied')
        self.assertEqual(r['event_time_precision'],'date_only')
        self.assertEqual((r['feedback']['amount_mode'],r['feedback']['fee_status'],r['feedback']['fees'],r['feedback']['time']),('price','known','0',''))
        self.assertEqual(r['changes']['cash_after'],876.55)
        self.assertEqual(rows((self.root/LEDGER).read_bytes())[0]['fees'],'0')
        self.assertEqual(self.store.submit(p),r)
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),1)

    def total_payload(self, **changes):
        p=self.simple_payload(**changes)
        p['feedback']['entry_mode']='simple_total'
        p['feedback'].pop('order_type',None)
        return p

    def test_total_fill_buy_and_sell_keep_total_cash_without_inventing_order_type(self):
        buy=self.submit(self.total_payload(shares='2',amount='201'))
        self.assertEqual(buy['stage'],'applied')
        self.assertEqual(buy['changes']['cash_after'],799)
        self.assertEqual(buy['changes']['fill_price'],100.5)
        self.assertEqual(buy['feedback']['order_type'],'UNSPECIFIED')
        self.assertEqual(buy['feedback']['amount_mode'],'net')
        sell=self.submit(self.total_payload(side='sell',shares='4',amount='440'))
        self.assertEqual(sell['changes']['cash_after'],1239)
        self.assertEqual(sell['changes']['shares_after'],0)
        self.assertEqual(sell['changes']['fill_price'],110)
        self.assertEqual(rows((self.root/LEDGER).read_bytes())[-1]['order_type'],'UNSPECIFIED')
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),2)

    def test_total_fill_partial_inherits_only_the_known_matching_order_type(self):
        order=self.submit(self.simple_payload(status='pending',shares='3',order_price='100'))
        p=self.total_payload(status='partial',shares='2',amount='199',remaining='1')
        result=self.submit(p)
        self.assertEqual(result['stage'],'applied')
        self.assertEqual(result['changes']['cash_after'],801)
        self.assertEqual(result['changes']['fill_price'],99.5)
        self.assertEqual(result['feedback']['order_type'],'LIMIT')
        self.assertEqual(result['feedback']['linked_order'],order['order_id'])
        self.assertEqual(json.loads((self.root/ORDERS).read_text())['orders'][0]['remaining_quantity'],1)
        self.assertEqual(self.store.submit(p),result)
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),1)

    def test_amount_protocol_versions_cannot_silently_reinterpret_multi_share_fills(self):
        new=self.store.preview(self.total_payload(shares='2',amount='100'))
        old=self.store.preview(self.simple_payload(shares='2',amount='100'))
        self.assertEqual(new['changes']['cash_after'],900)
        self.assertEqual(old['changes']['cash_after'],800)
        p=self.total_payload(amount_mode='price')
        with self.assertRaisesRegex(FeedbackError,'simple_entry_contract_conflict'):self.store.preview(p)
        # Unknown is valid for a fill, never for an unexecuted order.
        with self.assertRaisesRegex(FeedbackError,'invalid_order_type'):
            self.store.preview(self.simple_payload(status='pending',order_type='UNSPECIFIED'))
        self.assertEqual(self.store.history(),[])

    def test_compact_contract_never_silently_reinterprets_legacy_money_or_time(self):
        for field,value in [('amount_mode','gross'),('amount_mode','net'),('fee_status','unknown'),('fees','1'),('time','14:00')]:
            with self.subTest(field=field,value=value):
                with self.assertRaisesRegex(FeedbackError,'simple_entry_contract_conflict'):
                    self.store.preview(self.simple_payload(**{field:value}))
        self.assertEqual(self.store.history(),[])
        self.assertFalse((self.root/LEDGER).exists())

    def test_compact_pending_date_has_no_fabricated_submission_time(self):
        r=self.submit(self.simple_payload(status='pending',shares='3',order_price='100'))
        self.assertEqual(r['stage'],'applied')
        order=json.loads((self.root/ORDERS).read_text())['orders'][0]
        self.assertIsNone(order['submitted_at'])
        self.assertEqual(order['submitted_time_precision'],'date_only')
        self.assertEqual(order['session_date'],'2026-09-29')
        self.assertEqual(order['status'],'open')
        self.assertEqual(json.loads((self.root/ACCOUNT).read_text())['cash_available'],1000)
        self.assertFalse((self.root/LEDGER).exists())
        # Shared order checks consume session_date and prices, not an invented time.
        from investment_plans import _order_scopes
        from zoneinfo import ZoneInfo
        current=datetime(2026,9,29,14,0,tzinfo=ZoneInfo('America/New_York'))
        issues,_,_=_order_scopes(json.loads((self.root/ORDERS).read_text()),{'ABC':2},current,local_authority=True,local_risk_zero=True)
        self.assertEqual(issues,[])

    def test_compact_partial_and_final_fill_resolve_unique_order_without_typing_id(self):
        pending=self.submit(self.simple_payload(status='pending',shares='3',order_price='100'))
        preview=self.store.preview(self.simple_payload(status='partial',shares='1',remaining='2'))
        self.assertEqual(preview['changes']['linked_order'],dict(ticker='ABC',side='buy',remaining_quantity=3,
            limit_price=100.0,stop_price=None,order_type='LIMIT',time_in_force='DAY',session_date='2026-09-29'))
        self.assertNotIn('order_id',preview['changes']['linked_order'])
        first=self.submit(self.simple_payload(status='partial',shares='1',remaining='2'))
        second=self.submit(self.simple_payload(status='partial',shares='1',remaining='1'))
        final=self.submit(self.simple_payload(status='filled',shares='1'))
        self.assertEqual([r['feedback']['linked_order'] for r in (first,second,final)],[pending['order_id']]*3)
        self.assertEqual(rows((self.root/POSITIONS).read_bytes())[0]['shares_optional'],'5')
        self.assertEqual(json.loads((self.root/ACCOUNT).read_text())['cash_available'],700)
        order=json.loads((self.root/ORDERS).read_text())['orders'][0]
        self.assertEqual((order['status'],order['remaining_quantity']),('filled',0))
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),3)

    def test_compact_order_ambiguity_requires_choice_and_does_not_change_cash(self):
        first=self.submit(self.simple_payload(status='pending',shares='3',order_price='100'))
        second=self.submit(self.simple_payload(status='pending',shares='3',order_price='99'))
        before={p:(self.root/p).read_bytes() for p in (ACCOUNT,POSITIONS,ORDERS)}
        for status in ('partial','filled','cancelled'):
            with self.subTest(status=status):
                p=self.simple_payload(status=status,shares='1',remaining='2',terminal_confirmed=True)
                preview=self.store.preview(p)
                self.assertEqual(preview['missing'],['请选择对应挂单'])
                self.assertIsNone(preview['changes'])
        self.assertEqual(before,{p:(self.root/p).read_bytes() for p in before})
        r=self.submit(self.simple_payload(status='partial',shares='1',remaining='2',linked_order=second['order_id']))
        self.assertEqual(r['stage'],'applied')
        orders={r['order_id']:r for r in json.loads((self.root/ORDERS).read_text())['orders']}
        self.assertEqual(orders[first['order_id']]['remaining_quantity'],3)
        self.assertEqual(orders[second['order_id']]['remaining_quantity'],2)

    def test_compact_explicit_independent_fill_does_not_consume_matching_order(self):
        self.submit(self.simple_payload(status='pending',shares='3',order_price='100'))
        self.submit(self.simple_payload(status='pending',shares='3',order_price='99'))
        p=self.simple_payload(shares='1',order_link_mode='independent')
        preview=self.store.preview(p)
        self.assertEqual(preview['missing'],[])
        self.assertNotIn('linked_order',preview['changes'])
        result=self.submit(p)
        self.assertEqual(result['feedback']['linked_order'],'')
        orders=json.loads((self.root/ORDERS).read_text())['orders']
        self.assertEqual([o['remaining_quantity'] for o in orders],[3,3])
        self.assertEqual([o['status'] for o in orders],['open','open'])
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),1)
        with self.assertRaisesRegex(FeedbackError,'invalid_order_link_mode'):
            self.store.preview(self.simple_payload(status='partial',shares='1',remaining='2',order_link_mode='independent'))

    def test_compact_does_not_auto_resolve_historical_reservation_or_wrong_side(self):
        pending=self.submit(self.simple_payload(status='pending',shares='3',order_price='100'))
        orders=json.loads((self.root/ORDERS).read_text())
        orders['orders'][0]['record_scope']='unresolved_historical_reservation'
        self.put(ORDERS,orders)
        partial=self.store.preview(self.simple_payload(status='partial',shares='1',remaining='2'))
        self.assertEqual(partial['missing'],['对应挂单'])
        # An explicit mismatched selection cannot cancel another side's order.
        with self.assertRaisesRegex(FeedbackError,'order_facts_conflict'):
            self.store.preview(self.simple_payload(status='cancelled',side='sell',linked_order=pending['order_id'],terminal_confirmed=True))

    def test_compact_cancellation_resolves_unique_order_and_preserves_partial_fills(self):
        self.submit(self.simple_payload(status='pending',shares='3',order_price='100'))
        self.submit(self.simple_payload(status='partial',shares='1',remaining='2'))
        r=self.submit(self.simple_payload(status='cancelled',prior_partial=True,partial_recorded=True,terminal_confirmed=True))
        self.assertEqual(r['stage'],'applied')
        self.assertEqual(rows((self.root/POSITIONS).read_bytes())[0]['shares_optional'],'3')
        self.assertEqual(json.loads((self.root/ACCOUNT).read_text())['cash_available'],900)
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),1)
        self.assertEqual(json.loads((self.root/ORDERS).read_text())['orders'][0]['status'],'cancelled')

    def test_legacy_pending_still_requires_explicit_time_and_keeps_approximate_precision(self):
        self.assertEqual(self.store.preview(self.payload(status='pending',shares='3',order_price='100',time=''))['missing'],['挂单时间'])
        r=self.submit(self.payload(status='pending',shares='3',order_price='100',time='14:00'))
        order=json.loads((self.root/ORDERS).read_text())['orders'][0]
        self.assertEqual(r['event_time_precision'],'approximate')
        self.assertEqual(order['submitted_at'],'2026-09-29T14:00:00-04:00')

    def test_first_buy_and_sale_to_all_cash(self):
        r=self.submit(self.payload(ticker='XYZ',amount='50',fees='1'))
        self.assertEqual(r['stage'],'applied'); self.assertEqual(json.loads((self.root/ACCOUNT).read_text())['cash_available'],949)
        self.assertEqual({r['ticker']:r['shares_optional'] for r in rows((self.root/POSITIONS).read_bytes())},{'ABC':'2','XYZ':'1'})
        self.submit(self.payload(side='sell',shares='2'))
        self.submit(self.payload(ticker='XYZ',side='sell',shares='1',amount='50'))
        self.assertEqual(rows((self.root/POSITIONS).read_bytes()),[])
        self.assertEqual(json.loads((self.root/ACCOUNT).read_text())['cash_available'],1199)
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),3)
        self.assertEqual(len(rows((self.root/RECONCILED).read_bytes())),3)

    def test_unknown_fee_pending_then_complete_without_duplicate(self):
        p=self.payload(fee_status='unknown',fees='')
        before=(self.root/ACCOUNT).read_bytes()
        r=self.submit(p)
        self.assertEqual(r['stage'],'pending'); self.assertEqual((self.root/ACCOUNT).read_bytes(),before)
        self.assertEqual(len(json.loads((self.root/PENDING).read_text())['records']),1)
        new=self.payload(); new.update(record_id=r['id'],revision=r['revision'])
        complete=self.submit(new)
        self.assertEqual(complete['revision'],2); self.assertEqual(complete['stage'],'applied')
        self.assertEqual(json.loads((self.root/PENDING).read_text())['records'],[])
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),1)
        self.assertEqual(self.store.submit(new),complete)
        new['feedback']['shares']='2'
        with self.assertRaisesRegex(FeedbackError,'request_id_reused'): self.store.submit(new)

    def test_stale_account_is_not_rebased(self):
        p=self.payload(); self.submit(self.payload())
        with self.assertRaisesRegex(FeedbackError,'account_version_changed'): self.store.preview(p)

    def test_partial_increment_then_cancel(self):
        r=self.submit(self.payload(status='pending',shares='3',order_price='100'))
        oid=r['order_id']
        self.submit(self.payload(status='partial',shares='1',remaining='2',linked_order=oid))
        self.submit(self.payload(status='partial',shares='1',remaining='1',linked_order=oid))
        r=self.submit(self.payload(status='cancelled',linked_order=oid,prior_partial=True,partial_recorded=True,terminal_confirmed=True))
        self.assertEqual(r['stage'],'applied')
        self.assertEqual(rows((self.root/POSITIONS).read_bytes())[0]['shares_optional'],'4')
        order=json.loads((self.root/ORDERS).read_text())['orders'][0]
        self.assertEqual((order['status'],order['remaining_quantity']),('cancelled',0))
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),2)

    def test_unknown_public_price_keeps_facts(self):
        r=self.submit(self.payload(ticker='NEW',amount='10'))
        self.assertFalse(r['changes']['valuation_complete'])
        self.assertIn('NEW',{r['ticker'] for r in rows((self.root/POSITIONS).read_bytes())})

    def test_all_cash_owner_snapshot_preserves_contribution_history(self):
        r=self.submit(self.payload(status='account',date=datetime.now().astimezone().date().isoformat(), time='',cash='1200',holdings=[],account_observed=True,inventory_complete=True,no_open_orders=True))
        self.assertEqual(r['stage'],'applied'); self.assertEqual(rows((self.root/POSITIONS).read_bytes()),[])
        self.assertEqual(json.loads((self.root/ACCOUNT).read_text())['prior_account_value'],1200)

    def test_recovery_after_mid_transition_keeps_exactly_one_fill(self):
        import feedback
        original=feedback.atomic; counter=[0]
        def fail(root,rel,content):
            counter[0]+=1
            if counter[0]==3: raise OSError('simulated process failure')
            return original(root,rel,content)
        p=self.payload(); p['preview_hash']=self.store.preview(p)['preview_hash']
        with patch('feedback.atomic',fail):
            with self.assertRaises(OSError): self.store.submit(p)
        result=Store(self.root,self.root/'runtime.lock',refresh=False).submit(p)
        self.assertEqual(result['stage'],'applied')
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),1)

    def test_external_change_during_recovery_fails_without_overwrite(self):
        import feedback
        original=feedback.atomic
        def fail(root,rel,content):
            if rel==ACCOUNT: raise OSError('simulated process failure')
            return original(root,rel,content)
        p=self.payload(); p['preview_hash']=self.store.preview(p)['preview_hash']
        with patch('feedback.atomic',fail):
            with self.assertRaises(OSError): self.store.submit(p)
        self.put(ACCOUNT,{'external':'new state'})
        with self.assertRaisesRegex(FeedbackError,'recovery_conflict'): self.store.submit(p)
        self.assertEqual(json.loads((self.root/ACCOUNT).read_text()),{'external':'new state'})

    def test_busy_runtime_returns_retryable_without_effect(self):
        import fcntl
        with (self.root/'runtime.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            with self.assertRaisesRegex(FeedbackError,'runtime_refresh_in_progress'): self.store.preview(self.payload())

    def test_oversell_and_invalid_net_cash_are_rejected(self):
        with self.assertRaisesRegex(FeedbackError,'insufficient_recorded_shares'): self.store.preview(self.payload(side='sell',shares='3'))
        with self.assertRaisesRegex(FeedbackError,'net_amount_less_than_fees'): self.store.preview(self.payload(amount_mode='net',amount='1',fees='2'))

    def test_all_cash_loader_and_generated_weights(self):
        import account_common as common
        import calculate_dynamic_weights as weights
        self.put(POSITIONS,(self.root/POSITIONS).read_text().splitlines()[0]+'\n')
        with patch.object(common,'CURRENT_POSITIONS',self.root/POSITIONS):
            self.assertEqual(common.load_positions(),[])
        account=json.loads((self.root/ACCOUNT).read_text())
        out=self.root/'05_risk_and_positions/generated/current';out.mkdir(parents=True)
        with patch.multiple(weights,load_active_inhibit=lambda:None,load_research_account_state=lambda:account,
                            load_positions=lambda:[],load_market_rows=lambda _: {},load_packets=lambda: {},load_thesis_reviews=lambda: {},append_run_log=lambda *a,**k:None,
                            DYNAMIC_WEIGHTS=out/'weights.csv',PORTFOLIO_SUMMARY=out/'summary.csv'):
            weights.main()
        result=rows((out/'summary.csv').read_bytes())[0]
        self.assertEqual((result['position_count'],result['current_holdings_value'],result['account_total_value']),('0','0.00','1000.00'))
        self.assertEqual(rows((out/'weights.csv').read_bytes()),[])

    def test_incomplete_feedback_suspends_retained_protection(self):
        from investment_plans import load_plan_context
        self.submit(self.payload(fee_status='unknown',fees=''))
        self.put('05_risk_and_positions/investment_plans.local.json',{})
        context=dict(plans=[dict(ticker='ABC',role='long_horizon',status='maintained',order_draft={'stop_price':90},eligible_quantity=2,blockers=[])],
                     conflicts=[],global_blockers=[],ticker_blockers={},strategy_blockers={},unresolved_tickers=[],block_new_capital=False)
        with patch('investment_plans.evaluate_plans',return_value=context):
            result=load_plan_context(self.root,[],datetime.now().astimezone())
        self.assertIn('reported_account_feedback_unresolved',result['global_blockers'])
        self.assertIsNone(result['plans'][0]['order_draft']);self.assertEqual(result['plans'][0]['eligible_quantity'],0)

    def test_two_concurrent_devices_cannot_apply_same_baseline_twice(self):
        import concurrent.futures
        p=self.payload();q=self.payload()
        for request in (p,q): request['preview_hash']=self.store.preview(request)['preview_hash']
        def apply(request):
            try:return Store(self.root,self.root/'runtime.lock',refresh=False).submit(request)['stage']
            except FeedbackError as exc:return exc.code
        with concurrent.futures.ThreadPoolExecutor(2) as pool: result=list(pool.map(apply,(p,q)))
        self.assertEqual(result.count('applied'),1)
        self.assertTrue(any(v in {'runtime_refresh_in_progress','account_version_changed'} for v in result))
        self.assertEqual(len(rows((self.root/LEDGER).read_bytes())),1)

    def test_failed_research_retains_accepted_cash_and_shares(self):
        import subprocess
        self.submit(self.payload());self.store.refresh=True
        before={p:(self.root/p).read_bytes() for p in (ACCOUNT,POSITIONS,LEDGER)}
        with patch('feedback.subprocess.run',side_effect=subprocess.TimeoutExpired('public research',1800)):
            self.store.work_once()
        self.assertEqual(self.store.history()[0]['research_status'],'failed')
        self.assertEqual(before,{p:(self.root/p).read_bytes() for p in before})

    def test_all_cash_keeps_public_watchlist_research_without_invented_holdings(self):
        import refresh_daily_evidence as evidence
        self.put(POSITIONS,'ticker,shares_optional\n')
        with patch.multiple(evidence,POSITIONS_PATH=self.root/POSITIONS,researched_tickers=lambda:([],['SPY','XYZ'])),patch('sys.argv',['refresh_daily_evidence.py','--check']):
            self.assertEqual(evidence.main(),0)
            self.put(POSITIONS,'ticker,shares_optional\n,1\n')
            with self.assertRaisesRegex(RuntimeError,'no held tickers found'):evidence.main()


if __name__=='__main__': unittest.main()
