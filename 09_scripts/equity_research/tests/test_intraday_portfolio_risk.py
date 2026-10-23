from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from _support import SCRIPT_DIR  # noqa: F401
from account_access import capture_version
from daily_common import canonical_sha256
import intraday_prices as feed
import intraday_portfolio_risk as risk
from investment_plans import SCHEMA as PLAN_SCHEMA
from test_investment_plans import record
from test_intraday_prices import seed_admitted_history


class IntradayPortfolioRiskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = datetime.fromisoformat("2026-10-22T11:00:30-04:00")
        source = SCRIPT_DIR.parents[1]
        for relative in (risk.INPUTS[0], risk.INPUTS[1]):
            self.write(relative, json.loads((source / relative).read_text()))
        self.csv(risk.INPUTS[2], [
            {"ticker": "SPY", "sector": "ETF", "is_benchmark": "yes"},
            {"ticker": "AAA", "sector": "Technology", "is_benchmark": "no"},
        ])
        account = {"account_total_value": 9999, "prior_account_value": 1000, "new_external_cash": 1500,
            "cash_available": 100, "cash_reserved": 0, "investment_horizon_years": 1,
            "cash_needed_within_three_years": "no", "core_allocation_target_pct": 30,
            "active_stock_target_pct": 70, "active_stock_hard_cap_pct": 70,
            "cash_target_pct": 0, "single_stock_default_cap_pct": None, "single_stock_hard_cap_pct": None,
            "last_updated": "2026-10-20T11:00:00-04:00", "cash_basis": "ledger_estimate", "core_minimum_pct": 30}
        self.write(risk.INPUTS[3], account)
        self.csv(risk.INPUTS[4], [{"ticker": "SPY", "shares_optional": "2"}, {"ticker": "AAA", "shares_optional": "1"}])
        self.write(risk.INPUTS[5], {"schema_version": "phase5r_open_orders_v1", "as_of": "2026-10-01T11:00:00-04:00",
            "orders": [], "complete": False, "cash_confirmed": False,
            "existing_tactical_risk_confirmed": False, "existing_tactical_risk_usd": None})
        authority = {"schema_version": "equity_account_record_authority_v1", "mode": "owner_local_ledger",
            "approved_at": "2026-10-01T11:00:00-04:00", "owner_instruction": "Use local records for conditional manual plans.",
            "automatic_execution": False, "broker_observation_claimed": False}
        authority["content_sha256"] = canonical_sha256(authority)
        self.write(risk.POLICY_PATH, authority)
        (self.root / "receipt.json").write_bytes(b"receipt")
        self.plans()
        self.csv(feed.BASELINE, [{"ticker": "SPY", "last_price": "100", "market_session_date": "2026-10-21", "data_quality_label": "ok"},
            {"ticker": "AAA", "last_price": "100", "market_session_date": "2026-10-21", "data_quality_label": "ok"}])
        seed_admitted_history(self.root)
        self.symbols = {"AAA": "stocks", "SPY": "etf"}

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))

    def csv(self, relative, rows):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)

    def plans(self, *, tactical=False, review_due=False):
        records = []
        for ticker, role, shares in (("SPY", "broad_core", 2), ("AAA", "tactical" if tactical else "long_term_growth", 1)):
            row = record(ticker=ticker, role=role)
            row.update(recorded_at="2026-10-22T09:00:00-04:00", effective_at="2026-10-22T09:00:00-04:00",
                account_observed_at="2026-10-20T11:00:00-04:00", review_at="2026-10-22T10:00:00-04:00" if review_due else "2026-10-22T15:45:00-04:00",
                valid_until="2026-10-22T16:00:00-04:00", expected_shares=shares,
                proposed_change_shares=shares if role == "tactical" else 0,
                action="protect_review" if role == "tactical" else "hold", order_draft=None,
                time_exit_at="2026-10-22T15:45:00-04:00" if role == "tactical" else None)
            if role == "tactical":
                row["order_draft"] = {"side": "sell", "type": "STOP", "stop_price": 95, "quantity": shares,
                    "time_in_force": "DAY", "session_date": "2026-10-22"}
            row.update(version=1, supersedes=None, previous_hash=records[-1]["record_hash"] if records else "")
            row["record_hash"] = canonical_sha256(row)
            records.append(row)
        self.write(risk.INPUTS[6], {"schema_version": PLAN_SCHEMA, "records": records})

    def snapshot(self, *, broken=None, prices=None):
        prices = prices or {"SPY": 98.0, "AAA": 90.0}
        def get(url):
            ticker = url.split("/quote/")[1].split("/")[0]
            price = prices[ticker]
            data = {"status": {"rCode": 200, "bCodeMessage": None}, "data": {"symbol": ticker,
                "assetClass": self.symbols[ticker].upper(), "marketStatus": "Open", "primaryData": {
                    "lastSalePrice": "$%.2f" % price, "netChange": "%+.2f" % (price - 100),
                    "percentageChange": "%+.2f%%" % (price - 100), "isRealTime": True,
                    "currency": "USD", "lastTradeTimestamp": "Oct 22, 2026 11:00:00 AM ET"}}}
            if ticker == broken:
                data["data"]["primaryData"]["isRealTime"] = False
            return json.dumps(data).encode()
        client = feed.NasdaqIntradayClient(self.root, get=get, sleep=lambda _: None, now=lambda: self.now)
        return feed.collect(self.root, self.symbols, account_version=capture_version(self.root), claim_id="claim-risk", current=self.now, client=client)

    def test_complete_mark_includes_cash_and_all_inventory_not_stale_account_nav(self):
        snapshot = self.snapshot()
        result = risk.assess(self.root, snapshot, self.now)
        self.assertEqual(result["status"], "current", result)
        self.assertEqual(result["portfolio_nav"], 386)
        self.assertEqual(result["baseline_portfolio_nav"], 400)
        self.assertEqual(result["value_change_usd"], -14)
        self.assertEqual(result["value_change_pct"], -3.5)
        self.assertFalse(result["performance_is_actual"])
        self.assertEqual(result["cash_usd"], 100)
        self.assertEqual(result["concentration"]["single_stock_cap_pct"], None)
        self.assertEqual(result["reassessment_triggers"], [])
        self.assertFalse(result["email_authorized"])
        self.assertEqual(result["new_order_quantities"], 0)
        self.assertEqual(result["tactical_limits"]["existing_planned_risk_usd"], 0)
        self.assertEqual(result["tactical_limits"]["ordinary_risk_pct"], .5)
        self.assertEqual(result["tactical_limits"]["event_risk_pct"], .25)
        self.assertEqual(risk.validate_assessment(self.root, result), result)

    def test_missing_or_delayed_single_holding_cannot_make_portfolio_percent(self):
        result = risk.assess(self.root, self.snapshot(broken="AAA"), self.now)
        self.assertEqual(result["status"], "partial")
        self.assertIsNone(result["portfolio_nav"])
        self.assertIsNone(result["value_change_pct"])
        self.assertEqual(result["positions"], [])
        self.assertTrue(result["dependencies"])
        self.assertEqual(risk.validate_assessment(self.root, result), result)

    def test_expired_live_projection_suppresses_totals_but_retained_asof_validates(self):
        result = risk.assess(self.root, self.snapshot(), self.now)
        later = self.now + timedelta(minutes=6)
        self.assertEqual(risk.validate_assessment(self.root, result, current=later), result)
        projected = risk.projection(self.root, result, later)
        self.assertEqual(projected["status"], "expired")
        self.assertIsNone(projected["portfolio_nav"])
        self.assertIsNone(projected["value_change_pct"])
        self.assertEqual(projected["allocation"], {})
        self.assertTrue(all(x["price"] is None for x in projected["positions"]))
        self.assertEqual(result["portfolio_nav"], 386)

    def test_expired_marks_withhold_tactical_percentage_derived_from_marked_nav(self):
        orders = json.loads((self.root / risk.INPUTS[5]).read_text())
        orders.update(existing_tactical_risk_confirmed=True, existing_tactical_risk_usd=10)
        self.write(risk.INPUTS[5], orders)
        result = risk.assess(self.root, self.snapshot(), self.now)
        self.assertGreater(result["tactical_limits"]["combined_planned_risk_pct"], 2)
        self.assertTrue(any(x["kind"] == "tactical_budget" for x in result["reassessment_triggers"]))
        expired = risk.projection(self.root, result, self.now + timedelta(minutes=6))
        self.assertIsNone(expired["tactical_limits"]["combined_planned_risk_pct"])
        self.assertEqual(expired["tactical_limits"]["combined_status"], "unverified")
        self.assertFalse(any(x["kind"] == "tactical_budget" for x in expired["reassessment_triggers"]))
        self.assertEqual(expired["tactical_limits"]["existing_planned_risk_usd"], 10)
        self.assertEqual(expired["tactical_limits"]["combined_risk_pct"], 2)

    def test_actual_account_change_suppresses_previous_mark_and_does_not_revalue_new_cash_as_profit(self):
        result = risk.assess(self.root, self.snapshot(), self.now)
        account = json.loads((self.root / risk.INPUTS[3]).read_text())
        account["cash_available"] += 100
        self.write(risk.INPUTS[3], account)
        projected = risk.projection(self.root, result, self.now)
        self.assertEqual(projected["status"], "unavailable")
        self.assertIsNone(projected["value_change_pct"])
        self.assertIsNone(projected["portfolio_nav"])

    def test_future_account_observation_cannot_be_used_for_an_earlier_assessment(self):
        account = json.loads((self.root / risk.INPUTS[3]).read_text())
        account["last_updated"] = "2026-10-22T12:00:00-04:00"
        self.write(risk.INPUTS[3], account)
        with self.assertRaisesRegex(ValueError, "account_observation_after_assessment"):
            risk.assess(self.root, self.snapshot(), self.now)

    def test_current_stop_reference_is_reassessment_only_and_due_plan_is_not_renewed(self):
        self.plans(tactical=True)
        result = risk.assess(self.root, self.snapshot(), self.now)
        crossed = [x for x in result["reassessment_triggers"] if x["kind"] == "recorded_stop_review"]
        self.assertEqual(len(crossed), 1)
        self.assertEqual(crossed[0]["reference_price"], 95)
        self.assertEqual(crossed[0]["observed_price"], 90)
        self.assertEqual(crossed[0]["status"], "price_condition_met_reassessment_required")
        self.assertIsNone(result["tactical_limits"]["existing_planned_risk_usd"])
        self.assertFalse(result["trading_eligibility_granted"])
        self.plans(tactical=True, review_due=True)
        due = risk.assess(self.root, self.snapshot(), self.now)
        self.assertFalse(any(x["kind"] == "recorded_stop_review" for x in due["reassessment_triggers"]))
        self.assertTrue(any(x["status"] == "review_due" for x in due["reassessment_triggers"]))

    def test_structured_company_price_conditions_do_not_clear_entry_gates(self):
        payload = json.loads((self.root / risk.INPUTS[6]).read_text())
        row = payload["records"][1]
        row["strategy_horizon"] = "long_term_growth"
        row["purpose"] = {key: "Current source-bound company case; independent gates remain required."
            for key in ("strategy", "holding_period_justification", "entry_validity", "failure_condition", "exit_rule")}
        row["purpose"]["sources"] = row["sources"]
        row["reviewed_allocation"] = {key: "Sourced allocation judgment." for key in
            ("rationale", "downside_case", "portfolio_overlap", "alternatives")}
        row["reviewed_allocation"].update(target_position_pct=20, maximum_entry_price=100,
            invalidation_price=95, reassessment_price=120, reviewed_at=row["recorded_at"], sources=row["sources"])
        row["record_hash"] = canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
        self.write(risk.INPUTS[6], payload)
        result = risk.assess(self.root, self.snapshot(), self.now)
        triggers = [x for x in result["reassessment_triggers"] if x["kind"].startswith("reviewed_allocation_")]
        self.assertEqual({x["kind"] for x in triggers}, {"reviewed_allocation_invalidation_price", "reviewed_allocation_maximum_entry_price"})
        self.assertTrue(all(x["status"] == "price_condition_met_reassessment_required" for x in triggers))
        self.assertFalse(result["trading_eligibility_granted"])
        self.assertFalse(result["email_authorized"])
        self.assertEqual(result["new_order_quantities"], 0)

    def test_plan_deadline_inside_price_freshness_does_not_preserve_a_price_instruction(self):
        self.plans(tactical=True)
        payload = json.loads((self.root / risk.INPUTS[6]).read_text())
        chain = ""
        for row in payload["records"]:
            row["review_at"] = "2026-10-22T11:01:00-04:00"
            row["previous_hash"] = chain
            row["record_hash"] = canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
            chain = row["record_hash"]
        self.write(risk.INPUTS[6], payload)
        result = risk.assess(self.root, self.snapshot(), self.now)
        self.assertTrue(any(x["kind"] == "recorded_stop_review" for x in result["reassessment_triggers"]))
        current = risk.projection(self.root, result, datetime.fromisoformat("2026-10-22T11:02:00-04:00"))
        self.assertEqual(current["status"], "current")
        self.assertTrue(any(x["status"] == "review_due" for x in current["reassessment_triggers"]))
        self.assertFalse(any(x["kind"] == "recorded_stop_review" for x in current["reassessment_triggers"]))
        expired = risk.projection(self.root, result, self.now + timedelta(minutes=6))
        self.assertEqual(expired["status"], "expired")
        self.assertTrue(any(x["status"] == "review_due" for x in expired["reassessment_triggers"]))
        self.assertIsNone(expired["portfolio_nav"])
        self.assertTrue(any(x["kind"] == "recorded_stop_review" for x in result["reassessment_triggers"]))

    def test_raw_response_tamper_or_arithmetic_reseal_cannot_validate(self):
        snapshot = self.snapshot()
        result = risk.assess(self.root, snapshot, self.now)
        forged = copy.deepcopy(result)
        forged["portfolio_nav"] = 500
        forged["assessment_sha256"] = canonical_sha256({k: v for k, v in forged.items() if k != "assessment_sha256"})
        with self.assertRaisesRegex(ValueError, "recomposition_mismatch"):
            risk.validate_assessment(self.root, forged)
        self.assertIsNone(risk.projection(self.root, forged, self.now)["portfolio_nav"])
        source = self.root / snapshot["rows"]["AAA"]["source"]["response"]["path"]
        source.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            risk.validate_assessment(self.root, result)
        self.assertIsNone(risk.projection(self.root, result, self.now)["portfolio_nav"])

    def test_newer_failed_collection_does_not_reuse_old_fresh_marks(self):
        old = self.snapshot()
        result = risk.assess(self.root, old, self.now)
        self.snapshot(broken="AAA")
        stale_reuse = risk.assess(self.root, old, self.now)
        self.assertNotEqual(stale_reuse["status"], "current")
        self.assertIsNone(stale_reuse["portfolio_nav"])
        self.assertEqual(risk.validate_assessment(self.root, result), result)
        self.assertIsNone(risk.projection(self.root, result, self.now)["portfolio_nav"])

    def test_closed_market_receipt_has_explicit_dependency_and_no_fabricated_return(self):
        closed = datetime.fromisoformat("2026-10-22T16:01:00-04:00")
        snapshot = feed.collect(self.root, self.symbols, account_version=capture_version(self.root),
            claim_id="closed-risk", current=closed)
        result = risk.assess(self.root, snapshot, closed)
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["portfolio_nav"])
        self.assertIsNone(result["value_change_pct"])
        self.assertTrue(any("intraday_market_closed" in x for x in result["dependencies"]))
        self.assertEqual(risk.validate_assessment(self.root, result), result)

    def test_partial_failed_original_bytes_remain_bound(self):
        snapshot = self.snapshot(broken="AAA")
        result = risk.assess(self.root, snapshot, self.now)
        self.assertTrue(any("intraday_delay_unverified" in x for x in result["dependencies"]))
        source = self.root / snapshot["attempts"][0]["response"]["path"]
        source.write_bytes(b"corrupt partial original")
        with self.assertRaises(ValueError):
            risk.validate_assessment(self.root, result)

    def test_canonical_baseline_or_policy_change_invalidates_assessment(self):
        result = risk.assess(self.root, self.snapshot(), self.now)
        path = self.root / feed.BASELINE
        path.write_text(path.read_text().replace(",100,", ",101,"))
        with self.assertRaises(ValueError):
            risk.validate_assessment(self.root, result)
        self.assertIsNone(risk.projection(self.root, result, self.now)["portfolio_nav"])

    def test_missing_plan_cannot_prove_zero_tactical_risk(self):
        self.write(risk.INPUTS[6], {"schema_version": PLAN_SCHEMA, "records": []})
        result = risk.assess(self.root, self.snapshot(), self.now)
        self.assertIsNone(result["tactical_limits"]["existing_planned_risk_usd"])
        self.assertTrue(any(x["kind"] == "plan_integrity" for x in result["reassessment_triggers"]))


if __name__ == "__main__":
    unittest.main()
