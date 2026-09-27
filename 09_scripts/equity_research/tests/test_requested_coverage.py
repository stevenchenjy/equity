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
import regenerate_portfolio_outputs as portfolio
import refresh_valuation_scenarios as valuation
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

    def test_unheld_requested_only_missing_price_is_visible_without_scores_or_shares(self):
        def rows(path):
            if path == baseline.MARKET_SNAPSHOT_PATH:
                return [{"ticker": "SPY", "last_price": "100", "market_session_date": "2026-09-18",
                         "data_quality_label": "ok", "data_source": "fixture"}]
            if path == baseline.UNIVERSE_PATH:
                return [{"ticker": "SPY", "is_benchmark": "yes"}]
            if path == baseline.FUNDAMENTALS_PATH:
                return [{"ticker": "IOT", "revenue_yoy_pct": "30", "source_url": "https://www.sec.gov/fixture"}]
            return []

        with patch.object(baseline, "selected_tickers", return_value=(["IOT", "SPY"], {"SPY"})), \
             patch.object(baseline, "read_csv", side_effect=rows), \
             patch.object(baseline, "latest_published_market_session", return_value=date(2026, 9, 18)), \
             patch.object(baseline, "atomic_write_csv") as write:
            self.assertEqual(baseline.main(), 0)
        packets = {row["ticker"]: row for row in write.call_args.args[2]}
        row = packets["IOT"]
        self.assertEqual(row["research_role"], baseline.PRICE_UNVERIFIED_ROLE)
        self.assertEqual(row["recommendation_label"], "watch_for_price_evidence")
        for field in ("market_score", "technical_entry_discipline_score", "market_data_source"):
            self.assertEqual(row[field], "")
        self.assertIn("30", row["earnings_check"])
        self.assertEqual(packets["SPY"]["recommendation_label"], "hold_existing")
        score = portfolio.price_unverified_score("IOT", row)
        self.assertEqual(score["account_aware_conviction_score"], "")
        self.assertEqual(score["technical_entry_discipline_score"], "")
        self.assertEqual(score["weekly_rank"], "")
        recommendation = portfolio.price_unverified_recommendation("IOT", row)
        self.assertEqual(recommendation["suggested_whole_shares"], "0")
        self.assertEqual(recommendation["recommended_action"], "watch_only")
        self.assertEqual(recommendation["current_price"], "")
        self.assertEqual(recommendation["maximum_review_price"], "")
        self.assertEqual(recommendation["valuation_base_price"], "")
        self.assertEqual(recommendation["automatic_action_allowed"], "no")
        self.assertTrue(all(recommendation[field] == "no" for field in recommendation if field.endswith("_pass")))

    def test_missing_close_for_held_or_approved_or_unrequested_remains_fatal(self):
        for ticker, held in (("IOT", {"IOT"}), ("RKLB", set()), ("SPY", set()), ("UNREQ", set())):
            with self.subTest(ticker=ticker), \
                 patch.object(baseline, "selected_tickers", return_value=([ticker], held)), \
                 patch.object(baseline, "read_csv", return_value=[]), \
                 patch.object(baseline, "atomic_write_csv") as write:
                with self.assertRaisesRegex(ValueError, f"valid completed close for {ticker}"):
                    baseline.main()
                write.assert_not_called()

    def test_research_only_guard_independently_checks_scope_and_market_validity(self):
        kwargs = {"held": set(), "requested": {"IOT", "RKLB"}, "market_row": {}, "expected_session": "2026-09-18"}
        self.assertTrue(baseline.requested_only_price_unverified("IOT", **kwargs))
        self.assertFalse(baseline.requested_only_price_unverified("RKLB", **kwargs))
        self.assertFalse(baseline.requested_only_price_unverified("UNREQ", **kwargs))
        self.assertFalse(baseline.requested_only_price_unverified("IOT", **(kwargs | {"held": {"IOT"}})))
        valid_quote = {"market_session_date": "2026-09-18", "data_quality_label": "ok", "last_price": "40"}
        self.assertFalse(baseline.requested_only_price_unverified("IOT", **(kwargs | {"market_row": valid_quote})))
        for invalid_price in ("0", "-1", "nan", "inf", ""):
            self.assertFalse(baseline.valid_completed_close(valid_quote | {"last_price": invalid_price}, "2026-09-18"))

    def test_missing_or_stale_requested_only_quote_never_creates_valuation(self):
        for quote in ({}, {"ticker": "IOT", "last_price": "40", "market_session_date": "2026-09-17", "data_quality_label": "ok"}):
            packet = baseline.price_unverified_research_row("IOT", {}, "2026-09-18")

            def rows(path):
                if path == valuation.BASELINE_PATH:
                    return [packet]
                if path == valuation.MARKET_SNAPSHOT_PATH:
                    return [quote] if quote else []
                return []

            with self.subTest(quote=quote), patch.object(valuation, "read_csv", side_effect=rows), \
                 patch.object(valuation, "latest_published_market_session", return_value=date(2026, 9, 18)), \
                 patch.object(valuation, "valuation_input_issues", side_effect=AssertionError("must not construct valuation")), \
                 patch.object(valuation, "atomic_write_csv") as csv_write, \
                 patch.object(valuation, "atomic_write_json") as json_write:
                self.assertEqual(valuation.main(), 0)
            self.assertEqual(csv_write.call_args.args[2][0]["valuation_reasonableness_score"], "")
            payloads = {call.args[0]: call.args[1] for call in json_write.call_args_list}
            scenario = payloads[valuation.SCENARIO_PATH]["records"][0]
            self.assertEqual(scenario["status"], "insufficient")
            self.assertNotIn("current_price", scenario)
            self.assertNotIn("scenario_prices", scenario)
            self.assertEqual(payloads[valuation.DEFAULT_BUNDLE_PATH]["records"], [])

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
