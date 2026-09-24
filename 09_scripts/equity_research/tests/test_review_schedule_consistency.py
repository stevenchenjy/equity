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

    def critical_decision(self):
        decision = decision_fixture()
        decision.update(
            account_conflicts=['open_order_reconciliation'],
            material_events=[{'ticker': 'TEST', 'accession_number': 'event-1'}],
            evidence_gate={'passed': False, 'reason': 'source_unavailable'},
        )
        return decision

    def coverage_row(self, decision, **kwargs):
        row = self.row(**kwargs)
        row['reason'] = 'explicit_owner_review;' + sender.owner_review_coverage_key(decision)
        return row

    def test_exact_critical_content_is_covered_for_all_durable_owner_states(self):
        decisions = [self.critical_decision(), action_fixture()]
        for decision in decisions:
            for status in sender.OWNER_REVIEW_DELIVERY_STATUSES:
                with self.subTest(status=status, code=decision.get('decision_code')):
                    self.assertTrue(self.covered([self.coverage_row(decision, status=status)], decision))

    def test_exact_coverage_keeps_actual_et_date_and_status_guards(self):
        decision = self.critical_decision()
        for stamp in ['2026-09-22T23:59:00-04:00', '2026-09-23T14:00:00-04:00',
                      '2026-09-23T08:00:00', '2026-09-23T02:00:00+00:00', 'bad']:
            with self.subTest(stamp=stamp):
                self.assertFalse(self.covered([self.coverage_row(decision, stamp=stamp)], decision))
        self.assertFalse(self.covered([self.coverage_row(decision, status='sent')], decision))

    def test_any_changed_canonical_risk_or_plan_remains_eligible(self):
        original = self.critical_decision()
        row = self.coverage_row(original)
        changes = [
            ('material_events', [{'ticker': 'TEST', 'accession_number': 'event-2'}]),
            ('account_conflicts', ['different_order_conflict']),
            ('evidence_gate', {'passed': False, 'reason': 'different_source_unavailable'}),
            ('market_gate', {'passed': False, 'reason': 'stale_session'}),
            ('fundamental_gate', {'passed': True, 'weakening_tickers': ['TEST']}),
            ('account', {'cash_available': '4000', 'cash_basis': 'ledger_estimate'}),
            ('tactical_review', {'open_orders': {'orders': [{'ticker': 'TEST', 'quantity': 2}]}}),
            ('held_positions', [{'ticker': 'TEST', 'action': 'sell', 'whole_shares_to_change': 1,
                                 'reason': 'Changed risk rationale', 'target_price': '110'}]),
            ('generated_at', '2026-09-23T13:38:00-04:00'),
        ]
        for key, value in changes:
            decision = copy.deepcopy(original)
            decision[key] = value
            with self.subTest(key=key):
                self.assertFalse(self.covered([row], decision))

    def test_only_owner_appendix_is_excluded_and_hashing_does_not_mutate(self):
        decision = self.critical_decision()
        before = copy.deepcopy(decision)
        key = sender.owner_review_coverage_key(decision)
        self.assertEqual(decision, before)
        decision['owner_requested_research'] = {'sections': [{'body': 'Dated separate research'}]}
        self.assertEqual(sender.owner_review_coverage_key(decision), key)
        decision['tactical_review'] = {'drafts': [{'ticker': 'TEST', 'entry_price': 100,
                                                 'stop_price': 95, 'target_price': 112,
                                                 'quantity': 1, 'reason': 'First rationale'}]}
        row = self.coverage_row(decision)
        for field, value in [('entry_price', 101), ('stop_price', 96), ('target_price', 115),
                             ('quantity', 2), ('reason', 'Changed rationale')]:
            changed = copy.deepcopy(decision)
            changed['tactical_review']['drafts'][0][field] = value
            with self.subTest(field=field):
                self.assertFalse(self.covered([row], changed))

    def test_matching_coverage_requires_exact_marker_not_a_substring(self):
        decision = self.critical_decision()
        row = self.coverage_row(decision)
        row['reason'] += 'extra'
        self.assertFalse(self.covered([row], decision))

    def test_exact_reviewed_risk_suppresses_before_credentials_or_smtp(self):
        decision = self.critical_decision()
        decision.update(send_recommended=True, cycle_date='2026-09-23')
        with delivery_fixture() as (config, smtp), \
                patch.object(sender, 'now_et', return_value=self.current), \
                patch.object(sender, 'validate_decision', return_value=decision), \
                patch.object(sender, 'read_csv', return_value=[self.coverage_row(decision)]):
            self.assertEqual(sender.send_once(smtp), 0)
            config.assert_not_called()
            smtp.assert_not_called()

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
