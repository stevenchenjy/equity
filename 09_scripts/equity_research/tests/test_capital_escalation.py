from __future__ import annotations

import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import ET, ExclusiveFileLock, canonical_sha256
import capital_escalation as engine


def stamp(day="2026-10-08", hour=10):
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=ET)


def sealed(value, field="content_sha256"):
    result = copy.deepcopy(value)
    result[field] = canonical_sha256({k: v for k, v in result.items() if k != field})
    return result


def fixture(session="2026-10-07", current=None):
    current = current or stamp()
    config = {"account": {"cash_target_pct": 0, "core_minimum_pct": 30},
              "workflow": {"capital_deployment_escalation": {"required_sessions": 2, "material_excess_cash_pct": 5}}}
    decision = {"generated_at": current.isoformat(), "account": {"account_total_value": 10000, "cash_available": 8000, "cash_reserved": 100},
                "market_gate": {"passed": True, "complete_close_verified": True, "expected_market_session": session},
                "workflow_integrity": {"global_blockers": [], "ticker_blockers": {}},
                "held_positions": [], "plan_continuity": {"plans": []},
                "watch_candidates": [{"ticker": "GROW", "score": 8, "gate_blockers": "company_specific_valuation,upside", "current_price": 110, "maximum_review_price": 90}],
                "eligible_new_position_review_candidates": []}
    contract = sealed({"schema_version": "equity_capital_decision_v1", "generated_at": current.isoformat(),
                       "market_data_timestamp": session, "global_blockers": [], "estimated_uncommitted_cash_after": 7900,
                       "automatic_action_allowed": False, "broker_connected": False, "order_placed": False,
                       "decisions": [{"ticker": "GROW", "decision": "BLOCKED", "shares": 0, "estimated_notional": 0,
                                      "order_draft": None, "blockers": ["company_specific_valuation"], "reasons": ["Research remains incomplete."]}]})
    return decision, contract, config, current


def update(root, decision, contract, config, current):
    p = root / "00_project_control/active_production_config.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(config))
    result = engine.refresh(root, decision, contract, current=current)
    decision["capital_decision"] = contract
    path = root / engine.DAILY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decision))
    return result


def actionable(contract, *, quantity=2):
    contract = copy.deepcopy(contract)
    row = contract["decisions"][0]
    row.update(decision="ACTIONABLE_BUY", shares=quantity, estimated_notional=200 if quantity else 0,
               blockers=[], order_draft={"side": "buy", "entry_order_type": "LIMIT", "entry_limit": 100,
                                        "time_in_force": "DAY", "entry_window": {"ends_at": "2026-10-08T16:00:00-04:00"},
                                        "automatic_action_allowed": False})
    contract["estimated_uncommitted_cash_after"] = 7700 if quantity else 7900
    return sealed(contract)


class CapitalEscalationTests(unittest.TestCase):
    def two_sessions(self, root):
        first = fixture("2026-10-06", stamp("2026-10-07"))
        update(root, *first)
        second = fixture()
        return second, update(root, *second)

    def test_two_completed_observations_trigger_immediate_research_and_exact_gates(self):
        with tempfile.TemporaryDirectory() as name:
            values, result = self.two_sessions(Path(name))
            self.assertTrue(result["triggered"])
            self.assertEqual(result["consecutive_no_action_sessions"], 2)
            self.assertEqual(result["research_priority_tickers"], ["GROW"])
            self.assertEqual(result["research_requests"][0]["urgency"], "immediate")
            self.assertFalse(result["research_requests"][0]["completed"])
            self.assertIn("company_specific_valuation", result["closest_candidate"]["blockers"])
            self.assertIn("upside", result["closest_candidate"]["blockers"])
            self.assertEqual(result["admitted_order_drafts"], [])
            self.assertFalse(result["automatic_action_allowed"])
            state = json.loads((Path(name) / engine.STORE_REL).read_text())
            engine.validate_state(state)
            visible = (Path(name) / engine.TEXT_REL).read_text()
            self.assertIn("GROW / valuation / company_specific_valuation", visible)
            self.assertEqual(engine.research_priorities(Path(name), values[3]), ["GROW"])

    def test_missing_previous_evidence_is_unknown_not_assumed_one_or_two(self):
        d, c, cfg, now = fixture()
        result = engine.evaluate(d, c, config=cfg, current=now)
        self.assertIsNone(result["consecutive_no_action_sessions"])
        self.assertFalse(result["triggered"])
        self.assertEqual(result["session_history_reason"], "prior_completed_session_observation_missing")

    def test_repeated_same_session_changes_neither_counter_nor_events(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            values, first = self.two_sessions(root)
            before = json.loads((root / engine.STORE_REL).read_text())
            d, c, cfg, now = values
            d["generated_at"] = (now + timedelta(minutes=5)).isoformat()
            c["generated_at"] = d["generated_at"]
            result = update(root, d, sealed(c), cfg, now + timedelta(minutes=5))
            after = json.loads((root / engine.STORE_REL).read_text())
            self.assertEqual(first["consecutive_no_action_sessions"], result["consecutive_no_action_sessions"])
            self.assertEqual(before["session_observations"], after["session_observations"])
            self.assertEqual(before["events"], after["events"])

    def test_same_session_actionable_is_sticky_and_breaks_streak(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            values, _ = self.two_sessions(root)
            d, c, cfg, now = values
            result = update(root, d, actionable(c), cfg, now)
            self.assertEqual(result["consecutive_no_action_sessions"], 0)
            self.assertFalse(result["triggered"])
            self.assertEqual(result["status"], "actionable_available")
            later = update(root, d, c, cfg, now + timedelta(minutes=1))
            self.assertEqual(later["consecutive_no_action_sessions"], 0)
            state = json.loads((root / engine.STORE_REL).read_text())
            self.assertTrue(state["session_observations"][-1]["actionable_seen"])
            next_values = fixture("2026-10-08", stamp("2026-10-09"))
            next_result = update(root, *next_values)
            self.assertEqual(next_result["consecutive_no_action_sessions"], 1)

    def test_weekend_is_same_completed_session_then_monday_adjacent(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            update(root, *fixture("2026-10-01", stamp("2026-10-02")))
            result = update(root, *fixture("2026-10-02", stamp("2026-10-03")))
            self.assertEqual(result["consecutive_no_action_sessions"], 2)
            sunday = update(root, *fixture("2026-10-02", stamp("2026-10-04")))
            self.assertEqual(sunday["consecutive_no_action_sessions"], 2)
            monday = update(root, *fixture("2026-10-05", stamp("2026-10-06")))
            self.assertEqual(monday["consecutive_no_action_sessions"], 3)

    def test_holiday_does_not_create_missing_session(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            update(root, *fixture("2026-11-25", stamp("2026-11-26")))
            friday = update(root, *fixture("2026-11-27", stamp("2026-11-28")))
            self.assertEqual(friday["consecutive_no_action_sessions"], 2)

    def test_gap_is_unknown_then_two_fresh_adjacent_sessions_are_known(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            update(root, *fixture("2026-10-02", stamp("2026-10-03")))
            gap = update(root, *fixture("2026-10-06", stamp("2026-10-07")))
            self.assertIsNone(gap["consecutive_no_action_sessions"])
            self.assertEqual(gap["session_history_reason"], "completed_session_history_gap")
            closed = update(root, *fixture())
            self.assertEqual(closed["consecutive_no_action_sessions"], 2)
            self.assertTrue(closed["triggered"])

    def test_old_session_cannot_regress_persisted_ledger(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            update(root, *fixture("2026-10-07", stamp("2026-10-07", 18)))
            old = (root / engine.STORE_REL).read_bytes()
            values = fixture("2026-10-06", stamp("2026-10-08", 7))
            result = update(root, *values)
            self.assertIsNone(result["consecutive_no_action_sessions"])
            self.assertEqual(result["session_history_reason"], "completed_session_regression")
            self.assertEqual((root / engine.STORE_REL).read_bytes(), old)

    def test_unverified_intraday_and_future_sessions_do_not_count(self):
        d, c, cfg, now = fixture()
        for change in ("passed", "complete_close_verified", "future", "hash"):
            altered, contract = copy.deepcopy(d), copy.deepcopy(c)
            if change == "future":
                altered["market_gate"]["expected_market_session"] = "2026-10-08"
                contract["market_data_timestamp"] = "2026-10-08"
            elif change == "hash":
                contract["decisions"][0]["decision"] = "HOLD"
            else:
                altered["market_gate"][change] = False
            if change != "hash":
                contract = sealed(contract)
            result = engine.evaluate(altered, contract, config=cfg, current=now)
            self.assertEqual(result["status"], "session_unverified")
            self.assertFalse(result["triggered"])

    def test_corrupt_json_hash_chain_and_future_state_are_preserved(self):
        for mode in ("json", "hash", "events", "future"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                values, _ = self.two_sessions(root)
                state_path = root / engine.STORE_REL
                if mode == "json":
                    state_path.write_text("{broken")
                else:
                    state = json.loads(state_path.read_text())
                    if mode == "hash":
                        state["session_observations"][0]["actionable_seen"] = True
                    elif mode == "events":
                        state["events"][0]["previous_event_sha256"] = "wrong"
                        state = sealed(state, "integrity_sha256")
                    else:
                        state["generated_at"] = (values[3] + timedelta(days=1)).isoformat()
                        state = sealed(state, "integrity_sha256")
                    state_path.write_text(json.dumps(state))
                before = state_path.read_bytes()
                result = update(root, *values)
                self.assertIsNone(result["consecutive_no_action_sessions"])
                self.assertEqual(result["status"], "history_unverified")
                self.assertFalse(result["triggered"])
                self.assertEqual(state_path.read_bytes(), before)
                self.assertEqual(engine.research_priorities(root, values[3]), [])

    def test_account_blocker_prevents_trigger_but_preserves_closest_gates(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            values, _ = self.two_sessions(root)
            d, c, cfg, now = values
            c["global_blockers"] = ["current_account_snapshot_stale"]
            result = update(root, d, sealed(c), cfg, now)
            self.assertEqual(result["status"], "account_integrity_blocked")
            self.assertFalse(result["triggered"])
            self.assertEqual(result["account_integrity_blockers"], ["current_account_snapshot_stale"])
            self.assertTrue(result["cash"]["materially_above_target"])
            self.assertEqual(result["closest_candidate"]["ticker"], "GROW")
            self.assertIn("current_account_snapshot_stale", result["closest_candidate"]["blockers"])
            self.assertFalse(result["research_requests"][0]["urgency"] == "immediate")

    def test_issuer_blocker_is_not_account_wide_integrity_blocker(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            values, _ = self.two_sessions(root)
            d, c, cfg, now = values
            c["decisions"][0]["blockers"].append("issuer_news_coverage_incomplete")
            result = update(root, d, sealed(c), cfg, now)
            self.assertTrue(result["triggered"])
            self.assertEqual(result["account_integrity_blockers"], [])

    def test_material_cash_threshold_uses_percentage_points_above_approved_target(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            values, _ = self.two_sessions(root)
            d, c, cfg, now = values
            cfg["account"]["cash_target_pct"] = 74
            at_threshold = update(root, *values)
            self.assertEqual(at_threshold["cash"]["excess_cash_pct"], 5)
            self.assertFalse(at_threshold["triggered"])
            cfg["account"]["cash_target_pct"] = 73.9
            excess = update(root, *values)
            self.assertTrue(excess["triggered"])
            self.assertTrue(excess["cash"]["material_threshold_is_operational_trigger_not_risk_limit"])

    def test_invalid_cash_and_trigger_config_fail_closed(self):
        d, c, cfg, now = fixture()
        for value in ("NaN", -1, 12000):
            d["account"]["cash_available"] = value
            result = engine.evaluate(d, c, config=cfg, current=now)
            self.assertEqual(result["status"], "account_integrity_blocked")
            self.assertIsNone(result["cash"]["excess_cash_usd"])
        d, c, cfg, now = fixture()
        cfg["workflow"]["capital_deployment_escalation"]["required_sessions"] = 1
        result = engine.evaluate(d, c, config=cfg, current=now)
        self.assertFalse(result["triggered"])
        self.assertIn("capital_escalation_trigger_policy_invalid", [g["code"] for g in result["gates"]])

    def test_existing_admitted_draft_preserved_exactly_and_unexecuted_cash_retained(self):
        d, c, cfg, now = fixture()
        c = actionable(c)
        before = copy.deepcopy(c)
        result = engine.evaluate(d, c, config=cfg, current=now)
        self.assertEqual(result["admitted_order_drafts"][0]["order_draft"], c["decisions"][0]["order_draft"])
        self.assertEqual(result["ranked_capital_uses"][0]["shares"], 2)
        self.assertEqual(result["cash"]["uncommitted_cash_usd"], 7900)
        self.assertEqual(c, before)
        self.assertEqual(result["consecutive_no_action_sessions"], 0)

    def test_zero_or_hypothetical_draft_never_becomes_positive_option(self):
        d, c, cfg, now = fixture()
        zero = engine.evaluate(d, actionable(c, quantity=0), config=cfg, current=now)
        self.assertEqual(zero["admitted_order_drafts"], [])
        c["decisions"][0]["hypothetical_quantity"] = 20
        result = engine.evaluate(d, sealed(c), config=cfg, current=now)
        self.assertEqual(result["ranked_capital_uses"][0]["shares"], 0)
        self.assertIsNone(result["ranked_capital_uses"][0]["order_draft"])

    def test_exit_draft_proceeds_never_adjust_observed_uncommitted_cash(self):
        d, c, cfg, now = fixture()
        c["decisions"].append({"ticker": "EXIT", "decision": "EXIT_REVIEW", "shares": 2,
                               "estimated_notional": 200, "blockers": [], "reasons": ["Review held thesis exit."],
                               "order_draft": {"side": "sell", "automatic_action_allowed": False}})
        result = engine.evaluate(d, sealed(c), config=cfg, current=now)
        self.assertEqual(result["cash"]["uncommitted_cash_usd"], 7900)
        self.assertEqual(result["admitted_order_drafts"], [])

    def test_exact_gate_categories_and_three_routes_include_missing_route(self):
        d, c, cfg, now = fixture()
        c["decisions"][0]["blockers"] = ["company_specific_valuation", "latest_earnings_pending_incorporation", "entry_above_canonical_maximum", "cash_or_risk_budget_below_one_share", "strategy_not_production_adopted"]
        result = engine.evaluate(d, sealed(c), config=cfg, current=now)
        categories = {g["code"]: g["category"] for g in result["gates"]}
        self.assertEqual(categories["company_specific_valuation"], "valuation")
        self.assertEqual(categories["latest_earnings_pending_incorporation"], "evidence")
        self.assertEqual(categories["entry_above_canonical_maximum"], "price")
        self.assertEqual(categories["cash_or_risk_budget_below_one_share"], "risk")
        self.assertEqual(categories["strategy_not_production_adopted"], "policy")
        self.assertEqual({r["route"] for r in result["routes"]}, set(engine.ROUTES))
        absent = next(r for r in result["routes"] if r["route"] == "existing_quality_holding")
        self.assertEqual(absent["status"], "unavailable")
        self.assertEqual(absent["blockers"], ["no_existing_company_holding"])

    def test_hold_core_add_gates_explain_covered_floor_without_adding_shares(self):
        d, c, cfg, now = fixture()
        d["held_positions"] = [{"ticker": "CORE", "asset_role": "core_allocation", "current_shares": 4, "current_price": 1000}]
        d["watch_candidates"].append({"ticker": "CORE", "valuation_applicability": "not_applicable_broad_market_etf", "gate_blockers": "entry"})
        c["decisions"].append({"ticker": "CORE", "decision": "HOLD", "shares": 0, "estimated_notional": 0, "order_draft": None, "blockers": [], "reasons": ["Hold current position."]})
        result = engine.evaluate(d, sealed(c), config=cfg, current=now)
        core = next(r for r in result["ranked_capital_uses"] if r["ticker"] == "CORE")
        self.assertIn("whole_share_target_gap", core["blockers"])
        self.assertIn("entry", core["blockers"])
        self.assertFalse(core["eligible"])
        self.assertEqual(core["shares"], 0)
        self.assertEqual(result["closest_candidate"]["ticker"], "GROW")
        route = next(r for r in result["routes"] if r["route"] == "diversified_core_growth")
        self.assertEqual(route["status"], "unavailable")

    def test_ranking_does_not_promote_momentum_or_turn_negative_valuation_into_research(self):
        d, c, cfg, now = fixture()
        d["watch_candidates"].append({"ticker": "HYPE", "score": 10, "momentum_score": 100, "gate_blockers": "score,upside,reward_to_risk"})
        c["decisions"].append({"ticker": "HYPE", "decision": "NO_ACTION", "shares": 0, "estimated_notional": 0, "order_draft": None, "blockers": [], "reasons": ["upside"]})
        result = engine.evaluate(d, sealed(c), config=cfg, current=now)
        self.assertEqual(result["admitted_order_drafts"], [])
        self.assertNotIn("HYPE", result["research_priority_tickers"])
        hype = next(r for r in result["ranked_capital_uses"] if r["ticker"] == "HYPE")
        self.assertIn("upside", hype["blockers"])

    def test_unknown_candidate_cannot_outrank_known_canonical_economics(self):
        d, c, cfg, now = fixture()
        d["watch_candidates"][0]["gate_blockers"] = "score,upside,reward_to_risk"
        c["decisions"][0]["blockers"] = []
        c["decisions"].append({"ticker": "UNKNOWN", "decision": "BLOCKED", "shares": 0, "estimated_notional": 0,
                               "order_draft": None, "blockers": ["thesis_missing"], "reasons": ["Unknown issuer case."]})
        result = engine.evaluate(d, sealed(c), config=cfg, current=now)
        self.assertEqual(result["closest_candidate"]["ticker"], "GROW")
        self.assertFalse(result["closest_candidate"]["eligible"])
        self.assertEqual(next(r for r in result["routes"] if r["route"] == "researched_growth_candidate")["status"], "research_incomplete")

    def test_gate_prose_uses_owner_thresholds_and_observed_values(self):
        d, c, cfg, now = fixture()
        cfg["account"]["candidate_sizing_tiers"] = [{"minimum_score": 7, "minimum_expected_upside_pct": 10, "minimum_reward_to_risk": 1.25}]
        d["watch_candidates"][0].update(score=6.5, expected_upside_pct=-60.7, reward_to_risk_estimate=-.8,
                                          gate_blockers="score,upside,reward_to_risk,entry")
        result = engine.evaluate(d, c, config=cfg, current=now)
        messages = {g["code"]: g["evidence_required"] for g in result["gates"]}
        self.assertIn("6.50", messages["score"])
        self.assertIn("7.00", messages["score"])
        self.assertIn("$110.00", messages["entry"])
        self.assertIn("$90.00", messages["entry"])
        self.assertIn("-60.70%", messages["upside"])
        self.assertIn("10.00%", messages["upside"])
        self.assertIn("-0.80", messages["reward_to_risk"])
        self.assertIn("1.25", messages["reward_to_risk"])

    def test_verified_fund_identity_changes_comparison_route_without_admission(self):
        d, c, cfg, now = fixture()
        d["research_opportunities"] = {"decision_candidates": [{"ticker": "GROW", "security_type": "ETF", "blockers": ["issuer_prospectus_and_structure_review_required"]}]}
        result = engine.evaluate(d, c, config=cfg, current=now)
        self.assertEqual(result["ranked_capital_uses"][0]["route"], "diversified_core_growth")
        self.assertIn("issuer_prospectus_and_structure_review_required", result["ranked_capital_uses"][0]["blockers"])
        self.assertEqual(result["admitted_order_drafts"], [])

    def test_priority_top_three_unique_and_stale_or_tampered_report_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            first = fixture("2026-10-06", stamp("2026-10-07"))
            update(root, *first)
            d, c, cfg, now = fixture()
            for ticker in ("TWO", "THREE", "FOUR"):
                d["watch_candidates"].append({"ticker": ticker, "score": 7, "gate_blockers": "maintained_company_research_incomplete"})
                c["decisions"].append({"ticker": ticker, "decision": "BLOCKED", "shares": 0, "estimated_notional": 0, "order_draft": None, "blockers": ["maintained_company_research_incomplete"], "reasons": ["Incomplete."]})
            result = update(root, d, sealed(c), cfg, now)
            self.assertEqual(len(result["research_priority_tickers"]), 3)
            self.assertEqual(len(set(result["research_priority_tickers"])), 3)
            self.assertEqual(engine.research_priorities(root, now + timedelta(days=2)), [])
            report = root / engine.REPORT_REL
            result["research_requests"][0]["ticker"] = "UNBOUND"
            report.write_text(json.dumps(result))
            self.assertEqual(engine.research_priorities(root, now), [])

    def test_hash_bound_bootstrap_deduplicates_sessions_and_ignores_unbound_legacy(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / engine.HISTORY_REL
            path.parent.mkdir(parents=True)
            prior, rows = "", []
            for session, day in (("2026-10-02", "2026-10-03"), ("2026-10-05", "2026-10-06"), ("2026-10-05", "2026-10-06")):
                _, contract, _, now = fixture(session, stamp(day))
                from capital_decision import meaning
                workflow = {"capital_decision": meaning(contract)}
                row = {"schema_version": "equity_decision_history_v1", "recorded_at": now.isoformat(), "workflow": workflow,
                       "workflow_fingerprint": canonical_sha256(workflow), "previous_hash": prior}
                row = sealed(row, "record_hash")
                rows.append(row)
                prior = row["record_hash"]
            path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            result = update(root, *fixture("2026-10-06", stamp("2026-10-07")))
            self.assertEqual(result["consecutive_no_action_sessions"], 3)
            self.assertTrue(result["triggered"])
            state = json.loads((root / engine.STORE_REL).read_text())
            self.assertEqual(len(state["session_observations"]), 3)
            self.assertEqual(state["origin"], "verified_hash_bound_decision_history")

    def test_bad_history_binding_does_not_silently_start_clean_history(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            path = root / engine.HISTORY_REL
            path.parent.mkdir(parents=True)
            row = sealed({"schema_version": "equity_decision_history_v1", "recorded_at": stamp().isoformat(),
                          "workflow": {}, "workflow_fingerprint": "bad", "previous_hash": ""}, "record_hash")
            path.write_text(json.dumps(row) + "\n")
            result = update(root, *fixture())
            self.assertEqual(result["status"], "history_unverified")
            self.assertFalse((root / engine.STORE_REL).exists())
            self.assertFalse(result["triggered"])

    def test_research_priority_authority_expires_when_account_facts_or_latest_decision_change(self):
        for mode in ("account", "orders", "decision"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                values, _ = self.two_sessions(root)
                self.assertEqual(engine.research_priorities(root, values[3]), ["GROW"])
                if mode == "decision":
                    path = root / engine.DAILY_REL
                    decision = json.loads(path.read_text())
                    decision["capital_decision"]["content_sha256"] = "new blocked decision"
                    path.write_text(json.dumps(decision))
                else:
                    path = root / ("05_risk_and_positions/current_account_state.local.json" if mode == "account" else "05_risk_and_positions/current_open_orders.local.json")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('{"changed":true}')
                self.assertEqual(engine.research_priorities(root, values[3]), [])

    def test_refresh_lock_prevents_concurrent_ledger_write(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            d, c, cfg, now = fixture()
            p = root / "00_project_control/active_production_config.json"
            p.parent.mkdir(parents=True)
            p.write_text(json.dumps(cfg))
            with ExclusiveFileLock(root / engine.LOCK_REL):
                with self.assertRaisesRegex(RuntimeError, "lock already held"):
                    engine.refresh(root, d, c, current=now)
            self.assertFalse((root / engine.STORE_REL).exists())


if __name__ == "__main__":
    unittest.main()
