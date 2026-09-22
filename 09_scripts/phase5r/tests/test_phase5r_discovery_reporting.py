from __future__ import annotations

import copy
import unittest

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_email_brief import build_discovery_view, build_email_view, render_email


def decision_fixture() -> dict:
    return {
        "cycle_date": "2026-09-22", "generated_at": "2026-09-22T17:00:00-04:00",
        "decision_code": "hold_no_new_position", "decision_fingerprint": "offline-report",
        "held_positions": [], "watch_candidates": [], "account_conflicts": [],
        "eligible_action_review_candidates": [], "eligible_new_position_review_candidates": [],
        "market_gate": {"passed": True, "expected_market_session": "2026-09-21"},
        "evidence_gate": {"passed": True}, "fundamental_gate": {"passed": True},
        "account": {"account_total_value": "5000", "cash_available": "2000", "cash_reserved": "500"},
        "automatic_action_allowed": False,
    }


def discovery_fixture() -> dict:
    def candidate(ticker: str, rank: int) -> dict:
        return {
            "ticker": ticker, "name": ticker + " public company", "rank": rank,
            "close": 132.48, "return_5d_pct": 2.34,
            "relative_strength_20d_pct": 4.56, "relative_volume": 1.25,
            "classification": "watchlist", "research_status": "unresearched_discovery",
            "in_legacy_universe": False,
        }

    return {
        "schema_version": "phase5r_market_discovery_v1", "status": "complete", "complete": True,
        "as_of_session": "2026-09-22", "expected_session": "2026-09-22",
        "coverage": {
            "metadata_count": 9000, "common_stock_count": 5000, "etf_count": 3000,
            "with_21_bars_count": 7500, "screen_eligible_count": 1200,
            "stock_screen_eligible_count": 950, "etf_screen_eligible_count": 250,
            "screen_eligible_outside_legacy_count": 1170,
            "excluded_counts": {"missing_21_session_history": 500, "liquidity_below_20m": 1000},
        },
        "top_stocks": [candidate(ticker, i) for i, ticker in enumerate(("C", "TJX", "GE", "EQT"), 1)],
        "top_etfs": [candidate(ticker, i) for i, ticker in enumerate(("XBI", "IJR", "XLF", "XLE"), 1)],
    }


class DiscoveryReportingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision = decision_fixture()
        self.decision["independent_market_discovery"] = discovery_fixture()

    def test_complete_coverage_and_top_three_each_are_dated_and_watch_only(self) -> None:
        view = build_email_view(self.decision)
        rows = view["discovery"]["candidates"]
        self.assertEqual([row["ticker"] for row in rows], ["C", "TJX", "GE", "XBI", "IJR", "XLF"])
        self.assertTrue(all(row["suggested_whole_shares"] == 0 for row in rows))
        self.assertEqual(view["plans"], [])
        for body in render_email(self.decision)[1:]:
            for detail in ("2026-09-22 收盘（非实时）", "证券目录 9,000", "通过初筛 1,200",
                           "原观察范围以外 1,170", "排除计数", "132.48", "2.34%", "4.56 个百分点",
                           "1.25 倍", "观察名单成员不加分", "新增 0 股，无新委托", "规则 1", "规则 4"):
                self.assertIn(detail, body)
            self.assertNotIn("EQT public company", body)
            self.assertNotIn("XLE public company", body)

    def test_discovery_cannot_create_eligible_order_even_with_injected_quantity(self) -> None:
        before = copy.deepcopy(self.decision)
        for row in self.decision["independent_market_discovery"]["top_stocks"]:
            row.update(suggested_whole_shares=999, maximum_review_price=8888, action="eligible_buy_review")
        view = build_email_view(self.decision)
        self.assertFalse(view["plans"])
        self.assertFalse(view["watchlist"])
        self.assertEqual(self.decision["eligible_new_position_review_candidates"], before["eligible_new_position_review_candidates"])
        self.assertEqual(self.decision["watch_candidates"], before["watch_candidates"])
        for body in render_email(self.decision)[1:]:
            self.assertNotIn("999", body)
            self.assertNotIn("8,888", body)
            self.assertIn("新增 0 股，无新委托", body)

    def test_stale_discovery_does_not_display_old_shortlist_or_seed_fallback(self) -> None:
        review = self.decision["independent_market_discovery"]
        review.update(status="stale", complete=False, as_of_session="2026-09-18")
        for body in render_email(self.decision)[1:]:
            self.assertIn("初筛已过期", body)
            self.assertIn("上次数据 2026-09-18，本次需要 2026-09-22", body)
            self.assertIn("不会被当作全市场筛选结果", body)
            self.assertNotIn("C public company", body)
        self.assertFalse(build_discovery_view(self.decision)["candidates"])

    def test_unavailable_and_missing_discovery_are_explicit(self) -> None:
        variants = (None, {"schema_version": "phase5r_market_discovery_v1", "status": "unavailable"},
                    {**discovery_fixture(), "status": "unavailable", "complete": False})
        for review in variants:
            with self.subTest(review=review):
                self.decision["independent_market_discovery"] = review
                for body in render_email(self.decision)[1:]:
                    self.assertIn("独立市场初筛暂不可用", body)
                    self.assertNotIn("C public company", body)
                    self.assertIn("本节新增 0 股、无新委托", body)

    def test_mismatched_session_fails_closed_despite_complete_claim(self) -> None:
        self.decision["independent_market_discovery"]["as_of_session"] = "2026-09-21"
        view = build_discovery_view(self.decision)
        self.assertEqual(view["status"], "stale")
        self.assertFalse(view["candidates"])

    def test_incomplete_fetch_explains_why_discovery_is_unavailable(self) -> None:
        self.decision["independent_market_discovery"].update(
            status="unavailable", complete=False, failure_code="metadata_incomplete", as_of_session="")
        for body in render_email(self.decision)[1:]:
            self.assertIn("证券目录抓取不完整", body)
            self.assertNotIn("C public company", body)

    def test_malformed_or_incomplete_shortlist_does_not_become_positive_research(self) -> None:
        for patch in ({"classification": "real-trade candidate"}, {"close": "nan"},
                      {"return_5d_pct": None}, {"ticker": "<script>"}):
            with self.subTest(patch=patch):
                self.decision["independent_market_discovery"] = discovery_fixture()
                self.decision["independent_market_discovery"]["top_stocks"][0].update(patch)
                view = build_discovery_view(self.decision)
                self.assertEqual(view["status"], "unavailable")
                self.assertFalse(view["candidates"])

    def test_company_names_are_escaped_and_rendering_does_not_mutate_evidence(self) -> None:
        self.decision["independent_market_discovery"]["top_stocks"][0]["name"] = "<script>unsafe</script>"
        before = copy.deepcopy(self.decision)
        body = render_email(self.decision)[2]
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertEqual(self.decision, before)

    def test_compact_owner_message_remains_the_owner_supplied_narrative(self) -> None:
        self.decision["owner_requested_research"] = {
            "mode": "explicit_one_off_research", "presentation": "compact", "request_id": "offline-test",
            "decision_fingerprint": self.decision["decision_fingerprint"],
            "reviewed_at": "2026-09-22T17:00:00-04:00", "market_as_of": "2026-09-22",
            "sections": [{"title": "My review", "body": "A separate research conclusion.", "sources": []}],
        }
        actual = render_email(self.decision)
        self.decision.pop("independent_market_discovery")
        self.assertEqual(actual, render_email(self.decision))
        self.assertNotIn("独立市场初筛", actual[1] + actual[2])


if __name__ == "__main__":
    unittest.main()
