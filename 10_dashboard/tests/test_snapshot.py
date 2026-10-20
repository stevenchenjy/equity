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

    def test_changed_account_cannot_mix_with_old_decision(self):
        self.put(ACCOUNT, {'cash_available': 900})
        with self.assertRaisesRegex(SnapshotError, 'research_inputs_changed'):
            read_snapshot(self.root, self.now)

    def test_new_market_snapshot_cannot_relabel_old_prices(self):
        self.put(MARKET, 'ticker,last_price,market_session_date,data_quality_label\nABC,110,2026-09-30,ok\n')
        with self.assertRaisesRegex(SnapshotError, 'decision_price_snapshot_mismatch'):
            read_snapshot(self.root, self.now)

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
