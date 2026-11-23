"""Unstarted advisory work cannot consume the remaining required-tail time."""
from __future__ import annotations

from contextlib import contextmanager, nullcontext, redirect_stdout
from datetime import datetime
import io
from itertools import chain, repeat
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ET, read_json
import run_daily_refresh as refresh

NOW = datetime(2026, 11, 23, 4, 50, tzinfo=ET)
CAPITAL = ("capital_deployment_escalation", "run_capital_escalation.py", True)


class AdvisoryTailPriorityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def progress(self):
        return {"started_at": NOW.isoformat(), "steps": []}

    def passed(self, name, script, allowed, **kwargs):
        return {"name": name, "script": script, "allowed_to_fail": allowed,
                "started_at": NOW.isoformat(), "completed_at": NOW.isoformat(),
                "duration_seconds": 0, "exit_code": 0, "outcome": "passed", "result_code": "fixture_child_completed"}

    def test_insufficient_advisory_budget_skips_before_any_dependency_or_source_work(self):
        capital_source = self.root / "capital-evidence.json"
        capital_source.write_bytes(b'{"retained":"unchanged"}\n')
        progress = self.progress()
        with patch.object(refresh, "ROOT", self.root), \
                patch.object(refresh.time, "monotonic", return_value=1000), \
                patch.object(refresh, "run_step", side_effect=AssertionError("unstarted advisory child")) as child, \
                patch.object(refresh, "_record_work_step", side_effect=AssertionError("unstarted work receipt")) as record, \
                patch("decision_dependencies.observe", side_effect=AssertionError("unstarted dependency read")) as observe, \
                patch("decision_dependencies.record_attempt", side_effect=AssertionError("unstarted source write")) as attempt:
            result = refresh._progress_step(progress, CAPITAL, refresh.MARKET_SNAPSHOT_REUSE, deadline=1186)
        for call in (child, record, observe, attempt):
            call.assert_not_called()
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["outcome"], "not_run_insufficient_complete_stage_budget")
        self.assertEqual(result["result_code"], "advisory_complete_stage_budget_unavailable")
        self.assertEqual(result["remaining_budget_seconds"], 186)
        self.assertEqual(result["stage_budget_seconds"], 900)
        self.assertEqual(result["required_tail_reserve_seconds"], 120)
        self.assertIs(result["allowed_to_fail"], True)
        self.assertEqual(progress["steps"], [result])
        self.assertEqual(read_json(self.root / refresh.PROGRESS_REL)["steps"], [result])
        self.assertEqual(capital_source.read_bytes(), b'{"retained":"unchanged"}\n')
        self.assertEqual({p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()},
                         {"capital-evidence.json", refresh.PROGRESS_REL})

    def test_exact_complete_budget_boundary_permits_and_just_below_does_not(self):
        threshold = refresh.CAPITAL_ESCALATION_TIMEOUT_SECONDS + refresh.CAPITAL_REQUIRED_TAIL_RESERVE_SECONDS
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh.time, "monotonic", return_value=1000), \
                patch.object(refresh, "run_step", side_effect=self.passed) as child:
            below = refresh._progress_step(None, CAPITAL, refresh.MARKET_SNAPSHOT_REUSE,
                                           deadline=1000 + threshold - .000001)
            child.assert_not_called()
            self.assertEqual(below["exit_code"], 124)
            exact = refresh._progress_step(None, CAPITAL, refresh.MARKET_SNAPSHOT_REUSE,
                                           deadline=1000 + threshold)
        self.assertEqual(exact["exit_code"], 0)
        self.assertEqual(child.call_count, 1)
        self.assertEqual(child.call_args.kwargs["maximum_child_seconds"], threshold)

    def test_no_deadline_and_required_or_other_stages_keep_existing_behavior(self):
        specs = [(CAPITAL, None), ((CAPITAL[0], CAPITAL[1], False), 1010),
                 (("outcome_tracking", "track_recommendation_outcomes.py", False), 1010)]
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh.time, "monotonic", return_value=1000), \
                patch.object(refresh, "run_step", side_effect=self.passed) as child:
            for spec, deadline in specs:
                with self.subTest(spec=spec, deadline=deadline):
                    result = refresh._progress_step(None, spec, refresh.MARKET_SNAPSHOT_REUSE, deadline=deadline)
                    self.assertEqual(result["exit_code"], 0)
            with patch.object(refresh, "ADVISORY_STEPS", set()):
                result = refresh._progress_step(None, CAPITAL, refresh.MARKET_SNAPSHOT_REUSE, deadline=1010)
                self.assertEqual(result["exit_code"], 0)
        self.assertEqual(child.call_count, 4)
        self.assertIsNone(child.call_args_list[0].kwargs["maximum_child_seconds"])

    def test_exhausted_deadline_retains_original_budget_failure(self):
        with patch.object(refresh.time, "monotonic", return_value=1000), patch.object(refresh, "run_step") as child:
            result = refresh._progress_step(None, CAPITAL, refresh.MARKET_SNAPSHOT_REUSE, deadline=1000)
        child.assert_not_called()
        self.assertEqual(result["exit_code"], 124)
        self.assertEqual(result["outcome"], "not_run_budget_exhausted")
        self.assertEqual(result["result_code"], "full_refresh_total_budget_exhausted")

    def test_account_retry_keeps_same_deadline_and_required_tail_is_still_attempted(self):
        specs = [("earnings_incorporation", "incorporate.py", False), CAPITAL,
                 ("outcome_tracking", "outcomes.py", False)]
        guards, calls = [], []
        @contextmanager
        def guard(*args):
            guards.append(True)
            yield
            if len(guards) == 1:
                raise ValueError("account_inputs_changed_recompose_required")
        def child(name, script, allowed, **kwargs):
            calls.append((name, kwargs["maximum_child_seconds"]))
            return self.passed(name, script, allowed, **kwargs)
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh, "STEP_SPECS", specs), \
                patch.object(refresh.time, "monotonic", return_value=1000), \
                patch.object(refresh, "research_context", side_effect=lambda root: nullcontext("account-version")), \
                patch.object(refresh, "publication_guard", side_effect=guard), patch.object(refresh, "run_step", side_effect=child):
            steps, retries, current = refresh.consistent_steps(refresh.MARKET_SNAPSHOT_REUSE,
                progress=self.progress(), deadline=1186)
        self.assertTrue(current)
        self.assertEqual(len(retries), 1)
        self.assertEqual(calls, [("earnings_incorporation", 186), ("outcome_tracking", 186)] * 2)
        self.assertEqual(next(r for r in steps if r["name"] == CAPITAL[0])["exit_code"], 124)
        self.assertEqual(next(r for r in retries[0]["steps"] if r["name"] == CAPITAL[0])["exit_code"], 124)

    def test_full_outcome_retains_advisory_failure_and_requires_every_tail_result(self):
        specs = [("earnings_incorporation", "incorporate.py", False),
                 ("daily_decision", "decision.py", False), CAPITAL,
                 ("outcome_tracking", "outcomes.py", False),
                 ("workflow_evaluation", "workflow.py", False),
                 ("capital_allocation_validation", "allocation.py", False),
                 ("evidence_packet", "packet.py", False)]
        for failed_tail in (None, "capital_allocation_validation"):
            with self.subTest(failed_tail=failed_tail):
                calls = []
                def child(name, script, allowed, **kwargs):
                    calls.append(name)
                    result = self.passed(name, script, allowed, **kwargs)
                    if name == failed_tail:
                        result.update(exit_code=1, outcome="failed", result_code="fixture_required_failure")
                    return result
                with patch.object(refresh, "ROOT", self.root), patch.object(refresh, "STEP_SPECS", specs), \
                        patch.object(refresh, "DAILY_REFRESH_STATE_PATH", self.root / "state.json"), \
                        patch.object(refresh, "load_active_state"), patch.object(refresh, "load_inhibit"), \
                        patch.object(refresh, "cycle_date", return_value=NOW.date().isoformat()), \
                        patch.object(refresh, "now_et", return_value=NOW), \
                        patch.object(refresh, "iso_now", return_value=NOW.isoformat()), \
                        patch.object(refresh, "latest_published_market_session", return_value=NOW.date()), \
                        patch.object(refresh.time, "monotonic", side_effect=chain([0], repeat(1000))), \
                        patch.object(refresh, "research_context", side_effect=lambda root: nullcontext("account-version")), \
                        patch.object(refresh, "publication_guard", side_effect=lambda *args: nullcontext()), \
                        patch.object(refresh, "snapshot_active_portfolio"), patch.object(refresh, "run_step", side_effect=child), \
                        patch("workflow_evaluation.record_refresh"), patch.object(refresh, "log_daily_run"), redirect_stdout(io.StringIO()):
                    code = refresh.run_refresh(True, refresh.MARKET_SNAPSHOT_REUSE)
                state = read_json(self.root / "state.json")
                self.assertEqual(code, 0 if failed_tail is None else 1)
                self.assertEqual(state["outcome"], "passed" if failed_tail is None else "degraded_decision_created")
                self.assertEqual(state["advisory_failures"], [CAPITAL[0]])
                self.assertEqual(state["hard_failures"], [] if failed_tail is None else [failed_tail])
                capital = next(row for row in state["steps"] if row["name"] == CAPITAL[0])
                self.assertEqual(capital["exit_code"], 124)
                self.assertEqual(capital["result_code"], "advisory_complete_stage_budget_unavailable")
                self.assertNotIn(CAPITAL[0], calls)
                self.assertTrue(all(name in calls for name, _, _ in specs if name != CAPITAL[0]))
                self.assertTrue(state["account_publication_current"])
                self.assertFalse(state["email_attempted"])


if __name__ == "__main__":
    unittest.main()
