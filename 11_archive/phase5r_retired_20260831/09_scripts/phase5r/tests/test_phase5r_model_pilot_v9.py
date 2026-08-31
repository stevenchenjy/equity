from __future__ import annotations

import unittest

from run_phase5r_model_pilot_v9 import check_v9_readiness


class V9ReadinessTests(unittest.TestCase):
    def test_v9_is_fresh_and_gated_by_the_completed_v8_qualification(self) -> None:
        readiness = check_v9_readiness()

        self.assertTrue(readiness["passed"])
        self.assertTrue(readiness["v8_qualification_passed"])
        self.assertFalse(readiness["v8_qualification_output_used_as_research"])
        self.assertEqual(readiness["planned_model_calls"], 30)
        self.assertEqual(readiness["new_collection_usd_cap"], "5.00")
        self.assertEqual(
            readiness["combined_training_budget_upper_bound_usd"],
            "5.87120",
        )
        self.assertFalse(readiness["provider_constructed"])
        self.assertFalse(readiness["network_used"])
        self.assertFalse(readiness["files_written"])


if __name__ == "__main__":
    unittest.main()
