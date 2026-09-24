from __future__ import annotations

import copy
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import send_daily_email as sender
from email_brief import render_email
from test_email_brief import decision_fixture, action_fixture
from test_owner_review_delivery import delivery_fixture
from test_tactical_email import tactical_fixture


class ReviewScheduleConsistencyTests(unittest.TestCase):
    current = datetime(2026, 9, 23, 13, 37, tzinfo=ZoneInfo('America/New_York'))

    def row(self, status='owner_review_sent', stamp='2026-09-23T08:06:31-04:00'):
        return {'cycle_date': '2026-09-22', 'timestamp': stamp, 'status': status}

    def covered(self, rows, decision=None):
        with patch.object(sender, 'now_et', return_value=self.current):
            return sender.routine_covered_by_owner_review(rows, decision or decision_fixture())

    def test_actual_send_date_overrides_prior_canonical_cycle_for_all_claim_states(self):
        for status in sender.OWNER_REVIEW_DELIVERY_STATUSES:
            with self.subTest(status=status):
                self.assertTrue(self.covered([self.row(status)]))

    def test_previous_day_future_naive_and_malformed_timestamps_do_not_suppress(self):
        for stamp in ['2026-09-22T23:59:00-04:00', '2026-09-23T14:00:00-04:00',
                      '2026-09-23T08:00:00', 'bad']:
            with self.subTest(stamp=stamp):
                self.assertFalse(self.covered([self.row(stamp=stamp)]))
        self.assertFalse(self.covered([self.row(status='sent')]))
        # UTC calendar date differs, but ET date is yesterday.
        self.assertFalse(self.covered([self.row(stamp='2026-09-23T02:00:00+00:00')]))

    def test_new_risk_or_validated_action_is_not_silenced(self):
        decisions = [action_fixture()]
        for key, value in [('account_conflicts', ['pending_execution']),
                           ('material_events', [{'ticker': 'TEST'}]),
                           ('fundamental_gate', {'passed': True, 'weakening_tickers': ['TEST']}),
                           ('evidence_gate', {'passed': False})]:
            d = decision_fixture()
            d[key] = value
            decisions.append(d)
        for d in decisions:
            self.assertFalse(self.covered([self.row()], d))

    def test_sender_suppresses_routine_before_credentials_or_smtp(self):
        d = decision_fixture()
        d.update(send_recommended=True, cycle_date='2026-09-23')
        with delivery_fixture() as (config, smtp), \
                patch.object(sender, 'now_et', return_value=self.current), \
                patch.object(sender, 'validate_decision', return_value=d), \
                patch.object(sender, 'read_csv', return_value=[self.row()]):
            self.assertEqual(sender.send_once(smtp), 0)
            config.assert_not_called()
            smtp.assert_not_called()

    def test_scheduled_cards_hide_rejected_prices_but_keep_local_evidence(self):
        d = tactical_fixture()
        d['tactical_review']['drafts'][0].update(target_price='229', reward_to_risk='1.14', blockers=['reward_to_risk'])
        before = copy.deepcopy(d)
        _, text, html = render_email(d)
        self.assertNotIn('$217.75', text + html)
        self.assertNotIn('1.14R', text + html)
        self.assertIn('待研究标的：NVDA', text)
        self.assertIn('不替换', text)
        self.assertEqual(html.count('<h2 '), 6)
        self.assertEqual(d, before)


if __name__ == '__main__':
    unittest.main()
