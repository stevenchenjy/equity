import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from scheduled_email import cards


def maintained_plan():
    return {'ticker': 'TEST', 'status': 'maintained', 'action': 'protect_review',
        'record_hash': 'a' * 64, 'current_shares': 2, 'proposed_change_shares': 2,
        'automatic_action_allowed': False, 'validity': 'research_only_requires_current_verification',
        'review_at': '2026-09-28T15:30:00-04:00',
        'blockers': ['fresh_quote_and_available_shares_required'],
        'purpose': {'entry_validity': 'Only while the retained setup remains valid.',
                    'failure_condition': 'Review promptly if the recorded support fails.'},
        'historical_order_draft': {'side': 'sell', 'type': 'STOP', 'quantity': 2,
            'stop_price': 40.25, 'time_in_force': 'DAY', 'session_date': '2026-09-28'}}


class MaintainedPlanEmailTests(unittest.TestCase):
    def render(self, plan):
        decision = {'generated_at': '2026-09-28T14:59:00-04:00',
            'plan_continuity': {'schema_version': 'equity_plan_continuity_v1', 'plans': [plan]},
            'held_positions': [{'ticker': 'TEST', 'current_shares': 2, 'current_price': 43}],
            'eligible_action_review_candidates': [], 'eligible_new_position_review_candidates': []}
        before = copy.deepcopy(decision)
        rendered = cards(decision, {'plans': []})
        self.assertEqual(decision, before)
        return next(c['body'] for c in rendered if c['title'] == 'Orders and proposals')

    def test_current_maintained_protection_draft_survives_empty_new_eligibility(self):
        text = self.render(maintained_plan())
        for term in ('Maintained conditional plan', 'sell 2 shares', 'STOP', '$40.25',
                     'DAY', '2026-09-28', '2026-09-28T15:30:00-04:00',
                     'not submitted', 'fresh quote', 'available shares', 'recorded support fails'):
            self.assertIn(term, text)
        self.assertNotIn('eligible research proposal', text)

    def test_expired_review_due_failed_or_hold_plan_cannot_renew_draft(self):
        for status in ('expired_pending_verification', 'review_due', 'failed_setup_pending_review',
                       'time_exit_due_pending_verification', 'order_conflict_pending_review'):
            plan = maintained_plan(); plan['status'] = status
            self.assertNotIn('$40.25', self.render(plan))
            self.assertNotIn('Maintained conditional plan', self.render(plan))
        plan = maintained_plan(); plan.update(action='hold', proposed_change_shares=0)
        plan['historical_order_draft'] = {}
        self.assertNotIn('Maintained conditional plan', self.render(plan))

    def test_malformed_or_unbound_drafts_are_withheld(self):
        for field, value in [('quantity', 3), ('stop_price', float('nan')),
                             ('time_in_force', 'GTC'), ('session_date', '2026-09-25'),
                             ('side', 'buy')]:
            plan = maintained_plan(); plan['historical_order_draft'][field] = value
            self.assertNotIn('Maintained conditional plan', self.render(plan))
        plan = maintained_plan(); plan['record_hash'] = 'unverified'
        self.assertNotIn('Maintained conditional plan', self.render(plan))

    def test_limit_exit_keeps_explicit_price_and_known_blocker(self):
        plan = maintained_plan(); plan['action'] = 'exit_review'
        plan['historical_order_draft'].update(type='MARKETABLE_LIMIT', limit_price=41.50)
        plan['historical_order_draft'].pop('stop_price')
        plan['blockers'].append('cash_not_confirmed_for_tactical_execution')
        text = self.render(plan)
        self.assertIn('MARKETABLE_LIMIT', text)
        self.assertIn('limit $41.50', text)
        self.assertIn('cash confirmation', text)


if __name__ == '__main__':
    unittest.main()
