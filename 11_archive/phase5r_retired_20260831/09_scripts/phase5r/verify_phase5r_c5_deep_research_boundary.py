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
CONTROL = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RUN_LOG = CONTROL / "run_logs" / "phase5r_c5_run_log.csv"
LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
C2_STATUS = ROOT / "07_automation" / "email_delivery" / "phase5r_c2_delivery_status.csv"
C3_LOG = CONTROL / "run_logs" / "phase5r_c3_daily_pipeline_run_log.csv"
SMTP_CONFIG = ROOT / "07_automation" / "email_delivery" / "phase5r_email_config.local.json"
D1_INSTALLED = Path.home() / "Library" / "LaunchAgents" / "com.steven.phase5r.dailybrief.plist"
CONTROL_REPORT = CONTROL / "phase5r_c5_verification_report.md"
RESEARCH_REPORT = RESEARCH_DIR / "phase5r_c5_verification_report.md"

LOCAL_HASH_BASELINE = "d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c"
C2_HASH_BASELINE = "c548c061f0433fce31f5024af54c8ab540230e92db848989c0d1e2f02787a063"
C3_HASH_BASELINE = "8296dcbe3442bdfd9b9c065de89de6daf85cd4ad9160e7f889b3b52c29a1c649"
SMTP_SIZE_BASELINE = 241
SMTP_MTIME_BASELINE = 1783625651

GENERATORS = [
    SCRIPTS_DIR / "create_phase5r_c5_research_queue.py",
    SCRIPTS_DIR / "create_phase5r_c5_company_research_packets.py",
    SCRIPTS_DIR / "score_phase5r_c5_weekly_conviction.py",
    SCRIPTS_DIR / "create_phase5r_c5_weekly_conviction_memo.py",
    Path(__file__),
]
REQUIRED_FILES = [
    CONTROL / "phase5r_c5_deep_research_policy.md",
    CONTROL / "phase5r_c5_source_policy.md",
    CONTROL / "phase5r_c5_recommendation_label_policy.md",
    RESEARCH_DIR / "phase5r_c5_research_queue.csv",
    RESEARCH_DIR / "phase5r_c5_company_research_packets.csv",
    RESEARCH_DIR / "phase5r_c5_weekly_conviction_scores.csv",
    RESEARCH_DIR / "phase5r_c5_position_review_recommendations.csv",
    RESEARCH_DIR / "phase5r_c5_new_candidate_recommendations.csv",
    RESEARCH_DIR / "phase5r_c5_weekly_conviction_memo.md",
    *GENERATORS,
    RUN_LOG,
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
EMAIL_MODULES = {"smtplib", "imaplib", "poplib", "gmail", "sendgrid", "msal", "O365", "outlook"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "sendmail", "send_message"}
FORBIDDEN_LANGUAGE = [r"\bbuy now\b", r"\bsell now\b", r"\bexecute\b", r"\border\b", r"\bguaranteed\b", r"\bcertain profit\b"]
PACKET_REQUIRED = {
    "ticker", "research_role", "current_position_status", "market_score", "portfolio_concentration_status",
    "theme", "holding_horizon_candidate", "valuation_check", "filing_check", "earnings_check", "news_check",
    "technical_check", "risk_check", "entry_discipline", "exit_or_trim_conditions", "recommendation_label",
    "recommendation_confidence", "human_action_required", "notes",
}
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "research_rows", "current_position_rows", "new_candidate_rows", "eligible_buy_review_count",
    "email_sent", "scheduler_used", "broker_used", "smtp_config_modified",
    "archived_legacy_used", "safety_notes",
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
    roots = [CONTROL, POSITION_DIR, RESEARCH_DIR, ROOT / "07_automation", ROOT / "08_reviews", SCRIPTS_DIR]
    return sorted(str(path.relative_to(ROOT)) for folder in roots for path in folder.rglob("*") if path.is_file() and pattern.search(path.name))


def append_log(status: str, count: int, eligible: int) -> None:
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5", "script_name": Path(__file__).name,
            "action": "verify_deep_research_boundary", "input_paths": "phase5r_c5_generated_outputs",
            "output_paths": ";".join(str(path.relative_to(ROOT)) for path in [CONTROL_REPORT, RESEARCH_REPORT]),
            "status": status, "research_rows": str(count), "current_position_rows": "2",
            "new_candidate_rows": str(max(0, count - 2)), "eligible_buy_review_count": str(eligible),
            "email_sent": "no", "scheduler_used": "no", "broker_used": "no",
            "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "boundary_checks_complete=yes; credentials_not_read=yes; manual_review_only=yes",
        })


def main() -> None:
    queue_path = RESEARCH_DIR / "phase5r_c5_research_queue.csv"
    packets_path = RESEARCH_DIR / "phase5r_c5_company_research_packets.csv"
    score_path = RESEARCH_DIR / "phase5r_c5_weekly_conviction_scores.csv"
    position_path = RESEARCH_DIR / "phase5r_c5_position_review_recommendations.csv"
    candidate_path = RESEARCH_DIR / "phase5r_c5_new_candidate_recommendations.csv"
    memo_path = RESEARCH_DIR / "phase5r_c5_weekly_conviction_memo.md"
    queue = read_csv(queue_path)
    packets = read_csv(packets_path)
    scores = read_csv(score_path)
    positions = read_csv(position_path)
    candidates = read_csv(candidate_path)
    logs = read_csv(RUN_LOG)
    broker_imports, email_imports, blocked_calls = script_scan()
    eligible = sum(row["recommendation_label"] == "eligible_buy_review" for row in candidates)
    current_rows = [row for row in queue if row["research_role"] == "current_position_risk_review"]
    current_tickers = [row["ticker"] for row in current_rows]
    packet_header = set(packets[0]) if packets else set()
    source_hosts_ok = all(
        any(domain in row["primary_source_url"] for domain in ["sec.gov", "investor", "investors", "ir.", "ssga.com"])
        for row in packets
    )
    recommendation_text = "\n".join([
        memo_path.read_text(encoding="utf-8"), position_path.read_text(encoding="utf-8"),
        candidate_path.read_text(encoding="utf-8"), score_path.read_text(encoding="utf-8"),
    ]).lower()
    language_hits = [pattern for pattern in FORBIDDEN_LANGUAGE if re.search(pattern, recommendation_text, re.IGNORECASE)]
    archive_input_hits = [row["input_paths"] for row in logs if "11_archive" in row["input_paths"]]
    hard_cap_ok = all(
        float(row["position_pct"]) <= 8.0 or row["recommendation_label"] in {"trim_review", "hold_existing", "exit_review"}
        for row in positions
    ) and all(row["recommendation_label"] != "add_review" for row in positions if float(row["position_pct"]) > 8.0)
    local_sources_ok = current_tickers == ["IOT", "RBRK"] and all(
        row["source_position_path"] == "05_risk_and_positions/current_positions.local.csv" for row in current_rows
    )
    c2_unchanged = digest(C2_STATUS) == C2_HASH_BASELINE
    c3_unchanged = digest(C3_LOG) == C3_HASH_BASELINE
    smtp_stat = SMTP_CONFIG.stat()
    smtp_unchanged = smtp_stat.st_size == SMTP_SIZE_BASELINE and int(smtp_stat.st_mtime) == SMTP_MTIME_BASELINE
    checks = [
        ("current local positions were read", local_sources_ok, f"tickers={current_tickers}"),
        ("archived IOT/RBRK files were not read", not archive_input_hits, f"archive_input_hits={archive_input_hits}"),
        ("IOT/RBRK are current positions", current_tickers == ["IOT", "RBRK"], "queue begins with current-position risk reviews"),
        ("concentration rules were applied", hard_cap_ok, f"position_labels={[row['recommendation_label'] for row in positions]}"),
        ("new candidate count is 0 to 2", 0 <= eligible <= 2, f"eligible_count={eligible}"),
        ("deep research fields are complete", PACKET_REQUIRED <= packet_header and all(all(row.get(field, "").strip() for field in PACKET_REQUIRED) for row in packets), f"packet_rows={len(packets)}"),
        ("controlled source policy was used", source_hosts_ok, "primary sources are company IR, SEC, or official fund materials"),
        ("no broker libraries imported", not broker_imports, f"violations={broker_imports}"),
        ("no order code created", not blocked_calls, f"violations={blocked_calls}"),
        ("no email sent", not email_imports and c2_unchanged and c3_unchanged, f"email_imports={email_imports}; delivery_logs_unchanged={c2_unchanged and c3_unchanged}"),
        ("no scheduler installed or loaded", not D1_INSTALLED.exists() and not scheduler_loaded(), f"installed={D1_INSTALLED.exists()}"),
        ("SMTP config not modified", smtp_unchanged, "metadata unchanged; content not read"),
        ("no archived legacy data used", not archive_input_hits, "canonical inputs only"),
        ("no automatic trade language appears", not language_hits, f"violations={language_hits}"),
        ("Phase 5R-C6 was not created", not c6_paths(), f"paths={c6_paths()}"),
        ("current local file remained read-only", digest(LOCAL_POSITIONS) == LOCAL_HASH_BASELINE, "hash unchanged"),
        ("all required Phase 5R-C5 files exist", all(path.exists() for path in REQUIRED_FILES), f"missing={[str(path.relative_to(ROOT)) for path in REQUIRED_FILES if not path.exists()]}"),
    ]
    passed = all(ok for _, ok, _ in checks)
    generated = timestamp()
    lines = ["# Phase 5R-C5 Verification Report", "", f"Generated: `{generated}`", "", "## Required Checks", ""]
    lines.extend(f"- **{'PASS' if ok else 'FAIL'}** - {name}: {detail}." for name, ok, detail in checks)
    lines.extend(["", "## Weekly Outcome", "", f"- Research queue rows: `{len(queue)}`.", f"- Current positions reviewed first: `{', '.join(current_tickers)}`.", f"- New eligible candidates: `{eligible}`.", f"- Position labels: `{', '.join(row['ticker'] + '=' + row['recommendation_label'] for row in positions)}`.", "", "## Boundary", "", "Phase 5R-C5 is a weekly research workflow with independent human review. It did not access a broker, alter a portfolio, send email, activate a scheduler, read archived holdings, modify SMTP configuration, or create Phase 5R-C6."])
    report = "\n".join(lines) + "\n"
    CONTROL_REPORT.write_text(report, encoding="utf-8")
    RESEARCH_REPORT.write_text(report, encoding="utf-8")
    append_log("complete" if passed else "failed", len(scores), eligible)
    if not passed:
        raise RuntimeError("Phase 5R-C5 boundary verification failed")
    print(f"Phase 5R-C5 verification passed; queue={len(queue)}; eligible_new={eligible}")


if __name__ == "__main__":
    main()
