#!/usr/bin/env python3
"""Protected verifier for Phase 5R daily upgrade.

This verifier never invokes a pipeline, sender, installer, activator, or
launchctl kickstart. It never opens the local SMTP configuration.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import os
import plistlib
import re
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from phase5r_daily_common import (
    ACTIVE_STATE_PATH,
    DAILY_DELIVERY_LEDGER_PATH,
    EMAIL_CONFIG_PATH,
    INHIBIT_PATH,
    ROOT,
    ExclusiveFileLock,
    cycle_date,
    iso_now,
    read_json,
    read_csv,
)
from send_phase5r_daily_email import cycle_is_blocked, delivery_policy


SCHEDULER_DIR = ROOT / "07_automation" / "scheduler"
CONTROL_REPORT = ROOT / "00_project_control" / "phase5r_daily_verification_report.md"
RESEARCH_REPORT = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_daily_verification_report.md"
)
VERIFICATION_LOG = (
    ROOT / "00_project_control" / "run_logs" / "phase5r_daily_verification_log.csv"
)
LAUNCH_AGENTS = Path("/Users/messssi/Library/LaunchAgents")
LAUNCH_DOMAIN = f"gui/{os.getuid()}"
PRODUCTION_RUNTIME_ROOT = Path("/Users/messssi/LocalRuntime/equity")
PRODUCTION_RUNTIME_WRAPPER = (
    PRODUCTION_RUNTIME_ROOT
    / "09_scripts"
    / "phase5r"
    / "run_phase5r_runtime_scheduler.py"
)
EXTERNAL_DAILYREFRESH_LAUNCHER = Path(
    "/Users/messssi/Library/Application Support/Phase5R/bin/"
    "phase5r_dailyrefresh_launcher.py"
)
LEGACY_LABELS = (
    "com.steven.phase5r.dailybrief",
    "com.steven.phase5r.weeklyconviction",
    "com.steven.phase5r.weeklycatchup",
)
NEW_JOBS = {
    "com.steven.phase5r.dailyrefresh": "dailyrefresh",
    "com.steven.phase5r.dailydecision": "dailydecision",
}
NEW_PYTHON_FILES = (
    "phase5r_active_config.py",
    "phase5r_daily_common.py",
    "phase5r_evidence_freshness.py",
    "phase5r_massive_b2_adapter.py",
    "phase5r_sec_acceptance.py",
    "phase5r_sec_acceptance_extensions.py",
    "phase5r_return_objective.py",
    "phase5r_valuation_evidence_v1.py",
    "phase5r_valuation_input_bundle.py",
    "phase5r_c9_common.py",
    "phase5r_c9b_common.py",
    "run_phase5r_b2_full_universe_market_data.py",
    "score_phase5r_b2_candidates.py",
    "refresh_phase5r_daily_evidence.py",
    "refresh_phase5r_sec_filing_artifacts.py",
    "refresh_phase5r_valuation_scenarios.py",
    "build_phase5r_current_research_baseline.py",
    "regenerate_phase5r_c9_portfolio_outputs.py",
    "create_phase5r_c9b_price_aware_action_plan.py",
    "create_phase5r_daily_decision_and_brief.py",
    "build_phase5r_decision_evidence_packet.py",
    "track_phase5r_recommendation_outcomes.py",
    "generate_phase5r_current_status.py",
    "send_phase5r_daily_email.py",
    "run_phase5r_daily_refresh.py",
    "run_phase5r_daily_decision_pipeline.py",
    "run_phase5r_daily_refresh_scheduler.py",
    "run_phase5r_daily_scheduler.py",
    "run_phase5r_runtime_scheduler.py",
    "phase5r_packet_contract.py",
    "verify_phase5r_daily_upgrade.py",
)
SHELL_FILES = (
    "install_phase5r_daily_schedulers.sh",
    "check_phase5r_daily_scheduler_status.sh",
    "uninstall_phase5r_daily_schedulers.sh",
    "activate_phase5r_daily_after_verification.sh",
    "set_phase5r_c9_maintenance_inhibit.sh",
    "clear_phase5r_c9_maintenance_inhibit.sh",
)
MUTATION_SENTINELS = (
    DAILY_DELIVERY_LEDGER_PATH,
)


def file_digest_or_absent(target: Path) -> str:
    if not target.exists():
        return "absent"
    return hashlib.sha256(target.read_bytes()).hexdigest()


def smtp_stat_only() -> tuple[int, int, int] | str:
    try:
        metadata = EMAIL_CONFIG_PATH.stat()
    except FileNotFoundError:
        return "absent"
    return (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def smtp_owner_private() -> bool:
    """Validate metadata only; never open the SMTP configuration."""

    try:
        metadata = EMAIL_CONFIG_PATH.lstat()
    except FileNotFoundError:
        return False
    return bool(
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_nlink == 1
        and metadata.st_uid == os.getuid()
        and metadata.st_mode & 0o077 == 0
    )


def loaded(label: str) -> bool:
    return (
        subprocess.run(
            ["/bin/launchctl", "print", f"{LAUNCH_DOMAIN}/{label}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def add_check(
    checks: list[dict[str, str]], check_id: str, passed: bool, detail: str
) -> None:
    checks.append(
        {
            "id": check_id,
            "result": "PASS" if passed else "FAIL",
            "detail": detail,
        }
    )


def plist_checks(checks: list[dict[str, str]]) -> None:
    for label, job_name in NEW_JOBS.items():
        template = SCHEDULER_DIR / f"{label}.plist.template"
        installed = LAUNCH_AGENTS / f"{label}.plist"
        add_check(checks, f"{label}.loaded", loaded(label), "new job loaded")
        same = (
            template.exists()
            and installed.exists()
            and template.read_bytes() == installed.read_bytes()
        )
        add_check(checks, f"{label}.installed", same, "installed plist matches template")
        if not template.exists():
            continue
        with template.open("rb") as handle:
            payload = plistlib.load(handle)
        arguments = payload.get("ProgramArguments", [])
        expected_arguments = (
            [str(EXTERNAL_DAILYREFRESH_LAUNCHER)]
            if job_name == "dailyrefresh"
            else [
                "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
                str(PRODUCTION_RUNTIME_WRAPPER),
                "--job",
                job_name,
            ]
        )
        launcher_ready = (
            job_name != "dailyrefresh"
            or (
                EXTERNAL_DAILYREFRESH_LAUNCHER.is_file()
                and not EXTERNAL_DAILYREFRESH_LAUNCHER.is_symlink()
                and EXTERNAL_DAILYREFRESH_LAUNCHER.stat().st_uid == os.getuid()
                and (EXTERNAL_DAILYREFRESH_LAUNCHER.stat().st_mode & 0o777)
                in {0o500, 0o700}
            )
        )
        invariant = (
            payload.get("Label") == label
            and payload.get("RunAtLoad") is True
            and payload.get("KeepAlive") is False
            and payload.get("StartInterval") == 900
            and "StartCalendarInterval" not in payload
            and payload.get("WorkingDirectory") == str(PRODUCTION_RUNTIME_ROOT)
            and arguments == expected_arguments
            and launcher_ready
            and all(
                token not in " ".join(arguments).lower()
                for token in ("c2", "c3", "c6", "c7", "weekly", "sender")
            )
        )
        add_check(
            checks,
            f"{label}.invariants",
            invariant,
            "RunAtLoad=true KeepAlive=false StartInterval=900 locked runtime-wrapper arguments",
        )

    model_label = "com.steven.phase5r.llmshadow"
    add_check(
        checks,
        "model.job_absent",
        not loaded(model_label)
        and not (LAUNCH_AGENTS / f"{model_label}.plist").exists(),
        "retired model job is unloaded and has no installed plist",
    )


def source_checks(checks: list[dict[str, str]]) -> None:
    script_dir = ROOT / "09_scripts" / "phase5r"
    compile_ok = True
    for name in NEW_PYTHON_FILES:
        target = script_dir / name
        try:
            compile(target.read_text(encoding="utf-8"), str(target), "exec")
        except (OSError, SyntaxError):
            compile_ok = False
    add_check(checks, "python.syntax", compile_ok, "all daily Python files compile")

    shell_ok = True
    for name in SHELL_FILES:
        target = SCHEDULER_DIR / name
        syntax = subprocess.run(
            ["/bin/zsh", "-n", str(target)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if syntax.returncode != 0:
            shell_ok = False
    add_check(
        checks,
        "shell.safety",
        shell_ok,
        "active scheduler shell files pass zsh syntax validation",
    )

    refresh_source = (script_dir / "run_phase5r_daily_refresh.py").read_text(
        encoding="utf-8"
    )
    add_check(
        checks,
        "refresh.no_sender",
        all(
            token not in refresh_source
            for token in ("send_phase5r_daily_email", "smtplib", "EMAIL_CONFIG_PATH")
        ),
        "refresh pipeline has no sender or SMTP-config reference",
    )

    canonical_model_references: list[str] = []
    for name in (
        "run_phase5r_daily_refresh.py",
        "run_phase5r_daily_decision_pipeline.py",
        "run_phase5r_daily_refresh_scheduler.py",
        "run_phase5r_daily_scheduler.py",
        "send_phase5r_daily_email.py",
    ):
        source = (script_dir / name).read_text(encoding="utf-8")
        if any(
            marker in source
            for marker in (
                "run_phase5r_llm_shadow",
                "phase5r_llm_provider",
                "CodexCliProvider",
                "production_shadow",
                "OPENAI_API_KEY",
            )
        ):
            canonical_model_references.append(name)
    add_check(
        checks,
        "model.not_in_critical_path",
        not canonical_model_references,
        "canonical refresh, decision, scheduler, and sender have no model/provider path",
    )

    sender_source = (script_dir / "send_phase5r_daily_email.py").read_text(
        encoding="utf-8"
    )
    send_once_source = sender_source[sender_source.index("def send_once") :]
    order_ok = (
        send_once_source.index("delivery_guard()")
        < send_once_source.index("ExclusiveFileLock")
        < send_once_source.index("cycle_is_blocked")
        < send_once_source.index("load_config()")
        < send_once_source.index('status="send_claimed"')
        < send_once_source.index("smtp_factory(")
    )
    add_check(
        checks,
        "sender.ordering",
        order_ok,
        "eligibility, lock, dedupe, config validation, durable claim, SMTP ordering",
    )

    config_openers: list[str] = []
    for name in NEW_PYTHON_FILES:
        target = script_dir / name
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        for node in ast.walk(tree):
            path_open = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"open", "read_text", "read_bytes"}
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "EMAIL_CONFIG_PATH"
            )
            secure_os_open = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
                and node.func.attr == "open"
                and bool(node.args)
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id == "EMAIL_CONFIG_PATH"
            )
            if path_open or secure_os_open:
                config_openers.append(name)
    add_check(
        checks,
        "smtp.single_owner",
        sorted(set(config_openers)) == ["send_phase5r_daily_email.py"],
        "only the new sender opens SMTP configuration",
    )

    prohibited_calls: list[str] = []
    for name in NEW_PYTHON_FILES:
        target = script_dir / name
        tree = ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = (
                    [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                if any("broker" in module.lower() for module in modules):
                    prohibited_calls.append(f"{name}:broker_import")
            if isinstance(node, ast.Call):
                function_name = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if function_name in {
                    "place_order",
                    "submit_order",
                    "create_order",
                    "get_accounts",
                    "get_account",
                }:
                    prohibited_calls.append(f"{name}:{function_name}")
    add_check(
        checks,
        "prohibited.code",
        not prohibited_calls,
        "no broker/account/order API imports or calls",
    )

    retired_active_paths = (
        script_dir / "send_phase5r_c2_daily_email.py",
        script_dir / "run_phase5r_c3_daily_email_pipeline.py",
        script_dir / "run_phase5r_llm_shadow.py",
        script_dir / "run_phase5r_production_shadow.py",
    )
    legacy_retired = not any(path.exists() for path in retired_active_paths)
    add_check(
        checks,
        "retired.entrypoints_absent",
        legacy_retired,
        "retired email and model entrypoints are absent from the active script tree",
    )


def pure_guard_tests(checks: list[dict[str, str]]) -> None:
    blocked_ok = all(
        cycle_is_blocked(
            [{"cycle_date": "2026-07-24", "status": status}], "2026-07-24"
        )[0]
        for status in ("send_claimed", "sent", "delivery_unknown")
    )
    clear_ok = not cycle_is_blocked([], "2026-07-24")[0]
    add_check(
        checks,
        "sender.dedupe_matrix",
        blocked_ok and clear_ok,
        "claim, sent, and unknown all block same-date delivery",
    )

    weekend_matrix = (
        delivery_policy(
            is_weekend=False,
            material_event=False,
            decision_changed=False,
            account_conflict=False,
        )[0]
        and not delivery_policy(
            is_weekend=True,
            material_event=False,
            decision_changed=False,
            account_conflict=False,
        )[0]
        and delivery_policy(
            is_weekend=True,
            material_event=True,
            decision_changed=False,
            account_conflict=False,
        )[0]
        and delivery_policy(
            is_weekend=True,
            material_event=False,
            decision_changed=True,
            account_conflict=False,
        )[0]
        and delivery_policy(
            is_weekend=True,
            material_event=False,
            decision_changed=False,
            account_conflict=True,
        )[0]
    )
    add_check(
        checks,
        "weekend.policy",
        weekend_matrix,
        "weekday daily; weekend only material/change/conflict",
    )

    with tempfile.TemporaryDirectory() as directory:
        lock_target = Path(directory) / "delivery.lock"
        second_blocked = False
        with ExclusiveFileLock(lock_target):
            try:
                with ExclusiveFileLock(lock_target):
                    pass
            except RuntimeError:
                second_blocked = True
    add_check(
        checks,
        "sender.lock",
        second_blocked,
        "second concurrent lock acquisition is rejected",
    )


def append_verification_log(result: str, mode: str) -> None:
    fields = [
        "timestamp",
        "cycle_date",
        "mode",
        "result",
        "email_attempted",
        "email_sent",
        "c7_invoked",
        "smtp_config_read",
        "smtp_config_modified",
        "broker_connected",
        "broker_account_read",
        "order_code_created",
        "phase5r_e_created",
    ]
    VERIFICATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    existed = VERIFICATION_LOG.exists() and VERIFICATION_LOG.stat().st_size > 0
    with VERIFICATION_LOG.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not existed:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": iso_now(),
                "cycle_date": cycle_date(),
                "mode": mode,
                "result": result,
                "email_attempted": "no",
                "email_sent": "no",
                "c7_invoked": "no",
                "smtp_config_read": "no",
                "smtp_config_modified": "no",
                "broker_connected": "no",
                "broker_account_read": "no",
                "order_code_created": "no",
                "phase5r_e_created": "no",
            }
        )
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--protected", action="store_true")
    mode.add_argument("--operational", action="store_true")
    args = parser.parse_args()
    verification_mode = "protected" if args.protected else "operational"

    before_hashes = {str(target): file_digest_or_absent(target) for target in MUTATION_SENTINELS}
    smtp_before = smtp_stat_only()
    checks: list[dict[str, str]] = []

    active = read_json(ACTIVE_STATE_PATH)
    inhibit = read_json(INHIBIT_PATH)
    active_ok = (
        active.get("current_workflow") == "daily_decision"
        and active.get("active_pipeline") == "phase5r_daily"
        and active.get("email_delivery_allowed_from") == "phase5r_daily_only"
        and active.get("broker_connection_allowed") == "no"
        and active.get("order_code_allowed") == "no"
        and active.get("manual_execution_only") == "yes"
    )
    add_check(checks, "active.state", active_ok, "daily workflow and safety boundaries")
    smtp_permissions_ok = smtp_owner_private()
    add_check(
        checks,
        "smtp.permissions",
        smtp_permissions_ok
        or (verification_mode == "protected" and smtp_before == "absent"),
        "SMTP config absent in protected setup or owner-private regular file",
    )
    if verification_mode == "protected":
        inhibit_ok = inhibit.get("active") is True and inhibit.get("allowed_pipeline") == "none"
    else:
        inhibit_ok = (
            inhibit.get("active") is False
            and inhibit.get("allowed_pipeline") == "phase5r_daily"
        )
    add_check(
        checks,
        "maintenance.state",
        inhibit_ok,
        f"inhibit matches {verification_mode} mode",
    )

    for label in LEGACY_LABELS:
        add_check(
            checks,
            f"{label}.retired",
            not loaded(label) and not (LAUNCH_AGENTS / f"{label}.plist").exists(),
            "legacy job unloaded and installed plist absent",
        )
    plist_checks(checks)
    source_checks(checks)
    pure_guard_tests(checks)

    decision_path = (
        ROOT
        / "04_research"
        / "realtime_stock_picker_phase5r"
        / "phase5r_daily_decision.json"
    )
    if decision_path.exists():
        decision = read_json(decision_path)
        held_position_rows = decision.get("held_positions", [])
        hold_rows = [
            row
            for row in held_position_rows
            if row.get("action") == "hold"
        ]
        review_ok = all(
            row.get("human_confirmation_required") == "no" for row in hold_rows
        )
        fundamental_rows = decision.get("held_fundamentals", [])
        fundamental_ok = (
            decision.get("fundamental_gate", {}).get("passed") is True
            and len(fundamental_rows) == len(held_position_rows)
            and all(
                row.get("data_quality") == "ok"
                and str(row.get("source_url", "")).startswith(
                    "https://data.sec.gov/api/xbrl/companyfacts/"
                )
                for row in fundamental_rows
            )
        )
    else:
        review_ok = verification_mode == "protected"
        fundamental_ok = verification_mode == "protected"
    add_check(
        checks,
        "manual_review.reduced",
        review_ok,
        "HOLD rows do not require manual confirmation",
    )
    routine_review_violations: list[str] = []
    for target in (
        ROOT / "05_risk_and_positions" / "phase5r_c9_exact_action_plan.csv",
        ROOT
        / "04_research"
        / "realtime_stock_picker_phase5r"
        / "phase5r_c9_position_recommendations.csv",
        ROOT
        / "04_research"
        / "realtime_stock_picker_phase5r"
        / "phase5r_c9_new_candidate_recommendations.csv",
        ROOT
        / "05_risk_and_positions"
        / "phase5r_c9b_price_aware_action_plan.csv",
    ):
        for row in read_csv(target):
            action = (
                row.get("recommended_action")
                or row.get("action")
                or row.get("action_label")
                or ""
            ).strip().lower()
            if (
                action in {"hold", "watch", "watch_only", "no_new_position"}
                and row.get("human_confirmation_required", "").strip().lower()
                == "yes"
            ):
                routine_review_violations.append(f"{target.name}:{action}")
    add_check(
        checks,
        "manual_review.all_outputs",
        not routine_review_violations,
        "routine HOLD/WATCH rows across C9/C9B require no confirmation",
    )
    add_check(
        checks,
        "fundamentals.held_coverage",
        fundamental_ok,
        "held companies have current official SEC XBRL coverage",
    )

    phase_e_exists = any(
        re.search(r"phase5r[_-]e(?:[_\-.]|$)", target.name.lower()) is not None
        for target in ROOT.rglob("*")
        if target.is_file()
    )
    add_check(checks, "phase5r_e.absent", not phase_e_exists, "Phase 5R-E not created")

    after_hashes = {str(target): file_digest_or_absent(target) for target in MUTATION_SENTINELS}
    smtp_after = smtp_stat_only()
    add_check(
        checks,
        "verification.non_mutating",
        before_hashes == after_hashes,
        "daily delivery ledger unchanged",
    )
    add_check(
        checks,
        "smtp.non_modification",
        smtp_before == smtp_after,
        "SMTP config stat unchanged; content never opened",
    )

    passed = all(row["result"] == "PASS" for row in checks)
    overall = "PASS" if passed else "FAIL"
    lines = [
        "# Phase 5R Daily Upgrade Verification Report",
        "",
        f"Generated: `{iso_now()}`",
        "",
        f"Overall result: **{overall}**",
        f"Verification mode: `{verification_mode}`",
        "",
        "## Checks",
        "",
        "| ID | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for row in checks:
        lines.append(f"| {row['id']} | {row['result']} | {row['detail']} |")
    lines.extend(
        [
            "",
            "## Non-Modification Evidence",
            "",
            f"- Daily delivery sentinel state unchanged: `{'yes' if before_hashes == after_hashes else 'no'}`.",
            f"- SMTP configuration metadata unchanged: `{'yes' if smtp_before == smtp_after else 'no'}`.",
            "- SMTP configuration content read: `no`.",
            "",
            "## Prohibited-Action Verification",
            "",
            "- email_attempted=no",
            "- email_sent=no",
            "- c7_invoked=no",
            "- smtp_config_read=no",
            "- smtp_config_modified=no",
            "- broker_connected=no",
            "- broker_account_read=no",
            "- order_code_created=no",
            "- phase5r_e_created=no",
            "",
            "## Verification Safety Boundary",
            "",
            "The verifier used only static reads, plist parsing, launchctl print, zsh syntax checks, and temporary-file pure guard tests. It did not invoke any sender, research pipeline, installer, activator, or public network request.",
            "",
            "## Operational Handoff",
            "",
            "Protected PASS authorizes only the separate activation script. Operational PASS confirms the inhibit was cleared solely for phase5r_daily; it does not send an email.",
        ]
    )
    report = "\n".join(lines) + "\n"
    CONTROL_REPORT.write_text(report, encoding="utf-8")
    RESEARCH_REPORT.parent.mkdir(parents=True, exist_ok=True)
    RESEARCH_REPORT.write_text(report, encoding="utf-8")
    append_verification_log(overall, verification_mode)
    print(
        f"verification_result={overall.lower()} mode={verification_mode} "
        "email_attempted=false smtp_config_read=false"
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
