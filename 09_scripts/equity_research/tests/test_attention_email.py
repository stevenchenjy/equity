"""Attention projection keeps complete orders and removes internal backlog mail."""
from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import canonical_sha256
from capital_presentation import action_lines
from email_brief import EMAIL_BRIEF_VERSION, render_email
from attention_email import cards
import test_capital_decision as capital_tests
from test_assessment_presentation import envelope
import delivery_followthrough as follow


class AttentionEmailTests(unittest.TestCase):
    def setUp(self):
        # Presentation edits correctly invalidate the source checkout's old
        # strategy bindings. Review exact current bytes only in a temporary
        # registry; never alter production admission to make a fixture pass.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = SCRIPT_DIR.parent.parent
        registry = json.loads((source / '01_policies/production_strategies.json').read_text())
        for strategy in registry['strategies']:
            strategy['policy_bindings']['09_scripts/equity_research/attention_email.py'] = ''
            for relative in strategy['policy_bindings']:
                original = source / relative
                strategy['policy_bindings'][relative] = hashlib.sha256(original.read_bytes()).hexdigest()
                link = self.root / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.exists():
                    link.symlink_to(original)
        registry_path = self.root / '01_policies/production_strategies.json'
        registry_path.parent.mkdir(parents=True, exist_ok=True)
        registry_path.write_text(json.dumps(registry))
        self.builder = capital_tests.CapitalDecisionTests()
        self.builder.setUp()
        self.decision = self.builder.d
        self.decision['email_brief_version'] = EMAIL_BRIEF_VERSION
        self.decision['capital_decision'] = self.build()

    def build(self):
        with patch.object(capital_tests, 'ROOT', self.root):
            return self.builder.build()

    def no_entry(self):
        self.decision['eligible_action_review_candidates'] = []
        self.decision['eligible_new_position_review_candidates'] = []
        self.decision['capital_decision'] = self.build()

    def test_complete_real_engine_buy_draft_survives_both_bodies_and_archive_admission(self):
        row = self.decision['capital_decision']['decisions'][0]
        before = copy.deepcopy(self.decision)
        subject, plain, document = render_email(self.decision)
        visible = html.unescape(re.sub(r'<[^>]+>', '', document))
        self.assertIn('Conditional action', subject)
        for line in action_lines(row):
            self.assertIn(line, plain)
            self.assertIn(' '.join(line.split()), ' '.join(visible.split()))
        shown, incomplete = follow._displayed_actions(self.decision, plain, document, self.builder.v['current'])
        self.assertFalse(incomplete)
        self.assertEqual([(r['ticker'], r['side'], r['quantity']) for r in shown], [('TEST', 'buy', 4)])
        self.assertEqual(self.decision, before)

    def test_large_unfinished_queue_is_counted_not_promoted_or_dumped(self):
        self.decision['long_horizon_research'] = {}
        self.decision['capital_decision'] = self.build()
        contract = self.decision['capital_decision']
        row = contract['decisions'][0]
        self.assertEqual(row['decision'], 'BLOCKED')
        contract['decisions'] += [{**copy.deepcopy(row), 'ticker': 'PENDING' + str(i),
            'reasons': ['UNFINISHED_DOSSIER ' * 200]} for i in range(42)]
        contract['content_sha256'] = canonical_sha256({k:v for k,v in contract.items() if k != 'content_sha256'})
        self.decision['research_opportunities'] = {'raw_queue': ['RAW_QUEUE_ITEM' * 100] * 50}
        subject, plain, document = render_email(self.decision)
        self.assertIn('No new trade', subject)
        self.assertNotIn('Action plan', subject)
        for body in (plain, document):
            self.assertNotIn('UNFINISHED_DOSSIER', body)
            self.assertNotIn('RAW_QUEUE_ITEM', body)
            self.assertNotIn('Candidate decisions — research detail', body)
            self.assertIn('43 need evidence', body)
            self.assertIn('No current source-bound analyst shortlist', body)
        self.assertLess(len(plain), 4000)

    def test_only_current_authored_priority_order_is_listed_and_bounded(self):
        self.no_entry()
        self.decision['analyst_priority_review'] = {'schema_version':'equity_priority_review_context_v1',
            'status':'current', 'reviewed_at':self.decision['generated_at'], 'next_review_at':'2026-09-23T15:00:00-04:00',
            'entries':[{'ticker':ticker, 'reason':'A reviewed operating change changes the downside case.',
                        'next_step':'Verify collected cash and update the current allocation case.',
                        'sources':[{'source_url':'https://www.sec.gov/Archives/edgar/data/1/report.htm'}]}
                       for ticker in ('CASEA','CASEB','CASEC','CASED')]}
        subject, plain, _ = render_email(self.decision)
        self.assertIn('Company attention', subject)
        self.assertLess(plain.index('1. CASEA'), plain.index('2. CASEB'))
        self.assertIn('3. CASEC', plain)
        self.assertNotIn('CASED', plain)
        self.assertIn('Decisive next step:', plain)
        self.assertIn('not a cleared buy', plain)
        self.decision['analyst_priority_review']['status'] = 'inputs_changed'
        subject, plain, _ = render_email(self.decision)
        self.assertIn('No new trade', subject)
        self.assertNotIn('CASEA', plain)

    def test_material_global_failure_remains_prominent_with_no_synthetic_order(self):
        self.decision['workflow_integrity']['global_blockers'] = ['unrecorded_account_change']
        self.decision['capital_decision'] = self.build()
        _, plain, document = render_email(self.decision)
        self.assertIn('Required before any new trade', plain)
        self.assertIn('account', plain.lower())
        self.assertNotIn('Entry: LIMIT', plain)
        self.assertNotIn('BUY — TEST', document)

    def test_adverse_undrafted_exit_cannot_be_hidden_as_routine_hold(self):
        self.no_entry()
        c = self.decision['capital_decision']
        row = c['decisions'][0]
        row.update(decision='EXIT_REVIEW', reasons=['Verified loss of the sole customer requires immediate exit assessment.'])
        c['content_sha256'] = canonical_sha256({k:v for k,v in c.items() if k != 'content_sha256'})
        sections = cards(self.decision)
        exit_card = next(s for s in sections if s['title'] == 'EXIT REVIEW — TEST')
        self.assertEqual(exit_card['group'], 'action')
        self.assertEqual(exit_card['kind'], 'sell')
        _, plain, _ = render_email(self.decision)
        self.assertLess(plain.index('EXIT REVIEW — TEST'), plain.index('Opportunity shortlist'))
        self.assertIn(row['reasons'][0], plain)
        self.assertNotIn('Entry: LIMIT', plain)

    def test_independent_complete_exit_is_not_contradicted_by_source_limitation_banner(self):
        self.decision['eligible_new_position_review_candidates'] = []
        self.decision['watch_candidates'] = []
        self.decision['held_positions'] = [dict(ticker='TEST', current_shares=2, current_price=101, asset_role='active_stock')]
        self.decision['plan_continuity'] = {'plans':[dict(ticker='TEST', status='maintained', action='sell_review',
            blockers=['fresh_quote_and_available_shares_required'], review_at='2026-09-23T15:30:00-04:00',
            instruction='Reassess the complete two-share conditional exit; no order is submitted.',
            reason='Maintained sourced thesis exit', historical_order_draft={'side':'sell','type':'LIMIT',
            'quantity':2,'limit_price':102,'time_in_force':'DAY','session_date':'2026-09-23'})]}
        self.decision['evidence_gate']['passed'] = False
        self.decision['capital_decision'] = self.build()
        row = self.decision['capital_decision']['decisions'][0]
        self.assertEqual(row['decision'], 'EXIT_REVIEW')
        self.assertIsNotNone(row['order_draft'])
        _, plain, document = render_email(self.decision)
        self.assertIn('separately admitted sell/protection draft', plain)
        self.assertNotIn('No new order is approved', plain)
        for line in action_lines(row):
            self.assertIn(line, plain)
        self.assertIn('data-action-kind="sell"', document)

    def test_mixed_buy_and_unchanged_holding_zero_is_scoped_to_existing_holding(self):
        self.decision['held_positions'] = [dict(ticker='SPY', current_shares=2, current_price=100, asset_role='core_allocation')]
        self.decision['plan_continuity'] = {'plans':[dict(ticker='SPY', status='maintained', action='hold',
            instruction='Retain the two recorded index shares', blockers=[],
            review_at='2026-09-23T15:30:00-04:00', valid_until='2026-09-23T16:00:00-04:00')]}
        self.decision['capital_decision'] = self.build()
        self.assertTrue(any(r.get('order_draft') for r in self.decision['capital_decision']['decisions']))
        _, plain, _ = render_email(self.decision)
        self.assertIn('BUY — TEST', plain)
        self.assertIn('For these holdings only: add 0 / sell 0', plain)
        self.assertIn('Separate action cards govern any other ticker', plain)
        self.assertIn('SPY 2 recorded shares', plain)

    def test_skip_only_rotation_is_no_new_trade_not_positive_rotation_subject(self):
        self.no_entry()
        skip = {'title':'Skip the rotation', 'body':'Prices fail the fixed limits.', 'kind':'inactive', 'group':'action', 'sources':[]}
        with patch('attention_email.optional_rotation_cards', return_value=[skip]):
            subject, plain, _ = render_email(self.decision)
        self.assertIn('No new trade', subject)
        self.assertIn('Skip the rotation', plain)
        self.assertNotIn('Read the complete conditional drafts', plain)

    def test_held_completed_negative_is_no_action_not_unfinished_company_research(self):
        self.no_entry()
        self.decision['held_positions'] = [dict(ticker='TEST', current_shares=1, current_price=101, asset_role='active_stock')]
        c = self.decision['capital_decision']
        row = c['decisions'][0]
        row.update(decision='NO_ACTION', reasons=['Completed current company review: the observed price fails the unchanged valuation test.'],
                   research_case={'review_status':'current', 'business_case_status':'mixed', 'valuation_readiness':'reviewed_scenarios'})
        c['content_sha256'] = canonical_sha256({k:v for k,v in c.items() if k != 'content_sha256'})
        _, plain, document = render_email(self.decision)
        visible = html.unescape(re.sub(r'<[^>]+>', '', document))
        for body in (plain, visible):
            self.assertIn('No additional action — TEST', body)
            self.assertIn(row['reasons'][0], body)
            self.assertNotIn('Holding decision incomplete — TEST', body)
            self.assertNotIn('BUY — TEST', body)

    def test_v4_alert_uses_shared_shell_and_preserves_withdrawal(self):
        alert = envelope(self.decision, removed=['OLD'], priority=False)
        subject, plain, document = render_email(alert)
        self.assertIn('Action update', subject)
        self.assertIn('OLD — previous eligible instruction withdrawn; do not resubmit its earlier quantity.', plain)
        self.assertIn('max-width:600px', document)
        self.assertNotIn('BUY — TEST', plain)

    def test_v4_changed_action_alert_preserves_every_exact_condition_for_followthrough(self):
        alert = envelope(self.decision, changed=['TEST'], priority=False)
        _, plain, document = render_email(alert)
        for line in action_lines(self.decision['capital_decision']['decisions'][0]):
            self.assertIn(line, plain)
        shown, incomplete = follow._displayed_actions(alert, plain, document, self.builder.v['current'])
        self.assertFalse(incomplete)
        self.assertEqual([(r['ticker'], r['side'], r['quantity']) for r in shown], [('TEST', 'buy', 4)])

    def test_v3_alert_keeps_historical_renderer(self):
        self.decision['email_brief_version'] = 'equity_action_email_v3'
        alert = envelope(self.decision, changed=['TEST'], priority=False)
        _, plain, document = render_email(alert)
        self.assertTrue(document.startswith('<html><body>'))
        self.assertNotIn('max-width:600px', document)
        shown, incomplete = follow._displayed_actions(alert, plain, document, self.builder.v['current'])
        self.assertFalse(incomplete)
        self.assertEqual(len(shown), 1)


if __name__ == '__main__':
    unittest.main()
