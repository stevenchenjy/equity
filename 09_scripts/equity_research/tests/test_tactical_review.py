from __future__ import annotations

import copy
import json
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from _support import SCRIPT_DIR  # noqa: F401
import tactical_review as tactical


def fixture():
    current = datetime(2026, 9, 22, 18, tzinfo=ZoneInfo("America/New_York"))
    policy = json.loads(tactical.POLICY_PATH.read_text())
    policy["coverage_tickers"] = ["TEST"]
    bars = [{"session_date": day, "open": 100, "high": 104, "low": 98,
             "close": 101, "volume": 1000000}
            for day in tactical._last_sessions(current.date(), 20)]
    bars[0].update(high=120)
    bars[-1].update(high=102)
    history = {"schema_version": tactical.HISTORY_SCHEMA, "validated": True,
               "market_session": "2026-09-22", "data_source": "verified_public_eod",
               "snapshot_sha256": "a" * 64,
               "tickers": {"TEST": {"bars": bars, "source_url": "https://example.test/public/TEST"}}}
    candidate = {"ticker": "TEST", "eligibility_label": "eligible_buy_review",
                 "maximum_review_price": 105, "suggested_whole_shares": 10}
    decision = {"account": {"account_total_value": 10000, "cash_available": 8000,
                             "cash_reserved": 100, "cash_basis": "owner_confirmed"},
                "market_gate": {"passed": True, "complete_close_verified": True,
                                "expected_market_session": "2026-09-22"},
                "evidence_gate": {"passed": True}, "fundamental_gate": {"passed": True},
                "eligible_new_position_review_candidates": ["TEST"],
                "watch_candidates": [candidate], "held_positions": [], "account_conflicts": []}
    orders = {"schema_version": "phase5r_open_orders_v1", "as_of": current.isoformat(),
              "complete": True, "source": "owner_confirmed", "orders": [],
              "existing_tactical_risk_confirmed": True, "existing_tactical_risk_usd": 0,
              "event_calendar": {"as_of_session": "2026-09-22", "complete": True, "events": []}}
    return {"decision": decision, "current": current, "policy": policy, "history": history,
            "open_orders": orders, "snapshot_hash": "a" * 64,
            "market_rows": [{"ticker": "TEST", "last_price": 101, "market_session_date": "2026-09-22", "data_quality_label": "ok"}],
            "exact_actions": [], "all_candidates": [candidate]}


class TacticalReviewTests(unittest.TestCase):
    def test_verified_canonical_candidate_is_capped_and_dated(self):
        values = fixture()
        result = tactical.build_tactical_review(**values)
        draft = result["drafts"][0]
        self.assertTrue(draft["eligible"])
        self.assertEqual(draft["quantity"], 4)  # 5% account capital cap, rounded down.
        self.assertEqual(draft["planned_risk_usd"], 16)
        self.assertEqual(draft["reward_to_risk"], 4.5)
        self.assertEqual(draft["session_date"], "2026-09-23")
        self.assertEqual(draft["time_exit_session"], "2026-09-29")
        self.assertFalse(result["automatic_action_allowed"])
        self.assertEqual(values["decision"]["watch_candidates"][0]["suggested_whole_shares"], 10)

    def test_global_gates_cannot_be_overridden_by_history_or_candidate(self):
        for key in ("market_gate", "evidence_gate", "fundamental_gate"):
            values = fixture()
            values["decision"][key]["passed"] = False
            draft = tactical.build_tactical_review(**values)["drafts"][0]
            self.assertEqual((draft["quantity"], draft["hypothetical_quantity"]), (0, 0))
            self.assertIn(key + "_failed", draft["blockers"])

    def test_assumed_cash_and_unknown_existing_risk_are_only_scenarios(self):
        values = fixture()
        values["decision"]["account"]["cash_basis"] = "owner_assumed"
        values["open_orders"]["existing_tactical_risk_confirmed"] = False
        draft = tactical.build_tactical_review(**values)["drafts"][0]
        self.assertEqual(draft["quantity"], 0)
        self.assertEqual(draft["hypothetical_quantity"], 4)
        self.assertEqual(len(draft["hypothetical_assumptions"]), 2)
        values["decision"]["eligible_new_position_review_candidates"] = []
        draft = tactical.build_tactical_review(**values)["drafts"][0]
        self.assertEqual(draft["hypothetical_quantity"], 0)

    def test_owner_recorded_cash_requires_explicit_fresh_confirmation(self):
        values = fixture()
        values["decision"]["account"]["cash_basis"] = "owner_recorded"
        self.assertEqual(tactical.build_tactical_review(**values)["drafts"][0]["quantity"], 0)
        values["open_orders"]["cash_confirmed"] = True
        self.assertEqual(tactical.build_tactical_review(**values)["drafts"][0]["quantity"], 4)
        values["open_orders"]["as_of"] = "2026-09-22T15:17:00-04:00"
        draft = tactical.build_tactical_review(**values)["drafts"][0]
        self.assertEqual(draft["quantity"], 0)
        self.assertIn("open_orders_unconfirmed", draft["blockers"])

    def test_malformed_history_or_order_container_fails_closed(self):
        values = fixture()
        values["history"]["tickers"] = []
        draft = tactical.build_tactical_review(**values)["drafts"][0]
        self.assertEqual((draft["quantity"], draft["hypothetical_quantity"]), (0, 0))
        self.assertIn("price_history_malformed", draft["blockers"])
        for mutation in ("schema", "orders"):
            values = fixture()
            if mutation == "schema":
                values["open_orders"]["schema_version"] = "unknown"
            else:
                values["open_orders"]["orders"] = {}
            draft = tactical.build_tactical_review(**values)["drafts"][0]
            self.assertEqual(draft["quantity"], 0)
            self.assertIn("open_orders_unconfirmed", draft["blockers"])

    def test_draft_session_uses_remaining_regular_session_until_close(self):
        for hour, minute, expected in ((13, 30, "2026-09-22"), (16, 0, "2026-09-23")):
            values = fixture()
            values["current"] = values["current"].replace(hour=hour, minute=minute)
            result = tactical.build_tactical_review(**values)
            self.assertEqual(result["next_session"], expected)
            self.assertEqual(result["drafts"][0]["session_date"], expected)

    def test_missing_stale_future_duplicate_or_mismatched_bars_are_rejected(self):
        for mutation in ("missing", "future", "duplicate", "hash", "close", "ohlc"):
            values = fixture()
            bars = values["history"]["tickers"]["TEST"]["bars"]
            if mutation == "missing":
                bars.pop(0)
            elif mutation == "future":
                bars[-1]["session_date"] = "2026-09-23"
            elif mutation == "duplicate":
                bars[1]["session_date"] = bars[0]["session_date"]
            elif mutation == "hash":
                values["history"]["snapshot_sha256"] = "b" * 64
            elif mutation == "close":
                values["market_rows"][0]["last_price"] = 110
            else:
                bars[0]["open"] = 150
            with self.subTest(mutation=mutation):
                draft = tactical.build_tactical_review(**values)["drafts"][0]
                self.assertEqual(draft["quantity"], 0)
                self.assertIsNone(draft["entry_price"])
                self.assertFalse(draft["price_evidence"]["validated"])

    def test_observed_target_is_never_manufactured_to_meet_two_r(self):
        values = fixture()
        values["history"]["tickers"]["TEST"]["bars"][0]["high"] = 105
        draft = tactical.build_tactical_review(**values)["drafts"][0]
        self.assertEqual(draft["target_price"], 105)
        self.assertEqual(draft["reward_to_risk"], .75)
        self.assertEqual(draft["quantity"], 0)
        self.assertIn("reward_to_risk_below_2", draft["blockers"])

    def test_pending_order_is_reserved_and_never_assumed_unfilled(self):
        values = fixture()
        values["open_orders"]["orders"] = [{"ticker": "TEST", "side": "buy", "remaining_quantity": 1,
            "limit_price": 100, "time_in_force": "DAY", "session_date": "2026-09-22", "status": "open"}]
        result = tactical.build_tactical_review(**values)
        self.assertEqual(result["open_orders"]["orders"][0]["review_status"], "expired_pending_verification")
        self.assertEqual(result["open_orders"]["cash_reservation_usd"], 100)
        self.assertEqual(result["drafts"][0]["quantity"], 0)
        self.assertGreater(result["drafts"][0]["hypothetical_quantity"], 0)
        self.assertTrue(any("cancellation/fill" in text for text in result["drafts"][0]["hypothetical_assumptions"]))
        self.assertIn("existing_order_requires_reconciliation", result["drafts"][0]["blockers"])

    def test_current_cash_reserve_and_shared_combined_risk_limits_apply(self):
        values = fixture()
        values["decision"]["account"].update(cash_available=250, cash_reserved=100)
        self.assertEqual(tactical.build_tactical_review(**values)["drafts"][0]["quantity"], 1)
        values = fixture()
        values["open_orders"]["existing_tactical_risk_usd"] = 195
        self.assertEqual(tactical.build_tactical_review(**values)["drafts"][0]["quantity"], 1)
        second = copy.deepcopy(values["all_candidates"][0])
        second["ticker"] = "ZZZ"
        values["all_candidates"].append(second)
        values["decision"]["eligible_new_position_review_candidates"].append("ZZZ")
        values["history"]["tickers"]["ZZZ"] = copy.deepcopy(values["history"]["tickers"]["TEST"])
        values["market_rows"].append({**values["market_rows"][0], "ticker": "ZZZ"})
        self.assertEqual([row["quantity"] for row in tactical.build_tactical_review(**values)["drafts"]], [1, 0])

    def test_event_calendar_uses_lower_budget_and_missing_calendar_blocks(self):
        values = fixture()
        values["decision"]["account"]["account_total_value"] = 1000
        # At this size the capital cap cannot afford even one share.
        values["open_orders"]["event_calendar"]["events"] = [{"ticker": "ALL", "session_date": "2026-09-25", "type": "macro"}]
        draft = tactical.build_tactical_review(**values)["drafts"][0]
        self.assertTrue(draft["event_risk"])
        self.assertEqual(draft["risk_limit_usd"], 2.5)
        self.assertEqual(draft["quantity"], 0)
        values = fixture()
        values["open_orders"].pop("event_calendar")
        draft = tactical.build_tactical_review(**values)["drafts"][0]
        self.assertIn("event_calendar_unconfirmed", draft["blockers"])
        self.assertEqual(draft["quantity"], 0)

    def test_lagged_canonical_publication_cannot_create_a_next_session_order(self):
        values = fixture()
        values["decision"]["market_gate"]["expected_market_session"] = "2026-09-21"
        result = tactical.build_tactical_review(**values)
        self.assertIn("latest_completed_session_missing", result["blockers"])
        self.assertEqual(result["drafts"][0]["quantity"], 0)

    def test_policy_requested_coverage_survives_missing_market_or_eligibility(self):
        values = fixture()
        values["policy"]["coverage_tickers"] += ["APP", "XLI"]
        result = tactical.build_tactical_review(**values)
        rows = {row["ticker"]: row for row in result["drafts"]}
        self.assertEqual(set(rows), {"APP", "TEST", "XLI"})
        self.assertEqual(rows["XLI"]["quantity"], 0)
        self.assertIn("price_history_incomplete", rows["XLI"]["blockers"])


if __name__ == "__main__":
    unittest.main()
