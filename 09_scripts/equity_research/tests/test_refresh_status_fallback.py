"""Soft source failure preserves communication, never stale trading authority."""
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import refresh_handoff as handoff
import run_daily_refresh as refresh
import run_daily_decision_pipeline as pipeline
import send_daily_email as sender
import scheduled_email

NOW = datetime.fromisoformat("2026-10-06T14:35:00-04:00")


class LimitedRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = {
            "schema_version": "phase5r_daily_refresh_state_v1", "cycle_date": "2026-10-06",
            "expected_market_session": "2026-10-05", "started_at": "2026-10-06T13:50:00-04:00",
            "completed_at": "2026-10-06T14:00:00-04:00", "outcome": "degraded_decision_created",
            "decision_created": True, "hard_failures": [], "soft_failures": ["official_evidence"],
            **{key: False for key in ("email_attempted", "email_sent", "broker_connected", "broker_account_read", "order_code_created")},
            "steps": [{"name": name, "script": script, "allowed_to_fail": allowed,
                       "exit_code": int(name == "official_evidence"),
                       "outcome": "failed" if name == "official_evidence" else "passed"}
                      for name, script, allowed in refresh.STEP_SPECS]}
        self.decision = {
            "generated_at": "2026-10-06T13:59:00-04:00", "cycle_date": "2026-10-06",
            "market_gate": {"passed": True, "complete_close_verified": True,
                            "expected_market_session": "2026-10-05", "failures": []},
            "evidence_gate": {"passed": False}, "workflow_integrity": {"schema_version": "current"},
            "automatic_action_allowed": False,
            "boundaries": {key: False for key in ("broker_connected", "broker_account_read", "order_code_created", "trade_placed")},
            "capital_decision": {"global_blockers": ["evidence_gate_failed", "order_inventory_unverified_cannot_bound_buy_commitments"],
                                 "decisions": [{"ticker": "SPY", "decision": "BLOCKED", "shares": 0, "order_draft": None}]},
            "eligible_action_review_candidates": [], "eligible_new_position_review_candidates": [],
            "plan_continuity": {"plans": [{"ticker": "SPY", "status": "maintained", "eligible_quantity": 0}]}}
        for key, path in handoff.ARTIFACTS.items():
            p = self.root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(self.decision) if key == "decision" else key)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.workflow = self.stack.enter_context(patch("workflow_integrity.validate_published_workflow"))
        self.stack.enter_context(patch("delivery_followthrough.validate_followthrough"))
        self.stack.enter_context(patch("email_brief.render_email", return_value=("subject", "text", "html")))

    def save(self):
        (self.root / handoff.ARTIFACTS["decision"]).write_text(json.dumps(self.decision))

    def seal(self):
        self.save()
        self.state["limited_status_handoff"] = handoff.make_limited_handoff(self.state, root=self.root, current=NOW)

    def readiness(self, slot="afternoon"):
        state_path = self.root / "state.json"
        state_path.write_text(json.dumps(self.state))
        with patch.object(pipeline, "ROOT", self.root), patch.object(pipeline, "DAILY_REFRESH_STATE_PATH", state_path), \
             patch.object(pipeline, "now_et", return_value=NOW), patch.object(pipeline, "cycle_date", return_value="2026-10-06"):
            return pipeline.refresh_readiness(slot)

    def test_current_exact_zero_order_handoff_preserves_order_blocker(self):
        before = copy.deepcopy(self.decision)
        self.seal()
        self.assertEqual(self.readiness(), (True, "daily_refresh_limited_status_ready"))
        self.assertEqual(self.decision, before)
        self.assertEqual(self.state["outcome"], "degraded_decision_created")
        self.workflow.assert_called()

    def test_expired_plan_stays_expired_and_cannot_supply_positive_quantity(self):
        self.decision["plan_continuity"]["plans"][0]["status"] = "expired_pending_verification"
        self.seal()
        self.assertTrue(self.readiness()[0])
        self.assertEqual(self.decision["plan_continuity"]["plans"][0]["status"], "expired_pending_verification")
        self.decision["plan_continuity"]["plans"][0]["eligible_quantity"] = 1
        self.save()
        self.assertFalse(self.readiness()[0])

    def test_failures_cannot_be_relabelled_or_omitted(self):
        for field, value in [("hard_failures", ["market_refresh"]), ("soft_failures", ["official_evidence", "sec_filing_artifacts"]),
                             ("steps", self.state["steps"][:-1])]:
            with self.subTest(field=field):
                changed = copy.deepcopy(self.state)
                changed[field] = value
                with self.assertRaises(ValueError):
                    handoff.make_limited_handoff(changed, root=self.root, current=NOW)

    def test_stale_market_previous_cycle_and_morning_handoff_cannot_cover_afternoon(self):
        self.seal()
        for field, value in [("cycle_date", "2026-10-05"), ("expected_market_session", "2026-10-02"),
                             ("started_at", "2026-10-06T08:45:00-04:00")]:
            with self.subTest(field=field):
                original = self.state[field]
                self.state[field] = value
                self.assertFalse(self.readiness()[0])
                self.state[field] = original

    def test_eligible_candidates_any_order_or_removed_evidence_gate_fail_closed(self):
        for mutation in [lambda d: d.update(eligible_new_position_review_candidates=["NVDA"]),
                         lambda d: d["capital_decision"]["decisions"][0].update(order_draft={"quantity": 1}),
                         lambda d: d["capital_decision"]["decisions"][0].update(shares=1),
                         lambda d: d["evidence_gate"].update(passed=True),
                         lambda d: d["market_gate"].update(complete_close_verified=False),
                         lambda d: d["capital_decision"].update(global_blockers=[])]:
            original = copy.deepcopy(self.decision)
            mutation(self.decision)
            self.save()
            with self.assertRaises(ValueError):
                handoff.make_limited_handoff(self.state, root=self.root, current=NOW)
            self.decision = original

    def test_artifact_edit_or_stale_current_source_binding_rejects_handoff(self):
        self.seal()
        (self.root / handoff.ARTIFACTS["text"]).write_text("stale previous BUY 1 NVDA")
        self.assertFalse(self.readiness()[0])
        (self.root / handoff.ARTIFACTS["text"]).write_text("text")
        self.workflow.side_effect = ValueError("workflow_inputs_changed_recompose_required")
        self.assertFalse(self.readiness()[0])

    def test_sender_refuses_missing_handoff_before_credentials_or_smtp(self):
        with patch.object(sender, "delivery_guard", return_value=(True, "ok", {}, {})), \
             patch.object(sender, "now_et", return_value=NOW), \
             patch.object(pipeline, "refresh_readiness", return_value=(False, "daily_refresh_limited_status_invalid")), \
             patch.object(sender, "load_config") as config, patch.object(sender, "log_daily_run"), \
             patch.object(sender, "validate_decision") as validate:
            self.assertEqual(sender.send_once(limited_status=True, scheduled_slot="afternoon"), 2)
        config.assert_not_called()
        validate.assert_not_called()

    def test_label_separate_from_action_cards_and_retained_status(self):
        cards = [{"title": "BUY — none", "body": "0 shares", "group": "action"},
                 {"title": "SPY", "body": "Expired plan; broker orders unverified.", "group": "context"}]
        with patch("capital_presentation.cards", return_value=copy.deepcopy(cards)):
            result = scheduled_email.cards(self.decision, {})
        self.assertEqual(result[0]["title"], "Limited evidence update")
        self.assertEqual(result[0]["group"], "context")
        self.assertIn("expired prices and DAY drafts are not renewed", result[0]["body"])
        self.assertEqual(result[1:], cards)

    def test_refresh_keeps_failure_and_retry_signal_while_sealing_limited_handoff(self):
        state_path = self.root / "state.json"
        rows = {row["name"]: row for row in self.state["steps"]}
        def step(name, script, allowed, **_):
            return rows.get(name, {"name": name, "exit_code": 0, "outcome": "passed"})
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh, "DAILY_REFRESH_STATE_PATH", state_path), \
             patch.object(refresh, "snapshot_active_portfolio"), patch.object(refresh, "load_active_state"), \
             patch.object(refresh, "load_inhibit"), patch.object(refresh, "log_daily_run"), \
             patch.object(refresh, "run_step", side_effect=step), patch("workflow_evaluation.record_refresh"), \
             patch.object(refresh, "cycle_date", return_value="2026-10-06"), \
             patch.object(refresh, "now_et", return_value=NOW), \
             patch.object(refresh, "iso_now", side_effect=[self.state["started_at"], self.state["completed_at"], NOW.isoformat()]):
            self.assertEqual(refresh.run_refresh(no_lock=True), 1)
        published = json.loads(state_path.read_text())
        self.assertEqual(published["outcome"], "degraded_decision_created")
        self.assertEqual(published["soft_failures"], ["official_evidence"])
        self.assertEqual(published["limited_status_handoff"]["mode"], "limited_status_only")
        self.assertFalse(published["email_attempted"])

    def test_pipeline_selects_explicit_limited_sender_mode_without_marking_research_passed(self):
        import subprocess
        with patch.object(pipeline, "load_active_state"), patch.object(pipeline, "load_inhibit", return_value={}), \
             patch.object(pipeline, "ExclusiveFileLock", return_value=nullcontext()), \
             patch.object(pipeline, "now_et", return_value=NOW), patch.object(pipeline, "log_daily_run"), \
             patch.object(pipeline, "clear_automation_alert"), \
             patch.object(pipeline, "refresh_readiness", return_value=(True, "daily_refresh_limited_status_ready")), \
             patch.object(pipeline, "run_command", return_value=subprocess.CompletedProcess([], 0, "email_sent=false unchanged")) as command:
            self.assertEqual(pipeline.execute(send=True, scheduled_slot="afternoon"), 0)
        self.assertIn("--limited-status", command.call_args.args[0])
        self.assertEqual(command.call_args.args[0][-2:], ["--delivery-window", "afternoon"])


if __name__ == "__main__":
    unittest.main()
