from __future__ import annotations

import copy
import unittest
from datetime import datetime
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401

from phase5r_active_config import load_active_config
from phase5r_model_router import route_model
import phase5r_production_shadow_v1 as shadow
from track_phase5r_recommendation_outcomes import classification
from refresh_phase5r_valuation_scenarios import selected_band, utc_now_text
from phase5r_valuation_input_bundle import _SOURCE_POLICIES
import run_phase5r_daily_refresh as daily_refresh
import run_phase5r_daily_refresh_scheduler as refresh_scheduler
import create_phase5r_daily_decision_and_brief as decision_builder
from run_phase5r_llm_shadow import load_registry
from generate_phase5r_current_status import model_authorization_is_blocker
from create_phase5r_c9_exact_action_plan import valuation_trim_review_required


class ActiveProductionTests(unittest.TestCase):
    @staticmethod
    def future_evaluation_config() -> dict:
        config = copy.deepcopy(load_active_config())
        config["model_policy"]["status"] = "future_shadow_evaluation_authorized"
        return config

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
        route = route_model(
            {}, completed_shadow_observations=0,
            deterministic_refresh_passed=False, api_authorized=True,
            config_override=self.future_evaluation_config(),
        )
        self.assertEqual(route["action"], "no_call")

    def test_router_blocks_without_api_authorization(self) -> None:
        route = route_model(
            {}, completed_shadow_observations=0,
            deterministic_refresh_passed=True, api_authorized=False,
            config_override=self.future_evaluation_config(),
        )
        self.assertEqual(route["reason"], "api_authorization_absent")

    def test_router_uses_terra_medium_only_for_evaluation_window(self) -> None:
        route = route_model(
            {}, completed_shadow_observations=9,
            deterministic_refresh_passed=True, api_authorized=True,
            config_override=self.future_evaluation_config(),
        )
        self.assertEqual((route["model"], route["reasoning_effort"]), ("gpt-5.6-terra", "medium"))

    def test_router_makes_no_call_for_unchanged_post_evaluation_decision(self) -> None:
        route = route_model(
            {}, completed_shadow_observations=10,
            deterministic_refresh_passed=True, api_authorized=True,
            config_override=self.future_evaluation_config(),
        )
        self.assertEqual(route["action"], "no_call")

    def test_router_uses_terra_for_material_filing(self) -> None:
        route = route_model(
            {"material_events": [{"ticker": "IOT"}]},
            completed_shadow_observations=10,
            deterministic_refresh_passed=True,
            api_authorized=True,
            config_override=self.future_evaluation_config(),
        )
        self.assertEqual((route["model"], route["reasoning_effort"]), ("gpt-5.6-terra", "medium"))

    def test_router_uses_high_terra_for_complex_conflict(self) -> None:
        route = route_model(
            {"account_conflicts": ["test"]}, completed_shadow_observations=10,
            deterministic_refresh_passed=True, api_authorized=True,
            config_override=self.future_evaluation_config(),
        )
        self.assertEqual((route["model"], route["reasoning_effort"]), ("gpt-5.6-terra", "high"))

    def test_router_reserves_sol_for_prior_measured_disagreement(self) -> None:
        route = route_model(
            {"eligible_new_position_review_candidates": ["NVDA"]},
            completed_shadow_observations=10,
            deterministic_refresh_passed=True,
            api_authorized=True,
            prior_terra_disagreement=True,
            config_override=self.future_evaluation_config(),
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

    def test_current_status_observes_the_just_persisted_refresh_outcome(self) -> None:
        calls: list[str] = []
        writes: list[dict] = []

        def fake_run_step(name: str, script: str, allowed: bool, **_: object) -> dict:
            calls.append(name)
            return {
                "name": name,
                "script": script,
                "exit_code": 0,
                "allowed_to_fail": allowed,
                "outcome": "passed",
                "result_code": "child_completed",
            }

        with (
            patch.object(daily_refresh, "load_active_state"),
            patch.object(daily_refresh, "load_inhibit"),
            patch.object(daily_refresh, "log_daily_run"),
            patch.object(daily_refresh, "run_step", side_effect=fake_run_step),
            patch.object(
                daily_refresh,
                "atomic_write_json",
                side_effect=lambda _path, state: writes.append(copy.deepcopy(state)),
            ),
        ):
            result = daily_refresh.run_refresh(
                no_lock=True,
                market_snapshot_mode=daily_refresh.MARKET_SNAPSHOT_REUSE,
            )

        self.assertEqual(result, 0)
        self.assertEqual(calls[-1], "current_status")
        self.assertEqual(writes[0]["outcome"], "passed")
        self.assertNotIn("current_status_update", writes[0])
        self.assertEqual(
            writes[-1]["current_status_update"]["outcome"],
            "passed",
        )

    def test_historical_backfill_is_not_a_current_material_event(self) -> None:
        rows = [
            {
                "cycle_date": "2026-08-31",
                "filing_date": "2026-08-27",
                "is_new": "yes",
                "material_event": "yes",
                "ticker": "RBRK",
            },
            {
                "cycle_date": "2026-08-31",
                "filing_date": "2025-08-27",
                "is_new": "yes",
                "material_event": "yes",
                "ticker": "BACKFILL",
            },
        ]
        with (
            patch.object(decision_builder, "cycle_date", return_value="2026-08-31"),
            patch.object(decision_builder, "read_csv", return_value=rows),
        ):
            events = decision_builder.material_events_for_cycle(
                {"new_filing_lookback_calendar_days": 7}
            )
        self.assertEqual([row["ticker"] for row in events], ["RBRK"])

    def test_legacy_registry_is_explicitly_nonproduction(self) -> None:
        registry = load_registry()
        self.assertEqual(
            registry["authority_status"],
            "historical_nonproduction_fixture",
        )
        self.assertEqual(
            registry["superseded_by"],
            "00_project_control/phase5r_active_production_config.json",
        )
        self.assertFalse(registry["live_shadow_enabled"])

    def test_removed_ai_does_not_create_a_credential_blocker(self) -> None:
        config = load_active_config()
        self.assertFalse(
            model_authorization_is_blocker(
                config,
                {"completed_review_count": 0},
                {},
            )
        )

    def test_removed_ai_router_is_a_durable_no_call(self) -> None:
        route = route_model(
            {"material_events": [{"ticker": "IOT"}]},
            completed_shadow_observations=0,
            deterministic_refresh_passed=True,
            api_authorized=True,
        )
        self.assertEqual(route["action"], "no_call")
        self.assertEqual(route["reason"], "model_removed_from_active_production")

    def test_removed_ai_is_not_scheduler_eligible(self) -> None:
        self.assertFalse(refresh_scheduler.production_shadow_scheduler_enabled())

    def test_adverse_complete_valuation_opens_only_a_trim_review(self) -> None:
        valuation = {
            "status": "complete",
            "scenario_prices": {"bull": 72.0},
            "expected_upside_pct": -43.0,
            "reward_to_risk": 0.0,
        }
        policy = {
            "require_current_price_above_bull_scenario": True,
            "maximum_expected_upside_pct": 0.0,
            "exclusive_maximum_reward_to_risk": 1.0,
        }
        self.assertTrue(
            valuation_trim_review_required(valuation, 93.0, policy)
        )
        self.assertFalse(
            valuation_trim_review_required(valuation, 70.0, policy)
        )
        self.assertFalse(
            valuation_trim_review_required(
                {"status": "complete", "scenario_prices": {"bull": 72.0}},
                93.0,
                policy,
            )
        )
        self.assertFalse(
            valuation_trim_review_required(
                {**valuation, "reward_to_risk": 1.0},
                93.0,
                policy,
            )
        )

    def test_valuation_bundle_clock_matches_packet_precision(self) -> None:
        prepared_at = datetime.fromisoformat(
            utc_now_text().replace("Z", "+00:00")
        )
        self.assertEqual(prepared_at.microsecond, 0)


if __name__ == "__main__":
    unittest.main()
