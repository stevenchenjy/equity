from __future__ import annotations
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from _support import SCRIPT_DIR  # noqa: F401
from capital_work_queue import (STORE_REL, build_capital_work_queue, refresh_capital_work_queue,
                               semantic_state, validate_state)

WHEN = datetime.fromisoformat("2026-09-27T14:00:00-04:00")


def plan(ticker="SMTC", status="time_exit_due_pending_verification", version=2):
    return {"ticker":ticker, "plan_id":ticker+"-maintained", "version":version,
        "record_hash":str(version)*64, "role":"tactical", "status":status,
        "review_at":"2026-09-25T09:35:00-04:00", "time_exit_at":"2026-09-25T15:45:00-04:00",
        "blockers":["order_snapshot_requires_recheck"], "sources":[{"path":"receipt.json", "sha256":"a"*64}]}


def decision():
    return {"generated_at":"2026-09-27T13:08:48-04:00", "account":{"account_total_value":"4000.00",
        "cash_available":"2936.80", "cash_reserved":"587.00", "cash_basis":"owner_recorded"},
        "capital_allocation":{"proposed_deployment_value":0},
        "plan_continuity":{"status":"needs_reconciliation", "ledger_head":"b"*64, "plans":[plan(), plan("RBRK", "expired_pending_verification"),
            plan("APP", "completed_observed"), plan("IOT", "completed_observed")]},
        "watch_candidates":[{"ticker":"SPY", "label":"watchlist", "action":"core_allocation_tranche_review",
            "valuation_applicability":"not_applicable_broad_market_etf", "gate_blockers":"maintained_plans_require_reconciliation"},
            {"ticker":"DDOG", "label":"watchlist", "action":"watch_only", "gate_blockers":"valuation,reward_to_risk"}],
        "eligible_new_position_review_candidates":[]}


def negative_opportunity(ticker="NVDA"):
    return {"ticker": ticker, "state": "economics_failed", "reason_code": "recorded_assessment:"+"a"*64,
        "last_evidence_at": "2026-09-25T13:00:00-04:00", "first_seen_at": "2026-09-25T13:00:00-04:00",
        "first_observation": {"trigger": "company_business_review"}, "observations": [], "blockers": ["canonical_valuation_pending"],
        "assessment": {"assessed_at": "2026-09-27T13:30:00-04:00", "next_review_at": "2026-09-28T13:45:00-04:00",
            "valuation_status": "reviewed", "conclusion": "economics_failed"},
        "transitions": [{"owner": "analyst_assessment", "to_state": "economics_failed", "recorded_at": "2026-09-27T13:31:00-04:00"}]}


def write_valid_backlog(root):
    import hashlib
    from capital_work_queue import BACKLOG_REL
    from daily_common import canonical_sha256
    fundamentals=root/"03_source_data/equity_research/daily_fundamentals.csv"
    fundamentals.parent.mkdir(parents=True,exist_ok=True)
    if not fundamentals.exists(): fundamentals.write_bytes(b"ticker,value\nTEST,3\n")
    gap={"ticker":"DDOG","kind":"reasoning","reason_code":"valuation_judgment_pending"}
    gap.update(gap_id=canonical_sha256(gap),status="pending_research",next_step="Verify the specific valuation countercase.")
    report={"schema_version":"equity_research_backlog_v1","generated_at":WHEN.isoformat(),"status":"ready",
        "automatic_action_allowed":False,"items":[gap],"priority_queue":[{"ticker":"DDOG","priority_rank":1,"gap_ids":[gap["gap_id"]],"priority_reasons":["recorded_gap"]}],
        "issuer_queue":[],"attempts_latest_run":[],"selected_tickers":[],"work_budget_tickers":3,"counts":{"pending_research":1},
        "history_records":0,"history_head_hash":"","objective_dossiers_completed":0,"financial_fields_completed":0,"canonical_numeric_updates":0,
        "inputs":{"fundamentals_sha256_after":hashlib.sha256(fundamentals.read_bytes()).hexdigest()}}
    report["report_hash"]=canonical_sha256(report)
    path=root/BACKLOG_REL;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report))
    return report


class CapitalWorkQueueTests(unittest.TestCase):
    def build(self, d=None, previous=None, **kwargs):
        return build_capital_work_queue(d or decision(), previous, current=kwargs.pop("current", WHEN), **kwargs)

    def test_cash_buckets_do_not_allocate_overlapping_reason_amounts(self):
        d=decision(); before=copy.deepcopy(d); result=self.build(d)
        cash=result["cash_explanation"]
        self.assertEqual(cash["planning_capital_usd"],4000)
        self.assertEqual(cash["planning_cash_usd"],2936.8)
        self.assertEqual(cash["strategic_reserve_usd"],587)
        self.assertEqual(cash["unallocated_research_cash_usd"],2349.8)
        self.assertFalse(cash["reason_amounts_are_additive"])
        self.assertFalse(cash["execution_buying_power_verified"])
        self.assertIsNone(cash["execution_buying_power_usd"])
        self.assertEqual(d,before)
        self.assertTrue(all(r["eligible_quantity"] == 0 for r in result["items"]))

    def test_completed_plans_are_absent_and_original_deadlines_remain(self):
        result=self.build()
        self.assertEqual({r["ticker"] for r in result["plan_reassessment_queue"]},{"RBRK","SMTC"})
        for row in result["plan_reassessment_queue"]:
            self.assertEqual(row["original_time_exit_at"],"2026-09-25T15:45:00-04:00")
            self.assertEqual(row["plan_record_hash"],"2"*64)
            self.assertEqual(row["next_review_at"],"2026-09-28T09:45:00-04:00")
        self.assertFalse(result["automatic_action_allowed"])

    def test_unchanged_refresh_no_ticket_or_event_duplicates_and_no_deadline_roll(self):
        first=self.build()
        d=decision(); d["generated_at"]="2026-09-29T13:00:00-04:00"
        second=self.build(d,previous=first,current=datetime.fromisoformat("2026-09-29T14:00:00-04:00"))
        self.assertEqual(first["events"],second["events"])
        self.assertEqual(len(first["items"]),len(second["items"]))
        self.assertEqual(first["plan_reassessment_queue"][0]["next_review_at"],second["plan_reassessment_queue"][0]["next_review_at"])
        self.assertEqual(semantic_state(first),semantic_state(second))
        self.assertNotEqual(first["generated_at"],second["generated_at"])
        self.assertEqual(len(second["runs"]),len(first["runs"])+1)

    def test_terminal_completion_retains_history_and_absence_is_not_success(self):
        first=self.build(); d=decision(); d["plan_continuity"]["plans"][0]["status"]="completed_observed"
        d["plan_continuity"]["plans"]= [p for p in d["plan_continuity"]["plans"] if p["ticker"]!="RBRK"]
        second=self.build(d,first)
        by={r["item_id"]:r for r in second["items"]}
        self.assertEqual(by["plan:SMTC-maintained:v2"]["state"],"resolved")
        self.assertEqual(by["plan:RBRK-maintained:v2"]["state"],"not_observed")
        self.assertEqual(second["events"][:len(first["events"])],first["events"])
        self.assertEqual(second["plan_reassessment_queue"],[])

    def test_failed_setup_and_superseded_version_keep_prior_evidence(self):
        d=decision(); d["plan_continuity"]["plans"][0].update(status="failed",setup_status="failed")
        first=self.build(d)
        d["plan_continuity"]["plans"][0]=plan(version=3)
        second=self.build(d,first)
        old=next(r for r in second["items"] if r["item_id"]=="plan:SMTC-maintained:v2")
        self.assertEqual(old["state"],"superseded")
        self.assertEqual(old["setup_outcome"],"failed")
        self.assertEqual(old["plan_record_hash"],"2"*64)

    def test_missing_canonical_context_does_not_invent_an_empty_current_queue(self):
        with self.assertRaisesRegex(ValueError,"canonical_context"):
            self.build({"generated_at":WHEN.isoformat(),"account":{}})

    def test_invalid_cash_is_unknown_not_zero_or_free_to_deploy(self):
        d=decision(); d["account"]["cash_available"]="nan"
        cash=self.build(d)["cash_explanation"]
        self.assertEqual(cash["status"],"unverified")
        self.assertIsNone(cash["planning_cash_usd"])
        self.assertIsNone(cash["unallocated_research_cash_usd"])

    def test_backlog_priorities_link_work_without_changing_authority(self):
        result=self.build(research_backlog={"priority_queue":[{"ticker":"DDOG","gap_ids":["DDOG:debt"],"priority_reasons":["verified_numeric_gap"]}]})
        item=next(r for r in result["top_opportunities"] if r["ticker"]=="DDOG")
        self.assertEqual(item["gap_ids"],["DDOG:debt"])
        self.assertEqual(item["review_owner"],"scheduled_research_then_owner_if_eligible")
        self.assertEqual(item["eligible_quantity"],0)

    def core_context(self, *, shares="2", price="779.09"):
        d = decision()
        d["held_positions"] = [{"ticker": "SPY", "asset_role": "core_allocation",
            "current_shares": shares, "current_price": price}]
        d["watch_candidates"] += [{"ticker": ticker, "gate_blockers": "valuation"} for ticker in ("APP", "NVDA")]
        return d, {"account": {"core_minimum_pct": 30, "core_target_pct": 30}}

    def test_satisfied_core_retains_monitoring_history_without_company_research_slot(self):
        d, config = self.core_context()
        result = self.build(d, config=config)
        self.assertEqual({r["ticker"] for r in result["top_opportunities"]}, {"APP", "DDOG", "NVDA"})
        spy = next(r for r in result["items"] if r["item_id"] == "opportunity:SPY")
        self.assertEqual(spy["state"], "monitoring")
        self.assertEqual(spy["core_coverage"]["remaining_minimum_value_usd"], 0)
        self.assertIn("does not propose an add or a trim", spy["next_step"])
        repeat = self.build(d, result, config=config)
        self.assertEqual(result["events"], repeat["events"])
        self.assertEqual(next(r for r in repeat["items"] if r["ticker"] == "SPY")["occurrence"], 1)
        from capital_work_queue import render_report
        self.assertIn("Core allocation already satisfied", render_report(result))
        self.assertIn("no company-research slot assigned", render_report(result))

    def test_below_floor_or_unverified_core_still_has_priority_and_held_risk_is_preserved(self):
        for shares, price in (("1", "779.09"), ("2", "")):
            with self.subTest(shares=shares, price=price):
                d, config = self.core_context(shares=shares, price=price)
                # Hypothetical additions must not satisfy the present minimum.
                d["capital_allocation"]["post_review_core_value"] = "1600"
                d["plan_continuity"]["plans"].append(plan("SPY", "review_due"))
                result = self.build(d, config=config)
                self.assertEqual(result["top_opportunities"][0]["ticker"], "SPY")
                self.assertEqual(result["top_opportunities"][0]["priority"], 3)
                self.assertIn("SPY", {r["ticker"] for r in result["plan_reassessment_queue"]})
                self.assertTrue(all(r["priority"] < 3 for r in result["plan_reassessment_queue"]))

    def test_satisfied_core_still_allows_real_evidence_gap_or_eligible_research(self):
        for reason in ("gap", "held_review", "eligible"):
            d, config = self.core_context()
            kwargs = {}
            if reason == "gap":
                kwargs["research_backlog"] = {"priority_queue": [{"ticker": "SPY", "priority_rank": 1, "gap_ids": ["fund-gap"]}],
                    "items": [{"gap_id": "fund-gap", "status": "pending_research", "next_step": "Review changed fund mandate."}]}
            elif reason == "held_review":
                d["held_positions"][0]["research_review_required"] = True
            else:
                d["eligible_new_position_review_candidates"] = ["SPY"]
            result = self.build(d, config=config, **kwargs)
            spy = next(r for r in result["items"] if r["item_id"] == "opportunity:SPY")
            self.assertIn(spy["state"], {"blocked", "research_ready"})
            self.assertEqual(spy["priority"], 4)
            self.assertEqual(spy["eligible_quantity"], 0)

    def test_satisfied_core_reopens_on_shortfall_without_erasing_prior_due_or_history(self):
        d, config = self.core_context(shares="1")
        first = self.build(d, config=config)
        d["held_positions"][0]["current_shares"] = "2"
        satisfied = self.build(d, first, config=config)
        d["held_positions"][0]["current_shares"] = "1"
        reopened = self.build(d, satisfied, config=config)
        spy = next(r for r in reopened["items"] if r["item_id"] == "opportunity:SPY")
        self.assertEqual(spy["state"], "blocked")
        self.assertEqual(spy["occurrence"], 2)
        self.assertEqual(reopened["events"][:len(first["events"])], first["events"])
        self.assertEqual(spy["first_seen_at"], first["generated_at"])

    def test_overdue_report_keeps_due_date_and_separates_next_scheduled_check(self):
        from capital_work_queue import render_report
        first = self.build()
        d = decision(); d["generated_at"] = "2026-09-29T13:00:00-04:00"
        result = self.build(d, first, current=datetime.fromisoformat("2026-09-29T14:00:00-04:00"))
        text = render_report(result)
        self.assertIn("Overdue since: 2026-09-28T09:45:00-04:00", text)
        self.assertIn("Next automatic research review: 2026-09-30T08:00:00-04:00", text)
        self.assertNotIn("Next review:", text)

    def test_recorded_negative_case_waits_without_removing_canonical_gaps(self):
        d, config = self.core_context()
        d["market_gate"] = {"complete_close_verified": True, "expected_market_session": "2026-09-25"}
        report = {"opportunities": [negative_opportunity()]}
        first = self.build(d, config=config, opportunity_report=report)
        nvda = next(r for r in first["items"] if r["ticker"] == "NVDA")
        self.assertEqual(nvda["state"], "assessed_waiting_reassessment")
        self.assertEqual(nvda["blockers"], ["valuation"])
        self.assertNotIn("NVDA", [r["ticker"] for r in first["top_opportunities"]])
        self.assertEqual(self.build(d, first, config=config, opportunity_report=report)["events"], first["events"])
        from capital_work_queue import render_report
        self.assertIn("Completed negative research awaiting changed evidence", render_report(first))
        for change in ("new_source", "new_close", "review_due", "held", "missing_view"):
            altered, view = copy.deepcopy(d), copy.deepcopy(report)
            current = WHEN
            if change == "new_source":
                view["opportunities"][0]["last_evidence_at"] = "2026-09-27T13:40:00-04:00"
            elif change == "new_close":
                altered["market_gate"]["expected_market_session"] = "2026-09-28"
            elif change == "review_due":
                current = datetime.fromisoformat("2026-09-28T14:00:00-04:00")
                altered["generated_at"] = current.isoformat()
            elif change == "held":
                altered["held_positions"].append({"ticker": "NVDA", "asset_role": "active_stock", "current_shares": "1", "current_price": "239.24"})
            else:
                view = None
            with self.subTest(change=change):
                second = self.build(altered, first, config=config, current=current, opportunity_report=view)
                self.assertEqual(next(r for r in second["items"] if r["ticker"] == "NVDA")["state"], "blocked")
                self.assertEqual(second["events"][:len(first["events"])], first["events"])

    def test_state_and_hash_chain_tampering_rejected(self):
        first=self.build(); validate_state(first)
        first["events"][0]["after"]["state"]="resolved"
        with self.assertRaisesRegex(ValueError,"integrity"):
            self.build(previous=first)

    def test_persistence_corruption_keeps_original_bytes_and_returns_finite_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name)
            good=refresh_capital_work_queue(decision(),root=root,current=WHEN)
            self.assertEqual(good["status"],"current")
            path=root/STORE_REL; path.write_bytes(b'{"sensitive_value":"broken')
            before=path.read_bytes()
            failed=refresh_capital_work_queue(decision(),root=root,current=WHEN)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(failed["status"],"unverified")
            self.assertEqual(failed["failure_code"],"queue_read_failed")
            self.assertNotIn("sensitive_value",json.dumps(failed))
            self.assertEqual(failed["top_opportunities"],[])

    def test_output_root_rehearsal_reads_source_config_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); source=root/"source"; out=root/"out"
            p=source/"00_project_control/active_production_config.json";p.parent.mkdir(parents=True)
            p.write_text(json.dumps({"account":{"core_target_pct":40,"active_target_pct":50,"cash_target_pct":10}}))
            before=p.read_bytes()
            report=refresh_capital_work_queue(decision(),root=out,input_root=source,current=WHEN)
            self.assertEqual(report["cash_explanation"]["approved_targets_pct"]["active_target_pct"],50)
            self.assertEqual(p.read_bytes(),before)
            self.assertFalse((source/STORE_REL).exists())
            self.assertTrue((out/STORE_REL).exists())

    def test_canonical_ticker_string_eligibility_is_research_only(self):
        d=decision(); d["eligible_new_position_review_candidates"]=["SPY"]
        report=self.build(d)
        row=next(r for r in report["top_opportunities"] if r["ticker"]=="SPY")
        self.assertEqual(row["state"],"research_ready")
        self.assertEqual(row["eligible_quantity"],0)
        self.assertFalse(row["automatic_action_allowed"])

    def test_automatic_check_uses_real_refresh_boundary_not_mail_time(self):
        report=self.build()
        self.assertEqual(report["next_automatic_review_at"],"2026-09-28T08:00:00-04:00")
        when=datetime.fromisoformat("2026-09-28T11:30:00-04:00")
        d=decision(); d["generated_at"]="2026-09-28T11:00:00-04:00"
        report=self.build(d,current=when,scheduler_state={"dates":{"2026-09-28":{"refresh_slots_completed":["08:00","08:30","09:00","09:45","13:30","14:00"]}}})
        self.assertEqual(report["next_automatic_review_at"],"2026-09-29T08:00:00-04:00")

    def test_stale_optional_backlog_is_not_advertised_as_current(self):
        from capital_work_queue import BACKLOG_REL
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); path=root/BACKLOG_REL;path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"schema_version":"equity_research_backlog_v1","generated_at":"2026-09-25T13:00:00-04:00", "priority_queue":[],"items":[]}))
            report=refresh_capital_work_queue(decision(),root=root,current=WHEN)
            self.assertEqual(report["status"],"current")
            self.assertEqual(report["backlog_status"],"unverified")

    def test_bad_market_and_cash_inputs_visible_in_cash_explanation(self):
        d=decision();d["market_gate"]={"passed":False};d["account"]["cash_reserved"]="5000"
        cash=self.build(d)["cash_explanation"]
        self.assertIn("market_evidence_unverified",cash["overlapping_reasons"])
        self.assertIn("planning_cash_inputs_invalid",cash["overlapping_reasons"])

    def test_stale_decision_cannot_claim_current_queue(self):
        with tempfile.TemporaryDirectory() as name:
            report=refresh_capital_work_queue(decision(),root=Path(name),current=datetime.fromisoformat("2026-09-28T14:00:00-04:00"))
            self.assertEqual(report["status"],"unverified")
            self.assertEqual(report["failure_code"],"queue_inputs_invalid")
            self.assertFalse((Path(name)/STORE_REL).exists())

    def test_backlog_requires_matching_current_financial_inputs(self):
        import hashlib
        from capital_work_queue import BACKLOG_REL
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); path=root/BACKLOG_REL;path.parent.mkdir(parents=True)
            fundamentals=root/"03_source_data/equity_research/daily_fundamentals.csv";fundamentals.parent.mkdir(parents=True)
            fundamentals.write_bytes(b"ticker,value\nTEST,3\n")
            write_valid_backlog(root)
            report=refresh_capital_work_queue(decision(),root=root,current=WHEN)
            self.assertEqual(report["backlog_status"],"available")
            fundamentals.write_bytes(b"ticker,value\nTEST,4\n")
            report=refresh_capital_work_queue(decision(),root=root,current=WHEN)
            self.assertEqual(report["backlog_status"],"unverified")

    def test_missing_opportunity_is_retained_and_reopens_without_duplicate_identity(self):
        first=self.build(); d=decision(); d["watch_candidates"]=[d["watch_candidates"][0]]
        second=self.build(d,first)
        third=self.build(previous=second)
        ddog=[r for r in third["items"] if r["item_id"]=="opportunity:DDOG"]
        self.assertEqual(len(ddog),1)
        self.assertEqual(ddog[0]["occurrence"],2)
        self.assertEqual(ddog[0]["first_seen_at"],first["generated_at"])
        self.assertEqual(third["events"][:len(second["events"])],second["events"])

    def test_current_decision_failure_overrides_same_day_valid_backlog_success(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); write_valid_backlog(root)
            d=decision();d["research_backlog"]={"status":"failed","freshness":"current","failure_code":"current_refresh_step_failed"}
            report=refresh_capital_work_queue(d,root=root,current=WHEN)
            self.assertEqual(report["status"],"current")
            self.assertEqual(report["backlog_status"],"unverified")
            ddog=next(r for r in report["top_opportunities"] if r["ticker"]=="DDOG")
            self.assertEqual(ddog["gap_ids"],[])
            self.assertNotIn("specific valuation countercase",ddog["next_step"])

    def test_cli_health_reader_respects_newer_failed_attempt(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);write_valid_backlog(root)
            attempt=root/"08_reviews/research_backlog.local/last_run.json";attempt.parent.mkdir(parents=True)
            attempt.write_text(json.dumps({"schema_version":"equity_research_backlog_run_v1","started_at":"2026-09-27T14:01:00-04:00","completed_at":"2026-09-27T14:02:00-04:00","exit_code":1}))
            report=refresh_capital_work_queue(decision(),root=root,current=datetime.fromisoformat("2026-09-27T14:03:00-04:00"))
            self.assertEqual(report["backlog_status"],"unverified")
            self.assertTrue(all(not r["gap_ids"] for r in report["top_opportunities"]))

    def test_decision_stale_freshness_overrides_valid_backlog(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);write_valid_backlog(root)
            d=decision();d["research_backlog"]={"status":"ready","freshness":"stale_or_unverified"}
            report=refresh_capital_work_queue(d,root=root,current=WHEN)
            self.assertEqual(report["backlog_status"],"unverified")

    def test_invalid_plan_ledger_preserves_prior_unresolved_tasks_as_unverified(self):
        first=self.build();d=decision()
        d["plan_continuity"]={"status":"invalid","plans":[],"conflicts":["plan_source_missing"]}
        result=self.build(d,first)
        self.assertEqual(result["plan_reassessment_status"],"unverified")
        self.assertEqual({r["ticker"] for r in result["plan_reassessment_queue"]},{"SMTC","RBRK"})
        for row in result["plan_reassessment_queue"]:
            self.assertEqual(row["state"],"unverified")
            self.assertEqual(row["evidence_status"],"unverified")
            self.assertEqual(row["original_time_exit_at"],"2026-09-25T15:45:00-04:00")
            self.assertEqual(row["plan_record_hash"],"2"*64)
            self.assertNotIn("closed_at",row)
        self.assertEqual(result["events"][:len(first["events"])],first["events"])

    def test_first_invalid_plan_read_reports_unknown_not_empty_success(self):
        from capital_work_queue import compact_summary, render_report
        d=decision();d["plan_continuity"]={"status":"missing_or_invalid","plans":[],"conflicts":["plan_inputs_unavailable"]}
        result=self.build(d)
        self.assertEqual(compact_summary(result)["plan_reassessment_status"],"unverified")
        self.assertIn("plan_context_unverified",result["cash_explanation"]["overlapping_reasons"])
        report=render_report(result)
        self.assertIn("coverage is unverified",report)
        self.assertNotIn("No current source-bound reassessment item",report)
