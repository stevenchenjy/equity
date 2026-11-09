from __future__ import annotations

import copy
import csv
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import held_position_risk as risk
from attention_email import direct_cards, direct_subject
from decision_dependencies import classify


class HeldPositionRiskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = datetime.fromisoformat("2026-11-06T14:00:00-05:00")
        self.write_csv(risk.POSITIONS, [{"ticker": "AAA", "shares_optional": "4", "entry_price": "100"},
                                       {"ticker": "BBB", "shares_optional": "1", "entry_price": "50"}])
        self.quotes = [{"ticker": ticker, "last_price": price, "market_session_date": "2026-11-05",
                        "data_timestamp": "2026-11-06T08:00:00-05:00", "data_quality_label": "ok",
                        "data_source": "retained_test_source"} for ticker, price in (("AAA", "70"), ("BBB", "55"))]
        self.write_csv(risk.MARKET, self.quotes)
        self.write_csv(risk.QUALITY, [{"ticker": t, "usable_for_scoring": "yes"} for t in ("AAA", "BBB")])
        self.write_json(risk.ORDERS, {"as_of": "2026-11-05T16:00:00-05:00", "orders": []})
        self.plans = {"plans": [{"ticker": t, "status": "maintained", "role": "long_term_growth",
                                "plan_id": t + "-current", "version": 2, "record_hash": "test",
                                "review_at": "2026-11-06T15:00:00-05:00", "blockers": [],
                                "reason": "Current sourced ownership rationale", "purpose": None}
                               for t in ("AAA", "BBB")], "global_blockers": [], "ticker_blockers": {}}
        self.decision = {"generated_at": self.now.isoformat(), "market_gate": {"passed": True, "failures": []},
                         "capital_decision": {"decisions": [{"ticker": t, "decision": "HOLD", "blockers": [],
                                                             "order_draft": None} for t in ("AAA", "BBB")]}}

    def write_csv(self, relative, rows):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)

    def write_json(self, relative, data):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def build(self, current=None):
        with patch.object(risk, "load_plan_context", return_value=self.plans):
            return risk.build(self.decision, root=self.root, current=current or self.now)

    def test_basis_loss_is_visible_independent_of_unrelated_company_failure(self):
        self.decision["fundamental_gate"] = {"passed": False}
        self.decision["workflow_integrity"] = {"global_blockers": ["fundamental_gate_failed"]}
        report = self.build()
        aaa = report["holdings"][0]
        self.assertEqual(aaa["basis_price_change_pct"], -30)
        self.assertEqual(aaa["unrealized_change_usd"], -120)
        self.assertEqual(aaa["state"], "REVIEWED_HOLD")
        self.assertFalse(report["email_authorized"])
        self.assertFalse(report["trading_eligibility_granted"])
        # A loss alone cannot create an unapproved stop or numerical alert rule.
        self.assertEqual(aaa["conditions"], [])

    def test_missing_individual_price_retains_other_holding_observation(self):
        self.write_csv(risk.MARKET, self.quotes[:1])
        self.decision["market_gate"] = {"passed": False, "failures": ["BBB:market_row_missing"]}
        report = self.build()
        self.assertEqual(report["coverage"], "partial_or_unavailable")
        self.assertEqual(report["holdings"][0]["basis_price_change_pct"], -30)
        self.assertEqual(report["holdings"][1]["state"], "UNVERIFIED")
        self.assertIsNone(report["holdings"][1]["basis_price_change_pct"])

    def test_closed_zero_inventory_is_not_a_positive_holding(self):
        self.write_csv(risk.POSITIONS, [{"ticker": "AAA", "shares_optional": "0", "entry_price": "100"},
                                       {"ticker": "BBB", "shares_optional": "-1", "entry_price": "50"}])
        report = self.build()
        self.assertEqual([row["ticker"] for row in report["holdings"]], ["BBB"])
        self.assertEqual(report["holdings"][0]["state"], "UNVERIFIED")

    def test_expiry_and_crossed_reference_never_renew_order(self):
        p = self.plans["plans"][0]
        p.update(status="expired_pending_verification", historical_order_draft={
            "side": "sell", "type": "STOP", "stop_price": 80, "quantity": 4, "session_date": "2026-11-05"})
        report = self.build()
        aaa = report["holdings"][0]
        self.assertEqual(aaa["state"], "RISK_ALERT")
        self.assertTrue(aaa["conditions"][0]["reference_expired"])
        self.assertIn("no assertion it was crossed while valid", aaa["conditions"][0]["meaning"])
        self.assertFalse(aaa["action_draft_available"])
        self.assertEqual(aaa["plan_id"], "AAA-current")

    def test_no_closed_position_stop_is_reused(self):
        report = self.build()
        self.assertEqual(report["holdings"][0]["conditions"], [])
        # The projection never reads older/closed ledger rows as current refs.
        self.write_json("05_risk_and_positions/investment_plans.local.json", {
            "records": [{"ticker": "AAA", "state": "completed", "stop_price": 95}]})
        self.assertEqual(self.build()["holdings"][0]["conditions"], [])

    def test_account_contradiction_keeps_price_but_withholds_recommendation(self):
        self.plans["global_blockers"] = ["account_feedback_conflict"]
        aaa = self.build()["holdings"][0]
        self.assertEqual(aaa["state"], "UNVERIFIED")
        self.assertEqual(aaa["basis_price_change_pct"], -30)
        self.assertIn("actual remaining shares", aaa["next_step"])

    def test_partial_order_reserves_shares_and_names_reconciliation(self):
        self.write_json(risk.ORDERS, {"orders": [{"ticker": "AAA", "status": "partial_fill",
                                               "quantity": 4, "remaining_quantity": 2}]})
        row = self.build()["holdings"][0]
        self.assertIn("never duplicate", row["next_step"])
        self.assertEqual(row["known_pending_orders"][0]["remaining_quantity"], 2)

    def test_bound_source_change_and_content_tampering_rejected(self):
        report = self.build()
        d = {**self.decision, "held_position_risk": report}
        with patch.object(risk, "load_plan_context", return_value=self.plans):
            risk.validate_publication(d, root=self.root, current=self.now)
            d["held_position_risk"]["holdings"][0]["basis_price_change_pct"] = 10
            with self.assertRaisesRegex(ValueError, "recompose_required"):
                risk.validate_publication(d, root=self.root, current=self.now)
            d["held_position_risk"] = self.build()
            self.write_csv(risk.MARKET, [{**q, "last_price": "1"} for q in self.quotes])
            with self.assertRaisesRegex(ValueError, "recompose_required"):
                risk.validate_publication(d, root=self.root, current=self.now)

    def test_unchanged_observation_has_one_immutable_history_record(self):
        first = self.build()
        risk.publish(self.root, first)
        risk.publish(self.root, self.build(self.now + timedelta(seconds=10)))
        paths = list((self.root / risk.HISTORY).glob("*.json"))
        self.assertEqual(len(paths), 1)
        self.assertEqual(json.loads(paths[0].read_text())["generated_at"], first["generated_at"])

    def test_direct_email_exposes_expired_holding_and_real_engine_trigger_status(self):
        self.plans["plans"][0]["status"] = "expired_pending_verification"
        d = {**self.decision, "held_position_risk": self.build(), "held_positions": [
            {"ticker": "AAA", "current_shares": 4}, {"ticker": "BBB", "current_shares": 1}],
             "intraday_portfolio_risk": {"status": "current", "reassessment_triggers": [{"ticker": "BBB",
                "status": "price_condition_met_reassessment_required", "condition": "Existing stop crossed"}]}}
        with patch("attention_email.validate"), patch("attention_email.optional_rotation_cards", return_value=[]):
            result = direct_cards(d)
            self.assertIn("Holdings need attention", direct_subject(d))
        text = "\n".join(x["body"] for x in result)
        self.assertIn("AAA — PLAN EXPIRED", text)
        self.assertIn("-30.00%", text)
        self.assertIn("Existing stop crossed", text)
        self.assertFalse(any(x["title"] == "Unchanged holdings" for x in result))

    def test_exit_dependency_requests_exit_contract_not_new_buy_valuation(self):
        result = classify("maintained_exit_draft_requires_current_shares_price_and_validity")
        self.assertIn("exact remaining quantity", result["evidence_required"])
        self.assertIn("unfinished new-buy valuation alone", result["evidence_required"])


if __name__ == "__main__":
    unittest.main()
