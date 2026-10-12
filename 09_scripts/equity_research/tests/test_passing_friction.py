"""Routing repairs preserve numeric rejection and human execution authority."""
from __future__ import annotations
import unittest
from _support import SCRIPT_DIR  # noqa: F401
from regenerate_portfolio_outputs import etf_research_recommendation
from capital_escalation import _research_gate, order_options
from decision_dependencies import classify
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
            self.assertFalse(ranked[0]['route_available'])

    def test_unadopted_fund_route_cannot_outrank_company_work_as_closest_candidate(self):
        d, contract, config, now = fixture()
        d['watch_candidates'].append(dict(ticker='QQQM', asset_role='etf_research_candidate', score=9,
            gate_blockers='etf_allocation_strategy_review_required', suggested_whole_shares=0))
        contract['decisions'].append(dict(ticker='QQQM', decision='BLOCKED', shares=0,
            blockers=['etf_allocation_strategy_review_required'], estimated_notional=0, order_draft=None, reasons=[]))
        rows = order_options(d, contract, config)
        self.assertEqual(rows[0]['ticker'], 'GROW')
        self.assertFalse(rows[1]['route_available'])

    def test_company_financial_work_still_routes_to_research(self):
        self.assertTrue(_research_gate('latest_earnings_pending_incorporation'))
        self.assertTrue(_research_gate('maintained_company_research_incomplete'))
        self.assertFalse(_research_gate('reward_to_risk'))

    def test_adverse_review_explanation_does_not_request_unchanged_missing_research(self):
        code = 'reviewed_business_case_not_supported'
        self.assertIn('reviewed rejection, not unfinished research', classify(code)['evidence_required'])
        self.assertIn('zero-share NO_ACTION', classify(code)['evidence_required'])
        self.assertFalse(_research_gate(code))
        d, contract, config, now = fixture()
        d['watch_candidates'][0]['gate_blockers'] = code
        contract['decisions'][0].update(decision='NO_ACTION', blockers=[], reasons=[code])
        row = order_options(d, contract, config)[0]
        gate = next(g for g in row['gates'] if g['code'] == code)
        self.assertIn('reviewed rejection, not unfinished research', gate['evidence_required'])
        self.assertFalse(row['eligible'])
        self.assertIn('scheduled analyst must synthesize', classify('maintained_company_research_incomplete')['evidence_required'])

    def test_threshold_explanation_preserves_numbers_without_fixed_size_claim(self):
        d, contract, config, now = fixture()
        config['account']['candidate_sizing_tiers'] = [dict(minimum_score=7,
            minimum_expected_upside_pct=10, minimum_reward_to_risk=1.25)]
        d['watch_candidates'][0].update(score=6.2, expected_upside_pct=8,
            reward_to_risk_estimate=.9, gate_blockers='score,upside,reward_to_risk')
        gates = {g['code']: g['evidence_required'] for g in order_options(d, contract, config)[0]['gates']}
        for code, number in [('score', '7.00'), ('upside', '10.00%'), ('reward_to_risk', '1.25')]:
            self.assertIn(number, gates[code])
            self.assertNotIn('sizing tier', gates[code])


if __name__ == '__main__':
    unittest.main()
