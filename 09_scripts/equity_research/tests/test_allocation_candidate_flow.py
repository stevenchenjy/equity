from __future__ import annotations

import copy
import json
import unittest

from _support import PROJECT_ROOT, SCRIPT_DIR  # noqa: F401
import create_daily_decision_and_brief as decision
from active_config import ActiveConfigError, validate_allocation_targets
from daily_common import canonical_sha256
from portfolio_construction import individual_sizing_decision, remaining_core_floor_cost
from regenerate_portfolio_outputs import rank_candidate_budget_rows, reviewed_allocation_semantics, shared_candidate_budget


class SharedCandidateBudgetTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((PROJECT_ROOT / '00_project_control/active_production_config.json').read_text())['account']

    def budget(self, core, committed=0):
        return shared_candidate_budget(policy=self.policy, core_plan=core,
            account_total=4000, deployable_cash=3200, active_weight_pct=0,
            current_core_value=800, stock_committed_value=committed)

    def size(self, target, budget):
        return individual_sizing_decision(policy=self.policy, valuation_complete=True,
            score=9, confidence='high', expected_upside_pct=50, reward_to_risk=3,
            entry_score=9, portfolio_fit_score=9, current_price=100,
            account_total=4000, deployable_cash=budget['deployable_cash'],
            active_weight_pct=budget['active_weight_pct'], active_hard_cap_pct=70,
            single_stock_default_cap_pct=None, reviewed_target_pct=target,
            current_core_value=budget['current_core_value'], core_unit_price=budget.get('core_unit_price'))

    def test_core_roundup_and_growth_do_not_double_spend_cash(self):
        # The dollar core gap is only $400, but the admissible whole share costs $775.
        budget = self.budget({'status': 'selected_review', 'planned_amount': '775'})
        result = self.size(70, budget)
        self.assertEqual(result['suggested_whole_shares'], 24)
        self.assertLessEqual(775 + result['suggested_whole_shares'] * 100, 3200)
        self.assertEqual(budget['current_core_value'], 1575)
        self.assertEqual(budget['core_tranche_budget'], 775)

    def test_multiple_qualified_names_share_remaining_budget_without_a_quota(self):
        core = {'status': 'selected_review', 'planned_amount': '775'}
        committed = 0
        sizes = []
        for target in (30, 20, 70, 70):
            result = self.size(target, self.budget(core, committed))
            sizes.append(result['suggested_whole_shares'])
            committed += sizes[-1] * 100
        self.assertEqual(sizes, [12, 8, 4, 0])
        self.assertLessEqual(committed + 775, 3200)
        self.assertLessEqual(committed, 4000 * .7)

    def test_ineligible_core_has_no_phantom_commitment_but_core_floor_remains(self):
        budget = self.budget({'status': 'blocked_maintenance', 'planned_amount': '775'})
        self.assertEqual(budget['core_tranche_budget'], 0)
        self.assertEqual(budget['deployable_cash'], 3200)
        self.assertEqual(budget['spendable_after_core_floor'], 2800)
        self.assertEqual(self.size(70, budget)['suggested_whole_shares'], 28)

    def test_zero_core_keeps_capacity_for_two_whole_shares_across_one_share_tranche(self):
        budget = shared_candidate_budget(policy=self.policy,
            core_plan={'status': 'selected_review', 'planned_amount': '775'},
            account_total=4000, deployable_cash=4000, active_weight_pct=0,
            current_core_value=0, stock_committed_value=0, core_unit_price=775)
        self.assertEqual(budget['core_tranche_budget'], 775)
        self.assertEqual(budget['remaining_core_floor_cost'], 775)
        self.assertEqual(budget['spendable_after_core_floor'], 2450)
        result = self.size(70, budget)
        self.assertEqual(result['suggested_whole_shares'], 24)
        self.assertLessEqual(result['maximum_position_value'], 2450)
        self.assertGreaterEqual(4000 - 775 - result['suggested_whole_shares'] * 100, 775)

    def test_no_selected_tranche_still_preserves_whole_core_capacity(self):
        budget = shared_candidate_budget(policy=self.policy,
            core_plan={'status': 'not_selected', 'planned_amount': '775'},
            account_total=4000, deployable_cash=4000, active_weight_pct=0,
            current_core_value=0, stock_committed_value=0, core_unit_price=775)
        self.assertEqual(budget['core_tranche_budget'], 0)
        self.assertEqual(budget['remaining_core_floor_cost'], 1550)
        self.assertEqual(self.size(70, budget)['maximum_position_value'], 2450)

    def test_core_floor_cost_exact_boundary_satisfied_and_invalid_quotes(self):
        self.assertEqual(remaining_core_floor_cost(account_total=4000, current_core_value=600,
                         core_minimum_pct=30, core_unit_price=600), 600)
        self.assertEqual(remaining_core_floor_cost(account_total=4000, current_core_value=1550,
                         core_minimum_pct=30, core_unit_price=775), 0)
        for quote in (0, -1, float('nan'), float('inf'), True):
            with self.subTest(quote=quote), self.assertRaisesRegex(ValueError, 'core_unit_price_invalid'):
                remaining_core_floor_cost(account_total=4000, current_core_value=0,
                                          core_minimum_pct=30, core_unit_price=quote)

    def test_budget_order_prefers_stronger_unheld_case_over_lower_scored_holding(self):
        rows = [{"ticker": "HELD", "asset_role": "current_position", "account_aware_conviction_score": "7.5"},
                {"ticker": "NEW", "asset_role": "individual_stock_candidate", "account_aware_conviction_score": "9.0"},
                {"ticker": "AAA", "asset_role": "individual_stock_candidate", "account_aware_conviction_score": "7.5"},
                {"ticker": "UNKNOWN", "account_aware_conviction_score": ""}]
        ranked = rank_candidate_budget_rows(rows)
        self.assertEqual([row["ticker"] for row in ranked], ['NEW', 'AAA', 'HELD', 'UNKNOWN'])
        self.assertEqual(rows[0]['ticker'], 'HELD')  # Presentation ranking is not mutated.
        core = {'status': 'selected_review', 'planned_amount': '775'}
        committed = 0
        by_ticker = {}
        for row in ranked[:3]:
            result = self.size(70, self.budget(core, committed))
            by_ticker[row['ticker']] = result['suggested_whole_shares']
            committed += result['suggested_whole_shares'] * 100
        self.assertEqual(by_ticker, {'NEW': 24, 'AAA': 0, 'HELD': 0})

    def test_oversubscribed_shared_budget_is_invalid(self):
        with self.assertRaisesRegex(ValueError, 'shared_candidate_budget_invalid'):
            self.budget({'status': 'selected_review', 'planned_amount': '775'}, committed=2500)


class CompleteAllocationConfigTests(unittest.TestCase):
    def test_source_bound_sizing_cannot_fall_back_to_legacy_targets(self):
        account = {'sizing_method': 'source_bound_company_allocation',
                   'core_target_pct': 30, 'active_target_pct': 70,
                   'cash_target_pct': 0, 'core_minimum_pct': 30}
        self.assertEqual(validate_allocation_targets(account)['core_minimum_pct'], 30)
        for missing in ('core_target_pct', 'active_target_pct', 'cash_target_pct', 'core_minimum_pct'):
            broken = {key: value for key, value in account.items() if key != missing}
            with self.subTest(missing=missing), self.assertRaisesRegex(ActiveConfigError, 'source-bound sizing requires'):
                validate_allocation_targets(broken)
        with self.assertRaisesRegex(ActiveConfigError, 'source-bound sizing requires'):
            validate_allocation_targets({'sizing_method': 'source_bound_company_allocation'})
        self.assertEqual(validate_allocation_targets({}), {})


class CompleteCandidatePublicationTests(unittest.TestCase):
    def test_eligible_seventh_row_and_held_add_are_retained(self):
        rows = [{'ticker': f'ROW{i}', 'suggested_whole_shares': '0', 'asset_role': 'current_position'}
                for i in range(6)]
        rows += [{'ticker': 'GROW', 'asset_role': 'current_position',
                  'eligibility_label': 'eligible_buy_review', 'recommended_action': 'eligible_buy_review',
                  'suggested_whole_shares': '12', 'sizing_tier': 'source_bound_company_allocation',
                  'reviewed_allocation_semantic_sha256': 'a' * 64}]
        published = decision.build_watch_rows(rows, pending_candidate_tickers=set(),
            eligible_candidate_tickers={'GROW'}, candidate_counts={'GROW': 2}, required_distinct_closes=2)
        self.assertEqual(len(published), 7)
        grow = published[-1]
        self.assertEqual(grow['ticker'], 'GROW')
        self.assertEqual(grow['asset_role'], 'current_position')
        self.assertEqual(grow['suggested_whole_shares'], '12')
        self.assertEqual(grow['human_confirmation_required'], 'yes')
        self.assertEqual(grow['reviewed_allocation_semantic_sha256'], 'a' * 64)

    def test_material_allocation_change_resets_stability_even_when_shares_match(self):
        plan = {'role': 'long_term_growth', 'strategy_horizon': 'long_term_growth',
                'purpose': {'strategy': 'source-bound growth'},
                'reviewed_allocation': {'target_position_pct': 40, 'maximum_entry_price': 100,
                    'invalidation_price': 80, 'reassessment_price': 150,
                    'rationale': 'case', 'sources': [{'path': 'source', 'sha256': 'b' * 64}],
                    'reviewed_at': '2026-10-05T10:00:00-04:00'}}
        def row(p):
            return {'ticker': 'GROW', 'recommended_action': 'eligible_buy_review',
                    'eligibility_label': 'eligible_buy_review', 'suggested_whole_shares': '1',
                    'reviewed_allocation_semantic_sha256': canonical_sha256(reviewed_allocation_semantics(p))}
        first = decision.candidate_stability({}, [row(plan)], '2026-10-05', valid_close=True)
        changed = copy.deepcopy(plan)
        changed['reviewed_allocation']['maximum_entry_price'] = 101
        next_state = decision.candidate_stability({'new_candidate_stability': first}, [row(changed)], '2026-10-06', valid_close=True)
        self.assertEqual(next_state['proposals']['GROW']['distinct_closes'], 1)
        changed = copy.deepcopy(plan)
        changed['reviewed_allocation']['reviewed_at'] = '2026-10-06T10:00:00-04:00'
        changed['recorded_at'] = '2026-10-06T10:00:00-04:00'
        next_state = decision.candidate_stability({'new_candidate_stability': first}, [row(changed)], '2026-10-06', valid_close=True)
        self.assertEqual(next_state['proposals']['GROW']['distinct_closes'], 2)

    def test_blank_allocation_metadata_preserves_legacy_core_fingerprint(self):
        row = {'ticker': 'SPY', 'suggested_whole_shares': '1'}
        self.assertEqual(decision.candidate_proposal_fingerprint(row),
                         decision.candidate_proposal_fingerprint(row | {'reviewed_allocation_semantic_sha256': ''}))


if __name__ == '__main__':
    unittest.main()
