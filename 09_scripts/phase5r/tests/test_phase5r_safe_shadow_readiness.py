from __future__ import annotations

import unittest

from _support import SCRIPT_DIR  # noqa: F401
from verify_phase5r_safe_shadow_readiness import audit


class SafeShadowReadinessTests(unittest.TestCase):
    def test_static_audit_passes_controls_but_keeps_launch_blocked(
        self,
    ) -> None:
        result = audit(static_only=True)
        self.assertTrue(result["safety_controls_passed"])
        self.assertTrue(result["local_controls_ready"])
        self.assertFalse(result["live_shadow_launch_ready"])
        self.assertIn("sec_contact_string", result["external_blockers"])
        self.assertIn(
            "pilot_call_and_usd_authorization",
            result["external_blockers"],
        )
        self.assertFalse(result["boundaries"]["provider_invoked"])
        self.assertFalse(result["boundaries"]["email_attempted"])
        self.assertFalse(result["boundaries"]["files_written"])

    def test_all_readiness_checks_are_explicit(self) -> None:
        result = audit(static_only=True)
        checks = {
            row["check_id"]: row["passed"]
            for row in result["checks"]
        }
        self.assertTrue(checks["policy.cost_estimates_recomputed"])
        self.assertTrue(checks["policy.all_external_spend_disabled"])
        self.assertTrue(
            checks["adapter.responses_usage_and_cache_normalized"]
        )
        self.assertTrue(checks["ledger.fixed_private_cycle_path"])
        self.assertTrue(checks["registry.model_influence_disabled"])
        self.assertTrue(
            checks["registry.licensed_market_data_disabled"]
        )


if __name__ == "__main__":
    unittest.main()
