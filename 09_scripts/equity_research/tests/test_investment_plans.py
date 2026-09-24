from __future__ import annotations
import copy
import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from _support import SCRIPT_DIR  # noqa: F401
from investment_plans import (SCHEMA, append_plan, validate_ledger, evaluate_plans,
                              apply_plan_context, regular_close, semantic_state)


def record(ticker="TEST", role="tactical"):
    return {"plan_id": ticker + "-plan", "ticker": ticker, "role": role,
        "action": "protect_review", "recorded_at": "2026-09-24T12:00:00-04:00",
        "effective_at": "2026-09-24T11:00:00-04:00", "review_at": "2026-09-25T12:00:00-04:00",
        "account_observed_at": "2026-09-24T11:59:00-04:00", "expected_shares": 4,
        "proposed_change_shares": 4, "instruction": "保留已记录保护条件，先核对。", "reason": "risk limit",
        "counterargument": "Price can recover", "reviewer": "analyst", "change_reason": "first recorded plan",
        "state": "proposed", "automatic_action_allowed": False,
        "time_exit_at": "2026-09-25T15:45:00-04:00" if role == "tactical" else None,
        "order_draft": {"side": "sell", "type": "STOP", "stop_price": 10, "quantity": 4,
                        "time_in_force": "DAY", "session_date": "2026-09-24"},
        "sources": [{"path": "receipt.json", "sha256": hashlib.sha256(b"receipt").hexdigest()}]}


def ledger(row=None):
    return append_plan({"schema_version": SCHEMA, "records": []}, row or record())


def evaluate(payload=None, when="2026-09-24T12:05:00-04:00", shares=4, orders=None):
    return evaluate_plans(payload or ledger(), [{"ticker": "TEST", "current_shares": shares}] if shares else [],
        current=datetime.fromisoformat(when), open_orders=orders or {"as_of": "2026-09-24T12:00:00-04:00", "complete": True, "orders": []})


class InvestmentPlanTests(unittest.TestCase):
    def test_versions_are_append_only_and_hash_bound(self):
        first = ledger()
        proposal = record()
        proposal.update(change_reason="target explicitly reviewed", instruction="Revised protection")
        second = append_plan(first, proposal)
        self.assertEqual(first["records"][0], second["records"][0])
        self.assertEqual(second["records"][1]["version"], 2)
        self.assertEqual(second["records"][1]["supersedes"], first["records"][0]["record_hash"])
        second["records"][0]["instruction"] = "silently overwritten"
        with self.assertRaisesRegex(ValueError, "hash"):
            validate_ledger(second)

    def test_source_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "receipt.json").write_bytes(b"receipt")
            validate_ledger(ledger(), root=root)
            (root / "receipt.json").write_bytes(b"changed")
            result = evaluate_plans(ledger(), [], current=datetime.fromisoformat("2026-09-24T12:10:00-04:00"), open_orders={}, root=root)
            self.assertEqual(result["status"], "invalid")
            self.assertTrue(result["block_new_capital"])

    def test_day_expiry_preserves_friday_deadline_without_renewing(self):
        result = evaluate(when="2026-09-24T16:01:00-04:00")
        plan = result["plans"][0]
        self.assertEqual(plan["status"], "expired_pending_verification")
        self.assertEqual(plan["time_exit_at"], "2026-09-25T15:45:00-04:00")
        self.assertEqual(plan["eligible_quantity"], 0)
        self.assertEqual(plan["historical_order_draft"]["session_date"], "2026-09-24")

    def test_time_exit_never_rolls_to_monday(self):
        result = evaluate(when="2026-09-28T12:00:00-04:00")
        self.assertEqual(result["plans"][0]["status"], "time_exit_due_pending_verification")
        self.assertIn("2026-09-25", result["plans"][0]["time_exit_at"])

    def test_generic_hold_cannot_erase_maintained_plan(self):
        result = evaluate()
        rows = [{"ticker": "TEST", "action": "hold_pending_research", "reason": "generic", "current_shares": "4", "whole_shares_to_change": "0", "target_shares": "4"}]
        apply_plan_context(rows, result)
        self.assertEqual(rows[0]["action"], "maintained_plan_review")
        self.assertIn("保留已记录保护条件", rows[0]["current_instruction"])
        self.assertEqual(rows[0]["baseline_research"]["action"], "hold_pending_research")

    def test_concentration_review_is_not_erased_by_hold_plan(self):
        row = record(role="long_term_growth")
        row.update(action="hold", proposed_change_shares=0, order_draft=None)
        context = evaluate(ledger(row))
        rows = [{"ticker": "TEST", "action": "trim_specific_shares_review", "current_shares": 4}]
        apply_plan_context(rows, context)
        self.assertIn("TEST:baseline_risk_review_requires_merge", context["conflicts"])
        self.assertTrue(context["block_new_capital"])

    def test_missing_holding_does_not_invent_a_fill(self):
        self.assertEqual(evaluate(shares=0)["plans"][0]["status"], "position_absent_pending_verification")

    def test_linked_fill_ends_old_sell_when_position_absent(self):
        row = record()
        row["broker_order_id"] = "one"
        result = evaluate(ledger(row), shares=0, orders={"as_of": "2026-09-24T12:00:00-04:00", "complete": True,
            "orders": [{"ticker": "TEST", "order_id": "one", "status": "filled", "side": "sell", "quantity": 4, "remaining_quantity": 0}]})
        self.assertEqual(result["plans"][0]["status"], "completed_observed")
        self.assertEqual(result["plans"][0]["eligible_quantity"], 0)

    def test_partial_position_requires_reconciliation(self):
        plan = evaluate(shares=2)["plans"][0]
        self.assertEqual(plan["status"], "position_changed_pending_verification")
        self.assertEqual(plan["current_shares"], 2)
        self.assertEqual(plan["eligible_quantity"], 0)

    def test_two_active_plans_fail_closed(self):
        second = record()
        second["plan_id"] = "another"
        result = evaluate(append_plan(ledger(), second))
        self.assertIn("TEST:multiple_active_plans", result["conflicts"])

    def test_long_term_role_does_not_inherit_tactical_deadline(self):
        plan = evaluate(ledger(record(role="long_term_growth")))["plans"][0]
        self.assertEqual(plan["role"], "long_term_growth")
        self.assertIsNone(plan["time_exit_at"])

    def test_early_close_expiry_and_invalid_late_deadline(self):
        self.assertEqual(regular_close("2026-11-27").hour, 13)
        row = record()
        row["time_exit_at"] = "2026-11-27T15:45:00-05:00"
        with self.assertRaisesRegex(ValueError, "deadline_after_regular_close"):
            ledger(row)
        row["time_exit_at"] = "2026-11-27T12:45:00-05:00"
        row["order_draft"]["session_date"] = "2026-11-27"
        row["review_at"] = "2026-11-28T12:00:00-05:00"
        plan = evaluate(ledger(row), when="2026-11-27T13:01:00-05:00")["plans"][0]
        self.assertEqual(plan["status"], "time_exit_due_pending_verification")

    def test_rendering_clock_does_not_create_semantic_change(self):
        one = evaluate()
        two = evaluate(when="2026-09-24T12:10:00-04:00")
        self.assertEqual(semantic_state(one), semantic_state(two))

    def test_future_record_not_current(self):
        result = evaluate(when="2026-09-24T11:50:00-04:00")
        self.assertIn("TEST:future_plan_record", result["conflicts"])

    def test_other_order_prevents_competing_sell(self):
        result = evaluate(orders={"as_of": "2026-09-24T12:00:00-04:00", "complete": True,
            "orders": [{"ticker": "TEST", "order_id": "unlinked", "status": "open", "side": "sell"}]})
        self.assertEqual(result["plans"][0]["status"], "order_conflict_pending_review")


if __name__ == "__main__":
    unittest.main()


class ClosureEvidenceTests(unittest.TestCase):
    def test_confirmed_sale_cannot_hide_another_outstanding_sell(self):
        row = record()
        row["broker_order_id"] = "one"
        orders = {"as_of": "2026-09-24T12:00:00-04:00", "complete": True,
            "orders": [{"ticker": "TEST", "order_id": "one", "status": "filled", "side": "sell", "quantity": 4, "remaining_quantity": 0},
                       {"ticker": "TEST", "order_id": "two", "status": "open", "side": "sell", "quantity": 4, "remaining_quantity": 4}]}
        result = evaluate(ledger(row), shares=0, orders=orders)
        self.assertEqual(result["plans"][0]["status"], "order_conflict_pending_review")
        self.assertTrue(result["block_new_capital"])

    def test_incomplete_or_future_fill_cannot_end_plan(self):
        row = record()
        row["broker_order_id"] = "one"
        for change, observed in (({"side": "buy"}, "2026-09-24T12:00:00-04:00"),
                                 ({"quantity": 1}, "2026-09-24T12:00:00-04:00"),
                                 ({}, "2026-09-25T12:00:00-04:00"),
                                 ({}, "2026-09-23T12:00:00-04:00")):
            order = {"ticker": "TEST", "order_id": "one", "status": "filled", "side": "sell", "quantity": 4, "remaining_quantity": 0, **change}
            result = evaluate(ledger(row), shares=0, orders={"as_of": observed, "complete": True, "orders": [order]})
            self.assertEqual(result["plans"][0]["status"], "position_absent_pending_verification")
            self.assertTrue(result["block_new_capital"])

    def test_invalid_time_exit_cannot_be_maintained(self):
        for deadline in ("2026-09-25T00:00:00-04:00", "2026-09-23T15:00:00-04:00"):
            row = record()
            row["time_exit_at"] = deadline
            with self.assertRaisesRegex(ValueError, "deadline_before"):
                ledger(row)
