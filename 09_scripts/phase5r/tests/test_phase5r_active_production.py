from __future__ import annotations

import copy
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401

from phase5r_active_config import load_active_config
from phase5r_daily_common import notification_delivery_policy
from track_phase5r_recommendation_outcomes import classification
from refresh_phase5r_valuation_scenarios import selected_band, utc_now_text
from phase5r_valuation_input_bundle import _SOURCE_POLICIES
import run_phase5r_daily_refresh as daily_refresh
import run_phase5r_daily_refresh_scheduler as refresh_scheduler
import create_phase5r_daily_decision_and_brief as decision_builder
from create_phase5r_c9_exact_action_plan import valuation_trim_review_required


class ActiveProductionTests(unittest.TestCase):
    def test_notification_policy_is_event_driven_and_clock_independent(self) -> None:
        self.assertEqual(
            notification_delivery_policy(
                is_weekend=False,
                weekly_summary_due=False,
                material_event=False,
                decision_changed=False,
                account_conflict=False,
                fundamental_weakening=False,
                first_material_baseline=False,
            ),
            (False, "unchanged_daily_email_suppressed"),
        )
        self.assertEqual(
            notification_delivery_policy(
                is_weekend=False,
                weekly_summary_due=False,
                material_event=True,
                decision_changed=False,
                account_conflict=False,
                fundamental_weakening=False,
                first_material_baseline=False,
            ),
            (True, "material_decision_change"),
        )
        self.assertEqual(
            notification_delivery_policy(
                is_weekend=False,
                weekly_summary_due=True,
                material_event=False,
                decision_changed=False,
                account_conflict=False,
                fundamental_weakening=False,
                first_material_baseline=False,
            ),
            (True, "friday_weekly_summary"),
        )
        self.assertNotIn(
            "before_daily_decision_time",
            Path(decision_builder.__file__).read_text(encoding="utf-8"),
        )

    def test_active_configuration_holds_cost_and_execution_boundaries(self) -> None:
        config = load_active_config()
        self.assertEqual(config["model_policy"]["status"], "removed_from_active_production")
        self.assertFalse(config["model_policy"]["active"])
        self.assertFalse(config["model_policy"]["calls_allowed"])
        self.assertEqual(config["model_policy"]["monthly_hard_cap_usd"], 0)
        self.assertEqual(config["model_policy"]["actual_calls"], 0)
        self.assertFalse(config["boundaries"]["broker_connected"])
        self.assertFalse(config["boundaries"]["automatic_action_allowed"])
        self.assertEqual(
            tuple(config["notifications"]["post_close_refresh_retry_slots_et"]),
            refresh_scheduler.POST_CLOSE_MARKET_SLOTS,
        )
        self.assertEqual(
            config["notifications"]["send_after_et"],
            "18:30",
        )

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

    def test_degraded_refresh_returns_nonzero_for_scheduler_recovery(self) -> None:
        def fake_run_step(name: str, script: str, allowed: bool, **_: object) -> dict:
            failed = name == "market_refresh"
            return {
                "name": name,
                "script": script,
                "exit_code": 1 if failed else 0,
                "allowed_to_fail": allowed,
                "outcome": "failed" if failed else "passed",
                "result_code": "child_nonzero_exit" if failed else "child_completed",
            }

        with (
            patch.object(daily_refresh, "load_active_state"),
            patch.object(daily_refresh, "load_inhibit"),
            patch.object(daily_refresh, "log_daily_run"),
            patch.object(daily_refresh, "run_step", side_effect=fake_run_step),
            patch.object(daily_refresh, "atomic_write_json"),
        ):
            result = daily_refresh.run_refresh(
                no_lock=True,
                market_snapshot_mode=daily_refresh.MARKET_SNAPSHOT_REUSE,
            )

        self.assertEqual(result, 1)

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

    def test_removed_model_surface_is_absent_from_scheduler(self) -> None:
        self.assertFalse(hasattr(refresh_scheduler, "PRODUCTION_SHADOW_RUNNER"))
        self.assertFalse(hasattr(refresh_scheduler, "AUTH_PRESENCE_PROBE_ENV"))

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
