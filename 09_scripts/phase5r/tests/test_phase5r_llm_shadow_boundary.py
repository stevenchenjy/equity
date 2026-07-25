from __future__ import annotations

import ast
import hashlib
import json
import smtplib
import socket
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from _support import PROJECT_ROOT, digest_or_absent, materialized, rehash
from evaluate_phase5r_llm_decision import (
    _safe_output_dir,
    evaluate_manifest,
    write_report,
)
from enable_phase5r_llm_live_shadow import offline_replay_status
from phase5r_daily_common import EMAIL_CONFIG_PATH
from phase5r_llm_contract import ContractError, validate_packet
from run_phase5r_llm_shadow import (
    ShadowOutputLock,
    _write_audit,
    load_registry,
    output_paths,
)
from run_phase5r_llm_shadow_scheduler import validate_runtime_boundary


SCRIPT_DIR = PROJECT_ROOT / "09_scripts" / "phase5r"
SCAN_FILES = (
    SCRIPT_DIR / "phase5r_llm_contract.py",
    SCRIPT_DIR / "build_phase5r_decision_evidence_packet.py",
    SCRIPT_DIR / "phase5r_llm_provider.py",
    SCRIPT_DIR / "run_phase5r_llm_shadow.py",
    SCRIPT_DIR / "evaluate_phase5r_llm_decision.py",
    SCRIPT_DIR / "run_phase5r_llm_shadow_scheduler.py",
    SCRIPT_DIR / "enable_phase5r_llm_live_shadow.py",
)
SENTINELS = (
    PROJECT_ROOT
    / "07_automation"
    / "email_delivery"
    / "phase5r_daily_delivery_ledger.csv",
    PROJECT_ROOT
    / "07_automation"
    / "email_delivery"
    / "phase5r_c2_delivery_status.csv",
    PROJECT_ROOT
    / "07_automation"
    / "email_delivery"
    / "phase5r_c6_delivery_status.csv",
    PROJECT_ROOT / "00_project_control" / "run_logs" / "phase5r_c7_run_log.csv",
    PROJECT_ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_c7_weekly_pipeline_run_log.csv",
    PROJECT_ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_daily_decision.json",
    PROJECT_ROOT
    / "07_automation"
    / "email_briefs"
    / "phase5r_daily_email_brief.txt",
    PROJECT_ROOT
    / "07_automation"
    / "email_briefs"
    / "phase5r_daily_email_brief.html",
    PROJECT_ROOT / "05_risk_and_positions" / "current_positions.local.csv",
    PROJECT_ROOT / "05_risk_and_positions" / "current_account_state.local.json",
    PROJECT_ROOT / "06_execution_records" / "manual_executions.local.csv",
    PROJECT_ROOT
    / "06_execution_records"
    / "phase5r_c9b_pending_execution_report.csv",
    PROJECT_ROOT
    / "06_execution_records"
    / "phase5r_c9b_confirmed_execution_report.csv",
    PROJECT_ROOT
    / "06_execution_records"
    / "phase5r_c9b_reconciliation_report.csv",
    PROJECT_ROOT
    / "05_risk_and_positions"
    / "phase5r_c9_exact_action_plan.csv",
    PROJECT_ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_position_recommendations.csv",
    PROJECT_ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_new_candidate_recommendations.csv",
)


def smtp_stat() -> tuple[int, int, int, int] | str:
    try:
        metadata = EMAIL_CONFIG_PATH.stat()
    except FileNotFoundError:
        return "absent"
    return (
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


class BoundaryTests(unittest.TestCase):
    def test_static_model_layer_has_no_email_broker_order_or_c7_calls(self) -> None:
        prohibited_import_tokens = (
            "smtplib",
            "imaplib",
            "alpaca",
            "ib_insync",
            "robin_stocks",
            "ccxt",
        )
        prohibited_calls = {
            "sendmail",
            "send_message",
            "place_order",
            "submit_order",
            "create_order",
            "get_account",
            "get_accounts",
            "execute_trade",
        }
        violations: list[str] = []
        for path in SCAN_FILES:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("run_phase5r_c7_weekly_conviction_pipeline", source)
            self.assertNotIn("run_phase5r_daily_refresh.py", source)
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(token in alias.name.lower() for token in prohibited_import_tokens):
                            violations.append(f"{path.name}:import:{alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if any(token in module.lower() for token in prohibited_import_tokens):
                        violations.append(f"{path.name}:from:{module}")
                elif isinstance(node, ast.Call):
                    name = (
                        node.func.attr
                        if isinstance(node.func, ast.Attribute)
                        else node.func.id
                        if isinstance(node.func, ast.Name)
                        else ""
                    )
                    if name in prohibited_calls:
                        violations.append(f"{path.name}:call:{name}")
        self.assertEqual(violations, [])

    def test_offline_evaluation_does_not_touch_operational_state(self) -> None:
        before = {str(path): digest_or_absent(path) for path in SENTINELS}
        smtp_before = smtp_stat()
        original_open = Path.open

        def guarded_open(path: Path, *args: object, **kwargs: object):
            if path.expanduser().resolve() == EMAIL_CONFIG_PATH.expanduser().resolve():
                raise AssertionError("SMTP configuration was opened")
            return original_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory(prefix="phase5r-eval-test-") as directory:
            with (
                mock.patch.object(Path, "open", guarded_open),
                mock.patch(
                    "phase5r_llm_provider.subprocess.run",
                    side_effect=AssertionError("Codex/process invoked"),
                ) as process_mock,
                mock.patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network invoked"),
                ) as network_mock,
                mock.patch.object(
                    urllib.request,
                    "urlopen",
                    side_effect=AssertionError("HTTP invoked"),
                ) as urlopen_mock,
                mock.patch.object(
                    smtplib,
                    "SMTP",
                    side_effect=AssertionError("email invoked"),
                ) as smtp_mock,
            ):
                report = evaluate_manifest()
                write_report(Path(directory), report)
            process_mock.assert_not_called()
            network_mock.assert_not_called()
            urlopen_mock.assert_not_called()
            smtp_mock.assert_not_called()
            self.assertEqual(
                {path.name for path in Path(directory).iterdir()},
                {
                    "phase5r_llm_evaluation_report.json",
                    "phase5r_llm_evaluation_report.md",
                },
            )
        after = {str(path): digest_or_absent(path) for path in SENTINELS}
        self.assertEqual(before, after)
        self.assertEqual(smtp_before, smtp_stat())

    def test_output_path_rejects_project_and_sensitive_targets(self) -> None:
        with self.assertRaisesRegex(ContractError, "outside the project"):
            _safe_output_dir(PROJECT_ROOT / "00_project_control")
        with self.assertRaises(ContractError):
            _safe_output_dir(Path("/tmp/phase5r-smtp-canary"))
        with self.assertRaisesRegex(ContractError, "outside the project"):
            output_paths(PROJECT_ROOT / "04_research")
        with self.assertRaisesRegex(ContractError, "sensitive path"):
            output_paths(Path("/tmp/phase5r-email_delivery-canary"))

    def test_sensitive_packet_canary_is_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["entities"][0]["thesis"] = "SMTP_CANARY_DO_NOT_LEAK"
        with self.assertRaisesRegex(ContractError, "sensitive/local marker"):
            validate_packet(rehash(packet))

    def test_audit_append_refuses_symlink_target(self) -> None:
        bundle = {
            "model_run_id": "canary-run",
            "packet_id": "canary-packet",
            "decision_fingerprint": "canary-decision",
            "outcome": "validated",
            "adjudication": {
                "effective_classification": "hold_existing",
                "validation_passed": True,
            },
            "provider_metadata": [],
        }
        with tempfile.TemporaryDirectory(prefix="phase5r-audit-link-test-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.txt"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            link = root / "phase5r_llm_decision_audit.jsonl"
            link.symlink_to(canary)
            before = canary.read_bytes()
            with self.assertRaises(OSError):
                _write_audit(link, bundle)
            self.assertEqual(canary.read_bytes(), before)

    def test_live_runner_exposes_no_close_count_override(self) -> None:
        source = (SCRIPT_DIR / "run_phase5r_llm_shadow.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--distinct-valid-closes", source)

    def test_shadow_output_lock_refuses_symlink(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-lock-link-test-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.lock"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            link = root / "phase5r_llm_shadow.lock"
            link.symlink_to(canary)
            with self.assertRaises(OSError):
                with ShadowOutputLock(link):
                    pass
            self.assertEqual(canary.read_text(encoding="utf-8"), "UNCHANGED\n")

    def test_scheduler_revalidates_runtime_boundary(self) -> None:
        active = {
            "current_workflow": "daily_decision",
            "active_pipeline": "phase5r_daily",
            "email_delivery_allowed_from": "phase5r_daily_only",
            "broker_connection_allowed": "no",
            "order_code_allowed": "no",
            "manual_execution_only": "yes",
        }
        inhibit = {"active": False, "allowed_pipeline": "phase5r_daily"}
        registry = load_registry()
        validate_runtime_boundary(active, inhibit, registry)
        active["active_pipeline"] = "phase5r_c7"
        with self.assertRaisesRegex(RuntimeError, "active.active_pipeline"):
            validate_runtime_boundary(active, inhibit, registry)

    def test_installer_preflights_before_bootstrap(self) -> None:
        source = (
            PROJECT_ROOT
            / "07_automation"
            / "scheduler"
            / "install_phase5r_llm_shadow_scheduler.sh"
        ).read_text(encoding="utf-8")
        self.assertLess(
            source.index("run_phase5r_llm_shadow_scheduler.py\" --safe-check"),
            source.index("/bin/launchctl bootstrap"),
        )
        self.assertIn("cleanup_incomplete_install", source)

    def test_live_activation_is_blocked_until_replay_corpus_gate(self) -> None:
        ready, case_count, transition_count = offline_replay_status(200, 50)
        self.assertFalse(ready)
        self.assertLess(case_count, 200)
        self.assertLess(transition_count, 50)


if __name__ == "__main__":
    unittest.main()
