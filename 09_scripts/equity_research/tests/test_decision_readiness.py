from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import canonical_sha256
import decision_readiness
from decision_readiness import build, validate_projection

NOW = datetime.fromisoformat("2026-10-27T11:00:00-04:00")
AUTHORITY = {"mode": "owner_local_ledger", "local_planning_enabled": True}
STRATEGY = {"strategy_id": "test-reviewed", "version": 1, "authority": "owner_approved"}


def seal(value):
    value["content_sha256"] = canonical_sha256({k: v for k, v in value.items() if k != "content_sha256"})
    return value


def row(ticker="TEST", outcome="NO_ACTION", blockers=None, category=None):
    codes = blockers or []
    return dict(ticker=ticker, decision=outcome, shares=0, estimated_notional=0, order_draft=None,
                blockers=codes, reasons=["Reviewed price does not justify an addition."],
                market_data_timestamp="2026-10-26", dependencies=[dict(code=c, category=category, resolver="recurring_analyst",
                evidence_required="Complete the sourced countercase.") for c in codes])


def draft_row(*, sell=False):
    result = row(outcome="EXIT_REVIEW" if sell else "ACTIONABLE_BUY")
    result.update(shares=2, estimated_notional=200, strategy_source={"adapter": "exit" if sell else "company", **STRATEGY},
                  thesis_summary="A current sourced case.", key_evidence=["retained-primary"], reasons=[])
    result["order_draft"] = dict(side="sell" if sell else "buy", automatic_action_allowed=False,
        entry_order_type="LIMIT", entry_limit=None if sell else 100, exit_price=100 if sell else None,
        entry_window={"starts_at": "2026-10-27T09:30:00-04:00", "ends_at": "2026-10-27T16:00:00-04:00"},
        time_in_force="DAY", invalidation_price=None if sell else 95, planned_loss_per_share=0 if sell else 5,
        planned_total_loss=0 if sell else 10, planned_account_risk_pct=0 if sell else .25,
        initial_reassessment_price=None if sell else 115, reassessment_rule="Review on the named evidence.",
        portfolio_weight_before=5 if sell else 0, portfolio_weight_after=0 if sell else 5,
        cash_before=1000, estimated_cash_after=1200 if sell else 800,
        cancel_conditions=["Skip on changed account."], risk_model="conditional_exit_limit_no_downside_protection" if sell else "reviewed_thesis_invalidation",
        account_value=4000, trigger_rule="Use only the dated complete draft.")
    return result


class DecisionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binding = {"proof": "a" * 64}
        for target, value in (("capital_decision.binding", self.binding),
                              ("capital_decision.load_authority", AUTHORITY),
                              ("capital_decision.select", (STRATEGY, []))):
            handle = patch(target, return_value=value)
            handle.start()
            self.addCleanup(handle.stop)

    def decision(self, rows=None):
        return dict(generated_at=NOW.isoformat(), market_gate={"passed": True, "expected_market_session": "2026-10-26"},
                    capital_decision=seal(dict(schema_version="equity_capital_decision_v1", generated_at=NOW.isoformat(),
                        automatic_action_allowed=False, broker_connected=False, order_placed=False,
                        account_authority=copy.deepcopy(AUTHORITY), source_bindings=copy.deepcopy(self.binding), decisions=rows or [])),
                    plan_continuity={"plans": []}, long_horizon_research={"views": {}, "candidate_views": {}})

    def test_complete_buy_is_exact_projection_and_input_is_unchanged(self):
        d = self.decision([draft_row()]); before = copy.deepcopy(d)
        result = build(self.root, d, NOW)
        self.assertEqual(result["status"], "ready")
        item = result["decisions"][0]
        self.assertEqual(item["classification"], "valid_action")
        self.assertEqual(item["eligible_quantity"], 2)
        self.assertEqual(item["order_draft"], d["capital_decision"]["decisions"][0]["order_draft"])
        self.assertFalse(result["changes_canonical_decisions"])
        self.assertFalse(result["profitability_established"])
        self.assertEqual(d, before)

    def test_valid_exit_survives_independent_new_capital_market_failure(self):
        d = self.decision([draft_row(sell=True)])
        d["market_gate"]["passed"] = False
        result = build(self.root, d, NOW)
        self.assertEqual(result["decisions"][0]["classification"], "valid_action")
        self.assertEqual(result["decisions"][0]["order_draft"]["side"], "sell")

    def test_expired_draft_is_not_displayed_from_an_old_pass(self):
        d = self.decision([draft_row()])
        result = build(self.root, d, NOW.replace(hour=16))
        self.assertEqual(result["status"], "unverified")
        self.assertEqual(result["validation_error"], "capital_draft_expired")
        self.assertEqual(result["decisions"][0]["eligible_quantity"], 0)
        self.assertIsNone(result["decisions"][0]["order_draft"])

    def test_content_or_bound_source_mutation_fails_closed(self):
        for corrupt in ("content", "source"):
            d = self.decision([draft_row()])
            if corrupt == "content":
                d["capital_decision"]["decisions"][0]["shares"] = 3
            else:
                d["capital_decision"]["source_bindings"]["proof"] = "b" * 64
                seal(d["capital_decision"])
            result = build(self.root, d, NOW)
            self.assertEqual(result["status"], "unverified")
            self.assertEqual(result["analyst_handoff"], [])
            self.assertEqual(result["decisions"][0]["classification"], "data_unavailable")
            self.assertEqual(result["decisions"][0]["eligible_quantity"], 0)

    def test_distinguishes_completed_negative_missing_research_and_missing_data(self):
        rows = [row("NEGATIVE"), row("MISSING", "BLOCKED", ["valuation"], "D"),
                row("DATA", "BLOCKED", ["price_history_incomplete"], "B"),
                row("EXPERIMENT", "BLOCKED", ["strategy_not_adopted"], "E")]
        result = build(self.root, self.decision(rows), NOW)
        kinds = {r["ticker"]: r["classification"] for r in result["decisions"]}
        self.assertEqual(kinds, {"NEGATIVE": "justified_no_action", "MISSING": "research_incomplete",
                                 "DATA": "data_unavailable", "EXPERIMENT": "strategy_not_adopted"})

    def test_plan_expiry_retains_original_record_and_no_automatic_hold(self):
        d = self.decision([row("TEST", "BLOCKED", ["company_review_requires_reassessment"], "D")])
        d["plan_continuity"]["plans"] = [dict(ticker="TEST", plan_id="original", version=4,
            record_hash="c" * 64, role="long_term_growth", strategy_horizon="long_term_growth",
            status="expired_pending_verification", valid_until="2026-10-26T16:00:00-04:00",
            review_at="2026-10-26T13:45:00-04:00")]
        result = build(self.root, d, NOW)
        item = result["decisions"][0]
        self.assertEqual(item["classification"], "plan_expired")
        self.assertEqual(item["canonical_decision"], "BLOCKED")
        self.assertEqual(item["accepted_records"][0]["record_sha256"], "c" * 64)
        self.assertEqual(item["review_at"], "2026-10-26T13:45:00-04:00")
        self.assertIn("Do not renew", item["next_step"])

    def test_stale_close_suppresses_current_readiness_not_retained_negative_reasoning(self):
        original = row()
        original["research_case"] = {"conclusion": "Zero new shares because the reviewed economics fail."}
        d = self.decision([original])
        item = build(self.root, d, NOW.replace(hour=17))["decisions"][0]
        self.assertEqual(item["classification"], "data_unavailable")
        self.assertEqual(item["retained_company_conclusion"], original["research_case"]["conclusion"])
        self.assertEqual(item["canonical_decision"], "NO_ACTION")
        self.assertIn("2026-10-27", item["reason"])

    def test_handoff_preserves_authored_step_and_is_bounded(self):
        d = self.decision([row(f"T{i:02}", "BLOCKED", ["valuation"], "D") for i in range(20)])
        d["capital_work_queue"] = {"top_opportunities": [dict(ticker="T00", priority=1, state="blocked",
            next_step="Assess the retained debt maturity footnote against the cash countercase.",
            review_owner="scheduled_research_then_owner_if_eligible", item_id="exact-task", next_review_at=NOW.isoformat())]}
        result = build(self.root, d, NOW)
        self.assertEqual(len(result["decisions"]), 20)
        self.assertEqual(len(result["analyst_handoff"]), 10)
        task = result["analyst_handoff"][0]
        self.assertEqual(task["next_step"], d["capital_work_queue"]["top_opportunities"][0]["next_step"])
        self.assertEqual(task["source_ids"], ["exact-task"])
        self.assertTrue(all(r["eligible_quantity"] == 0 for r in result["decisions"]))

    def test_validated_objective_attachment_routes_to_analysis_without_fabricated_completion(self):
        base = self.root / "04_research/company_research/opportunities.local"
        base.mkdir(parents=True)
        (base / "report.json").write_text("{}")
        report = {"report_hash": "e" * 64, "priority_queue": [dict(ticker="NEW", state="evidence_attached",
            opportunity_id="original-opportunity", reason_code="objective_dossier:source", assessment={})]}
        with patch("research_opportunities.read_report", return_value=report):
            result = build(self.root, self.decision(), NOW)
        task = result["analyst_handoff"][0]
        self.assertEqual(task["classification"], "research_incomplete")
        self.assertEqual(task["source_ids"], ["original-opportunity"])
        self.assertIn("record a sourced conclusion", task["next_step"])
        self.assertEqual(result["opportunity_report_sha256"], "e" * 64)
        self.assertEqual(result["decisions"], [])
        (base / "last_objective_run.json").write_text(json.dumps({"exit_code": 1}))
        with patch("research_opportunities.read_report") as reader:
            failed = build(self.root, self.decision(), NOW)
            reader.assert_not_called()
        self.assertEqual(failed["opportunity_handoff_status"], "unverified")
        self.assertEqual(failed["analyst_handoff"], [])

    def test_held_research_precedes_unheld_work_and_one_company_has_one_task(self):
        d = self.decision([row("A", "BLOCKED", ["valuation"], "D"), row("ZHELD", "BLOCKED", ["valuation"], "D")])
        d["held_positions"] = [{"ticker": "ZHELD", "current_shares": 1}]
        d["capital_work_queue"] = {"top_opportunities": [dict(ticker="ZHELD", priority=4, state="blocked",
            next_step="Assess held adverse evidence first.", review_owner="scheduled_research_then_owner_if_eligible", item_id="held-task")]}
        result = build(self.root, d, NOW)
        self.assertEqual(result["analyst_handoff"][0]["ticker"], "ZHELD")
        self.assertEqual(result["analyst_handoff"][0]["next_step"], "Assess held adverse evidence first.")
        self.assertEqual([t["ticker"] for t in result["analyst_handoff"]].count("ZHELD"), 1)

    def test_no_opportunity_is_valid_and_swing_remains_experimental(self):
        result = build(self.root, self.decision(), NOW)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["decisions"], [])
        self.assertEqual(result["analyst_handoff"], [])
        swing = next(s for s in result["strategies"] if s["strategy_id"] == "swing_5_14_research")
        self.assertEqual(swing["status"], "experimental_not_adopted")
        self.assertFalse(swing["capital_authority"])

    def test_unheld_approved_core_uses_core_route_and_growth_keeps_authored_horizon(self):
        growth = row("COMPANY")
        growth["research_case"] = {"horizon": "Next four reported quarters"}
        d = self.decision([row("QQQM"), growth])
        d["allocation_policy"] = {"core_tickers": ["SPY", "QQQM"]}
        d["plan_continuity"]["plans"] = [dict(ticker="COMPANY", role="long_term_growth", strategy_horizon="long_term_growth")]
        by = {r["ticker"]: r for r in build(self.root, d, NOW)["decisions"]}
        self.assertEqual(by["QQQM"]["strategy_id"], "broad_core")
        self.assertEqual(by["COMPANY"]["horizon"], "Next four reported quarters")

    def test_future_or_naive_clock_does_not_admit_a_projection(self):
        d = self.decision()
        d["capital_decision"]["generated_at"] = (NOW + timedelta(seconds=1)).isoformat()
        seal(d["capital_decision"])
        self.assertEqual(build(self.root, d, NOW)["status"], "unverified")
        with self.assertRaisesRegex(ValueError, "aware_clock"):
            build(self.root, d, NOW.replace(tzinfo=None))

    def test_read_time_source_proof_keeps_dated_reasoning_without_admitting_expired_action(self):
        # The server separately applies its current capital projection. This
        # validator proves the original observation and never renews its draft.
        d = self.decision([draft_row()])
        view = build(self.root, d, NOW)
        implementation = self.root / decision_readiness.IMPLEMENTATION_REL
        implementation.parent.mkdir(parents=True)
        implementation.write_bytes(Path(decision_readiness.__file__).read_bytes())
        view["swing_research"] = {"separate_binding": "owned by its validator"}
        view["swing_benchmarks"] = {"separate_binding": "requires its independent source validation"}
        validate_projection(self.root, view, d["capital_decision"], NOW.replace(hour=17))
        self.assertEqual(view["decisions"][0]["order_draft"]["entry_window"]["ends_at"], "2026-10-27T16:00:00-04:00")
        broken = copy.deepcopy(view)
        broken["analyst_handoff"] = [{"ticker": "FAKE"}]
        with self.assertRaisesRegex(ValueError, "content_invalid"):
            validate_projection(self.root, broken, d["capital_decision"], NOW)
        implementation.write_text("changed implementation")
        with self.assertRaisesRegex(ValueError, "implementation_changed"):
            validate_projection(self.root, view, d["capital_decision"], NOW)


if __name__ == "__main__":
    unittest.main()
