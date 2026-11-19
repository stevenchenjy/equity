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
from account_feedback_gate import LEGACY_SCHEMA, LOCAL_SCOPE_KIND, RELATIVE as PENDING, SCHEMA, UNRESOLVED
from attention_email import direct_cards, direct_subject
from decision_dependencies import classify
from investment_plans import RELATIVE_PATH as PLAN, append_plan
from tactical_review import review_open_orders
from test_investment_plans import ledger, record


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

    def test_pending_fill_scope_keeps_unrelated_hold_and_shared_capital_barrier(self):
        (self.root / "receipt.json").write_bytes(b"receipt")
        def held_plan(ticker, quantity):
            plan = record(ticker=ticker, role="long_term_growth")
            plan.update(action="hold", order_draft=None, expected_shares=quantity, proposed_change_shares=0,
                        review_at=(self.now + timedelta(hours=1)).isoformat())
            return plan
        plans = append_plan(ledger(held_plan("AAA", 4)), held_plan("BBB", 1), root=self.root)
        self.write_json(PLAN, plans)
        self.write_json(risk.ORDERS, {"as_of": self.now.isoformat(), "complete": True, "orders": []})
        feedback = dict(id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", ticker="AAA", stage="pending",
                        revision=1, record_sha256="b" * 64, missing=["Unresolved fill input"],
                        scope={"kind": LOCAL_SCOPE_KIND, "side": "sell", "status": "filled"})
        self.write_json(PENDING, {"schema_version": SCHEMA, "records": [feedback]})
        quantities = [{"ticker": "AAA", "current_shares": 4}, {"ticker": "BBB", "current_shares": 1}]
        context = risk.load_plan_context(self.root, quantities, self.now)
        self.assertEqual(context["feedback_fill_tickers"], ["AAA"])
        self.assertTrue(context["block_new_capital"])
        self.assertIn(UNRESOLVED, context["global_blockers"])
        self.assertIn(UNRESOLVED, context["ticker_blockers"]["AAA"])
        self.assertEqual([item["status"] for item in context["plans"]],
                         ["account_feedback_pending_verification", "maintained"])
        self.decision["workflow_integrity"] = {"global_blockers": [UNRESOLVED]}
        report = risk.build(self.decision, root=self.root, current=self.now)
        self.assertEqual([holding["state"] for holding in report["holdings"]], ["UNVERIFIED", "REVIEWED_HOLD"])
        self.assertEqual(report["holdings"][0]["quote"]["price"], 70)
        self.assertIn(UNRESOLVED, report["holdings"][0]["dependencies"])
        self.assertNotIn(UNRESOLVED, report["holdings"][1]["dependencies"])
        self.assertFalse(report["trading_eligibility_granted"])
        decision = {**self.decision, "held_position_risk": report}
        risk.validate_publication(decision, root=self.root, current=self.now)

        for schema, pending in ((LEGACY_SCHEMA, {k: feedback[k] for k in ("id", "ticker", "stage", "missing")}),
                                (SCHEMA, {**feedback, "scope": None}),
                                (SCHEMA, {**feedback, "stage": "recovery_conflict", "scope": None}),
                                (SCHEMA, {**feedback, "record_sha256": "unverified"})):
            with self.subTest(schema=schema, pending=pending):
                self.write_json(PENDING, {"schema_version": schema, "records": [pending]})
                broad = risk.build(self.decision, root=self.root, current=self.now)
                self.assertEqual([holding["state"] for holding in broad["holdings"]], ["UNVERIFIED", "UNVERIFIED"])
                with self.assertRaisesRegex(ValueError, "recompose_required"):
                    risk.validate_publication(decision, root=self.root, current=self.now)

    def test_changed_plan_quantity_uses_current_account_without_reasking_owner(self):
        self.write_json(risk.ORDERS, {"as_of": self.now.isoformat(), "orders": [], "complete": True,
                                     "cash_confirmed": True})
        self.plans["plans"][0].update(status="position_changed_pending_verification",
                                       blockers=["remaining_quantity_changed"])
        report = self.build()
        row = report["holdings"][0]
        self.assertEqual(row["state"], "UNVERIFIED")
        self.assertEqual(row["basis_price_change_pct"], -30)
        self.assertIn("Reconcile the prior plan with the current recorded 4 shares", row["next_step"])
        self.assertNotIn("Owner/account record:", row["next_step"])
        self.assertNotIn("provide actual remaining shares", row["next_step"])
        self.assertIn(row["next_step"], risk.cards({"held_position_risk": report})[0]["body"])
        self.assertFalse(report["trading_eligibility_granted"])

    def test_partial_order_reserves_shares_and_names_reconciliation(self):
        self.write_json(risk.ORDERS, {"orders": [{"ticker": "AAA", "status": "partial_fill",
                                               "quantity": 4, "remaining_quantity": 2}]})
        row = self.build()["holdings"][0]
        self.assertIn("never duplicate", row["next_step"])
        self.assertIn("Owner/account record: provide actual remaining shares", row["next_step"])
        self.assertEqual(row["known_pending_orders"][0]["remaining_quantity"], 2)

    def test_verified_working_sell_reserves_shares_without_reasking_owner(self):
        order = {"order_id": "broker-working", "ticker": "AAA", "status": "open", "side": "sell",
                 "quantity": 4, "remaining_quantity": 4, "order_type": "LIMIT", "limit_price": 90.0,
                 "time_in_force": "GTD", "session_date": "2026-11-06", "expiration_date": "2027-05-05"}
        relative = "06_execution_records/working-order-observation.json"
        self.write_json(relative, {"orders_shown": [order]})
        stamp = self.now.isoformat()
        orders = {"schema_version": "phase5r_open_orders_v1", "as_of": stamp, "complete": True,
                  "orders": [order], "current_inventory_observation": {"as_of": stamp, "complete": True,
                      "orders_shown": [order], "source": {"path": relative, "sha256": risk.sha256_file(self.root / relative)}}}
        self.write_json(risk.ORDERS, orders)
        self.decision["tactical_review"] = {"open_orders": review_open_orders(orders, self.now, self.now.date(), [
            {"ticker": "AAA", "current_shares": 4}, {"ticker": "BBB", "current_shares": 1}])}
        self.assertTrue(self.decision["tactical_review"]["open_orders"]["broker_inventory_verified"])
        self.plans["plans"][0]["status"] = "expired_pending_verification"
        self.plans["ticker_blockers"]["AAA"] = ["outstanding_sell_reserves_current_shares"]
        self.decision["capital_decision"]["decisions"][0].update(
            decision="BLOCKED", blockers=["outstanding_sell_reserves_current_shares"])

        report = self.build()
        row = report["holdings"][0]
        self.assertEqual(report["observed_orders_display_version"], 1)
        self.assertEqual(row["state"], "PLAN_EXPIRED")
        self.assertTrue(row["observed_working_orders_verified"])
        self.assertFalse(row["action_draft_available"])
        self.assertIn("outstanding_sell_reserves_current_shares", row["dependencies"])
        self.assertNotIn("known_order_remaining_quantity_requires_reconciliation_before_replacement", row["dependencies"])
        self.assertIn("verified working sell order reserves its remaining shares", row["next_step"])
        self.assertNotIn("Owner/account record:", row["next_step"])
        self.assertEqual(row["known_pending_orders"], [order])

        with patch.object(risk, "load_plan_context", return_value=self.plans):
            old = risk.build(self.decision, root=self.root, current=self.now, legacy_order_display=True)
            self.assertNotIn("observed_orders_display_version", old)
            self.assertNotIn("observed_working_orders_verified", old["holdings"][0])
            self.assertIn("Owner/account record:", old["holdings"][0]["next_step"])
            risk.validate_publication({**self.decision, "held_position_risk": old}, root=self.root, current=self.now)

        blockers = self.decision["capital_decision"]["decisions"][0]["blockers"]
        blockers.append("earlier_instruction_execution_unreconciled")
        conflicted = self.build()["holdings"][0]
        self.assertFalse(conflicted["observed_working_orders_verified"])
        self.assertIn("Owner/account record:", conflicted["next_step"])
        blockers.pop()

        self.write_json(relative, {"orders_shown": []})
        unbound = self.build()["holdings"][0]
        self.assertFalse(unbound["observed_working_orders_verified"])
        self.assertIn("known_order_remaining_quantity_requires_reconciliation_before_replacement", unbound["dependencies"])
        self.assertIn("Owner/account record:", unbound["next_step"])

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

    def test_pending_account_feedback_requests_the_named_intake_fields(self):
        pending = classify(UNRESOLVED, scope="global")
        self.assertEqual((pending["category"], pending["resolver"], pending["scope"]),
                         ("C", "approved_manual_account_record", "global"))
        self.assertIn("specific saved feedback record", pending["evidence_required"])
        self.assertIn("missing fields", pending["evidence_required"])
        self.assertNotIn("account-wide", pending["evidence_required"])
        earlier = classify("earlier_instruction_execution_unreconciled", scope="global")
        self.assertIn("complete owner-recorded holdings/cash snapshot", earlier["evidence_required"])
        self.assertIn("account-wide order observation", earlier["evidence_required"])


if __name__ == "__main__":
    unittest.main()
