"""Delivery envelopes expose only instructions actually shown to the owner."""
from __future__ import annotations
import copy
import unittest
from datetime import timedelta
from _support import SCRIPT_DIR  # noqa: F401
from daily_common import canonical_sha256
import delivery_assessments as contract
import delivery_followthrough as follow
from email_brief import render_email, priority_research_card
from capital_presentation import action_lines
import test_capital_decision as capital_tests


def capital_fixture():
    builder = capital_tests.CapitalDecisionTests()
    builder.setUp()
    decision = builder.d
    decision['capital_decision'] = builder.build()
    assert decision['capital_decision']['decisions'][0]['order_draft'], 'Fixture must clear real entry gates.'
    decision['analyst_priority_review'] = {
        'schema_version': 'equity_priority_review_context_v1', 'status': 'current',
        'reviewed_at': builder.v['current'].isoformat(),
        'next_review_at': (builder.v['current'] + timedelta(hours=2)).isoformat(),
        'entries': [{'ticker': 'META', 'reason': 'Official results changed the valuation work needed next.',
            'next_step': 'Rebuild the financing and downside case before considering entry.',
            'sources': [{'source_url': 'https://investor.atmeta.com/financials/'}]}]}
    return decision, builder.v['current']


def envelope(decision, *, changed=(), removed=(), priority=True):
    eligibility = {'eligible': True, 'mode': 'intraday_alert',
        'purpose_key': 'alert:' + decision['cycle_date'] + ':' + 'a'*64 + ':' + 'b'*64,
        'meaning_key': contract.advice_meaning_key(decision), 'action_changed': bool(changed or removed),
        'priority_changed': priority, 'changed_action_tickers': list(changed),
        'removed_action_tickers': list(removed)}
    result = copy.deepcopy(decision)
    result['delivery_assessment'] = contract.delivery_envelope(decision, eligibility,
        canonical_decision_sha256=canonical_sha256(decision))
    return result


class AssessmentPresentationTests(unittest.TestCase):
    def test_priority_only_alert_does_not_imply_hidden_canonical_draft_was_delivered(self):
        decision, stamp = capital_fixture()
        alert = envelope(decision)
        subject, plain, html = render_email(alert)
        self.assertIn('Research priority', subject)
        self.assertIn('META', plain)
        self.assertIn('No new or repeated trading instruction', plain)
        self.assertNotIn('BUY — TEST', plain)
        self.assertNotIn('Entry: LIMIT', plain)
        self.assertEqual(follow._displayed_actions(alert, plain, html, stamp), ([], False))
        self.assertEqual(alert['capital_decision'], decision['capital_decision'])

    def test_changed_action_includes_every_canonical_condition_and_is_recognized_exactly(self):
        decision, stamp = capital_fixture()
        alert = envelope(decision, changed=['TEST'], priority=False)
        _, plain, html = render_email(alert)
        self.assertIn('BUY — TEST', plain)
        for line in action_lines(decision['capital_decision']['decisions'][0]):
            self.assertIn(line, plain)
        shown, incomplete = follow._displayed_actions(alert, plain, html, stamp)
        self.assertFalse(incomplete)
        self.assertEqual([(r['ticker'], r['side'], r['quantity']) for r in shown], [('TEST', 'buy', 4)])
        # A modified archived body cannot acquire the execution-assumption branch.
        self.assertEqual(follow._displayed_actions(alert, plain.replace('Entry: LIMIT', 'Assess'), html, stamp), ([], True))

    def test_priority_card_is_background_and_stale_review_does_not_repeat_ticker_instructions(self):
        decision, _ = capital_fixture()
        card = priority_research_card(decision)
        self.assertEqual(card['group'], 'background')
        self.assertIn('1. META', card['body'])
        self.assertIn('https://investor.atmeta.com/financials/', card['sources'])
        decision['analyst_priority_review']['status'] = 'reassessment_due'
        stale = priority_research_card(decision)
        self.assertNotIn('META', stale['body'])
        self.assertEqual(stale['sources'], [])

    def test_envelope_cannot_smuggle_a_hidden_or_nondraft_ticker_into_followthrough(self):
        decision, stamp = capital_fixture()
        alert = envelope(decision)
        alert['delivery_assessment']['changed_action_tickers'] = ['META']
        alert['delivery_assessment']['action_changed'] = True
        value = alert['delivery_assessment']
        value['envelope_sha256'] = canonical_sha256({k: v for k, v in value.items() if k != 'envelope_sha256'})
        with self.assertRaises(ValueError):
            render_email(alert)
        self.assertEqual(follow._displayed_actions(alert, '', '', stamp), ([], True))


if __name__ == '__main__':
    unittest.main()
