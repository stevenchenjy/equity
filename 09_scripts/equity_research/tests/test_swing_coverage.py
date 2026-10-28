from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import market_discovery as md
import swing_coverage as coverage

NOW = datetime(2026, 9, 22, 14, tzinfo=md.ET)


def fixture(root):
    days = [str(d) for d in md.published_sessions(NOW, count=51)]
    meta = {"session": days[-1], "complete": True, "rows": {}}
    for ticker, kind in (("AAA", "CS"), ("BBB", "CS"), ("SPY", "ETF")):
        meta["rows"][ticker] = {"ticker": ticker, "name": ticker + " Company", "type": kind,
            "primary_exchange": "XNYS", "currency_name": "usd"}
    series = {}
    for i, day in enumerate(days):
        rows = {}
        for ticker, growth in (("AAA", 1.0), ("BBB", .6), ("SPY", .1)):
            close = 100 + i * growth
            rows[ticker] = {"o": close, "h": close+1, "l": close-1, "c": close, "v": 1_000_000}
        series[day] = {"session": day, "complete": True, "adjusted": True, "rows": rows}
        md._cache_write(root/md.CACHE_RELATIVE/f"grouped-{day}.local.json", series[day])
    md._cache_write(root/md.CACHE_RELATIVE/f"metadata-{days[-1]}.local.json", meta)
    report = md.build_report(meta, {day: series[day] for day in days[-21:]}, md.date.fromisoformat(days[-1]), {"SPY"})
    report["fetched_at"] = NOW.isoformat()
    md._cache_write(root/md.CACHE_RELATIVE/"latest.local.json", report)
    seed = root/coverage.UNIVERSE; seed.parent.mkdir(parents=True, exist_ok=True); seed.write_text("ticker\nSPY\n")
    return days, meta, series, report


def files(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class SwingCoverageTests(unittest.TestCase):
    def setUp(self):
        for name in ("MIN_COMMON_STOCKS", "MIN_ETFS", "MIN_GROUPED_ROWS"):
            handle = patch.object(md, name, 1); handle.start(); self.addCleanup(handle.stop)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.days, self.metadata, self.series, self.report = fixture(self.root)

    def test_complete_outside_histories_are_source_bound_readonly_and_not_canonical(self):
        before = files(self.root)
        result = coverage.admitted_histories(self.root, NOW)
        self.assertEqual(result["status"], "waiting_on_data")
        self.assertEqual(result["histories"], {})
        self.assertFalse(result["provisional_technical_history_admitted"])
        self.assertEqual(result["provisional_history_tickers"], ["AAA","BBB"])
        result = coverage._grouped_provisional(self.root, NOW)
        self.assertEqual(result["status"], "provisional_research_only")
        self.assertEqual(set(result["histories"]), {"AAA", "BBB"})
        for ticker, history in result["histories"].items():
            self.assertEqual(len(history["bars"]), 51)
            self.assertEqual(history["bars"][0]["session_date"], self.days[0])
            self.assertEqual(history["bars"][-1]["session_date"], self.days[-1])
            self.assertEqual(history["price_basis"], "split_adjusted")
            self.assertTrue(history["common_stock_verified"])
            self.assertFalse(history["canonical_admission"])
            self.assertEqual(history["actionable_quantity"], 0)
            self.assertTrue(history["corporate_action_review_required"])
            for rel, digest in history["source_bindings"].items():
                self.assertEqual(hashlib.sha256((self.root/rel).read_bytes()).hexdigest(), digest)
        self.assertEqual(files(self.root), before)

    def test_failed_current_attempt_withholds_prices_but_keeps_dated_original_lead(self):
        md._cache_write(self.root/md.CACHE_RELATIVE/"latest.local.json", md._empty(md.date.fromisoformat(self.days[-1]), "unavailable", "authentication_failed"))
        base = self.root/"04_research/company_research/opportunities.local"
        base.mkdir(parents=True); (base/"report.json").write_text("{}")
        first = "2026-09-15T08:45:00-04:00"
        item = {"ticker": "AAA", "state": "data_blocked", "first_seen_at": first,
            "observations": [{"family": "market", "instrument_kind": "stock", "observation_id": "original",
                "detected_at": first, "evidence": {"market_session": "2026-09-14", "metrics": {"name": "AAA", "rank": 1, "close": 900}},
                "sources": [{"sha256": "a"*64}]}]}
        before = files(self.root)
        with patch("research_opportunities.read_report", return_value={"opportunities": [item], "store_sha256": "b"*64}):
            result = coverage.build(self.root, NOW)
        self.assertEqual(result["status"], "waiting_on_data")
        self.assertEqual(result["admitted_history_tickers"], [])
        self.assertEqual(result["candidates"][0]["first_seen_at"], first)
        self.assertEqual(result["candidates"][0]["discovery_session"], "2026-09-14")
        self.assertIsNone(result["candidates"][0]["current_price"])
        self.assertEqual(result["candidates"][0]["actionable_quantity"], 0)
        self.assertNotIn("close", result["candidates"][0])
        self.assertEqual(result["latest_provider_failure"]["original_http_evidence"], "not_retained_by_older_collector")
        self.assertEqual(files(self.root), before)

    def test_missing_exact_sessions_are_not_replaced_by_older_or_fabricated_bars(self):
        missing = self.days[2]
        (self.root/md.CACHE_RELATIVE/f"grouped-{missing}.local.json").unlink()
        result = coverage.admitted_histories(self.root, NOW)
        self.assertEqual(result["histories"], {})
        self.assertEqual(result["coverage"]["missing_grouped_sessions"], [missing])
        self.assertIn("outside_swing_51_consecutive_sessions_missing", result["blockers"])

    def test_wrong_basis_corrupt_wrapper_or_future_publication_cannot_admit(self):
        for mode in ("basis", "checksum", "clock"):
            with self.subTest(mode=mode):
                fixture(self.root)
                path = self.root/md.CACHE_RELATIVE/f"grouped-{self.days[0]}.local.json"
                if mode == "basis":
                    value = deepcopy(self.series[self.days[0]]); value["adjusted"] = False; md._cache_write(path, value)
                elif mode == "checksum":
                    value = json.loads(path.read_text()); value["payload"]["rows"]["AAA"]["c"] += 1; path.write_text(json.dumps(value))
                else:
                    value = deepcopy(self.report); value["fetched_at"] = (NOW+timedelta(seconds=1)).isoformat()
                    md._cache_write(self.root/md.CACHE_RELATIVE/"latest.local.json", value)
                result = coverage.admitted_histories(self.root, NOW)
                self.assertEqual(result["histories"], {})
                self.assertEqual(result["status"], "waiting_on_data")

    def test_one_young_or_missing_ticker_does_not_block_another_valid_history(self):
        value = deepcopy(self.series[self.days[0]]); value["rows"].pop("AAA")
        md._cache_write(self.root/md.CACHE_RELATIVE/f"grouped-{self.days[0]}.local.json", value)
        result = coverage._grouped_provisional(self.root, NOW)
        self.assertEqual(result["status"], "provisional_research_only")
        self.assertEqual(set(result["histories"]), {"BBB"})
        self.assertIn("AAA", result["ticker_blockers"])

    def test_older_discontinuity_is_reviewed_not_relabelled_a_profitable_setup(self):
        value = deepcopy(self.series[self.days[0]])
        value["rows"]["AAA"] = {"o": 250, "h": 251, "l": 249, "c": 250, "v": 1_000_000}
        md._cache_write(self.root/md.CACHE_RELATIVE/f"grouped-{self.days[0]}.local.json", value)
        result = coverage._grouped_provisional(self.root, NOW)
        self.assertEqual(set(result["histories"]), {"BBB"})
        self.assertEqual(result["ticker_blockers"]["AAA"], "outside_swing_large_discontinuity_review")
        self.assertEqual(result["histories"]["BBB"]["basis_consistency"], "provider_declared_only_corporate_action_review_required")

    def test_saved_rank_cannot_become_an_admitted_history_without_original_source_agreement(self):
        report = deepcopy(self.report); report["all_stocks"][0]["score"] = 9999
        md._cache_write(self.root/md.CACHE_RELATIVE/"latest.local.json", report)
        result = coverage.admitted_histories(self.root, NOW)
        self.assertEqual(result["histories"], {})
        self.assertIn("outside_swing_discovery_not_bound_to_grouped_history", result["blockers"])

    def test_no_outside_opportunity_or_missing_scope_is_finite_without_writes(self):
        (self.root/coverage.UNIVERSE).write_text("ticker\nAAA\nBBB\nSPY\n")
        report = md.build_report(self.metadata, {day: self.series[day] for day in self.days[-21:]}, md.date.fromisoformat(self.days[-1]), {"AAA","BBB","SPY"})
        report["fetched_at"] = NOW.isoformat(); md._cache_write(self.root/md.CACHE_RELATIVE/"latest.local.json", report)
        result = coverage.build(self.root, NOW)
        self.assertEqual(result["status"], "waiting_on_data")
        self.assertEqual(result["candidates"], [])
        (self.root/coverage.UNIVERSE).unlink()
        self.assertEqual(coverage.build(self.root, NOW)["status"], "waiting_on_data")

    def test_current_focused_history_advances_even_when_broad_discovery_failed(self):
        # An independently retained unadjusted series is distinct from broad
        # grouped coverage. The dated screen stays dated and quantity stays zero.
        from test_swing_candidate_history import FakeMassive,targets,NOW as PRIVATE_NOW
        import swing_candidate_history as private
        tt=targets(self.root)
        with patch.object(md,"MIN_ETFS",0):
            private.collect(self.root,PRIVATE_NOW,massive=FakeMassive(self.root),targets=tt,max_candidates=1,clock=lambda:PRIVATE_NOW)
            end=md.latest_published_market_session(PRIVATE_NOW)
            md._cache_write(self.root/md.CACHE_RELATIVE/"latest.local.json",md._empty(end,"unavailable","authentication_failed"))
            before=files(self.root)
            result=coverage.build(self.root,PRIVATE_NOW)
        self.assertEqual(result["status"],"focused_research_ready")
        self.assertNotEqual(result["current_discovery_status"],"complete")
        self.assertEqual(result["admitted_history_tickers"],["AAA"])
        self.assertEqual(result["coverage"]["focused_admitted_history_count"],1)
        self.assertTrue(result["coverage"]["focused_scope_is_not_whole_market_coverage"])
        candidate=result["candidates"][0]
        self.assertEqual(candidate["source_status"],"current_focused_unadjusted_research_history")
        self.assertEqual(candidate["discovery_session"],"2026-10-26")
        self.assertEqual(candidate["source_session"],"2026-10-27")
        self.assertEqual(candidate["actionable_quantity"],0);self.assertIsNone(candidate["current_price"])
        self.assertEqual(files(self.root),before)

    def test_read_time_rebuild_does_not_trust_tampered_saved_prices(self):
        old = coverage.build(self.root, NOW)
        old["candidates"][0]["current_price"] = 999
        before = files(self.root)
        result = coverage.revalidate_projection(self.root, old, NOW)
        self.assertIsNone(result["candidates"][0]["current_price"])
        self.assertEqual(files(self.root), before)


if __name__ == "__main__": unittest.main()
