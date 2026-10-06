"""Owner-approved allocation migration: source-bound size across final authority."""
from __future__ import annotations
import copy
from datetime import datetime
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from _support import SCRIPT_DIR
import test_capital_decision as capital_tests
from test_investment_plans import record, ledger
from investment_plans import evaluate_plans
from reviewed_allocation import current_allocations, validate_allocation
import capital_decision as engine

class ConcentratedAllocationTests(unittest.TestCase):
    def setUp(self):
        self.base=capital_tests.CapitalDecisionTests();self.base.setUp();self.base._session_decision()
        self.d=self.base.d;self.now=self.base.v['current']
        self.d['held_positions']=[dict(ticker='SPY',current_shares=30,current_price=100,asset_role='core_allocation')]
        source={'path':'receipt.json','sha256':'a'*64}
        self.plan=dict(ticker='TEST',status='maintained',role='long_term_growth',strategy_horizon='long_term_growth',action='watch',blockers=[],
            reason='Sourced company-specific growth case',recorded_at='2026-09-23T09:15:00-04:00',review_at='2026-09-23T15:00:00-04:00',valid_until='2026-09-23T16:00:00-04:00',sources=[source],
            purpose={'entry_validity':'Quote <= $100 and reviewed evidence remains valid.','failure_condition':'Thesis failure or reviewed $90 invalidation requires exit review.','exit_rule':'Reassess by the dated deadline; do not inherit a tactical time stop.'},
            reviewed_allocation=dict(target_position_pct=40,maximum_entry_price=100,invalidation_price=90,reassessment_price=130,rationale='Evidence supports this concentration.',downside_case='A gap can exceed the planned loss.',portfolio_overlap='No duplicated current company exposure.',alternatives='Reviewed against core and cash.',reviewed_at='2026-09-23T09:10:00-04:00',sources=[source]))
        self.d['plan_continuity']={'plans':[self.plan]}
        self.d['watch_candidates'][0].update(suggested_whole_shares=40,maximum_review_price=105)
    def result(self):
        return next(r for r in self.base.build()['decisions'] if r['ticker']=='TEST')
    def test_reviewed_forty_percent_has_no_legacy_name_or_tactical_cap(self):
        r=self.result();self.assertEqual(r['decision'],'ACTIONABLE_BUY');self.assertEqual(r['shares'],40)
        self.assertEqual(r['order_draft']['portfolio_weight_after'],40)
        self.assertEqual(r['strategy_source']['adapter'],'reviewed_company')
        self.assertEqual(r['order_draft']['risk_model'],'reviewed_thesis_invalidation')
        self.assertIsNone(r['position_purpose']['time_exit_session'])
        engine.validate(self.base.build(),current=self.now)
    def test_held_growth_addition_only_fills_reviewed_target(self):
        self.d['held_positions'].append(dict(ticker='TEST',current_shares=10,current_price=100,asset_role='active_stock'))
        r=self.result();self.assertEqual((r['decision'],r['shares']),('ACTIONABLE_ADD',30));self.assertEqual(r['order_draft']['portfolio_weight_after'],40)
    def test_aggregate_seventy_and_core_floor_still_bound_name(self):
        self.plan['reviewed_allocation']['target_position_pct']=95;self.d['watch_candidates'][0]['suggested_whole_shares']=95
        self.assertEqual(self.result()['shares'],70)
        self.d['held_positions']=[]
        self.d['watch_candidates'].append(dict(ticker='SPY',current_price=100))
        self.assertEqual(self.result()['shares'],49) # $7900 free cash less $3000 core floor
    def test_final_stock_budget_preserves_whole_share_core_capacity(self):
        self.d['held_positions']=[]
        self.d['account'].update(account_total_value=4000,cash_available=4000,cash_reserved=0)
        self.plan['reviewed_allocation']['target_position_pct']=70
        self.d['watch_candidates'].append(dict(ticker='SPY',current_price=775))
        # $1200 fractional gap actually needs $1550 for 2 whole SPY shares.
        self.assertEqual(self.result()['shares'],24)

    def test_missing_expired_or_excessive_entry_review_fails_closed(self):
        for change in ('missing','expired','price','reward'):
            with self.subTest(change=change):
                saved=copy.deepcopy(self.plan)
                if change=='missing':self.plan.pop('reviewed_allocation')
                elif change=='expired':self.plan['review_at']='2026-09-23T09:00:00-04:00'
                elif change=='price':self.plan['reviewed_allocation']['maximum_entry_price']=106
                else:self.plan['reviewed_allocation']['reassessment_price']=101
                self.assertEqual(self.result()['shares'],0)
                self.plan.clear();self.plan.update(saved)
    def test_only_tactical_still_uses_existing_risk_cap(self):
        self.plan.update(role='tactical',strategy_horizon='multi_day_trend')
        self.assertEqual(self.result()['shares'],4)
    def test_review_requires_sources_and_nonempty_analysis(self):
        for key in ('sources','rationale','downside_case','portfolio_overlap','alternatives'):
            row=copy.deepcopy(self.plan);row['reviewed_allocation'].pop(key)
            with self.assertRaises(ValueError):validate_allocation(row)
    def test_zero_share_watch_plan_is_current_research_not_an_assumed_fill(self):
        row=record(role='long_term_growth')
        row.update(action='watch',proposed_change_shares=0,expected_shares=0,order_draft=None,state='maintained',valid_until='2026-09-25T16:00:00-04:00',strategy_horizon='long_term_growth')
        row['purpose']=dict(strategy='Reviewed company case',holding_period_justification='Sourced business evidence supports longer horizon.',entry_validity='At or below approved limit.',failure_condition='Thesis deterioration.',exit_rule='Reassess at deadline.',sources=row['sources'])
        row['reviewed_allocation']=copy.deepcopy(self.plan['reviewed_allocation']);row['reviewed_allocation'].update(sources=row['sources'],reviewed_at='2026-09-24T11:55:00-04:00')
        current=datetime.fromisoformat('2026-09-24T12:05:00-04:00')
        context=evaluate_plans(ledger(row),[],current=current,open_orders={'as_of':current.isoformat(),'complete':True,'orders':[]})
        p=context['plans'][0];self.assertEqual(p['status'],'maintained');self.assertEqual(p['current_shares'],0);self.assertNotIn('fresh_quote_and_available_shares_required',p['blockers'])
    def test_future_or_conflicting_allocations_do_not_size(self):
        row=copy.deepcopy(self.plan);row.update(state='maintained',effective_at='2026-09-23T09:00:00-04:00',recorded_at='2026-09-23T10:00:00-04:00')
        with patch('investment_plans.validate_ledger',return_value={'a':row}),patch('daily_common.read_json',return_value={'records':[]}):
            self.assertEqual(current_allocations(Path('/tmp'),self.now),{})
            row['recorded_at']='2026-09-23T09:00:00-04:00'
            with patch('investment_plans.validate_ledger',return_value={'a':row,'b':copy.deepcopy(row)}):self.assertEqual(current_allocations(Path('/tmp'),self.now),{})

if __name__=='__main__':unittest.main()
