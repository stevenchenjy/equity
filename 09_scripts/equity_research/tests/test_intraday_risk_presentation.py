"""Intraday observation presentation never changes EOD trading authority."""
import copy
import unittest

from _support import SCRIPT_DIR, visible_html_text  # noqa: F401
from email_brief import intraday_risk_card, render_email
from test_email_brief import decision_fixture


def observation():
    return {"schema_version": "intraday_portfolio_risk_v1", "status": "current",
            "generated_at": "2026-10-22T15:31:00-04:00", "session_date": "2026-10-22",
            "mark_as_of": "2026-10-22T15:30:20-04:00", "expires_at": "2026-10-22T15:35:20-04:00",
            "baseline_session": "2026-10-21", "portfolio_nav": "1980", "baseline_portfolio_nav": "2000",
            "value_change_usd": "-20", "value_change_pct": "-1", "cash_usd": "1000",
            "positions": [{"ticker": "SPY", "shares": 2, "price": "490", "price_as_of": "2026-10-22T15:30:20-04:00",
                           "price_change_pct": "-2", "weight_pct": "49.4949", "source": "Massive",
                           "delay_label": "Real-time entitlement; observed last trade", "status": "current"}],
            "allocation": {"core_weight_pct": "49.4949", "stock_weight_pct": "0", "cash_weight_pct": "50.5051"},
            "plan_conditions": [{"ticker": "SPY", "condition": "Retain the core minimum.", "status": "met"}],
            "reassessment_triggers": [], "dependencies": [], "limitations": ["A last trade is not an executable quote."]}


class IntradayRiskPresentationTests(unittest.TestCase):
    def test_validated_snapshot_has_same_cash_and_inventory_baseline_and_explicit_expiry(self):
        decision = decision_fixture()
        decision['intraday_portfolio_risk'] = observation()
        before = copy.deepcopy(decision)
        card = intraday_risk_card(decision)
        for expected in ['2026-10-22 15:30', '2026-10-22 15:35', '$1,980.00', '$2,000.00', '$-20.00', '-1.00%',
                         'not the actual account', 'Massive', 'Real-time entitlement', 'Retain the core minimum.',
                         'no extra email', 'last trade is not an executable quote']:
            self.assertIn(expected, card['body'])
        _, text, html = render_email(decision)
        for output in (text, html):
            self.assertIn('Intraday portfolio risk', output)
            self.assertIn('$1,980.00', output)
            self.assertIn('freshness expires 2026-10-22 15:35', output)
        self.assertEqual(decision, before)

    def test_partial_or_expired_snapshot_withholds_aggregate_loss_and_marked_weights(self):
        for status in ['partial', 'expired', 'unavailable', 'unverified']:
            risk = {**observation(), 'status': status, 'dependencies': ['MSFT source unavailable']}
            card = intraday_risk_card({'intraday_portfolio_risk': risk})
            with self.subTest(status=status):
                self.assertIn('complete current portfolio valuation', card['body'])
                self.assertIn('MSFT source unavailable', card['body'])
                for forbidden in ['$1,980.00', '$-20.00', '49.49%', '$490.00']:
                    self.assertNotIn(forbidden, card['body'])

    def test_optional_overlay_absent_on_old_decision_and_unsafe_text_escaped(self):
        self.assertIsNone(intraday_risk_card(decision_fixture()))
        decision=decision_fixture()
        risk=observation()
        risk['limitations']=['<script>bad()</script>']
        decision['intraday_portfolio_risk']=risk
        _,text,html=render_email(decision)
        self.assertIn('<script>bad()</script>',text)
        self.assertNotIn('<script>bad()</script>',html)
        self.assertIn('&lt;script&gt;bad()',html)

    def test_actual_maintained_email_includes_one_prominent_observation_and_original_risk_limits(self):
        decision=decision_fixture()
        decision['workflow_integrity']={'status':'current'}
        risk=observation()
        risk['tactical_limits']={'ordinary_risk_pct':0.5,'event_risk_pct':0.25,'combined_risk_pct':2,
            'max_position_pct':5,'min_reward_to_risk':2,'existing_planned_risk_usd':0,'combined_planned_risk_pct':0}
        decision['intraday_portfolio_risk']=risk
        _,text,html=render_email(decision)
        for output in (text,html):
            self.assertEqual(output.count('Intraday portfolio risk — observed snapshot'),1)
            self.assertIn('ordinary 0.50%, event 0.25%, combined 2.00%',output)
            self.assertIn('minimum reward/risk 2.00R',output)
            self.assertIn('Recorded planned tactical loss: $0.00; 0.00%',visible_html_text(output) if output.startswith('<!doctype') else output)
        self.assertLess(text.index('Intraday portfolio risk'),text.index('Holdings'))

    def test_generated_email_remains_deterministic_and_does_not_expire_eod_advice(self):
        decision=decision_fixture()
        decision['intraday_portfolio_risk']=observation()
        self.assertEqual(render_email(decision),render_email(decision))
        self.assertEqual(decision['intraday_portfolio_risk']['status'],'current')


if __name__ == '__main__':
    unittest.main()
