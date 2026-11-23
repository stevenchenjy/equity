"""Small fixtures for deferring only the coordinated derived attention view."""
from __future__ import annotations

import copy
from contextlib import contextmanager, nullcontext, redirect_stdout
from datetime import timedelta
import io
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_csv, atomic_write_json, read_csv, read_json
import research_backlog as backlog
import research_opportunities as opportunities
import run_daily_refresh as refresh
import create_research_opportunities as opportunity_cli
from opportunity_contract import MARKDOWN_REL, REPORT_REL, STORE_REL
import test_objective_transition_batch as objective_fixtures
import test_research_backlog as backlog_fixtures

CURRENT = objective_fixtures.CURRENT
NOW = backlog_fixtures.NOW
FUNDAMENTAL_FIELDS = backlog_fixtures.FUNDAMENTAL_FIELDS


class CoordinatedAttentionObjectiveTests(unittest.TestCase):
    def test_default_keeps_immediate_view_and_deferral_keeps_identical_work_and_outputs(self):
        fixture = objective_fixtures.ObjectiveTransitionBatchTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.setup_store([("AONE", "queued", "blocked", 0)])
        with tempfile.TemporaryDirectory() as directory:
            deferred_root = Path(directory) / "deferred"
            shutil.copytree(fixture.root, deferred_root)
            outputs = []
            for root, defer in ((fixture.root, False), (deferred_root, True)):
                with patch.object(opportunities, "objective_research", return_value=(None, "fixture_missing")) as work, \
                        patch("capital_escalation.research_priorities", return_value=["AONE"]), \
                        patch.object(backlog, "refresh_attention_view") as immediate, \
                        patch.object(backlog, "validate_attention_view_base") as preflight, \
                        patch("research_opportunities.time.monotonic", return_value=100):
                    kwargs = {"defer_attention_view": True} if defer else {}
                    result = opportunities.objective(root, current=CURRENT,
                        clock=lambda: CURRENT + timedelta(seconds=1), **kwargs)
                self.assertEqual(work.call_count, 1)
                self.assertEqual(immediate.call_count, 0 if defer else 1)
                self.assertEqual(preflight.call_count, 1 if defer else 0)
                self.assertEqual(result["metrics"]["shared_objective_work_budget"], 10)
                self.assertEqual(result["metrics"]["network_requests"], 0)
                self.assertEqual(result["metrics"]["canonical_fields_admitted"], 0)
                outputs.append(result)
            self.assertEqual(outputs[0], outputs[1])
            for relative in (STORE_REL, REPORT_REL, MARKDOWN_REL):
                self.assertEqual((fixture.root / relative).read_bytes(),
                                 (deferred_root / relative).read_bytes())


class CoordinatedAttentionBacklogTests(unittest.TestCase):
    def setUp(self):
        self.fixture = backlog_fixtures.ResearchBacklogTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.original = self.fixture.execute(max_tickers=1)

    def publication_bytes(self):
        return {(str(path.relative_to(self.root))): path.read_bytes()
                for path in self.root.rglob("*") if path.is_file()
                and path.suffix not in {".lock"}}

    def test_deferred_preflight_rejects_corrupt_history_or_replaced_fundamentals(self):
        baseline = self.publication_bytes()
        backlog.validate_attention_view_base(self.root)
        self.assertEqual(self.publication_bytes(), baseline)
        for kind in ("history", "fundamentals", "report"):
            with self.subTest(kind=kind):
                for name, raw in baseline.items():
                    (self.root / name).write_bytes(raw)
                if kind == "history":
                    path = self.root / backlog.HISTORY_REL
                    path.write_bytes(path.read_bytes().replace(b'"record_hash":', b'"invalid_hash":', 1))
                elif kind == "fundamentals":
                    path = self.root / backlog.FUNDAMENTALS_REL
                    path.write_bytes(path.read_bytes() + b"\n")
                else:
                    report = read_json(self.root / backlog.REPORT_REL)
                    report["selected_tickers"] = ["STALE"]
                    atomic_write_json(self.root / backlog.REPORT_REL, report)
                before = self.publication_bytes()
                with self.assertRaises(ValueError):
                    backlog.validate_attention_view_base(self.root)
                self.assertEqual(self.publication_bytes(), before)

    def test_strict_final_view_binds_attention_and_keeps_original_work_and_history(self):
        original_report_bytes = (self.root / backlog.REPORT_REL).read_bytes()
        original_history = (self.root / backlog.HISTORY_REL).read_bytes()
        dossier = (self.root / backlog.DOSSIER_REL / "ABC.json").read_bytes()
        changed = read_csv(self.root / backlog.FUNDAMENTALS_REL)
        changed[0]["debt_latest"] = "50.00"
        atomic_write_csv(self.root / backlog.FUNDAMENTALS_REL, FUNDAMENTAL_FIELDS, changed)
        fundamentals = (self.root / backlog.FUNDAMENTALS_REL).read_bytes()
        attention_hash = "a" * 64
        with patch.object(opportunities, "read_report", return_value={"report_hash": attention_hash, "opportunities": []}) as read_attention, \
                patch.object(backlog, "attention_rows", side_effect=AssertionError("strict coordinated validation required")), \
                patch.object(backlog, "complete_objective_data", side_effect=AssertionError("no second objective allowance")):
            final = backlog.recompose_final_view(self.root, NOW + timedelta(minutes=1),
                                                 attention_report_hash=attention_hash)
        read_attention.assert_called_once_with(self.root, current=NOW + timedelta(minutes=1))
        self.assertEqual(final["attention_report_hash"], attention_hash)
        for field in ("selected_tickers", "attempts_latest_run", "work_budget_tickers", "network_requests",
                      "financial_fields_completed", "canonical_numeric_updates", "objective_dossiers_completed"):
            self.assertEqual(final[field], self.original[field])
        self.assertEqual((self.root / backlog.FUNDAMENTALS_REL).read_bytes(), fundamentals)
        self.assertEqual((self.root / backlog.DOSSIER_REL / "ABC.json").read_bytes(), dossier)
        self.assertTrue((self.root / backlog.HISTORY_REL).read_bytes().startswith(original_history))
        self.assertEqual((self.root / backlog.DOSSIER_REL / "view_history" /
                          (self.original["report_hash"] + ".json")).read_bytes(), original_report_bytes)
        event = backlog._history(self.root / backlog.HISTORY_REL)[-1]
        self.assertEqual(event["attention_report_hash"], attention_hash)
        self.assertEqual(event["objective_attempt_count"], 0)
        backlog.validate_report(final, root=self.root, current=NOW + timedelta(minutes=2))

    def test_strict_final_view_never_swallows_attention_hash_or_source_failure(self):
        baseline = self.publication_bytes()
        cases = (({"report_hash": "b" * 64, "opportunities": []}, None, "attention_report_changed"),
                 (None, ValueError("research_source_changed"), "research_source_changed"))
        for value, error, reason in cases:
            with self.subTest(reason=reason):
                with patch.object(opportunities, "read_report", return_value=value, side_effect=error), \
                        patch.object(backlog, "attention_rows", side_effect=AssertionError("no optional fallback")):
                    with self.assertRaisesRegex(ValueError, reason):
                        backlog.recompose_final_view(self.root, NOW + timedelta(minutes=1),
                                                     attention_report_hash="a" * 64)
                self.assertEqual(self.publication_bytes(), baseline)
        for digest in ("", "A" * 64, "a" * 63, 1):
            with self.subTest(invalid_digest=digest):
                with self.assertRaisesRegex(ValueError, "attention_report_hash_invalid"):
                    backlog.recompose_final_view(self.root, NOW, attention_report_hash=digest)
                self.assertEqual(self.publication_bytes(), baseline)


class CoordinatedAttentionParentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = backlog_fixtures.ResearchBacklogTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.fixture.execute(max_tickers=1)
        self.digest = "a" * 64
        self.current = NOW + timedelta(seconds=7)
        with patch.object(opportunities, "read_report", return_value={
                "report_hash": self.digest, "opportunities": []}):
            final = backlog.recompose_final_view(self.root, NOW + timedelta(seconds=5),
                                                 attention_report_hash=self.digest)
        self.objective = {"name": "research_opportunity_objective", "exit_code": 0,
            "started_at": (NOW + timedelta(seconds=1)).isoformat(),
            "completed_at": (NOW + timedelta(seconds=3)).isoformat(),
            "attention_view_deferral_requested": True, "attention_view_deferred": True,
            "attention_report_hash": self.digest,
            "attention_deferral_completed_at": (NOW + timedelta(seconds=2)).isoformat()}
        self.view = {"name": "research_backlog_view", "exit_code": 0,
            "started_at": (NOW + timedelta(seconds=4)).isoformat(),
            "completed_at": (NOW + timedelta(seconds=6)).isoformat(),
            "backlog_view_report_hash": final["report_hash"]}
        self.progress = {"started_at": NOW.isoformat(), "steps": [self.objective, self.view]}
        self.objective_marker_path = self.root / "04_research/company_research/opportunities.local/last_objective_run.json"
        self.view_marker_path = self.root / "08_reviews/research_backlog.local/last_view_run.json"
        self.objective_marker = {"stage": "objective", **{key: value for key, value in self.objective.items()
            if key not in {"name", "attention_view_deferral_requested"}}}
        self.view_marker = {"schema_version": "equity_research_backlog_run_v1",
            **{key: self.view[key] for key in ("started_at", "completed_at", "exit_code")},
            "report_hash": final["report_hash"]}
        atomic_write_json(self.objective_marker_path, self.objective_marker)
        atomic_write_json(self.view_marker_path, self.view_marker)
        self.baseline = {str(path.relative_to(self.root)): path.read_bytes()
                         for path in self.root.rglob("*") if path.is_file() and path.suffix != ".lock"}

    def restore(self):
        for name, raw in self.baseline.items():
            (self.root / name).write_bytes(raw)
        return copy.deepcopy(self.progress)

    def bind_changed_report(self, progress, **changes):
        report = read_json(self.root / backlog.REPORT_REL)
        report.update(changes)
        from daily_common import canonical_sha256
        report["report_hash"] = canonical_sha256({key: value for key, value in report.items() if key != "report_hash"})
        atomic_write_json(self.root / backlog.REPORT_REL, report)
        progress["steps"][-1]["backlog_view_report_hash"] = report["report_hash"]
        atomic_write_json(self.view_marker_path, {**self.view_marker, "report_hash": report["report_hash"]})

    def test_final_gate_accepts_only_matching_same_run_success(self):
        with patch.object(refresh, "ROOT", self.root):
            self.assertEqual(refresh._attention_deferral(self.progress), self.objective)
            refresh._require_final_attention_view(self.progress, self.current)
            self.assertIsNone(refresh._attention_deferral(None))
            refresh._require_final_attention_view({"started_at": NOW.isoformat(), "steps": []}, self.current)
            for fault in ("failed_objective", "old_objective_marker", "marker_hash", "run_started_after_objective"):
                with self.subTest(fault=fault):
                    progress = self.restore()
                    if fault == "failed_objective":
                        progress["steps"][0]["exit_code"] = 124
                    elif fault == "old_objective_marker":
                        atomic_write_json(self.objective_marker_path, {**self.objective_marker,
                            "started_at": (NOW - timedelta(days=1)).isoformat()})
                    elif fault == "marker_hash":
                        atomic_write_json(self.objective_marker_path, {**self.objective_marker,
                            "attention_report_hash": "b" * 64})
                    else:
                        progress["started_at"] = (NOW + timedelta(seconds=2)).isoformat()
                    with self.assertRaisesRegex(ValueError, "deferral_unverified"):
                        refresh._attention_deferral(progress)

    def test_final_gate_rejects_skipped_failed_old_or_changed_publications(self):
        faults = ("failed_view", "skipped_view", "missing_view", "old_success_marker", "view_hash",
                  "attention_hash", "stale_view_time", "future_view_time", "fundamentals", "history")
        with patch.object(refresh, "ROOT", self.root):
            for fault in faults:
                with self.subTest(fault=fault):
                    progress = self.restore()
                    if fault in {"failed_view", "skipped_view"}:
                        progress["steps"][-1]["exit_code"] = 1 if fault == "failed_view" else 124
                    elif fault == "missing_view":
                        progress["steps"].pop()
                    elif fault == "old_success_marker":
                        atomic_write_json(self.view_marker_path, {**self.view_marker,
                            "started_at": (NOW - timedelta(days=1)).isoformat()})
                    elif fault == "view_hash":
                        progress["steps"][-1]["backlog_view_report_hash"] = "b" * 64
                    elif fault == "attention_hash":
                        self.bind_changed_report(progress, attention_report_hash="b" * 64)
                    elif fault in {"stale_view_time", "future_view_time"}:
                        seconds = 2 if fault == "stale_view_time" else 8
                        self.bind_changed_report(progress, view_recomposed_at=(NOW + timedelta(seconds=seconds)).isoformat())
                    else:
                        path = self.root / (backlog.FUNDAMENTALS_REL if fault == "fundamentals" else backlog.HISTORY_REL)
                        path.write_bytes(path.read_bytes() + (b"\n" if fault == "fundamentals" else b"{}\n"))
                    with self.assertRaises(ValueError):
                        refresh._require_final_attention_view(progress, self.current)

    def test_unfulfilled_final_gate_prevents_composer_spawn(self):
        progress = copy.deepcopy(self.progress)
        progress["steps"][-1]["exit_code"] = 124
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh, "now_et", return_value=self.current), \
                patch.object(refresh, "run_step") as child:
            result = refresh._progress_step(progress, ("daily_decision", "create_daily_decision_and_brief.py", False),
                                            refresh.MARKET_SNAPSHOT_REUSE)
        child.assert_not_called()
        self.assertEqual(result["exit_code"], 1)
        self.assertEqual(result["result_code"], "coordinated_attention_view_unfulfilled")

    def test_parent_admission_cannot_turn_an_old_child_success_into_current_proof(self):
        # A zero-returning child must not reuse a completion marker left by an
        # earlier run. The parent still records its actual outcome and times.
        with patch.object(refresh, "ROOT", self.root):
            child = {"stage": "objective", "exit_code": 0, "attention_view_deferred": True,
                "report_hash": self.digest, "attention_report_hash": self.digest,
                "started_at": (NOW - timedelta(days=1)).isoformat(),
                "completed_at": (NOW - timedelta(days=1) + timedelta(seconds=1)).isoformat()}
            atomic_write_json(self.objective_marker_path, child)
            result = refresh._record_work_step({"name": "research_opportunity_objective", "exit_code": 0,
                "started_at": self.objective["started_at"], "completed_at": self.objective["completed_at"],
                "attention_view_deferral_requested": True})
            self.assertEqual(result["exit_code"], 1)
            self.assertEqual(result["result_code"], "coordinated_attention_deferral_unverified")
            self.assertEqual(read_json(self.objective_marker_path)["exit_code"], 1)
            progress = self.restore()
            # Final-view admission must also reject an old successful child
            # marker before restamping it with this invocation's parent times.
            later_start = NOW + timedelta(seconds=10)
            admitted = refresh._record_work_step({"name": "research_backlog_view", "exit_code": 0,
                "started_at": later_start.isoformat(),
                "completed_at": (later_start + timedelta(seconds=1)).isoformat(),
                "attention_report_hash_required": self.digest})
            self.assertEqual(admitted["exit_code"], 1)
            self.assertNotIn("backlog_view_report_hash", admitted)
            progress["steps"][-1] = admitted
            with self.assertRaisesRegex(ValueError, "final_view_unfulfilled"):
                refresh._require_final_attention_view(progress, later_start + timedelta(seconds=2))

    def test_full_account_retry_never_repeats_objective_or_increases_allowances(self):
        specs = [(name, name + ".py", False) for name in ("research_opportunity_objective",
                 "earnings_incorporation", "research_backlog_view", "daily_decision")]
        calls, guards = [], []
        def step(progress, spec, mode, **kwargs):
            calls.append((spec[0], kwargs["defer_attention_view"]))
            return {"name": spec[0], "exit_code": 0}
        @contextmanager
        def guard(*args):
            guards.append(True)
            yield
            if len(guards) == 1:
                raise ValueError("account_inputs_changed_recompose_required")
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh, "STEP_SPECS", specs), \
                patch.object(refresh, "_progress_step", side_effect=step), \
                patch.object(refresh, "research_context", return_value=nullcontext("account-version")), \
                patch.object(refresh, "publication_guard", side_effect=guard), patch.object(refresh, "atomic_write_json"):
            _, retries, success = refresh.consistent_steps(refresh.MARKET_SNAPSHOT_REUSE,
                progress={"started_at": NOW.isoformat(), "steps": []})
        self.assertTrue(success)
        self.assertEqual(len(retries), 1)
        self.assertEqual([entry for entry in calls if entry[0] == "research_opportunity_objective"],
                         [("research_opportunity_objective", True)])
        self.assertEqual([entry for entry in calls if entry[0] == "research_backlog_view"],
                         [("research_backlog_view", False)] * 2)
        self.assertEqual(refresh.DEFAULT_CHILD_TIMEOUT_SECONDS, 240)
        self.assertEqual(refresh.FULL_REFRESH_MAX_SECONDS, 1020)


class CoordinatedAttentionRoutingTests(unittest.TestCase):
    def test_same_second_precise_parent_windows_admit_only_current_ordered_child_markers(self):
        parent_start = NOW.replace(microsecond=100000)
        parent_end = NOW.replace(microsecond=900000)
        child_start = NOW.replace(microsecond=200000)
        child_end = NOW.replace(microsecond=800000)
        digest = "a" * 64
        for name in ("research_opportunity_objective", "research_backlog_view"):
            for case in ("valid", "future", "regression", "old_success"):
                with self.subTest(stage=name, case=case), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    marker_path = root / ("04_research/company_research/opportunities.local/last_objective_run.json"
                        if name == "research_opportunity_objective" else "08_reviews/research_backlog.local/last_view_run.json")
                    start, end = child_start, child_end
                    if case == "future":
                        end = parent_end + timedelta(microseconds=1)
                    elif case == "regression":
                        start, end = child_end, child_start
                    elif case == "old_success":
                        start, end = child_start - timedelta(days=1), child_end - timedelta(days=1)
                    def child(*args, **kwargs):
                        marker = {"started_at": start.isoformat(), "completed_at": end.isoformat(),
                                  "exit_code": 0, "report_hash": digest}
                        if name == "research_opportunity_objective":
                            marker.update(stage="objective", attention_view_deferred=True,
                                          attention_report_hash=digest)
                        else:
                            marker["schema_version"] = "equity_research_backlog_run_v1"
                        atomic_write_json(marker_path, marker)
                        return SimpleNamespace(returncode=0)
                    with patch.object(refresh, "ROOT", root), \
                            patch.object(refresh, "iso_now", return_value=NOW.replace(microsecond=0).isoformat()), \
                            patch.object(refresh, "now_et", side_effect=[parent_start, parent_end]), \
                            patch("decision_dependencies.observe", return_value={}), \
                            patch("decision_dependencies.record_attempt"), \
                            patch.object(refresh, "run_stage", side_effect=child):
                        result = refresh.run_step(name, "fixture.py", True,
                            market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE,
                            defer_attention_view=name == "research_opportunity_objective",
                            attention_report_hash=digest if name == "research_backlog_view" else None)
                    self.assertEqual(result["started_at"], parent_start.isoformat())
                    self.assertEqual(result["completed_at"], parent_end.isoformat())
                    self.assertEqual(result["exit_code"], 0 if case == "valid" else 1)
                    if case == "valid":
                        field = "attention_report_hash" if name == "research_opportunity_objective" else "backlog_view_report_hash"
                        self.assertEqual(result[field], digest)
                    else:
                        self.assertNotIn("attention_view_deferred", result)
                        self.assertNotIn("backlog_view_report_hash", result)
                    self.assertEqual(read_json(marker_path)["exit_code"], result["exit_code"])

    def test_cli_records_deferral_only_after_success_and_default_stays_immediate(self):
        report = {"report_hash": "a" * 64, "metrics": {"research_queue_size": 1, "network_requests": 0}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker_path = root / opportunity_cli.BASE_REL / "last_objective_run.json"
            for defer in (False, True):
                with patch.object(opportunity_cli, "objective", return_value=report) as work, \
                        patch.object(opportunity_cli, "now_et", return_value=NOW), redirect_stdout(io.StringIO()):
                    self.assertEqual(opportunity_cli.run_stage(root, "objective", defer_attention_view=defer), 0)
                self.assertEqual(work.call_args.kwargs["defer_attention_view"], defer)
                marker = read_json(marker_path)
                self.assertEqual(marker.get("attention_view_deferred"), True if defer else None)
            with patch.object(opportunity_cli, "objective", side_effect=ValueError("preflight changed")), \
                    patch.object(opportunity_cli, "now_et", return_value=NOW), redirect_stdout(io.StringIO()):
                self.assertEqual(opportunity_cli.run_stage(root, "objective", defer_attention_view=True), 1)
            failed = read_json(marker_path)
            self.assertEqual(failed["exit_code"], 1)
            self.assertNotIn("attention_view_deferred", failed)
            with self.assertRaisesRegex(ValueError, "requires_objective_stage"):
                opportunity_cli.run_stage(root, "intake", defer_attention_view=True)

    def test_runner_routes_flags_only_to_their_bound_stage_with_default_unchanged(self):
        with patch("decision_dependencies.observe", return_value={}), \
                patch.object(refresh, "_record_work_step", side_effect=lambda result: result), \
                patch.object(refresh, "run_stage", return_value=SimpleNamespace(returncode=0)) as child:
            default = refresh.run_step("research_opportunity_objective", "objective.py", True,
                market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE)
            self.assertNotIn("--defer-attention-view", child.call_args.args[0])
            self.assertNotIn("attention_view_deferral_requested", default)
            deferred = refresh.run_step("research_opportunity_objective", "objective.py", True,
                market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE, defer_attention_view=True)
            self.assertIn("--defer-attention-view", child.call_args.args[0])
            self.assertIs(deferred["attention_view_deferral_requested"], True)
            refresh.run_step("research_backlog_view", "backlog.py", True,
                market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE, attention_report_hash="a" * 64)
            self.assertEqual(child.call_args.args[0][-3:], ["--recompose-only", "--attention-report-hash", "a" * 64])
            self.assertEqual(child.call_args.kwargs["timeout"], 240)
        with self.assertRaisesRegex(ValueError, "requires_objective_step"):
            refresh.run_step("research_opportunity_intake", "intake.py", True, defer_attention_view=True)
        with self.assertRaisesRegex(ValueError, "requires_final_view_step"):
            refresh.run_step("daily_decision", "decision.py", False, attention_report_hash="a" * 64)


if __name__ == "__main__":
    unittest.main()
