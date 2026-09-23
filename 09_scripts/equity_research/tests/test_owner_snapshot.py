from __future__ import annotations

import json
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import account_common as account
import update_manual_account as updater
from email_brief import build_email_view, render_email
from test_email_brief import action_fixture, decision_fixture


class OwnerSnapshotTests(unittest.TestCase):
    def test_snapshot_is_bound_to_positions_account_and_confirmed_ledger(self):
        receipt = {"schema_version": "phase5r_owner_snapshot_v1", "owner_snapshot": True,
                   "source_note": "Owner screenshot and inclusive costs",
                   "positions_sha256_after": "a" * 64, "account_sha256_after": "b" * 64,
                   "confirmed_execution_sha256": "c" * 64}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.json"
            path.write_text(json.dumps(receipt))
            with patch.object(updater, "MANUAL_SNAPSHOT_PATH", path), patch.object(updater, "sha256_file", return_value="c" * 64):
                self.assertTrue(updater.current_manual_snapshot_matches("a" * 64, "b" * 64))
                self.assertFalse(updater.current_manual_snapshot_matches("d" * 64, "b" * 64))
                self.assertFalse(updater.current_manual_snapshot_matches("a" * 64, "d" * 64))
                with patch.object(updater, "sha256_file", return_value="new-confirmed-ledger"):
                    self.assertFalse(updater.current_manual_snapshot_matches("a" * 64, "b" * 64))

    def test_symlink_snapshot_is_not_a_reconciliation_waiver(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "receipt.json"
            path.symlink_to(Path(folder) / "untrusted.json")
            with patch.object(updater, "MANUAL_SNAPSHOT_PATH", path):
                self.assertFalse(updater.current_manual_snapshot_matches("a" * 64, "b" * 64))

    def test_optional_planning_range_preserves_cash_and_validates_strictly(self):
        state = {key: 1 for key in account.ACCOUNT_FIELDS}
        state.update(account_total_value=2400, cash_available=1400, cash_reserved=500,
                     core_allocation_target_pct=60, active_stock_target_pct=20, cash_target_pct=20,
                     active_stock_hard_cap_pct=30, single_stock_default_cap_pct=6,
                     single_stock_hard_cap_pct=8, cash_needed_within_three_years="no",
                     last_updated="2026-09-11T14:00:00-04:00")
        state.update(cash_basis="ledger_estimate", planning_capital_min=3000, planning_capital_max=4500)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "account.json"
            with patch.object(account, "ACCOUNT_STATE", path):
                path.write_text(json.dumps(state))
                self.assertEqual(account.load_account_state()["cash_available"], state["cash_available"])
                for changes in ({"planning_capital_max": 2000}, {"cash_basis": "unlimited"}, {"unrecognized": True}):
                    path.write_text(json.dumps(dict(state, **changes)))
                    with self.assertRaises(ValueError):
                        account.load_account_state()

    def test_nonfinite_position_input_is_rejected(self):
        for text in ("NVDA=nan@220", "NVDA=1@inf"):
            with self.assertRaises(argparse.ArgumentTypeError):
                updater.parse_position(text)

    def test_snapshot_update_archives_history_without_fabricating_fill_fees(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            positions, state, quotes, confirmed, receipt = [root / name for name in ("positions.csv", "account.json", "market.csv", "confirmed.csv", "snapshot.json")]
            prior = {key: "" for key in ("ticker", "entry_date", "entry_price", "position_pct", "shares_optional", "thesis", "horizon_class", "planned_review_date", "max_loss_pct_of_account", "invalidation_rule", "current_action", "notes")}
            prior.update(ticker="RBRK", shares_optional="1", entry_price="84.40", notes="Historical record")
            updater.atomic_write_csv(positions, list(prior), [prior])
            updater.atomic_write_json(state, {"cash_reserved": 500, "cash_available": 1409.53})
            updater.atomic_write_csv(quotes, ["ticker", "last_price", "data_quality_label"], [
                {"ticker": "RBRK", "last_price": "88.91", "data_quality_label": "ok"},
                {"ticker": "NVDA", "last_price": "218.36", "data_quality_label": "ok"},
            ])
            confirmed.write_text("execution_id\nhistorical\n")
            before_confirmed = confirmed.read_bytes()
            args = ["update", "--cash", "1013.53", "--cash-basis", "ledger_estimate", "--position", "RBRK=3@87.96333333", "--position", "NVDA=1@220", "--new-position-date", "2026-09-10", "--planning-capital-min", "3000", "--planning-capital-max", "4500", "--source-note", "Screenshot; total inclusive outlays 176 and 220; separate fees unknown", "--apply"]
            with patch.object(updater, "POSITIONS_PATH", positions), patch.object(updater, "ACCOUNT_STATE_PATH", state), patch.object(updater, "MARKET_SNAPSHOT_PATH", quotes), patch.object(updater, "CONFIRMED_PATH", confirmed), patch.object(updater, "MANUAL_SNAPSHOT_PATH", receipt), patch.object(sys, "argv", args):
                self.assertEqual(updater.main(), 0)
                self.assertTrue(updater.current_manual_snapshot_matches(updater.sha256_file(positions), updater.sha256_file(state)))
            result = updater.read_csv(positions)
            self.assertEqual(result[1]["entry_date"], "2026-09-10")
            self.assertEqual(result[0]["entry_price"], "87.96333333")
            snapshot = updater.read_json(receipt)
            self.assertEqual(snapshot["positions_before"][0]["entry_price"], "84.40")
            self.assertEqual(updater.read_json(state)["cash_available"], 1013.53)
            self.assertEqual(confirmed.read_bytes(), before_confirmed)


class PlanningEmailTests(unittest.TestCase):
    def test_estimated_cash_does_not_block_research_or_present_trade_quantities(self):
        decision = action_fixture()
        decision["account"].update(cash_basis="ledger_estimate", planning_capital_min=3000, planning_capital_max=4500)
        view = build_email_view(decision)
        self.assertFalse(view["plans"])
        self.assertEqual(view["label"], "资金区间研究")
        text = render_email(decision)[1]
        self.assertIn("本次无需补交精确现金", text)
        self.assertIn("账本现金估算", text)
        self.assertIn("银行备用资金未计入账户", text)
        self.assertIn("不是已到账现金", text)
        self.assertNotIn("减少 1 股", text)

    def test_range_weights_use_position_value_and_never_change_production_denominator(self):
        decision = decision_fixture()
        decision["held_positions"][0].update(current_shares="3", current_price="88.91")
        decision["account"].update(planning_capital_min=3000, planning_capital_max=4500)
        before = json.dumps(decision, sort_keys=True)
        text = render_email(decision)[1]
        self.assertIn("按 $3,000.00 分母约 8.89%", text)
        self.assertIn("按 $4,500.00 分母约 5.93%", text)
        self.assertEqual(before, json.dumps(decision, sort_keys=True))

    def test_account_conflict_still_takes_precedence_over_range(self):
        decision = action_fixture()
        decision["account"]["cash_basis"] = "ledger_estimate"
        decision["account_conflicts"] = ["pending_execution:test"]
        self.assertEqual(build_email_view(decision)["label"], "需核对账户")

    def test_explicit_one_off_research_is_separate_and_snapshot_bound(self):
        decision = decision_fixture()
        decision["owner_requested_research"] = {
            "mode": "explicit_one_off_research", "decision_fingerprint": decision["decision_fingerprint"],
            "sections": [{"title": "NVDA", "body": "研究解读 <script>no execution</script>",
                          "sources": ["https://nvidianews.nvidia.com/news/results"]}],
        }
        text, html = render_email(decision)[1:]
        self.assertIn("不参与自动通知或 SHADOW 评估", text)
        self.assertNotIn("<script>", html)
        self.assertIn("官方财报来源", html)
        decision["owner_requested_research"]["decision_fingerprint"] = "stale"
        with self.assertRaisesRegex(ValueError, "snapshot_mismatch"):
            render_email(decision)

    def test_bad_research_links_and_unrequested_modes_are_rejected(self):
        decision = decision_fixture()
        review = {"mode": "explicit_one_off_research", "decision_fingerprint": decision["decision_fingerprint"],
                  "sections": [{"title": "RBRK", "body": "No forecast", "sources": ["https://evil.example"]}]}
        decision["owner_requested_research"] = review
        with self.assertRaisesRegex(ValueError, "source_not_allowed"):
            render_email(decision)
        review["mode"] = "shadow_automatic"
        with self.assertRaisesRegex(ValueError, "snapshot_mismatch"):
            render_email(decision)


if __name__ == "__main__":
    unittest.main()
