"""Objective batching preserves exact serial events, clocks and failure fences."""
from __future__ import annotations

import copy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import weakref

from _support import SCRIPT_DIR  # noqa: F401
import test_research_opportunities as fixtures
from daily_common import atomic_write_json, read_json
from opportunity_contract import (STORE_REL, REPORT_REL, MARKDOWN_REL, retain_input,
    transition, replay)
from market_discovery import CACHE_RELATIVE
from opportunity_evidence import EVIDENCE_REL
import research_opportunities as opportunities

NOW = fixtures.NOW
CURRENT = NOW + timedelta(seconds=10)
LEGACY_OBJECTIVE = r'''
@content_proof_scope()
def objective(root: Path, *, current: datetime, allow_network: bool = False, clock=None) -> dict:
    start = time.monotonic()
    clock = clock or (lambda: current)
    policy = validate_policy(read_json(root / POLICY_REL))
    with ExclusiveFileLock(root / BASE_REL / "store.lock"):
        previous = read_json(root / STORE_REL, empty_store())
        initial_items = replay(previous, root=root, current=current)
        store, metrics = {**previous, "events": list(previous["events"])}, _base_metrics()
        metrics["request_limit"] = 2*policy["external_issuers_per_fetch"]
        config = read_json(root / "00_project_control/active_production_config.json", {})
        budget = config.get("workflow", {}).get("objective_research_max_tickers", 3)
        # Reuse the authoritative work-budget bounds without inventing another
        # canonical research quota. Already attempted issuers consume this run.
        from research_backlog import MAX_WORK_BUDGET
        require(type(budget) is int and 1 <= budget <= MAX_WORK_BUDGET, "research_work_budget_invalid")
        backlog = read_json(root / "04_research/company_research/research_backlog.local.json", {})
        same_cycle = backlog.get("generated_at", "")[:10] == current.date().isoformat()
        canonical_attempted = set(backlog.get("selected_tickers", [])) if same_cycle else set()
        completed = len(canonical_attempted)
        remaining = max(0, budget-completed)
        rows = {r["ticker"]: r for r in read_csv(root / "03_source_data/equity_research/daily_fundamentals.csv")}
        market_session = latest_published_market_session(current).isoformat()
        held = held_tickers(root)
        prior_report = read_json(root / REPORT_REL, {})
        from capital_escalation import research_priorities
        escalation_rank = {ticker: i for i, ticker in enumerate(research_priorities(root, current))}
        reserved = set(backlog.get("reserved_external_event_tickers", [])) if same_cycle else set()
        def objective_priority(item):
            base = work_priority(item, held, current=current, escalation_rank=escalation_rank)
            # Canonical held work already performed must not consume the
            # isolated external slots a second time through an attachment.
            bucket = 0 if base[0] == 0 and item["ticker"] not in canonical_attempted else 1 if item["ticker"] in reserved else 2
            return (bucket, *base)
        for item in sorted(initial_items.values(), key=objective_priority):
            if item["state"] in TERMINAL | {"deferred_capacity"}:
                continue
            if metrics["objective_items_processed"] >= remaining:
                break
            task_started = clock()
            requests_before = metrics["network_requests"]
            dossier, reason = objective_research(root, item, current=task_started, policy=policy,
                canonical_rows=rows, market_session=market_session, allow_network=allow_network, metrics=metrics)
            task_completed = max(clock(), aware(dossier["observed_at"]) if dossier else task_started)
            latest_attachment = next((t for t in reversed(item["transitions"]) if t["to_state"] == "evidence_attached"), {})
            unchanged = ((dossier and latest_attachment.get("reason_code") == "objective_dossier:"+dossier["dossier_hash"]
                and item["state"] not in {"queued", "data_blocked"})
                or (not dossier and item["state"] == "data_blocked" and item["reason_code"] == reason and requests_before == metrics["network_requests"]))
            if unchanged:
                metrics["unchanged_items_skipped"] = metrics.get("unchanged_items_skipped", 0)+1
                continue
            metrics["objective_items_processed"] += 1
            attempt = {"ticker": item["ticker"], "reason_code": reason, "status": "source_bound" if dossier else "unverified",
                "dossier_hash": dossier.get("dossier_hash", "") if dossier else "", "canonical_fields_admitted": 0}
            metrics["attempts"].append(attempt)
            if not item["research_started_at"] and item["state"] in {"queued", "data_blocked", "evidence_attached", "insufficient_evidence"}:
                transition(store, item["opportunity_id"], "researching", owner="objective_research", reason="objective_source_inspection_started",
                    sources=item["first_observation"]["sources"], blockers=[], current=task_started)
            if dossier:
                src = retain_input(root, root / EVIDENCE_REL / "history" / (dossier["dossier_hash"]+".json"), available_at=dossier["observed_at"])
                if item["state"] in {"research_supported", "eligibility_review"}:
                    transition(store, item["opportunity_id"], "data_blocked", owner="objective_research", reason="changed_objective_evidence_requires_recorded_reassessment",
                        sources=[src], blockers=["current_business_and_valuation_reassessment"], current=task_completed)
                if replay(store)[item["opportunity_id"]]["state"] != "researching":
                    transition(store, item["opportunity_id"], "researching", owner="objective_research", reason="source_bound_objective_work_started",
                        sources=item["first_observation"]["sources"], blockers=[], current=task_completed)
                transition(store, item["opportunity_id"], "evidence_attached", owner="objective_research", reason="objective_dossier:"+dossier["dossier_hash"],
                    sources=[src], blockers=dossier["missing_evidence"], current=task_completed)
                metrics["objective_attachments_accepted"] += 1
                metrics["new_research_numeric_fields"] += len(dossier["facts_available"]) if not latest_attachment else 0
            elif item["state"] != "data_blocked" or item["reason_code"] != reason:
                transition(store, item["opportunity_id"], "data_blocked", owner="objective_research", reason=reason,
                    sources=item["observations"][-1]["sources"], blockers=[reason], current=task_completed)
        del initial_items
        final_current = max(clock(), aware(store["events"][-1]["recorded_at"]) if store["events"] else current)
        publish_store(root, store, previous=previous, current=final_current)
        metrics["duration_seconds"] = round(time.monotonic()-start, 4)
        metrics["shared_objective_work_budget"] = budget
        metrics["canonical_issuers_attempted_before_intake"] = completed
        report = publish_view(root, store, current=final_current, metrics=metrics, diagnostics=prior_report.get("diagnostics", {}))
        # The backlog's non-authoritative view must expose the accepted progress
        # from this same full refresh, without another objective pass.
        from research_backlog import refresh_attention_view
        refresh_attention_view(root, final_current)
        return report
'''


class ObjectiveTransitionBatchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OpportunityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root

    def setup_store(self, specs):
        # specs: ticker, initial state, provider mode, simulated network increment.
        store = self.fixture.queue_store([(ticker, 'queued', n, False)
            for n, (ticker, state, mode, network) in enumerate(specs, 1)])
        dossiers = {}
        for ticker, state, mode, network in specs:
            item = next(item for item in replay(store).values() if item['ticker'] == ticker)
            sources = item['observations'][-1]['sources']
            old = None
            if mode in {'success', 'cached', 'changed'}:
                old = self.fixture.evidence(ticker)
            if state in {'evidence_attached', 'research_supported'}:
                transition(store, item['opportunity_id'], 'researching', owner='objective_research',
                    reason='fixture_start', sources=sources, blockers=[], current=NOW)
                src = retain_input(self.root, self.root/EVIDENCE_REL/'history'/(old['dossier_hash']+'.json'),
                    available_at=old['observed_at'])
                transition(store, item['opportunity_id'], 'evidence_attached', owner='objective_research',
                    reason='objective_dossier:'+old['dossier_hash'], sources=[src],
                    blockers=old['missing_evidence'], current=NOW)
                if state == 'research_supported':
                    transition(store, item['opportunity_id'], state, owner='analyst_assessment',
                        reason='fixture_supported', sources=sources, blockers=[], current=NOW)
            elif state in {'data_blocked', 'researching'}:
                transition(store, item['opportunity_id'], state, owner='objective_research',
                    reason='same-block' if state == 'data_blocked' else 'fixture_start',
                    sources=sources, blockers=['same-block'] if state == 'data_blocked' else [], current=NOW)
            if mode == 'changed':
                (self.root/EVIDENCE_REL/(ticker+'.json')).unlink()
                with patch.object(fixtures, 'NOW', NOW+timedelta(seconds=1)):
                    dossiers[ticker] = self.fixture.evidence(ticker)
                self.assertNotEqual(old['dossier_hash'], dossiers[ticker]['dossier_hash'])
            elif old:
                dossiers[ticker] = old
        atomic_write_json(self.root/STORE_REL, store)
        atomic_write_json(self.root/'00_project_control/active_production_config.json',
            {'workflow': {'objective_research_max_tickers': 10}})
        atomic_write_json(self.root/'04_research/company_research/research_backlog.local.json',
            {'generated_at': CURRENT.isoformat(), 'selected_tickers': [],
             'reserved_external_event_tickers': []})
        atomic_write_json(self.root/REPORT_REL, {'diagnostics': {'fixture': 'retained diagnostics'}})
        return dossiers

    def run_objective(self, root, specs, dossiers, *, legacy=False, clocks=None, mutate_source=False,
                      timed_batch=None):
        calls = []
        values = iter(clocks or [NOW+timedelta(seconds=n) for n in range(11, 80)])

        def provider(root_arg, item, *, metrics, **kwargs):
            calls.append(item['ticker'])
            ticker, state, mode, network = next(row for row in specs if row[0] == item['ticker'])
            metrics['network_requests'] += network
            if mutate_source:
                (root_arg/item['first_observation']['sources'][0]['path']).write_bytes(b'external source change')
            return (copy.deepcopy(dossiers.get(ticker)),
                    'same-block' if state == 'data_blocked' else 'fixture_missing' if mode == 'blocked'
                    else 'source_bound_objective_attachment')

        with patch.object(opportunities, 'objective_research', side_effect=provider), \
                patch('capital_escalation.research_priorities', return_value=[row[0] for row in specs]), \
                patch('research_backlog.refresh_attention_view'), \
                patch('research_opportunities.time.monotonic', return_value=100):
            if legacy:
                namespace = dict(vars(opportunities))
                exec(LEGACY_OBJECTIVE, namespace)
                function = namespace['objective']
            else:
                function = opportunities.objective
            if timed_batch is None:
                result = function(root, current=CURRENT, clock=lambda: next(values))
            else:
                with patch.object(opportunities, 'transition_batch', side_effect=timed_batch):
                    result = function(root, current=CURRENT, clock=lambda: next(values))
        return result, calls

    def test_exact_legacy_journal_report_and_markdown_with_distinct_task_clocks(self):
        specs = [('AQUE', 'queued', 'success', 0),
                 ('BBLOCK', 'data_blocked', 'blocked', 1),
                 ('CSUPPORT', 'research_supported', 'changed', 0),
                 ('DCACHE', 'evidence_attached', 'cached', 0),
                 ('ERESEARCH', 'researching', 'blocked', 0),
                 ('FUNCHANGE', 'data_blocked', 'blocked', 0)]
        dossiers = self.setup_store(specs)
        with tempfile.TemporaryDirectory() as directory:
            old_root = Path(directory)/'serial'
            shutil.copytree(self.root, old_root)
            expected, old_calls = self.run_objective(old_root, specs, dossiers, legacy=True)
            actual, new_calls = self.run_objective(self.root, specs, dossiers)
            self.assertEqual(old_calls, new_calls)
            self.assertEqual(actual, expected)
            for relative in (STORE_REL, REPORT_REL, MARKDOWN_REL):
                self.assertEqual((self.root/relative).read_bytes(), (old_root/relative).read_bytes())
        items = {item['ticker']: item for item in replay(read_json(self.root/STORE_REL)).values()}
        # Preserve the old initial-data_blocked/reason condition even after a start event.
        self.assertEqual(items['BBLOCK']['state'], 'researching')
        self.assertEqual(items['DCACHE']['state'], 'evidence_attached')
        times = [event['recorded_at'] for event in read_json(self.root/STORE_REL)['events']
                 if event['recorded_at'] > CURRENT.isoformat()]
        self.assertGreater(len(set(times)), 2)
        self.assertEqual(actual['metrics']['unchanged_items_skipped'], 2)
        self.assertEqual(actual['metrics']['network_requests'], 1)
        self.assertEqual(actual['metrics']['canonical_fields_admitted'], 0)

    def test_regressing_clock_stops_before_a_later_issuer_and_never_publishes(self):
        specs = [('AONE', 'queued', 'blocked', 0), ('BTWO', 'queued', 'blocked', 0),
                 ('CTHREE', 'queued', 'blocked', 0)]
        dossiers = self.setup_store(specs)
        clocks = [NOW+timedelta(seconds=n) for n in (11, 12, 11, 13, 14, 15, 16)]
        before = (self.root/STORE_REL).read_bytes()
        results = []
        with tempfile.TemporaryDirectory() as directory:
            old_root = Path(directory)/'serial'
            shutil.copytree(self.root, old_root)
            for root, legacy in ((old_root, True), (self.root, False)):
                calls = []
                def provider(root, item, **kwargs):
                    calls.append(item['ticker'])
                    return None, 'fixture_missing'
                with patch.object(opportunities, 'objective_research', side_effect=provider), \
                        patch('capital_escalation.research_priorities', return_value=[row[0] for row in specs]), \
                        patch('research_backlog.refresh_attention_view'):
                    if legacy:
                        namespace = dict(vars(opportunities))
                        exec(LEGACY_OBJECTIVE, namespace)
                        function = namespace['objective']
                    else:
                        function = opportunities.objective
                    values = iter(clocks)
                    with self.assertRaisesRegex(ValueError, 'research_journal_clock_regression'):
                        function(root, current=CURRENT, clock=lambda: next(values))
                results.append(calls)
                self.assertEqual((root/STORE_REL).read_bytes(), before)
        # Both paths notice the second task's bad start after its work, before a third task.
        self.assertEqual(results, [['AONE', 'BTWO'], ['AONE', 'BTWO']])

    def test_changed_source_and_future_staged_event_fail_before_publication(self):
        specs = [('AONE', 'queued', 'blocked', 0)]
        dossiers = self.setup_store(specs)
        before = (self.root/STORE_REL).read_bytes()
        report_before = (self.root/REPORT_REL).read_bytes()
        with self.assertRaisesRegex(ValueError, 'research_source_changed'):
            self.run_objective(self.root, specs, dossiers, mutate_source=True)
        self.assertEqual((self.root/STORE_REL).read_bytes(), before)
        self.assertEqual((self.root/REPORT_REL).read_bytes(), report_before)
        # Restore only the test fixture's retained bytes; real code never repairs source mutations.
        source = self.root/read_json(self.root/STORE_REL)['events'][0]['observation']['sources'][0]['path']
        source.write_bytes((self.root/CACHE_RELATIVE/'latest.local.json').read_bytes())

        batch = opportunities.transition_batch
        def future_event(store, changes, *, root, current):
            changed = copy.deepcopy(changes)
            changed[-1]['recorded_at'] = (current+timedelta(seconds=1)).isoformat()
            return batch(store, changed, root=root, current=current)
        with self.assertRaisesRegex(ValueError, 'research_journal_clock_regression'):
            self.run_objective(self.root, specs, dossiers, timed_batch=future_event)
        self.assertEqual((self.root/STORE_REL).read_bytes(), before)
        self.assertEqual((self.root/REPORT_REL).read_bytes(), report_before)

    def test_shared_remaining_budget_and_reserved_order_match_legacy(self):
        specs = [('AONE', 'queued', 'blocked', 0), ('BTWO', 'queued', 'blocked', 0),
                 ('CTHREE', 'queued', 'blocked', 0)]
        dossiers = self.setup_store(specs)
        atomic_write_json(self.root/'00_project_control/active_production_config.json',
            {'workflow': {'objective_research_max_tickers': 3}})
        atomic_write_json(self.root/'04_research/company_research/research_backlog.local.json',
            {'generated_at': CURRENT.isoformat(), 'selected_tickers': ['PRIOR1', 'PRIOR2'],
             'reserved_external_event_tickers': ['BTWO']})
        with tempfile.TemporaryDirectory() as directory:
            old_root = Path(directory)/'serial'
            shutil.copytree(self.root, old_root)
            expected, old_calls = self.run_objective(old_root, specs, dossiers, legacy=True)
            actual, calls = self.run_objective(self.root, specs, dossiers)
            self.assertEqual((actual, calls), (expected, old_calls))
            self.assertEqual(calls, ['BTWO'])
            self.assertEqual(actual['metrics']['objective_items_processed'], 1)
            self.assertEqual(actual['metrics']['canonical_issuers_attempted_before_intake'], 2)
            self.assertEqual(actual['metrics']['shared_objective_work_budget'], 3)

    def test_objective_journal_walks_are_constant_as_task_count_grows(self):
        import opportunity_contract as contract
        for count in (1, 3, 6):
            with self.subTest(count=count):
                specs = [('TASK'+str(n), 'queued', 'blocked', 0) for n in range(count)]
                dossiers = self.setup_store(specs)
                with patch.object(contract, '_replay', wraps=contract._replay) as calls:
                    report, tasks = self.run_objective(self.root, specs, dossiers)
                self.assertEqual(len(tasks), count)
                self.assertEqual(report['metrics']['objective_items_processed'], count)
                self.assertEqual(calls.call_count, 5)

    def test_prior_report_is_released_before_issuer_work(self):
        specs = [('AONE', 'queued', 'blocked', 0)]
        self.setup_store(specs)
        class PriorReport(dict):
            pass
        weak = []
        reader = opportunities.read_json
        def report_reader(path, *args, **kwargs):
            if path == self.root/REPORT_REL:
                report = PriorReport(diagnostics={'fixture': 'retained diagnostics'},
                                     unused_history=[{'large': 'unused retained view'}])
                weak.append(weakref.ref(report))
                return report
            return reader(path, *args, **kwargs)
        def provider(root, item, **kwargs):
            self.assertTrue(weak)
            self.assertIsNone(weak[0](), 'unused full prior report remains retained')
            return None, 'fixture_missing'
        with patch.object(opportunities, 'read_json', side_effect=report_reader), \
                patch.object(opportunities, 'objective_research', side_effect=provider), \
                patch('capital_escalation.research_priorities', return_value=[]), \
                patch('research_backlog.refresh_attention_view'):
            opportunities.objective(self.root, current=CURRENT)
