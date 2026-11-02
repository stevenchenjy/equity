"""Migration/capture regressions for separate active V3 benchmark registration."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR
import active_swing_research as active
import active_swing_benchmark_review as active_review
import frozen_swing_runtime as runtime
import swing_benchmarks as legacy
import swing_benchmarks_v2 as benchmark
import swing_benchmark_quotes as quotes
import swing_research_v2 as legacy_study
import test_swing_benchmarks as fixtures
import test_swing_benchmark_review as review_fixtures
import swing_research as common


ROOT=SCRIPT_DIR.parents[1]


def setup(root):
    for relative in [active.POLICY,runtime.CONFIG,benchmark.POLICY]:
        path=root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((ROOT/relative).read_bytes())
    policy=json.loads((root/benchmark.POLICY).read_text())
    return datetime.fromisoformat(policy["registered_at"])+timedelta(seconds=1)


class BenchmarkV2MigrationTests(unittest.TestCase):
    def test_genuine_v3_outcomes_capture_both_benchmarks_and_forward_review_in_new_namespace(self):
        # All prices and evidence below come from explicitly synthetic retained
        # provider fixtures; no real performance, network or broker is involved.
        case=fixtures.MatchedBenchmarkTests("test_future_open_both_benchmarks_same_dates_costs_and_unique_denominators")
        case.setUp()
        try:
            root=case.root
            for relative in [active.POLICY,runtime.CONFIG,benchmark.POLICY]:
                (root/relative).write_bytes((ROOT/relative).read_bytes())
            policy=json.loads((root/benchmark.POLICY).read_text())
            policy["registered_at"]="2026-09-22T16:45:00-04:00"
            (root/benchmark.POLICY).write_text(json.dumps(policy))
            first=active.build(root,case.capture_clock,capture=True)
            self.assertEqual(first["status"],"experimental_current",first)
            days=common._sessions_after(case.capture_clock.date(),5)
            forward=[{"session_date":day,"open":512.+i,"high":515.+i,"low":508.+i,"close":513.+i,"volume":1100.} for i,day in enumerate(days)]
            case._write_market(case.msft+forward)
            matured=active.build(root,case.future,capture=True)
            self.assertEqual(matured["status"],"experimental_current",matured)
            source_before=(root/active.OUTPUT/"ledger.jsonl").read_bytes()
            clock=case.future+timedelta(minutes=5)
            view=benchmark.build(root,clock,capture=True)
            self.assertEqual(view["status"],"raw_comparisons_available",view)
            self.assertEqual(view["summary"]["unique_stock_outcomes"],1)
            self.assertEqual(view["summary"]["comparison_pairs"],2)
            records,_=benchmark._comparison_ledger(root,clock)
            record=next(row for row in records if row["benchmark"]=="SPY")
            helper=review_fixtures.BenchmarkForwardReviewTests("test_prior_outside_window_distribution_does_not_block_forward_review_or_clear_stock")
            helper.root=root;helper.clock=clock
            proposal=helper._proposal(record)
            accepted=active_review.review(root,proposal,clock,apply=True)
            self.assertFalse(accepted["original_stock_setup_history_cleared"])
            self.assertEqual(len(active_review.read_reviews(root,clock)),1)
            self.assertTrue((root/active_review.STORE).exists())
            self.assertFalse((root/legacy.OUTPUT/"forward_reviews.jsonl").exists())
            updated=benchmark.build(root,clock+timedelta(seconds=1),capture=True)
            self.assertEqual(updated["summary"]["comparison_pairs"],2)
            self.assertEqual(updated["summary"]["reviewed_pairs"],0)
            self.assertEqual(updated["summary"]["qualified_strategy_paths"],0)
            self.assertEqual((root/active.OUTPUT/"ledger.jsonl").read_bytes(),source_before)
        finally:
            case.temporary.cleanup()

    def test_capture_with_prior_registration_uses_new_namespace_and_preserves_all_legacy_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);current=setup(root)
            old=root/legacy.OUTPUT;old.mkdir(parents=True)
            originals={
                "registration.json":json.dumps({"version":legacy.VERSION,"policy_sha256":"a"*64,"implementation_sha256":"b"*64}).encode(),
                "comparisons.jsonl":b"", "forward_reviews.jsonl":b"legacy bytes deliberately not an active review\n",
                "projections/historical.json":b'{"historical":true}\n'}
            for name,raw in originals.items():
                path=old/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
            first=benchmark.build(root,current,capture=True)
            self.assertEqual(first["status"],"pending_forward_evidence",first)
            self.assertEqual(first["protocol"]["version"],benchmark.VERSION)
            self.assertEqual(first["stock_source"]["path"],str(active.OUTPUT/"ledger.jsonl"))
            self.assertEqual(first["comparison_source"]["path"],str(benchmark.OUTPUT/"comparisons.jsonl"))
            registration=(root/benchmark.OUTPUT/"registration.json").read_bytes()
            self.assertNotEqual(registration,originals["registration.json"])
            second=benchmark.build(root,current+timedelta(seconds=1),capture=True)
            self.assertEqual(second["status"],"pending_forward_evidence",second)
            self.assertEqual((root/benchmark.OUTPUT/"registration.json").read_bytes(),registration)
            comparisons=root/benchmark.OUTPUT/"comparisons.jsonl"
            self.assertEqual(comparisons.read_bytes() if comparisons.exists() else b"",b"")
            checked=benchmark.revalidate_projection(root,first,current+timedelta(seconds=2))
            self.assertEqual(checked["status"],"pending_forward_evidence",checked)
            self.assertEqual(active_review.OUTPUT,benchmark.OUTPUT)
            self.assertEqual(active_review.read_reviews(root,current),[])
            for name,raw in originals.items():self.assertEqual((old/name).read_bytes(),raw)

    def test_missing_or_invalid_active_registry_does_not_fall_back_to_legacy_stock_rows(self):
        for invalid in [False,True]:
            with self.subTest(invalid=invalid),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);current=setup(root)
                if invalid:(root/runtime.CONFIG).write_text('{}')
                else:(root/active.POLICY).unlink()
                with patch.object(legacy_study,"_load",side_effect=AssertionError("legacy fallback used")):
                    view=benchmark.build(root,current,capture=True)
                self.assertEqual(view["status"],"unavailable")
                self.assertFalse((root/benchmark.OUTPUT/"registration.json").exists())
                self.assertFalse((root/benchmark.OUTPUT/"comparisons.jsonl").exists())

    def test_quote_entry_selection_preserves_original_receipt_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);current=setup(root)
            original_rel=quotes.REL
            with patch.object(active,"_load",return_value=[]) as load,patch.object(active,"_verify") as verify:
                self.assertEqual(quotes._entries(root,current),({},{}))
                load.assert_called_once_with(root,current);verify.assert_called_once_with(root,[])
            (root/active.POLICY).unlink()
            with patch.object(legacy_study,"_load",return_value=[]) as load,patch.object(legacy_study,"_verify") as verify:
                self.assertEqual(quotes._entries(root,current),({},{}))
                load.assert_called_once_with(root,current);verify.assert_called_once_with(root,[])
            self.assertEqual(quotes.REL,original_rel)
            self.assertEqual(quotes.REL,"03_source_data/equity_research/swing_benchmark_quotes.local")


if __name__=="__main__":unittest.main()
