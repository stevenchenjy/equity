import hashlib
import json
import tempfile
import unittest
import fcntl
import http.client
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from datetime import datetime
from pathlib import Path

from server import ACCOUNT, CORE_INPUTS, DECISION, MARKET, ORDERS, PLANS, POSITIONS, Handler, SnapshotError, read_snapshot, safe_read


class SnapshotTests(unittest.TestCase):
    def core_policy(self):
        config = json.loads((Path(__file__).resolve().parents[2] / '00_project_control/active_production_config.json').read_text())
        config['account']['core_allocation_tickers'] = ['SPY', 'QQQM']
        self.put('00_project_control/active_production_config.json', config)
        self.put('03_source_data/equity_research/universe_seed.csv', 'ticker,sector,is_benchmark\nSPY,ETF,yes\nQQQM,ETF,yes\nXLI,ETF,yes\n')

    def test_core_display_uses_this_roots_policy_for_held_and_unheld_funds(self):
        self.core_policy()
        self.put(POSITIONS, 'ticker,shares_optional\nSPY,1\nQQQM,2\nXLI,1\n')
        self.put(MARKET, 'ticker,last_price,market_session_date,data_quality_label\nSPY,100,2026-09-29,ok\nQQQM,50,2026-09-29,ok\nXLI,25,2026-09-29,ok\n')
        self.decision['held_positions'] = [dict(ticker=t,current_shares=q,current_price=p,current_weight_pct=q*p/1225*100,asset_role='active_stock') for t,q,p in [('SPY',1,100),('QQQM',2,50),('XLI',1,25)]]
        self.decision['account'].update(invested_capital=225,account_total_value=1225)
        original = self.decision['plan_continuity']['plans'][0]
        self.decision['plan_continuity']['plans'] = [{**original,'ticker':t} for t in ['SPY','QQQM','XLI']]
        self.decision['workflow_integrity']['input_hashes'][POSITIONS] = hashlib.sha256((self.root/POSITIONS).read_bytes()).hexdigest()
        self.publish()
        snapshot = read_snapshot(self.root,self.now)
        self.assertEqual(snapshot['allocation']['core_tickers'],['SPY','QQQM'])
        self.assertAlmostEqual(snapshot['allocation']['core_weight_pct'],200/1225*100)
        self.assertEqual([p['ticker'] for p in snapshot['positions'] if p['role']=='broad_core'],['SPY','QQQM'])
        self.assertEqual([p['ticker'] for p in snapshot['plans'] if p.get('asset_role')=='broad_core'],['SPY','QQQM'])
        self.put(POSITIONS,'ticker,shares_optional\nSPY,1\nXLI,1\n')
        self.decision['held_positions'] = [p for p in self.decision['held_positions'] if p['ticker']!='QQQM']
        self.decision['account'].update(invested_capital=125,account_total_value=1125)
        self.decision['workflow_integrity']['input_hashes'][POSITIONS]=hashlib.sha256((self.root/POSITIONS).read_bytes()).hexdigest()
        self.publish()
        snapshot=read_snapshot(self.root,self.now)
        self.assertEqual(next(p for p in snapshot['plans'] if p['ticker']=='QQQM')['asset_role'],'broad_core')
        self.assertAlmostEqual(snapshot['allocation']['core_weight_pct'],100/1125*100)

    def test_core_display_does_not_invent_policy_or_accept_other_etf_by_label(self):
        from server import core_allocation_view
        positions=[dict(ticker='QQQM',shares=2,price=50),dict(ticker='XLI',shares=1,price=25)]
        self.assertIsNone(core_allocation_view(self.root,positions,1200))
        self.core_policy()
        value=core_allocation_view(self.root,positions,1200)
        self.assertAlmostEqual(value['core_weight_pct'],100/1200*100)
        self.put('03_source_data/equity_research/universe_seed.csv','ticker,sector,is_benchmark\nSPY,ETF,yes\nQQQM,Technology,no\nXLI,ETF,yes\n')
        self.assertIsNone(core_allocation_view(self.root,positions,1200))

    def test_readable_order_picker_retains_order_terms_and_session_without_guessing(self):
        order=dict(order_id='private-opaque-id',ticker='ABC',side='buy',quantity=3,remaining_quantity=2,status='partial_fill',
            limit_price=99,stop_price=None,order_type='LIMIT',time_in_force='DAY',session_date='2026-09-30')
        self.put(ORDERS,dict(as_of='2026-09-30T13:00:00-04:00',complete=True,orders=[order]))
        self.decision['workflow_integrity']['input_hashes'][ORDERS]=hashlib.sha256((self.root/ORDERS).read_bytes()).hexdigest()
        self.publish()
        result=read_snapshot(self.root,self.now)
        self.assertEqual(result['orders']['rows'][0],{**order,'record_scope':None})
        # Missing historical terms stay unknown, rather than inventing order facts.
        self.put(ORDERS,dict(as_of='2026-09-30T13:00:00-04:00',complete=True,orders=[{k:v for k,v in order.items() if k not in {'order_type','time_in_force','session_date'}}]))
        self.decision['workflow_integrity']['input_hashes'][ORDERS]=hashlib.sha256((self.root/ORDERS).read_bytes()).hexdigest()
        self.publish()
        old=read_snapshot(self.root,self.now)['orders']['rows'][0]
        self.assertIsNone(old['order_type']);self.assertIsNone(old['time_in_force']);self.assertIsNone(old['session_date'])

    def test_busy_snapshot_does_not_mislabel_incoming_session_prices(self):
        from server import current_snapshot
        self.put(MARKET,'ticker,last_price,market_session_date,data_quality_label\nABC,999,2026-09-30,ok\n')
        result=current_snapshot(self.root,research_busy=True)
        self.assertEqual(result['account']['cash_available'],1000)
        self.assertIsNone(result['account']['account_total_value'])
        self.assertIsNone(result['positions'][0]['price'])
        self.assertEqual(result['plans'],[])

    def test_recomposition_fallback_keeps_exact_gates_and_withholds_drafts(self):
        from daily_common import canonical_sha256
        from server import current_snapshot
        row={'ticker':'ABC','eligible':True,'shares':2,'estimated_notional':200,'order_draft':{'side':'buy'},'gates':[{'code':'company_specific_valuation','category':'valuation'}]}
        e={'status':'active','triggered':True,'cash':{'excess_cash_usd':1000},'ranked_capital_uses':[row],
           'closest_candidate':row,'routes':[{'closest_candidate':row}],'research_requests':[{'ticker':'ABC','urgency':'immediate'}]}
        e['content_sha256']=canonical_sha256(e)
        self.decision['capital_deployment_escalation']=e;self.publish()
        self.put(MARKET,'ticker,last_price,market_session_date,data_quality_label\nABC,100,2026-09-28,ok\n')
        result=current_snapshot(self.root)
        summary=result['capital_deployment_escalation']
        self.assertFalse(summary['triggered'])
        self.assertEqual(summary['status'],'session_unverified')
        self.assertEqual(summary['ranked_capital_uses'][0]['gates'][0]['code'],'company_specific_valuation')
        self.assertIsNone(summary['ranked_capital_uses'][0]['order_draft'])
        self.assertEqual(summary['ranked_capital_uses'][0]['shares'],0)
        self.assertIsNone(result['capital_decision'])
        self.assertIsNone(summary['cash']['excess_cash_usd'])

    def test_unbound_escalation_summary_is_not_displayed(self):
        from server import escalation_view
        self.assertIsNone(escalation_view({'capital_deployment_escalation':{'status':'active','content_sha256':'bad'}},current_contract=True))
    def test_presentation_summary_matches_source_without_changing_research_facts(self):
        from plan_summary import SCHEMA, SUMMARY_PATH, source_hash
        p=self.decision['plan_continuity']['plans'][0]
        p.update(reason='Reviewed prior close.',counterargument='No current quote.',purpose={'exit_rule':'No automatic sell.'},record_hash='a'*64)
        self.publish()
        sections={k:[{'label':'要点','text':'仅供复审。'}] for k in ('reason','counterargument','conditions')}
        entry={**{k:p[k] for k in ('ticker','plan_id','version','record_hash')},'source_sha256':source_hash(p),'sections':sections}
        self.put(SUMMARY_PATH,{'schema_version':SCHEMA,'entries':[entry]})
        raw=(self.root/DECISION).read_bytes()
        result=read_snapshot(self.root,self.now)
        self.assertEqual(result['plans'][0]['display_summary'],sections)
        self.assertEqual((self.root/DECISION).read_bytes(),raw)
        p['reason']='New evidence.';self.publish()
        result=read_snapshot(self.root,self.now)
        self.assertIsNone(result['plans'][0]['display_summary'])
        self.assertEqual(result['plans'][0]['reason'],'New evidence.')
        self.assertEqual(result['plans'][0]['eligible_quantity'],2)

    def test_shared_publication_inputs_accept_bound_local_approval_and_detect_changes(self):
        from account_authority import POLICY_REL
        from workflow_inputs import WORKFLOW_INPUTS
        from server import ALLOWED_INPUTS
        self.assertEqual(ALLOWED_INPUTS, WORKFLOW_INPUTS)
        from account_authority import SCHEMA as AUTHORITY_SCHEMA, load_authority
        from daily_common import canonical_sha256
        from capital_decision import binding, SCHEMA as CAPITAL_SCHEMA
        approval = {'schema_version': AUTHORITY_SCHEMA, 'mode': 'owner_local_ledger',
                    'approved_at': '2026-09-30T13:00:00-04:00', 'owner_instruction': 'Use local records for conditional plans',
                    'automatic_execution': False, 'broker_observation_claimed': False}
        approval['content_sha256'] = canonical_sha256(approval)
        self.put(POLICY_REL, approval)
        self.put(ORDERS, {'as_of':'2026-09-15T13:00:00-04:00', 'complete':False, 'orders':[], 'cash_confirmed':False})
        self.decision['account']['cash_basis'] = 'ledger_estimate'
        c = dict(schema_version=CAPITAL_SCHEMA, generated_at=self.decision['generated_at'], decisions=[], action='NO_NEW_POSITION',
                 source_bindings=binding(self.root), account_authority=load_authority(self.root,self.now),
                 automatic_action_allowed=False, broker_connected=False, order_placed=False)
        c['content_sha256'] = canonical_sha256(c)
        self.decision['capital_decision'] = c
        self.decision['workflow_integrity']['input_hashes'] = {
            p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() if (self.root / p).exists() else None
            for p in WORKFLOW_INPUTS}
        self.publish()
        result = read_snapshot(self.root, self.now)
        self.assertEqual(result['positions'][0]['shares'], 2)
        self.assertEqual(result['capital_decision_status'], 'current')
        self.assertTrue(result['capital_decision']['account_authority']['local_planning_enabled'])
        self.assertFalse(result['capital_decision']['account_authority']['broker_observation_claimed'])
        from server import current_snapshot
        busy=current_snapshot(self.root,research_busy=True)
        self.assertTrue(busy['account_authority']['local_planning_enabled'])
        self.assertFalse(busy['account_authority']['broker_observation_claimed'])
        self.assertEqual(busy['plans'],[])

        self.assertFalse(result['orders']['complete'])
        self.assertFalse(result['account']['settled_cash_verified'])
        self.put(POLICY_REL, {'mode': 'changed'})
        with self.assertRaisesRegex(SnapshotError, 'research_inputs_changed'):
            read_snapshot(self.root, self.now)

    def test_intraday_snapshot_projection_is_optional_and_cannot_replace_closing_values(self):
        import sys
        import types
        from unittest.mock import Mock
        observation={'schema_version':'intraday_portfolio_risk_v1','status':'validated','portfolio_nav':1180}
        self.decision['intraday_portfolio_risk']=observation
        self.publish()
        expected={'schema_version':'intraday_portfolio_risk_v1','status':'expired','portfolio_nav':None}
        projection=Mock(return_value=expected)
        with patch.dict(sys.modules,{'intraday_portfolio_risk':types.SimpleNamespace(projection=projection)}):
            result=read_snapshot(self.root,self.now)
        projection.assert_called_once_with(self.root,observation,self.now)
        self.assertEqual(result['intraday_portfolio_risk'],expected)
        self.assertEqual(result['account']['account_total_value'],1200)
        self.assertEqual(result['account']['cash_available'],1000)
        self.assertEqual(result['positions'][0]['price'],100)
        self.decision.pop('intraday_portfolio_risk')
        self.publish()
        self.assertIsNone(read_snapshot(self.root,self.now)['intraday_portfolio_risk'])

    def test_intraday_source_validation_failure_is_scoped_to_optional_observation(self):
        import sys
        import types
        from unittest.mock import Mock
        observation={'schema_version':'intraday_portfolio_risk_v1','status':'validated','portfolio_nav':1180}
        self.decision['intraday_portfolio_risk']=observation
        self.publish()
        with patch.dict(sys.modules,{'intraday_portfolio_risk':types.SimpleNamespace(projection=Mock(side_effect=ValueError('source hash changed')))}):
            result=read_snapshot(self.root,self.now)
        self.assertEqual(result['intraday_portfolio_risk']['status'],'unverified')
        self.assertNotIn('portfolio_nav',result['intraday_portfolio_risk'])
        self.assertEqual(result['account']['account_total_value'],1200)
        self.assertEqual(result['positions'][0]['price'],100)
        self.assertEqual(result['global_blockers'],[])

    def test_broken_or_symlinked_presentation_notes_do_not_break_snapshot(self):
        from plan_summary import SUMMARY_PATH
        self.put(SUMMARY_PATH,'{broken')
        self.assertIsNone(read_snapshot(self.root,self.now)['plans'][0]['display_summary'])
        path=self.root/SUMMARY_PATH;path.unlink();path.symlink_to(self.root/DECISION)
        self.assertIsNone(read_snapshot(self.root,self.now)['plans'][0]['display_summary'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.fromisoformat('2026-09-30T14:00:00-04:00')
        self.put(ACCOUNT, {'cash_available': 1000, 'last_updated': '2026-09-30T13:00:00-04:00'})
        self.put(ORDERS, {'as_of': '2026-09-30T13:00:00-04:00', 'complete': True, 'orders': [], 'cash_confirmed': True})
        self.put(PLANS, {'records': []})
        self.put(POSITIONS, 'ticker,shares_optional\nABC,2\n')
        self.put(MARKET, 'ticker,last_price,market_session_date,data_quality_label\nABC,100,2026-09-29,ok\n')
        self.decision = {
            'generated_at': '2026-09-30T13:30:00-04:00', 'cycle_date': '2026-09-30',
            'account': {'cash_available': '1000', 'invested_capital': '200', 'account_total_value': '1200'},
            'market_gate': {'expected_market_session': '2026-09-29'},
            'workflow_integrity': {'input_hashes': {p: hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in CORE_INPUTS}},
            'held_positions': [{'ticker': 'ABC', 'current_shares': '2', 'current_price': '100', 'current_weight_pct': '16.6667'}],
            'plan_continuity': {'plans': [{
                'ticker': 'ABC', 'plan_id': 'ABC-1', 'version': 1, 'action': 'protect_review',
                'review_at': '2026-09-30T15:30:00-04:00', 'eligible_quantity': 2,
                'order_draft': {'quantity': 2, 'stop_price': 90}, 'blockers': [],
            }]},
            'eligible_new_position_review_candidates': ['ABC'],
            'watch_candidates': [{'ticker': 'ABC', 'suggested_whole_shares': '1', 'maximum_review_price': '100'}],
        }
        self.publish()

    def put(self, path, data):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))

    def publish(self):
        self.put(DECISION, self.decision)

    def test_admitted_capital_contract_is_projected_and_changed_binding_suppresses_it(self):
        from capital_decision import binding, SCHEMA
        from daily_common import canonical_sha256
        from account_authority import load_authority
        c=dict(schema_version=SCHEMA,generated_at=self.decision['generated_at'],decisions=[],action='NO_NEW_POSITION',
            account_authority=load_authority(self.root,self.now),source_bindings=binding(self.root),automatic_action_allowed=False,broker_connected=False,order_placed=False)
        c['content_sha256']=canonical_sha256(c)
        self.decision['capital_decision']=c;self.publish()
        result=read_snapshot(self.root,self.now)
        self.assertEqual(result['capital_decision_status'],'current')
        self.assertEqual(result['capital_decision']['action'],'NO_NEW_POSITION')
        self.assertEqual(result['plans'][0]['eligible_quantity'],0)
        self.assertIsNone(result['plans'][0]['draft'])

        self.assertEqual(result['plans'][0]['historical_draft']['quantity'],2)
        self.assertEqual(result['candidates'][0]['quantity'],0)
        self.put('01_policies/production_strategies.json',{'changed':'policy'})
        result=read_snapshot(self.root,self.now)
        self.assertEqual(result['capital_decision_status'],'recompose_required')
        self.assertIsNone(result['capital_decision'])
        self.assertEqual(result['candidates'][0]['quantity'],0)
        self.assertIsNone(result['plans'][0]['draft'])

    def test_zero_partial_company_case_is_retained_by_actual_snapshot_without_plan(self):
        from capital_decision import binding, SCHEMA
        from daily_common import canonical_sha256
        from account_authority import load_authority
        case={'ticker':'MSFT','review_status':'current','review_version':2,'scenario_prices':None,
            'conclusion':'目标仓位 0%；新增 0 股；公司特定模型仍需核验。',
            'review_conditions':['Source-bound cash/debt/shares are required.'],
            'next_review_at':'2026-10-02T13:45:00-04:00','automatic_action_allowed':False}
        row={'ticker':'MSFT','decision':'BLOCKED','shares':0,'estimated_notional':0,
            'order_draft':None,'reasons':[case['conclusion']],'blockers':['valuation'],
            'dependencies':[],'research_case':case}
        c=dict(schema_version=SCHEMA,generated_at=self.decision['generated_at'],decisions=[row],action='NO_NEW_POSITION',
            account_authority=load_authority(self.root,self.now),source_bindings=binding(self.root),
            automatic_action_allowed=False,broker_connected=False,order_placed=False)
        c['content_sha256']=canonical_sha256(c)
        self.decision['capital_decision']=c;self.publish()
        result=read_snapshot(self.root,self.now)
        projected=result['capital_decision']['decisions'][0]
        self.assertEqual(projected['research_case'],case)
        self.assertEqual(projected['shares'],0)
        self.assertIsNone(projected['order_draft'])
        self.assertFalse(any(p['ticker']=='MSFT' for p in result['plans']))

    def test_current_snapshot_preserves_quantity_and_does_not_change_inputs(self):
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = read_snapshot(self.root, self.now)
        self.assertEqual(result['plans'][0]['eligible_quantity'], 2)
        self.assertEqual(result['candidates'][0]['quantity'], 1)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_large_hash_bound_research_report_preserves_the_genuine_account_snapshot(self):
        relative = '04_research/company_research/opportunities.local/report.json'
        payload = json.dumps({'retained_research': 'x' * 12_100_000}).encode()
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        self.decision['workflow_integrity']['input_hashes'][relative] = hashlib.sha256(payload).hexdigest()
        self.publish()
        current_events = {'status': 'ready', 'events': [{'ticker': 'ABC', 'status': 'reviewed_without_entry'}]}
        original_safe_read = safe_read
        # The actual snapshot path still validates account/holdings; the large
        # journal is hash-only, never passed to the byte-retaining reader.
        def bounded_read(root, name):
            self.assertNotEqual(name, relative)
            return original_safe_read(root, name)
        with patch('server.safe_read', side_effect=bounded_read), patch('server.earnings_event_view', return_value=current_events):
            result = read_snapshot(self.root, self.now)
        self.assertEqual(result['account']['cash_available'], 1000)
        self.assertEqual(result['positions'][0]['shares'], 2)
        self.assertEqual(result['earnings_events'], current_events)
        from server import streamed_input_fingerprint
        original_fingerprint = streamed_input_fingerprint
        calls = 0
        def replace_between_reads(root, name):
            nonlocal calls
            value = original_fingerprint(root, name)
            calls += 1
            if calls == 1:
                replacement = path.with_suffix('.replacement')
                replacement.write_bytes(payload)
                replacement.replace(path)
            return value
        with patch('server.streamed_input_fingerprint', side_effect=replace_between_reads), self.assertRaisesRegex(SnapshotError, 'snapshot_changed_during_read'):
            read_snapshot(self.root, self.now)
        with self.assertRaisesRegex(SnapshotError, 'input_missing_or_too_large'):
            safe_read(self.root, relative)
        path.write_bytes(payload + b' ')
        with self.assertRaisesRegex(SnapshotError, 'research_inputs_changed'):
            read_snapshot(self.root, self.now)

    def test_streamed_research_rejects_symlinks_mutation_timeout_and_unregistered_paths(self):
        import os
        from server import streamed_input_hash
        relative = '04_research/company_research/opportunities.local/store.json'
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * 2_000_000)
        self.assertEqual(streamed_input_hash(self.root, relative), hashlib.sha256(path.read_bytes()).hexdigest())
        with self.assertRaisesRegex(SnapshotError, 'unregistered_streamed_input'):
            streamed_input_hash(self.root, DECISION)
        original_read = os.read
        changed = False
        def mutating_read(descriptor, amount):
            nonlocal changed
            value = original_read(descriptor, amount)
            if not changed:
                changed = True
                with path.open('ab') as handle:
                    handle.write(b'changed')
            return value
        with patch('server.os.read', side_effect=mutating_read), self.assertRaisesRegex(SnapshotError, 'snapshot_changed_during_read'):
            streamed_input_hash(self.root, relative)
        with patch('server.monotonic', side_effect=[0, 6]), self.assertRaisesRegex(SnapshotError, 'streamed_input_read_timeout'):
            streamed_input_hash(self.root, relative)
        target = self.root / 'retained-real-journal.json'
        path.rename(target)
        path.symlink_to(target)
        with self.assertRaisesRegex(SnapshotError, 'symlink_input_rejected'):
            streamed_input_hash(self.root, relative)

    def test_large_display_decision_is_still_rejected_before_parsing(self):
        (self.root / DECISION).write_bytes(b' ' * 12_000_001)
        with self.assertRaisesRegex(SnapshotError, 'input_missing_or_too_large'):
            read_snapshot(self.root, self.now)

    def test_review_deadline_suppresses_both_held_and_new_quantities(self):
        result = read_snapshot(self.root, datetime.fromisoformat('2026-09-30T15:30:00-04:00'))
        self.assertEqual(result['plans'][0]['status'], 'expired')
        self.assertEqual(result['plans'][0]['eligible_quantity'], 0)
        self.assertIsNone(result['plans'][0]['draft'])
        self.assertEqual(result['candidates'][0]['quantity'], 0)
        self.assertIsNone(result['candidates'][0]['maximum_review_price'])

    def test_different_day_is_stale_without_renewing_plan(self):
        result = read_snapshot(self.root, datetime.fromisoformat('2026-10-01T08:00:00-04:00'))
        self.assertTrue(result['stale'])
        self.assertEqual(result['plans'][0]['status'], 'expired')

    def test_same_day_close_boundary_revalidates_market_without_relabelling_retained_prices(self):
        before = (self.root / DECISION).read_bytes()
        earlier = read_snapshot(self.root, datetime.fromisoformat('2026-09-30T16:14:59-04:00'))
        self.assertTrue(earlier['market_current'])
        later = read_snapshot(self.root, datetime.fromisoformat('2026-09-30T16:15:00-04:00'))
        self.assertEqual(later['expected_market_session'], '2026-09-30')
        self.assertEqual(later['market_session'], '2026-09-29')
        self.assertFalse(later['market_current'])
        self.assertTrue(later['stale'])
        self.assertEqual(later['positions'][0]['price'], 100)
        self.assertEqual(later['account']['cash_available'], 1000)
        self.assertEqual(later['account']['account_total_value'], 1200)
        self.assertEqual(later['candidates'][0]['quantity'], 0)
        self.assertIsNone(later['candidates'][0]['maximum_review_price'])
        self.assertEqual((self.root / DECISION).read_bytes(), before)

    def test_next_morning_requires_previous_close_and_weekend_does_not_require_weekend_prices(self):
        self.put(MARKET, 'ticker,last_price,market_session_date,data_quality_label\nABC,100,2026-10-02,ok\n')
        self.decision.update(generated_at='2026-10-02T16:30:00-04:00', cycle_date='2026-10-02')
        self.decision['market_gate']['expected_market_session'] = '2026-10-02'
        self.publish()
        weekend = read_snapshot(self.root, datetime.fromisoformat('2026-10-03T09:00:00-04:00'))
        self.assertEqual(weekend['expected_market_session'], '2026-10-02')
        self.assertTrue(weekend['market_current'])
        self.assertTrue(weekend['stale'])
        self.assertEqual(weekend['plans'][0]['eligible_quantity'], 0)

    def test_dated_capital_projection_withholds_buys_and_preserves_independent_protective_exit(self):
        from copy import deepcopy
        from server import dated_capital_projection
        buy = dict(ticker='NEW', decision='ACTIONABLE_BUY', shares=2, estimated_notional=200,
                   order_draft={'side': 'buy', 'entry_limit': 100}, reasons=['Reviewed purchase'], blockers=[])
        sell = dict(ticker='HELD', decision='REDUCE_REVIEW', shares=1, estimated_notional=90,
                    order_draft={'side': 'sell', 'entry_order_type': 'STOP', 'exit_price': 90},
                    reasons=['Reviewed protective exit'], blockers=[])
        original = dict(content_sha256='a' * 64, decisions=[buy, sell], global_blockers=[], dependencies=[])
        before = deepcopy(original)
        projected = dated_capital_projection(original, '2026-09-30', '2026-09-29')
        self.assertEqual(original, before)
        self.assertEqual(projected['decisions'][0]['decision'], 'BLOCKED')
        self.assertEqual(projected['decisions'][0]['shares'], 0)
        self.assertIsNone(projected['decisions'][0]['order_draft'])
        self.assertEqual(projected['decisions'][1], sell)
        self.assertNotIn('content_sha256', projected)
        self.assertEqual(projected['read_time_projection']['source_content_sha256'], 'a' * 64)
        self.assertFalse(projected['read_time_projection']['canonical_contract'])
        self.assertEqual(projected['action'], 'REVIEW_HELD_RISK')

    def test_strategy_readiness_read_time_projection_withholds_old_buy_and_expires_hold(self):
        from copy import deepcopy
        from server import strategy_framework_view
        framework = dict(schema_version='equity_strategy_framework_v1', automatic_action_allowed=False,
            decisions=[dict(ticker='NEW', classification='valid_action', canonical_decision='ACTIONABLE_BUY',
                            eligible_quantity=9, order_draft={'side':'buy','entry_limit':100}, entry_trigger=100),
                       dict(ticker='OLD', classification='justified_no_action', canonical_decision='HOLD',
                            eligible_quantity=0, review_at='2026-09-30T13:00:00-04:00')])
        from daily_common import canonical_sha256
        framework['content_sha256'] = canonical_sha256(framework)
        before = deepcopy(framework)
        with patch('decision_readiness.validate_projection'):
            result = strategy_framework_view(self.root, {'strategy_framework': framework}, self.now,
                                             capital=None, market_current=False)
        self.assertEqual(framework, before)
        self.assertEqual(result['decisions'][0]['eligible_quantity'], 0)
        self.assertNotIn('order_draft', result['decisions'][0])
        self.assertNotIn('entry_trigger', result['decisions'][0])
        self.assertEqual(result['decisions'][0]['classification'], 'data_unavailable')
        self.assertEqual(result['decisions'][1]['classification'], 'plan_expired')

    def test_swing_projection_failure_never_retains_old_setup_levels(self):
        from server import strategy_framework_view
        from unittest.mock import Mock
        framework = dict(schema_version='equity_strategy_framework_v1', automatic_action_allowed=False,
            decisions=[], swing_research={'schema_version':'equity_swing_research_v1',
                'candidates':[{'ticker':'NEW','entry_trigger':123}], 'capital_authority':False})
        from daily_common import canonical_sha256
        framework['content_sha256'] = canonical_sha256({k:v for k,v in framework.items() if k!='swing_research'})
        with patch('decision_readiness.validate_projection'), patch.dict('sys.modules', {'swing_research': Mock(revalidate_projection=Mock(side_effect=ValueError('bad binding')))}):
            result = strategy_framework_view(self.root, {'strategy_framework':framework}, self.now,
                                             capital=None, market_current=True)
        self.assertEqual(result['swing_research']['status'], 'waiting_on_data')
        self.assertEqual(result['swing_research']['candidates'], [])
        self.assertEqual(result['swing_research']['actionable_quantity'], 0)
        self.assertFalse(result['swing_research']['capital_authority'])

    def test_review_window_swing_projection_uses_v2_validator_without_reinterpreting_frozen_v1(self):
        from copy import deepcopy
        from server import strategy_framework_view
        from unittest.mock import Mock
        swing = dict(schema_version='equity_swing_research_v2', version='daily-swing-review-windows-v2-20261028',
            status='experimental_current', research_only=True, capital_authority=False, actionable_quantity=0,
            candidates=[dict(ticker='NEW',entry_trigger=101,validity={'ends_at':'2026-09-30T15:20:00-04:00'})])
        framework = dict(schema_version='equity_strategy_framework_v1', automatic_action_allowed=False,
            decisions=[], analyst_handoff=[], swing_research=swing)
        before = deepcopy(framework)
        projected = {**swing, 'read_time':self.now.isoformat()}
        validator = Mock(return_value=projected)
        with patch('decision_readiness.validate_projection'), \
             patch.dict('sys.modules', {'swing_research_v2':Mock(revalidate_projection=validator)}), \
             patch('swing_research.revalidate_projection') as legacy:
            result = strategy_framework_view(self.root, {'strategy_framework':framework}, self.now,
                                             capital=None, market_current=True)
        validator.assert_called_once_with(self.root, swing, self.now)
        legacy.assert_not_called()
        self.assertEqual(result['swing_research'], projected)
        self.assertEqual(framework, before)
        self.assertEqual(result['decisions'], [])

    def test_review_window_projection_failure_preserves_version_and_withholds_all_levels(self):
        from server import strategy_framework_view
        from unittest.mock import Mock
        framework = dict(schema_version='equity_strategy_framework_v1', automatic_action_allowed=False,
            decisions=[], swing_research={'schema_version':'equity_swing_research_v2',
                'candidates':[{'ticker':'NEW','entry_trigger':123}], 'capital_authority':False})
        with patch('decision_readiness.validate_projection'), \
             patch.dict('sys.modules', {'swing_research_v2':Mock(revalidate_projection=Mock(side_effect=ValueError('changed_source')))}):
            result = strategy_framework_view(self.root, {'strategy_framework':framework}, self.now,
                                             capital=None, market_current=True)
        value = result['swing_research']
        self.assertEqual(value['schema_version'], 'equity_swing_research_v2')
        self.assertEqual(value['status'], 'waiting_on_data')
        self.assertEqual(value['candidates'], [])
        self.assertEqual(value['actionable_quantity'], 0)
        self.assertFalse(value['capital_authority'])
        self.assertTrue(value.get('blockers') or value.get('dependencies'))

    def test_unverified_readiness_cannot_restore_authored_tasks_or_accepted_records(self):
        from server import strategy_framework_view
        framework = dict(schema_version='equity_strategy_framework_v1', automatic_action_allowed=False,
            decisions=[{'ticker':'FAKE','eligible_quantity':999}], analyst_handoff=[{'ticker':'FAKE','next_step':'Unverified'}])
        result = strategy_framework_view(self.root, {'strategy_framework':framework}, self.now,
                                         capital=None, market_current=True)
        self.assertEqual(result['status'], 'unverified')
        self.assertEqual(result['decisions'], [])
        self.assertEqual(result['analyst_handoff'], [])

    def test_validated_capital_contract_becomes_explicit_dated_projection_after_close_boundary(self):
        from capital_decision import binding, SCHEMA
        from daily_common import canonical_sha256
        from account_authority import load_authority
        capital = dict(schema_version=SCHEMA, generated_at=self.decision['generated_at'], decisions=[],
            action='NO_NEW_POSITION', account_authority=load_authority(self.root, self.now),
            source_bindings=binding(self.root), automatic_action_allowed=False, broker_connected=False,
            order_placed=False)
        capital['content_sha256'] = canonical_sha256(capital)
        self.decision['capital_decision'] = capital
        self.publish()
        result = read_snapshot(self.root, datetime.fromisoformat('2026-09-30T17:00:00-04:00'))
        self.assertEqual(result['capital_decision_status'], 'dated_research')
        self.assertEqual(result['capital_decision']['read_time_projection']['source_content_sha256'], capital['content_sha256'])
        self.assertFalse(result['capital_decision']['read_time_projection']['canonical_contract'])

    def test_changed_account_cannot_mix_with_old_decision(self):
        self.put(ACCOUNT, {'cash_available': 900})
        with self.assertRaisesRegex(SnapshotError, 'research_inputs_changed'):
            read_snapshot(self.root, self.now)

    def test_new_market_snapshot_cannot_relabel_old_prices(self):
        self.put(MARKET, 'ticker,last_price,market_session_date,data_quality_label\nABC,110,2026-09-30,ok\n')
        with self.assertRaisesRegex(SnapshotError, 'decision_price_snapshot_mismatch'):
            read_snapshot(self.root, self.now)

    def test_failed_new_close_keeps_verified_dated_research_without_entry_drafts(self):
        self.decision['market_gate'].update(expected_market_session='2026-09-30', passed=False,
            complete_close_verified=False, held_session_dates={'ABC':'2026-09-29'})
        self.publish()
        result=read_snapshot(self.root,self.now)
        self.assertEqual(result['market_session'],'2026-09-29')
        self.assertEqual(result['expected_market_session'],'2026-09-30')
        self.assertFalse(result['market_current'])
        self.assertEqual(result['positions'][0]['price'],100)
        self.assertEqual(result['plans'][0]['eligible_quantity'],0)
        self.assertIsNone(result['plans'][0]['draft'])
        self.assertEqual(result['candidates'][0]['quantity'],0)

    def test_retained_close_requires_explicit_failed_gate_and_exact_bound_dates(self):
        for changes in [dict(passed=True),dict(complete_close_verified=True),
                        dict(held_session_dates={}),dict(held_session_dates={'ABC':'2026-09-28'})]:
            self.decision['market_gate']={'expected_market_session':'2026-09-30','passed':False,
                'complete_close_verified':False,'held_session_dates':{'ABC':'2026-09-29'},**changes}
            self.publish()
            with self.subTest(changes=changes),self.assertRaisesRegex(SnapshotError,'decision_price_snapshot_mismatch'):
                read_snapshot(self.root,self.now)

    def test_mixed_canonical_sessions_cannot_be_displayed_as_one_retained_close(self):
        self.decision['market_gate'].update(expected_market_session='2026-09-30', passed=False,
            complete_close_verified=False, held_session_dates={'ABC':'2026-09-29'})
        self.put(MARKET,'ticker,last_price,market_session_date,data_quality_label\nABC,100,2026-09-29,ok\nXYZ,50,2026-09-30,ok\n')
        self.publish()
        with self.assertRaisesRegex(SnapshotError,'decision_price_snapshot_mismatch'):
            read_snapshot(self.root,self.now)

    def test_mismatched_dynamic_total_fails_closed(self):
        self.decision['account']['account_total_value'] = '1250'
        self.publish()
        with self.assertRaisesRegex(SnapshotError, 'decision_account_total_does_not_reconcile'):
            read_snapshot(self.root, self.now)

    def test_cash_confirmation_does_not_prove_settlement(self):
        self.assertFalse(read_snapshot(self.root, self.now)['account']['settled_cash_verified'])

    def test_missing_publication_fingerprint_is_rejected(self):
        del self.decision['workflow_integrity']['input_hashes'][PLANS]
        self.publish()
        with self.assertRaisesRegex(SnapshotError, 'publication_fingerprints_missing'):
            read_snapshot(self.root, self.now)

    def test_unknown_input_and_symlink_are_rejected(self):
        self.decision['workflow_integrity']['input_hashes']['../../outside'] = 'a' * 64
        self.publish()
        with self.assertRaisesRegex(SnapshotError, 'unregistered_publication_input'):
            read_snapshot(self.root, self.now)
        linked = self.root / 'linked'
        linked.symlink_to(self.root / ACCOUNT)
        with self.assertRaisesRegex(SnapshotError, 'symlink_input_rejected'):
            safe_read(self.root, 'linked')

    def test_http_routes_reject_mutation_cross_origin_and_busy_runtime(self):
        lock_path = self.root / 'runtime.lock'
        lock_path.touch()
        http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        http.runtime_root = self.root
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        # Name the listener differently from the standard-library client module.
        import http.client as client_module
        def request(method, path, headers=None):
            client = client_module.HTTPConnection('127.0.0.1', http.server_port)
            client.request(method, path, headers=headers or {})
            response = client.getresponse()
            result = (response.status, response.read())
            client.close()
            return result
        with patch('server.RUNTIME_LOCK', lock_path):
            self.assertEqual(request('GET', '/api/snapshot')[0], 200)
            for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
                self.assertEqual(request(method, '/api/snapshot')[0], 405)
            self.assertEqual(request('GET', '/api/snapshot', {'Host': 'untrusted.example'})[0], 403)
            self.assertEqual(request('GET', '/api/snapshot', {'Origin': 'https://untrusted.example'})[0], 403)
            self.assertEqual(request('GET', '/api/snapshot', {'Sec-Fetch-Site': 'cross-site'})[0], 403)
            self.assertEqual(request('GET', '/../../05_risk_and_positions/current_positions.local.csv')[0], 404)
            with lock_path.open('rb') as held:
                fcntl.flock(held.fileno(), fcntl.LOCK_EX)
                code, raw = request('GET', '/api/snapshot')
                self.assertEqual(code, 503)
                self.assertIn(b'runtime_refresh_in_progress', raw)


if __name__ == '__main__':
    unittest.main()
