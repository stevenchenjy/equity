from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_daily_common as common
import send_phase5r_daily_email as sender
from phase5r_active_config import ActiveConfigError, load_active_config
from test_phase5r_email_brief import action_fixture
from test_phase5r_owner_review_delivery import delivery_fixture, owner_review_fixture, save_decision


def notification_fixture():
    decision = action_fixture()
    decision["eligible_new_position_review_candidates"] = ["PANW"]
    decision["new_candidate_stability_distinct_closes"] = 2
    decision["watch_candidates"] = [
        {"ticker": "PANW", "label": "eligible_buy_review", "action": "eligible_buy_review",
         "gate_blockers": "", "current_price": "190", "maximum_review_price": "195.50", "suggested_whole_shares": "1"},
        {"ticker": "ARM", "label": "wait_for_more_evidence", "action": "watch_only",
         "gate_blockers": "valuation,portfolio_fit", "current_price": "264.79", "suggested_whole_shares": "0"},
    ]
    return decision


class RecommendationNotificationTests(unittest.TestCase):
    def test_tactical_plan_and_order_changes_notify_but_rollover_and_rejected_prices_do_not(self):
        prior = notification_fixture()
        prior["tactical_review"] = {
            "schema_version": "phase5r_tactical_review_v1", "as_of": "2026-09-22T18:00:00-04:00",
            "blockers": ["cash_not_confirmed"], "cash_basis": "ledger_estimate",
            "risk_policy": {"ordinary_risk_pct": 0.5},
            "open_orders": {"complete": False, "as_of": "2026-09-22T15:24:00-04:00", "orders": [
                {"ticker": "NOW", "order_id": "owner-1", "status": "open", "review_status": "open",
                 "quantity": 1, "remaining_quantity": 1, "limit_price": 133, "time_in_force": "GTD"}]},
            "drafts": [
                {"ticker": "NVDA", "quantity": 0, "eligible": False, "hypothetical_quantity": 1,
                 "entry_price": 223, "stop_price": 217.75, "target_price": 233.50,
                 "price_evidence": {"validated": True}, "blockers": ["cash_not_confirmed"],
                 "session_date": "2026-09-23", "time_exit_session": "2026-09-29"},
                {"ticker": "META", "quantity": 0, "eligible": False, "hypothetical_quantity": 0,
                 "entry_price": 740, "stop_price": 720, "target_price": 741,
                 "blockers": ["reward_to_risk_below_2"]}],
        }
        same = copy.deepcopy(prior)
        same["tactical_review"].update(as_of="2026-09-23T18:00:00-04:00", risk_budget={"ordinary_usd": 29.4})
        same["tactical_review"]["drafts"][0].update(session_date="2026-09-24", time_exit_session="2026-09-30", entry_price="223.00")
        same["tactical_review"]["drafts"][1].update(entry_price=741, target_price=742)
        self.assertEqual(common.recommendation_notification_fingerprint(prior), common.recommendation_notification_fingerprint(same))
        for mutate in (
            lambda review: review["drafts"][0].update(entry_price=222),
            lambda review: review["drafts"][0].update(hypothetical_quantity=0),
            lambda review: review["drafts"][0].update(blockers=["event_calendar_unconfirmed"]),
            lambda review: review["open_orders"]["orders"][0].update(status="filled"),
            lambda review: review["open_orders"]["orders"][0].update(limit_price=134),
        ):
            changed = copy.deepcopy(prior)
            mutate(changed["tactical_review"])
            self.assertNotEqual(common.recommendation_notification_fingerprint(prior), common.recommendation_notification_fingerprint(changed))

    def test_new_mode_ignores_raw_events_and_unchanged_weekly_while_legacy_remains(self):
        values = dict(is_weekend=True, weekly_summary_due=True, material_event=True,
                      decision_changed=True, account_conflict=True, fundamental_weakening=True,
                      first_material_baseline=True)
        self.assertEqual(common.notification_delivery_policy(**values), (True, "friday_weekly_summary"))
        self.assertEqual(common.notification_delivery_policy(**values, regular_delivery_mode=common.WATCH_ACTION_NOTIFICATION_MODE),
                         (False, "unchanged_watch_and_actions_suppressed"))
        self.assertEqual(common.notification_delivery_policy(**values, regular_delivery_mode=common.WATCH_ACTION_NOTIFICATION_MODE, notification_changed=True),
                         (True, "watch_or_action_changed"))
        with self.assertRaisesRegex(ValueError, "notification_mode_invalid"):
            common.notification_delivery_policy(**values, regular_delivery_mode="always_send")

    def test_quotes_dates_raw_filings_order_and_numeric_formatting_do_not_notify(self):
        prior = notification_fixture()
        changed = copy.deepcopy(prior)
        changed["generated_at"] = "2026-09-02T12:45:00-04:00"
        changed["cycle_date"] = "2026-09-02"
        changed["market_gate"]["expected_market_session"] = "2026-09-01"
        changed["decision_fingerprint"] = "new-research-document"
        changed["material_events"] = [{"accession_number": "new-raw-filing"}]
        changed["held_positions"][0].update(current_price="100.25", current_weight_pct="8.1",
                                                whole_shares_to_change="1.000", target_shares="1.0")
        changed["watch_candidates"][0].update(current_price="192.77", maximum_review_price="195.5000", suggested_whole_shares="1.000")
        changed["watch_candidates"][1].update(current_price="266.10", maximum_review_price="500", gate_blockers=" portfolio_fit,valuation,valuation ", score="9.2")
        changed["watch_candidates"].reverse()
        self.assertEqual(common.recommendation_notification_fingerprint(prior), common.recommendation_notification_fingerprint(changed))

    def test_semantic_membership_blockers_quantities_and_eligible_limits_notify(self):
        baseline = notification_fixture()
        mutations = [
            lambda row: row["held_positions"][0].update(whole_shares_to_change="2", target_shares="0"),
            lambda row: row["watch_candidates"][0].update(suggested_whole_shares="2"),
            lambda row: row["watch_candidates"][0].update(maximum_review_price="196.25"),
            lambda row: row["watch_candidates"][1].update(gate_blockers="portfolio_fit"),
            lambda row: row["watch_candidates"][1].update(invalidation="Reassess when official guidance deteriorates."),
            lambda row: row["watch_candidates"].pop(),
            lambda row: row.update(account_conflicts=["pending_execution:RBRK"], decision_code="account_conflict_hold"),
            lambda row: row["market_gate"].update(passed=False),
            lambda row: row["fundamental_gate"].update(weakening_tickers=["RBRK"]),
        ]
        for index, mutate in enumerate(mutations):
            changed = copy.deepcopy(baseline)
            mutate(changed)
            with self.subTest(mutation=index):
                self.assertTrue(common.notification_change_comparison(changed, {}, baseline)["changed"])

    def test_migration_uses_previous_valid_snapshot_and_missing_baseline_seeds_quietly(self):
        previous = notification_fixture()
        current = copy.deepcopy(previous)
        current["held_positions"][0]["current_price"] = "110"
        comparison = common.notification_change_comparison(current, {}, previous)
        self.assertFalse(comparison["changed"])
        self.assertEqual(comparison["comparison_source"], "prior_decision_migration")
        for missing in ({}, {"decision_code": "hold_no_new_position"}):
            comparison = common.notification_change_comparison(current, {}, missing)
            self.assertFalse(comparison["changed"])
            self.assertEqual(comparison["comparison_source"], "initial_baseline")

    def test_same_cycle_recomposition_keeps_undelivered_change_pending(self):
        previous = notification_fixture()
        current = copy.deepcopy(previous)
        current["held_positions"][0]["whole_shares_to_change"] = "2"
        first = common.notification_change_comparison(current, {}, previous)
        state = {"cycle_date": current["cycle_date"], "notification_change_fingerprint": first["fingerprint"],
                 "notification_change_anchor": first["prior_fingerprint"]}
        second = common.notification_change_comparison(current, state, current)
        self.assertTrue(second["changed"])
        self.assertEqual(second["comparison_source"], "same_cycle_anchor")
        current["cycle_date"] = "2026-09-02"
        self.assertFalse(common.notification_change_comparison(current, state, current)["changed"])

    def test_sender_recomputes_semantic_change_and_rejects_spoofed_policy_flag(self):
        previous = notification_fixture()
        decision = copy.deepcopy(previous)
        decision["watch_candidates"][0]["maximum_review_price"] = "196.25"
        decision["notification_policy"]["regular_delivery_mode"] = common.WATCH_ACTION_NOTIFICATION_MODE
        decision["notification_change"] = common.notification_change_comparison(decision, {}, previous)
        decision.update(send_recommended=True, send_reason="watch_or_action_changed")
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            self.assertEqual(sender.validate_decision(), decision)
            decision["notification_change"]["changed"] = False
            save_decision(decision)
            with self.assertRaisesRegex(ValueError, "notification_change_mismatch"):
                sender.validate_decision()
            config.assert_not_called()
            smtp.assert_not_called()

    def test_legacy_owner_review_retains_old_policy_truth_but_regular_send_requires_refresh(self):
        decision = owner_review_fixture()
        self.assertNotIn("regular_delivery_mode", decision["notification_policy"])
        self.assertNotIn("notification_change", decision)
        with delivery_fixture() as (config, smtp):
            save_decision(decision)
            with self.assertRaisesRegex(ValueError, "notification_mode_requires_refresh"):
                sender.validate_decision()
            self.assertEqual(sender.validate_decision(owner_review_request_id=decision["owner_requested_research"]["request_id"]), decision)
            config.assert_not_called()
            smtp.assert_not_called()

    def test_config_supports_new_mode_and_missing_legacy_mode_but_rejects_unknown(self):
        config = load_active_config()
        self.assertEqual(config["notifications"]["regular_delivery_mode"], common.WATCH_ACTION_NOTIFICATION_MODE)
        with tempfile.TemporaryDirectory(prefix="phase5r-notify-config-") as directory:
            path = Path(directory) / "config.json"
            config["notifications"].pop("regular_delivery_mode")
            path.write_text(json.dumps(config), encoding="utf-8")
            self.assertNotIn("regular_delivery_mode", load_active_config(path)["notifications"])
            config["notifications"]["regular_delivery_mode"] = "send_every_day"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaises(ActiveConfigError):
                load_active_config(path)


if __name__ == "__main__":
    unittest.main()
