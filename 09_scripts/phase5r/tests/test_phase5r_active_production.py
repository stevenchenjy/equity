from __future__ import annotations

import copy
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401

from phase5r_active_config import load_active_config
from phase5r_daily_common import (
    BASIC_EOD_PUBLICATION_TIME_ET,
    notification_delivery_policy,
)
from track_phase5r_recommendation_outcomes import classification
from refresh_phase5r_valuation_scenarios import selected_band, utc_now_text
from phase5r_valuation_input_bundle import _SOURCE_POLICIES
import run_phase5r_daily_refresh as daily_refresh
import run_phase5r_daily_refresh_scheduler as refresh_scheduler
import create_phase5r_daily_decision_and_brief as decision_builder
from create_phase5r_c9_exact_action_plan import valuation_trim_review_required
from create_phase5r_daily_decision_and_brief import (
    action_review_display,
    held_position_summary,
    valuation_display,
)
from phase5r_portfolio_construction import (
    core_starter_decision,
    individual_sizing_decision,
)


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
            tuple(config["notifications"]["eod_publication_retry_slots_et"]),
            refresh_scheduler.EOD_PUBLICATION_RETRY_SLOTS,
        )
        self.assertEqual(
            config["notifications"]["market_data_publication_after_et"],
            BASIC_EOD_PUBLICATION_TIME_ET,
        )
        self.assertEqual(
            config["notifications"]["send_after_et"],
            "13:30",
        )
        self.assertEqual(
            config["notifications"]["terminal_alert_after_et"],
            "15:30",
        )

    def test_recommendation_labels_are_explicit(self) -> None:
        self.assertEqual(classification("trim_specific_shares_review"), "TRIM")
        self.assertEqual(classification("hold"), "HOLD")
        self.assertEqual(classification("eligible_buy_review"), "ADD_REVIEW")
        self.assertEqual(classification("watch_only"), "WATCH")
        self.assertEqual(
            classification("core_allocation_tranche_review"), "ADD_REVIEW"
        )

    def test_etf_valuation_is_explicitly_not_applicable(self) -> None:
        self.assertEqual(
            valuation_display({
                "valuation_applicability": "not_applicable_broad_market_etf"
            }),
            "不适用（宽基 ETF 使用核心配置口径）",
        )

    def test_trim_review_email_includes_exact_shares_target_and_reason(self) -> None:
        row = {
            "ticker": "IOT",
            "action": "trim_specific_shares_review",
            "current_price": "40.85",
            "current_shares": "5.0000",
            "current_weight_pct": "8.3922",
            "target_shares": "4.0000",
            "whole_shares_to_change": "1",
            "reason": "Dynamic weight exceeds the 8.00% hard cap.",
            "holding_horizon": "medium_conviction",
            "invalidation": "Review if thesis weakens.",
            "valuation_bear_price": "16.57",
            "valuation_base_price": "25.4",
            "valuation_bull_price": "34.24",
            "strongest_positive_evidence": "revenue_growth_pct=29.60",
            "strongest_negative_evidence": "current_ev_to_revenue=13.75",
            "human_confirmation_required": "yes",
        }
        detail = action_review_display(row)
        self.assertIn("减少 1 股", detail)
        self.assertIn("复核后持有 4 股", detail)
        self.assertIn("触发依据：Dynamic weight exceeds the 8.00% hard cap.", detail)
        self.assertIn("不会自动执行", detail)
        self.assertIn(detail, held_position_summary(row))

    def test_hold_email_does_not_invent_an_action_scenario(self) -> None:
        self.assertEqual(action_review_display({"action": "hold"}), "")

    def test_uncertainty_maps_to_smaller_whole_share_sizing(self) -> None:
        policy = load_active_config()["account"]
        decision = individual_sizing_decision(
            policy=policy,
            valuation_complete=True,
            score=7.1,
            confidence="medium_high",
            expected_upside_pct=12.0,
            reward_to_risk=1.5,
            entry_score=5.5,
            portfolio_fit_score=6.0,
            current_price=140.0,
            account_total=3000.0,
            deployable_cash=2000.0,
            active_weight_pct=10.0,
            active_hard_cap_pct=30.0,
            single_stock_default_cap_pct=6.0,
        )
        self.assertEqual(decision["sizing_tier"], "starter_allocation")
        self.assertEqual(decision["suggested_whole_shares"], 1)
        self.assertTrue(decision["small_account_exception_used"])

        adverse = individual_sizing_decision(
            policy=policy,
            valuation_complete=True,
            score=8.5,
            confidence="high",
            expected_upside_pct=-5.0,
            reward_to_risk=0.0,
            entry_score=8.0,
            portfolio_fit_score=8.0,
            current_price=20.0,
            account_total=3000.0,
            deployable_cash=2000.0,
            active_weight_pct=10.0,
            active_hard_cap_pct=30.0,
            single_stock_default_cap_pct=6.0,
        )
        self.assertEqual(adverse["sizing_tier"], "no_allocation")
        self.assertIn("upside", adverse["failed_gates"])

    def test_core_starter_is_whole_share_and_not_forced(self) -> None:
        policy = load_active_config()["account"]
        selected = core_starter_decision(
            policy=policy,
            market_quality="ok",
            technical_score=5.5,
            current_price=767.05,
            fifty_two_week_high=779.37,
            fifty_two_week_low=629.28,
            account_total=2433.82,
            deployable_cash=1543.49,
            current_core_value=0.0,
            core_target_pct=60.0,
            maintenance_active=False,
        )
        self.assertTrue(selected["selected"])
        self.assertEqual(selected["suggested_whole_shares"], 1)
        self.assertAlmostEqual(selected["suggested_position_pct"], 31.5163, places=3)
        blocked = core_starter_decision(
            policy=policy,
            market_quality="ok",
            technical_score=5.5,
            current_price=779.37,
            fifty_two_week_high=779.37,
            fifty_two_week_low=629.28,
            account_total=2433.82,
            deployable_cash=1543.49,
            current_core_value=0.0,
            core_target_pct=60.0,
            maintenance_active=False,
        )
        self.assertFalse(blocked["selected"])
        self.assertIn("price_range", blocked["failed_gates"])

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
