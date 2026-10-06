from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401
import account_common as account
import active_config as config
from calculate_dynamic_weights import held_recommendation_label
from create_research_questions import whole_share_diagnostics
from packet_contract import ContractError, validate_portfolio_constraints
from return_objective import return_objective_payload
import migrate_allocation_policy as migration
import create_cash_deployment_plan as cash_plan
from daily_common import sha256_file


def policy() -> dict:
    return {
        "core_target_pct": 30, "core_minimum_pct": 30,
        "active_target_pct": 70, "cash_target_pct": 0,
        "research_risk_limits": {
            "active_stock_hard_cap_pct": 70,
            "single_stock_default_cap_pct": None,
            "single_stock_hard_cap_pct": None,
        },
    }


def recorded_account() -> dict:
    return {
        "account_total_value": 4000, "prior_account_value": 1000,
        "new_external_cash": 1500, "cash_available": 2468.82,
        "cash_reserved": 0, "investment_horizon_years": 1,
        "cash_needed_within_three_years": "no", "cash_basis": "ledger_estimate",
        "planning_capital_min": 4000, "planning_capital_max": 4000,
        "core_allocation_target_pct": 40, "active_stock_target_pct": 50,
        "active_stock_hard_cap_pct": 50, "cash_target_pct": 10,
        "single_stock_default_cap_pct": 15, "single_stock_hard_cap_pct": 15,
        "last_updated": "2026-10-01T20:30:05-04:00",
    }


class AllocationMigrationTests(unittest.TestCase):
    def test_active_targets_replace_legacy_research_input_without_mutating_financial_truth(self):
        original = recorded_account()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "account.json"
            path.write_text(json.dumps(original))
            before = path.read_bytes()
            with patch.object(account, "ACCOUNT_STATE", path), patch.object(
                config, "load_active_config", return_value={"account": policy()}
            ):
                result = account.load_research_account_state()
                self.assertEqual(account.load_account_state(), original)
            self.assertEqual(path.read_bytes(), before)
        for name in ("cash_available", "cash_reserved", "cash_basis", "last_updated",
                     "account_total_value", "new_external_cash", "prior_account_value",
                     "planning_capital_min", "planning_capital_max"):
            self.assertEqual(result[name], original[name], name)
        self.assertEqual([result[k] for k in ("core_allocation_target_pct", "active_stock_target_pct", "cash_target_pct")], [30, 70, 0])
        self.assertEqual(result["core_minimum_pct"], 30)
        self.assertIsNone(result["single_stock_hard_cap_pct"])
        self.assertIsNone(result["single_stock_default_cap_pct"])

    def test_raw_policy_migration_accepts_nulls_without_refreshing_observation_time(self):
        migrated = {**recorded_account(), "core_allocation_target_pct": 30,
                    "active_stock_target_pct": 70, "cash_target_pct": 0,
                    "core_minimum_pct": 30, **policy()["research_risk_limits"]}
        self.assertEqual(account.validate_account_state(migrated), migrated)
        self.assertEqual(migrated["last_updated"], recorded_account()["last_updated"])
        for value in (float("inf"), float("nan"), 0, True, 100):
            bad = {**migrated, "single_stock_default_cap_pct": value}
            with self.subTest(value=value), self.assertRaises(ValueError):
                account.validate_account_state(bad)

    def test_partial_or_inconsistent_target_overlay_fails_closed(self):
        for change in ({"core_target_pct": 30}, {**policy(), "cash_target_pct": 10},
                       {**policy(), "core_minimum_pct": 35}, {**policy(), "core_minimum_pct": True}):
            with self.subTest(change=change), self.assertRaises(config.ActiveConfigError):
                config.validate_allocation_targets(change)

    def test_no_default_cap_penalty_and_no_automatic_core_trim_above_minimum(self):
        effective = {**recorded_account(), **policy()["research_risk_limits"]}
        self.assertEqual(account.concentration_status(55, effective), "no_fixed_single_stock_cap")
        self.assertEqual(account.dynamic_position_fit(55, effective), 8)
        self.assertEqual(account.format_cap(None), "")
        self.assertEqual(held_recommendation_label(is_core=True, current_weight=38.7,
                         hard_cap=None, score=8, thesis_break_confirmed=False), "hold_existing")
        self.assertEqual(held_recommendation_label(is_core=False, current_weight=55,
                         hard_cap=None, score=4, thesis_break_confirmed=False), "hold_pending_research")
        self.assertEqual(held_recommendation_label(is_core=False, current_weight=55,
                         hard_cap=None, score=8, thesis_break_confirmed=True), "exit_review")

    def test_whole_share_diagnostics_do_not_invent_a_name_target_or_trim_amount(self):
        effective = {**recorded_account(), **policy()["research_risk_limits"]}
        result = whole_share_diagnostics({"account_total_value": 4000, "deployable_cash": 1000},
                 [{"ticker": "TST", "latest_price": 100, "current_shares": 20, "asset_role": "active_stock"}], effective)[0]
        self.assertEqual(result["target_kind"], "company_specific_allocation_required")
        self.assertIsNone(result["target_pct"])
        self.assertIsNone(result["hard_cap_pct"])
        self.assertIsNone(result["above_target_dollars"])
        self.assertEqual(result["plus_one_share_weight_pct"], 52.5)


class PacketAllocationContractTests(unittest.TestCase):
    def constraints(self):
        return {
            "account_size_band": "small", "investment_horizon_years": 1,
            "manual_execution_only": True, "return_objective": return_objective_payload(),
            "core_allocation_target_pct": 30, "core_minimum_pct": 30,
            "active_stock_target_pct": 70, "cash_target_pct": 0,
            **policy()["research_risk_limits"],
        }

    def test_null_name_caps_keep_risk_and_manual_contract_valid(self):
        validate_portfolio_constraints(self.constraints())

    def test_null_name_caps_do_not_remove_aggregate_or_manual_constraints(self):
        for updates in (
            {"active_stock_hard_cap_pct": None}, {"active_stock_target_pct": 71},
            {"single_stock_hard_cap_pct": 70}, {"single_stock_hard_cap_pct": float("inf")},
            {"core_minimum_pct": 31}, {"core_minimum_pct": None},
            {"manual_execution_only": False}, {"cash_target_pct": 10},
        ):
            with self.subTest(updates=updates), self.assertRaises(ContractError):
                validate_portfolio_constraints({**self.constraints(), **updates})

    def test_legacy_finite_packet_remains_reproducible(self):
        historical = copy.deepcopy(self.constraints())
        historical.pop("core_minimum_pct")
        historical.update(core_allocation_target_pct=40, active_stock_target_pct=50,
                          active_stock_hard_cap_pct=50, cash_target_pct=10,
                          single_stock_default_cap_pct=15, single_stock_hard_cap_pct=15)
        validate_portfolio_constraints(historical)


class CashPlanFloorReportingTests(unittest.TestCase):
    def output(self, current_core: float):
        effective = {**recorded_account(), "core_allocation_target_pct": 30,
                     "active_stock_target_pct": 70, "cash_target_pct": 0,
                     "core_minimum_pct": 30, **policy()["research_risk_limits"]}
        summary = dict(account_total_value=4000, cash_available=4000-current_core,
                       cash_reserved=0, deployable_cash=4000-current_core,
                       current_active_stock_value=0, current_active_stock_weight_pct=0,
                       current_core_value=current_core, active_stock_status="within_target",
                       cash_status="above_target")
        written = {}
        with (patch.object(cash_plan, "load_active_inhibit", return_value={"active": False}),
              patch.object(cash_plan, "load_research_account_state", return_value=effective),
              patch.object(cash_plan, "load_portfolio_summary", return_value=summary),
              patch.object(cash_plan, "load_market_rows", return_value={"SPY": dict(
                  last_price=775, fifty_two_week_high=800, fifty_two_week_low=600, data_quality_label="ok")}),
              patch.object(cash_plan, "load_packets", return_value={"SPY": {"technical_entry_discipline_score": 7}}),
              patch.object(cash_plan, "read_csv", return_value=[]),
              patch.object(cash_plan, "write_csv", side_effect=lambda path, rows, _fields: written.update({path: rows})),
              patch.object(cash_plan, "append_run_log")):
            cash_plan.main()
        return written

    def test_two_whole_core_shares_report_minimum_satisfied_not_unfunded(self):
        output = self.output(1550)
        core = next(row for row in output[cash_plan.TARGET_ALLOCATION_REPORT] if row["asset_role"] == "core_allocation")
        self.assertEqual(core["policy_status"], "minimum_satisfied")
        self.assertEqual(core["current_weight_pct"], "38.7500")
        rows = output[cash_plan.CASH_DEPLOYMENT_PLAN]
        self.assertEqual(rows[0]["status"], "available_for_qualified_opportunities")
        self.assertEqual(rows[1]["status"], "minimum_satisfied")
        self.assertEqual(rows[1]["planned_shares"], "0")
        self.assertIn("not a trim instruction", rows[1]["reason"])

    def test_one_core_share_can_propose_the_whole_share_that_reaches_floor(self):
        output = self.output(775)
        core = next(row for row in output[cash_plan.TARGET_ALLOCATION_REPORT] if row["asset_role"] == "core_allocation")
        self.assertEqual(core["policy_status"], "below_minimum_starter_review")
        row = output[cash_plan.CASH_DEPLOYMENT_PLAN][1]
        self.assertEqual(row["status"], "selected_review")
        self.assertEqual(row["planned_shares"], "1")
        self.assertEqual(row["core_weight_after"], "38.7500")


class DurablePolicyMigrationTests(unittest.TestCase):
    def fixture(self, root: Path, *, matching_snapshot: bool) -> dict[str, bytes]:
        values = {
            migration.CONFIG: config.load_active_config(), migration.ACCOUNT: recorded_account(),
            migration.ORDERS: {"as_of": "2026-09-29T16:02:00-04:00", "complete": False, "orders": []},
        }
        for rel, value in values.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
        for rel, value in ((migration.POSITIONS, "ticker,shares_optional\nSPY,2\n"),
                           (migration.CONFIRMED, "execution_id\nhistorical-fill\n")):
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        receipt = {"schema_version": "phase5r_owner_snapshot_v1", "owner_snapshot": True,
                   "recorded_at": recorded_account()["last_updated"], "source_note": "Historical owner observation",
                   "positions_sha256_after": sha256_file(root / migration.POSITIONS),
                   "account_sha256_after": sha256_file(root / migration.ACCOUNT) if matching_snapshot else "0" * 64,
                   "confirmed_execution_sha256": sha256_file(root / migration.CONFIRMED)}
        (root / migration.MANUAL).write_text(json.dumps(receipt))
        return {rel: (root / rel).read_bytes() for rel in (*values, migration.POSITIONS, migration.CONFIRMED, migration.MANUAL)}

    def test_private_migration_receipt_and_lock_are_ignored_by_repository(self):
        # These real writer products must not dirty production or expose the
        # private account audit trail when the next safe sync runs.
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "equity"
            self.fixture(root, matching_snapshot=False)
            result = migration.migrate(root, apply=True, request_reference="Owner allocation instruction 2026-10-06")
            receipt = Path(result["receipt_path"])
            lock = root / "05_risk_and_positions/allocation_policy.local.lock"
            for artifact in (receipt, lock):
                self.assertTrue(artifact.is_file())
                relative = artifact.resolve().relative_to(root.resolve())
                with self.subTest(path=str(relative)):
                    check = subprocess.run(
                        ["git", "check-ignore", "--quiet", "--", str(relative)],
                        cwd=SCRIPT_DIR.parents[1], check=False,
                    )
                    self.assertEqual(check.returncode, 0)

    def test_preview_then_apply_preserves_facts_orders_and_stale_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "equity"
            before = self.fixture(root, matching_snapshot=False)
            preview = migration.migrate(root)
            self.assertFalse(preview["applied"])
            self.assertTrue(preview["changes"])
            self.assertEqual({rel: (root / rel).read_bytes() for rel in before}, before)
            result = migration.migrate(root, apply=True, request_reference="Owner allocation instruction 2026-10-06")
            self.assertTrue(result["applied"])
            self.assertFalse(result["manual_snapshot_rebound"])
            for rel in (migration.POSITIONS, migration.CONFIRMED, migration.ORDERS, migration.MANUAL):
                self.assertEqual((root / rel).read_bytes(), before[rel], rel)
            current = json.loads((root / migration.ACCOUNT).read_bytes())
            self.assertEqual(current["last_updated"], recorded_account()["last_updated"])
            self.assertEqual(current["cash_available"], recorded_account()["cash_available"])
            self.assertEqual(current["cash_basis"], "ledger_estimate")
            self.assertEqual(current["active_stock_target_pct"], 70)
            self.assertIsNone(current["single_stock_hard_cap_pct"])
            self.assertEqual(Path(result["predecessor_archives"][migration.ACCOUNT]).read_bytes(), before[migration.ACCOUNT])
            second = migration.migrate(root, apply=True, request_reference="Owner allocation instruction 2026-10-06")
            self.assertEqual(second["status"], "already_current")
            self.assertFalse(second["applied"])

    def test_valid_snapshot_hash_rebind_never_renews_its_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "equity"
            before = self.fixture(root, matching_snapshot=True)
            result = migration.migrate(root, apply=True, request_reference="Owner allocation instruction 2026-10-06")
            self.assertTrue(result["manual_snapshot_rebound"])
            after = json.loads((root / migration.MANUAL).read_bytes())
            self.assertEqual(after["recorded_at"], json.loads(before[migration.MANUAL])["recorded_at"])
            self.assertEqual(after["account_sha256_after"], sha256_file(root / migration.ACCOUNT))
            self.assertFalse(after["allocation_policy_rebind"]["broker_evidence_updated"])
            self.assertEqual(Path(result["predecessor_archives"][migration.MANUAL]).read_bytes(), before[migration.MANUAL])

    def test_failed_second_write_restores_exact_account_and_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "equity"
            before = self.fixture(root, matching_snapshot=True)
            real_write = migration.atomic_write_json
            def write(path, payload):
                if path == (root / migration.MANUAL).resolve():
                    raise OSError("simulated snapshot persistence failure")
                return real_write(path, payload)
            with patch.object(migration, "atomic_write_json", side_effect=write), self.assertRaises(OSError):
                migration.migrate(root, apply=True, request_reference="Owner allocation instruction 2026-10-06")
            self.assertEqual((root / migration.ACCOUNT).read_bytes(), before[migration.ACCOUNT])
            self.assertEqual((root / migration.MANUAL).read_bytes(), before[migration.MANUAL])


if __name__ == "__main__":
    unittest.main()
