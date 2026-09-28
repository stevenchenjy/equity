from __future__ import annotations

import copy
from datetime import datetime
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from generate_current_status import shadow_evaluation_health


CURRENT = datetime.fromisoformat("2026-09-28T15:30:00-04:00")


class ShadowStatusHealthTests(unittest.TestCase):
    def payload(self):
        return {"schema_version": "phase5r_shadow_incremental_value_evaluation_v3",
                "generated_at": "2026-09-28T15:20:00-04:00",
                "archive_integrity": {"status": "degraded", "invalid_archives": [
                    {"path": "archived/bundle.json", "reason": "archive_validation_failed"}], "valid_bundle_count": 3},
                "decision": {"status": "blocked_invalid_archived_evidence"}}

    def test_current_failure_is_visible_as_advisory_without_granting_authority(self):
        payload = self.payload(); before = copy.deepcopy(payload)
        result = shadow_evaluation_health(payload, current=CURRENT)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(result["freshness"], "current")
        self.assertEqual(result["invalid_archive_count"], 1)
        self.assertEqual(result["valid_bundle_count"], 3)
        self.assertEqual(result["evaluation_decision_status"], "blocked_invalid_archived_evidence")
        for field in ("automatic_action_allowed", "changes_canonical_eligibility", "production_authority", "email_eligible"):
            self.assertFalse(result[field])
        self.assertEqual(payload, before)
        self.assertNotIn("global_blockers", result)

    def test_stale_or_future_health_cannot_appear_current(self):
        for stamp in ("2026-09-22T19:14:18-04:00", "2026-09-28T16:00:00-04:00", "invalid"):
            result = shadow_evaluation_health({**self.payload(), "generated_at": stamp}, current=CURRENT)
            self.assertEqual(result["freshness"], "stale_or_unverified")
            self.assertEqual(result["status"], "stale_or_unverified")

    def test_missing_malformed_or_contradictory_health_is_not_validated(self):
        for payload in (None, [], {}, {**self.payload(), "archive_integrity": {}},
                        {**self.payload(), "archive_integrity": {"status": "validated", "invalid_archives": [{}], "valid_bundle_count": 3}}):
            result = shadow_evaluation_health(payload, current=CURRENT)
            self.assertEqual(result["status"], "missing_or_invalid")


if __name__ == "__main__":
    unittest.main()
