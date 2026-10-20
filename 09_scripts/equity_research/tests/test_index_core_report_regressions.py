"""Final stock budgets and rendered diagnostics use the admitted core inputs."""
from __future__ import annotations

import copy
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
from active_config import load_active_config
import capital_decision as engine
import regenerate_portfolio_outputs as portfolio
import test_concentrated_allocation as allocation_tests


class IndexCoreReportRegressionTests(unittest.TestCase):
    def test_stale_cheaper_fund_cannot_release_more_stock_capacity(self):
        base = allocation_tests.ConcentratedAllocationTests()
        base.setUp()
        base.d["held_positions"] = []
        base.d["account"].update(account_total_value=4000, cash_available=4000, cash_reserved=0)
        base.base.config["account"]["core_allocation_tickers"] = ["SPY", "QQQM"]
        base.plan["reviewed_allocation"]["target_position_pct"] = 70
        expected = base.d["market_gate"]["expected_market_session"]
        quotes = [dict(ticker=t, last_price=p, data_quality_label="ok", market_session_date=expected,
                       data_source="fixture", data_timestamp=base.now.isoformat())
                  for t, p in (("SPY", 775), ("QQQM", 100))]
        # An optimistic watch row cannot substitute for stale canonical data.
        base.d["watch_candidates"].append(dict(ticker="QQQM", current_price=100))
        for fund_session, shares in (("2026-09-21", 24), (expected, 28)):
            quotes[1]["market_session_date"] = fund_session
            with self.subTest(fund_session=fund_session), patch.object(engine, "read_csv", return_value=quotes):
                self.assertEqual(base.result()["shares"], shares)

    def test_core_headline_follows_selected_fund_instead_of_score_rank(self):
        config = load_active_config()
        account = {**config["account"], "active_stock_hard_cap_pct": 70}
        summary = dict(account_total_value=4000, cash_available=4000, deployable_cash=4000,
                       current_core_value=0, current_active_stock_value=0, current_active_stock_weight_pct=0,
                       current_cash_pct=100, current_holdings_value=0, reconciliation_difference=0,
                       reconciliation_status="reconciled", active_stock_status="within_target")
        with tempfile.TemporaryDirectory() as directory:
            valuation = Path(directory) / "valuation.json"
            valuation.write_text('{"records": []}')
            for selected in ("SPY", "QQQM"):
                other = "QQQM" if selected == "SPY" else "SPY"
                packets = {t: dict(ticker=t, research_role="core_allocation_candidate", theme="Index",
                              holding_horizon_candidate="broad_core", exit_or_trim_conditions="Review allocation",
                              recommendation_confidence="medium_high", business_quality_score="5",
                              earnings_revenue_trend_score="5", valuation_reasonableness_score="5",
                              catalyst_news_quality_score="5", technical_entry_discipline_score="6" if t == selected else "9")
                           for t in ("SPY", "QQQM")}
                plans = [dict(plan_id="retain_cash_fallback", asset_role="cash", ticker_or_category="CASH",
                              planned_review_date="2026-10-20")]
                plans += [dict(plan_id=f"core_starter_whole_share_review:{t}", asset_role="core_allocation",
                               ticker_or_category=t, status="selected_review" if t == selected else "alternative_not_selected",
                               planned_shares="1" if t == selected else "0", planned_amount="100" if t == selected else "0",
                               core_weight_after="2.5" if t == selected else "0", sizing_tier="starter_allocation",
                               cash_rationale="Shared capacity", reason="Failed gates: none.") for t in ("SPY", "QQQM")]
                def rows(path):
                    if path == portfolio.PORTFOLIO_SUMMARY:
                        return [summary]
                    if path == portfolio.CASH_DEPLOYMENT_PLAN:
                        return plans
                    if path == portfolio.MARKET_SNAPSHOT:
                        return [dict(ticker=t, last_price=100, market_session_date="2026-10-16",
                                     data_quality_label="ok", data_source="fixture", data_timestamp="2026-10-16T20:00:00Z") for t in packets]
                    if path == portfolio.POST_ACTION_PORTFOLIO:
                        return [dict(scenario="after_position_and_core_reviews", resulting_cash=3900, cash_weight_pct=97.5, resulting_active_value=0, active_weight_pct=0, resulting_core_value=100, core_weight_pct=2.5, retained_cash_reason="Shared capacity")]
                    return []
                rendered, written = {}, {}
                with (self.subTest(selected=selected), patch.object(portfolio, "VALUATION_SCENARIO_PATH", valuation),
                      patch.object(portfolio, "run_children"),
                      patch.object(portfolio, "load_active_inhibit", return_value={"active": False}),
                      patch.object(portfolio, "load_research_account_state", return_value=account),
                      patch.object(portfolio, "load_active_config", return_value=config),
                      patch.object(portfolio, "approved_core_tickers", return_value=("SPY", "QQQM")),
                      patch.object(portfolio, "is_core_allocation_ticker", side_effect=lambda t: t in {"SPY", "QQQM"}),
                      patch.object(portfolio, "load_packets", return_value=copy.deepcopy(packets)),
                      patch.object(portfolio, "requested_coverage_tickers", return_value=set()),
                      patch.object(portfolio, "read_csv", side_effect=rows),
                      patch.object(portfolio, "latest_published_market_session", return_value=date(2026, 10, 16)),
                      patch("reviewed_allocation.current_allocations", return_value={}),
                      patch.object(portfolio, "write_csv", side_effect=lambda p, r, f: written.update({p: r})),
                      patch.object(portfolio, "write_text", side_effect=lambda p, t: rendered.update({p: t})),
                      patch.object(portfolio, "append_run_log")):
                    portfolio.main()
                self.assertEqual(written[portfolio.C9_NEW_RECOMMENDATIONS][0]["ticker"], other)
                self.assertIn(f"whole-share example `1` {selected}", rendered[portfolio.C9_MEMO])
                self.assertIn("proposed whole shares `1`", rendered[portfolio.WEEKLY_DECISION_SUMMARY])


if __name__ == "__main__":
    unittest.main()
