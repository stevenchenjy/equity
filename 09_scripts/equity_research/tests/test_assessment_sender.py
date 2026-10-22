"""Assessment-purpose routing uses temporary stores and mocked SMTP only."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import delivery_assessments as contract
import run_daily_decision_pipeline as pipeline
import run_daily_scheduler as scheduler
import send_daily_email as sender
from delivery_schedule import intraday_alert_window_open
from test_delivery_windows import CONFIG
from test_email_brief import decision_fixture
from test_owner_review_delivery import delivery_fixture, save_decision

ET = ZoneInfo("America/New_York")


def at(hour, minute=0):
    return datetime(2026, 9, 1, hour, minute, tzinfo=ET)


def adopted_config():
    value = copy.deepcopy(sender.load_active_config())
    value["notifications"].pop("regular_delivery_mode", None)
    value["notifications"].update(mandatory_daily_briefs=True, intraday_alerts_enabled=True,
        delivery_assessment_effective_from="2026-09-01")
    return value


@contextmanager
def adopted_sender():
    config = adopted_config()
    clock = {"now": at(9, 30)}
    with delivery_fixture() as (credentials, smtp), ExitStack() as stack:
        root = sender.DAILY_DELIVERY_LEDGER_PATH.parent
        ledger = root / contract.ARCHIVE_REL.parent / "daily_delivery_ledger.csv"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        stack.enter_context(patch.object(sender, "DAILY_DELIVERY_LEDGER_PATH", ledger))
        path = root / contract.CONFIG_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config))
        stack.enter_context(patch.object(sender, "ROOT", root))
        stack.enter_context(patch.object(sender, "load_active_config", return_value=config))
        stack.enter_context(patch.object(sender, "now_et", side_effect=lambda: clock["now"]))
        stack.enter_context(patch.object(sender, "iso_now", side_effect=lambda: clock["now"].isoformat()))
        # These tests isolate sender routing. The contract's source-bound
        # publication/priority validators have their own independent tests.
        stack.enter_context(patch.object(contract, "validate_current_publication"))
        stack.enter_context(patch("delivery_followthrough.validate_followthrough"))
        stack.enter_context(redirect_stdout(io.StringIO()))
        decision = decision_fixture()
        decision["generated_at"] = at(9, 20).isoformat()
        decision["assessment_delivery_policy"] = contract.delivery_policy_context(root)
        decision["analyst_priority_review"] = contract.priority_review_context(root, clock["now"])
        save_decision(decision)
        yield root, clock, decision, credentials, smtp


class AssessmentSenderTests(unittest.TestCase):
    def test_both_mandatory_briefs_send_once_even_when_the_canonical_policy_says_unchanged(self):
        with adopted_sender() as (_, clock, decision, credentials, smtp):
            self.assertFalse(decision["send_recommended"])
            self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning"), 0)
            credentials.reset_mock()
            self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning"), 0)
            credentials.assert_not_called()
            clock["now"] = at(14, 30)
            self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="afternoon"), 0)
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 2)
            rows = sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)
            self.assertEqual(len(rows), 4)
            self.assertIn("delivery_purpose_v1=brief:2026-09-01:morning", rows[0]["reason"])
            self.assertIn("delivery_purpose_v1=brief:2026-09-01:afternoon", rows[-1]["reason"])
            self.assertFalse(json.loads(sender.DAILY_DECISION_JSON_PATH.read_bytes())["send_recommended"])

    def test_market_alerts_have_distinct_durable_purposes_and_unchanged_advice_stays_quiet(self):
        with adopted_sender() as (root, clock, decision, credentials, smtp):
            self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning"), 0)
            original_hash = sender.sha256_file(sender.DAILY_DECISION_JSON_PATH)
            for hour, minute, ticker in [(11, 0, "META"), (11, 15, "AMD"), (11, 30, "META")]:
                clock["now"] = at(hour, minute)
                decision["analyst_priority_review"] = {"status": "current", "change_basis": "source_bound_event_change",
                    "entries": [{"ticker": ticker, "reason": "Changed source-bound research conclusion.",
                                 "next_step": "Complete the company-specific valuation before considering entry."}]}
                save_decision(decision)
                self.assertEqual(sender.send_once(smtp, delivery_mode="intraday_alert"), 0)
            self.assertEqual(smtp.return_value.__enter__.return_value.send_message.call_count, 4)
            credentials.reset_mock()
            self.assertEqual(sender.send_once(smtp, delivery_mode="intraday_alert"), 0)
            credentials.assert_not_called()
            rows = sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)
            sent = [row for row in rows if row["status"] == "sent"]
            purposes = [next(part for part in row["reason"].split(";") if part.startswith("delivery_purpose_v1=")) for row in sent]
            self.assertEqual(len(set(purposes)), 4)
            archive = root / contract.ARCHIVE_REL
            self.assertTrue((archive / (original_hash + ".json")).is_file())
            for receipt in sent[1:]:
                archived = json.loads((archive / (receipt["decision_sha256"] + ".json")).read_bytes())
                envelope = contract.validate_envelope(archived)
                self.assertEqual(envelope["mode"], "intraday_alert")
                self.assertTrue((archive / (envelope["canonical_decision_sha256"] + ".json")).is_file())
                text = (archive / (receipt["brief_text_sha256"] + ".txt")).read_text()
                self.assertIn("No new or repeated trading instruction", text)
                self.assertNotIn("BUY LIMIT", text)

    def test_first_alert_is_quiet_and_unknown_smtp_blocks_every_new_purpose(self):
        with adopted_sender() as (_, clock, _, credentials, smtp):
            clock["now"] = at(11)
            self.assertEqual(sender.send_once(smtp, delivery_mode="intraday_alert"), 0)
            credentials.assert_not_called()
            smtp.assert_not_called()
            clock["now"] = at(9, 30)
            smtp.return_value.__enter__.return_value.send_message.side_effect = OSError("mock uncertain delivery")
            self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning"), 1)
            credentials.reset_mock()
            smtp.reset_mock()
            clock["now"] = at(11)
            self.assertEqual(sender.send_once(smtp, delivery_mode="intraday_alert"), 0)
            credentials.assert_not_called()
            smtp.assert_not_called()
            self.assertEqual(len(sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)), 2)

    def test_alert_clocks_include_early_close_and_final_gate_rechecks(self):
        for stamp in [at(9, 29), at(16), datetime(2026, 11, 27, 13, tzinfo=ET),
                      datetime(2026, 9, 7, 11, tzinfo=ET)]:
            self.assertFalse(intraday_alert_window_open(stamp))
        self.assertTrue(intraday_alert_window_open(at(11)))
        with adopted_sender() as (_, clock, _, credentials, smtp):
            clock["now"] = at(16)
            self.assertEqual(sender.send_once(smtp, delivery_mode="intraday_alert"), 2)
            credentials.assert_not_called()
            smtp.assert_not_called()
            with self.assertRaisesRegex(ValueError, "routine_purpose"):
                sender.send_once(smtp, delivery_mode="intraday_alert", owner_review_request_id="owner-request")

    def test_market_close_crossed_after_credentials_never_claims_or_sends_an_alert(self):
        with adopted_sender() as (_, clock, decision, credentials, smtp):
            self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning"), 0)
            clock["now"] = at(15, 59)
            decision["analyst_priority_review"] = {"status": "current", "change_basis": "source_bound_event_change",
                "entries": [{"ticker": "META", "reason": "New source-bound case.", "next_step": "Complete valuation."}]}
            save_decision(decision)
            def cross_close():
                clock["now"] = at(16)
                return credentials.return_value
            credentials.side_effect = cross_close
            smtp.reset_mock()
            self.assertEqual(sender.send_once(smtp, delivery_mode="intraday_alert"), 2)
            smtp.assert_not_called()
            self.assertEqual(len(sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)), 2)

    def test_future_contract_does_not_create_a_catchup_send(self):
        with adopted_sender() as (root, clock, _, credentials, smtp):
            path = root / contract.CONFIG_REL
            config = json.loads(path.read_bytes())
            config["notifications"]["delivery_assessment_effective_from"] = "2026-09-02"
            path.write_text(json.dumps(config))
            clock["now"] = at(11)
            with patch.object(sender, "load_active_config", return_value=config):
                self.assertEqual(sender.send_once(smtp, delivery_mode="intraday_alert"), 2)
            credentials.assert_not_called()
            smtp.assert_not_called()

    def test_failed_refresh_uses_a_typed_zero_order_artifact_without_reusing_success(self):
        with adopted_sender() as (root, _, _, _, smtp):
            old_bytes = sender.DAILY_DECISION_JSON_PATH.read_bytes()
            state_path = root / contract.REFRESH_REL
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"cycle_date": "2026-09-01", "started_at": at(8).isoformat(),
                "completed_at": at(9).isoformat(), "outcome": "failed", "hard_failures": ["market_data"]}))
            with patch.object(sender, "validate_decision", side_effect=AssertionError("stale success must not be read")):
                self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning",
                    failure_reason="daily_refresh_not_fully_passed"), 0)
            self.assertEqual(sender.DAILY_DECISION_JSON_PATH.read_bytes(), old_bytes)
            row = sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)[-1]
            archive = root / contract.ARCHIVE_REL
            artifact = json.loads((archive / (row["decision_sha256"] + ".json")).read_bytes())
            self.assertEqual(artifact["schema_version"], "equity_mandatory_status_brief_v1")
            self.assertNotIn("capital_decision", artifact)
            text = (archive / (row["brief_text_sha256"] + ".txt")).read_text()
            self.assertIn("verifies neither market prices nor account facts", text)
            self.assertNotIn("$87.18", text)

    def test_changed_failure_source_blocks_the_durable_claim(self):
        with adopted_sender() as (root, _, _, credentials, smtp):
            path = root / contract.REFRESH_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"outcome":"failed"}')
            def mutate():
                path.write_text('{"outcome":"changed"}')
                return credentials.return_value
            credentials.side_effect = mutate
            self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning",
                failure_reason="daily_refresh_not_fully_passed"), 2)
            smtp.assert_not_called()
            self.assertEqual(sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH), [])

    def test_failed_current_publication_cannot_suppress_or_leak_stale_orders_into_mandatory_brief(self):
        with adopted_sender() as (root, _, _, _, smtp):
            path = root / contract.REFRESH_REL
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"cycle_date": "2026-09-01", "started_at": at(8).isoformat(),
                "completed_at": at(9).isoformat(), "outcome": "passed"}))
            with patch.object(sender, "validate_decision", side_effect=ValueError("workflow_inputs_changed_recompose_required")):
                self.assertEqual(sender.send_once(smtp, delivery_mode="scheduled_brief", scheduled_slot="morning"), 0)
            row = sender.read_csv(sender.DAILY_DELIVERY_LEDGER_PATH)[-1]
            artifact = json.loads((root / contract.ARCHIVE_REL / (row["decision_sha256"] + ".json")).read_bytes())
            self.assertEqual(artifact["status"], "current_publication_unverified")
            self.assertNotIn("capital_decision", artifact)
            self.assertNotIn("held_positions", artifact)
            text = (root / contract.ARCHIVE_REL / (row["brief_text_sha256"] + ".txt")).read_text()
            self.assertNotIn("$87.18", text)
            self.assertIn("No earlier price, DAY order or trading quantity is renewed", text)


class AssessmentSchedulerTests(unittest.TestCase):
    def invoke(self, state, current, output="email_sent=false reason=unchanged_action_and_priority", code=0):
        config = copy.deepcopy(CONFIG)
        config["notifications"].update(mandatory_daily_briefs=True, intraday_alerts_enabled=True,
            delivery_assessment_effective_from="2026-09-01")
        with ExitStack() as stack:
            for name, value in [("load_active_state", {"operational_from": "2026-08-01"}), ("load_inhibit", {"active": False}),
                    ("load_active_config", config), ("now_et", current), ("cycle_date", current.date().isoformat()),
                    ("iso_now", current.isoformat()), ("read_json", state)]:
                stack.enter_context(patch.object(scheduler, name, return_value=value))
            for name in ["atomic_write_json", "publish_automation_alert", "clear_automation_alert"]:
                stack.enter_context(patch.object(scheduler, name))
            stack.enter_context(patch.object(scheduler.sys, "argv", ["scheduler.py"]))
            run = stack.enter_context(patch.object(scheduler.subprocess, "run", return_value=
                scheduler.subprocess.CompletedProcess([], code, stdout=output)))
            with redirect_stdout(io.StringIO()):
                result = scheduler.main()
            return result, run

    def test_one_due_brief_covers_the_poll_then_later_polls_can_check_more_alerts(self):
        state = {"dates": {}}
        _, run = self.invoke(state, at(9, 30), "email_sent=true message_count=1")
        self.assertIn("scheduled_brief", run.call_args.args[0])
        self.assertEqual(run.call_count, 1)
        for stamp in [at(9, 45), at(11), at(11, 15)]:
            _, run = self.invoke(state, stamp)
            self.assertIn("intraday_alert", run.call_args.args[0])
        self.assertEqual(state["dates"]["2026-09-01"]["intraday_alerts"]["decision_checks"], 3)
        _, run = self.invoke(state, at(14, 30), "email_sent=true message_count=1")
        self.assertIn("scheduled_brief", run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-1], "afternoon")

    def test_waiting_validation_does_not_retire_a_mandatory_brief_or_consume_smtp_attempts(self):
        state = {"dates": {}}
        self.invoke(state, at(9, 30), "email_sent=false reason=source_changed smtp_config_read=false", 2)
        slot = state["dates"]["2026-09-01"]["delivery_windows"]["morning"]
        self.assertNotIn("decision_completed", slot)
        self.assertNotIn("decision_attempts", slot)
        _, run = self.invoke(state, at(9, 45), "email_sent=false delivery_purpose_complete=true")
        self.assertIn("scheduled_brief", run.call_args.args[0])
        self.assertTrue(slot["decision_completed"])

    def test_unknown_delivery_and_closed_market_prevent_future_alert_invocations(self):
        state = {"dates": {}}
        self.invoke(state, at(9, 30), "email_sent=unknown reason=smtp_exception_after_claim", 1)
        _, run = self.invoke(state, at(11))
        run.assert_not_called()
        for stamp in [at(16), at(20)]:
            _, run = self.invoke({"dates": {}}, stamp)
            run.assert_not_called()

    def test_pipeline_failure_routes_only_the_current_typed_brief(self):
        config = copy.deepcopy(CONFIG)
        config["notifications"].update(mandatory_daily_briefs=True, intraday_alerts_enabled=True,
            delivery_assessment_effective_from="2026-09-01")
        with ExitStack() as stack:
            for name, value in [("load_active_state", {}), ("load_inhibit", {"active": False}),
                    ("now_et", at(9, 30)), ("load_active_config", config),
                    ("refresh_readiness", (False, "daily_refresh_not_fully_passed"))]:
                stack.enter_context(patch.object(pipeline, name, return_value=value))
            stack.enter_context(patch.object(pipeline, "ExclusiveFileLock"))
            stack.enter_context(patch.object(pipeline, "log_daily_run"))
            stack.enter_context(patch.object(pipeline, "clear_automation_alert"))
            run = stack.enter_context(patch.object(pipeline, "run_command", return_value=
                pipeline.subprocess.CompletedProcess([], 0, stdout="email_sent=true message_count=1")))
            with redirect_stdout(io.StringIO()):
                self.assertEqual(pipeline.execute(True, "morning", "scheduled_brief"), 0)
            command = run.call_args.args[0]
            self.assertIn("--failure-status", command)
            self.assertIn("daily_refresh_not_fully_passed", command)


class AssessmentFollowthroughIntegrationTests(unittest.TestCase):
    def test_priority_only_alert_does_not_retire_earlier_delivered_order_instructions(self):
        import delivery_followthrough as follow
        from email_brief import render_email
        from test_delivery_followthrough import decision, archive, MORNING, AFTERNOON
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = decision()
            archive(root, prior, when=MORNING)
            later = copy.deepcopy(prior)
            later["generated_at"] = MORNING.replace(hour=12).isoformat()
            later["analyst_priority_review"] = {"status": "current", "change_basis": "source_bound_event_change",
                "entries": [{"ticker": "META", "reason": "Event expectations remain unknown.",
                             "next_step": "Complete the sourced downside case."}]}
            eligibility = {"eligible": True, "mode": "intraday_alert", "purpose_key": "alert:2026-09-28:" + "a" * 64 + ":" + "b" * 64,
                "meaning_key": contract.advice_meaning_key(later), "action_changed": False, "priority_changed": True,
                "changed_action_tickers": [], "removed_action_tickers": []}
            raw = json.dumps(later).encode()
            later["delivery_assessment"] = contract.delivery_envelope(later, eligibility,
                canonical_decision_sha256=hashlib.sha256(raw).hexdigest())
            _, text, document = render_email(later)
            # An honest research-only alert is structured and contains no new
            # displayed order. The older actual instructions still remain due.
            self.assertEqual(follow._displayed_actions(later, text, document, MORNING.replace(hour=12)), ([], False))
            archive(root, later, when=MORNING.replace(hour=12))
            context = follow.build_followthrough(later, root=root, current=AFTERNOON)
            self.assertEqual(context["status"], "multiple_deliveries_require_reconciliation")
            self.assertTrue(follow.continuation_requires_reconciliation(context))
            self.assertEqual(context["actions"], [])


if __name__ == "__main__":
    unittest.main()
