"""Exact pre-change intake oracle and bounded initial-read regressions."""
from __future__ import annotations

import copy
from datetime import timedelta
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from daily_common import atomic_write_json, read_json
import opportunity_contract as contract
import research_opportunities as opportunities
from opportunity_triggers import packet
import test_research_opportunities as fixtures

NOW = fixtures.NOW
# Captured verbatim from the deployed pre-change intake; this oracle never
# follows future edits to the implementation under test.
LEGACY_INTAKE_SOURCE = r'''
def intake(root: Path, *, current: datetime) -> dict:
    start = time.monotonic()
    policy = validate_policy(read_json(root / POLICY_REL))
    with ExclusiveFileLock(root / BASE_REL / "store.lock"):
        previous = read_json(root / STORE_REL, empty_store())
        items = replay(previous, root=root, current=current)
        # Events are append-only. Candidate transitions append new records and
        # never edit an existing event, so only the event list needs isolation.
        store, metrics = {**previous, "events": list(previous["events"])}, _base_metrics()
        held = held_tickers(root)
        expirations = []
        for identity, item in items.items():
            if item["state"] not in TERMINAL and item["ticker"] not in held and elapsed_sessions(item["last_evidence_at"], current) >= policy["stale_after_market_sessions"]:
                expirations.append({"identity": identity, "target": "expired", "owner": "research_orchestration",
                    "reason": "research_evidence_stale_without_reassessment", "sources": item["first_observation"]["sources"],
                    "blockers": ["new_evidence_and_recorded_reassessment_required"]})
                metrics["expired"] += 1
        if expirations:
            transition_batch(store, expirations, root=root, current=current)
        seen = {p["observation_id"] for i in items.values() for p in i["observations"]}
        by_ticker = {i["ticker"]: identity for identity, i in items.items()}
        latest_schedules = {(i["ticker"], p["evidence"]["event"]["event_id"]): p
            for i in items.values() for p in i["observations"]
            if p.get("trigger") == "upcoming_earnings_calendar"}
        # These small lookup projections contain everything intake still
        # needs. Release the full copied history before collecting new leads.
        del items, expirations
        packets, diagnostics = collect_triggers(root, current=current, policy=policy,
            known_schedule_ids={event_id for _, event_id in latest_schedules})
        for p in sorted(packets, key=lambda i: priority(i, held, current=current)):
            schedule_key = ((p["ticker"], p["evidence"]["event"]["event_id"])
                if p.get("trigger") == "upcoming_earnings_calendar" else None)
            latest = latest_schedules.get(schedule_key)
            duplicate = p["observation_id"] in seen
            if ((latest and _earnings_schedule_evidence(latest["evidence"]) == _earnings_schedule_evidence(p["evidence"]))
                    or duplicate and not latest):
                metrics["duplicate_packets_skipped"] += 1
                continue
            if duplicate:
                # A recovery can match an earlier original schedule. Bind
                # this newly observed state to the immediately prior state
                # rather than rewriting history or discarding it as old.
                evidence = {**p["evidence"], "prior_schedule_observation_id": latest["observation_id"]}
                p = packet(ticker=p["ticker"], family=p["family"], trigger=p["trigger"],
                    evidence=evidence, sources=p["sources"], current=aware(p["detected_at"]),
                    produced_by=p["producer"], kind=p["instrument_kind"], missing=p["missing_evidence"])
                validate_observation(p, root=root, current=current)
            identity = by_ticker.get(p["ticker"])
            if identity:
                append_event(store, {"kind": "observed", "opportunity_id": identity,
                    "recorded_at": current.isoformat(), "observation": p, "owner": "research_orchestration",
                    "reason_code": "changed_evidence_first_seen_preserved"})
                metrics["rediscovery_updates"] += 1
            else:
                identity = canonical_sha256({"first_observation_id": p["observation_id"], "ticker": p["ticker"]})
                append_event(store, {"kind": "detected", "opportunity_id": identity,
                    "recorded_at": current.isoformat(), "observation": p, "owner": "research_orchestration",
                    "to_state": "deferred_capacity", "reason_code": "research_capacity_wait",
                    "blockers": ["bounded_research_capacity"]})
                by_ticker[p["ticker"]] = identity
            seen.add(p["observation_id"])
            if schedule_key:
                latest_schedules[schedule_key] = p
        del seen, by_ticker, latest_schedules, packets
        # A separately accepted analyst review can move deferred work into an
        # active state. Reconcile that real lifecycle transition before new
        # admissions; preserve its assessment and the displaced unfinished work.
        current_items = replay(store)
        changes, admitted = _queue_transitions(current_items, held, policy, current=current)
        if changes:
            transition_batch(store, changes, root=root, current=current)
        metrics["new_opportunities"] += admitted
        # Publication performs its own complete source-bound replay. Do not
        # retain another full materialized history while that proof is built.
        del current_items, changes
        publish_store(root, store, previous=previous, current=current)
        metrics["duration_seconds"] = round(time.monotonic()-start, 4)
        return publish_view(root, store, current=current, metrics=metrics, diagnostics=diagnostics)
'''


class IntakeBoundStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.OpportunityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root

    def history_bytes(self, root):
        base = root / contract.BASE_REL
        return {str(path.relative_to(base)): path.read_bytes()
                for name in ('history', 'run_history') for path in (base/name).rglob('*') if path.is_file()}

    def compare(self, packets, *, current=NOW, held=None, tie=False):
        with tempfile.TemporaryDirectory() as directory:
            old_root = Path(directory)/'legacy'
            shutil.copytree(self.root, old_root)
            results = []
            for root, legacy in ((old_root, True), (self.root, False)):
                def collect(*args, **kwargs):
                    return copy.deepcopy(packets), {'fixture': 'unchanged diagnostics'}
                with patch.object(opportunities, 'collect_triggers', side_effect=collect),                         patch.object(opportunities, 'held_tickers', return_value=set(held or [])),                         patch('research_opportunities.time.monotonic', return_value=100):
                    namespace = dict(vars(opportunities))
                    exec(LEGACY_INTAKE_SOURCE, namespace)
                    function = namespace['content_proof_scope']()(namespace['intake']) if legacy else opportunities.intake
                    if tie:
                        with patch.object(opportunities, 'priority', return_value=(2, 'same', 1)):
                            result = function(root, current=current)
                    else:
                        result = function(root, current=current)
                    results.append(result)
            self.assertEqual(results[0], results[1])
            for relative in (contract.STORE_REL, contract.REPORT_REL, contract.MARKDOWN_REL):
                self.assertEqual((old_root/relative).read_bytes(), (self.root/relative).read_bytes())
            self.assertEqual(self.history_bytes(old_root), self.history_bytes(self.root))
            return results[1]

    def test_empty_bootstrap_matches_exact_legacy_store_report_markdown_and_history(self):
        seed = self.fixture.queue_store([('AONE', 'queued', 1, False), ('BTWO', 'queued', 2, False)])
        report = self.compare([event['observation'] for event in seed['events']])
        self.assertEqual(report['metrics']['new_opportunities'], 2)
        self.assertEqual(len(report['opportunities']), 2)

    def test_expiry_precedes_rediscovery_with_exact_legacy_history(self):
        store = self.fixture.deferred_store(2)
        atomic_write_json(self.root/contract.STORE_REL, store)
        current = NOW + timedelta(days=10)
        prior = store['events'][0]
        observed = packet(ticker=prior['observation']['ticker'], family='request', trigger='owner_requested_research',
            evidence={'question': 'Synthetic changed question'}, sources=prior['observation']['sources'], current=current,
            produced_by={'implementation_sha256':'a'*64, 'policy_sha256':'b'*64})
        report = self.compare([observed], current=current)
        final = read_json(self.root/contract.STORE_REL)
        self.assertEqual([event['kind'] for event in final['events'][2:]], ['transition','transition','observed'])
        self.assertEqual(report['metrics']['expired'], 2)
        self.assertEqual(report['metrics']['rediscovery_updates'], 1)

    def test_calendar_recovery_keeps_old_versions_and_detached_collector_ids(self):
        self.fixture.calendar_fixture()
        store = read_json(self.root/contract.STORE_REL)
        original = copy.deepcopy(store['events'][0]['observation'])
        evidence = copy.deepcopy(original['evidence'])
        evidence['event'].update(status='schedule_conflict', blockers=['synthetic_conflict'])
        conflict = packet(ticker='EARN', family='catalyst', trigger='upcoming_earnings_calendar',
            evidence=evidence, sources=original['sources'], current=NOW-timedelta(minutes=20),
            produced_by=original['producer'])
        contract.append_event(store, {'kind':'observed', 'opportunity_id':store['events'][0]['opportunity_id'],
            'recorded_at':(NOW-timedelta(minutes=20)).isoformat(), 'observation':conflict,
            'owner':'research_orchestration', 'reason_code':'synthetic_conflict'})
        atomic_write_json(self.root/contract.STORE_REL, store)
        before = copy.deepcopy(store)
        report = self.compare([original])
        recovered = read_json(self.root/contract.STORE_REL)
        self.assertEqual(recovered['events'][:len(before['events'])], before['events'])
        updates = [event['observation'] for event in recovered['events'][len(before['events']):] if event['kind']=='observed']
        self.assertEqual(updates[0]['evidence']['prior_schedule_observation_id'], conflict['observation_id'])
        self.assertEqual(report['metrics']['rediscovery_updates'], 1)
        prefix = copy.deepcopy(recovered['events'])
        def collector(root, **kwargs):
            known = kwargs['known_schedule_ids']
            self.assertEqual(known, {'known-schedule'})
            self.assertTrue(all(type(value) is str for value in known))
            known.clear(); known.add('mutated detached set')
            return [], {}
        with patch.object(opportunities, 'collect_triggers', side_effect=collector):
            opportunities.intake(self.root, current=NOW)
        self.assertEqual(read_json(self.root/contract.STORE_REL)['events'][:len(prefix)], prefix)

    def test_victim_and_exact_tie_order_match_legacy(self):
        for specs, held, tie in (([('OLD','queued',40,False),('HELD','deferred_capacity',1,False)], {'HELD'}, False),
                                 ([('ONE','queued',1,False),('TWO','queued',1,False),('THREE','queued',1,False)], set(), True)):
            with self.subTest(tie=tie):
                store = self.fixture.queue_store(specs)
                atomic_write_json(self.root/contract.STORE_REL, store)
                policy = read_json(self.root/contract.POLICY_REL)
                policy.update(active_capacity=1, new_opportunities_per_run=1)
                atomic_write_json(self.root/contract.POLICY_REL, policy)
                self.compare([], held=held, tie=tie)

    def test_initial_borrowed_projection_omits_history_copy_but_keeps_all_checks(self):
        store = self.fixture.queue_store([('AONE','queued',1,False)])
        atomic_write_json(self.root/contract.STORE_REL, store)
        original = contract._replay
        calls = []
        def inspect_initial(value, **kwargs):
            calls.append(kwargs)
            if len(calls)==1:
                self.assertIs(kwargs.get('copy_history'), False)
                self.assertEqual(kwargs.get('root'), self.root)
                self.assertEqual(kwargs.get('current'), NOW)
                with patch.object(contract.copy, 'deepcopy', side_effect=AssertionError('initial history copy')):
                    return original(value, **kwargs)
            return original(value, **kwargs)
        with patch.object(contract, '_replay', side_effect=inspect_initial),                 patch.object(opportunities, 'collect_triggers', return_value=([], {})):
            opportunities.intake(self.root, current=NOW)
        self.assertTrue(any(call.get('materialize') is False and call.get('root') == self.root for call in calls[1:]))
        source = self.root/store['events'][0]['observation']['sources'][0]['path']
        source.write_bytes(b'changed retained source')
        with patch.object(opportunities, 'collect_triggers') as collect:
            with self.assertRaisesRegex(ValueError, 'source_changed'):
                opportunities.intake(self.root, current=NOW)
        collect.assert_not_called()

    def test_raw_source_and_clock_mutation_fail_before_any_new_publication(self):
        store = self.fixture.queue_store([('AONE','queued',1,False)])
        atomic_write_json(self.root/contract.STORE_REL, store)
        baseline = (self.root/contract.STORE_REL).read_bytes()
        source = self.root/store['events'][0]['observation']['sources'][0]['path']
        source_bytes = source.read_bytes()
        for fault in ('raw', 'source', 'clock'):
            with self.subTest(fault=fault):
                (self.root/contract.STORE_REL).write_bytes(baseline)
                source.write_bytes(source_bytes)
                def collect(root, **kwargs):
                    if fault=='raw':
                        (root/contract.STORE_REL).write_bytes(baseline+b'\n')
                    elif fault=='source':
                        source.write_bytes(b'external source replacement')
                    return [], {}
                with patch.object(opportunities, 'collect_triggers', side_effect=collect):
                    with self.assertRaises(ValueError):
                        opportunities.intake(self.root, current=NOW-timedelta(microseconds=1) if fault=='clock' else NOW)
                self.assertEqual((self.root/contract.STORE_REL).read_bytes(), baseline+(b'\n' if fault=='raw' else b''))
                self.assertFalse((self.root/contract.REPORT_REL).exists())
                self.assertEqual(self.history_bytes(self.root), {})


if __name__=='__main__':
    unittest.main()
