from __future__ import annotations

import unittest

from _support import SCRIPT_DIR  # noqa: F401

from phase5r_active_config import load_active_config
from phase5r_model_router import route_model
import phase5r_production_shadow_v1 as shadow
from track_phase5r_recommendation_outcomes import classification
from refresh_phase5r_valuation_scenarios import selected_band
from phase5r_valuation_input_bundle import _SOURCE_POLICIES


class ActiveProductionTests(unittest.TestCase):
    def test_active_configuration_holds_cost_and_execution_boundaries(self) -> None:
        config = load_active_config()
        self.assertLessEqual(config["model_policy"]["one_time_evaluation_budget_usd"], 5)
        self.assertLessEqual(config["model_policy"]["monthly_hard_cap_usd"], 2)
        self.assertLessEqual(config["model_policy"]["maximum_output_tokens"], 4000)
        self.assertFalse(config["boundaries"]["broker_connected"])
        self.assertFalse(config["boundaries"]["automatic_action_allowed"])

    def test_ten_reserved_shadow_days_fit_monthly_cap(self) -> None:
        self.assertLessEqual(shadow.maximum_provider_cost_usd(), shadow.DAILY_COST_CAP_USD)
        self.assertLessEqual(
            shadow.DAILY_COST_CAP_USD * shadow.OBSERVATION_COMPLETED_TRADING_DAYS,
            shadow.MONTHLY_COST_CAP_USD,
        )

    def test_router_blocks_before_deterministic_pass(self) -> None:
        route = route_model({}, completed_shadow_observations=0, deterministic_refresh_passed=False, api_authorized=True)
        self.assertEqual(route["action"], "no_call")

    def test_router_blocks_without_api_authorization(self) -> None:
        route = route_model({}, completed_shadow_observations=0, deterministic_refresh_passed=True, api_authorized=False)
        self.assertEqual(route["reason"], "api_authorization_absent")

    def test_router_uses_terra_medium_only_for_evaluation_window(self) -> None:
        route = route_model({}, completed_shadow_observations=9, deterministic_refresh_passed=True, api_authorized=True)
        self.assertEqual((route["model"], route["reasoning_effort"]), ("gpt-5.6-terra", "medium"))

    def test_router_makes_no_call_for_unchanged_post_evaluation_decision(self) -> None:
        route = route_model({}, completed_shadow_observations=10, deterministic_refresh_passed=True, api_authorized=True)
        self.assertEqual(route["action"], "no_call")

    def test_router_uses_terra_for_material_filing(self) -> None:
        route = route_model(
            {"material_events": [{"ticker": "IOT"}]},
            completed_shadow_observations=10,
            deterministic_refresh_passed=True,
            api_authorized=True,
        )
        self.assertEqual((route["model"], route["reasoning_effort"]), ("gpt-5.6-terra", "medium"))

    def test_router_uses_high_terra_for_complex_conflict(self) -> None:
        route = route_model(
            {"account_conflicts": ["test"]}, completed_shadow_observations=10,
            deterministic_refresh_passed=True, api_authorized=True,
        )
        self.assertEqual((route["model"], route["reasoning_effort"]), ("gpt-5.6-terra", "high"))

    def test_router_reserves_sol_for_prior_measured_disagreement(self) -> None:
        route = route_model(
            {"eligible_new_position_review_candidates": ["NVDA"]},
            completed_shadow_observations=10,
            deterministic_refresh_passed=True,
            api_authorized=True,
            prior_terra_disagreement=True,
        )
        self.assertEqual((route["model"], route["reasoning_effort"]), ("gpt-5.6-sol", "high"))

    def test_recommendation_labels_are_explicit(self) -> None:
        self.assertEqual(classification("trim_specific_shares_review"), "TRIM")
        self.assertEqual(classification("hold"), "HOLD")
        self.assertEqual(classification("eligible_buy_review"), "ADD_REVIEW")
        self.assertEqual(classification("watch_only"), "WATCH")

    def test_growth_band_selection_is_deterministic(self) -> None:
        policy = load_active_config()  # prove the active config is independently valid
        self.assertEqual(policy["schema_version"], "phase5r_active_production_config_v1")
        valuation_policy = {
            "growth_bands": [
                {"minimum_yoy_pct": 25, "base_multiple": 8},
                {"minimum_yoy_pct": -100, "base_multiple": 3},
            ]
        }
        self.assertEqual(selected_band(valuation_policy, 30)["base_multiple"], 8)
        self.assertEqual(selected_band(valuation_policy, -5)["base_multiple"], 3)

    def test_deterministic_policy_is_an_allowed_valuation_source(self) -> None:
        self.assertEqual(
            _SOURCE_POLICIES["deterministic_valuation_policy"],
            ("deterministic_policy", ("01_policies",)),
        )


if __name__ == "__main__":
    unittest.main()
