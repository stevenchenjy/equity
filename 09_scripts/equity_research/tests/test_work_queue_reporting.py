from __future__ import annotations
import copy
import unittest
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa
from work_queue_reporting import work_health, cash_lines, research_lines, read_backlog_summary, BACKLOG_REL
from delivery_continuity import delivery_meaning_key
from daily_common import recommendation_notification_fingerprint
from email_brief import render_email
from test_delivery_continuity import fixture
from generate_current_status import workflow_health
import test_current_workflow_status as status_tests
from run_daily_refresh import STEP_SPECS
import run_daily_refresh as refresh_pipeline

NOW = datetime.fromisoformat('2026-09-27T16:00:00-04:00')


class WorkQueueReportingTests(unittest.TestCase):
    def test_advisory_failure_cannot_reuse_prior_success(self):
        payload = {'status': 'ready', 'generated_at': NOW.isoformat()}
        state = {'cycle_date': '2026-09-27', 'steps': [{'name': 'research_backlog', 'exit_code': 1}]}
        self.assertEqual(work_health(payload, state, current=NOW, step='research_backlog')['status'], 'failed')
        payload['generated_at'] = '2026-09-26T16:00:00-04:00'
        self.assertEqual(work_health(payload, {}, current=NOW, step='research_backlog')['freshness'], 'stale_or_unverified')
        self.assertEqual(work_health(None, {}, current=NOW, step='research_backlog')['status'], 'missing_or_invalid')

    def test_failed_or_timed_out_latest_attempt_covers_earlier_same_day_success(self):
        with tempfile.TemporaryDirectory() as temp, patch('research_backlog.validate_report'):
            root = Path(temp)
            path = root / BACKLOG_REL; path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'schema_version':'equity_research_backlog_v1', 'status':'ready',
                'generated_at':'2026-09-27T12:00:00-04:00', 'priority_queue':[], 'objective_dossiers_completed':3}))
            for code in (1, 124):
                with patch.object(refresh_pipeline, 'ROOT', root):
                    refresh_pipeline._record_work_step({'name':'research_backlog', 'exit_code':code,
                        'started_at':'2026-09-27T13:00:00-04:00', 'completed_at':'2026-09-27T13:04:00-04:00'})
                result = read_backlog_summary(root, current=NOW)
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('This run', ' '.join(research_lines({'research_backlog':result})))

    def test_cash_report_separates_planning_reserve_and_execution(self):
        decision = {'workflow_integrity': {'global_blockers': ['order_inventory_unverified'], 'ticker_blockers': {'AAA': ['valuation']}},
            'capital_work_queue': {'status': 'current', 'cash_explanation': {'status': 'planning_only',
                'strategic_reserve_usd': 587, 'unallocated_research_cash_usd': 2349.8}, 'next_automatic_review_at': 'next slot'}}
        body = ' '.join(cash_lines(decision))
        for expected in ('$587.00', '$2,349.80', 'Reasons overlap', 'execution funds still require confirmation'):
            self.assertIn(expected, body)
        decision['capital_work_queue']['status'] = 'unverified'
        self.assertNotIn('$2,349.80', ' '.join(cash_lines(decision)))

    def test_work_queue_dates_or_rank_rotation_do_not_create_delivery_event(self):
        before = fixture(); after = copy.deepcopy(before)
        after['capital_work_queue'] = {'status': 'current', 'generated_at': NOW.isoformat(), 'top_opportunities': [{'ticker': 'NEW'}]}
        after['research_backlog'] = {'priority_queue': [{'ticker': 'NEW'}]}
        self.assertEqual(delivery_meaning_key(before), delivery_meaning_key(after))

    def test_scoped_clock_aging_ignored_but_account_and_source_changes_notify(self):
        before = fixture(); after = copy.deepcopy(before)
        after['plan_continuity'].update(status='needs_reconciliation', ticker_blockers={'RBRK': ['review_due']})
        after['workflow_integrity']['ticker_blockers'] = {'RBRK': ['review_due']}
        self.assertEqual(delivery_meaning_key(before), delivery_meaning_key(after))
        after['workflow_integrity']['blockers'] = ['order_inventory_unverified_cannot_bound_buy_commitments']
        self.assertNotEqual(delivery_meaning_key(before), delivery_meaning_key(after))
        after = copy.deepcopy(before)
        after['workflow_integrity']['ticker_blockers'] = {'RBRK': ['source_hash_changed']}
        self.assertNotEqual(delivery_meaning_key(before), delivery_meaning_key(after))

    def test_held_core_candidate_renders_and_hashes_candidate_quantity(self):
        decision = fixture()
        decision.update(decision_code='action_review_candidate', eligible_new_position_review_candidates=['SPY'], new_candidate_stability_distinct_closes=2)
        decision['held_positions'] = [{'ticker':'SPY', 'action':'hold', 'current_shares':'1', 'whole_shares_to_change':'0'}]
        decision['watch_candidates'] = [{'ticker':'SPY', 'action':'core_allocation_tranche_review', 'suggested_whole_shares':'1', 'maximum_review_price':'771.35'}]
        text = render_email(decision)[1]
        self.assertIn('SPY eligible research proposal: change up to 1 shares', text)
        self.assertNotIn('change up to 0 shares', text)
        after = copy.deepcopy(decision); after['watch_candidates'][0]['suggested_whole_shares'] = '2'
        self.assertNotEqual(recommendation_notification_fingerprint(decision), recommendation_notification_fingerprint(after))

    def test_status_does_not_promote_local_review_gaps_to_global_freeze(self):
        args = status_tests.CurrentWorkflowStatusTests().fixture()
        args['decision']['plan_continuity'].update(block_new_capital=False, global_blockers=[], ticker_blockers={'APP':['expired_pending_verification']})
        result = workflow_health(**args)['plan_continuity']
        self.assertFalse(result['block_new_capital'])
        self.assertIn('maintained_plans_require_review', result['gaps'])

    def test_objective_work_precedes_existing_financial_admission(self):
        names = [row[0] for row in STEP_SPECS]
        self.assertLess(names.index('sec_filing_artifacts'), names.index('research_backlog'))
        self.assertLess(names.index('research_backlog'), names.index('earnings_incorporation'))
        self.assertLess(names.index('earnings_incorporation'), names.index('daily_decision'))


if __name__ == '__main__': unittest.main()
