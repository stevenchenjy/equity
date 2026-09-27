"""Local research work never clears evidence or freezes unrelated valid work."""
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from test_investment_plans import ledger, record
from investment_plans import append_plan, evaluate_plans, RELATIVE_PATH
from workflow_integrity import apply_workflow_integrity, validate_published_workflow


CURRENT = datetime.fromisoformat("2026-09-24T12:05:00-04:00")


def orders(**changes):
    return {"schema_version": "phase5r_open_orders_v1", "as_of": "2026-09-24T12:00:00-04:00",
            "complete": True, "orders": [], "cash_confirmed": True,
            "existing_tactical_risk_confirmed": True, "existing_tactical_risk_usd": 0, **changes}


def sell(ticker="SMTC", **changes):
    return {"ticker": ticker, "order_id": "one", "status": "open", "side": "sell", "quantity": 1,
            "remaining_quantity": 1, "time_in_force": "DAY", "session_date": "2026-09-24", **changes}


class PlanBlockerScopeTests(unittest.TestCase):
    def evaluate(self, order_snapshot=None, payload=None, held=None, when=CURRENT):
        return evaluate_plans(payload or ledger(record("SMTC")), held if held is not None else [{"ticker": "SMTC", "current_shares": 4}],
                              current=when, open_orders=orders() if order_snapshot is None else order_snapshot)

    def test_quote_prompt_and_due_plan_are_local_without_asserting_validity(self):
        result = self.evaluate()
        self.assertFalse(result["block_new_capital"])
        self.assertIn("fresh_quote_and_available_shares_required", result["ticker_blockers"]["SMTC"])
        self.assertEqual(result["plans"][0]["eligible_quantity"], 0)
        after = datetime.fromisoformat("2026-09-25T15:50:00-04:00")
        expired = self.evaluate(orders(as_of=after.isoformat()), when=after)
        self.assertFalse(expired["block_new_capital"])
        self.assertIn("time_exit_due_pending_verification", expired["ticker_blockers"]["SMTC"])
        self.assertEqual(expired["plans"][0]["action"], "reconcile_plan")

    def test_incomplete_or_stale_inventory_cannot_exclude_unknown_buys(self):
        for snapshot in (orders(complete=False), orders(as_of="2026-09-23T11:00:00-04:00"),
                         orders(as_of="2026-09-25T12:00:00-04:00"), [], {}):
            with self.subTest(snapshot=snapshot):
                result = self.evaluate(snapshot)
                self.assertTrue(result["block_new_capital"])
                self.assertTrue(result["global_blockers"])

    def test_fresh_inventory_of_expired_sell_is_local_and_retains_all_shares(self):
        result = self.evaluate(orders(orders=[sell(session_date="2026-09-23")]))
        self.assertFalse(result["block_new_capital"])
        self.assertIn("sell_order_terminal_status_unverified", result["ticker_blockers"]["SMTC"])
        self.assertEqual(result["plans"][0]["current_shares"], 4)
        self.assertEqual(result["plans"][0]["eligible_quantity"], 0)

    def test_order_duplicates_overreservation_and_unknown_buy_commitments_are_global(self):
        for rows in ([sell(), sell()], [sell(quantity=5, remaining_quantity=5)],
                     [sell(side="buy", limit_price=100)],
                     [sell(), sell(order_id="two", side="buy", limit_price=100)],
                     [sell(status="unknown")], [sell(remaining_quantity=-1)],
                     [sell(status="filled", remaining_quantity=1)],
                     [sell(status=[])], [sell(side={})]):
            with self.subTest(orders=rows):
                self.assertTrue(self.evaluate(orders(orders=rows))["block_new_capital"])

    def test_tactical_budget_unknown_is_strategy_specific(self):
        result = self.evaluate(orders(existing_tactical_risk_confirmed=False, existing_tactical_risk_usd=None))
        self.assertFalse(result["block_new_capital"])
        self.assertIn("existing_tactical_risk_unconfirmed", result["strategy_blockers"]["tactical"])
        self.assertIn("existing_tactical_risk_unconfirmed", result["ticker_blockers"]["SMTC"])

    def test_corruption_or_duplicate_positions_is_global(self):
        broken = ledger(record("SMTC"))
        broken["records"][0]["instruction"] = "tampered"
        self.assertIn("plan_ledger_integrity_invalid", self.evaluate(payload=broken)["global_blockers"])
        duplicate = [{"ticker": "SMTC", "current_shares": 4}] * 2
        self.assertIn("position_inventory_integrity_invalid", self.evaluate(held=duplicate)["global_blockers"])


class WorkflowBlockerScopeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / RELATIVE_PATH).parent.mkdir(parents=True)
        (self.root / RELATIVE_PATH).write_text(json.dumps(ledger(record("SMTC"))))
        (self.root / "receipt.json").write_bytes(b"receipt")
        self.order_path = self.root / "05_risk_and_positions/current_open_orders.local.json"
        self.order_path.write_text(json.dumps(orders()))
        self.incorporation = {"companies": {"SMTC": {"positive_decision_eligible": False}}}
        self.news = {"required_coverage_complete": False, "sources": [], "recent_events": []}
        self.views = {"SMTC": {"status": "reassess", "news_review": {"coverage_complete": False}}}
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch("workflow_integrity.read_earnings_incorporation_status", side_effect=lambda **kw: copy.deepcopy(self.incorporation)))
        stack.enter_context(patch("workflow_integrity.current_news_context", side_effect=lambda *a, **kw: copy.deepcopy(self.news)))
        stack.enter_context(patch("workflow_integrity.current_thesis_views", side_effect=lambda *a, **kw: {} if kw.get("candidate_tickers") is not None else copy.deepcopy(self.views)))
        stack.enter_context(patch("workflow_integrity.record_review_states"))

    def decision(self):
        return {"decision_code": "action_review_candidate", "headline": "Baseline research", "decisive_advice": "Baseline",
            "decision_fingerprint": "baseline", "generated_at": CURRENT.isoformat(), "account_conflicts": [],
            "market_gate": {"passed": True}, "evidence_gate": {"passed": True}, "fundamental_gate": {"passed": True},
            "held_positions": [{"ticker": "SMTC", "current_shares": 4, "asset_role": "active_stock", "action": "hold", "reason": "baseline"}],
            "account": {"account_total_value": 4000, "cash_available": 3000, "cash_reserved": 587, "cash_basis": "owner_recorded"},
            "long_horizon_research": {"views": {}, "warnings": []}, "eligible_action_review_candidates": [],
            "eligible_new_position_review_candidates": ["SPY"],
            "watch_candidates": [{"ticker": "SPY", "suggested_whole_shares": "1", "current_price": "100",
                "maximum_review_price": "102", "label": "eligible_core_starter_review", "action": "core_starter_review",
                "stability_distinct_closes": 3, "required_distinct_closes": 2,
                "valuation_applicability": "not_applicable_broad_market_etf"}],
            "capital_allocation": {"proposed_deployment_value": 100}}

    def apply(self, value=None):
        value = value or self.decision()
        apply_workflow_integrity(value, root=self.root, current=CURRENT)
        return value

    def test_unrelated_spy_keeps_existing_eligibility_while_named_research_remains_blocked(self):
        value = self.apply()
        self.assertEqual(value["eligible_new_position_review_candidates"], ["SPY"])
        self.assertEqual(value["watch_candidates"][0]["suggested_whole_shares"], "1")
        self.assertEqual(value["capital_allocation"]["proposed_deployment_value"], 100)
        self.assertEqual(value["workflow_integrity"]["global_blockers"], [])
        self.assertIn("SMTC", value["workflow_integrity"]["blocked_tickers"])
        self.assertTrue(value["human_review_required"])
        self.assertEqual(value["held_positions"][0]["whole_shares_to_change"], "0")
        validate_published_workflow(value, root=self.root, current=CURRENT)

    def test_matching_candidate_cannot_bypass_its_plan_or_company_gaps(self):
        value = self.decision()
        value["watch_candidates"].append({"ticker": "SMTC", "suggested_whole_shares": "1", "current_price": "100",
                                            "maximum_review_price": "102", "action": "buy_review", "label": "eligible_buy_review"})
        value["eligible_new_position_review_candidates"].append("SMTC")
        value["capital_allocation"]["proposed_deployment_value"] = 200
        self.apply(value)
        self.assertEqual(value["eligible_new_position_review_candidates"], ["SPY"])
        self.assertEqual(value["watch_candidates"][1]["suggested_whole_shares"], "0")
        self.assertEqual(value["capital_allocation"]["proposed_deployment_value"], 100)

    def test_existing_spy_core_add_retains_watch_origin_and_never_rewrites_held_plan(self):
        spy = record("SPY", role="broad_core")
        spy.update(action="hold", proposed_change_shares=0, order_draft=None, expected_shares=1,
                   instruction="Retain current one-share core research plan")
        payload = append_plan(ledger(record("SMTC")), spy)
        (self.root / RELATIVE_PATH).write_text(json.dumps(payload))
        value = self.decision()
        value["held_positions"].append({"ticker": "SPY", "asset_role": "core_allocation", "current_shares": 1,
                                        "action": "hold", "reason": "Existing core allocation"})
        self.apply(value)
        self.assertEqual(value["eligible_new_position_review_candidates"], ["SPY"])
        self.assertEqual(value["eligible_action_review_candidates"], [])
        self.assertEqual(value["held_positions"][1]["whole_shares_to_change"], "0")
        self.assertEqual(value["watch_candidates"][0]["suggested_whole_shares"], "1")
        # Its own expired validity still blocks this same ticker regardless of
        # unrelated failures being scoped away.
        spy["valid_until"] = "2026-09-24T12:00:00-04:00"
        payload = append_plan(payload, spy)
        (self.root / RELATIVE_PATH).write_text(json.dumps(payload))
        later = self.decision()
        later["held_positions"].append({"ticker": "SPY", "asset_role": "core_allocation", "current_shares": 1, "action": "hold"})
        self.apply(later)
        self.assertFalse(later["eligible_new_position_review_candidates"])
        self.assertEqual(later["watch_candidates"][0]["suggested_whole_shares"], "0")
        self.assertFalse(later["workflow_integrity"]["global_blockers"])
        self.assertIn("expired_pending_verification", later["workflow_integrity"]["ticker_blockers"]["SPY"])

    def test_unknown_tactical_risk_does_not_reclassify_core_budget(self):
        self.order_path.write_text(json.dumps(orders(existing_tactical_risk_confirmed=False, existing_tactical_risk_usd=None)))
        value = self.apply()
        self.assertEqual(value["eligible_new_position_review_candidates"], ["SPY"])
        self.assertIn("existing_tactical_risk_unconfirmed", value["workflow_integrity"]["strategy_blockers"]["tactical"])

    def test_named_weakening_does_not_hide_unrelated_eligible_proposal_in_renderer(self):
        from email_brief import build_email_view
        value = self.decision()
        value.update(decision_code="fundamental_weakening_review", headline="Old pause-all headline")
        value["fundamental_gate"]["weakening_tickers"] = ["SMTC"]
        self.apply(value)
        self.assertEqual(value["decision_code"], "action_review_candidate")
        self.assertIn("SPY", value["headline"])
        self.assertIn("SMTC", value["headline"])
        self.assertEqual(value["fundamental_gate"]["weakening_tickers"], ["SMTC"])
        self.assertIn("fundamental_weakening_requires_review", value["workflow_integrity"]["ticker_blockers"]["SMTC"])
        self.assertEqual([row["ticker"] for row in build_email_view(value)["plans"]], ["SPY"])
        blocked = self.decision()
        blocked.update(decision_code="fundamental_weakening_review", account_conflicts=["shared account unverified"])
        blocked["fundamental_gate"]["weakening_tickers"] = ["SMTC"]
        self.apply(blocked)
        self.assertFalse(blocked["eligible_new_position_review_candidates"])
        self.assertEqual(build_email_view(blocked)["plans"], [])

    def test_shared_account_and_inventory_failures_still_freeze_every_candidate(self):
        mutations = [lambda value: value["account"].update(cash_available=-1),
                     lambda value: value["account"].update(cash_available=500),
                     lambda value: value["account"].update(account_total_value="NaN"),
                     lambda value: value.update(account_conflicts=["unreconciled_account"]),
                     lambda value: value["market_gate"].update(passed=False),
                     lambda value: value["evidence_gate"].update(passed=False)]
        for mutate in mutations:
            value = self.decision()
            mutate(value)
            self.apply(value)
            self.assertTrue(value["workflow_integrity"]["global_blockers"])
            self.assertFalse(value["eligible_new_position_review_candidates"])
            self.assertEqual(value["watch_candidates"][0]["suggested_whole_shares"], "0")
        self.order_path.write_text(json.dumps(orders(complete=False)))
        value = self.apply()
        self.assertIn("order_inventory_unverified_cannot_bound_buy_commitments", value["workflow_integrity"]["global_blockers"])
        self.assertFalse(value["eligible_new_position_review_candidates"])

    def test_scoping_never_promotes_an_ineligible_baseline_candidate(self):
        value = self.decision()
        value["eligible_new_position_review_candidates"] = []
        value["watch_candidates"][0].update(action="pending_second_distinct_close", suggested_whole_shares="0")
        self.apply(value)
        self.assertFalse(value["eligible_new_position_review_candidates"])
        self.assertEqual(value["watch_candidates"][0]["suggested_whole_shares"], "0")

    def test_publication_rejects_later_inventory_changes_or_plan_expiry(self):
        value = self.apply()
        with self.assertRaisesRegex(ValueError, "plan_state_changed"):
            validate_published_workflow(value, root=self.root, current=datetime.fromisoformat("2026-09-24T16:01:00-04:00"))
        self.order_path.write_text(json.dumps(orders(complete=False)))
        with self.assertRaisesRegex(ValueError, "inputs_changed"):
            validate_published_workflow(value, root=self.root, current=CURRENT)


if __name__ == "__main__":
    unittest.main()
