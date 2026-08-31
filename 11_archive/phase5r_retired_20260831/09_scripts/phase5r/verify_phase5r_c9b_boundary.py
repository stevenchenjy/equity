from __future__ import annotations

import ast
import csv
import hashlib
import os
import subprocess
from pathlib import Path

from phase5r_c9_common import EXACT_ACTION_PLAN, load_positions
from phase5r_c9b_common import (
    ACCOUNT_STATE,
    C9B_RUN_LOG,
    CONFIRMED_REPORT,
    CURRENT_POSITIONS,
    EXECUTION_EXAMPLE,
    EXECUTION_FIELDS,
    EXECUTION_FILE,
    EXECUTION_RESEARCH_REPORT,
    EXECUTION_TEMPLATE,
    PENDING_REPORT,
    POST_EXECUTION_SUMMARY,
    POST_EXECUTION_WEIGHTS,
    PRICE_AWARE_ACTION_PLAN,
    RECONCILIATION_REPORT,
    ROOT,
    applied_reconciliation_matches_current_state,
    append_c9b_log,
    load_account_state,
    load_active_inhibit,
    load_execution_rows,
    read_csv,
    sha256,
    timestamp,
    write_text,
)


CONTROL_REPORT = ROOT / "00_project_control" / "phase5r_c9b_verification_report.md"
RESEARCH_REPORT = ROOT / "04_research" / "realtime_stock_picker_phase5r" / "phase5r_c9b_verification_report.md"
EXECUTION_POLICY = ROOT / "00_project_control" / "phase5r_c9b_execution_policy.md"
PRICE_POLICY = ROOT / "00_project_control" / "phase5r_c9b_price_guidance_policy.md"
RECONCILIATION_POLICY = ROOT / "00_project_control" / "phase5r_c9b_account_reconciliation_policy.md"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"
C6_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv"
C6_BODY = ROOT / "07_automation" / "email_briefs" / "phase5r_c6_weekly_email_body.txt"
SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"

EXPECTED_SMTP_SHA256 = "01c2c75377dd1c758fd581bf2d374ae058c60fa8c4fbf962c116099c91b12e16"
EXPECTED_C6_STATUS_SHA256 = "9870aa5dbb008ee32fe50b87deec8c73ed3ff255b21a4695460c2fe591060f9e"
REQUIRED_OUTPUTS = [
    EXECUTION_POLICY,
    PRICE_POLICY,
    RECONCILIATION_POLICY,
    EXECUTION_TEMPLATE,
    EXECUTION_EXAMPLE,
    PENDING_REPORT,
    CONFIRMED_REPORT,
    RECONCILIATION_REPORT,
    POST_EXECUTION_WEIGHTS,
    POST_EXECUTION_SUMMARY,
    PRICE_AWARE_ACTION_PLAN,
    EXECUTION_RESEARCH_REPORT,
    C9B_RUN_LOG,
]
REQUIRED_ACTION_FIELDS = [
    "ticker",
    "action",
    "shares_under_review",
    "target_shares",
    "reference_price",
    "reference_price_timestamp",
    "minimum_sell_price_or_condition",
    "maximum_buy_price_or_condition",
    "suggested_order_style",
    "maximum_slippage_pct",
    "validity_window",
    "cancellation_condition",
    "target_weight_after",
    "reason",
    "human_confirmation_required",
    "automatic_action_allowed",
]
FORBIDDEN_BROKER_MODULES = {
    "alpaca",
    "alpaca_trade_api",
    "ib_insync",
    "ibapi",
    "robin_stocks",
    "ccxt",
    "tda",
    "schwab",
    "futu",
}
FORBIDDEN_ORDER_CALLS = {"place_order", "submit_order", "send_order", "execute_order", "route_order", "cancel_order", "modify_order"}


def check(condition: bool, name: str, detail: str, results: list[tuple[str, str, str]]) -> None:
    results.append((name, "PASS" if condition else "FAIL", detail))


def gitignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path.relative_to(ROOT))],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def code_boundary() -> tuple[set[str], set[str], set[str]]:
    broker_imports: set[str] = set()
    order_calls: set[str] = set()
    archive_refs: set[str] = set()
    for path in sorted(SCRIPT_DIR.glob("*phase5r_c9b*.py")):
        source = path.read_text(encoding="utf-8")
        if path.name != Path(__file__).name and ("11_archive" in source or "archived_position" in source):
            archive_refs.add(path.name)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".", 1)[0] in FORBIDDEN_BROKER_MODULES:
                        broker_imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] in FORBIDDEN_BROKER_MODULES:
                    broker_imports.add(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_ORDER_CALLS:
                    order_calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ORDER_CALLS:
                    order_calls.add(node.func.attr)
    return broker_imports, order_calls, archive_refs


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def main() -> int:
    results: list[tuple[str, str, str]] = []
    rows = load_execution_rows()
    inhibit = load_active_inhibit()
    account = load_account_state()
    positions = {str(row["ticker"]): row for row in load_positions()}

    check(EXECUTION_FILE.exists(), "execution_file_exists", str(EXECUTION_FILE.relative_to(ROOT)), results)
    check(gitignored(EXECUTION_FILE), "execution_file_gitignored", "git check-ignore", results)
    check((EXECUTION_FILE.stat().st_mode & 0o077) == 0, "execution_file_private_mode", oct(EXECUTION_FILE.stat().st_mode & 0o777), results)
    check(csv_header(EXECUTION_FILE) == EXECUTION_FIELDS, "execution_columns_exact", f"columns={len(EXECUTION_FIELDS)}", results)

    execution = rows[0] if len(rows) == 1 and rows[0]["ticker"] == "IOT" and rows[0]["side"] == "sell" else {}
    execution_status = execution.get("order_status", "missing")
    execution_contract_ok = bool(execution) and execution.get("shares_before") == "8"
    if execution_status in {"pending_fill", "filled"}:
        execution_contract_ok = execution_contract_ok and execution.get("shares") == "3" and execution.get("shares_after") == "5"
    check(execution_contract_ok, "iot_execution_record_valid", f"status={execution_status}; rows={len(rows)}", results)
    pending_values_ok = True
    if execution_status == "pending_fill":
        pending_values_ok = all(
            execution[field].strip() == ""
            for field in ("fill_date", "fill_price", "fees", "cash_before", "cash_after", "account_total_after")
        )
    check(pending_values_ok, "pending_financial_values_blank", "not applicable" if execution_status != "pending_fill" else "fill/cash/account fields blank", results)

    pending_report_rows = read_csv(PENDING_REPORT) if PENDING_REPORT.exists() else []
    confirmed_report_rows = read_csv(CONFIRMED_REPORT) if CONFIRMED_REPORT.exists() else []
    intake_rows = pending_report_rows if execution_status == "pending_fill" else confirmed_report_rows
    intake = next((row for row in intake_rows if row.get("execution_id") == execution.get("execution_id")), {})
    positions_match_intake = bool(intake) and sha256(CURRENT_POSITIONS) == intake.get("positions_sha256_at_intake")
    account_matches_intake = bool(intake) and sha256(ACCOUNT_STATE) == intake.get("account_state_sha256_at_intake")

    missing = [path for path in REQUIRED_OUTPUTS if not path.exists() or path.stat().st_size == 0]
    check(not missing, "required_outputs_exist", f"missing={len(missing)}", results)
    reconciliation = read_csv(RECONCILIATION_REPORT) if RECONCILIATION_REPORT.exists() else []
    recon = reconciliation[0] if len(reconciliation) == 1 and reconciliation[0].get("execution_id") == execution.get("execution_id") else {}
    applied = recon.get("canonical_state_applied") == "yes"
    if execution_status == "pending_fill":
        reconciliation_ok = recon.get("reconciliation_status") == "pending_no_mutation" and not applied
    elif execution_status == "cancelled":
        reconciliation_ok = recon.get("reconciliation_status") == "cancelled_no_mutation" and not applied
    elif execution_status in {"filled", "partial_fill"}:
        reconciliation_ok = recon.get("reconciliation_status") in {"validated_preview_not_applied", "applied"}
    else:
        reconciliation_ok = False
    check(reconciliation_ok, "execution_reconciliation_state_valid", recon.get("reconciliation_status", "missing"), results)
    post_weights = read_csv(POST_EXECUTION_WEIGHTS) if POST_EXECUTION_WEIGHTS.exists() else []
    if execution_status in {"pending_fill", "cancelled"}:
        canonical_consistency = positions_match_intake and account_matches_intake and not post_weights
    elif applied:
        canonical_consistency = (
            sha256(CURRENT_POSITIONS) == recon.get("positions_sha256_after")
            and applied_reconciliation_matches_current_state(
                recon,
                current_positions_sha256=sha256(CURRENT_POSITIONS),
                current_account_sha256=sha256(ACCOUNT_STATE),
                current_account_last_updated=account["last_updated"],
            )
            and float(positions.get("IOT", {}).get("shares", -1)) == float(execution.get("shares_after", -2))
            and bool(post_weights)
        )
    else:
        canonical_consistency = (
            positions_match_intake
            and account_matches_intake
            and float(positions.get("IOT", {}).get("shares", -1)) == float(execution.get("shares_before", -2))
            and bool(post_weights)
        )
    check(canonical_consistency, "canonical_state_matches_execution_stage", f"status={execution_status}; applied={applied}; post_weight_rows={len(post_weights)}", results)

    action_header_ok = PRICE_AWARE_ACTION_PLAN.exists() and csv_header(PRICE_AWARE_ACTION_PLAN) == REQUIRED_ACTION_FIELDS
    action_rows = read_csv(PRICE_AWARE_ACTION_PLAN) if PRICE_AWARE_ACTION_PLAN.exists() else []
    check(action_header_ok, "price_aware_action_fields", f"columns={len(csv_header(PRICE_AWARE_ACTION_PLAN)) if PRICE_AWARE_ACTION_PLAN.exists() else 0}", results)
    iot_action = next((row for row in action_rows if row["ticker"] == "IOT"), {})
    guidance_ok = (
        iot_action.get("suggested_order_style") in {"limit_review", "wait_for_market_open_review", "staged_limit_review", "no_action"}
        and iot_action.get("reference_price", "") != ""
        and iot_action.get("reference_price_timestamp", "") != ""
        and float(iot_action.get("maximum_slippage_pct", -1)) > 0
    )
    if execution_status == "pending_fill":
        guidance_ok = guidance_ok and iot_action.get("action") == "pending_fill_confirmation" and "not a fill assumption" in iot_action.get("minimum_sell_price_or_condition", "")
    elif execution_status in {"filled", "partial_fill"} and not applied:
        guidance_ok = guidance_ok and iot_action.get("action") == "confirmed_fill_awaiting_reconciliation" and iot_action.get("suggested_order_style") == "no_action"
    check(guidance_ok, "iot_price_guidance_matches_execution_stage", f"action={iot_action.get('action')}; style={iot_action.get('suggested_order_style')}; slippage={iot_action.get('maximum_slippage_pct')}", results)
    check(all(row["suggested_order_style"] != "market_at_open" for row in action_rows), "market_at_open_not_default", "no market_at_open rows", results)
    check(all(row["human_confirmation_required"] == "yes" and row["automatic_action_allowed"] == "no" for row in action_rows), "manual_action_constants", f"rows={len(action_rows)}", results)
    c6_body = C6_BODY.read_text(encoding="utf-8") if C6_BODY.exists() else ""
    email_fields = (
        "shares under review",
        "target shares",
        "preferred condition",
        "maximum slippage",
        "order-style review",
        "resulting reference weight",
        f"fill confirmation status {execution_status}",
    )
    check(all(field in c6_body for field in email_fields), "future_weekly_email_fields_integrated", "C6 composition only; no delivery", results)
    policy_text = PRICE_POLICY.read_text(encoding="utf-8") if PRICE_POLICY.exists() else ""
    check("Limit orders may not execute" in policy_text, "limit_non_execution_risk_documented", "price policy", results)
    check("fill price is never inferred" in policy_text.lower(), "no_fill_price_invention_policy", "price policy", results)

    broker_imports, order_calls, archive_refs = code_boundary()
    check(not broker_imports, "no_broker_libraries_imported", ",".join(sorted(broker_imports)) or "none", results)
    check(not order_calls, "no_order_code_created", ",".join(sorted(order_calls)) or "none", results)
    check(not archive_refs, "archived_legacy_positions_unused", ",".join(sorted(archive_refs)) or "none", results)
    check(inhibit.get("active") is True and inhibit.get("allowed_pipeline") == "none", "d3_maintenance_inhibit_active", "allowed_pipeline=none", results)
    check(sha256(SMTP_CONFIG) == EXPECTED_SMTP_SHA256, "smtp_configuration_unchanged", sha256(SMTP_CONFIG), results)
    check(sha256(C6_STATUS) == EXPECTED_C6_STATUS_SHA256, "no_email_sent_during_c9b", sha256(C6_STATUS), results)
    c10_paths = [path for path in ROOT.rglob("*") if "phase5r_c10" in path.name.lower()]
    check(not c10_paths, "phase5r_c10_not_created", f"paths={len(c10_paths)}", results)

    failed = [row for row in results if row[1] == "FAIL"]
    status = "PASS" if not failed else "FAIL"
    lines = [
        "# Phase 5R-C9B Verification Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        f"## Result: `{status}`",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for name, result, detail in results:
        lines.append(f"| {name} | {result} | {detail.replace('|', '/')} |")
    lines.extend(
        [
            "",
            "## Current State",
            "",
            f"The IOT execution is `{execution_status}` and canonical-state application is `{'yes' if applied else 'no'}`. Reconciliation and post-execution outputs are required to match that stage; unknown fill values are never inferred.",
            "",
            "## Boundary",
            "",
            "C9B is a local manual intake and reconciliation framework. It does not connect to a broker, place or modify an order, infer a fill, send email, clear the D3 maintenance inhibit, read archived positions, or authorize automatic action.",
        ]
    )
    content = "\n".join(lines) + "\n"
    write_text(CONTROL_REPORT, content)
    write_text(RESEARCH_REPORT, content)
    append_c9b_log(
        Path(__file__).name,
        "verify_c9b_boundary",
        "complete" if not failed else "failed",
        [EXECUTION_FILE, CURRENT_POSITIONS, ACCOUNT_STATE, PRICE_AWARE_ACTION_PLAN, RECONCILIATION_REPORT],
        [CONTROL_REPORT, RESEARCH_REPORT],
        execution_id=execution.get("execution_id", ""),
        execution_status=execution_status,
        notes=f"verification_status={status}; failures={len(failed)}",
    )
    print(f"Phase 5R-C9B verification status={status}; failures={len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
