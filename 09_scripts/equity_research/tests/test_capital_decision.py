from __future__ import annotations
import copy,json,tempfile,unittest
from pathlib import Path
from datetime import timedelta
from _support import SCRIPT_DIR
from test_tactical_review import fixture
import capital_decision as engine
import tactical_review
import production_strategies as strategies
from daily_common import ROOT, canonical_sha256
from active_config import load_active_config
from email_brief import render_email
from capital_presentation import cards
from decision_dependencies import classify, observe, record_attempt

class CapitalDecisionTests(unittest.TestCase):
    def setUp(self):
        self.v=fixture();self.d=self.v['decision'];self.d.update(generated_at=self.v['current'].isoformat(),cycle_date=self.v['current'].date().isoformat(),decision_code='action_review_candidate',workflow_integrity={'global_blockers':[],'ticker_blockers':{}},plan_continuity={'plans':[]})
        self.d['watch_candidates'][0].update(confidence='high',strongest_positive_evidence='Current reviewed source-bound company case',strongest_negative_evidence='Margin risks remain')
        self.d['tactical_review']=tactical_review.build_tactical_review(**self.v)
        self.d['account']['last_updated']=self.v['current'].isoformat()
        self.d['long_horizon_research']={'candidate_views':{'TEST':{'status':'reviewed','business_case_status':'provisionally_supported','valuation_readiness':'reviewed_scenarios','news_review':{'status':'current','coverage_complete':True}}}}
        self.config=load_active_config()
    def build(self):
        return engine.build(self.d,root=ROOT,current=self.v['current'],config=self.config,orders=self.v['open_orders'])
    def test_eligible_company_exact_order_and_loss(self):
        c=self.build();r=c['decisions'][0];p=r['order_draft']
        self.assertEqual(r['decision'],'ACTIONABLE_BUY');self.assertEqual(r['shares'],4);self.assertEqual(r['estimated_notional'],408)
        self.assertEqual(p['invalidation_price'],98);self.assertEqual(p['planned_total_loss'],16);self.assertEqual(p['planned_account_risk_pct'],.16)
        self.assertEqual(p['estimated_cash_after'],7492);self.assertEqual(p['time_in_force'],'DAY');self.assertEqual(p['entry_limit'],102)
        engine.validate(c,current=self.v['current'],root=ROOT)
    def test_real_account_risk_change_resizes_without_symbolic_review(self):
        self.d['account']['account_total_value']=4000;self.d['account']['cash_available']=3000
        self.d['tactical_review']=tactical_review.build_tactical_review(**self.v)
        r=self.build()['decisions'][0];self.assertEqual(r['shares'],1);self.assertEqual(r['order_draft']['portfolio_weight_after'],2.55)
    def test_stale_orders_and_unverified_cash_prevent_quantity(self):
        for change in ('orders','cash'):
            if change=='orders':self.v['open_orders']['as_of']=(self.v['current']-timedelta(days=2)).isoformat()
            else:self.v['open_orders']['as_of']=self.v['current'].isoformat();self.d['account']['cash_basis']='ledger_estimate'
            r=self.build()['decisions'][0];self.assertEqual(r['decision'],'BLOCKED');self.assertEqual(r['shares'],0);self.assertIsNone(r['order_draft'])
    def test_stale_account_is_not_rescued_by_fresh_orders(self):
        self.d['account']['last_updated']=(self.v['current']-timedelta(days=3)).isoformat()
        r=self.build()['decisions'][0];self.assertEqual(r['shares'],0);self.assertIn('current_account_snapshot_stale',r['blockers'])
    def test_company_thesis_required_even_with_positive_screen_and_tactical_overlay(self):
        self.d['long_horizon_research']={}
        r=self.build()['decisions'][0];self.assertEqual(r['shares'],0);self.assertIn('maintained_company_research_incomplete',r['blockers'])
    def test_global_data_gate_cannot_be_bypassed_by_old_draft(self):
        self.d['evidence_gate']['passed']=False
        r=self.build()['decisions'][0];self.assertEqual(r['shares'],0);self.assertIn('evidence_gate_failed',r['blockers'])
    def test_joint_budget_never_double_spends(self):
        d2=copy.deepcopy(self.d['watch_candidates'][0]);d2['ticker']='TWO';self.d['watch_candidates'].append(d2);self.d['eligible_new_position_review_candidates'].append('TWO');self.d['long_horizon_research']['candidate_views']['TWO']=copy.deepcopy(self.d['long_horizon_research']['candidate_views']['TEST'])
        t2=copy.deepcopy(self.d['tactical_review']['drafts'][0]);t2['ticker']='TWO';self.d['tactical_review']['drafts'].append(t2)
        self.d['account']['cash_available']=250
        rows=self.build()['decisions'];amount=sum(r['estimated_notional'] for r in rows)
        self.assertLessEqual(amount,150) # existing mandatory reserve 100 retained
        self.assertEqual(sum(r['shares'] for r in rows),1)
    def test_zero_budget_exact_reason(self):
        self.d['account']['cash_available']=100
        r=self.build()['decisions'][0];self.assertEqual(r['shares'],0);self.assertEqual(r['decision'],'NO_ACTION');self.assertEqual(r['dependencies'],[])
        self.assertIn('uncommitted cash $0.00',r['reasons'][0]);self.assertIn('limit $102.00',r['reasons'][0])
    def test_action_content_and_source_tampering_rejected(self):
        c=self.build();c['decisions'][0]['shares']=999
        with self.assertRaisesRegex(ValueError,'content'):engine.validate(c,current=self.v['current'])
        c=self.build();c['source_bindings']={};c['content_sha256']=canonical_sha256({k:v for k,v in c.items() if k!='content_sha256'})
        with self.assertRaisesRegex(ValueError,'inputs_changed'):engine.validate(c,current=self.v['current'],root=ROOT)
    def test_hypothetical_tactical_size_never_executable(self):
        self.d['tactical_review']['drafts'][0].update(eligible=False,quantity=0,hypothetical_quantity=4,blockers=['cash_not_confirmed'])
        r=self.build()['decisions'][0];self.assertEqual(r['decision'],'BLOCKED');self.assertEqual(r['shares'],0)
    def test_draft_expiry_rejected(self):
        c=self.build()
        with self.assertRaisesRegex(ValueError,'expired'):engine.validate(c,current=self.v['current']+timedelta(days=2))
    def test_no_action_and_hold_explain_why(self):
        self.d['eligible_new_position_review_candidates']=[];self.d['watch_candidates'][0]['gate_blockers']='upside,reward_to_risk'
        r=self.build()['decisions'][0];self.assertEqual(r['decision'],'NO_ACTION');self.assertIn('upside',r['reasons'])
        self.d['held_positions']=[dict(ticker='TEST',current_shares=1,current_price=101,asset_role='active_stock')]
        self.d['plan_continuity']={'plans':[dict(ticker='TEST',status='maintained',action='hold',instruction='Hold 1 through the recorded review',blockers=[])]}
        r=self.build()['decisions'][0];self.assertEqual(r['decision'],'HOLD');self.assertTrue(r['reasons'])
    def test_existing_fundamental_purpose_cannot_be_silently_recast_as_tactical(self):
        self.d['held_positions']=[dict(ticker='TEST',current_shares=1,current_price=101,asset_role='active_stock')]
        self.d['plan_continuity']={'plans':[dict(ticker='TEST',status='maintained',role='fundamental',action='hold',blockers=[])]}
        r=self.build()['decisions'][0];self.assertEqual(r['shares'],0);self.assertIn('position_purpose_change_requires_recorded_reassessment',r['blockers'])
    def test_current_dated_exit_has_complete_sell_draft_without_assumed_proceeds_funding_buys(self):
        self.d['eligible_new_position_review_candidates']=[];self.d['watch_candidates']=[]
        self.d['held_positions']=[dict(ticker='TEST',current_shares=2,current_price=101,asset_role='active_stock')]
        self.d['plan_continuity']={'plans':[dict(ticker='TEST',status='maintained',action='sell_review',blockers=['fresh_quote_and_available_shares_required'],review_at='2026-09-23T15:30:00-04:00',reason='Maintained sourced thesis exit',historical_order_draft={'side':'sell','type':'LIMIT','quantity':2,'limit_price':102,'time_in_force':'DAY','session_date':'2026-09-23'})]}
        c=self.build();r=c['decisions'][0];self.assertEqual(r['decision'],'EXIT_REVIEW');self.assertEqual(r['shares'],2);self.assertEqual(r['order_draft']['side'],'sell');self.assertEqual(r['order_draft']['exit_price'],102)
        self.assertEqual(c['estimated_uncommitted_cash_after'],7900)
        engine.validate(c,current=self.v['current']);self.d['capital_decision']=c
        self.assertIn('SELL LIMIT ≥ $102.00',next(s for s in cards(self.d) if s['title']=='EXIT REVIEW — TEST')['body'])
    def test_research_support_not_capital_authority(self):
        self.d['eligible_new_position_review_candidates']=[];self.d['watch_candidates']=[]
        self.d['research_opportunities']={'priority_queue':[{'ticker':'MXL','state':'research_supported','blockers':['company_specific_valuation']}]}
        r=self.build()['decisions'][0];self.assertEqual(r['decision'],'BLOCKED');self.assertEqual(r['shares'],0)
    def test_classifications_not_all_research_is_owner_work(self):
        for code,kind in [('debt_latest','A'),('cash_latest','A'),('planning_cash_unverified','C'),('order_inventory_unverified_cannot_bound_buy_commitments','C'),('sec_acceptance_timestamp_unreconciled','B'),('company_specific_valuation','D'),('strategy_not_production_adopted','E')]:
            self.assertEqual(classify(code)['category'],kind)
    def test_automatic_workers_have_durable_actual_attempt_receipt(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);before=observe(root,'valuation_scenarios');p=root/'04_data/equity_research/valuation_scenarios.local.json';p.parent.mkdir(parents=True);p.write_text('{}')
            record_attempt(root,dict(name='valuation_scenarios',started_at='a',completed_at='b',exit_code=0),before)
            receipt=json.loads((root/'08_reviews/decision_resolution.local/valuation_scenarios.json').read_text())
            self.assertIn(str(p.relative_to(root)),receipt['changed_paths']);self.assertFalse(receipt['stage_success_is_dependency_resolution'])
    def test_email_actions_precede_research_with_numbers(self):
        self.d['capital_decision']=self.build();self.d['send_recommended']=False
        sections=cards(self.d);self.assertEqual(sections[0]['title'],"TODAY'S ACTION")
        buy=next(r for r in sections if r['title']=='BUY — TEST');self.assertIn('$102.00',buy['body']);self.assertIn('planned loss $16.00',buy['body'])
        _,text,html=render_email(self.d)
        self.assertLess(text.index('BUY — TEST'),text.index('Candidate decisions'));self.assertIn('data-action-kind="buy"',html)
    def _session_decision(self):
        self.v['current']=self.v['current']+timedelta(hours=15,minutes=20)
        self.v['open_orders']['as_of']=self.v['current'].isoformat()
        self.d['account']['last_updated']=self.v['current'].isoformat()
        self.d.update(generated_at=self.v['current'].isoformat(),cycle_date=self.v['current'].date().isoformat())
        self.d['tactical_review']=tactical_review.build_tactical_review(**self.v)
        import delivery_followthrough as follow
        self.d['workflow_integrity']['input_hashes']={p:'c'*64 for p in follow.RECORD_PATHS}
        self.d['capital_decision']=self.build()
    def test_exact_new_capital_email_has_labelled_fill_scenario_and_prevents_repeat(self):
        import delivery_followthrough as follow
        from test_delivery_followthrough import archive
        self._session_decision()
        prior=copy.deepcopy(self.d);afternoon=self.v['current'].replace(hour=14,minute=30)
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);archive(root,prior,when=self.v['current'].replace(hour=9,minute=30))
            context=follow.build_followthrough(self.d,root=root,current=afternoon)
            self.assertEqual(context['status'],'conditional_execution_followthrough')
            self.assertEqual(context['actions'][0]['assumed_remaining_shares'],4)
            self.assertEqual(context['actions'][0]['source'],'exact_displayed_capital_draft')
            self.assertFalse(context['canonical_state_changed'])
            self.d['delivery_followthrough']=context
            self.d['capital_decision']=self.build()
            self.assertEqual(self.d['capital_decision']['decisions'][0]['shares'],0)
            self.assertIn('earlier_instruction_execution_unreconciled',self.d['capital_decision']['global_blockers'])
            self.d['delivery_followthrough']=follow.build_followthrough(self.d,root=root,current=afternoon)
            follow.validate_followthrough(self.d,root=root,current=afternoon)
            text=render_email(self.d)[1];self.assertNotIn('BUY — TEST',text);self.assertIn('Do not repeat that purchase',text)
            self.assertEqual(prior['account'],self.d['account'])
    def test_capital_archive_with_missing_displayed_risk_never_falls_back_to_old_draft(self):
        import delivery_followthrough as follow
        from test_delivery_followthrough import archive
        self._session_decision()
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);archive(root,self.d,when=self.v['current'].replace(hour=9,minute=30),alter_html=lambda h:h.replace('planned loss $16.00','risk omitted'))
            context=follow.build_followthrough(self.d,root=root,current=self.v['current'].replace(hour=14,minute=30))
            self.assertEqual(context['status'],'prior_action_not_structured');self.assertEqual(context['actions'],[])
    def test_delivery_comparison_uses_exact_capital_drafts_and_ignores_clocks_and_unqualified_churn(self):
        from delivery_continuity import delivery_meaning_key
        self.d['capital_decision']=self.build();baseline=copy.deepcopy(self.d)
        self.d['capital_decision']['generated_at']='2026-09-22T18:05:00-04:00'
        self.d['capital_decision']['decisions'][0]['decision_timestamp']='2026-09-22T18:05:00-04:00'
        self.d['capital_decision']['decisions'].append(dict(ticker='UNQUALIFIED',decision='BLOCKED',order_draft=None))
        self.assertEqual(delivery_meaning_key(baseline),delivery_meaning_key(self.d))
        self.d['capital_decision']['decisions'][0]['order_draft']['entry_limit']=101
        self.assertNotEqual(delivery_meaning_key(baseline),delivery_meaning_key(self.d))
    def test_contract_cannot_relabel_a_sell_as_buy_even_with_recomputed_hash(self):
        c=self.build();c['decisions'][0]['order_draft']['side']='sell'
        c['content_sha256']=canonical_sha256({k:v for k,v in c.items() if k!='content_sha256'})
        with self.assertRaisesRegex(ValueError,'execution_authority'):engine.validate(c,current=self.v['current'])
    def test_no_trade_or_sender_path_in_decision_modules(self):
        import ast
        for name in ('capital_decision','capital_presentation','decision_dependencies','production_strategies'):
            tree=ast.parse((SCRIPT_DIR/(name+'.py')).read_text())
            imports={n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)}|{a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names}
            self.assertFalse(imports & {'smtplib','send_daily_email','send_email','ib_insync','alpaca','chase','requests'})
        c=self.build();self.assertFalse(c['order_placed']);self.assertFalse(c['broker_connected'])

class StrategyLifecycleTests(unittest.TestCase):
    def test_adopted_version_reused_future_signals_and_experiment_denied(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);p=root/'policy.json';p.write_text('{}');e=root/'mature_review.json';e.write_text('{"mature":true}')
            s=dict(strategy_id='test-v1',adapter='reviewed_tactical',version=1,state='EXPERIMENT',origin='experiment',authority='owner approved strategy definition',policy_bindings={'policy.json':strategies.sha256_file(p)})
            self.assertIn('strategy_not_production_adopted',strategies.admit(root,s))
            s.update(state='VERSIONED_PRODUCTION_STRATEGY',evidence_review=dict(mature_evidence=True,reviewed_at='2026-09-20T12:00:00-04:00',experiment_version='separate-fixture-only',source_bindings={'mature_review.json':strategies.sha256_file(e)}))
            self.assertIn('owner_strategy_adoption_required',strategies.admit(root,s))
            digest=canonical_sha256(s);s['owner_adoption']=dict(approved_by='owner',approved_at='2026-09-20T13:00:00-04:00',request_reference='explicit fixture owner decision',strategy_definition_sha256=digest)
            self.assertEqual(strategies.admit(root,s),[]);self.assertEqual(strategies.admit(root,s),[]) # no per-signal adoption state
            s['version']=2;self.assertIn('owner_strategy_adoption_required',strategies.admit(root,s))
    def test_future_review_and_string_maturity_cannot_adopt_a_strategy(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);p=root/'policy.json';p.write_text('{}')
            s=dict(strategy_id='fixture',adapter='reviewed_tactical',version=1,state='VERSIONED_PRODUCTION_STRATEGY',origin='experiment',authority='fixture only',policy_bindings={'policy.json':strategies.sha256_file(p)},evidence_review={'mature_evidence':'true','reviewed_at':'2999-01-01T12:00:00-04:00','experiment_version':'fixture','source_bindings':{'policy.json':strategies.sha256_file(p)}})
            s['owner_adoption']=dict(approved_by='owner',approved_at='2999-01-01T13:00:00-04:00',request_reference='fixture only',strategy_definition_sha256=canonical_sha256(s))
            errors=strategies.admit(root,s)
            self.assertIn('strategy_mature_evidence_review_missing',errors);self.assertIn('strategy_review_adoption_clock_invalid',errors)

if __name__=='__main__':unittest.main()
