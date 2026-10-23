from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ET, ExclusiveFileLock, atomic_write_json, canonical_sha256, sha256_file
import short_assessment as short


class ShortAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "equity"
        self.root.mkdir()
        self.runtime_lock = Path(self.temp.name) / "runtime.lock"
        atomic_write_json(self.root / "00_project_control/active_production_config.json", {
            "notifications": {"delivery_assessment_effective_from": "2026-10-22",
                "short_assessment_slots_et": list(short.SLOTS), "short_assessment_budget_minutes": 10}})
        self.news = patch("official_news.read_official_news_status", return_value={"status": "ok", "sources": [], "recent_events": []})
        self.events = patch("earnings_events.summary", return_value={"status": "ready", "events": [], "coverage": {}})
        self.news.start(); self.events.start()
        self.addCleanup(self.news.stop); self.addCleanup(self.events.stop)
        self.source = self.root / "08_reviews/source.txt"
        self.source.parent.mkdir()
        self.source.write_text("Dated primary source observation.")
        self.typed_publication("09:20")

    def moment(self, clock, day="2026-10-22"):
        return datetime.fromisoformat(f"{day}T{clock}:00").replace(tzinfo=ET)

    def claim(self, when="09:30", **kwargs):
        return short.claim(self.root, self.moment(when), runtime_lock=self.runtime_lock, **kwargs)

    def result(self, claim, **kwargs):
        return {"schema_version": short.SCHEMA, "claim_id": claim["receipt"]["claim_id"],
            "outcome": "unresolved", "accepted_amendments": [],
            "continuation": {"status": "waiting_on_external_dependency",
                             "next_step": "Wait for a source establishing current consensus expectations."}, "items": [{
                "ticker": "META", "conclusion": "No entry supported by available evidence.",
                "rationale": "The source does not establish a price-expectations difference.",
                "next_step": "Complete expectations and downside valuation in the full review.",
                "sources": [{"path": "08_reviews/source.txt", "sha256": sha256_file(self.source),
                             "available_at": self.moment("09:20").isoformat()}]}], **short.AUTHORITY, **kwargs}

    def complete(self, result, clock="09:35"):
        return short.complete(self.root, result, self.moment(clock), runtime_lock=self.runtime_lock)

    def typed_publication(self, clock, *, degraded=False):
        from test_email_brief import decision_fixture
        from delivery_assessments import delivery_policy_context, priority_review_context
        from workflow_integrity import apply_workflow_integrity, validate_published_workflow
        from earnings_events import summary
        from email_brief import render_email
        for relative, value in (
                ("05_risk_and_positions/investment_plans.local.json", {"schema_version": "equity_investment_plans_v1", "records": []}),
                ("05_risk_and_positions/current_open_orders.local.json", {"as_of": self.moment("09:20").isoformat(), "complete": True, "orders": []})):
            if not (self.root / relative).exists():
                atomic_write_json(self.root / relative, value)
        value = decision_fixture()
        value.update(generated_at=self.moment(clock).isoformat(), cycle_date="2026-10-22", held_positions=[])
        value["account"].update(account_total_value="1000", cash_available="1000", cash_reserved="0")
        if degraded:
            value["market_gate"]["passed"] = False
            value["decision_code"] = "data_gate_hold"
        apply_workflow_integrity(value, root=self.root, current=self.moment(clock))
        value["earnings_events"] = summary(self.root, current=self.moment(clock))
        value["assessment_delivery_policy"] = delivery_policy_context(self.root)
        value["analyst_priority_review"] = priority_review_context(self.root, self.moment(clock))
        atomic_write_json(self.root / "04_research/company_research/daily_decision.json", value)
        validate_published_workflow(value, root=self.root, current=self.moment(clock))
        _subject, text, html = render_email(value)
        directory = self.root / "07_automation/email_briefs"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "daily_email_brief.txt").write_text(text)
        (directory / "daily_email_brief.html").write_text(html)
        return value

    def calendar(self, clock):
        from earnings_events import refresh_events, POLICY_REL
        from daily_common import ROOT
        from test_earnings_events import feed
        if not (self.root / POLICY_REL).exists():
            (self.root / POLICY_REL).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / POLICY_REL, self.root / POLICY_REL)
        return refresh_events(self.root, clock=lambda: self.moment(clock),
                              fetcher=lambda day, policy: feed(day, []))

    def refresh_receipt(self, started, completed, *, degraded=False):
        from run_daily_refresh import STEP_SPECS
        atomic_write_json(self.root / "00_project_control/run_logs/daily_refresh_state.local.json", {
            "started_at": self.moment(started).isoformat(), "completed_at": self.moment(completed).isoformat(),
            "outcome": "degraded_decision_created" if degraded else "passed", "decision_created": True,
            "market_snapshot_mode": "reuse_validated_snapshot", "email_attempted": False, "email_sent": False,
            "steps": [{"name": spec[0], "exit_code": 1 if degraded and spec[0] == "market_refresh" else 0}
                      for spec in STEP_SPECS]})

    def test_slot_cadence_dst_and_no_catchup(self):
        for clock in short.SLOTS:
            self.assertEqual(short.due_slot(self.moment(clock))["slot"], clock)
        for clock in ("09:29", "09:45", "10:30", "16:00", "20:00"):
            self.assertEqual(short.due_slot(self.moment(clock))["outcome"], "not_due")
        utc = datetime.fromisoformat("2026-11-02T14:30:00+00:00")
        self.assertEqual(short.due_slot(utc)["slot"], "09:30")
        self.assertEqual(short.due_slot(datetime.fromisoformat("2026-10-22T13:30:00+00:00"))["slot"], "09:30")
        with self.assertRaisesRegex(ValueError, "aware_timestamp"):
            short.due_slot(datetime(2026, 10, 22, 9, 30))

    def test_holiday_weekend_and_existing_early_close(self):
        for day in ("2026-10-24", "2026-11-26", "2026-12-25"):
            self.assertEqual(short.market_session(self.moment("11:00", day))["reason"], "exchange_closed")
        for day in ("2026-11-27", "2026-12-24"):
            self.assertEqual(short.due_slot(self.moment("12:30", day))["outcome"], "due")
            self.assertEqual(short.due_slot(self.moment("14:00", day))["outcome"], "not_due")
            self.assertTrue(short.market_session(self.moment("12:30", day))["close_at"].endswith("13:00:00-05:00"))
        self.assertEqual(short.market_session(self.moment("11:00", "2030-10-22"))["reason"], "exchange_calendar_unverified")

    def test_effective_date_and_read_only_check(self):
        value = short.check(self.root, self.moment("09:30", "2026-10-21"))
        self.assertEqual(value["reason"], "short_assessments_not_active")
        self.assertFalse((self.root / short.STATE_REL).exists())
        self.assertEqual(short.check(self.root, self.moment("09:30"))["outcome"], "due")
        self.assertFalse((self.root / short.STATE_REL).exists())

    def test_claim_is_durable_duplicate_safe_and_has_ten_minute_scope(self):
        value = self.claim()
        row = value["receipt"]
        self.assertEqual(value["outcome"], "claimed")
        self.assertTrue((self.root / row["receipt_path"]).is_file())
        self.assertEqual(short.aware(row["expires_at"]), self.moment("09:40"))
        self.assertEqual(row["context"]["scope"]["maximum_items"], 2)
        self.assertFalse(row["context"]["market_data_is_intraday_quote"])
        self.assertEqual(self.claim("09:31")["outcome"], "already_reserved")

    def test_busy_runtime_and_pipeline_never_consume_slot_or_wait(self):
        for lock in (self.runtime_lock, self.root / "00_project_control/run_logs/daily_pipeline.lock"):
            with ExclusiveFileLock(lock):
                value = self.claim()
            self.assertEqual(value["outcome"], "pending_refresh_lock")
            self.assertEqual(short.check(self.root, self.moment("09:31"))["outcome"], "due")
        self.assertEqual(self.claim("09:32")["outcome"], "claimed")

    def test_expired_work_and_missed_slots_remain_receipts_not_catchup(self):
        first = self.claim()
        with self.assertRaisesRegex(ValueError, "outside_budget"):
            self.complete(self.result(first), "09:41")
        value = self.claim("11:00")
        state = json.loads((self.root / short.STATE_REL).read_text())
        self.assertEqual(state["slots"]["2026-10-22/09:30"]["status"], "expired")
        self.assertEqual(value["outcome"], "claimed")
        short.claim(self.root, self.moment("14:20"), runtime_lock=self.runtime_lock)
        state = json.loads((self.root / short.STATE_REL).read_text())
        self.assertEqual(state["slots"]["2026-10-22/12:30"]["status"], "missed")
        self.assertEqual(state["slots"]["2026-10-22/14:00"]["status"], "missed")

    def test_late_completion_expires_durably_before_any_next_slot(self):
        value = self.claim()
        with ExclusiveFileLock(self.runtime_lock):
            with self.assertRaisesRegex(ValueError, "outside_budget"):
                self.complete(self.result(value), "09:41")
        state = json.loads((self.root / short.STATE_REL).read_text())
        row = state["slots"]["2026-10-22/09:30"]
        self.assertEqual(row["status"], "expired")
        self.assertEqual(row["expires_at"], value["receipt"]["expires_at"])
        self.assertNotIn("result", row)
        self.assertEqual(row["rejected_completion"]["status"], "unvalidated_late_attempt")
        self.assertFalse(row["rejected_completion"]["analytical_completion"])
        self.assertTrue((self.root / row["receipt_path"]).exists())
        self.assertEqual(short.check(self.root, self.moment("09:42"))["status"], "expired")

    def test_non_due_wake_retires_elapsed_claim_without_replay_or_network(self):
        value = self.claim()
        with patch.object(short, "refresh_public_handoff") as collector:
            result = self.claim("10:00", refresh_public=True)
        collector.assert_not_called()
        self.assertEqual(result["outcome"], "not_due")
        state = json.loads((self.root / short.STATE_REL).read_text())
        row = state["slots"]["2026-10-22/09:30"]
        self.assertEqual(row["status"], "expired")
        self.assertEqual(row["claim_id"], value["receipt"]["claim_id"])
        self.assertEqual(len(state["slots"]), 1)

    def journal_detection(self, clock="09:31"):
        from opportunity_contract import empty_store, append_event
        from opportunity_triggers import packet
        store = json.loads((self.root / short.OPPORTUNITY_JOURNAL).read_text())
        observation = packet(ticker="META", family="business", trigger="source_inspection",
            evidence={"fact": "Synthetic source-bound observation"},
            sources=[{"path": "08_reviews/source.txt", "sha256": sha256_file(self.source),
                "available_at": self.moment("09:20").isoformat()}], current=self.moment(clock),
            produced_by={"implementation_sha256": "1" * 64, "policy_sha256": "2" * 64})
        identity = canonical_sha256({"first_observation_id": observation["observation_id"], "ticker": "META"})
        append_event(store, {"kind": "detected", "opportunity_id": identity,
            "recorded_at": self.moment(clock).isoformat(), "observation": observation,
            "owner": "research_orchestration", "to_state": "queued",
            "reason_code": "bounded_attention_admission", "blockers": []})
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, store)
        return store, identity

    def test_collector_journal_append_is_separate_from_an_accepted_analyst_amendment(self):
        from opportunity_contract import empty_store, transition
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, empty_store())
        self.typed_publication("09:20")
        value = self.claim()
        store, identity = self.journal_detection()
        transition(store, identity, "researching", owner="objective_research",
            reason="objective_source_inspection_started", current=self.moment("09:31"),
            sources=self.result(value)["items"][0]["sources"], blockers=[])
        transition(store, identity, "data_blocked", owner="objective_research",
            reason="official_issuer_sources_not_cached_network_refresh_required", current=self.moment("09:32"),
            sources=self.result(value)["items"][0]["sources"], blockers=["missing_current_source"])
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, store)
        with self.assertRaisesRegex(ValueError, "post_public_handoff_recomposition_required"):
            self.complete(self.result(value))
        self.typed_publication("09:33")
        self.refresh_receipt("09:32", "09:34")
        done = self.complete(self.result(value))
        self.assertEqual(done["status"], "completed")
        self.assertFalse(done["result"]["accepted_amendments"])
        self.assertEqual(done["collector_changes"][0]["appended_records"], 3)
        self.assertFalse(done["collector_changes"][0]["analytical_completion"])
        self.assertTrue(done["publication"]["fully_passed_research"])

    def test_collector_classification_never_waives_analyst_journal_or_source_tamper(self):
        from opportunity_contract import empty_store, transition
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, empty_store())
        self.journal_detection("09:20")
        self.typed_publication("09:20")
        value = self.claim()
        store = json.loads((self.root / short.OPPORTUNITY_JOURNAL).read_text())
        identity = store["events"][0]["opportunity_id"]
        transition(store, identity, "insufficient_evidence", owner="analyst_assessment",
            reason="recorded_assessment:synthetic", current=self.moment("09:31"),
            sources=self.result(value)["items"][0]["sources"], blockers=["valuation_unresolved"])
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, store)
        self.assertIsNone(short._collector_journal_delta(self.root, value["receipt"], self.moment("09:35")))
        with self.assertRaisesRegex(ValueError, "amendment_receipts_incomplete"):
            self.complete(self.result(value))
        # Even a legally owned collector append needs original source bytes.
        store["events"].pop()
        transition(store, identity, "researching", owner="objective_research",
            reason="objective_source_inspection_started", current=self.moment("09:31"),
            sources=self.result(value)["items"][0]["sources"], blockers=[])
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, store)
        self.source.write_text("Corrupt retained original source")
        self.assertIsNone(short._collector_journal_delta(self.root, value["receipt"], self.moment("09:35")))

    def test_collector_classification_rejects_rewritten_history_even_with_new_hash_chain(self):
        from opportunity_contract import empty_store, append_event
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, empty_store())
        self.journal_detection("09:20")
        self.typed_publication("09:20")
        value = self.claim()
        store = json.loads((self.root / short.OPPORTUNITY_JOURNAL).read_text())
        event = store["events"][0]
        event["reason_code"] = "changed historical reason"
        event["record_hash"] = canonical_sha256({k: v for k, v in event.items() if k != "record_hash"})
        append_event(store, {"kind": "transition", "opportunity_id": event["opportunity_id"],
            "from_state": "queued", "to_state": "researching", "owner": "objective_research",
            "reason_code": "objective_source_inspection_started", "blockers": [],
            "sources": self.result(value)["items"][0]["sources"], "recorded_at": self.moment("09:31").isoformat()})
        atomic_write_json(self.root / short.OPPORTUNITY_JOURNAL, store)
        self.assertIsNone(short._collector_journal_delta(self.root, value["receipt"], self.moment("09:35")))
        with self.assertRaisesRegex(ValueError, "amendment_receipts_incomplete"):
            self.complete(self.result(value))

    def test_unchanged_completed_inputs_skip_without_repeat_analysis(self):
        value = self.claim()
        done = self.complete(self.result(value))
        self.assertEqual(done["status"], "completed")
        self.assertFalse(done["email_sent"])
        second = self.claim("11:00")
        self.assertEqual(second["outcome"], "unchanged")
        self.assertEqual(self.claim("11:01")["outcome"], "already_reserved")

    def test_unchanged_inputs_resume_useful_unfinished_analysis_without_repeating_receipt(self):
        first = self.claim()
        continuation = {"status": "continue_analysis", "next_step": "Compare the retained filing's two segment margin cases."}
        self.complete(self.result(first, continuation=continuation))
        second = self.claim("11:00")
        self.assertEqual(second["outcome"], "claimed")
        self.assertEqual(second["receipt"]["context"]["pending_work"]["status"], "continue_analysis")
        with self.assertRaisesRegex(ValueError, "unchanged_analytical_receipt_not_progress"):
            self.complete(self.result(second, continuation=continuation), "11:05")
        proposal = self.result(second, continuation={"status": "waiting_on_external_dependency",
            "next_step": "The retained segment cases are now compared; await the missing disclosure."})
        proposal["items"][0]["rationale"] = "Both margin cases remain below the existing required reward/risk. Missing disclosure prevents a supported terminal case."
        self.complete(proposal, "11:05")
        self.assertEqual(self.claim("12:30")["outcome"], "unchanged")

    def test_explicit_recheck_due_can_reopen_even_when_inputs_unchanged(self):
        first = self.claim()
        self.complete(self.result(first, outcome="no_action", continuation={"status": "complete",
            "next_step": "Review the current evidence before the afternoon decision deadline.",
            "next_review_at": self.moment("12:00").isoformat()}))
        self.assertEqual(self.claim("11:00")["outcome"], "unchanged")
        self.assertEqual(self.claim("12:30")["outcome"], "claimed")

    def test_changed_account_starts_a_new_assessment_and_rejects_stale_completion(self):
        value = self.claim()
        account = self.root / short.ACCOUNT_MARKET[0]
        account.parent.mkdir(parents=True, exist_ok=True)
        account.write_text("ticker,shares\nMETA,1\n")
        with self.assertRaisesRegex(ValueError, "account_or_market_changed"):
            self.complete(self.result(value))

    def test_pending_execution_change_is_bound_even_before_positions_or_cash_change(self):
        value = self.claim()
        pending = self.root / "06_execution_records/dashboard_feedback_pending.local.json"
        atomic_write_json(pending, {"records": [{"stage": "applying", "ticker": "META"}]})
        with self.assertRaisesRegex(ValueError, "account_or_market_changed"):
            self.complete(self.result(value))
        self.assertEqual(json.loads((self.root / short.STATE_REL).read_text())["slots"]["2026-10-22/09:30"]["status"], "claimed")

    def test_completion_rejects_fabricated_amendment_authority_missing_sources_and_source_tamper(self):
        value = self.claim()
        result = self.result(value)
        with self.assertRaisesRegex(ValueError, "authority_invalid"):
            self.complete({**result, "trade_placed": True})
        with self.assertRaisesRegex(ValueError, "actual_amendments_mismatch"):
            self.complete({**result, "outcome": "accepted_amendments"})
        with self.assertRaisesRegex(ValueError, "sources_required"):
            self.complete({**result, "items": [{**result["items"][0], "sources": []}]})
        self.source.write_text("Changed observation.")
        with self.assertRaisesRegex(ValueError, "source_changed"):
            self.complete(result)

    def test_accepted_store_changes_require_full_current_published_recomposition(self):
        value = self.claim()
        path = short.MUTABLE_STORES[0]
        store = self.root / path
        store.parent.mkdir(parents=True, exist_ok=True)
        record = {"recorded_at": self.moment("09:32").isoformat(), "plan_id": "accepted-plan-v2"}
        store.write_text(json.dumps({"records": [record]}))
        result = self.result(value, outcome="accepted_amendments", accepted_amendments=[{
            "path": path, "sha256": sha256_file(store), "record_identity": canonical_sha256(record)}])
        with self.assertRaisesRegex(ValueError, "post_amendment_recomposition_required"):
            self.complete(result)
        # A passing CLI, file edit or stale daily decision cannot complete the run.
        atomic_write_json(self.root / "04_research/company_research/daily_decision.json", {
            "generated_at": self.moment("09:00").isoformat()})
        with self.assertRaisesRegex(ValueError, "post_amendment_recomposition"):
            self.complete(result)
        with self.assertRaisesRegex(ValueError, "amendment_receipts_incomplete"):
            self.complete(self.result(value))

    def test_current_full_recomposition_binds_accepted_record_and_exact_artifacts(self):
        from run_daily_refresh import STEP_SPECS
        from delivery_assessments import delivery_policy_context, priority_review_context
        value = self.claim()
        path = short.MUTABLE_STORES[0]
        record = {"recorded_at": self.moment("09:31").isoformat(), "plan_id": "case-plan-v2"}
        atomic_write_json(self.root / path, {"records": [record]})
        result = self.result(value, outcome="accepted_amendments", accepted_amendments=[{
            "path": path, "sha256": sha256_file(self.root / path), "record_identity": canonical_sha256(record)}])
        atomic_write_json(self.root / "04_research/company_research/daily_decision.json", {
            "generated_at": self.moment("09:33").isoformat(),
            "workflow_integrity": {"schema_version": "equity_workflow_integrity_v1"},
            "assessment_delivery_policy": delivery_policy_context(self.root),
            "analyst_priority_review": priority_review_context(self.root, self.moment("09:33"))})
        atomic_write_json(self.root / "00_project_control/run_logs/daily_refresh_state.local.json", {
            "started_at": self.moment("09:32").isoformat(), "completed_at": self.moment("09:34").isoformat(),
            "outcome": "passed", "market_snapshot_mode": "reuse_validated_snapshot",
            "email_attempted": False, "email_sent": False,
            "steps": [{"name": spec[0], "exit_code": 0} for spec in STEP_SPECS]})
        folder = self.root / "07_automation/email_briefs"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "daily_email_brief.txt").write_text("actual text")
        (folder / "daily_email_brief.html").write_text("actual HTML")
        with patch("workflow_integrity.validate_published_workflow") as validate, patch(
                "email_brief.render_email", return_value=("subject", "actual text", "actual HTML")):
            done = self.complete(result)
        validate.assert_called_once()
        self.assertEqual(done["status"], "completed")
        self.assertFalse(done["publication"]["email_sent"])

    def test_real_priority_admission_and_typed_publication_complete_without_validation_mocks(self):
        from delivery_assessments import (AUTHORITY as PRIORITY_AUTHORITY, STORE_REL,
            apply_priority_review, priority_review_context, delivery_policy_context)
        from test_email_brief import decision_fixture
        from workflow_integrity import apply_workflow_integrity, validate_published_workflow
        from email_brief import render_email
        from run_daily_refresh import STEP_SPECS
        # Synthetic facts are deliberately not an eligible trade case. Actual
        # writers and publication validators, rather than patched successes,
        # must connect the resulting research-only priority to the final brief.
        for path, content in (
                ("05_risk_and_positions/current_positions.local.csv", "ticker,shares\n"),
                ("03_source_data/equity_research/market_data_snapshot.csv", "ticker,close\n")):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
        atomic_write_json(self.root / "05_risk_and_positions/current_account_state.local.json", {"cash": 1000})
        atomic_write_json(self.root / "05_risk_and_positions/current_open_orders.local.json", {
            "as_of": self.moment("09:20").isoformat(), "complete": True, "orders": []})
        atomic_write_json(self.root / "05_risk_and_positions/investment_plans.local.json", {
            "schema_version": "equity_investment_plans_v1", "records": []})
        atomic_write_json(self.root / "04_research/company_research/thesis_dossiers.local.json", {
            "schema_version": "equity_thesis_dossiers_v1", "records": []})
        decision = decision_fixture()
        decision.update(generated_at=self.moment("09:20").isoformat(), cycle_date="2026-10-22", held_positions=[])
        decision["account"].update(account_total_value="1000", cash_available="1000", cash_reserved="0")
        apply_workflow_integrity(decision, root=self.root, current=self.moment("09:20"))
        decision["assessment_delivery_policy"] = delivery_policy_context(self.root)
        decision["analyst_priority_review"] = priority_review_context(self.root, self.moment("09:20"))
        target = self.root / "04_research/company_research/daily_decision.json"
        atomic_write_json(target, decision)
        claim = self.claim()
        proposal = {"schema_version": "equity_research_priority_review_v1",
            "reviewed_at": self.moment("09:31").isoformat(), "next_review_at": self.moment("14:30").isoformat(),
            "reviewer": "isolated integration fixture", "change_basis": "completed_analysis",
            "review_summary": "A source-bound research priority changed; no trading eligibility is implied.",
            "basis_decision_sha256": sha256_file(target), "entries": [{"ticker": "META",
                "reason": "Complete expectations and the downside case before considering an event entry.",
                "next_step": "Use the retained dated source to finish a causal downside valuation.",
                "sources": self.result(claim)["items"][0]["sources"]}], **PRIORITY_AUTHORITY}
        self.assertEqual(apply_priority_review(self.root, proposal, current=self.moment("09:31"))["status"], "validated")
        accepted = apply_priority_review(self.root, proposal, current=self.moment("09:31"), apply=True)
        self.assertEqual(accepted["status"], "recorded")
        self.assertEqual(priority_review_context(self.root, self.moment("09:32"))["status"], "current")
        decision["generated_at"] = self.moment("09:33").isoformat()
        apply_workflow_integrity(decision, root=self.root, current=self.moment("09:33"))
        decision["assessment_delivery_policy"] = delivery_policy_context(self.root)
        decision["analyst_priority_review"] = priority_review_context(self.root, self.moment("09:33"))
        atomic_write_json(target, decision)
        validate_published_workflow(decision, root=self.root, current=self.moment("09:35"))
        _subject, text, html = render_email(decision)
        directory = self.root / "07_automation/email_briefs"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "daily_email_brief.txt").write_text(text)
        (directory / "daily_email_brief.html").write_text(html)
        atomic_write_json(self.root / "00_project_control/run_logs/daily_refresh_state.local.json", {
            "started_at": self.moment("09:32").isoformat(), "completed_at": self.moment("09:34").isoformat(),
            "outcome": "passed", "market_snapshot_mode": "reuse_validated_snapshot", "email_attempted": False,
            "email_sent": False, "steps": [{"name": spec[0], "exit_code": 0} for spec in STEP_SPECS]})
        result = self.result(claim, outcome="accepted_amendments", continuation={"status": "continue_analysis",
            "next_step": "Continue the retained source-bound downside valuation."}, accepted_amendments=[{
                "path": str(STORE_REL), "sha256": sha256_file(self.root / STORE_REL),
                "record_identity": accepted["record_sha256"]}])
        # A newly generated legacy-shaped report must not exploit the common
        # validator's intentional support for historic uncontracted artifacts.
        del decision["workflow_integrity"]
        atomic_write_json(target, decision)
        with self.assertRaisesRegex(ValueError, "typed_current_publication"):
            self.complete(result)
        apply_workflow_integrity(decision, root=self.root, current=self.moment("09:33"))
        atomic_write_json(target, decision)
        _subject, text, html = render_email(decision)
        (directory / "daily_email_brief.txt").write_text(text)
        (directory / "daily_email_brief.html").write_text(html)
        done = self.complete(result)
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["result"]["accepted_amendments"][0]["record_identity"], accepted["record_sha256"])
        self.assertEqual(done["publication"]["decision_sha256"], sha256_file(target))

    def test_public_handoff_binds_news_calendar_and_held_prices_after_reservation(self):
        def child(command, **kwargs):
            state = json.loads((self.root / short.STATE_REL).read_text())
            self.assertEqual(state["slots"]["2026-10-22/09:30"]["status"], "claimed")
            name = Path(command[1]).name
            self.assertIn(name, {"refresh_official_news.py", "refresh_earnings_events.py", "run_intraday_assessment.py"})
            self.assertEqual(kwargs["timeout"], 105 if name == "run_intraday_assessment.py" else 90)
            return SimpleNamespace(returncode=0)
        value = self.claim(refresh_public=True, runner=child)
        handoff = value["receipt"]["context"]["public_handoff"]
        self.assertEqual(handoff["status"], "completed")
        self.assertEqual(len(handoff["children"]), 3)

    def test_identical_calendar_refetch_requires_recomposition_even_with_unchanged_economics(self):
        self.events.stop()  # Use real retained scans and the actual summary validator.
        self.calendar("09:20")
        self.typed_publication("09:20")
        first = self.claim()
        self.complete(self.result(first))

        def collector(command, **kwargs):
            if Path(command[1]).name == "refresh_earnings_events.py":
                self.calendar("11:00")
            return SimpleNamespace(returncode=0)

        second = self.claim("11:00", refresh_public=True, runner=collector)
        # The actual collector changes scan references and collection clocks,
        # despite returning the same empty calendar on all ten dates.
        self.assertEqual(first["receipt"]["context"]["input_fingerprint"],
                         second["receipt"]["context"]["input_fingerprint"])
        self.assertEqual(second["outcome"], "claimed")
        self.assertTrue(second["publication_recomposition_required"])
        self.assertEqual(second["required_next_step"]["operation"], "short_publication_no_send_recomposition")
        self.assertTrue(second["required_next_step"]["release_mutation_locks_first"])
        self.assertIn("03_source_data/equity_research/earnings_events.local.json",
                      second["receipt"]["publication_input_changes"])
        for outcome in ("no_action", "unresolved"):
            with self.assertRaisesRegex(ValueError, "post_public_handoff_recomposition_required"):
                self.complete(self.result(second, outcome=outcome), "11:03")
        self.typed_publication("11:03")
        self.refresh_receipt("11:02", "11:04")
        done = self.complete(self.result(second), "11:05")
        self.assertEqual(done["status"], "completed")
        self.assertTrue(done["publication"]["fully_passed_research"])
        self.assertFalse(done["publication"]["email_sent"])
        state = json.loads((self.root / short.STATE_REL).read_text())
        self.assertNotIn("publication_recomposition_pending", state)

    def test_publication_closure_is_separate_from_full_accepted_amendment_refresh(self):
        value = self.claim()
        # A public binding change requires publication but not a new company model.
        atomic_write_json(self.root / "03_source_data/equity_research/earnings_events_status.local.json",
                          {"observed_at": self.moment("09:31").isoformat()})
        self.typed_publication("09:33")
        atomic_write_json(self.root / "00_project_control/run_logs/short_publication_refresh.local.json",
                          {"claim_id": value["receipt"]["claim_id"]})
        metadata = {"decision_sha256": sha256_file(self.root / "04_research/company_research/daily_decision.json"),
                    "generated_at": self.moment("09:33").isoformat(), "email_sent": False,
                    "refresh_outcome": "passed", "fully_passed_research": False,
                    "publication_only": True}
        # The standalone validator has separate real source-bound integration
        # tests. Here prove completion invokes it and preserves its narrower claim.
        with patch.dict("sys.modules", {"short_publication": SimpleNamespace(
                validate_receipt=lambda root, row, current: metadata)}):
            done = self.complete(self.result(value))
        self.assertEqual(done["status"], "completed")
        self.assertFalse(done["publication"]["fully_passed_research"])
        self.assertTrue(done["publication"]["publication_only"])

    def test_corrupt_short_publication_cannot_fallback_or_complete_accepted_amendment(self):
        value = self.claim()
        atomic_write_json(self.root / "03_source_data/equity_research/earnings_events_status.local.json", {"changed": True})
        self.typed_publication("09:33")
        self.refresh_receipt("09:32", "09:34")
        atomic_write_json(self.root / "00_project_control/run_logs/short_publication_refresh.local.json",
                          {"claim_id": value["receipt"]["claim_id"]})
        def corrupt(*args):
            raise ValueError("short_publication_corrupt_exact_bytes")
        with patch.dict("sys.modules", {"short_publication": SimpleNamespace(validate_receipt=corrupt)}):
            with self.assertRaisesRegex(ValueError, "short_publication_corrupt_exact_bytes"):
                self.complete(self.result(value))
        path = short.MUTABLE_STORES[0]
        record = {"recorded_at": self.moment("09:31").isoformat(), "plan_id": "new-accepted-plan"}
        atomic_write_json(self.root / path, {"records": [record]})
        result = self.result(value, outcome="accepted_amendments", accepted_amendments=[{
            "path": path, "sha256": sha256_file(self.root / path), "record_identity": canonical_sha256(record)}])
        # A matching short-publication receipt never replaces the strict full
        # refresh and actual post-amendment input binding for a plan/model edit.
        with patch.dict("sys.modules", {"short_publication": SimpleNamespace(validate_receipt=corrupt)}):
            with self.assertRaisesRegex(ValueError, "inputs_changed"):
                self.complete(result)

    def test_public_recomposition_can_finish_as_truthful_degraded_zero_order_without_amendment(self):
        self.events.stop()
        self.calendar("09:20")
        self.typed_publication("09:20")

        def collector(command, **kwargs):
            if Path(command[1]).name == "refresh_earnings_events.py":
                self.calendar("09:30")
            return SimpleNamespace(returncode=0)

        value = self.claim(refresh_public=True, runner=collector)
        self.assertTrue(value["publication_recomposition_required"])
        decision = self.typed_publication("09:33", degraded=True)
        self.refresh_receipt("09:32", "09:34", degraded=True)
        self.assertFalse(decision["market_gate"]["passed"])
        self.assertFalse(decision["eligible_new_position_review_candidates"])
        done = self.complete(self.result(value))
        self.assertEqual(done["publication"]["refresh_outcome"], "degraded_decision_created")
        self.assertFalse(done["publication"]["fully_passed_research"])
        self.assertTrue(done["publication"]["safe_degraded_zero_order"])
        self.assertFalse(done["result"]["accepted_amendments"])

    def test_expired_or_interrupted_public_repair_carries_into_the_next_slot(self):
        def collector(command, **kwargs):
            atomic_write_json(self.root / "03_source_data/equity_research/earnings_events_status.local.json",
                              {"status": "partial", "generated_at": self.moment("09:30").isoformat()})
            raise SystemExit("collector interrupted after its atomic publication")
        with self.assertRaises(SystemExit):
            self.claim(refresh_public=True, runner=collector)
        state = json.loads((self.root / short.STATE_REL).read_text())
        self.assertEqual(state["publication_recomposition_pending"]["status"], "public_refresh_in_progress")
        value = self.claim("11:00")
        self.assertEqual(value["outcome"], "claimed")
        self.assertTrue(value["publication_recomposition_required"])

    def test_stale_publication_before_claim_is_not_an_unchanged_success(self):
        first = self.claim()
        self.complete(self.result(first))
        decision_path = self.root / "04_research/company_research/daily_decision.json"
        value = json.loads(decision_path.read_text())
        del value["workflow_integrity"]
        atomic_write_json(decision_path, value)
        second = self.claim("11:00")
        self.assertEqual(second["outcome"], "claimed")
        self.assertTrue(second["publication_recomposition_required"])
        self.assertEqual(second["receipt"]["publication_validation_error"],
                         "short_assessment_typed_current_publication_required")
        self.assertFalse(second["receipt"]["publication_input_changes"])
        with self.assertRaisesRegex(ValueError, "post_public_handoff_recomposition_required"):
            self.complete(self.result(second), "11:03")

    def test_every_no_action_completion_rechecks_actual_final_bodies(self):
        value = self.claim()
        self.assertFalse(value["publication_recomposition_required"])
        body = self.root / "07_automation/email_briefs/daily_email_brief.txt"
        body.write_text("A stale or different body.")
        with self.assertRaisesRegex(ValueError, "final_email_recomposition_required"):
            self.complete(self.result(value, outcome="no_action"))

    def test_public_timeout_failure_is_explicit_and_no_repeat_same_slot(self):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("public source", 90)
        value = self.claim(refresh_public=True, runner=timeout)
        self.assertEqual(value["receipt"]["context"]["public_handoff"]["status"], "failed_or_incomplete")
        self.assertEqual(self.claim("09:31", refresh_public=True, runner=timeout)["outcome"], "already_reserved")

    def test_public_recent_reuse_and_budget_exhaustion(self):
        for path, field in (("03_source_data/equity_research/official_news_status.local.json", "last_attempt_at"),
                            ("03_source_data/equity_research/earnings_events.local/last_run.json", "completed_at")):
            atomic_write_json(self.root / path, {field: self.moment("09:20").isoformat()})
        with patch.object(short.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as child:
            value = self.claim(refresh_public=True, runner=child)
        child.assert_called_once()
        self.assertEqual(Path(child.call_args.args[0][1]).name, "run_intraday_assessment.py")
        self.assertEqual(value["receipt"]["context"]["public_handoff"]["status"], "completed")
        value = self.claim("11:00", runner=lambda *a, **k: SimpleNamespace(returncode=0),
                           clock=lambda: self.moment("11:11"))
        self.assertEqual(value["outcome"], "expired")


if __name__ == "__main__":
    unittest.main()
