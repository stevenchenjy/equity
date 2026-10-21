"""Synthetic event routing tests: no public requests or investment authority."""
from __future__ import annotations

import copy
from datetime import timedelta
import json
from unittest.mock import patch
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_csv, atomic_write_json, read_csv, read_json
from opportunity_contract import AUTHORITY, POLICY_REL, STORE_REL, retain_input, replay
from research_opportunities import intake, objective, summary, priority, upcoming_earnings
from research_backlog import build_backlog, run as run_backlog
import test_research_opportunities as opportunity_fixtures
from update_research_assessment import apply_assessment


NOW = opportunity_fixtures.NOW


class EarningsResearchRoutingTests(unittest.TestCase):
    discovery = opportunity_fixtures.OpportunityTests.discovery
    evidence = opportunity_fixtures.OpportunityTests.evidence
    assessment = opportunity_fixtures.OpportunityTests.assessment

    def setUp(self):
        opportunity_fixtures.OpportunityTests.setUp(self)
        self.discovery(["TOP"])

    def tearDown(self):
        opportunity_fixtures.OpportunityTests.tearDown(self)

    def event(self, ticker, hours=24):
        raw = self.root / (ticker + "-calendar.raw")
        raw.write_text("Synthetic dated public earnings calendar: " + ticker)
        first = NOW - timedelta(hours=1)
        sources = [retain_input(self.root, raw, available_at=first.isoformat(),
            source_url="https://api.nasdaq.com/api/calendar/earnings?date=2026-10-04")]
        deadline = NOW + timedelta(hours=hours)
        return {"event_id": "synthetic-" + ticker, "ticker": ticker,
            "company_name": ticker + " synthetic company", "event_date": deadline.date().isoformat(),
            "session": "after_close", "event_at": None, "research_deadline_at": deadline.isoformat(),
            "first_detected_at": first.isoformat(), "last_observed_at": NOW.isoformat(),
            "date_confidence": "exchange_calendar_estimate", "status": "detected", "timing": "pre_event",
            "blockers": [], "sources": sources}

    def collect(self, events, current=NOW, coverage=None):
        with patch("earnings_events.event_observations", return_value=(events, coverage or {"status": "ready"})):
            return intake(self.root, current=current)

    def test_two_weak_momentum_outside_issuers_reach_actual_backlog_and_zero_authority_decision_intake(self):
        events = [self.event("WEAK", 20), self.event("OTHER", 22)]
        report = self.collect(events)
        self.assertEqual([i["ticker"] for i in report["priority_queue"][:2]], ["WEAK", "OTHER"])
        self.assertTrue(all(i["first_seen_at"] == NOW.isoformat() for i in report["opportunities"]))
        self.assertEqual(report["priority_queue"][0]["first_observation"]["available_at"], events[0]["sources"][0]["available_at"])
        backlog = build_backlog(fundamentals=[{"ticker": "TOP"}], positions=[], research={}, dossiers={},
            current=NOW, opportunities=report["opportunities"], max_tickers=2, escalation_priorities=["TOP"])
        self.assertEqual([r["ticker"] for r in backlog["priority_queue"]], ["WEAK", "OTHER"])
        self.assertTrue(all(r["evidence_scope"] == "research_only_no_canonical_admission" for r in backlog["priority_queue"]))
        decision_view = summary(self.root, current=NOW)
        self.assertTrue({"WEAK", "OTHER"}.issubset({r["ticker"] for r in decision_view["decision_candidates"]}))
        self.assertTrue(all(r["eligible_quantity"] == 0 for r in decision_view["decision_candidates"]))
        self.assertTrue(all(decision_view[key] is False for key in AUTHORITY))
        self.assertFalse((self.root / "03_source_data/equity_research/universe_seed.csv").exists())
        self.assertTrue(any(i["reason_code"] == "earnings_expectations_and_priced_in_case" for i in backlog["items"]))

    def test_full_pool_admits_nearest_event_preserving_held_and_displaced_work(self):
        policy = read_json(self.root / POLICY_REL)
        policy.update(active_capacity=2, new_opportunities_per_run=2)
        atomic_write_json(self.root / POLICY_REL, policy)
        self.discovery(["HELD", "MOM"])
        path = self.root / "05_risk_and_positions/current_positions.local.csv"
        path.parent.mkdir(parents=True, exist_ok=True); path.write_text("ticker,shares_optional\nHELD,1\n")
        self.collect([])
        report = self.collect([self.event("LATER", 25), self.event("SOON", 10)], current=NOW + timedelta(minutes=1))
        self.assertEqual([r["ticker"] for r in report["priority_queue"]], ["HELD", "SOON"])
        by = {r["ticker"]: r for r in report["opportunities"]}
        self.assertEqual(by["MOM"]["state"], "deferred_capacity")
        self.assertEqual(by["MOM"]["reason_code"], "research_capacity_reserved_for_pre_earnings_deadline")
        self.assertEqual(by["LATER"]["state"], "deferred_capacity")
        self.assertEqual(len(by), 4)

    def test_repoll_is_idempotent_all_events_retained_without_top_ten_cutoff(self):
        events = [self.event("EV" + chr(65 + i), 20 + i / 100) for i in range(20)]
        first = self.collect(events)
        prior = (self.root / STORE_REL).read_bytes()
        polled = copy.deepcopy(events)
        for event in polled:
            event["last_observed_at"] = (NOW + timedelta(minutes=1)).isoformat()
        second = self.collect(polled, current=NOW + timedelta(minutes=1))
        self.assertEqual(len(first["opportunities"]), 21)
        # A later run can admit deferred work within its unchanged six-item
        # budget; repeated detection must not append duplicate observations.
        self.assertEqual(second["metrics"]["rediscovery_updates"], 0)
        self.assertEqual(sum(len(i["observations"]) for i in second["opportunities"]), 21)
        self.assertEqual(len(replay(read_json(self.root / STORE_REL))), 21)
        old_events = json.loads(prior)["events"]
        self.assertEqual(read_json(self.root / STORE_REL)["events"][:len(old_events)], old_events)

    def test_elapsed_conflicting_or_missing_coverage_never_invents_event_priority(self):
        elapsed = self.event("OLD", -1)
        conflicting = self.event("BAD", 2); conflicting.update(status="schedule_conflict", blockers=["schedule_conflict"])
        report = self.collect([elapsed, conflicting], coverage={"status": "partial", "failed_dates": ["2026-10-04"]})
        self.assertEqual({r["ticker"] for r in report["opportunities"]}, {"TOP"})
        self.assertEqual(report["diagnostics"]["earnings_calendar"]["status"], "partial")
        future = self.collect([self.event("NEW", 1)])
        item = next(r for r in future["opportunities"] if r["ticker"] == "NEW")
        self.assertIsNotNone(upcoming_earnings(item, NOW))
        self.assertIsNone(upcoming_earnings(item, NOW + timedelta(hours=2)))
        self.assertEqual(priority(item, set(), current=NOW + timedelta(hours=2))[0], 3)
        conflict = self.event("NEW", 1)
        conflict.update(status="schedule_conflict", blockers=["event_session_changed_requires_confirmation"])
        changed = self.collect([conflict], current=NOW + timedelta(minutes=1))
        changed_item = next(i for i in changed["opportunities"] if i["ticker"] == "NEW")
        self.assertIsNone(upcoming_earnings(changed_item, NOW + timedelta(minutes=1)))
        self.assertEqual(len(changed_item["observations"]), 2)
        with patch("earnings_events.event_observations", side_effect=ValueError("synthetic conflict")):
            failed = intake(self.root, current=NOW + timedelta(minutes=2))
        self.assertEqual(failed["diagnostics"]["earnings_calendar"]["status"], "unverified")
        self.assertTrue(any(i["ticker"] == "TOP" for i in failed["opportunities"]))

    def test_closed_negative_case_new_event_reaches_reassessment_without_auto_reopening(self):
        self.discovery(["SYN"])
        self.collect([])
        proposal = self.assessment("rejected")
        apply_assessment(self.root, proposal, current=NOW, apply=True)
        report = self.collect([self.event("SYN", 20)], current=NOW + timedelta(minutes=1))
        item = next(i for i in report["opportunities"] if i["ticker"] == "SYN")
        self.assertEqual(item["state"], "rejected")
        self.assertEqual(report["reassessment_queue"][0]["ticker"], "SYN")
        self.assertFalse(report["capital_authority"])

    def test_event_objective_work_precedes_ordinary_escalation_without_analyst_conclusion(self):
        report = self.collect([self.event("NEW", 20), self.event("OTH", 21)])
        dossier = self.evidence("NEW")
        attempted = []
        def inspect(root, item, **kwargs):
            attempted.append(item["ticker"])
            return (dossier, "source_bound_objective_attachment") if item["ticker"] == "NEW" else (None, "precise_missing_public_source")
        with patch("capital_escalation.research_priorities", return_value=["TOP"]), patch("research_opportunities.objective_research", side_effect=inspect):
            result = objective(self.root, current=NOW)
        self.assertEqual(attempted[:2], ["NEW", "OTH"])
        by = {i["ticker"]: i for i in result["opportunities"]}
        self.assertEqual(by["NEW"]["state"], "evidence_attached")
        self.assertEqual(by["OTH"]["state"], "data_blocked")
        self.assertEqual(result["metrics"]["analyst_assessments_completed"], 0)
        self.assertEqual(result["metrics"]["canonical_fields_admitted"], 0)
        self.assertFalse(result["capital_authority"])

    def test_canonical_pass_reserves_existing_external_slots_then_following_worker_processes_events(self):
        from refresh_daily_evidence import FUNDAMENTAL_FIELDS
        rows = [opportunity_fixtures.row(ticker) for ticker in ("TOP", "MOMA", "MOMB")]
        path = self.root / "03_source_data/equity_research/daily_fundamentals.csv"
        atomic_write_csv(path, FUNDAMENTAL_FIELDS, rows)
        atomic_write_json(self.root / "00_project_control/active_production_config.json",
            {"workflow": {"objective_research_max_tickers": 3}})
        positions = self.root / "05_risk_and_positions/current_positions.local.csv"
        positions.parent.mkdir(parents=True, exist_ok=True)
        positions.write_text("ticker,shares_optional\nTOP,1\n")
        self.collect([self.event("NEW", 20), self.event("OTH", 21)])
        report = run_backlog(input_root=self.root, output_root=self.root, current=NOW, max_tickers=3)
        self.assertEqual(report["reserved_external_event_tickers"], ["NEW", "OTH"])
        self.assertEqual(len(report["selected_tickers"]), 1)
        self.assertEqual(report["selected_tickers"], ["TOP"])
        self.assertEqual({r["ticker"] for r in read_csv(path)}, {"TOP", "MOMA", "MOMB"})
        attempted = []
        def inspect(root, item, **kwargs):
            attempted.append(item["ticker"])
            return None, "synthetic_current_primary_source_missing"
        with patch("research_opportunities.objective_research", side_effect=inspect):
            final = objective(self.root, current=NOW)
        self.assertEqual(attempted, ["NEW", "OTH"])
        self.assertEqual(final["metrics"]["canonical_issuers_attempted_before_intake"], 1)
        self.assertEqual(final["metrics"]["objective_items_processed"], 2)
        self.assertEqual(final["metrics"]["network_requests"], 0)


if __name__ == "__main__":
    unittest.main()
