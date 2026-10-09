from __future__ import annotations

import copy
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR
from daily_common import ET, atomic_write_json, canonical_sha256, read_json, sha256_file
from market_discovery import CACHE_RELATIVE, _cache_write
from opportunity_contract import (AUTHORITY, BASE_REL, POLICY_REL, STORE_REL, REPORT_REL,
    empty_store, replay, retain_input, transition, publish_store, validate_observation)
from opportunity_triggers import packet, positive_changes, validate_approval
from opportunity_evidence import objective_research, _seal, EVIDENCE_REL
from research_opportunities import intake, objective, read_report, summary
from research_backlog import build_backlog
from update_research_assessment import apply_assessment
import run_daily_refresh as refresh

NOW = datetime(2026, 10, 3, 12, tzinfo=ET)
REPO = SCRIPT_DIR.parent.parent


def row(ticker="SYN"):
    values = {"revenue_latest": 200, "revenue_yoy_pct": 30, "revenue_yoy_prior_quarter_pct": 20,
        "net_margin_pct": 15, "net_margin_prior_quarter_pct": 8, "cash_latest": 500,
        "ttm_revenue": 700, "ttm_revenue_yoy_pct": 25, "diluted_shares_latest": 10,
        "share_dilution_pct": 1}
    provenance = {k: {"status": "available", "available_at_utc": "2026-08-01T20:00:00+00:00",
        "end": "2026-03-31" if "prior_quarter" in k else "2026-06-30", "val": v, "unit": "USD",
        "tag": k, "accn": "0000000001-26-000001"} for k, v in values.items()}
    return {"ticker": ticker, "cik": "1", "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json",
        "latest_period_end": "2026-06-30", "prior_quarter_period_end": "2026-03-31",
        "financial_period_type": "quarter", "data_quality": "ok", "fetched_at": NOW.isoformat(),
        "field_provenance_json": json.dumps(provenance), **values}


class OpportunityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        for name in ("research_opportunity_policy.json", "long_horizon_research_policy.json", "momentum_experiment.json"):
            dest = self.root / "01_policies" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / "01_policies" / name, dest)
        self.discovery(["SYN", "NEW", "OTH"])

    def tearDown(self):
        self.directory.cleanup()

    def discovery(self, tickers):
        rows = [{"ticker": t, "name": t, "close": 100+i, "rank": i+1, "score": 10-i,
            "in_legacy_universe": False, "relative_volume": 2, "average_dollar_volume_20d": 100000000,
            "relative_strength_5d_pct": 10, "relative_strength_20d_pct": 30} for i, t in enumerate(tickers)]
        self.data = {"schema_version": "phase5r_market_discovery_v1", "status": "complete", "complete": True,
            "as_of_session": "2026-10-02", "expected_session": "2026-10-02", "fetched_at": "2026-10-03T11:00:00-04:00",
            "price_basis": "synthetic adjusted EOD fixture", "methodology": "synthetic test fixture", "failure_code": "",
            "coverage": {"metadata_count": 3000, "common_stock_count": 2000, "etf_count": 1000,
                "latest_grouped_count": 5000, "stock_screen_eligible_count": len(rows), "etf_screen_eligible_count": 0,
                "screen_eligible_count": len(rows)}, "top_stocks": rows, "top_etfs": [], "all_stocks": rows, "all_etfs": []}
        _cache_write(self.root / CACHE_RELATIVE / "latest.local.json", self.data)

    def evidence(self, ticker="SYN"):
        from earnings_incorporation import retain_sec_response
        selected = row(ticker)
        receipts = []
        for url, body in (("https://data.sec.gov/submissions/CIK0000000001.json", {"cik": "1", "tickers": [ticker], "name": "Synthetic test company", "filings": {}}),
            (selected["source_url"], {"cik": "1", "facts": {}})):
            raw = retain_sec_response(json.dumps(body).encode(), url=url, retrieved_at=NOW.isoformat(), root=self.root)
            receipts.append(raw)
        sources = [retain_input(self.root, self.root/r["raw_path"], available_at=NOW.isoformat(), source_url=r["source_url"]) for r in receipts]
        selection = {"ticker": ticker, "financial_selection_sha256": canonical_sha256(selected), "submissions": receipts[0], "companyfacts": receipts[1]}
        path = self.root / (ticker+"-synthetic-selection.json");atomic_write_json(path, selection)
        sources.append(retain_input(self.root, path, available_at=NOW.isoformat()))
        dossier = _seal(self.root, ticker, selected, sources, NOW, "existing_canonical_fact_observations_research_attachment")
        return dossier

    def assessment(self, conclusion="supported"):
        item = next(i for i in read_report(self.root, current=NOW)["opportunities"] if i["ticker"] == "SYN")
        source = self.evidence()["sources"][0]
        return {"schema_version": "equity_opportunity_assessment_v1", "opportunity_id": item["opportunity_id"],
            "ticker": "SYN", "assessed_at": NOW.isoformat(), "next_review_at": (NOW+timedelta(days=5)).isoformat(),
            "conclusion": conclusion, "origin": "analyst", "hypothesis": "Synthetic test hypothesis",
            "reasoning": "Synthetic source comparison", "data_confidence": "verified_partial", "investment_conviction": "developing",
            "valuation_status": "pending", "missing_evidence": ["valuation"],
            "supporting_points": [{"point": "Synthetic supporting fact", "evidence_kind": "fact", "sources": [source]}],
            "counterpoints": [{"point": "Synthetic unresolved counterevidence", "evidence_kind": "unknown", "sources": [source]}], **AUTHORITY}

    def test_broad_outside_universe_gets_task_without_canonical_files(self):
        report = intake(self.root, current=NOW)
        self.assertEqual({i["ticker"] for i in report["priority_queue"]}, {"SYN", "NEW", "OTH"})
        self.assertFalse((self.root / "03_source_data/equity_research/universe_seed.csv").exists())
        self.assertTrue(all(i["capital_authority"] is False for i in report["opportunities"]))
    def test_decision_coverage_does_not_truncate_to_work_priority_budget(self):
        tickers=['SYN'+chr(65+i) for i in range(12)]
        for offset in (0,6):
            self.discovery(tickers[offset:offset+6])
            report=intake(self.root,current=NOW+timedelta(minutes=offset//6))
        view=summary(self.root,current=NOW+timedelta(minutes=1))
        self.assertEqual(len(view['priority_queue']),10)
        self.assertEqual(len(view['decision_candidates']),len(report['priority_queue']))
        self.assertGreater(len(view['decision_candidates']),10)
        self.assertFalse(view['capital_authority'])

    def test_duplicate_restart_preserves_exact_journal_and_first_seen(self):
        intake(self.root, current=NOW)
        before = (self.root / STORE_REL).read_bytes()
        intake(self.root, current=NOW+timedelta(minutes=10))
        self.assertEqual(before, (self.root / STORE_REL).read_bytes())
        self.assertEqual(read_report(self.root, current=NOW+timedelta(minutes=10))["opportunities"][0]["first_seen_at"], NOW.isoformat())

    def test_local_authority_projects_old_account_requirements_without_rewriting_assessment(self):
        from account_authority import POLICY_REL as ACCOUNT_POLICY, SCHEMA, LEGACY_ACCOUNT_RESEARCH_REQUIREMENTS
        from research_backlog import attention_rows
        intake(self.root, current=NOW)
        assessment = self.assessment('unresolved')
        old_code = sorted(LEGACY_ACCOUNT_RESEARCH_REQUIREMENTS)[0]
        assessment['missing_evidence'] = [old_code, 'valuation', 'buy_commitment_unbounded']
        apply_assessment(self.root, assessment, current=NOW, apply=True)
        journal = (self.root / STORE_REL).read_bytes()
        self.assertIn(old_code, next(i for i in summary(self.root, current=NOW)['priority_queue'] if i['ticker']=='SYN')['blockers'])
        approval = {'schema_version': SCHEMA, 'mode': 'owner_local_ledger', 'approved_at': NOW.isoformat(),
            'owner_instruction': 'Use local records for research planning.', 'automatic_execution': False,
            'broker_observation_claimed': False}
        atomic_write_json(self.root / ACCOUNT_POLICY, {**approval, 'content_sha256': canonical_sha256(approval)})
        with self.assertRaisesRegex(ValueError, 'account_authority_changed'):
            read_report(self.root, current=NOW)
        intake(self.root, current=NOW)
        item = next(i for i in attention_rows(self.root, NOW) if i['ticker'] == 'SYN')
        self.assertEqual(item['blockers'], ['valuation', 'buy_commitment_unbounded'])
        self.assertEqual(item['retained_assessment_execution_requirements'], [old_code])
        self.assertEqual(item['assessment'], assessment)
        self.assertEqual((self.root / STORE_REL).read_bytes(), journal)
        self.assertNotIn(old_code, next(i for i in summary(self.root, current=NOW)['priority_queue'] if i['ticker']=='SYN')['blockers'])

    def test_changed_discovery_retains_original_price_and_bytes(self):
        original = intake(self.root, current=NOW)["opportunities"][0]["first_observation"]
        self.data["top_stocks"][0]["close"] = 150
        _cache_write(self.root / CACHE_RELATIVE / "latest.local.json", self.data)
        report = intake(self.root, current=NOW+timedelta(minutes=10))
        item = next(i for i in report["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(item["first_observation"], original)
        self.assertEqual(len(item["observations"]), 2)
        self.assertEqual(item["first_observation"]["evidence"]["metrics"]["close"], 100)

    def test_capacity_and_per_run_bounds_keep_deferred_visible(self):
        policy = read_json(self.root / POLICY_REL); policy.update(active_capacity=2, new_opportunities_per_run=1)
        atomic_write_json(self.root / POLICY_REL, policy)
        a = intake(self.root, current=NOW)
        self.assertEqual(len(a["priority_queue"]), 1)
        b = intake(self.root, current=NOW+timedelta(minutes=1))
        self.assertEqual(len(b["priority_queue"]), 2)
        c = intake(self.root, current=NOW+timedelta(minutes=2))
        self.assertEqual(len(c["priority_queue"]), 2)
        self.assertEqual(len(c["opportunities"]), 3)
        self.assertEqual(c["metrics"]["states"]["deferred_capacity"], 1)

    def test_held_work_has_reserved_priority_over_higher_market_rank(self):
        p = self.root / "05_risk_and_positions/current_positions.local.csv"; p.parent.mkdir(parents=True)
        p.write_text("ticker,shares_optional\nOTH,1\n")
        policy = read_json(self.root / POLICY_REL); policy["new_opportunities_per_run"] = 1
        atomic_write_json(self.root / POLICY_REL, policy)
        self.assertEqual(intake(self.root, current=NOW)["priority_queue"][0]["ticker"], "OTH")

    def test_adverse_event_gets_priority_without_inventing_direction(self):
        from research_opportunities import priority
        market = {"ticker": "A", "family": "market", "evidence": {"metrics": {"rank": 1}}}
        adverse = {"ticker": "B", "family": "catalyst", "evidence": {"event": {"direction": "negative"}}}
        self.assertLess(priority(adverse, set()), priority(market, set()))
        adverse["evidence"]["event"]["direction"] = "unknown"
        self.assertEqual(priority(adverse, set())[0], 1)

    def test_stale_discovery_is_not_admitted(self):
        self.data["as_of_session"] = "2026-10-01"
        _cache_write(self.root / CACHE_RELATIVE / "latest.local.json", self.data)
        report = intake(self.root, current=NOW)
        self.assertEqual(report["priority_queue"], [])
        self.assertEqual(report["diagnostics"]["discovery_status"], "stale")

    def test_expiry_retains_episode_and_does_not_redetect_from_old_cache(self):
        first = intake(self.root, current=NOW)
        later = intake(self.root, current=NOW+timedelta(days=10))
        self.assertEqual(len(first["opportunities"]), len(later["opportunities"]))
        self.assertTrue(all(i["state"] == "expired" for i in later["opportunities"]))

    def test_missing_data_is_blocked_not_rejected_and_no_network(self):
        intake(self.root, current=NOW)
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden")):
            report = objective(self.root, current=NOW)
        self.assertTrue(all(i["state"] == "data_blocked" for i in report["opportunities"]))
        self.assertEqual(report["metrics"]["network_requests"], 0)
        self.assertEqual(report["metrics"]["canonical_fields_admitted"], 0)

    def test_escalation_changes_actual_objective_order_with_shared_remaining_budget(self):
        intake(self.root, current=NOW)
        atomic_write_json(self.root / "00_project_control/active_production_config.json",
            {"workflow": {"objective_research_max_tickers": 2}})
        atomic_write_json(self.root / "04_research/company_research/research_backlog.local.json",
            {"generated_at": NOW.isoformat(), "selected_tickers": ["ALREADY"]})
        with patch("capital_escalation.research_priorities", return_value=["OTH", "NEW"]), \
                patch("research_backlog.refresh_attention_view"), \
                patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network forbidden")):
            report = objective(self.root, current=NOW)
        self.assertEqual([r["ticker"] for r in report["metrics"]["attempts"]], ["OTH"])
        self.assertEqual(report["metrics"]["canonical_issuers_attempted_before_intake"], 1)
        self.assertEqual(report["metrics"]["shared_objective_work_budget"], 2)
        self.assertEqual(report["metrics"]["network_requests"], 0)
        self.assertFalse(report["capital_authority"])

    def test_no_escalation_preserves_objective_order_and_unchanged_attempt_is_skipped(self):
        intake(self.root, current=NOW)
        atomic_write_json(self.root / "00_project_control/active_production_config.json",
            {"workflow": {"objective_research_max_tickers": 1}})
        with patch("capital_escalation.research_priorities", return_value=[]):
            first = objective(self.root, current=NOW)
        self.assertEqual([r["ticker"] for r in first["metrics"]["attempts"]], ["SYN"])
        with patch("capital_escalation.research_priorities", return_value=["SYN", "OTH"]):
            second = objective(self.root, current=NOW+timedelta(minutes=1))
        self.assertEqual([r["ticker"] for r in second["metrics"]["attempts"]], ["OTH"])
        self.assertEqual(second["metrics"]["unchanged_items_skipped"], 1)

    def test_cached_primary_research_progresses_and_repeat_does_not_republish(self):
        intake(self.root, current=NOW)
        self.evidence()
        report = objective(self.root, current=NOW)
        item = next(i for i in report["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(item["state"], "evidence_attached")
        before = (self.root / STORE_REL).read_bytes()
        objective(self.root, current=NOW+timedelta(minutes=5))
        self.assertEqual(before, (self.root / STORE_REL).read_bytes())

    def test_real_automatic_objective_progress_flows_into_explicit_final_dependency(self):
        intake(self.root, current=NOW)
        before = objective(self.root, current=NOW)
        self.assertEqual(next(i for i in before["opportunities"] if i["ticker"] == "SYN")["state"], "data_blocked")
        self.evidence()
        report = objective(self.root, current=NOW)
        item = next(i for i in report["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(item["state"], "evidence_attached")
        from capital_decision import build
        from active_config import load_active_config
        decision = {"account": {"account_total_value":10000,"cash_available":8000,"cash_reserved":0,"cash_basis":"owner_confirmed","last_updated":NOW.isoformat()},
            "market_gate":{"passed":True,"expected_market_session":"2026-10-02"},"evidence_gate":{"passed":True},"fundamental_gate":{"passed":True},
            "workflow_integrity":{"global_blockers":[],"ticker_blockers":{}},"held_positions":[],"watch_candidates":[],
            "research_opportunities":{"priority_queue":[{"ticker":"SYN","state":item["state"],"blockers":["company_specific_valuation"]}]}}
        orders={"schema_version":"phase5r_open_orders_v1","as_of":NOW.isoformat(),"complete":True,"orders":[]}
        final=build(decision,root=self.root,current=NOW,config=load_active_config(),orders=orders)["decisions"][0]
        self.assertEqual(final["decision"],"BLOCKED");self.assertEqual(final["shares"],0)
        self.assertEqual(final["dependencies"][0]["resolver"],"recurring_analyst")
        self.assertFalse(report["capital_authority"])

    def test_backlog_routes_outside_and_keeps_research_scope(self):
        opportunities = intake(self.root, current=NOW)["opportunities"]
        backlog = build_backlog(fundamentals=[], positions=[], research={}, dossiers={}, current=NOW, opportunities=opportunities)
        self.assertIn("SYN", [i["ticker"] for i in backlog["priority_queue"]])
        self.assertEqual(backlog["priority_queue"][0]["evidence_scope"], "research_only_no_canonical_admission")

    def test_capital_and_cash_do_not_control_attention(self):
        intake(self.root, current=NOW)
        before = (self.root / STORE_REL).read_bytes()
        atomic_write_json(self.root / "05_risk_and_positions/current_account_state.local.json", {"cash": 0, "account_blocked": True})
        intake(self.root, current=NOW+timedelta(minutes=2))
        self.assertEqual(before, (self.root / STORE_REL).read_bytes())

    def test_journal_tampering_is_not_repaired_by_overwriting_history(self):
        intake(self.root, current=NOW)
        store = read_json(self.root / STORE_REL);store["events"][0]["observation"]["evidence"]["metrics"]["close"] = 5
        atomic_write_json(self.root / STORE_REL, store)
        before = (self.root / STORE_REL).read_bytes()
        with self.assertRaises(ValueError): intake(self.root, current=NOW)
        self.assertEqual(before, (self.root / STORE_REL).read_bytes())

    def test_historical_source_tampering_fails_admission(self):
        report = intake(self.root, current=NOW)
        source = report["opportunities"][0]["first_observation"]["sources"][0]
        (self.root / source["path"]).write_text("changed")
        self.assertEqual(summary(self.root, current=NOW)["status"], "unverified")

    def test_crash_before_atomic_store_publication_keeps_prior_prefix(self):
        intake(self.root, current=NOW)
        old = read_json(self.root / STORE_REL)
        changed = copy.deepcopy(old)
        item = next(iter(replay(old).values()))
        transition(changed, item["opportunity_id"], "data_blocked", owner="objective_research", reason="missing_source",
            sources=item["first_observation"]["sources"], blockers=["missing_source"], current=NOW)
        import opportunity_contract
        original = opportunity_contract.atomic_write_json
        def fail(path, payload):
            if path == self.root / STORE_REL: raise OSError("synthetic crash")
            return original(path, payload)
        with patch.object(opportunity_contract, "atomic_write_json", side_effect=fail):
            with self.assertRaises(OSError): publish_store(self.root, changed, previous=old, current=NOW)
        self.assertEqual(read_json(self.root / STORE_REL), old)

    def test_wrong_layer_cannot_advance_supported_research(self):
        report = intake(self.root, current=NOW)
        store = read_json(self.root / STORE_REL); i = report["opportunities"][0]
        with self.assertRaises(ValueError): transition(store, i["opportunity_id"], "research_supported", owner="research_orchestration",
            reason="high_score", sources=i["first_observation"]["sources"], blockers=[], current=NOW)

    def test_observation_authority_and_future_data_rejected(self):
        p = intake(self.root, current=NOW)["opportunities"][0]["first_observation"]
        p["capital_authority"] = True
        with self.assertRaises(ValueError): validate_observation(p, root=self.root, current=NOW)
        p["capital_authority"] = False; p["available_at"] = (NOW+timedelta(days=1)).isoformat()
        with self.assertRaises(ValueError): validate_observation(p, root=self.root, current=NOW)

    def test_period_comparable_positive_acceleration_is_research_only(self):
        thresholds = read_json(self.root / "01_policies/long_horizon_research_policy.json")["review_thresholds"]
        result = positive_changes(row(), NOW, thresholds)
        self.assertEqual({v["code"] for v in result}, {"revenue_growth_acceleration", "net_margin_improvement"})
        bad = row(); bad["financial_period_type"] = "annual"
        self.assertEqual(positive_changes(bad, NOW, thresholds), [])
        bad = row();bad["prior_quarter_period_end"] = "2024-03-31"
        self.assertEqual(positive_changes(bad, NOW, thresholds), [])
        bad = row();bad["field_provenance_json"] = "{}"
        self.assertEqual(positive_changes(bad, NOW, thresholds), [])

    def test_supported_assessment_stays_research_only_and_idempotent(self):
        intake(self.root, current=NOW); self.evidence(); objective(self.root, current=NOW)
        proposal = self.assessment()
        result = apply_assessment(self.root, proposal, current=NOW, apply=True)
        self.assertEqual(result["status"], "recorded")
        self.assertFalse(result["capital_authority"])
        self.assertEqual(apply_assessment(self.root, proposal, current=NOW, apply=True)["status"], "already_recorded")
        self.assertFalse((self.root / "04_research/company_research/thesis_dossiers.local.json").exists())

    def test_rejected_and_economic_failures_keep_observations(self):
        intake(self.root, current=NOW);self.evidence();objective(self.root, current=NOW)
        proposal = self.assessment("rejected")
        apply_assessment(self.root, proposal, current=NOW, apply=True)
        item = next(i for i in read_report(self.root, current=NOW)["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(item["state"], "rejected")
        self.assertTrue(item["observations"])
        self.assertEqual(item["first_seen_at"], NOW.isoformat())

    def test_mature_experiment_without_owner_approval_cannot_enter_research(self):
        with self.assertRaises(ValueError): validate_approval({"ready_for_owner_review": True}, root=self.root, current=NOW)

    def test_forward_study_never_uses_signal_close_as_entry(self):
        report = intake(self.root, current=NOW)
        paths = report["prospective_measurement"]["observations"]
        self.assertEqual(paths[0]["model_entry_session"], "2026-10-05")
        self.assertTrue(all(o["status"] == "pending_forward_observation" for o in paths[0]["outcomes"]))
        self.assertFalse(paths[0]["capital_authority"])

    def test_fetch_stage_only_and_refresh_pipeline_has_no_sender(self):
        # Exercise the real marker writer inside the fixture, never the
        # authoring or production checkout used to run this test suite.
        with patch.object(refresh, "ROOT", self.root), patch.object(refresh.subprocess, "run") as run:
            run.return_value.returncode = 0
            refresh.run_step("research_opportunity_objective", "create_research_opportunities.py", True, market_snapshot_mode=refresh.MARKET_SNAPSHOT_REUSE)
            self.assertNotIn("--refresh", run.call_args.args[0])
            refresh.run_step("research_opportunity_objective", "create_research_opportunities.py", True, market_snapshot_mode=refresh.MARKET_SNAPSHOT_FETCH)
            self.assertIn("--refresh", run.call_args.args[0])
        self.assertTrue((self.root / BASE_REL / "last_objective_run.json").exists())
        self.assertFalse(any("send" in spec[1] for spec in refresh.STEP_SPECS))

    def test_projection_hash_and_clock_are_verified(self):
        intake(self.root, current=NOW)
        self.assertEqual(summary(self.root, current=NOW-timedelta(minutes=1))["status"], "unverified")
        report = read_json(self.root / REPORT_REL);report["metrics"]["research_queue_size"] = 999
        atomic_write_json(self.root / REPORT_REL, report)
        self.assertEqual(summary(self.root, current=NOW)["status"], "unverified")

    def test_latest_failure_cannot_be_hidden_by_a_prior_green_report(self):
        intake(self.root, current=NOW)
        atomic_write_json(self.root / BASE_REL / "last_objective_run.json", {"exit_code": 124, "started_at": NOW.isoformat()})
        self.assertEqual(summary(self.root, current=NOW)["status"], "failed_or_incomplete")

    def test_urgent_held_work_displaces_low_priority_without_deleting_history(self):
        policy = read_json(self.root / POLICY_REL);policy.update(active_capacity=1, new_opportunities_per_run=1)
        atomic_write_json(self.root / POLICY_REL, policy)
        a = intake(self.root, current=NOW)
        p = self.root / "05_risk_and_positions/current_positions.local.csv";p.parent.mkdir(parents=True)
        p.write_text("ticker,shares_optional\nOTH,1\n")
        b = intake(self.root, current=NOW+timedelta(minutes=1))
        self.assertEqual(b["priority_queue"][0]["ticker"], "OTH")
        old = next(i for i in b["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(old["state"], "deferred_capacity")
        self.assertEqual(old["first_seen_at"], NOW.isoformat())
        self.assertEqual(len(b["opportunities"]), len(a["opportunities"]))

    def test_business_repoll_and_wrong_units_cannot_create_acceleration(self):
        thresholds = read_json(self.root / "01_policies/long_horizon_research_policy.json")["review_thresholds"]
        a = row(); b = row();b["fetched_at"] = (NOW+timedelta(minutes=1)).isoformat()
        self.assertEqual(positive_changes(a, NOW, thresholds), positive_changes(b, NOW+timedelta(minutes=1), thresholds))
        bound = json.loads(b["field_provenance_json"])
        bound["revenue_yoy_prior_quarter_pct"]["unit"] = "incompatible_units"
        bound["net_margin_prior_quarter_pct"]["end"] = "2025-03-31"
        b["field_provenance_json"] = json.dumps(bound)
        self.assertEqual(positive_changes(b, NOW, thresholds), [])

    def test_changed_baseline_research_queue_does_not_rediscover_same_market_signal(self):
        intake(self.root, current=NOW)
        before = (self.root / STORE_REL).read_bytes()
        atomic_write_json(self.root / "04_research/company_research/research_backlog.local.json",
            {"generated_at": NOW.isoformat(), "issuer_queue": [{"ticker": "SYN"}]})
        intake(self.root, current=NOW+timedelta(minutes=1))
        self.assertEqual(before, (self.root / STORE_REL).read_bytes())

    def test_network_failure_is_reserved_once_per_issuer_session(self):
        item = intake(self.root, current=NOW)["opportunities"][0]
        atomic_write_json(self.root / "03_source_data/equity_research/sec_ticker_map.local.json", {item["ticker"]: 1})
        metrics = {"network_requests": 0, "external_issuers_attempted": 0, "request_limit": 4}
        def failed(*args):
            metrics["network_requests"] += 1
            raise OSError("synthetic endpoint failure")
        with patch.dict("os.environ", {"PHASE5R_SEC_USER_AGENT": "Synthetic test test@example.test"}):
            for _ in range(2):
                dossier, reason = objective_research(self.root, item, current=NOW, policy=read_json(self.root / POLICY_REL),
                    canonical_rows={}, market_session="2026-10-02", allow_network=True, metrics=metrics, fetcher=failed)
                self.assertIsNone(dossier)
        self.assertEqual(metrics["network_requests"], 1)
        self.assertEqual(metrics["external_issuers_attempted"], 1)

    def test_old_report_is_invalid_after_a_new_journal_publication(self):
        report = intake(self.root, current=NOW)
        old = read_json(self.root / STORE_REL); new = copy.deepcopy(old);item = report["opportunities"][0]
        transition(new, item["opportunity_id"], "data_blocked", owner="objective_research", reason="source_missing",
            sources=item["first_observation"]["sources"], blockers=["source_missing"], current=NOW)
        publish_store(self.root, new, previous=old, current=NOW)
        self.assertEqual(summary(self.root, current=NOW)["status"], "unverified")

    def test_supported_research_requires_a_separate_valuation_before_handoff(self):
        intake(self.root, current=NOW);self.evidence();objective(self.root, current=NOW)
        proposal = self.assessment();proposal["request_eligibility_review"] = True
        with self.assertRaises(ValueError): apply_assessment(self.root, proposal, current=NOW, apply=True)
        proposal["valuation_status"] = "reviewed"
        apply_assessment(self.root, proposal, current=NOW, apply=True)
        item = next(i for i in read_report(self.root, current=NOW)["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(item["state"], "eligibility_review")
        self.assertIn("existing_account_risk_and_execution_contracts", item["blockers"])
        self.assertFalse(item["capital_authority"])

    def test_experiment_approval_countercases_and_registered_research_boundary(self):
        import momentum_experiment_review as review_module
        import momentum_experiment as experiment
        import test_momentum_experiment_review as fixtures
        from contextlib import nullcontext
        archive = {"implementation_files": {"synthetic_test_module.py": "a"*64}}
        rows = fixtures.observations()
        for record in rows:
            record["inputs"]["implementation_sha256"] = canonical_sha256(archive["implementation_files"])
        values = fixtures.payloads([*rows, *(fixtures.outcome(record) for record in rows)])
        ledger_path = self.root / experiment.OUTPUT / "ledger.jsonl"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text("".join(json.dumps(r)+"\n" for r in values["records"]))
        digest = sha256_file(ledger_path)
        values["ledger_sha256"] = digest;values["experiment_report"]["ledger_sha256"] = digest
        version, policy_hash = rows[0]["experiment_version"], rows[0]["policy_sha256"]
        for relative, data in ((review_module.POLICY, values["policy"]), (experiment.POLICY, values["frozen_policy"]),
            (experiment.OUTPUT/"report.json", values["experiment_report"]), (experiment.OUTPUT/"status.json", values["experiment_status"])):
            atomic_write_json(self.root/relative, data)
        relatives = [review_module.POLICY, experiment.POLICY, experiment.OUTPUT/"ledger.jsonl", experiment.OUTPUT/"report.json", experiment.OUTPUT/"status.json"]
        values["input_hashes"] = {str(r): sha256_file(self.root/r) for r in relatives}
        actual_review = review_module.build_review(**values)
        owner_path = self.root / "owner-test.json";review_path = self.root / "review-test.json"
        atomic_write_json(owner_path, {"origin": "owner", "scope": "research_attention_only", "experiment_version": version, "instruction": "Synthetic owner test authorization"})
        atomic_write_json(review_path, actual_review)
        proposal = {"schema_version": "equity_experiment_research_approval_v1", "scope": "research_attention_only",
            "owner_authorized": True, "experiment_version": version, "policy_sha256": policy_hash,
            "approved_at": NOW.isoformat(), "allowed_dispositions": [rows[0]["disposition"]],
            "owner_receipt": retain_input(self.root, owner_path, available_at=NOW.isoformat()),
            "review_receipt": retain_input(self.root, review_path, available_at=NOW.isoformat()),
            "review_inputs": [retain_input(self.root, self.root/r, available_at=NOW.isoformat()) for r in relatives], **AUTHORITY}
        proposal["approval_id"] = canonical_sha256(proposal)
        with patch("frozen_momentum_runtime.load_registry", return_value={version: archive}), patch("frozen_momentum_runtime.verified_snapshot", return_value=nullcontext((self.root, values["frozen_policy"]))):
            self.assertEqual(validate_approval(proposal, root=self.root, current=NOW), proposal)
            bad = copy.deepcopy(proposal);bad["capital_authority"] = True
            with self.assertRaises(ValueError): validate_approval(bad, root=self.root, current=NOW)
            bad = copy.deepcopy(proposal);bad["review_inputs"] = bad["review_inputs"][:-1]
            with self.assertRaises(ValueError): validate_approval(bad, root=self.root, current=NOW)
            tampered = copy.deepcopy(actual_review);tampered["complete_cohorts"] += 1
            atomic_write_json(review_path, tampered)
            bad = copy.deepcopy(proposal);bad["review_receipt"] = retain_input(self.root, review_path, available_at=NOW.isoformat())
            with self.assertRaises(ValueError): validate_approval(bad, root=self.root, current=NOW)

    def test_unchanged_high_priority_items_do_not_starve_new_objective_work(self):
        intake(self.root, current=NOW);self.evidence();objective(self.root, current=NOW)
        self.evidence("NEW")
        atomic_write_json(self.root / "00_project_control/active_production_config.json", {"workflow": {"objective_research_max_tickers": 1}})
        result = objective(self.root, current=NOW)
        new = next(i for i in result["opportunities"] if i["ticker"] == "NEW")
        self.assertEqual(new["state"], "evidence_attached")
        self.assertEqual(result["metrics"]["objective_items_processed"], 1)
        self.assertGreater(result["metrics"]["unchanged_items_skipped"], 0)

    def test_forward_outcomes_freeze_first_prices_and_keep_revisions_visible(self):
        from opportunity_measurement import measure_paths
        items = intake(self.root, current=NOW)["opportunities"]
        cache_path = self.root / CACHE_RELATIVE / "grouped-2026-10-05.local.json"
        prices = {i["ticker"]: {"o": 100, "c": 110} for i in items}
        prices["SPY"] = {"o": 500, "c": 505}
        bars = {"session": "2026-10-05", "complete": True, "adjusted": True, "rows": prices}
        _cache_write(cache_path, bars)
        # The repository's Basic REST publication target reaches Monday's
        # close on Tuesday morning, not on Monday evening.
        later = datetime(2026, 10, 6, 9, tzinfo=ET)
        paths = measure_paths(self.root, items, current=later)
        one = paths["observations"][0]["outcomes"][0]
        self.assertEqual(one["status"], "observed_hypothetical_path")
        self.assertEqual(one["gross_price_change_pct"], 10)
        self.assertLess(one["net_cost_sensitivities"][0]["net_price_change_pct"], 10)
        stored = (self.root / BASE_REL / "forward_outcomes.json").read_bytes()
        bars["rows"][items[0]["ticker"]]["c"] = 120
        _cache_write(cache_path, bars)
        revised = measure_paths(self.root, items, current=later)
        self.assertEqual(revised["observations"][0]["outcomes"][0]["status"], "correction_review_required")
        self.assertEqual((self.root / BASE_REL / "forward_outcomes.json").read_bytes(), stored)
        cache_path.unlink()
        missing = measure_paths(self.root, items, current=later)["observations"][0]["outcomes"][0]
        self.assertEqual(missing["status"], "missing_or_unverified_forward_coverage")
        self.assertEqual(missing["original_outcome"]["gross_price_change_pct"], 10)

    def test_rejection_with_changed_evidence_needs_recorded_reassessment(self):
        intake(self.root, current=NOW);self.evidence();objective(self.root, current=NOW)
        apply_assessment(self.root, self.assessment("rejected"), current=NOW, apply=True)
        self.data["top_stocks"][0]["relative_volume"] = 3
        _cache_write(self.root / CACHE_RELATIVE / "latest.local.json", self.data)
        report = intake(self.root, current=NOW+timedelta(minutes=1))
        item = next(i for i in report["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(item["state"], "rejected")
        self.assertEqual(item["first_seen_at"], NOW.isoformat())
        self.assertIn("SYN", [i["ticker"] for i in report["reassessment_queue"]])
        self.assertNotIn("SYN", [i["ticker"] for i in report["priority_queue"]])

    def test_concurrent_duplicate_intakes_publish_one_first_observation(self):
        expected = intake(self.root, current=NOW)
        old = (self.root / STORE_REL).read_bytes()
        code = "import sys; from datetime import datetime; import create_research_opportunities as c; stamp=datetime.fromisoformat(sys.argv.pop()); c.now_et=lambda: stamp; raise SystemExit(c.main())"
        commands = [subprocess.Popen([sys.executable, "-c", code, "--root", str(self.root), NOW.isoformat()],
            cwd=SCRIPT_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        # A contending invocation either completes after release or reports
        # busy without overwriting the active stage marker or journal.
        for command in commands:
            stdout, stderr = command.communicate(timeout=20)
            self.assertIn(command.returncode, (0, 3), stderr.decode())
        retry = subprocess.run([sys.executable, "-c", code, "--root", str(self.root), NOW.isoformat()],
            cwd=SCRIPT_DIR, capture_output=True, timeout=20)
        self.assertEqual(retry.returncode, 0, retry.stderr.decode())
        self.assertEqual((self.root / STORE_REL).read_bytes(), old)
        self.assertEqual(read_report(self.root, current=NOW)["metrics"]["total_retained_opportunities"], len(expected["opportunities"]))

    def test_failed_second_request_keeps_successful_primary_receipt(self):
        from earnings_incorporation import retain_sec_response
        item = intake(self.root, current=NOW)["opportunities"][0]
        atomic_write_json(self.root / "03_source_data/equity_research/sec_ticker_map.local.json", {item["ticker"]: 1})
        metrics = {"network_requests": 0, "external_issuers_attempted": 0, "request_limit": 4}
        def partly_failed(root, url, current, counters):
            counters["network_requests"] += 1
            if "companyfacts" in url:
                raise OSError("synthetic companyfacts unavailable")
            data = {"cik": "1", "tickers": [item["ticker"]], "name": "Synthetic test company", "filings": {}}
            receipt = retain_sec_response(json.dumps(data).encode(), url=url, retrieved_at=current.isoformat(), root=root)
            return data, receipt
        with patch.dict("os.environ", {"PHASE5R_SEC_USER_AGENT": "Synthetic test test@example.test"}):
            dossier, reason = objective_research(self.root, item, current=NOW, policy=read_json(self.root / POLICY_REL),
                canonical_rows={}, market_session="2026-10-02", allow_network=True, metrics=metrics, fetcher=partly_failed)
        attempt = next(iter(read_json(self.root / BASE_REL / "fetch_attempts.json")["attempts"].values()))
        self.assertIsNone(dossier)
        self.assertEqual(attempt["status"], "failed")
        self.assertEqual(len(attempt["sources"]), 1)
        self.assertEqual(attempt["network_requests"], 2)
        self.assertTrue((self.root / attempt["sources"][0]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
