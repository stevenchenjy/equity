from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import PROJECT_ROOT, SCRIPT_DIR  # noqa: F401
import create_capital_allocation_validation as validation
from create_research_questions import whole_share_diagnostics, render_whole_share_diagnostics


class AllocationReportSemanticsTests(unittest.TestCase):
    def diagnostics(self, shares):
        return whole_share_diagnostics(
            {'account_total_value': 4000, 'deployable_cash': 2450},
            [{'ticker': 'SPY', 'asset_role': 'core_allocation', 'latest_price': 775,
              'current_shares': shares}],
            {'core_minimum_pct': 30, 'core_allocation_target_pct': 30,
             'single_stock_default_cap_pct': None, 'single_stock_hard_cap_pct': None})

    def test_core_above_floor_is_satisfied_without_excess_or_diluting_capital(self):
        rows = self.diagnostics(2)
        self.assertEqual(rows[0]['allocation_status'], 'minimum_satisfied')
        self.assertIsNone(rows[0]['above_target_dollars'])
        self.assertIsNone(rows[0]['additional_capital_to_reach_target_without_share_change'])
        text = '\n'.join(render_whole_share_diagnostics(rows))
        self.assertIn('最低配置已满足；高于下限不需减仓', text)
        self.assertIn('≥30.0%', text)
        self.assertNotIn('$350', text)
        self.assertNotIn('超过目标金额', text)
        self.assertNotIn('超额容忍带', text)

    def test_core_below_floor_reports_shortfall_without_inventing_order(self):
        rows = self.diagnostics(1)
        self.assertEqual(rows[0]['allocation_status'], 'below_minimum')
        text = '\n'.join(render_whole_share_diagnostics(rows))
        self.assertIn('最低配置未满足，市值缺口 $425.00', text)
        self.assertIn('仍需合格计划及整股资金', text)
        self.assertTrue(rows[0]['not_a_trade_plan'])

    def test_current_allocation_report_names_reviewed_sizing_and_labels_historical_comparison(self):
        summary = {'account_total_value': 4000, 'deployable_cash': 2450,
                   'active_stock_hard_cap_pct': 70, 'current_active_stock_weight_pct': 0,
                   'current_cash_pct': 61.25, 'cash_available': 2450, 'current_holdings_value': 1550}
        with tempfile.TemporaryDirectory() as temp:
            valuation = Path(temp) / 'valuation.json'
            valuation.write_text('{"records": []}')
            def rows(path):
                return [summary] if path == validation.PORTFOLIO_SUMMARY_PATH else []
            with patch.object(validation, 'read_csv', side_effect=rows), \
                 patch.object(validation, '_jsonl', return_value=[]), \
                 patch.object(validation, 'VALUATION_PATH', valuation), \
                 patch.object(validation, 'atomic_write_csv'), \
                 patch.object(validation, 'atomic_write_text') as output, \
                 patch.object(validation, 'write_research_questions'):
                self.assertEqual(validation.main(), 0)
            text = output.call_args.args[1]
            self.assertIn('Current company-specific reviewed allocation', text)
            self.assertIn('historical fixed-size assumptions for comparison only', text)
            self.assertIn('fixed starting-size tiers do not govern current allocation', text)
            self.assertNotIn('Production tiered profile', text)
            self.assertNotIn('sizing tiers cannot bypass', text)


if __name__ == '__main__':
    unittest.main()
