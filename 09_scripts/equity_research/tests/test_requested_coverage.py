from __future__ import annotations

import csv
import json
import unittest
from datetime import date
from unittest.mock import patch

from _support import PROJECT_ROOT, SCRIPT_DIR  # noqa: F401
import build_current_research_baseline as baseline
import account_common as c9
import refresh_daily_evidence as evidence
from long_horizon_research import build_long_horizon_report


REQUIRED = {"SPY", "APP", "IOT", "RBRK", "RKLB", "META", "NOW", "QQQM", "NVDA", "XLI"}
POLICY = json.loads((PROJECT_ROOT / "01_policies/long_horizon_research_policy.json").read_text())


class RequestedCoverageTests(unittest.TestCase):
    def test_owner_names_survive_ranked_shortlist_without_becoming_eligible(self):
        def rows(path):
            if path == baseline.POSITIONS_PATH:
                return [{"ticker": "APP"}]
            if path == baseline.SIGNAL_SCORES_PATH:
                return [
                    {"ticker": ticker, "total_score": "9.0", "data_quality_label": "ok"}
                    for ticker in ("AAA", "BBB", "CCC", "DDD")
                ]
            return []

        with patch.object(baseline, "read_csv", side_effect=rows):
            selected, held = baseline.selected_tickers()
        self.assertTrue(REQUIRED.issubset(selected))
        self.assertEqual(held, {"APP"})
        self.assertTrue({"AAA", "BBB", "CCC"}.issubset(selected))
        self.assertNotIn("DDD", selected)

    def test_requested_coverage_rejects_missing_duplicate_or_malformed_symbols(self):
        for value in (None, [], ["APP", "APP"], ["app"], ["https://example.com"], [None]):
            with self.subTest(value=value), patch.object(
                baseline, "read_json", return_value={"coverage_tickers": value}
            ):
                with self.assertRaises(ValueError):
                    baseline.requested_coverage_tickers()

    def test_new_seed_rows_cover_requested_prices_but_do_not_authorize_etf_core(self):
        with baseline.UNIVERSE_PATH.open(newline="") as handle:
            seeds = list(csv.DictReader(handle))
        tickers = [row["ticker"] for row in seeds]
        self.assertEqual(len(tickers), 31)
        self.assertEqual(len(set(tickers)), 31)
        self.assertTrue(REQUIRED.issubset(set(tickers) | {"IOT", "RBRK"}))
        by_ticker = {row["ticker"]: row for row in seeds}
        for ticker in ("QQQM", "XLI"):
            self.assertEqual(by_ticker[ticker]["is_benchmark"], "yes")
            self.assertFalse(evidence.company_fundamentals_required(ticker))
            self.assertFalse(c9.is_core_allocation_ticker(ticker))
            self.assertIn(ticker, POLICY["excluded_benchmarks"])
        for ticker in ("APP", "RKLB"):
            self.assertTrue(evidence.company_fundamentals_required(ticker))
            self.assertIn("analyst qualitative", by_ticker[ticker]["notes"])

    def test_named_missing_company_evidence_stays_watch_and_etfs_are_not_stocks(self):
        def rows(path):
            if path == baseline.MARKET_SNAPSHOT_PATH:
                return [
                    {"ticker": ticker, "last_price": "100", "market_session_date": "2026-09-18",
                     "data_quality_label": "ok", "data_source": "fixture"}
                    for ticker in REQUIRED
                ]
            if path == baseline.UNIVERSE_PATH:
                return [
                    {"ticker": ticker, "is_benchmark": "yes" if ticker in {"SPY", "QQQM", "XLI"} else "no"}
                    for ticker in REQUIRED
                ]
            return []

        with patch.object(baseline, "read_csv", side_effect=rows), \
             patch.object(baseline, "latest_published_market_session", return_value=date(2026, 9, 18)), \
             patch.object(baseline, "atomic_write_csv") as write:
            self.assertEqual(baseline.main(), 0)
        by_ticker = {row["ticker"]: row for row in write.call_args.args[2]}
        self.assertEqual(set(by_ticker), REQUIRED)
        for ticker in REQUIRED - {"SPY", "QQQM", "XLI"}:
            self.assertEqual(by_ticker[ticker]["recommendation_label"], "watch_for_valuation")
            self.assertEqual(by_ticker[ticker]["human_action_required"], "no")
            self.assertEqual(by_ticker[ticker]["primary_source_url"], "")
        for ticker in ("QQQM", "XLI"):
            self.assertEqual(by_ticker[ticker]["research_role"], "etf_research_candidate")
            self.assertEqual(by_ticker[ticker]["recommendation_label"], "watch_for_allocation_review")
            self.assertIn("not_applicable_to_etf", by_ticker[ticker]["valuation_check"])

    def test_missing_named_market_data_still_blocks_baseline_commit(self):
        with patch.object(baseline, "selected_tickers", return_value=(["RKLB"], set())), \
             patch.object(baseline, "read_csv", return_value=[]), \
             patch.object(baseline, "atomic_write_csv") as write:
            with self.assertRaisesRegex(ValueError, "valid completed close for RKLB"):
                baseline.main()
        write.assert_not_called()

    def test_held_noncore_etf_omits_company_scenarios_without_core_promotion(self):
        report = build_long_horizon_report(
            [], [{"ticker": "QQQM"}, {"ticker": "XLI"}], [], POLICY, "2026-09-22T20:00:00+00:00"
        )
        for ticker in ("QQQM", "XLI"):
            row = report["companies"][ticker]
            self.assertEqual(row["readiness"], "not_applicable_etf")
            self.assertEqual(row["thesis"]["status"], "allocation_policy_review_required")
            self.assertNotIn("sensitivity_scenarios", row)
        self.assertFalse(report["recommendation_authority"])
        self.assertFalse(report["automatic_action_allowed"])


if __name__ == "__main__":
    unittest.main()
