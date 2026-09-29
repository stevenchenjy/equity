import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from email_brief import render_email
from scheduled_email import cards
from test_delivery_followthrough import decision


class ActionEmailTests(unittest.TestCase):
    def core(self):
        d = decision()
        d.update(decision_code='action_review_candidate',
                 eligible_new_position_review_candidates=['SPY'])
        d['account'].update(cash_basis='owner_recorded', cash_available='3116.79',
                            cash_reserved='0', cash_pct='78.0')
        d['market_gate']['bar_state'] = 'complete_close'
        d['held_positions'] = [{'ticker': 'SPY', 'current_shares': 1, 'current_price': 765.61}]
        d['plan_continuity']['plans'] = [{
            'ticker': 'SPY', 'status': 'maintained', 'role': 'broad_core', 'action': 'hold',
            'record_hash': 'a' * 64, 'automatic_action_allowed': False,
            'review_at': '2026-09-29T13:30:00-04:00',
            'instruction': 'Hold one core share. No automatic sell; review the next validated close.'}]
        d['watch_candidates'] = [{'ticker': 'SPY', 'action': 'core_allocation_tranche_review',
            'suggested_whole_shares': 1, 'maximum_review_price': 765.61,
            'human_confirmation_required': 'yes',
            'valuation_applicability': 'not_applicable_broad_market_etf',
            'stability_distinct_closes': 2, 'required_distinct_closes': 2}]
        d['capital_work_queue'] = {'status': 'current',
            'next_automatic_review_at': '2026-09-29T08:00:00-04:00',
            'top_opportunities': [{'ticker': 'NVDA', 'next_step': 'Assess company-specific evidence.'}]}
        d['research_backlog'] = {'priority_queue': [{'ticker': 'APP'}]}
        d['independent_market_discovery'] = {'top_stocks': [{'ticker': 'SCREEN'}]}
        return d

    def test_valid_core_draft_has_exact_action_price_session_and_skip_conditions(self):
        d = self.core(); before = copy.deepcopy(d)
        _, text, html = render_email(d)
        for body in (text, html):
            for phrase in ('What to do now', 'buy 1 additional share', '$765.61',
                           'DAY; session 2026-09-28', 'Otherwise skip', 'buying power',
                           'HOLD the recorded 1 share', 'Add 0 / sell 0 under the holding plan',
                           'mandatory internal reserve $0.00'):
                self.assertIn(phrase, body)
            for phrase in ('Research queue and evidence', 'Rules and next step', 'Stock screen',
                           'source-bound dossiers', 'Assess company-specific evidence', 'SCREEN'):
                self.assertNotIn(phrase, body)
        self.assertEqual(d, before)

    def test_expired_plan_is_unfinished_analysis_not_an_invented_hold_or_stop(self):
        d = decision(); plan = d['plan_continuity']['plans'][0]
        plan['status'] = 'expired_pending_verification'
        _, text, html = render_email(d)
        for body in (text, html):
            self.assertIn('Current sell/protection price: none', body)
            self.assertIn('unfinished analysis', body)
            self.assertNotIn('HOLD the recorded', body)
            self.assertNotIn('$40.25', body)

    def test_large_cash_never_creates_entry_or_renews_session(self):
        d = self.core(); d.update(generated_at='2026-09-28T16:01:00-04:00')
        text = render_email(d)[1]
        self.assertIn("regular session is closed", text)
        self.assertIn('not an instruction to keep this cash percentage', text)
        self.assertNotIn('buy 1 additional share', text)
        for fault in ('account', 'data', 'estimated'):
            d = self.core()
            if fault == 'account': d['account_conflicts'] = ['unknown_current_order_inventory']
            elif fault == 'data': d['market_gate']['passed'] = False
            else: d['account']['cash_basis'] = 'ledger_estimate'
            text = render_email(d)[1]
            self.assertNotIn('buy 1 additional share', text)
            self.assertNotIn('SPY research candidate: up to', text)

    def test_unstructured_eligible_row_cannot_supply_an_order_price(self):
        d = self.core(); d['watch_candidates'][0]['action'] = 'eligible_buy_review'
        d['watch_candidates'][0]['maximum_review_price'] = 654.32
        rendered = cards(d, {'plans': [{'ticker': 'SPY'}]})
        orders = next(c['body'] for c in rendered if c['title'] == 'Orders and proposals')
        self.assertIn('no complete current order draft', orders)
        self.assertNotIn('$654.32', orders)

    def test_tactical_direction_is_complete_and_incomplete_or_stale_draft_is_hidden(self):
        d = self.core(); d['eligible_new_position_review_candidates'] = ['NEW']
        d['watch_candidates'] = [{'ticker': 'NEW', 'action': 'eligible_buy_review'}]
        draft = {'ticker': 'NEW', 'eligible': True, 'quantity': 2,
            'entry_price': 50, 'stop_price': 45, 'target_price': 65, 'planned_risk_usd': 10,
            'order_type': 'conditional limit draft', 'time_in_force': 'DAY',
            'session_date': '2026-09-28', 'time_exit_session': '2026-10-02',
            'entry_rule': 'Enter only on the verified support retest.',
            'invalidation_rule': 'Skip a breakdown; exit on setup failure.'}
        d['tactical_review'] = {'drafts': [draft]}
        current = '\n'.join(c['body'] for c in cards(d, {'plans': [{'ticker': 'NEW'}]}))
        for term in ('Preferred action', 'entry/max $50.00', 'stop $45.00',
                     'target $65.00', 'verified support retest', 'exit on setup failure'):
            self.assertIn(term, current)
        self.assertNotIn('no complete current order draft', current)
        for field, value in [('entry_rule', ''), ('stop_price', 55),
                             ('session_date', '2026-09-25'), ('quantity', float('nan'))]:
            bad = copy.deepcopy(d); bad['tactical_review']['drafts'][0][field] = value
            text = '\n'.join(c['body'] for c in cards(bad, {'plans': [{'ticker': 'NEW'}]}))
            self.assertNotIn('NEW tactical draft:', text)
            self.assertIn('no complete current order draft', text)


if __name__ == '__main__':
    unittest.main()
