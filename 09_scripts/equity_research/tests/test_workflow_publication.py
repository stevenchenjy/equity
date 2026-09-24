from __future__ import annotations
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from _support import SCRIPT_DIR  # noqa: F401
from test_email_brief import decision_fixture
from test_investment_plans import ledger
from daily_common import recommendation_notification_fingerprint
from email_brief import build_email_view, render_email
from investment_plans import RELATIVE_PATH
from workflow_integrity import apply_workflow_integrity, validate_published_workflow, record_decision_history


class WorkflowPublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.now = datetime.fromisoformat('2026-09-24T12:05:00-04:00')
        (self.root / RELATIVE_PATH).parent.mkdir(parents=True)
        (self.root / RELATIVE_PATH).write_text(json.dumps(ledger()))
        (self.root / 'receipt.json').write_bytes(b'receipt')
        self.orders_path = self.root / '05_risk_and_positions/current_open_orders.local.json'
        self.orders_path.write_text(json.dumps({'as_of': '2026-09-24T12:00:00-04:00', 'complete': True, 'orders': []}))
        self.earnings = {'companies': {'TEST': {'status': 'incorporated', 'positive_decision_eligible': True, 'selected_period_end': '2026-06-30', 'financial_economic_sha256': 'one'}}, 'held_pending_tickers': []}
        self.patch = patch('workflow_integrity.read_earnings_incorporation_status', side_effect=lambda **kwargs: copy.deepcopy(self.earnings))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def decision(self):
        value = decision_fixture()
        value.update(generated_at=self.now.isoformat(), cycle_date='2026-09-24')
        value['held_positions'] = [{'ticker': 'TEST', 'current_shares': '4', 'action': 'hold_pending_research', 'reason': 'generic hold', 'asset_role': 'active_stock'}]
        value['evidence_coverage'] = {'official_news': {'required_coverage_complete': True}}
        value['watch_candidates'] = [{'ticker': 'NEW', 'suggested_whole_shares': '1', 'label': 'real-trade candidate'}]
        value['eligible_new_position_review_candidates'] = ['NEW']
        return value

    def test_compose_render_and_send_validation_share_plan_state(self):
        value = self.decision()
        apply_workflow_integrity(value, root=self.root, current=self.now)
        self.assertEqual(value['held_positions'][0]['action'], 'maintained_plan_review')
        self.assertFalse(value['eligible_new_position_review_candidates'])
        self.assertEqual(value['watch_candidates'][0]['suggested_whole_shares'], '0')
        self.assertEqual(value['held_positions'][0]['baseline_research']['reason'], 'generic hold')
        validate_published_workflow(value, root=self.root, current=self.now)
        for body in render_email(value)[1:]:
            self.assertIn('TEST-plan', body)
            self.assertIn('2026-09-25T15:45', body)
            self.assertNotIn('报告状态未识别', body)
        with self.assertRaisesRegex(ValueError, 'plan_state_changed'):
            validate_published_workflow(value, root=self.root, current=datetime.fromisoformat('2026-09-24T16:01:00-04:00'))

    def test_changed_account_or_financial_values_require_recomposition(self):
        value = self.decision()
        apply_workflow_integrity(value, root=self.root, current=self.now)
        self.earnings['companies']['TEST']['financial_economic_sha256'] = 'corrected'
        with self.assertRaisesRegex(ValueError, 'earnings_changed'):
            validate_published_workflow(value, root=self.root, current=self.now)
        self.earnings['companies']['TEST']['financial_economic_sha256'] = 'one'
        self.orders_path.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'inputs_changed'):
            validate_published_workflow(value, root=self.root, current=self.now)

    def test_expired_plan_visible_when_cash_estimated_and_account_blocked(self):
        value = self.decision()
        value['account']['cash_basis'] = 'ledger_estimate'
        value['account_conflicts'] = ['account_needs_review']
        apply_workflow_integrity(value, root=self.root, current=datetime.fromisoformat('2026-09-24T16:01:00-04:00'))
        view = build_email_view(value)
        self.assertFalse(view['plans'])
        self.assertIn('期限持续有效', view['next_step'])
        text = render_email(value)[1]
        self.assertIn('旧方案已到期', text)
        self.assertIn('2026-09-25T15:45', text)
        self.assertNotIn('没有交易截止时刻', text)

    def test_history_and_notifications_ignore_clock_but_record_semantic_change(self):
        first = self.decision()
        apply_workflow_integrity(first, root=self.root, current=self.now)
        second = self.decision()
        second['generated_at'] = '2026-09-24T12:06:00-04:00'
        apply_workflow_integrity(second, root=self.root, current=datetime.fromisoformat(second['generated_at']))
        self.assertEqual(recommendation_notification_fingerprint(first), recommendation_notification_fingerprint(second))
        record_decision_history(first, root=self.root)
        record_decision_history(second, root=self.root)
        path = self.root / '00_project_control/run_logs/decision_history.local.jsonl'
        self.assertEqual(len(path.read_text().splitlines()), 1)
        third = self.decision()
        third['generated_at'] = '2026-09-24T16:01:00-04:00'
        apply_workflow_integrity(third, root=self.root, current=datetime.fromisoformat(third['generated_at']))
        self.assertNotEqual(recommendation_notification_fingerprint(first), recommendation_notification_fingerprint(third))
        record_decision_history(third, root=self.root)
        rows = [json.loads(row) for row in path.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['previous_hash'], rows[0]['record_hash'])
        self.assertIn('plans', rows[1]['changed_components'])
        rows[0]['workflow_fingerprint'] = 'tampered'
        path.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
        with self.assertRaisesRegex(ValueError, 'hash_chain'):
            record_decision_history(third, root=self.root)

    def test_data_and_weakening_blocks_are_not_erased(self):
        for code in ('data_gate_hold', 'fundamental_weakening_review'):
            value = self.decision()
            value['decision_code'] = code
            if code == 'data_gate_hold':
                value['market_gate']['passed'] = False
            else:
                value['fundamental_gate']['weakening_tickers'] = ['TEST']
            apply_workflow_integrity(value, root=self.root, current=self.now)
            self.assertEqual(value['decision_code'], code)
            self.assertFalse(value['eligible_new_position_review_candidates'])
