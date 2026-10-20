"""Two approved funds share one starter budget and retain local evidence failures."""
from __future__ import annotations

import copy
from datetime import date
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import create_cash_deployment_plan as cash_plan
from active_config import load_active_config


class IndexCoreCashPlanTests(unittest.TestCase):
    def output(self, *, core=775, cash=None, fail=(), stale=(), maintenance=False):
        cash = 4000 - core if cash is None else cash
        config = copy.deepcopy(load_active_config())
        config["account"]["core_allocation_tickers"] = ["SPY", "QQQM"]
        account = dict(core_allocation_target_pct=30, core_minimum_pct=30,
                       active_stock_target_pct=70, cash_target_pct=0)
        summary = dict(account_total_value=4000, cash_available=cash, cash_reserved=0,
                       deployable_cash=cash, current_active_stock_value=4000-core-cash,
                       current_active_stock_weight_pct=(4000-core-cash)/40,
                       current_core_value=core, active_stock_status="within_target", cash_status="above_target")
        quotes = {t: dict(last_price=price, fifty_two_week_high=high, fifty_two_week_low=low,
                          market_session_date="2026-10-15" if t in stale else "2026-10-16",
                          data_quality_label="ok", data_source="fixture", data_timestamp="2026-10-16T20:00:00Z")
                  for t, price, low, high in (("SPY", 775, 500, 1000), ("QQQM", 290, 200, 400))}
        def market(required):
            ticker = required[0]
            if ticker in fail:
                raise ValueError(f"canonical B2 market snapshot is missing {ticker}")
            return quotes
        written = {}
        with (patch.object(cash_plan, "load_active_config", return_value=config),
              patch.object(cash_plan, "approved_core_tickers", return_value=("SPY", "QQQM")),
              patch.object(cash_plan, "is_core_allocation_ticker", side_effect=lambda t: t in {"SPY", "QQQM"}),
              patch.object(cash_plan, "latest_published_market_session", return_value=date(2026, 10, 16)),
              patch.object(cash_plan, "load_active_inhibit", return_value={"active": maintenance}),
              patch.object(cash_plan, "load_research_account_state", return_value=account),
              patch.object(cash_plan, "load_portfolio_summary", return_value=summary),
              patch.object(cash_plan, "load_market_rows", side_effect=market),
              patch.object(cash_plan, "load_packets", return_value={t: {"technical_entry_discipline_score": 7} for t in quotes}),
              patch.object(cash_plan, "read_csv", return_value=[]),
              patch.object(cash_plan, "write_csv", side_effect=lambda path, rows, fields: written.update({path: rows})),
              patch.object(cash_plan, "append_run_log")):
            cash_plan.main()
        by = {r["ticker_or_category"]: r for r in written[cash_plan.CASH_DEPLOYMENT_PLAN]}
        post = next(r for r in written[cash_plan.POST_ACTION_PORTFOLIO]
                    if r["scenario"] == "after_position_and_core_reviews")
        return by, post

    def test_both_qualifying_funds_cannot_duplicate_the_shared_tranche(self):
        rows, post = self.output()
        self.assertEqual(rows["SPY"]["status"], "selected_review")
        self.assertEqual(rows["SPY"]["planned_shares"], "1")
        self.assertEqual(rows["QQQM"]["status"], "alternative_not_selected")
        self.assertEqual(rows["QQQM"]["planned_shares"], "0")
        self.assertEqual(rows["QQQM"]["planned_amount"], "0.00")
        self.assertEqual(len({r["plan_id"] for r in rows.values()}), 3)
        self.assertEqual(sum(int(r["planned_shares"]) for r in rows.values()), 1)
        self.assertEqual(post["proposed_core_ticker"], "SPY")
        self.assertEqual(post["resulting_core_value"], "1550.00")

    def test_missing_spy_quote_preserves_issue_and_allows_qqqm_review(self):
        rows, post = self.output(fail=("SPY",))
        self.assertEqual(rows["SPY"]["status"], "not_selected")
        self.assertIn("missing SPY", rows["SPY"]["reason"])
        self.assertIn("core_market_or_entry_evidence_unverified", rows["SPY"]["reason"])
        self.assertEqual(rows["QQQM"]["status"], "selected_review")
        self.assertEqual(post["proposed_core_ticker"], "QQQM")
        self.assertEqual(post["proposed_core_value"], "290.00")

    def test_unavailable_qqqm_does_not_disable_valid_spy(self):
        rows, _ = self.output(fail=("QQQM",))
        self.assertEqual(rows["SPY"]["status"], "selected_review")
        self.assertEqual(rows["QQQM"]["planned_shares"], "0")
        self.assertIn("missing QQQM", rows["QQQM"]["reason"])

    def test_stale_quotes_cannot_supply_a_core_entry(self):
        rows, post = self.output(stale=("SPY", "QQQM"))
        self.assertEqual(sum(int(r["planned_shares"]) for r in rows.values()), 0)
        self.assertEqual(post["proposed_core_ticker"], "")
        self.assertIn("completed close for 2026-10-16", rows["QQQM"]["reason"])

    def test_satisfied_combined_core_does_not_add_or_rotate(self):
        rows, post = self.output(core=1347)
        for ticker in ("SPY", "QQQM"):
            self.assertEqual(rows[ticker]["status"], "minimum_satisfied")
            self.assertEqual(rows[ticker]["planned_shares"], "0")
            self.assertIn("not a trim instruction", rows[ticker]["reason"])
        self.assertEqual(post["proposed_core_ticker"], "")
        self.assertEqual(post["resulting_core_value"], "1347.00")

    def test_maintenance_cannot_use_either_fund(self):
        rows, post = self.output(maintenance=True)
        self.assertEqual(sum(int(r["planned_shares"]) for r in rows.values()), 0)
        self.assertTrue(all(rows[t]["status"] == "blocked_maintenance" for t in ("SPY", "QQQM")))
        self.assertEqual(post["proposed_core_value"], "0.00")

    def test_cheaper_fund_can_fill_gap_when_spy_is_unaffordable(self):
        rows, post = self.output(core=1000, cash=350)
        self.assertEqual(rows["SPY"]["planned_shares"], "0")
        self.assertEqual(rows["QQQM"]["planned_shares"], "1")
        self.assertEqual(post["resulting_cash"], "60.00")
        self.assertEqual(post["resulting_core_value"], "1290.00")


if __name__ == "__main__":
    unittest.main()
