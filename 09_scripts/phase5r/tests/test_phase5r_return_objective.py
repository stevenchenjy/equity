from __future__ import annotations

import unittest

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_return_objective import (
    annualized_to_monthly_compound_pct,
    return_objective_payload,
    validate_return_objective_payload,
)


class ReturnObjectiveTests(unittest.TestCase):
    def test_exact_monthly_compound_equivalents(self) -> None:
        self.assertEqual(annualized_to_monthly_compound_pct(12.0), 0.9489)
        self.assertEqual(annualized_to_monthly_compound_pct(15.0), 1.1715)

    def test_objective_is_not_a_quota_guarantee_or_risk_override(self) -> None:
        objective = return_objective_payload()
        self.assertEqual(
            objective["measurement_horizon"],
            "rolling_5_year_net_total_return",
        )
        self.assertEqual(
            (
                objective["target_annualized_return_pct_low"],
                objective["target_annualized_return_pct_high"],
            ),
            (12.0, 15.0),
        )
        self.assertEqual(
            (
                objective["excellent_calendar_year_pct_low"],
                objective["excellent_calendar_year_pct_high"],
            ),
            (15.0, 20.0),
        )
        self.assertIs(objective["monthly_or_annual_quota"], False)
        self.assertIs(objective["return_guarantee"], False)
        self.assertIs(objective["risk_gates_override_allowed"], False)
        self.assertEqual(validate_return_objective_payload(objective), objective)
        mutated = dict(objective)
        mutated["monthly_or_annual_quota"] = True
        with self.assertRaisesRegex(ValueError, "closed policy"):
            validate_return_objective_payload(mutated)


if __name__ == "__main__":
    unittest.main()
