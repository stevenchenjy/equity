from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_intraday_prices import moment
from daily_common import ExclusiveFileLock
import swing_observer as observer
import swing_candidate_quotes as quotes


class SwingObserverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.current = moment("2026-10-22T09:45:00-04:00")
        active = self.root / "00_project_control/active_decision_state.yaml"
        active.parent.mkdir(parents=True)
        active.write_text(json.dumps({"current_workflow": "daily_decision", "active_pipeline": "phase5r_daily",
            "broker_connection_allowed": "no", "order_code_allowed": "no", "manual_execution_only": "yes"}))
        inhibit = self.root / "07_automation/scheduler/maintenance_inhibit.local.json"
        inhibit.parent.mkdir(parents=True); inhibit.write_text(json.dumps({"active": False, "allowed_pipeline": "phase5r_daily"}))
        self.lock = self.root / "runtime.lock"

    def tearDown(self):
        self.tmp.cleanup()

    def invoke(self, **kw):
        # The engine itself is exercised in its own full source-admission suite.
        module = types.ModuleType("swing_research_v2")
        module.build = kw.get("builder", Mock(return_value={"status": "experimental_current", "version": "fixture"}))
        module.quote_targets = kw.get("targets", Mock(return_value=[]))
        with patch.dict(sys.modules, swing_research_v2=module):
            return observer.run(self.root, current=self.current, clock=lambda: self.current,
                                runtime_lock=self.lock, **kw)

    def test_premarket_postopen_midday_afterhours_holiday_and_earlyclose_gates(self):
        for stamp, due in (("2026-10-22T08:45:00-04:00", False),
                           ("2026-10-22T09:31:00-04:00", False),
                           ("2026-10-22T09:45:00-04:00", True),
                           ("2026-10-22T10:44:59-04:00", True),
                           ("2026-10-22T10:45:00-04:00", False),
                           ("2026-10-22T12:30:00-04:00", False),
                           ("2026-10-22T14:45:00-04:00", True),
                           ("2026-10-22T15:20:00-04:00", False),
                           ("2026-10-22T20:00:00-04:00", False),
                           ("2026-11-26T09:45:00-05:00", False),
                           ("2026-11-27T14:45:00-05:00", False)):
            self.assertEqual(observer.due_window(moment(stamp)) is not None, due, stamp)

    def test_outside_window_never_imports_engine_collects_or_writes(self):
        self.current = moment("2026-10-22T12:30:00-04:00")
        collector = Mock(side_effect=AssertionError("no request"))
        result = self.invoke(collector=collector)
        collector.assert_not_called()
        self.assertEqual(result["status"], "outside_review_window")
        self.assertFalse((self.root / quotes.CURRENT).exists())

    def test_no_opportunity_captures_truthfully_without_request_or_research_slot(self):
        collector = Mock()
        value = self.invoke(collector=collector)
        collector.assert_not_called()
        self.assertEqual(value["status"], "no_candidates")
        self.assertFalse(value["network_attempted"])
        self.assertFalse(value["research_slot_consumed"])
        self.assertFalse(value["fully_passed_research"])
        self.assertFalse(value["email_sent"])
        self.assertFalse(value["trade_placed"])

    def test_active_claim_defers_without_taking_or_modifying_claim(self):
        p = self.root / "00_project_control/run_logs/short_assessment.local.json"
        p.parent.mkdir(exist_ok=True)
        raw = json.dumps({"slots": {"a": {"status": "claimed", "claim_id": "owner", "expires_at": "2026-10-22T09:50:00-04:00"}}})
        p.write_text(raw)
        result = self.invoke()
        self.assertEqual(result["status"], "deferred_active_short_claim")
        self.assertEqual(p.read_text(), raw)
        self.assertFalse((self.root / quotes.CURRENT).exists())

    def test_runtime_and_pipeline_locks_are_nonblocking(self):
        for lock in (self.lock, self.root / "00_project_control/run_logs/daily_pipeline.lock"):
            with ExclusiveFileLock(lock):
                value = self.invoke()
                self.assertEqual(value["status"], "deferred_mutation_lock")
            self.assertFalse((self.root / quotes.CURRENT).exists())

    def test_first_capture_precedes_quote_and_immutable_window_capture(self):
        calls = []
        def build(root, **kw):
            calls.append(("capture", kw.get("candidate_quote_context")))
            return {"status": "experimental_current", "version": "fixture"}
        def collect(root, **kw):
            calls.append(("quote", kw["claim_id"]))
            return {"status": "current", "source": {"sha256": "fixture"}, "request_count": 1}
        value = self.invoke(builder=build, targets=lambda *a, **k: ["MSFT"], collector=collect)
        self.assertEqual([c[0] for c in calls], ["capture", "quote", "capture"])
        self.assertIsNone(calls[0][1])
        self.assertEqual(value["status"], "observed")
        self.assertTrue(value["network_attempted"])
        self.assertFalse(value["analysis_completed"])

    def test_failed_refresh_fences_previous_quote_and_retains_failed_receipt(self):
        def broken(*a, **k):raise ValueError("admitted history unavailable")
        value = self.invoke(builder=broken)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["failure"], "admitted history unavailable")
        pointer = json.loads((self.root / quotes.CURRENT).read_bytes())
        snap = quotes._source(self.root, pointer["source"])
        self.assertEqual(snap["rows"], {})
        self.assertIn("history unavailable", snap["failures"]["__attempt__"])
        self.assertEqual(len(list((self.root / observer.REL / "receipts").glob("*.json"))), 1)

    def test_maintenance_inhibit_or_open_execution_boundary_prevents_collection(self):
        p = self.root / "07_automation/scheduler/maintenance_inhibit.local.json"
        p.write_text(json.dumps({"active": True, "allowed_pipeline": "none"}))
        with self.assertRaisesRegex(ValueError, "maintenance_inhibit"):
            self.invoke()
        self.assertFalse((self.root / quotes.CURRENT).exists())

    def test_missing_history_is_not_reported_as_a_completed_no_opportunity_screen(self):
        collector = Mock()
        value = self.invoke(builder=lambda *a, **k: {"status": "waiting_on_data", "blockers": ["current_history_missing"]},
                            collector=collector)
        collector.assert_not_called()
        self.assertEqual(value["status"], "waiting_on_data")
        self.assertEqual(value["failure"], "current_history_missing")
        self.assertFalse(value["analysis_completed"])


if __name__ == "__main__":unittest.main()
