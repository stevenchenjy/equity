"""Dual index core authority and shared whole-share funding regressions."""
import copy
import unittest
from unittest.mock import patch
from _support import SCRIPT_DIR
import account_common
from active_config import validate_core_allocation_tickers, ActiveConfigError
from portfolio_construction import remaining_core_floor_cost
from regenerate_portfolio_outputs import shared_candidate_budget
import test_capital_decision as capital_tests

class IndexCoreAuthorityTests(unittest.TestCase):
    def test_only_approved_etfs_count_not_all_benchmarks(self):
        rows=[dict(ticker=t,sector='ETF',is_benchmark='yes') for t in ('SPY','QQQM','QQQ','XLK','XLI')]
        with patch.object(account_common,'approved_core_tickers',return_value=('SPY','QQQM')), patch.object(account_common,'read_csv',return_value=rows):
            self.assertEqual([t for t in ('SPY','QQQM','QQQ','XLK','XLI') if account_common.is_core_allocation_ticker(t)],['SPY','QQQM'])
            rows[1]['sector']='Technology'
            self.assertFalse(account_common.is_core_allocation_ticker('QQQM'))
    def test_unapproved_config_cannot_expand_core(self):
        for members in ([],['QQQ'],['SPY','SPY'],['SPY','XLI'],['spy']):
            with self.assertRaises(ActiveConfigError):validate_core_allocation_tickers({'core_allocation_tickers':members})
    def test_combined_rotation_meets_floor_without_more_core_cash(self):
        value=763.25+2*292.26
        self.assertEqual(remaining_core_floor_cost(account_total=3999.29,current_core_value=value,core_minimum_pct=30,core_unit_prices=[763.25,292.26]),0)
        # One of each would not meet the floor; preserve capacity for one more QQQM.
        self.assertAlmostEqual(remaining_core_floor_cost(account_total=3999.29,current_core_value=763.25+292.26,core_minimum_pct=30,core_unit_prices=[763.25,292.26]),292.26)
    def test_combination_can_need_less_cash_than_single_fund_route(self):
        self.assertEqual(remaining_core_floor_cost(account_total=4000,current_core_value=0,core_minimum_pct=30,core_unit_prices=[700,260]),1220)
    def test_one_shared_core_commitment_and_remaining_floor(self):
        b=shared_candidate_budget(policy={'core_minimum_pct':30},core_plan={'status':'selected_review','planned_amount':260},account_total=4000,deployable_cash=4000,active_weight_pct=0,current_core_value=0,stock_committed_value=0,core_unit_prices=[700,260])
        self.assertEqual(b['core_tranche_budget'],260)
        self.assertEqual(b['remaining_core_floor_cost'],960)
        self.assertEqual(b['spendable_after_core_floor'],2780)
    def test_missing_nonheld_fund_does_not_invalidate_covered_floor(self):
        self.assertEqual(remaining_core_floor_cost(account_total=4000,current_core_value=1500,core_minimum_pct=30,core_unit_prices=[]),0)
        with self.assertRaisesRegex(ValueError,'core_floor_price_unverified'):
            remaining_core_floor_cost(account_total=4000,current_core_value=0,core_minimum_pct=30,core_unit_prices=[])
    def test_qqqm_can_reach_same_final_core_adapter_without_relaxing_admission(self):
        base=capital_tests.CapitalDecisionTests();base.setUp();base._session_decision()
        base.config['account']['core_allocation_tickers']=['SPY','QQQM']
        d=base.d
        d['account']['cash_basis']='owner_recorded'
        base.v['open_orders']['cash_confirmed']=True
        d['market_gate']['bar_state']='complete_close'
        d['eligible_new_position_review_candidates']=['QQQM']
        d['held_positions']=[dict(ticker='SPY',current_shares=1,current_price=50,asset_role='core_allocation')]
        d['watch_candidates']=[dict(ticker='QQQM',action='core_allocation_tranche_review',suggested_whole_shares=1,maximum_review_price=50,human_confirmation_required='yes',valuation_applicability='not_applicable_broad_market_etf',stability_distinct_closes=2,required_distinct_closes=2)]
        d['plan_continuity']={'plans':[dict(ticker='QQQM',status='maintained',role='broad_core',action='hold',current_shares=0,review_at='2026-09-23T10:00:00-04:00',reason='Reviewed core rationale',purpose={'exit_rule':'Review fund evidence and shared floor.'})]}
        r=next(row for row in base.build()['decisions'] if row['ticker']=='QQQM')
        self.assertEqual(r['decision'],'ACTIONABLE_BUY')
        self.assertEqual(r['shares'],1)
        self.assertEqual(r['strategy_source']['adapter'],'core_tranche')
        d['watch_candidates'][0]['stability_distinct_closes']=1
        self.assertEqual(next(row for row in base.build()['decisions'] if row['ticker']=='QQQM')['shares'],0)

if __name__=='__main__':unittest.main()
