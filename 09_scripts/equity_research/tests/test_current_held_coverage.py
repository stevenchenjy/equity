"""Account intake remains visible when downstream portfolio refresh fails."""
from contextlib import ExitStack
from datetime import date, datetime
import csv
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR, visible_html_text
import capital_decision
import create_daily_decision_and_brief as composer
from active_config import load_active_config
from daily_common import ROOT
from email_brief import render_email
from test_tactical_review import fixture


class CurrentHeldCoverageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.current = datetime.fromisoformat("2026-09-22T18:00:00-04:00")
        self.positions = self.root / "05_risk_and_positions/current_positions.local.csv"
        self.exact = self.root / "exact.csv"
        self.market = self.root / "03_source_data/equity_research/market_data_snapshot.csv"
        self.quality = self.root / "quality.csv"
        self.recommendations = self.root / "recommendations.csv"
        self.account = self.root / "05_risk_and_positions/current_account_state.local.json"
        self.summary = self.root / "summary.csv"
        self.account.parent.mkdir(parents=True, exist_ok=True)
        self.account.write_text('{"cash_available":137.19,"cash_reserved":0}')
        self.write(self.summary, [{"cash_available": "137.19", "cash_reserved": "0"}])
        self.write(self.recommendations, [], ["ticker"])
        self.write(self.quality, [{"ticker": t, "usable_for_scoring": "yes"}
                                 for t in ("SPY", "DEF", "GHI")])
        self.write(self.market, [{"ticker": t, "last_price": p,
            "market_session_date": "2026-09-22", "data_quality_label": "ok",
            "data_source": "massive_stocks_basic_eod", "data_timestamp": self.current.isoformat()}
            for t, p in (("SPY", "700"), ("DEF", "200"), ("GHI", "300"))])
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key, value in {"ROOT": self.root, "EXACT_ACTION_PATH": self.exact,
            "POSITION_RECOMMENDATION_PATH": self.recommendations, "MARKET_SNAPSHOT_PATH": self.market,
            "MARKET_QUALITY_PATH": self.quality, "ACCOUNT_STATE_PATH": self.account,
            "PORTFOLIO_SUMMARY_PATH": self.summary}.items():
            stack.enter_context(patch.object(composer, key, value))
        stack.enter_context(patch.object(composer, "now_et", return_value=self.current))
        stack.enter_context(patch.object(composer, "latest_published_market_session", return_value=date(2026, 9, 22)))

    def write(self, path, rows, fields=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def inventory(self, values):
        fields = sorted(composer.POSITION_REQUIRED_FIELDS)
        rows = []
        for ticker, quantity in values:
            row = dict.fromkeys(fields, "synthetic fixture")
            row.update(ticker=ticker, shares_optional=str(quantity), horizon_class="long_term_research")
            rows.append(row)
        self.write(self.positions, rows, fields)

    def derived(self, values):
        self.write(self.exact, [{"ticker": t, "current_shares": str(q), "recommended_action": "sell_review",
            "current_price": "999", "current_weight_pct": "88", "target_shares": "0",
            "whole_shares_to_change": str(q), "reason": "stale sell instruction"} for t, q in values])

    def test_new_inventory_drives_gates_capital_and_both_rendered_bodies(self):
        # Deliberately synthetic quantities and cash; no private account facts.
        actual = [("SPY", 3), ("ABC", 6), ("DEF", 5), ("GHI", 2), ("JKL", 7)]
        self.inventory(actual)
        self.derived([("SPY", 3), ("DEF", 5)])
        rows = composer.normalized_held_rows()
        self.assertEqual([(r["ticker"], int(r["current_shares"])) for r in rows], actual)
        self.assertTrue(all(r["whole_shares_to_change"] == "0" for r in rows))
        self.assertTrue(all(r["current_weight_pct"] == "" for r in rows))
        self.assertTrue(all("stale sell" not in r["reason"] for r in rows))
        self.assertEqual({r["ticker"] for r in rows if not r["current_price"]}, {"ABC", "JKL"})
        self.assertEqual(next(r["current_price"] for r in rows if r["ticker"] == "SPY"), "700")
        gate = composer.load_market_gate(self.current, [r["ticker"] for r in rows])
        self.assertFalse(gate["passed"])
        self.assertIn("ABC:market_row_missing", gate["failures"])
        self.assertIn("JKL:market_row_missing", gate["failures"])

        values = fixture()
        decision = values["decision"]
        decision.update(generated_at=self.current.isoformat(), cycle_date="2026-09-22",
            decision_code="data_gate_hold", held_positions=rows, market_gate=gate,
            holdings_coverage={"status": "portfolio_recomposition_required"},
            watch_candidates=[], eligible_new_position_review_candidates=[], eligible_action_review_candidates=[],
            plan_continuity={"status": "invalid", "conflicts": ["plan_source_hash_mismatch"], "plans": []},
            workflow_integrity={"global_blockers": ["plan_ledger_integrity_invalid"], "ticker_blockers": {}})
        decision["account"].update(account_total_value=None, cash_available=137.19, cash_reserved=0,
            cash_basis="owner_recorded", last_updated=self.current.isoformat())
        contract = capital_decision.build(decision, root=ROOT, current=self.current,
            config=load_active_config(), orders=values["open_orders"])
        self.assertEqual(contract["planning_cash"], 137.19)
        self.assertIn("held_position_prices_unverified", contract["global_blockers"])
        self.assertIn("shared_account_values_unverified", contract["global_blockers"])
        self.assertEqual({r["ticker"] for r in contract["decisions"]}, dict(actual).keys())
        self.assertTrue(all(r["shares"] == 0 and r["order_draft"] is None for r in contract["decisions"]))
        self.assertEqual(decision["plan_continuity"]["conflicts"], ["plan_source_hash_mismatch"])
        decision["capital_decision"] = contract
        _, plain, html = render_email(decision)
        for body in (plain, visible_html_text(html)):
            for ticker, _ in actual:
                self.assertIn(ticker, body)
            for ticker, quantity in actual:
                self.assertIn(f"{ticker}: {quantity} recorded shares", body)
            self.assertIn("ABC: 6 recorded shares; retained canonical mark unavailable", body)
            self.assertIn("JKL: 7 recorded shares; retained canonical mark unavailable", body)
            self.assertNotIn("stale sell instruction", body)
            self.assertNotIn("$999", body)

    def test_removed_position_and_changed_quantity_do_not_reuse_stale_action(self):
        self.inventory([("SPY", 1)])
        self.derived([("SPY", 2), ("DEF", 2)])
        rows = composer.normalized_held_rows()
        self.assertEqual([(r["ticker"], r["current_shares"]) for r in rows], [("SPY", "1")])
        self.assertEqual(rows[0]["whole_shares_to_change"], "0")
        self.assertEqual(rows[0]["action"], "hold_pending_research")

    def test_matching_inventory_preserves_current_derived_risk_review(self):
        self.inventory([("SPY", 2), ("DEF", 2)])
        self.derived([("SPY", 2), ("DEF", 2)])
        rows = composer.normalized_held_rows()
        self.assertEqual([r["action"] for r in rows], ["sell_review", "sell_review"])
        self.assertTrue(all(r["derived_position_status"] == "current" for r in rows))

    def test_cash_or_reserve_only_change_with_same_shares_discards_derived_actions(self):
        self.inventory([("SPY", 3), ("ABC", 5)])
        self.derived([("SPY", 3), ("ABC", 5)])
        for observed in ('{"cash_available":291.43,"cash_reserved":0}',
                         '{"cash_available":137.19,"cash_reserved":11}'):
            with self.subTest(observed=observed):
                self.account.write_text(observed)
                rows = composer.normalized_held_rows()
                self.assertTrue(all(r["whole_shares_to_change"] == "0" for r in rows))
                self.assertTrue(all(r["current_weight_pct"] == "" for r in rows))
                self.assertTrue(all(r["derived_position_status"] == "portfolio_outputs_mismatch" for r in rows))
                self.assertTrue(all("stale sell" not in r["reason"] for r in rows))

    def test_duplicate_current_inventory_is_not_hidden_by_fallback(self):
        self.inventory([("SPY", 2), ("SPY", 1)])
        self.derived([("SPY", 2)])
        with self.assertRaisesRegex(ValueError, "current_position_inventory_invalid"):
            composer.normalized_held_rows()

    def test_explicit_empty_inventory_does_not_resurrect_derived_holdings(self):
        self.inventory([])
        self.derived([("SPY", 3), ("DEF", 5)])
        self.assertEqual(composer.normalized_held_rows(), [])

    def test_missing_or_malformed_inventory_is_not_confirmed_all_cash(self):
        self.derived([("SPY", 3)])
        with self.assertRaisesRegex(ValueError, "current_position_inventory_missing_or_invalid"):
            composer.normalized_held_rows()

    def test_markdown_unknown_values_and_old_cash_scenario_remain_unavailable(self):
        stale = [{"scenario": "after_position_and_core_reviews", "resulting_cash": "8900",
                  "cash_weight_pct": "89", "retained_cash_reason": "obsolete cash scenario"}]
        withheld = composer.current_post_action(stale, held_outputs_current=False)
        self.assertNotIn("resulting_cash", withheld)
        self.assertNotIn("cash_weight_pct", withheld)
        for value in (None, "", "NaN"):
            self.assertEqual(composer.report_number(value, prefix="$"), "unavailable")
            self.assertEqual(composer.report_number(value, suffix="%"), "unavailable")
        self.assertEqual(composer.report_number("137.19", prefix="$"), "$137.19")
        self.assertEqual(composer.current_post_action(stale, held_outputs_current=True), stale[0])
        self.inventory([("ABC", 3)])
        self.derived([("SPY", 7)])
        rendered = composer.held_position_summary(composer.normalized_held_rows()[0])
        self.assertIn("现价 unavailable", rendered)
        self.assertIn("约占 unavailable", rendered)
        self.assertNotIn("$None", rendered)
        self.assertNotIn("100.0000%", rendered)
        self.write(self.positions, [], ["ticker"])
        with self.assertRaisesRegex(ValueError, "current_position_inventory_missing_or_invalid"):
            composer.normalized_held_rows()


if __name__ == "__main__":
    unittest.main()
