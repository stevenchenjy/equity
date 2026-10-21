import copy
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from server import earnings_event_view


class EarningsEventViewTests(unittest.TestCase):
    def test_current_capital_is_required_for_event_eligibility_and_input_is_not_mutated(self):
        retained = {"schema_version": "equity_earnings_event_view_v1", "status": "ready", "events": [
            {"ticker": "LOWM", "status": "eligible_conditional_plan", "timing": "pre_event", "blockers": [], "next_step": "See current draft"}]}
        before = copy.deepcopy(retained)
        summary = Mock(return_value=retained)
        capital = {"decisions": [{"ticker": "LOWM", "decision": "ACTIONABLE_BUY", "shares": 1, "order_draft": {"side": "buy"}}]}
        with patch.dict(sys.modules, {"earnings_events": SimpleNamespace(summary=summary)}):
            current = earnings_event_view(Path("/isolated"), datetime.fromisoformat("2026-10-21T09:00:00-04:00"),
                                          capital=capital, current_contract=True)
            self.assertEqual(current["events"][0]["status"], "eligible_conditional_plan")
            busy = earnings_event_view(Path("/isolated"), datetime.fromisoformat("2026-10-21T09:00:00-04:00"),
                                       capital=capital, current_contract=False)
            self.assertIsNone(summary.call_args.kwargs["capital"])
            self.assertEqual(busy["events"][0]["status"], "research_in_progress")
            self.assertIn("current_conditional_plan_unverified", busy["events"][0]["blockers"])
            self.assertFalse(busy["capital_authority"])
            self.assertFalse(busy["automatic_action_allowed"])
        self.assertEqual(retained, before)

    def test_unverified_or_elapsed_report_cannot_reuse_an_eligible_label(self):
        for report_status, timing in (("stale", "pre_event"), ("ready", "post_event"), ("partial", "pre_event")):
            summary = Mock(return_value={"status": report_status, "events": [
                {"ticker": "LOWM", "status": "eligible_conditional_plan", "timing": timing, "blockers": []}]})
            capital = {"decisions": [{"ticker": "LOWM", "decision": "ACTIONABLE_BUY", "shares": 1, "order_draft": {"side": "buy"}}]}
            with patch.dict(sys.modules, {"earnings_events": SimpleNamespace(summary=summary)}):
                result = earnings_event_view(Path("/isolated"), datetime.fromisoformat("2026-10-21T09:00:00-04:00"),
                                            capital=capital, current_contract=True)
                self.assertEqual(result["events"][0]["status"], "research_in_progress")

    def test_invalid_source_read_is_not_a_verified_empty_calendar(self):
        summary = Mock(side_effect=ValueError("source_receipt_mismatch"))
        with patch.dict(sys.modules, {"earnings_events": SimpleNamespace(summary=summary)}):
            result = earnings_event_view(Path("/isolated"), datetime.fromisoformat("2026-10-21T09:00:00-04:00"))
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["events"], [])


if __name__ == "__main__":
    unittest.main()
