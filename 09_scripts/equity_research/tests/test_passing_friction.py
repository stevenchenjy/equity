"""Routing repairs preserve numeric rejection and human execution authority."""
from __future__ import annotations
import unittest
from _support import SCRIPT_DIR  # noqa: F401
from regenerate_portfolio_outputs import etf_research_recommendation
from capital_escalation import _research_gate, order_options
from test_capital_escalation import fixture


class PassingFrictionTests(unittest.TestCase):
    def test_etf_observed_price_never_creates_stock_valuation_or_quantity(self):
        for ticker in ('XLI', 'QQQM'):
            row = etf_research_recommendation(ticker, {'theme': 'broad_fund'},
                {'weekly_rank': '1', 'account_aware_conviction_score': '9.0', 'portfolio_fit_score': '9.0'},
                {'last_price': '100.00'})
            self.assertEqual(row['suggested_whole_shares'], '0')
            self.assertEqual(row['valuation_applicability'], 'not_applicable_etf')
            self.assertEqual(row['valuation_base_price'], '')
            self.assertEqual(row['automatic_action_allowed'], 'no')
            self.assertFalse(_research_gate(row['gate_blockers']))
            d, contract, config, now = fixture()
            d['watch_candidates'] = [dict(row, score=9.0)]
            contract['decisions'][0].update(ticker=ticker, blockers=[row['gate_blockers']])
            ranked = order_options(d, contract, config)
            self.assertEqual(ranked[0]['route'], 'diversified_core_growth')
            self.assertFalse(ranked[0]['eligible'])

    def test_company_financial_work_still_routes_to_research(self):
        self.assertTrue(_research_gate('latest_earnings_pending_incorporation'))
        self.assertTrue(_research_gate('maintained_company_research_incomplete'))
        self.assertFalse(_research_gate('reward_to_risk'))


if __name__ == '__main__':
    unittest.main()
