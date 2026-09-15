from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import phase5r_active_config as config
import phase5r_c9_common as account
from phase5r_portfolio_construction import individual_sizing_decision


class ResearchRiskLimitsTests(unittest.TestCase):
    def state(self):
        state = {key: 1 for key in account.ACCOUNT_FIELDS}
        state.update(
            account_total_value=2500, cash_available=1000, cash_reserved=500,
            core_allocation_target_pct=60, active_stock_target_pct=20,
            cash_target_pct=20, active_stock_hard_cap_pct=30,
            single_stock_default_cap_pct=6, single_stock_hard_cap_pct=8,
            cash_needed_within_three_years="no",
            last_updated="2026-09-11T14:00:00-04:00", cash_basis="ledger_estimate",
        )
        return state

    def limits(self):
        return dict(active_stock_hard_cap_pct=50,
                    single_stock_default_cap_pct=15, single_stock_hard_cap_pct=15)

    def test_absent_overlay_preserves_legacy_and_returns_independent_copy(self):
        original = self.state()
        with patch.object(account, "load_account_state", return_value=original), \
             patch.object(config, "load_active_config", return_value={"account": {}}):
            result = account.load_research_account_state()
        self.assertEqual(result, original)
        self.assertIsNot(result, original)

    def test_only_three_caps_change_and_raw_bytes_hash_remain_identical(self):
        original = self.state()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "account.json"
            path.write_text(json.dumps(original), encoding="utf-8")
            before = path.read_bytes()
            with patch.object(account, "ACCOUNT_STATE", path), \
                 patch.object(config, "load_active_config", return_value={
                     "account": {"research_risk_limits": self.limits()}}):
                result = account.load_research_account_state()
                raw = account.load_account_state()
            self.assertEqual(result, {**original, **self.limits()})
            self.assertEqual(raw, original)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),
                             hashlib.sha256(before).digest())

    def test_cash_timestamps_and_unconfirmed_basis_cannot_be_overlaid(self):
        for key, value in (("cash_available", 100000), ("last_updated", "today"),
                           ("cash_basis", "owner_recorded"), ("automatic_action_allowed", True)):
            with self.subTest(key=key), self.assertRaises(config.ActiveConfigError):
                config.validate_research_risk_limits({**self.limits(), key: value})

    def test_missing_nonfinite_bool_and_bad_ordering_are_rejected(self):
        cases = [None, {}, {**self.limits(), "single_stock_default_cap_pct": True},
                 {**self.limits(), "active_stock_hard_cap_pct": float("nan")},
                 {**self.limits(), "active_stock_hard_cap_pct": float("inf")},
                 {**self.limits(), "single_stock_default_cap_pct": 0},
                 {**self.limits(), "single_stock_default_cap_pct": 16},
                 {**self.limits(), "active_stock_hard_cap_pct": 10},
                 {**self.limits(), "active_stock_hard_cap_pct": 101}]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(config.ActiveConfigError):
                config.validate_research_risk_limits(value)

    def test_overlay_below_recorded_active_target_fails_closed(self):
        limits = dict(active_stock_hard_cap_pct=15,
                      single_stock_default_cap_pct=10, single_stock_hard_cap_pct=15)
        with patch.object(account, "load_account_state", return_value=self.state()), \
             patch.object(config, "load_active_config", return_value={
                 "account": {"research_risk_limits": limits}}), self.assertRaises(ValueError):
            account.load_research_account_state()

    def test_real_config_accepts_valid_optional_overlay_without_activation(self):
        original = config.load_active_config()
        before = config.ACTIVE_CONFIG_PATH.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            original["account"]["research_risk_limits"] = self.limits()
            path.write_text(json.dumps(original), encoding="utf-8")
            self.assertEqual(config.load_active_config(path)["account"]["research_risk_limits"], self.limits())
            original["boundaries"]["automatic_action_allowed"] = True
            path.write_text(json.dumps(original), encoding="utf-8")
            with self.assertRaises(config.ActiveConfigError):
                config.load_active_config(path)
        self.assertEqual(config.ACTIVE_CONFIG_PATH.read_bytes(), before)

    def test_selected_profile_removes_old_size_blocks_not_evidence_or_cash_checks(self):
        policy = config.load_active_config()["account"]
        limits = config.validate_research_risk_limits(policy["research_risk_limits"])
        self.assertEqual(limits, self.limits())
        state = {**self.state(), **limits}
        self.assertEqual(account.concentration_status(12.3, state), "within_default_cap")
        self.assertEqual(account.concentration_status(8.6, state), "within_default_cap")
        self.assertEqual(account.concentration_status(15.01, state), "above_hard_cap")
        args = dict(policy=policy, valuation_complete=True, score=7.8,
                    confidence="medium_high", expected_upside_pct=20,
                    reward_to_risk=2.1, entry_score=6.2, portfolio_fit_score=5,
                    current_price=145, account_total=2500, deployable_cash=500,
                    active_weight_pct=30.1, active_hard_cap_pct=50,
                    single_stock_default_cap_pct=15)
        self.assertEqual(individual_sizing_decision(**args)["suggested_whole_shares"], 1)
        for changes in ({"active_hard_cap_pct": 30}, {"deployable_cash": 100},
                        {"valuation_complete": False}, {"active_weight_pct": 50}):
            with self.subTest(changes=changes):
                self.assertEqual(individual_sizing_decision(**{**args, **changes})["suggested_whole_shares"], 0)


if __name__ == "__main__":
    unittest.main()
