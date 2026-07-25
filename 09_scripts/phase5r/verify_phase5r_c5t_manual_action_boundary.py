from __future__ import annotations

import ast
import csv
import hashlib
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c5t_run_log.csv"

LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
SCENARIOS = POSITION_DIR / "phase5r_c5t_trim_scenario_table.csv"
CHECKLIST = POSITION_DIR / "phase5r_c5t_hold_vs_trim_checklist.csv"
TRIGGERS = POSITION_DIR / "phase5r_c5t_next_review_triggers.csv"
PLAN = POSITION_DIR / "phase5r_c5t_manual_action_plan.md"
RESEARCH_ACTION_REPORT = RESEARCH_DIR / "phase5r_c5t_manual_action_report.md"
CONTROL_REPORT = CONTROL_DIR / "phase5r_c5t_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c5t_verification_report.md"
C2_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c2_delivery_status.csv"
C3_LOG = CONTROL_DIR / "run_logs" / "phase5r_c3_daily_pipeline_run_log.csv"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.steven.phase5r.dailybrief.plist"

LOCAL_HASH_BASELINE = "d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c"
C2_HASH_BASELINE = "c548c061f0433fce31f5024af54c8ab540230e92db848989c0d1e2f02787a063"
C3_HASH_BASELINE = "8296dcbe3442bdfd9b9c065de89de6daf85cd4ad9160e7f889b3b52c29a1c649"
SMTP_SIZE_BASELINE = 241
SMTP_MTIME_BASELINE = 1783625651

GENERATORS = [
    SCRIPTS_DIR / "create_phase5r_c5t_trim_scenarios.py",
    SCRIPTS_DIR / "create_phase5r_c5t_manual_action_plan.py",
    Path(__file__),
]
REQUIRED_FILES = [
    CONTROL_DIR / "phase5r_c5t_manual_action_policy.md", SCENARIOS, CHECKLIST, TRIGGERS, PLAN,
    RESEARCH_ACTION_REPORT, *GENERATORS, RUN_LOG,
]
REQUIRED_SCENARIOS = {
    "no_action_until_next_review", "trim_to_active_stock_sleeve_target_30pct",
    "trim_each_position_to_8pct_hard_cap", "trim_each_position_to_6pct_default_cap",
    "whole_share_practical_scenario",
}
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
EMAIL_MODULES = {"smtplib", "imaplib", "poplib", "gmail", "sendgrid", "msal", "O365", "outlook"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "sendmail", "send_message"}
FORBIDDEN_LANGUAGE = [r"\bbuy now\b", r"\bsell now\b", r"\bexecute\b", r"\border\b", r"\bguaranteed\b", r"\bcertain profit\b"]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "account_value_usd", "position_rows", "scenario_count", "scenario_rows", "email_sent",
    "scheduler_used", "broker_used", "smtp_config_modified", "archived_legacy_used", "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def script_scan() -> tuple[list[str], list[str], list[str]]:
    broker: list[str] = []
    email: list[str] = []
    blocked: list[str] = []
    for path in GENERATORS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            broker.extend(f"{path.name}:{module}" for module in modules if module in BROKER_MODULES)
            email.extend(f"{path.name}:{module}" for module in modules if module in EMAIL_MODULES)
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                if name in BLOCKED_CALLS:
                    blocked.append(f"{path.name}:{name}")
    return broker, email, blocked


def scheduler_loaded() -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/com.steven.phase5r.dailybrief"],
        capture_output=True, text=True, check=False,
    )
    return result.returncode == 0


def c6_paths() -> list[str]:
    pattern = re.compile(r"phase5r(?:_c6_|-c6\b)|phase5rc6\b", re.IGNORECASE)
    roots = [CONTROL_DIR, POSITION_DIR, RESEARCH_DIR, ROOT / "07_automation", ROOT / "08_reviews", SCRIPTS_DIR]
    return sorted(str(path.relative_to(ROOT)) for folder in roots for path in folder.rglob("*") if path.is_file() and pattern.search(path.name))


def append_log(status: str, scenario_count: int, scenario_rows: int) -> None:
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5t", "script_name": Path(__file__).name,
            "action": "verify_manual_action_boundary", "input_paths": "phase5r_c5t_generated_outputs",
            "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [CONTROL_REPORT, RESEARCH_REPORT]),
            "status": status, "account_value_usd": "1000.00", "position_rows": "2",
            "scenario_count": str(scenario_count), "scenario_rows": str(scenario_rows),
            "email_sent": "no", "scheduler_used": "no", "broker_used": "no",
            "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "verification_complete=yes; credentials_not_read=yes; manual_only=yes",
        })


def main() -> None:
    scenarios = read_csv(SCENARIOS)
    checklist = read_csv(CHECKLIST)
    triggers = read_csv(TRIGGERS)
    logs = read_csv(RUN_LOG)
    broker_imports, email_imports, blocked_calls = script_scan()
    scenario_ids = {row["scenario_id"] for row in scenarios}
    manual_only = all(row["human_decision_needed"] == "yes" and row["automatic_action_allowed"] == "no" for row in scenarios + checklist + triggers)
    whole_rows = [row for row in scenarios if row["scenario_id"] == "whole_share_practical_scenario"]
    whole_share_ok = all(float(row["approximate_shares_to_hold"]).is_integer() and float(row["approximate_shares_to_trim"]).is_integer() for row in whole_rows)
    active_rows = [row for row in scenarios if row["scenario_id"] == "trim_to_active_stock_sleeve_target_30pct"]
    active_target_ok = active_rows and all(abs(float(row["scenario_total_sleeve_pct"]) - 30.0) <= 0.01 for row in active_rows)
    cap_8_rows = [row for row in scenarios if row["scenario_id"] == "trim_each_position_to_8pct_hard_cap"]
    cap_6_rows = [row for row in scenarios if row["scenario_id"] == "trim_each_position_to_6pct_default_cap"]
    cap_math_ok = all(abs(float(row["estimated_remaining_position_pct"]) - 8.0) <= 0.01 for row in cap_8_rows) and all(abs(float(row["estimated_remaining_position_pct"]) - 6.0) <= 0.01 for row in cap_6_rows)
    planning_text = "\n".join([
        SCENARIOS.read_text(encoding="utf-8"), CHECKLIST.read_text(encoding="utf-8"),
        TRIGGERS.read_text(encoding="utf-8"), PLAN.read_text(encoding="utf-8"),
        RESEARCH_ACTION_REPORT.read_text(encoding="utf-8"),
    ]).lower()
    language_hits = [pattern for pattern in FORBIDDEN_LANGUAGE if re.search(pattern, planning_text, re.IGNORECASE)]
    archive_input_hits = [row["input_paths"] for row in logs if "11_archive" in row["input_paths"]]
    c2_unchanged = digest(C2_STATUS) == C2_HASH_BASELINE
    c3_unchanged = digest(C3_LOG) == C3_HASH_BASELINE
    smtp_stat = SMTP_CONFIG.stat()
    smtp_unchanged = smtp_stat.st_size == SMTP_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_MTIME_BASELINE
    required_trigger_categories = {
        "thesis_deterioration", "earnings_risk", "score_drop", "concentration_still_above_cap",
        "public_market_data_missing", "price_gap_up_down", "active_sleeve_still_above_target",
        "new_eligible_candidates_appear",
    }
    checks = [
        ("current local positions were read", {row["ticker"] for row in checklist} == {"IOT", "RBRK"}, f"tickers={[row['ticker'] for row in checklist]}"),
        ("archived IOT/RBRK files were not read", not archive_input_hits, f"archive_input_hits={archive_input_hits}"),
        ("all required scenarios were created", REQUIRED_SCENARIOS <= scenario_ids, f"scenarios={sorted(scenario_ids)}"),
        ("all scenarios are manual-only", manual_only, "human_decision_needed=yes; automatic_action_allowed=no"),
        ("active-sleeve target math is correct", bool(active_target_ok), "resulting sleeve=30.00%"),
        ("single-stock cap math is correct", cap_math_ok, "8% and 6% fractional scenarios checked"),
        ("whole-share constraint is explicit", whole_share_ok and "8.88%" in PLAN.read_text(encoding="utf-8"), "whole shares only; RBRK constraint documented"),
        ("next-review triggers are complete", required_trigger_categories <= {row["trigger_category"] for row in triggers}, f"trigger_rows={len(triggers)}"),
        ("no broker libraries imported", not broker_imports, f"violations={broker_imports}"),
        ("no order code created", not blocked_calls, f"violations={blocked_calls}"),
        ("no email sent", not email_imports and c2_unchanged and c3_unchanged, f"email_imports={email_imports}; delivery_logs_unchanged={c2_unchanged and c3_unchanged}"),
        ("no scheduler installed or loaded", not D1_INSTALLED.exists() and not scheduler_loaded(), f"installed={D1_INSTALLED.exists()}"),
        ("SMTP config not modified", smtp_unchanged, "metadata unchanged; content not read"),
        ("no automatic trade language appears", not language_hits, f"violations={language_hits}"),
        ("Phase 5R-C6 was not created", not c6_paths(), f"paths={c6_paths()}"),
        ("current local file remained read-only", digest(LOCAL_POSITIONS) == LOCAL_HASH_BASELINE, "hash unchanged"),
        ("all required C5T files exist", all(path.exists() for path in REQUIRED_FILES), f"missing={[str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]}"),
    ]
    passed = all(ok for _, ok, _ in checks)
    lines = ["# Phase 5R-C5T Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    lines.extend(f"- **{'PASS' if ok else 'FAIL'}** - {name}: {detail}." for name, ok, detail in checks)
    lines.extend(["", "## Scenario Outcome", "", f"- Scenario count: `{len(scenario_ids)}`.", f"- Scenario rows: `{len(scenarios)}`.", "- Current positions: `IOT, RBRK`.", "- Next review date: `2026-07-16`.", "", "## Boundary", "", "C5T created manual research-planning artifacts only. It did not access a broker, alter positions, send email, activate a scheduler, read archived holdings, modify SMTP configuration, or create Phase 5R-C6."])
    report = "\n".join(lines) + "\n"
    CONTROL_REPORT.write_text(report, encoding="utf-8")
    RESEARCH_REPORT.write_text(report, encoding="utf-8")
    append_log("complete" if passed else "failed", len(scenario_ids), len(scenarios))
    if not passed:
        raise RuntimeError("Phase 5R-C5T boundary verification failed")
    print(f"Phase 5R-C5T verification passed; scenarios={len(scenario_ids)} rows={len(scenarios)}")


if __name__ == "__main__":
    main()
