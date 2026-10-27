from __future__ import annotations

import copy
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import subprocess
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ET, atomic_write_json, canonical_sha256
from account_access import input_version
from account_authority import load_authority
import capital_decision as capital
import delivery_assessments as delivery
from delivery_followthrough import build_followthrough, continuation_requires_reconciliation
from email_brief import render_email
import post_delivery_publication as repair
import run_daily_decision_pipeline as pipeline
import run_daily_scheduler as scheduler
from send_daily_email import LEDGER_FIELDS
import test_refresh_recovery as market_fixture
import test_short_assessment as short_fixture
import test_capital_decision as capital_fixture
from test_delivery_assessments import action_row

NOW = datetime(2026, 10, 26, 10, 0, tzinfo=ET)


class PostDeliveryPublicationTests(unittest.TestCase):
    def setUp(self):
        market = market_fixture.MarketRecoveryTests(); market.setUp(); self.addCleanup(market.doCleanups)
        self.market = market; self.root = market.root.resolve(); market.capture()
        fixture = short_fixture.ShortAssessmentTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        config = json.loads((fixture.root / delivery.CONFIG_REL).read_text())
        config['notifications'].update(mandatory_daily_briefs=True, intraday_alerts_enabled=True,
            delivery_windows_et=[{'id': 'morning', 'start': '09:30', 'end': '10:30', 'refresh_not_before': '08:00'},
                {'id': 'afternoon', 'start': '14:30', 'end': '15:05', 'refresh_not_before': '13:30'}])
        self.config = config; atomic_write_json(self.root / delivery.CONFIG_REL, config)
        atomic_write_json(self.root / '05_risk_and_positions/current_account_state.local.json',
            {'cash_available': 1000, 'account_total_value': 1000})
        fixture.root = self.root
        self.decision = fixture.typed_publication('09:40')
        self.decision.update(schema_version='phase5r_daily_decision_v1', cycle_date=NOW.date().isoformat(), generated_at=NOW.replace(hour=9, minute=40).isoformat(),
            account_input_version=input_version(self.root))
        self.decision['market_gate'].update(expected_market_session='2026-10-23')
        from investment_plans import load_plan_context
        self.decision['plan_continuity'] = load_plan_context(self.root, self.decision.get('held_positions', []), NOW)
        self.decision['analyst_priority_review'] = delivery.priority_review_context(self.root, NOW)
        self.ledger = self.root / repair.LEDGER; self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open('w', newline='') as f: csv.DictWriter(f, fieldnames=LEDGER_FIELDS).writeheader()
        from run_daily_refresh import STEP_SPECS
        atomic_write_json(self.root / '00_project_control/run_logs/daily_refresh_state.local.json', {
            'outcome': 'passed', 'cycle_date': NOW.date().isoformat(), 'expected_market_session': '2026-10-23',
            'started_at': NOW.replace(hour=8).isoformat(), 'completed_at': NOW.replace(hour=9, minute=20).isoformat(),
            'steps': [{'name': name, 'exit_code': 0} for name, _, _ in STEP_SPECS]})
        self.capital(self.decision)
        self.save(self.decision)
        self.calls = []; self.seconds = 0

    def capital(self, value):
        contract = value.get('capital_decision', {'schema_version': capital.SCHEMA,
            'automatic_action_allowed': False, 'broker_connected': False, 'order_placed': False,
            'decisions': [], 'global_blockers': [], 'dependencies': [],
            'planning_cash': 1000.0, 'mandatory_reserve': 0.0})
        contract.update(source_bindings=capital.binding(self.root), account_authority=load_authority(self.root, NOW))
        contract['content_sha256'] = canonical_sha256({k: v for k, v in contract.items() if k != 'content_sha256'})
        value['capital_decision'] = contract

    def save(self, value):
        atomic_write_json(self.root / repair.ARTIFACTS[0], value)
        _, text, html = (delivery.render_failure_brief(value)
            if value.get('schema_version') == 'equity_mandatory_status_brief_v1' else render_email(value))
        for path, body in zip(repair.ARTIFACTS[1:], (text, html)):
            (self.root / path).write_text(body)

    def append_delivery(self, *, status='sent', envelope=False):
        value = copy.deepcopy(self.decision)
        if envelope:
            canonical_raw = (self.root / repair.ARTIFACTS[0]).read_bytes()
            canonical_digest = hashlib.sha256(canonical_raw).hexdigest()
            directory = self.root / delivery.ARCHIVE_REL; directory.mkdir(parents=True, exist_ok=True)
            (directory / (canonical_digest + '.json')).write_bytes(canonical_raw)
            eligibility = {'eligible': True, 'mode': 'intraday_alert',
                'purpose_key': 'alert:2026-10-26:'+'a'*64+':'+'b'*64,
                'baseline_receipt_sha256': 'b' * 64,
                'meaning_key': delivery.advice_meaning_key(value), 'action_changed': True,
                'priority_changed': False, 'changed_action_tickers': ['SYN'], 'removed_action_tickers': []}
            value['delivery_assessment'] = delivery.delivery_envelope(value, eligibility,
                canonical_decision_sha256=canonical_digest)
        body = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
        _, text, html = (delivery.render_failure_brief(value)
            if value.get('schema_version') == 'equity_mandatory_status_brief_v1' else render_email(value))
        contents = [('decision_sha256', '.json', body), ('brief_text_sha256', '.txt', text.encode()),
                    ('brief_html_sha256', '.html', html.encode())]
        hashes = {}
        for key, suffix, raw in contents:
            digest = hashlib.sha256(raw).hexdigest(); hashes[key] = digest
            path = self.root / delivery.ARCHIVE_REL / (digest + suffix)
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        reason = ('delivery_mode=intraday_alert;delivery_purpose_v1='+eligibility['purpose_key'] if envelope else
            'delivery_mode=scheduled_brief;delivery_purpose_v1=brief:2026-10-26:morning;scheduled_slot=morning')
        claim = {'timestamp': NOW.replace(hour=9, minute=43, second=4).isoformat(), 'cycle_date': NOW.date().isoformat(),
            'status': 'send_claimed', 'reason': 'pre_smtp_durable_claim;'+reason, 'decision_fingerprint': value['decision_fingerprint'],
            'message_count': '0', 'email_attempted': 'no', 'email_sent': 'no', **hashes}
        sent = {**claim, 'timestamp': NOW.replace(hour=9, minute=43, second=7).isoformat(), 'status': status,
                'message_count': '1' if status == 'sent' else '0', 'reason': 'smtp_send_completed;'+reason,
                'email_attempted': 'yes', 'email_sent': 'yes' if status == 'sent' else 'unknown'}
        with self.ledger.open('a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=LEDGER_FIELDS); writer.writerow(claim); writer.writerow(sent)
        return sent

    def positive_draft(self):
        row = action_row('SYN', 1)
        row['key_evidence'] = [{'source': 'Synthetic retained primary fixture'}]
        row['order_draft'].update(automatic_action_allowed=False, planned_loss_per_share=10.0,
            account_value=4000.0, entry_window={'session': '2026-10-26',
                'starts_at': '2026-10-26T09:30:00-04:00', 'ends_at': '2026-10-26T15:30:00-04:00'})
        self.decision['capital_decision']['decisions'] = [row]
        self.capital(self.decision); self.save(self.decision)

    def runner(self, name, script, allowed, **kwargs):
        self.calls.append(name)
        self.assertFalse(allowed); self.assertEqual(kwargs['market_snapshot_mode'], 'reuse_validated_snapshot')
        self.assertLessEqual(kwargs['maximum_child_seconds'], 75)
        if name == 'daily_decision':
            value = json.loads((self.root / repair.ARTIFACTS[0]).read_text())
            value['generated_at'] = NOW.isoformat()
            value['delivery_followthrough'] = build_followthrough(value, root=self.root, current=NOW)
            if continuation_requires_reconciliation(value['delivery_followthrough']):
                for row in value['capital_decision']['decisions']:
                    row.update(decision='BLOCKED', shares=0, order_draft=None,
                        blockers=['earlier_instruction_execution_unreconciled'],
                        reasons=['Previously delivered instructions require actual reconciliation.'])
            self.capital(value)
            value['delivery_followthrough'] = build_followthrough(value, root=self.root, current=NOW)
            self.save(value)
        return {'name': name, 'exit_code': 0}

    def recover(self, runner=None, **kwargs):
        return repair.recover_locked(self.root, clock=lambda: NOW, step_runner=runner or self.runner,
            monotonic=lambda: self.seconds, **kwargs)

    def test_actual_pair_repairs_exact_binding_and_outputs_without_research_or_mail(self):
        self.append_delivery(); ledger = self.ledger.read_bytes()
        before = repair._hashes(self.root, (*repair.ACCOUNT_MARKET, *repair.MUTABLE_STORES,
            '00_project_control/run_logs/daily_refresh_state.local.json'))
        with self.assertRaisesRegex(ValueError, 'inputs_changed_recompose_required'):
            capital.validate(self.decision['capital_decision'], root=self.root, current=NOW)
        result = self.recover()
        self.assertEqual(result['outcome'], 'passed', result)
        self.assertEqual(self.calls, list(repair.STEP_NAMES))
        self.assertFalse(result['fully_passed_research']); self.assertFalse(result['email_attempted'])
        self.assertEqual(self.ledger.read_bytes(), ledger)
        self.assertEqual(before, repair._hashes(self.root, before))
        repair._validate_current(self.root, NOW)
        current = json.loads((self.root / repair.ARTIFACTS[0]).read_text())
        capital.validate(current['capital_decision'], root=self.root, current=NOW)
        eligibility = delivery.delivery_eligibility(current, root=self.root, current=NOW,
            rows=list(csv.DictReader(self.ledger.read_text().splitlines())), mode='intraday_alert')
        self.assertFalse(eligibility['eligible'])

    def test_no_append_dedup_skip_or_unknown_does_not_run_closure(self):
        self.assertEqual(self.recover()['outcome'], 'not_required'); self.assertEqual(self.calls, [])
        self.append_delivery(status='delivery_unknown')
        result = self.recover(); self.assertEqual(result['outcome'], 'not_applicable')
        self.assertTrue(result['publication_pending']); self.assertEqual(self.calls, [])

    def test_no_ledger_first_send_is_not_required_and_status_only_cannot_repair_canonical_advice(self):
        self.ledger.unlink(); self.capital(self.decision); self.save(self.decision)
        self.assertEqual(self.recover()['outcome'], 'not_required')
        with self.ledger.open('w', newline='') as f: csv.DictWriter(f, fieldnames=LEDGER_FIELDS).writeheader()
        self.capital(self.decision); self.save(self.decision)
        self.decision = delivery.build_failure_brief(self.root, NOW.replace(hour=9, minute=40),
            'morning', 'capital_decision_inputs_changed_recompose_required')
        self.append_delivery()
        result = self.recover()
        self.assertEqual(result['outcome'], 'not_applicable'); self.assertTrue(result['publication_pending'])
        self.assertEqual(self.calls, [])

    def test_prefix_archive_and_current_html_tampering_are_rejected(self):
        receipt = self.append_delivery()
        original = self.ledger.read_bytes(); self.ledger.write_bytes(original.replace(b'timestamp,', b'timestamp ,', 1))
        self.assertEqual(self.recover()['outcome'], 'rejected'); self.ledger.write_bytes(original)
        path = self.root / delivery.ARCHIVE_REL / (receipt['brief_html_sha256'] + '.html')
        raw = path.read_bytes(); path.write_bytes(raw+b'forged')
        self.assertEqual(self.recover()['outcome'], 'rejected'); path.write_bytes(raw)
        (self.root / repair.ARTIFACTS[2]).write_text('unexpected current HTML')
        self.assertEqual(self.recover()['outcome'], 'rejected'); self.assertEqual(self.calls, [])

    def test_account_analyst_source_and_corrupt_original_market_history_do_not_admit_repair(self):
        self.append_delivery()
        path = self.root / '05_risk_and_positions/investment_plans.local.json'
        raw = path.read_bytes(); path.write_bytes(raw+b' ')
        self.assertEqual(self.recover()['outcome'], 'rejected'); path.write_bytes(raw)
        raw = self.market.raw.read_bytes(); self.market.raw.write_bytes(raw+b'corrupt')
        result = self.recover(); self.assertIn('current_market_admission_required', result['reason'])
        self.market.raw.write_bytes(raw)
        account = self.root / '05_risk_and_positions/current_account_state.local.json'
        account.write_text('{"unexpected_account_change":true}')
        self.assertEqual(self.recover()['outcome'], 'rejected'); self.assertEqual(self.calls, [])

    def test_changed_inputs_during_closure_fail_and_preserve_smtp_receipt(self):
        self.append_delivery(); original = self.ledger.read_bytes()
        def mutate(*args, **kwargs):
            result = self.runner(*args, **kwargs)
            (self.root / '04_data/equity_research/valuation_research_inputs.local.json').parent.mkdir(parents=True, exist_ok=True)
            (self.root / '04_data/equity_research/valuation_research_inputs.local.json').write_text('{"new_model":true}')
            return result
        result = self.recover(mutate)
        self.assertEqual(result['outcome'], 'failed'); self.assertTrue(result['alert_required'])
        self.assertEqual(self.ledger.read_bytes(), original)

    def test_partial_stage_failure_retries_on_next_poll_without_another_send(self):
        self.append_delivery(); original = self.ledger.read_bytes()
        def fail(name, *args, **kwargs):
            return {'name': name, 'exit_code': 124} if name == 'workflow_evaluation' else self.runner(name, *args, **kwargs)
        self.assertEqual(self.recover(fail)['outcome'], 'failed')
        self.calls = []; result = self.recover()
        self.assertEqual(result['outcome'], 'passed', result)
        self.assertEqual(self.calls, list(repair.STEP_NAMES)); self.assertEqual(self.ledger.read_bytes(), original)

    def test_protected_short_window_actual_clock_and_shared_budget_defer_without_steps(self):
        self.append_delivery()
        with patch('run_daily_refresh_scheduler.short_window_conflict', return_value={'reason': 'protected'}):
            self.assertEqual(self.recover()['outcome'], 'deferred')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.recover(maximum_seconds=0)['outcome'], 'deferred')
        def exhausted(*args, **kwargs):
            value = self.runner(*args, **kwargs); self.seconds = 200; return value
        self.assertEqual(self.recover(exhausted)['outcome'], 'failed')
        self.assertLess(len(self.calls), len(repair.STEP_NAMES))

    def test_slow_proof_rechecks_actual_clock_before_starting_stages(self):
        self.append_delivery(); calls = [0]
        def clock():
            calls[0] += 1
            return NOW.replace(hour=10, minute=55 if calls[0] == 1 else 59)
        result = repair.recover_locked(self.root, clock=clock, step_runner=self.runner,
            monotonic=lambda: 0)
        self.assertEqual(result['outcome'], 'deferred'); self.assertEqual(self.calls, [])

    def test_later_full_refresh_supersedes_failed_helper_without_replaying_old_sources(self):
        self.append_delivery()
        def fail(name, *args, **kwargs):
            return {'name': name, 'exit_code': 1} if name == 'workflow_evaluation' else self.runner(name, *args, **kwargs)
        self.assertEqual(self.recover(fail)['outcome'], 'failed')
        path = self.root / '00_project_control/run_logs/daily_refresh_state.local.json'
        full = json.loads(path.read_text()); full['completed_at'] = (NOW+timedelta(seconds=1)).isoformat()
        atomic_write_json(path, full); self.calls = []
        result = repair.recover_locked(self.root, clock=lambda: NOW+timedelta(seconds=2), step_runner=self.runner,
            monotonic=lambda: self.seconds)
        self.assertEqual(result['outcome'], 'superseded_by_full_refresh', result)
        self.assertFalse(result['publication_pending']); self.assertEqual(self.calls, [])

    def test_real_priority_envelope_uses_canonical_source_without_inventing_delivery_scope(self):
        self.positive_draft()
        self.append_delivery(envelope=True)
        result = self.recover(); self.assertEqual(result['outcome'], 'passed', result)
        current = json.loads((self.root / repair.ARTIFACTS[0]).read_text())
        self.assertFalse(current['delivery_followthrough']['canonical_state_changed'])

    def test_delivered_positive_draft_preserves_conditional_followthrough_and_withholds_repeat(self):
        self.positive_draft(); self.append_delivery(); ledger = self.ledger.read_bytes()
        result = self.recover(); self.assertEqual(result['outcome'], 'passed', result)
        current = json.loads((self.root / repair.ARTIFACTS[0]).read_text())
        follow = current['delivery_followthrough']
        self.assertEqual(follow['status'], 'conditional_execution_followthrough')
        self.assertFalse(follow['canonical_state_changed']); self.assertFalse(follow['creates_trade_eligibility'])
        self.assertEqual(current['capital_decision']['decisions'][0]['shares'], 0)
        self.assertIsNone(current['capital_decision']['decisions'][0]['order_draft'])
        self.assertEqual(self.ledger.read_bytes(), ledger)
        eligibility = delivery.delivery_eligibility(current, root=self.root, current=NOW,
            rows=list(csv.DictReader(self.ledger.read_text().splitlines())), mode='intraday_alert')
        self.assertFalse(eligibility['eligible'])

    def test_genuine_adverse_blocker_and_real_build_reason_only_rejection_remain_alerts(self):
        self.positive_draft(); self.append_delivery(); self.assertEqual(self.recover()['outcome'], 'passed')
        current = json.loads((self.root / repair.ARTIFACTS[0]).read_text())
        rows = list(csv.DictReader(self.ledger.read_text().splitlines()))
        adverse = copy.deepcopy(current)
        adverse['capital_decision']['decisions'][0]['blockers'].append('fundamental_gate_failed')
        self.capital(adverse)
        self.assertTrue(delivery.delivery_eligibility(adverse, root=self.root, current=NOW,
            rows=rows, mode='intraday_alert')['eligible'])
        # The real builder can report economic failure in canonical reasons
        # with no missing-evidence blocker. Use that output rather than a
        # handcrafted blocked row, then bind its changed retained model input.
        case = capital_fixture.CapitalDecisionTests(); case.setUp(); self.addCleanup(case.doCleanups)
        case.d['eligible_new_position_review_candidates'] = []
        case.d['eligible_action_review_candidates'] = []
        case.d['workflow_integrity']['ticker_blockers'] = {'TEST': ['reviewed_business_case_not_supported']}
        case.d['watch_candidates'][0]['gate_blockers'] = 'reward_to_risk,reviewed_business_case_not_supported'
        built = case.build()['decisions'][0]
        self.assertEqual(built['decision'], 'NO_ACTION'); self.assertEqual(built['blockers'], [])
        self.assertIn('reviewed_business_case_not_supported', built['reasons'])
        built['ticker'] = 'SYN'  # Synthetic identity only; builder economics stay intact.
        path = self.root / '04_data/equity_research/valuation_scenarios.local.json'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text('{"synthetic_current_valuation":"adverse"}')
        reason_only = copy.deepcopy(current); reason_only['capital_decision']['decisions'] = [built]
        reason_only['workflow_integrity']['input_hashes'][str(path.relative_to(self.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.capital(reason_only)
        self.assertTrue(delivery.delivery_eligibility(reason_only, root=self.root, current=NOW,
            rows=rows, mode='intraday_alert')['eligible'])

    def test_corrupt_followthrough_archive_and_unknown_claim_stay_fenced(self):
        self.positive_draft(); sent = self.append_delivery(); self.assertEqual(self.recover()['outcome'], 'passed')
        current = json.loads((self.root / repair.ARTIFACTS[0]).read_text())
        rows = list(csv.DictReader(self.ledger.read_text().splitlines()))
        forged = copy.deepcopy(current); forged['delivery_followthrough']['actions'][0]['quantity'] = 999
        self.assertFalse(delivery.delivery_eligibility(forged, root=self.root, current=NOW,
            rows=rows, mode='intraday_alert')['eligible'])
        path = self.root / delivery.ARCHIVE_REL / (sent['brief_html_sha256'] + '.html')
        original = path.read_bytes(); path.write_bytes(original+b'corrupt')
        self.assertFalse(delivery.delivery_eligibility(current, root=self.root, current=NOW,
            rows=rows, mode='intraday_alert')['eligible']); path.write_bytes(original)
        unknown = {**sent, 'timestamp': NOW.isoformat(), 'status': 'delivery_unknown'}
        self.assertFalse(delivery.delivery_eligibility(current, root=self.root, current=NOW,
            rows=[*rows, unknown], mode='intraday_alert')['eligible'])

    def test_valid_nonconditional_or_mismatched_retention_does_not_gain_an_exemption(self):
        self.positive_draft(); self.append_delivery(); self.assertEqual(self.recover()['outcome'], 'passed')
        current = json.loads((self.root / repair.ARTIFACTS[0]).read_text())
        rows = list(csv.DictReader(self.ledger.read_text().splitlines()))
        baseline = delivery.latest_receipt_baseline(rows, root=self.root, current=NOW)
        prior = baseline['projection']['actions'][0]
        changed = copy.deepcopy(current)
        changed['delivery_followthrough']['status'] = 'multiple_deliveries_require_reconciliation'
        with patch('delivery_followthrough.validate_followthrough'):
            self.assertFalse(delivery._retained_instruction_only(changed, 'SYN', prior, baseline, root=self.root, current=NOW))
            changed = copy.deepcopy(current); changed['delivery_followthrough']['actions'][0]['side'] = 'sell'
            self.assertFalse(delivery._retained_instruction_only(changed, 'SYN', prior, baseline, root=self.root, current=NOW))


class PipelineRecoveryBudgetTests(unittest.TestCase):
    def invoke(self, summary='email_sent=true message_count=1', *, moment=NOW, seconds=(0, 100, 100, 180), slot=None):
        config = {'notifications': {'mandatory_daily_briefs': True, 'intraday_alerts_enabled': True,
            'delivery_assessment_effective_from': '2026-10-22', 'delivery_windows_et': [
                {'id': 'morning', 'start': '09:30', 'end': '10:30', 'refresh_not_before': '08:00'},
                {'id': 'afternoon', 'start': '14:30', 'end': '15:05', 'refresh_not_before': '13:30'}]}}
        with ExitStack() as stack:
            for name, value in [('load_active_state', {}), ('load_inhibit', {'active': False}),
                    ('load_active_config', config), ('now_et', moment), ('refresh_readiness', (True, 'daily_refresh_ready'))]:
                stack.enter_context(patch.object(pipeline, name, return_value=value))
            stack.enter_context(patch.object(pipeline, 'ExclusiveFileLock'))
            stack.enter_context(patch.object(pipeline, 'log_daily_run'))
            clear = stack.enter_context(patch.object(pipeline, 'clear_automation_alert'))
            stack.enter_context(patch('daily_common.publish_automation_alert'))
            stack.enter_context(patch.object(pipeline.time, 'monotonic', side_effect=seconds))
            recover = stack.enter_context(patch.object(repair, 'recover_locked',
                return_value={'outcome': 'deferred', 'publication_pending': True}))
            sender = stack.enter_context(patch.object(pipeline, 'run_command',
                return_value=subprocess.CompletedProcess([], 0, stdout=summary)))
            output = io.StringIO()
            with redirect_stdout(output): result = pipeline.execute(True, slot, 'scheduled_brief' if slot else 'intraday_alert')
            return result, recover, sender, clear, output.getvalue()

    def test_pre_and_post_share_one180_second_budget_and_keep_smtp_success_if_pending(self):
        result, recover, sender, clear, output = self.invoke()
        self.assertEqual(result, 0); self.assertEqual(sender.call_count, 1)
        self.assertEqual([call.kwargs['maximum_seconds'] for call in recover.call_args_list], [180, 80])
        self.assertIn('email_sent=true', output); self.assertIn('post_delivery_publication_pending=true', output)
        clear.assert_not_called()

    def test_unknown_or_skip_stdout_never_runs_post_send_hook(self):
        for summary in ['email_sent=unknown reason=delivery_unknown', 'email_sent=false reason=existing_completed_purpose']:
            result, recover, sender, _, _ = self.invoke(summary, seconds=(0, 0))
            self.assertEqual(recover.call_count, 1); self.assertEqual(sender.call_count, 1)

    def test_pre_recovery_reserves_sender_runway_before_the1100_short_window(self):
        _, recover, _, _, _ = self.invoke('email_sent=false reason=existing_completed_purpose',
            moment=NOW.replace(hour=10, minute=55), seconds=(0, 0))
        self.assertEqual(recover.call_args.kwargs['maximum_seconds'], 0)

    def test_near_mandatory_window_close_does_not_spend_sender_attempt_on_recovery(self):
        result, recover, sender, _, _ = self.invoke('email_sent=false reason=existing_completed_purpose',
            moment=NOW.replace(hour=10, minute=29), seconds=(0, 0), slot='morning')
        self.assertEqual(result, 0); self.assertEqual(sender.call_count, 1)
        self.assertEqual(recover.call_args.kwargs['maximum_seconds'], 0)


if __name__ == '__main__': unittest.main()
