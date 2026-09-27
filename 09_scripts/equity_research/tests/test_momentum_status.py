"""Advisory errors must stay visible without breaking the production status."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
from generate_current_status import momentum_health


class MomentumStatusTests(unittest.TestCase):
    def setUp(self):
        self.current = datetime(2026, 9, 27, 13, tzinfo=ZoneInfo("America/New_York"))
        self.session = "2026-09-25"
        self.success = {"status": "experimental", "generated_at": "2026-09-27T12:00:00-04:00",
                        "market_session": self.session, "observations": 34, "outcomes": 0}

    def health(self, payload, refresh=None):
        return momentum_health(payload, refresh or {}, current=self.current, expected_session=self.session)

    def test_malformed_optional_status_never_raises(self):
        for value in (None, [], "bad", 12, {}, {"status": []}, {"status": {}}, {"status": "unsupported"}):
            with self.subTest(payload=value):
                result = self.health(value)
                self.assertEqual(result["status"], "missing_or_invalid")
                self.assertEqual(result["freshness"], "stale_or_unverified")
                self.assertFalse(result["automatic_action_allowed"])

    def test_explicit_failure_is_preserved_even_without_market_session(self):
        result = self.health({"status": "failed", "generated_at": self.success["generated_at"], "reason": "invalid_input"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["reason"], "invalid_input")
        self.assertEqual(result["freshness"], "stale_or_unverified")
        self.assertTrue(result["prior_report_is_historical"])

    def test_current_refresh_timeout_overrides_prior_same_day_success(self):
        refresh = {"cycle_date": "2026-09-27", "expected_market_session": self.session,
                   "steps": [{"name": "momentum_experiment", "exit_code": 124}]}
        result = self.health(self.success, refresh)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["refresh_step_exit_code"], 124)
        self.assertEqual(result["freshness"], "current")
        self.assertTrue(result["prior_report_is_historical"])
        self.assertEqual(self.success["status"], "experimental")

    def test_old_refresh_failure_does_not_override_current_success(self):
        refresh = {"cycle_date": "2026-09-26", "expected_market_session": self.session,
                   "steps": [{"name": "momentum_experiment", "exit_code": 1}]}
        result = self.health(self.success, refresh)
        self.assertEqual(result["status"], "experimental")
        self.assertFalse(result["prior_report_is_historical"])

    def test_stale_future_or_wrong_session_success_never_claims_current(self):
        for change in ({"generated_at": "2026-09-26T12:00:00-04:00"},
                       {"generated_at": "2026-09-28T12:00:00-04:00"},
                       {"generated_at": "2026-09-27T12:00:00"},
                       {"market_session": "2026-09-24"}):
            with self.subTest(change=change):
                result = self.health({**self.success, **change})
                self.assertEqual(result["status"], "stale_or_unverified")
                self.assertTrue(result["prior_report_is_historical"])


if __name__ == "__main__":
    unittest.main()
