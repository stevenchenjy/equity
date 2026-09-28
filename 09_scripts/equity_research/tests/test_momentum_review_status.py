"""A failed advisory review must not appear ready or inhibit canonical reporting."""
import copy
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import run_daily_refresh as refresh
from generate_current_status import momentum_review_health


class MomentumReviewStatusTests(unittest.TestCase):
    def setUp(self):
        self.current = datetime(2026, 10, 3, 12, tzinfo=ZoneInfo("America/New_York"))
        self.payload = {"status": "ready_for_owner_review", "ready_for_owner_review": True,
                        "generated_at": "2026-10-03T11:30:00-04:00", "market_session": "2026-10-02"}

    def health(self, payload, state=None):
        return momentum_review_health(payload, state or {}, current=self.current,
                                      expected_session="2026-10-02")

    def test_current_success_only_authorizes_review(self):
        result = self.health(self.payload)
        self.assertTrue(result["ready_for_owner_review"])
        self.assertFalse(result["automatic_action_allowed"])
        self.assertFalse(result["incremental_value_established"])
        self.assertFalse(result["changes_canonical_eligibility"])

    def test_invalid_stale_or_future_packet_cannot_appear_ready(self):
        for payload in (None, [], {}, {"status": []}, {**self.payload, "status": "unsupported"},
                        {**self.payload, "market_session": "2026-10-01"},
                        {**self.payload, "generated_at": "2026-10-02T11:30:00-04:00"},
                        {**self.payload, "generated_at": "2026-10-03T13:30:00-04:00"},
                        {**self.payload, "ready_for_owner_review": "true"}):
            with self.subTest(payload=payload):
                self.assertFalse(self.health(payload)["ready_for_owner_review"])

    def test_current_failed_study_or_review_overrides_earlier_success(self):
        for name in ("momentum_experiment", "momentum_experiment_review"):
            state = {"cycle_date": "2026-10-03", "steps": [{"name": name, "exit_code": 124}]}
            result = self.health(self.payload, state)
            self.assertEqual(result["status"], "failed")
            self.assertFalse(result["ready_for_owner_review"])

    def test_historical_readiness_is_separate_and_fails_closed_on_stale_or_failed_packet(self):
        payload = {**self.payload, "status": "waiting_for_complete_cohort", "ready_for_owner_review": False,
                   "historical_ready_for_owner_review": True}
        self.assertFalse(self.health(payload)["ready_for_owner_review"])
        self.assertTrue(self.health(payload)["historical_ready_for_owner_review"])
        stale = {**payload, "generated_at": "2026-10-02T11:30:00-04:00"}
        self.assertFalse(self.health(stale)["historical_ready_for_owner_review"])
        for name in ("momentum_experiment", "momentum_experiment_review"):
            state = {"cycle_date": "2026-10-03", "steps": [{"name": name, "exit_code": 1}]}
            self.assertFalse(self.health(payload, state)["historical_ready_for_owner_review"])

    def test_review_failure_is_visible_but_not_canonical_refresh_failure(self):
        writes = []
        def step(name, script, allowed, **kwargs):
            return {"name": name, "script": script, "allowed_to_fail": allowed,
                    "exit_code": 1 if name == "momentum_experiment_review" else 0}
        with (patch.object(refresh, "load_active_state"), patch.object(refresh, "load_inhibit"),
              patch("workflow_evaluation.record_refresh"), patch.object(refresh, "log_daily_run"),
              patch.object(refresh, "run_step", side_effect=step),
              patch.object(refresh, "atomic_write_json", side_effect=lambda p, v: writes.append(copy.deepcopy(v)))):
            self.assertEqual(refresh.run_refresh(no_lock=True), 0)
        self.assertEqual(writes[-1]["advisory_failures"], ["momentum_experiment_review"])
        self.assertEqual(writes[-1]["hard_failures"], [])
        self.assertEqual(writes[-1]["soft_failures"], [])


if __name__ == "__main__":
    unittest.main()
