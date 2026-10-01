import copy
import unittest
from html.parser import HTMLParser

from _support import SCRIPT_DIR  # noqa: F401
from email_brief import render_email, build_email_view
from scheduled_email import cards
import test_action_email as action_fixtures
from test_delivery_followthrough import decision


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


class ActionEmailLayoutTests(unittest.TestCase):
    def test_current_sell_is_prominent_before_holdings_and_old_order_prices(self):
        d = decision()
        d['tactical_review'] = {'open_orders': {'orders': [
            {'ticker': 'OLD', 'status': 'pending', 'side': 'sell',
             'quantity': 3, 'limit_price': 99.99, 'current_status_verified': False}]}}
        before = copy.deepcopy(d)
        sections = cards(d, build_email_view(d))
        sell = next(c for c in sections if c.get('kind') == 'sell')
        self.assertEqual(sell['title'], 'SELL — TEST')
        self.assertEqual(sell['headline'], '2 shares · STOP $40.25 · DAY')
        for term in ('STOP is triggered at $40.25', 'not a guaranteed fill price',
                     '2026-09-28T15:30:00-04:00', 'recorded support fails',
                     'complete current order inventory', 'otherwise skip'):
            self.assertIn(term, sell['body'])
        _, text, html = render_email(d)
        for body in (text, html):
            self.assertLess(body.index('SELL — TEST'), body.index('Supporting information'))
            lead = body.split('Supporting information')[0]
            for term in ('$99.99', 'TEST reference', 'Planning cash', 'TEST why:'):
                self.assertNotIn(term, lead)
            self.assertEqual(body.count('Maintained conditional plan — TEST:'), 1)
        self.assertIn('data-action-kind="sell"', html)
        self.assertIn('border-left:6px solid #9f1239', html)
        self.assertEqual(d, before)

    def test_buy_price_trigger_and_skip_are_together_not_cash_or_reference_prices(self):
        d = action_fixtures.ActionEmailTests().core()
        sections = cards(d, build_email_view(d))
        buy = next(c for c in sections if c.get('kind') == 'buy')
        self.assertEqual(buy['title'], 'BUY — SPY')
        self.assertEqual(buy['headline'], '1 additional share · maximum $765.61 · DAY')
        for term in ('current quote at or below $765.61', 'no conflicting order',
                     'Otherwise skip', '2026-09-28', 'review 2026-09-29T13:30:00-04:00'):
            self.assertIn(term, buy['body'])
        _, text, html = render_email(d)
        parser = VisibleText(); parser.feed(html)
        visible = '\n'.join(parser.parts)
        for body in (text, visible):
            self.assertLess(body.index('BUY — SPY'), body.index('Supporting information'))
            self.assertLess(body.index('Otherwise skip'), body.index('Supporting information'))
            self.assertNotIn('$3,116.79', body.split('Supporting information')[0])
        self.assertIn('data-action-kind="buy"', html)
        self.assertIn('border-left:6px solid #166534', html)

    def test_expiry_and_unverified_order_inventory_never_gain_buy_price_from_layout(self):
        for fault in ('closed', 'order_inventory', 'estimated_cash'):
            d = action_fixtures.ActionEmailTests().core()
            if fault == 'closed':
                d['generated_at'] = '2026-09-28T16:01:00-04:00'
            elif fault == 'order_inventory':
                d['workflow_integrity']['global_blockers'] = ['unknown_current_order_inventory']
            else:
                d['account']['cash_basis'] = 'ledger_estimate'
            _, text, html = render_email(d)
            for body in (text, html):
                lead = body.split('Supporting information')[0]
                self.assertIn('BUY — none', lead)
                self.assertIn('0 shares · no current order price', lead)
                self.assertNotIn('$765.61', lead)
                self.assertNotIn('Core conditional draft', lead)

    def test_afternoon_does_not_repeat_assumed_filled_orders_in_action_cards(self):
        d = decision()
        d['delivery_followthrough'] = {'status': 'conditional_execution_followthrough',
            'requires_reconciliation': True, 'actions': []}
        _, text, html = render_email(d)
        for body in (text, html):
            lead = body.split('Supporting information')[0]
            self.assertIn('do not repeat the earlier instructions', lead)
            self.assertIn('SELL — none', lead)
            self.assertIn('BUY — none', lead)
            self.assertNotIn('$40.25', lead)
            self.assertNotIn('Maintained conditional plan', lead)


if __name__ == '__main__':
    unittest.main()
