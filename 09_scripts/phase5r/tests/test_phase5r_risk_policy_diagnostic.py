from __future__ import annotations

from decimal import Decimal
import unittest

from _support import SCRIPT_DIR  # noqa: F401

from phase5r_risk_policy_diagnostic import (
    Holding,
    PREFERENCE_SCENARIOS,
    RiskPolicy,
    Snapshot,
    compare_policies,
    simultaneous_stress,
)


class RiskPolicyDiagnosticTests(unittest.TestCase):
    def snapshot(self, *, confirmed: bool = True) -> Snapshot:
        # Entirely synthetic fixture: no owner cash or account information.
        return Snapshot(2500, 1000, 500, confirmed, (
            Holding("AAA", 3, 100, "active"),
            Holding("BBB", 1, 210, "active"),
            Holding("CCC", 4, 45, "active"),
            Holding("CORE", 1, 810, "core"),
        ))

    def test_preferences_compare_independent_capacity_not_production_activation(self) -> None:
        report = compare_policies(self.snapshot(), {"NEW": 370})
        old, moderate, aggressive = report["comparisons"]
        self.assertAlmostEqual(report["active_weight_pct"], 27.6)
        self.assertEqual([row["active_headroom_value"] for row in report["comparisons"]], [60, 560, 1060])
        self.assertEqual([row["new_candidates_independent_not_joint"][0]["independent_hypothetical_whole_share_capacity"] for row in report["comparisons"]], [0, 1, 1])
        self.assertEqual(old["new_candidates_independent_not_joint"][0]["one_share_blockers"], ["active_sleeve_headroom", "new_position_cap"])
        self.assertEqual(moderate["new_candidates_independent_not_joint"][0]["limiting_budget_constraints"], ["new_position_cap"])
        self.assertEqual(aggressive["new_candidates_independent_not_joint"][0]["limiting_budget_constraints"], ["cash_after_reserve", "new_position_cap"])
        self.assertFalse(aggressive["new_candidates_independent_not_joint"][0]["order_eligible"])
        self.assertIn("no_policy_activation_no_orders", report["status"])

    def test_integer_cap_math_is_not_a_sell_recommendation_and_core_is_exempt(self) -> None:
        report = compare_policies(self.snapshot(), {})
        old = report["comparisons"][0]["positions"]
        self.assertEqual([row["minimum_whole_share_reduction_for_cap_math_only"] for row in old], [1, 1, 0, 0])
        self.assertFalse(old[-1]["active_single_stock_cap_applies"])
        self.assertTrue(all(row["action"] == "none_diagnostic_only" for row in old))
        self.assertTrue(all(row["held_cap_excess_value"] == 0 for row in report["comparisons"][1]["positions"]))
        fractional = Snapshot(2500, 2200, 500, True, (Holding("AAA", 1.5, 200, "active"),))
        self.assertIsNone(compare_policies(fractional, {})["comparisons"][0]["positions"][0]["minimum_whole_share_reduction_for_cap_math_only"])

    def test_unconfirmed_cash_keeps_hypothetical_capacity_but_no_confirmed_capacity(self) -> None:
        report = compare_policies(self.snapshot(confirmed=False), {"NEW": 200})
        candidate = report["comparisons"][2]["new_candidates_independent_not_joint"][0]
        self.assertEqual(candidate["independent_hypothetical_whole_share_capacity"], 2)
        self.assertEqual(candidate["confirmed_cash_arithmetic_capacity"], 0)
        self.assertIn("cash_unconfirmed", candidate["one_share_blockers"])
        self.assertEqual(report["nav"], 2500)
        self.assertEqual(report["deployable_cash_entered_basis"], 500)

    def test_candidates_are_independent_and_pending_sales_do_not_create_cash(self) -> None:
        report = compare_policies(self.snapshot(), {"NEW1": 300, "NEW2": 300})
        candidates = report["comparisons"][2]["new_candidates_independent_not_joint"]
        self.assertEqual([row["independent_hypothetical_whole_share_capacity"] for row in candidates], [1, 1])
        self.assertIn("alternatives, not jointly fundable", report["limitations"][1])
        self.assertEqual(report["deployable_cash_entered_basis"], 500)

    def test_decimal_boundary_does_not_lose_an_affordable_share(self) -> None:
        snapshot = Snapshot(100, 100, 0, True, ())
        report = compare_policies(snapshot, {"NEW": 0.10}, (RiskPolicy("full", 100, 100, 100),))
        self.assertEqual(report["comparisons"][0]["new_candidates_independent_not_joint"][0]["independent_hypothetical_whole_share_capacity"], 1000)

    def test_active_cap_breach_has_zero_headroom_and_cash_reserve_is_binding(self) -> None:
        snapshot = Snapshot(1000, 100, 100, True, (Holding("AAA", 9, 100, "active"),))
        report = compare_policies(snapshot, {"NEW": 1})
        self.assertEqual(report["comparisons"][0]["active_cap_excess_value"], 600)
        self.assertEqual(report["comparisons"][0]["active_headroom_value"], 0)
        self.assertEqual(report["comparisons"][0]["new_candidates_independent_not_joint"][0]["confirmed_cash_arithmetic_capacity"], 0)

    def test_simultaneous_stress_includes_core_and_cash_denominator(self) -> None:
        report = simultaneous_stress(self.snapshot(), {"AAA": -20, "BBB": -20, "CCC": -20, "CORE": -10})
        self.assertEqual(report["total_pnl"], -219)
        self.assertEqual(report["ending_nav"], 2281)
        self.assertAlmostEqual(report["loss_pct_of_starting_nav"], 8.76)
        self.assertEqual(report["cash_unchanged"], 1000)
        self.assertIn("not_var_backtest_or_forecast", report["status"])
        self.assertEqual(sum(row["ending_value"] for row in report["positions"]) + report["cash_unchanged"], report["ending_nav"])

    def test_full_equity_loss_leaves_cash_and_positive_shock_is_not_loss(self) -> None:
        snapshot = self.snapshot(confirmed=False)
        report = simultaneous_stress(snapshot, {item.ticker: -100 for item in snapshot.holdings})
        self.assertEqual(report["ending_nav"], 1000)
        self.assertEqual(report["loss_pct_of_starting_nav"], 60)
        self.assertFalse(report["cash_confirmed"])
        gain = simultaneous_stress(snapshot, {item.ticker: 10 for item in snapshot.holdings})
        self.assertEqual(gain["loss_pct_of_starting_nav"], 0)
        self.assertEqual(gain["pnl_pct_of_starting_nav"], 6)

    def test_rejects_nonfinite_zero_negative_or_non_numeric_inputs(self) -> None:
        for invalid in (0, -1, float("nan"), float("inf"), Decimal("NaN"), True, "100"):
            with self.subTest(value=invalid):
                with self.assertRaises(ValueError):
                    Holding("AAA", 1, invalid, "active")
                with self.assertRaises(ValueError):
                    Snapshot(invalid, 0, 0, True, ())
                with self.assertRaises(ValueError):
                    compare_policies(self.snapshot(), {"NEW": invalid})
        for invalid in (-1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                Snapshot(100, invalid, 0, True, ())
        with self.assertRaises(ValueError):
            Holding("AAA", 0, 1, "active")

    def test_rejects_fabricated_nav_invalid_cash_and_duplicate_inputs(self) -> None:
        for args in ((3000, 1000, 500, True), (2500, 1000, 1001, True), (2500, 1000, 500, "yes")):
            with self.assertRaises(ValueError):
                Snapshot(*args, self.snapshot().holdings)
        with self.assertRaises(ValueError):
            Snapshot(100, 0, 0, True, (Holding("aaa", 1, 50, "active"), Holding("AAA", 1, 50, "active")))
        for quotes in ({"AAA": 10}, {"new": 10, "NEW": 20}):
            with self.assertRaises(ValueError):
                compare_policies(self.snapshot(), quotes)
        with self.assertRaises(ValueError):
            Holding("AAA", 1, 1, "unknown")

    def test_policy_inputs_and_shock_coverage_are_explicit(self) -> None:
        for caps in ((30, 9, 8), (30, 6, 31), (101, 6, 8), (30, 0, 8), (float("nan"), 6, 8)):
            with self.assertRaises(ValueError):
                RiskPolicy("invalid", *caps)
        with self.assertRaises(ValueError):
            compare_policies(self.snapshot(), {}, (PREFERENCE_SCENARIOS[0], PREFERENCE_SCENARIOS[0]))
        full = {item.ticker: -20 for item in self.snapshot().holdings}
        for shocks in ({"AAA": -20}, {**full, "EXTRA": -20}, {**full, "AAA": -101}, {**full, "AAA": float("nan")}, {**full, "AAA": True}):
            with self.assertRaises(ValueError):
                simultaneous_stress(self.snapshot(), shocks)


if __name__ == "__main__":
    unittest.main()
