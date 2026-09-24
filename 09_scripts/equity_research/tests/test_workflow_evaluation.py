from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import track_recommendation_outcomes as outcomes
from workflow_evaluation import (operational_summary, outcome_coverage, performance_summary,
    record_performance, load_performance_records, record_refresh)


def base(record_id, kind):
    return dict(record_id=record_id, kind=kind, currency="USD", source_reference="statement.json",
                source_sha256="a" * 64, confirmed_by="owner_statement_review", confirmed_at="2026-09-24T18:00:00-04:00")


def nav(record_id, day, value):
    return dict(base(record_id, "nav"), observed_at=f"2026-09-{day}T16:00:00-04:00", nav=value,
                actual_cash=value - 1000, securities_value=1000, cash_basis="broker_observed_actual",
                complete_account=True, valuation_basis="broker_close")


def review():
    return dict(base("interval", "interval_review"), start_nav_id="start", end_nav_id="end", external_flow_ids=[],
                cash_flow_history_complete=True, holdings_history_reconciled=True,
                fees_income_corporate_actions_reconciled=True)


def flow():
    return dict(base("deposit", "external_flow"), occurred_at="2026-09-22T16:00:00-04:00", amount=500,
                transaction_id="ach-001", flow_type="deposit", status="posted_confirmed")


class WorkflowEvaluationTests(unittest.TestCase):
    def test_deposit_is_not_profit_and_time_weighting_is_explicit(self):
        rows = [nav("start", "21", 1000), nav("end", "23", 1500), flow(), dict(review(), external_flow_ids=["deposit"])]
        result = performance_summary(rows)
        self.assertEqual(result["intervals"][0]["return_pct"], 0)
        self.assertIsNone(result["portfolio_lifetime_return_pct"])
        rows[1]["nav"] = 1625
        rows[1]["actual_cash"] = 625
        self.assertEqual(performance_summary(rows)["intervals"][0]["return_pct"], 10)
        self.assertIn("approximation", result["intervals"][0]["method"])

    def test_missing_history_or_flow_attestation_blocks(self):
        rows = [nav("start", "21", 1000), nav("end", "23", 1600)]
        self.assertEqual(performance_summary(rows)["status"], "not_ready")
        rows.extend([flow(), review()])
        result = performance_summary(rows)
        self.assertIsNone(result["intervals"][0]["return_pct"])
        self.assertIn("external_flow_list_not_reconciled", result["intervals"][0]["blockers"])
        rows[-1].update(external_flow_ids=["deposit"], fees_income_corporate_actions_reconciled=False)
        self.assertEqual(performance_summary(rows)["status"], "not_ready")

    def test_planning_cash_unconfirmed_flow_and_sweeps_rejected(self):
        for record in (dict(nav("x", "21", 1000), cash_basis="ledger_estimate"),
                       dict(flow(), status="pending"), dict(flow(), flow_type="sweep")):
            with self.assertRaises(ValueError):
                performance_summary([record])

    def test_exact_timestamps_and_total_return_basis_required_for_benchmark(self):
        first, last = nav("start", "21", 1000), nav("end", "23", 1100)
        first["benchmark"] = dict(ticker="SPY", value=100, basis="total_return_index", observed_at=first["observed_at"], source_reference="provider-index")
        last["benchmark"] = dict(first["benchmark"], value=105, observed_at=last["observed_at"])
        self.assertEqual(performance_summary([first, last, review()])["intervals"][0]["benchmark_relative_return_pct"], 5)
        last["benchmark"]["basis"] = "unadjusted_close"
        self.assertIsNone(performance_summary([first, last, review()])["intervals"][0]["benchmark_relative_return_pct"])
        last["benchmark"].update(basis="total_return_index", observed_at=first["observed_at"])
        self.assertIsNone(performance_summary([first, last, review()])["intervals"][0]["benchmark_relative_return_pct"])

    def test_preview_append_dedup_conflict_and_hash_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.local.jsonl"
            record = nav("start", "21", 1000)
            self.assertEqual(record_performance(record, path=path)["status"], "preview_only")
            self.assertFalse(path.exists())
            record_performance(record, path=path, apply=True)
            original = path.read_bytes()
            self.assertEqual(record_performance(record, path=path, apply=True)["status"], "already_recorded")
            self.assertEqual(path.read_bytes(), original)
            for changed in (dict(record, nav=1001, actual_cash=1), dict(record, record_id="duplicate")):
                with self.assertRaises(ValueError):
                    record_performance(changed, path=path, apply=True)
            path.write_text(path.read_text().replace('"nav": 1000', '"nav": 1001'))
            with self.assertRaises(ValueError):
                load_performance_records(path)

    def test_duplicate_deposit_cannot_hide_behind_new_record_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.local.jsonl"
            record_performance(flow(), path=path, apply=True)
            with self.assertRaises(ValueError):
                record_performance(dict(flow(), record_id="new-id"), path=path, apply=True)

    def test_correction_preserves_history_and_invalidates_old_interval(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "observations.local.jsonl"
            for row in (nav("start", "21", 1000), nav("end", "23", 1100), review()):
                record_performance(row, path=path, apply=True)
            correction = dict(nav("corrected-end", "23", 1110), supersedes_record_id="end")
            record_performance(correction, path=path, apply=True)
            rows = load_performance_records(path)
            self.assertEqual(len(rows), 4)
            self.assertIn("missing_or_superseded_nav", performance_summary(rows)["intervals"][0]["blockers"])

    def test_forward_review_and_mixed_nav_basis_blocked(self):
        start, end = nav("start", "21", 1000), nav("end", "23", 1100)
        end["valuation_basis"] = "broker_intraday"
        result = performance_summary([start, end, dict(review(), confirmed_at="2026-09-22T16:00:00-04:00")])
        self.assertEqual(result["status"], "not_ready")
        self.assertIn("inconsistent_nav_basis", result["intervals"][0]["blockers"])
        self.assertIn("interval_review_predates_end_observation", result["intervals"][0]["blockers"])

    def test_late_recovery_not_on_time_and_missing_day_not_erased(self):
        scheduler = {"dates": {
            "2026-09-21": {"refresh_fully_passed": True, "refresh_last_passed_at": "2026-09-21T11:30:00-04:00"},
            "2026-09-23": {"refresh_fully_passed": True, "refresh_last_passed_at": "2026-09-23T15:00:00-04:00", "decision_terminal_reason": "delivery_status_unknown"},
        }}
        result = operational_summary(scheduler, [], [], [], now=datetime.fromisoformat("2026-09-24T12:00:00-04:00"))
        self.assertEqual(result["on_time_cycles"], 1)
        self.assertEqual(result["eventually_ready_cycles"], 2)
        self.assertEqual(result["due_calendar_cycles"], 3)
        self.assertEqual(result["late_cycles"], 1)
        self.assertEqual(result["cycles"][-1]["status"], "not_yet_due")
        self.assertEqual(result["cycles"][1]["status"], "no_observation")
        self.assertEqual(result["cycles"][2]["delivery_terminal_reason"], "delivery_status_unknown")

    def test_earlier_success_is_not_overwritten_by_later_recovery(self):
        scheduler = {"dates": {"2026-09-23": {"refresh_last_passed_at": "2026-09-23T15:00:00-04:00"}}}
        log = [{"cycle_date": "2026-09-23", "component": "daily_refresh", "outcome": "passed", "logged_at": "2026-09-23T12:00:00-04:00"}]
        result = operational_summary(scheduler, log, [], [], now=datetime.fromisoformat("2026-09-23T18:00:00-04:00"))
        self.assertEqual(result["on_time_cycles"], 1)
        self.assertEqual(result["timed_runs"], 0)

    def test_refresh_history_is_durable_idempotent_and_reports_step_timing(self):
        state = dict(cycle_date="2026-09-23", started_at="2026-09-23T12:00:00-04:00", completed_at="2026-09-23T12:02:00-04:00", outcome="passed",
                     steps=[dict(name="market", duration_seconds=110, exit_code=0, diagnostic="untrusted provider text")])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "refresh.local.jsonl"
            self.assertTrue(record_refresh(state, path))
            self.assertFalse(record_refresh(state, path))
            self.assertNotIn("untrusted", path.read_text())
            records = [json.loads(line) for line in path.read_text().splitlines()]
        result = operational_summary({"dates": {"2026-09-23": {}}}, [], [], records, now=datetime.fromisoformat("2026-09-23T18:00:00-04:00"))
        self.assertEqual(result["median_refresh_seconds"], 120)
        self.assertEqual(result["step_timing"]["market"]["median_seconds"], 110)

    def test_multiple_roles_and_horizons_do_not_inflate_observations_or_completed_reviews(self):
        snapshots = [dict(snapshot_id=str(i), ticker="IOT", created_at="2026-09-21T12:00:00-04:00", market_session="2026-09-18", human_confirmation_required="yes", classification="HOLD") for i in range(30)]
        history = [dict(ticker="IOT", market_session=day) for day in ("2026-09-21", "2026-09-22", "2026-09-23")]
        oid = outcomes.observation_id(snapshots[0], "2026-09-22")
        results = [dict(independent_observation_id=oid, horizon_sessions=str(h), primary_observation="yes") for h in (1, 5)]
        summary = outcome_coverage(snapshots, results * 5, history)
        self.assertEqual(summary["unique_origin_observations"], 1)
        self.assertEqual(summary["unique_matured_observations"], 1)
        self.assertEqual(summary["unique_material_instruction_versions"], 1)
        self.assertIsNone(summary["completed_review_meetings"])
        self.assertEqual(summary["horizons"][2]["matured"], 0)

    def test_missing_exchange_session_is_not_compressed_to_one_session(self):
        snapshot = dict(snapshot_id="one", ticker="IOT", created_at="2026-09-21T12:00:00-04:00", market_session="2026-09-18", classification="HOLD")
        history = [dict(ticker="IOT", market_session=day, close=100, price_basis="raw_close") for day in ("2026-09-22", "2026-09-24")]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(outcomes, "jsonl", return_value=[snapshot]), patch.object(outcomes, "OUTCOME_PATH", Path(directory) / "outcomes.csv"):
                self.assertEqual(outcomes.evaluate(history), [])

    def test_expired_instruction_is_reconciliation_not_a_fresh_exit(self):
        for status, action, expected in (("maintained", "hold", "HOLD"), ("maintained", "protect_review", "PROTECTION_REVIEW"), ("expired_pending_verification", "exit_review", "RECONCILE")):
            value = {"held_positions": [{"ticker": "TEST", "action": "maintained_plan_review"}], "plan_continuity": {"plans": [{"ticker": "TEST", "status": status, "action": action}]}}
            row = outcomes.recommendation_rows(value)[0]
            self.assertEqual(row["classification"], expected)
            self.assertEqual(row["plan_status"], status)

    def test_new_candidate_thesis_is_linked_separately_from_held_views(self):
        self.assertEqual(outcomes.linked_record({"views": {}, "candidate_views": {"TEST": {"thesis_id": "company_thesis:TEST", "version": 2}}}, "TEST")["version"], 2)

    def test_plan_and_thesis_versions_linked_without_retroactive_rewrite(self):
        decision = dict(held_positions=[dict(ticker="IOT", action="hold")],
            plan_continuity=dict(plans=[dict(ticker="IOT", plan_id="p", version=2)]),
            long_horizon_research=dict(views={"IOT": dict(maintained_view=dict(thesis_id="t", version=3))}))
        row = outcomes.recommendation_rows(decision)[0]
        self.assertEqual((row["plan_id"], row["plan_version"], row["thesis_id"], row["thesis_version"]), ("p", 2, "t", 3))


if __name__ == "__main__":
    unittest.main()
