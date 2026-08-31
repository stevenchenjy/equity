from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import math
import subprocess
from datetime import datetime
from pathlib import Path

from phase5r_c9_common import (
    ACCOUNT_STATE,
    CASH_DEPLOYMENT_PLAN,
    C9_ALLOCATION_REPORT,
    C9_MEMO,
    C9_NEW_RECOMMENDATIONS,
    C9_POSITION_RECOMMENDATIONS,
    C9_SCORES,
    C9_INHIBIT,
    C9_RUN_LOG,
    CONTROL_DIR,
    CURRENT_POSITIONS,
    DYNAMIC_WEIGHTS,
    EXACT_ACTION_PLAN,
    MARKET_SNAPSHOT,
    PORTFOLIO_SUMMARY,
    RESEARCH_DIR,
    REVIEW_QUEUE,
    ROOT,
    TARGET_ALLOCATION_REPORT,
    WEEKLY_DECISION_SUMMARY,
    append_run_log,
    as_float,
    load_account_state,
    load_active_inhibit,
    load_market_rows,
    load_positions,
    read_csv,
    timestamp,
    write_text,
)


CONTROL_REPORT = CONTROL_DIR / "phase5r_c9_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c9_verification_report.md"
C7_LOG = CONTROL_DIR / "run_logs" / "phase5r_c7_weekly_pipeline_run_log.csv"
C6_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c6_delivery_status.csv"
C9_SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"
REQUIRED_OUTPUTS = [
    DYNAMIC_WEIGHTS,
    PORTFOLIO_SUMMARY,
    EXACT_ACTION_PLAN,
    CASH_DEPLOYMENT_PLAN,
    TARGET_ALLOCATION_REPORT,
    REVIEW_QUEUE,
    WEEKLY_DECISION_SUMMARY,
    C9_SCORES,
    C9_POSITION_RECOMMENDATIONS,
    C9_NEW_RECOMMENDATIONS,
    C9_MEMO,
    C9_ALLOCATION_REPORT,
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
FORBIDDEN_ORDER_CALLS = {"place_order", "submit_order", "send_order", "execute_order", "route_order"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the Phase 5R-C9 account and execution boundary.")
    parser.add_argument("--require-c7-no-send", action="store_true")
    return parser.parse_args()


def check(condition: bool, name: str, detail: str, results: list[tuple[str, str, str]]) -> None:
    results.append((name, "PASS" if condition else "FAIL", detail))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gitignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path.relative_to(ROOT))],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def code_boundary() -> tuple[set[str], set[str]]:
    broker_imports: set[str] = set()
    order_calls: set[str] = set()
    c9_files = sorted(C9_SCRIPT_DIR.glob("*phase5r_c9*.py")) + [C9_SCRIPT_DIR / "phase5r_c9_common.py"]
    for path in c9_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", 1)[0]
                    if root_name in FORBIDDEN_BROKER_MODULES:
                        broker_imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_name = node.module.split(".", 1)[0]
                if root_name in FORBIDDEN_BROKER_MODULES:
                    broker_imports.add(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_ORDER_CALLS:
                    order_calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ORDER_CALLS:
                    order_calls.add(node.func.attr)
    return broker_imports, order_calls


def latest_successful_send() -> str:
    if not C6_STATUS.exists():
        return ""
    successful = [row for row in read_csv(C6_STATUS) if row.get("sent") == "yes"]
    return successful[-1]["timestamp"] if successful else ""


def latest_c7_no_send_complete() -> tuple[bool, str]:
    if not C7_LOG.exists():
        return False, "C7 log missing"
    rows = read_csv(C7_LOG)
    if not rows:
        return False, "C7 log empty"
    latest_run_id = rows[-1]["run_id"]
    latest = [row for row in rows if row["run_id"] == latest_run_id]
    mode_ok = all(row["mode"] == "no_send" for row in latest)
    failed = [row for row in latest if row["status"] == "failed"]
    delivery = [row for row in latest if row["phase_step"] == "weekly_email_delivery"]
    delivery_ok = len(delivery) == 1 and delivery[0]["status"] == "skipped" and delivery[0]["email_send_attempted"] == "no"
    c9_steps = {row["phase_step"] for row in latest}
    required_steps = {"account_state", "account_aware_regeneration", "account_boundary_verification", "weekly_email_composition"}
    ok = mode_ok and not failed and delivery_ok and required_steps <= c9_steps
    return ok, f"run_id={latest_run_id}; rows={len(latest)}; failed={len(failed)}; delivery_skipped={delivery_ok}"


def main() -> int:
    args = parse_args()
    results: list[tuple[str, str, str]] = []
    account = load_account_state()
    inhibit = load_active_inhibit()
    positions = load_positions()
    market = load_market_rows([str(row["ticker"]) for row in positions] + ["SPY"])

    check(ACCOUNT_STATE.exists(), "account_state_exists", str(ACCOUNT_STATE.relative_to(ROOT)), results)
    check(gitignored(ACCOUNT_STATE), "account_state_gitignored", "git check-ignore", results)
    check((ACCOUNT_STATE.stat().st_mode & 0o077) == 0, "account_state_private_mode", oct(ACCOUNT_STATE.stat().st_mode & 0o777), results)
    total = as_float(account["account_total_value"], "account_total_value")
    check(total > 0, "account_total_current_and_positive", f"{total:.2f}", results)
    check(as_float(account["new_external_cash"], "new_external_cash") == 1500.0, "external_cash_confirmed", "1500.00", results)
    cash_available = as_float(account["cash_available"], "cash_available")
    check(cash_available >= 0, "cash_available_current_and_nonnegative", f"{cash_available:.2f}", results)
    check(inhibit.get("active") is True and inhibit.get("allowed_pipeline") == "none", "d3_maintenance_inhibit_active", "allowed_pipeline=none", results)

    missing_outputs = [path for path in REQUIRED_OUTPUTS if not path.exists() or path.stat().st_size == 0]
    check(not missing_outputs, "required_account_outputs_exist", f"missing={len(missing_outputs)}", results)

    weights = read_csv(DYNAMIC_WEIGHTS)
    weight_by_ticker = {row["ticker"]: row for row in weights}
    check(set(weight_by_ticker) == {str(row["ticker"]) for row in positions}, "dynamic_weight_ticker_match", ",".join(sorted(weight_by_ticker)), results)
    formula_ok = True
    provenance_ok = True
    for position in positions:
        ticker = str(position["ticker"])
        row = weight_by_ticker[ticker]
        expected = as_float(position["shares"], f"{ticker}.shares") * as_float(market[ticker]["last_price"], f"{ticker}.price") / total * 100.0
        formula_ok = formula_ok and math.isclose(expected, float(row["current_weight_pct"]), abs_tol=0.0001)
        provenance_ok = provenance_ok and row["price_quality_label"] == "ok" and row["weight_formula"] == "current_shares*latest_price/account_total_value*100"
    check(formula_ok, "weights_recalculated_from_shares_price_total", "all current positions", results)
    check(provenance_ok, "weight_provenance_complete", "B2 quality=ok and formula recorded", results)
    check(
        all(math.isclose(float(row["account_total_value"]), total, abs_tol=0.01) for row in weights),
        "stale_denominator_not_current",
        f"all dynamic rows use current account total {total:.2f}",
        results,
    )

    iot = weight_by_ticker.get("IOT", {})
    rbrk = weight_by_ticker.get("RBRK", {})
    hard_cap = as_float(account["single_stock_hard_cap_pct"], "single_stock_hard_cap_pct")
    default_cap = as_float(account["single_stock_default_cap_pct"], "single_stock_default_cap_pct")

    def expected_concentration(weight: float) -> str:
        if weight > hard_cap + 1e-9:
            return "above_hard_cap"
        if weight > default_cap + 1e-9:
            return "above_default_cap"
        return "within_default_cap"

    iot_weight = float(iot.get("current_weight_pct", -1))
    rbrk_weight = float(rbrk.get("current_weight_pct", -1))
    check(iot.get("concentration_status") == expected_concentration(iot_weight), "iot_dynamic_concentration", f"weight={iot.get('current_weight_pct')}", results)
    check(rbrk.get("concentration_status") == expected_concentration(rbrk_weight), "rbrk_dynamic_concentration", f"weight={rbrk.get('current_weight_pct')}", results)

    summary_rows = read_csv(PORTFOLIO_SUMMARY)
    summary = summary_rows[0] if len(summary_rows) == 1 else {}
    dynamic_sleeve = sum(float(row["current_weight_pct"]) for row in weights)
    check(
        bool(summary) and math.isclose(dynamic_sleeve, float(summary["current_active_stock_weight_pct"]), abs_tol=0.0001),
        "combined_active_sleeve_dynamic",
        f"weight={dynamic_sleeve:.4f}",
        results,
    )
    check(dynamic_sleeve <= 30.0 and summary.get("active_stock_status") != "above_hard_cap", "active_sleeve_not_above_30", summary.get("active_stock_status", "missing"), results)
    check(summary.get("reconciliation_status") == "estimated_price_drift_within_tolerance", "cash_reconciliation_documented", f"difference={summary.get('reconciliation_difference')}", results)

    actions = {row["ticker"]: row for row in read_csv(EXACT_ACTION_PLAN)}
    iot_action = actions.get("IOT", {})
    rbrk_action = actions.get("RBRK", {})
    if iot:
        expected_iot_change = max(0, math.ceil(float(iot["current_shares"]) - math.floor(total * hard_cap / 100.0 / float(iot["latest_price"]) + 1e-12) - 1e-9))
    else:
        expected_iot_change = -1
    iot_action_ok = False
    if iot_weight > hard_cap + 1e-9:
        iot_action_ok = (
            iot_action.get("recommended_action") == "trim_specific_shares_review"
            and int(iot_action.get("whole_shares_to_change", -1)) == expected_iot_change
            and float(iot_action.get("resulting_weight_pct", 99)) <= hard_cap + 1e-9
        )
    else:
        iot_action_ok = (
            iot_action.get("recommended_action") == "hold"
            and int(iot_action.get("whole_shares_to_change", -1)) == 0
        )
    check(
        iot_action_ok,
        "iot_whole_share_scenario_dynamic",
        f"change={iot_action.get('whole_shares_to_change')}; expected={expected_iot_change}",
        results,
    )
    rbrk_action_ok = (
        rbrk_action.get("recommended_action") == "trim_specific_shares_review"
        if rbrk_weight > hard_cap + 1e-9
        else rbrk_action.get("recommended_action") == "hold" and int(rbrk_action.get("whole_shares_to_change", -1)) == 0
    )
    check(
        rbrk_action_ok,
        "rbrk_dynamic_action",
        f"action={rbrk_action.get('recommended_action')}",
        results,
    )
    check(
        all(row.get("human_confirmation_required") == "yes" and row.get("automatic_action_allowed") == "no" for row in actions.values()),
        "manual_action_boundary",
        "all exact actions require human confirmation",
        results,
    )

    allocation = read_csv(TARGET_ALLOCATION_REPORT)
    roles = {row["asset_role"] for row in allocation}
    check(roles == {"core_allocation", "active_stock", "cash"}, "core_active_cash_separated", ",".join(sorted(roles)), results)
    cash_plans = read_csv(CASH_DEPLOYMENT_PLAN)
    tranche_rows = [row for row in cash_plans if row["plan_id"] == "three_tranche_core_plan"]
    check(
        len(tranche_rows) == 3
        and all(float(row["planned_amount"]) == 500.0 for row in tranche_rows)
        and all(row["status"] == "blocked_maintenance" for row in tranche_rows),
        "three_tranche_core_plan_conditional",
        "three $500 tranches; maintenance blocked",
        results,
    )

    new_rows = read_csv(C9_NEW_RECOMMENDATIONS)
    eligible_individual = [row for row in new_rows if row["asset_role"] == "individual_stock_candidate" and row["eligibility_label"] == "eligible_buy_review"]
    incomplete_safe = all(
        row["expected_upside_pass"] == "no" and row["reward_to_risk_pass"] == "no" and row["recommended_action"] == "watch_only"
        for row in new_rows
        if row["asset_role"] == "individual_stock_candidate"
    )
    check(not eligible_individual and incomplete_safe, "no_incomplete_individual_purchase_review", f"eligible={len(eligible_individual)}", results)
    check(any(row["asset_role"] == "core_allocation_candidate" and row["ticker"] == "SPY" for row in new_rows), "broad_market_core_separate", "SPY core role present", results)

    broker_imports, order_calls = code_boundary()
    check(not broker_imports, "no_broker_libraries_imported", ",".join(sorted(broker_imports)) or "none", results)
    check(not order_calls, "no_order_code_created", ",".join(sorted(order_calls)) or "none", results)

    latest_send = latest_successful_send()
    account_updated = datetime.fromisoformat(str(account["last_updated"]))
    if latest_send:
        send_time = datetime.fromisoformat(latest_send.replace("Z", "+00:00"))
        no_c9_send = send_time < account_updated
    else:
        no_c9_send = True
    check(no_c9_send, "no_email_sent_during_c9", latest_send or "none", results)

    if args.require_c7_no_send:
        c7_ok, c7_detail = latest_c7_no_send_complete()
        check(c7_ok, "c7_no_send_complete", c7_detail, results)
    else:
        results.append(("c7_no_send_complete", "PENDING", "final verification runs after C7 --no-send"))

    failed = [row for row in results if row[1] == "FAIL"]
    status = "PASS" if not failed and args.require_c7_no_send else "PASS_PRE_C7" if not failed else "FAIL"
    generated = timestamp()
    lines = [
        "# Phase 5R-C9 Verification Report",
        "",
        f"Generated: `{generated}`",
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
            "## Protected Inputs",
            "",
            f"- Current positions SHA-256: `{sha256(CURRENT_POSITIONS)}`.",
            f"- Account state SHA-256: `{sha256(ACCOUNT_STATE)}`.",
            f"- Maintenance inhibit SHA-256: `{sha256(C9_INHIBIT)}`.",
            "",
            "## Boundary",
            "",
            "C9 uses current shares, canonical B2 public prices, and the confirmed account total. Stored position percentages are emitted only as historical comparison values. No broker, order path, automatic action, archived holding input, credential read, or email send is part of C9.",
        ]
    )
    content = "\n".join(lines) + "\n"
    write_text(CONTROL_REPORT, content)
    write_text(RESEARCH_REPORT, content)
    append_run_log(
        Path(__file__).name,
        "verify_account_boundary",
        "complete" if not failed else "failed",
        [ACCOUNT_STATE, CURRENT_POSITIONS, MARKET_SNAPSHOT, DYNAMIC_WEIGHTS, EXACT_ACTION_PLAN, C9_INHIBIT],
        [CONTROL_REPORT, RESEARCH_REPORT],
        position_count=len(weights),
        notes=f"verification_status={status}; failures={len(failed)}",
        c7_mode="no_send_verified" if args.require_c7_no_send and not failed else "pending_no_send",
    )
    print(f"Phase 5R-C9 verification status={status}; failures={len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
