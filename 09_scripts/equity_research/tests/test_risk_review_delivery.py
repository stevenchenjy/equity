"""Independent risk notices use actual local evidence and mocked SMTP only."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from _support import SCRIPT_DIR  # noqa: F401
import delivery_assessments as delivery
import held_position_risk as held
import risk_review_alerts as risk
import run_daily_decision_pipeline as pipeline
import run_daily_scheduler as scheduler
import send_daily_email as sender
from delivery_schedule import risk_review_alert_window
from email_brief import render_email
from test_email_brief import decision_fixture
from test_intraday_prices import seed_admitted_history
from test_risk_review_alerts import NOW, seed_risk_fixture, write_csv, write_json


def risk_config():
    return {'notifications': {'mandatory_daily_briefs': True, 'intraday_alerts_enabled': True,
        'delivery_assessment_effective_from': '2026-10-22',
        'short_assessment_slots_et': ['09:30', '11:00', '12:30', '14:00', '15:30'],
        'short_assessment_budget_minutes': 10,
        'risk_review_alerts': {'schema_version': 'owner_held_risk_review_alert_permission_v1',
            'enabled': True, 'effective_from': '2026-11-01', 'delivery_grace_minutes': 15,
            'allowed_triggers': ['approved_risk_condition_crossed', 'held_review_or_protection_unavailable']},
        'delivery_windows_et': [
            {'id': 'morning', 'start': '09:30', 'end': '10:30', 'refresh_not_before': '08:00'},
            {'id': 'afternoon', 'start': '14:30', 'end': '15:05', 'refresh_not_before': '13:30'}]}}


class RiskReviewDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = NOW.replace(hour=11)
        self.artifact = seed_risk_fixture(self.root, current=self.now)
        self.config = risk_config()
        write_json(self.root, delivery.CONFIG_REL, self.config)
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(sender, 'ROOT', self.root))
        for name, relative in {
            'DAILY_DELIVERY_LEDGER_PATH': '07_automation/email_delivery/daily_delivery_ledger.csv',
            'DAILY_DELIVERY_LOCK_PATH': '07_automation/email_delivery/delivery.lock',
            'DAILY_DECISION_JSON_PATH': str(delivery.DECISION_REL),
            'DAILY_BRIEF_TEXT_PATH': '07_automation/email_briefs/daily_email_brief.txt',
            'DAILY_BRIEF_HTML_PATH': '07_automation/email_briefs/daily_email_brief.html',
        }.items():
            self.stack.enter_context(patch.object(sender, name, self.root / relative))
        self.stack.enter_context(patch.object(sender, 'now_et', side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(sender, 'iso_now', side_effect=lambda: self.now.isoformat()))
        self.stack.enter_context(patch.object(sender, 'load_active_config', side_effect=lambda: self.config))
        self.stack.enter_context(patch.object(sender, 'delivery_guard', return_value=(True, 'delivery_enabled', {}, {})))
        self.stack.enter_context(patch.object(sender, 'log_daily_run'))
        self.credentials = self.stack.enter_context(patch.object(sender, 'load_config', return_value={
            'smtp_username': 'sender@example.com', 'smtp_app_password': 'mock-password',
            'recipient_email': 'existing-recipient@example.com'}))
        self.canonical = self.stack.enter_context(patch.object(sender, 'validate_decision',
            side_effect=AssertionError('risk notices must not require the full canonical publication')))
        self.smtp = MagicMock()

    def send(self):
        return sender.send_once(self.smtp, delivery_mode='risk_review_alert')

    def rows(self):
        return sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)

    def change_price(self, price):
        rows = held._csv(self.root, held.MARKET); rows[0]['last_price'] = str(price)
        rows[0]['data_timestamp'] = self.now.isoformat()
        write_csv(self.root, held.MARKET, rows); seed_admitted_history(self.root)

    def archive(self, decision, *, stamp=None, reason='', status='sent', bodies=None):
        if bodies is None:
            if decision.get('schema_version') == delivery.RISK_DELIVERY_SCHEMA:
                _, plain, document = delivery.render_risk_review_alert(decision)
            elif decision.get('schema_version') == 'equity_mandatory_status_brief_v1':
                _, plain, document = delivery.render_failure_brief(decision)
            else:
                # The same actual card renderer used by the canonical email;
                # capital research is deliberately outside this coverage fixture.
                from email_brief import _render_cards
                _, plain, document = _render_cards('[Equity] Research', held.cards(decision),
                    title='Current holding review', stamp=decision['generated_at'], footer='Human review only.')
        else:
            plain, document = bodies
        row = {'timestamp': (stamp or self.now).isoformat(), 'cycle_date': decision['cycle_date'],
               'status': status, 'reason': reason}
        for key, suffix, raw in [('decision_sha256', '.json', json.dumps(decision).encode()),
                ('brief_text_sha256', '.txt', plain.encode()), ('brief_html_sha256', '.html', document.encode())]:
            digest = hashlib.sha256(raw).hexdigest()
            path = self.root / delivery.ARCHIVE_REL / (digest + suffix)
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw); row[key] = digest
        return row

    def ordinary(self):
        d = decision_fixture(); d.update(cycle_date=self.now.date().isoformat(), generated_at=self.now.isoformat())
        d['intraday_portfolio_risk'] = risk._intraday(self.root, self.now)
        d['held_position_risk'] = held.build({'market_gate': risk._market_gate(self.root, self.now),
            'intraday_portfolio_risk': d['intraday_portfolio_risk']}, root=self.root, current=self.now)
        return d

    def intraday_price(self, price):
        """Retain a real validated current observation using a mock public response."""
        import intraday_prices as feed
        import intraday_portfolio_risk as monitor
        import intraday_assessment as store
        from account_access import capture_version
        for relative in monitor.INPUTS[:2]:
            write_json(self.root, relative, json.loads((SCRIPT_DIR.parents[1] / relative).read_text()))
        write_csv(self.root, monitor.INPUTS[2], [{'ticker': 'AAA', 'sector': 'Technology', 'is_benchmark': 'no'}])
        config = json.loads((self.root / delivery.CONFIG_REL).read_text())
        config['notifications'].update(self.config['notifications'])
        write_json(self.root, delivery.CONFIG_REL, config)
        baseline = float(held._csv(self.root, held.MARKET)[0]['last_price'])
        def get(_url):
            return json.dumps({'status': {'rCode': 200, 'bCodeMessage': None}, 'data': {
                'symbol': 'AAA', 'assetClass': 'STOCKS', 'marketStatus': 'Open', 'primaryData': {
                    'lastSalePrice': f'${price:.2f}', 'netChange': f'{price - baseline:+.2f}',
                    'percentageChange': f'{(price / baseline - 1) * 100:+.2f}%', 'isRealTime': True, 'currency': 'USD',
                    'lastTradeTimestamp': self.now.strftime('%b %d, %Y %I:%M:%S %p ET')}}}).encode()
        client = feed.NasdaqIntradayClient(self.root, get=get, sleep=lambda _: None, now=lambda: self.now)
        snapshot = feed.collect(self.root, {'AAA': 'stocks'}, account_version=capture_version(self.root),
            claim_id='risk-delivery-test', current=self.now, client=client)
        assessment = monitor.assess(self.root, snapshot, self.now)
        self.assertEqual(assessment['status'], 'current', assessment)
        source = store._retain(self.root, assessment)
        write_json(self.root, store.CURRENT, {'schema_version': store.SCHEMA, 'generated_at': self.now.isoformat(),
            'status': assessment['status'], 'source': source, 'assessment': assessment})

    def eligible(self, rows, artifact=None):
        return delivery.delivery_eligibility(artifact or risk.build(self.root, self.now), root=self.root,
            current=self.now, rows=rows, mode='risk_review_alert')

    def test_independent_notice_claim_archive_and_existing_recipient_without_canonical_refresh(self):
        write_json(self.root, delivery.REFRESH_REL, {'outcome': 'failed', 'hard_failures': ['company_research']})
        def at_send(message):
            self.assertEqual([r['status'] for r in self.rows()], ['send_claimed'])
            self.assertEqual(message['To'], 'existing-recipient@example.com')
            body = message.get_body(preferencelist=('plain',)).get_content()
            self.assertIn('AAA', body); self.assertIn('version 1', body)
            self.assertIn('company invalidation $95.00', body)
            self.assertIn('Observation time:', body)
            self.assertNotIn('BUY LIMIT', body); self.assertNotIn('SELL STOP', body)
        self.smtp.return_value.__enter__.return_value.send_message.side_effect = at_send
        self.assertEqual(self.send(), 0)
        self.canonical.assert_not_called()
        self.assertEqual([row['status'] for row in self.rows()], ['send_claimed', 'sent'])
        sent = self.rows()[-1]
        self.assertIn('publication_status=risk_review', sent['reason'])
        self.assertEqual(delivery._archived_receipt_baseline(sent, root=self.root)['status'], 'risk_only')

    def test_same_check_one_notice_even_if_a_new_position_quantity_changes(self):
        self.assertEqual(self.send(), 0)
        write_csv(self.root, held.POSITIONS, [{'ticker': 'AAA', 'shares_optional': '2', 'entry_price': '100'}])
        self.now += timedelta(minutes=1)
        self.credentials.reset_mock(); self.assertEqual(self.send(), 0)
        self.credentials.assert_not_called()
        self.assertEqual(self.smtp.return_value.__enter__.return_value.send_message.call_count, 1)

    def test_two_unavailable_holdings_share_one_combined_notice(self):
        (self.root / risk.PLAN).unlink()
        write_csv(self.root, held.POSITIONS, [
            {'ticker': 'AAA', 'shares_optional': '1', 'entry_price': '100'},
            {'ticker': 'BBB', 'shares_optional': '2', 'entry_price': '50'}])
        self.assertEqual(self.send(), 0)
        message = self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        body = message.get_body(preferencelist=('plain',)).get_content()
        self.assertIn('AAA — risk review requested', body)
        self.assertIn('BBB — risk review requested', body)
        self.assertEqual(self.smtp.return_value.__enter__.return_value.send_message.call_count, 1)
        self.assertEqual(len(self.rows()), 2)

    def test_unavailable_notice_survives_actual_advancing_validation_clock(self):
        (self.root / risk.PLAN).unlink()
        def advance():
            self.now += timedelta(seconds=1)
            return self.now
        with patch.object(sender, 'now_et', side_effect=advance):
            self.assertEqual(self.send(), 0)
        self.assertEqual([row['status'] for row in self.rows()], ['send_claimed', 'sent'])

    def test_partial_stop_scope_is_visible_without_a_replacement_order(self):
        from daily_common import canonical_sha256
        write_csv(self.root, held.POSITIONS, [{'ticker': 'AAA', 'shares_optional': '4', 'entry_price': '100'}])
        ledger = json.loads((self.root / risk.PLAN).read_text())
        plan = ledger['records'][0]
        plan.update(expected_shares=4, action='protect_review', proposed_change_shares=1,
            order_draft={'side': 'sell', 'type': 'STOP', 'stop_price': 95, 'quantity': 1,
                         'time_in_force': 'DAY', 'session_date': self.now.date().isoformat(),
                         'starts_at': self.now.replace(hour=9, minute=30).isoformat()})
        plan['record_hash'] = canonical_sha256({k: v for k, v in plan.items() if k != 'record_hash'})
        write_json(self.root, risk.PLAN, ledger)
        self.assertEqual(self.send(), 0)
        message = self.smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        for kind in ('plain', 'html'):
            text = message.get_body(preferencelist=(kind,)).get_content()
            self.assertIn('stop reference for 1 of 4 recorded shares', text)
            self.assertNotIn('SELL STOP', text)

    def test_same_crossing_price_and_collection_churn_stay_quiet_in_next_check(self):
        self.assertEqual(self.send(), 0)
        self.change_price(89); self.now = self.now.replace(hour=12, minute=30)
        self.credentials.reset_mock(); self.assertEqual(self.send(), 0)
        self.credentials.assert_not_called()
        self.assertEqual(len(self.rows()), 2)

    def test_unavailable_same_plan_position_episode_stays_quiet_across_days(self):
        (self.root / risk.PLAN).unlink()
        self.assertEqual(self.send(), 0)
        self.now = self.now.replace(day=9, hour=11)
        self.credentials.reset_mock(); self.assertEqual(self.send(), 0)
        self.credentials.assert_not_called()
        self.assertEqual(len(self.rows()), 2)

    def test_ordinary_risk_cards_cover_but_status_only_does_not(self):
        normal = self.archive(self.ordinary())
        self.assertFalse(self.eligible([normal])['eligible'])
        status = delivery.build_failure_brief(self.root, self.now, 'morning', 'company_research_failed')
        receipt = self.archive(status)
        self.assertTrue(self.eligible([receipt])['eligible'])

    def test_intraday_existing_alert_cards_cover_risk(self):
        normal = self.ordinary()
        normal['assessment_delivery_policy'] = delivery.delivery_policy_context(self.root)
        normal['capital_decision'] = {'decisions': []}
        normal['analyst_priority_review'] = {'status': 'current', 'entries': [
            {'ticker': 'AAA', 'reason': 'Current research review.', 'next_step': 'Complete the company review.'}]}
        evaluation = {'eligible': True, 'mode': 'intraday_alert', 'meaning_key': delivery.advice_meaning_key(normal),
            'purpose_key': 'alert:2026-11-06:' + 'c' * 64 + ':' + 'a' * 64, 'baseline_receipt_sha256': 'a' * 64,
            'action_changed': False, 'priority_changed': True, 'changed_action_tickers': [], 'removed_action_tickers': []}
        normal['delivery_assessment'] = delivery.delivery_envelope(normal, evaluation,
            canonical_decision_sha256='b' * 64, mode='intraday_alert')
        receipt = self.archive(normal, bodies=delivery.render_intraday_alert(normal)[1:])
        self.assertFalse(self.eligible([receipt])['eligible'])

    def test_hidden_or_corrupt_risk_cards_fail_closed(self):
        decision = self.ordinary()
        hidden = self.archive(decision, bodies=('No risk cards', '<p>No risk cards</p>'))
        self.assertEqual(self.eligible([hidden])['reason'], 'risk_prior_card_not_displayed')
        receipt = self.archive(decision)
        (self.root / delivery.ARCHIVE_REL / (receipt['brief_html_sha256'] + '.html')).write_text('corrupt')
        self.assertEqual(self.eligible([receipt])['reason'], 'risk_delivery_receipt_archive_changed')

    def test_verified_recovery_allows_recross_but_status_or_missing_evidence_does_not(self):
        self.change_price(100); self.intraday_price(90)
        active = self.archive(self.ordinary())
        self.now += timedelta(minutes=1); self.intraday_price(100)
        recovered = self.archive(self.ordinary())
        self.now = self.now.replace(hour=12, minute=30); self.intraday_price(90)
        self.assertTrue(self.eligible([active, recovered])['eligible'])
        status = delivery.build_failure_brief(self.root, self.now, 'morning', 'company_research_failed')
        self.assertFalse(self.eligible([active, self.archive(status)])['eligible'])

    def test_later_delivery_of_older_healthy_close_cannot_recover_newer_crossing(self):
        self.change_price(100)
        older_healthy = self.ordinary()
        self.now += timedelta(minutes=1); self.intraday_price(90)
        active = self.archive(self.ordinary())
        self.now += timedelta(minutes=1)
        stale_recovery = self.archive(older_healthy)
        self.now = self.now.replace(hour=12, minute=30); self.intraday_price(90)
        self.assertFalse(self.eligible([active, stale_recovery])['eligible'])

    def test_older_crossing_cannot_follow_a_newer_verified_recovery(self):
        self.intraday_price(100)
        recovered = self.archive(self.ordinary())
        (self.root / risk.INTRADAY).unlink()
        self.now = self.now.replace(hour=12, minute=30)
        self.assertFalse(self.eligible([recovered])['eligible'])

    def test_unknown_and_unmatched_claim_before_permission_cannot_be_bypassed(self):
        self.config['notifications']['risk_review_alerts']['effective_from'] = self.now.date().isoformat()
        write_json(self.root, delivery.CONFIG_REL, self.config)
        for status in ('delivery_unknown', 'owner_review_delivery_unknown', 'send_claimed'):
            with self.subTest(status=status):
                row = {'timestamp': (self.now - timedelta(days=1)).isoformat(),
                       'status': status, 'reason': '', 'cycle_date': '2026-11-05'}
                self.assertFalse(self.eligible([row])['eligible'])
                self.assertIn('existing_', self.eligible([row])['reason'])

    def test_actual_unknown_smtp_blocks_risk_and_action_purposes(self):
        self.smtp.return_value.__enter__.return_value.send_message.side_effect = OSError('mock SMTP uncertainty')
        self.assertEqual(self.send(), 1)
        self.credentials.reset_mock(); self.smtp.reset_mock()
        self.now = self.now.replace(hour=12, minute=30)
        self.assertEqual(self.send(), 0)
        self.credentials.assert_not_called(); self.smtp.assert_not_called()
        with patch.object(sender, 'validate_decision', return_value=self.ordinary()):
            self.assertEqual(sender.send_once(self.smtp, delivery_mode='intraday_alert'), 0)
        self.credentials.assert_not_called(); self.smtp.assert_not_called()

    def test_old_unscoped_unknown_and_claim_allow_later_verified_substantive_baseline(self):
        prior = self.ordinary()
        prior['capital_decision'] = {'decisions': []}
        prior['analyst_priority_review'] = {'status': 'current', 'entries': []}
        receipt = self.archive(prior)
        self.assertEqual(delivery._archived_receipt_baseline(receipt, root=self.root)['status'], 'verified')
        write_csv(self.root, held.POSITIONS, [{'ticker': 'AAA', 'shares_optional': '2', 'entry_price': '100'}])
        for status in ('delivery_unknown', 'send_claimed'):
            row = {'timestamp': (self.now - timedelta(days=2)).isoformat(), 'status': status,
                   'reason': 'legacy_transport_result', 'cycle_date': '2026-11-04'}
            self.assertTrue(self.eligible([row, receipt])['eligible'])

    def test_status_only_earlier_or_corrupt_baseline_cannot_supersede_legacy_unknown(self):
        row = {'timestamp': (self.now - timedelta(days=1)).isoformat(), 'status': 'delivery_unknown',
               'reason': 'smtp_exception_after_claim', 'cycle_date': '2026-11-05'}
        status = self.archive(delivery.build_failure_brief(self.root, self.now, 'morning', 'company_research_failed'))
        prior = self.ordinary()
        prior['capital_decision'] = {'decisions': []}
        prior['analyst_priority_review'] = {'status': 'current', 'entries': []}
        earlier = self.archive(prior, stamp=self.now - timedelta(days=2))
        for receipts in ([row, status], [earlier, row, status]):
            self.assertEqual(self.eligible(receipts)['reason'], 'existing_delivery_unknown')
        valid = self.archive(prior)
        (self.root / delivery.ARCHIVE_REL / (valid['brief_html_sha256'] + '.html')).write_text('corrupt')
        self.assertEqual(self.eligible([row, valid])['reason'], 'existing_delivery_unknown')

    def test_current_cycle_unknown_is_not_superseded_by_later_verified_baseline(self):
        prior = self.ordinary()
        prior['capital_decision'] = {'decisions': []}
        prior['analyst_priority_review'] = {'status': 'current', 'entries': []}
        receipt = self.archive(prior)
        row = {'timestamp': (self.now - timedelta(minutes=1)).isoformat(), 'status': 'delivery_unknown',
               'reason': 'smtp_exception_after_claim', 'cycle_date': self.now.date().isoformat()}
        self.assertEqual(self.eligible([row, receipt])['reason'], 'existing_delivery_unknown')

    def test_risk_uncertainty_survives_next_day_and_later_substantive_or_status_send(self):
        observation = risk.build(self.root, self.now)
        wrapper = delivery.risk_review_envelope(observation, self.eligible([]))
        for status in ('delivery_unknown', 'send_claimed'):
            unknown = self.archive(wrapper, status=status,
                reason='delivery_mode=risk_review_alert;delivery_purpose_v1=risk-review:2026-11-06:11:00')
            self.now = self.now.replace(day=9)
            prior = self.ordinary()
            prior['capital_decision'] = {'decisions': []}
            prior['analyst_priority_review'] = {'status': 'current', 'entries': []}
            receipt = self.archive(prior)
            status_receipt = self.archive(delivery.build_failure_brief(self.root, self.now, 'morning', 'company_research_failed'))
            for receipts in ([unknown, receipt], [unknown, status_receipt]):
                self.assertIn(self.eligible(receipts)['reason'], ('existing_delivery_unknown', 'existing_send_claimed'))
            unknown['reason'] = ''
            self.assertIn(self.eligible([unknown, receipt])['reason'], ('existing_delivery_unknown', 'existing_send_claimed'))
            self.now = self.now.replace(day=6)

    def test_malformed_naive_or_future_known_receipt_clocks_fail_closed(self):
        from delivery_continuity import RECEIPTS
        self.config['notifications']['risk_review_alerts']['effective_from'] = self.now.date().isoformat()
        write_json(self.root, delivery.CONFIG_REL, self.config)
        for status in sorted(RECEIPTS):
            for stamp in ('corrupt', '2026-11-05T11:00:00',
                          (self.now + timedelta(days=1)).isoformat(), None):
                with self.subTest(status=status, stamp=stamp):
                    row = {'timestamp': stamp, 'status': status,
                           'reason': '', 'cycle_date': '2026-11-05'}
                    result = self.eligible([row])
                    self.assertFalse(result['eligible'])
                    self.assertEqual(result['reason'], 'risk_delivery_receipt_clock_invalid')

    def test_future_permission_closed_windows_holiday_and_early_close(self):
        config = self.config['notifications']
        self.assertIsNotNone(risk_review_alert_window(config, self.now))
        for stamp in (self.now.replace(hour=10), self.now.replace(hour=11, minute=15),
                      self.now.replace(month=11, day=27, hour=14), self.now.replace(month=11, day=26, hour=11)):
            self.assertIsNone(risk_review_alert_window(config, stamp))
        self.assertIsNotNone(risk_review_alert_window(config, self.now.replace(month=11, day=27, hour=12, minute=30)))
        config['risk_review_alerts']['effective_from'] = '2026-11-09'
        self.assertEqual(self.send(), 2)
        self.credentials.assert_not_called(); self.smtp.assert_not_called()

    def test_final_clock_and_source_change_after_credentials_never_claim_or_send(self):
        for change in ('clock', 'source'):
            with self.subTest(change=change):
                def mutate():
                    if change == 'clock':
                        self.now = self.now.replace(minute=15)
                    else:
                        write_csv(self.root, held.POSITIONS, [{'ticker': 'AAA', 'shares_optional': '2', 'entry_price': '100'}])
                    return self.credentials.return_value
                self.now = NOW.replace(hour=11)
                self.credentials.side_effect = mutate
                self.assertEqual(self.send(), 2)
                self.smtp.assert_not_called(); self.assertEqual(self.rows(), [])

    def test_risk_pipeline_never_requires_full_refresh_or_starts_research(self):
        with ExitStack() as stack:
            for name, value in [('ROOT', self.root), ('DAILY_PIPELINE_LOCK_PATH', self.root / 'pipeline.lock')]:
                stack.enter_context(patch.object(pipeline, name, value))
            stack.enter_context(patch.object(pipeline, 'load_active_state', return_value={}))
            stack.enter_context(patch.object(pipeline, 'load_inhibit', return_value={'active': False}))
            stack.enter_context(patch.object(pipeline, 'load_active_config', return_value=self.config))
            stack.enter_context(patch.object(pipeline, 'now_et', side_effect=lambda: self.now))
            stack.enter_context(patch.object(pipeline, 'log_daily_run'))
            refresh = stack.enter_context(patch.object(pipeline, 'refresh_readiness', side_effect=AssertionError('full refresh forbidden')))
            command = stack.enter_context(patch.object(pipeline, 'run_command', return_value=
                subprocess.CompletedProcess([], 0, stdout='email_sent=false reason=already_covered')))
            self.assertEqual(pipeline.execute(True, delivery_mode='risk_review_alert'), 0)
            refresh.assert_not_called()
            self.assertIn('risk_review_alert', command.call_args.args[0])

    def test_scheduler_checks_risk_after_status_only_and_stops_after_unknown(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown), ExitStack() as stack:
                self.now = NOW.replace(hour=9, minute=30)
                state = {'dates': {}}
                for name, value in [('read_json', state), ('load_active_config', self.config),
                                    ('cycle_date', self.now.date().isoformat()), ('now_et', self.now),
                                    ('iso_now', self.now.isoformat())]:
                    stack.enter_context(patch.object(scheduler, name, return_value=value))
                for name in ('_save_state', 'publish_automation_alert', 'clear_automation_alert'):
                    stack.enter_context(patch.object(scheduler, name))
                first = 'email_sent=unknown reason=smtp_exception_after_claim' if unknown else 'email_sent=true publication_status=status_only'
                run = stack.enter_context(patch.object(scheduler.subprocess, 'run', side_effect=[
                    subprocess.CompletedProcess([], 1 if unknown else 0, stdout=first),
                    subprocess.CompletedProcess([], 0, stdout='email_sent=false reason=already_covered')]))
                scheduler.assessment_scheduler(self.now, self.config['notifications'])
                self.assertEqual(run.call_count, 1 if unknown else 2)
                if not unknown:
                    self.assertIn('risk_review_alert', run.call_args_list[-1].args[0])


if __name__ == '__main__':
    unittest.main()
