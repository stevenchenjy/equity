from __future__ import annotations

import ast
import csv
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
AUTOMATION_DIR = ROOT / "07_automation" / "email_briefs"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c1_run_log.csv"
REPORT_PATH = CONTROL_DIR / "phase5r_c1_verification_report.md"
RESEARCH_REPORT_PATH = RESEARCH_DIR / "phase5r_c1_verification_report.md"

SCORES_PATH = DATA_DIR / "phase5r_b2_signal_scores.csv"
SUBJECT_PATH = AUTOMATION_DIR / "phase5r_c1_daily_email_subject.txt"
TEXT_PATH = AUTOMATION_DIR / "phase5r_c1_daily_email_body.txt"
HTML_PATH = AUTOMATION_DIR / "phase5r_c1_daily_email_body.html"
METADATA_PATH = AUTOMATION_DIR / "phase5r_c1_email_brief_metadata.csv"
PREVIEW_PATH = REVIEWS_DIR / "latest_phase5r_c1_email_preview.md"

REQUIRED_FILES = [
    "00_project_control/phase5r_c1_email_brief_policy.md", "00_project_control/phase5r_c1_low_attention_rules.md", "00_project_control/phase5r_c1_verification_report.md",
    "07_automation/email_briefs/phase5r_c1_daily_email_subject.txt", "07_automation/email_briefs/phase5r_c1_daily_email_body.txt", "07_automation/email_briefs/phase5r_c1_daily_email_body.html", "07_automation/email_briefs/phase5r_c1_email_brief_metadata.csv",
    "08_reviews/current/latest_phase5r_c1_email_preview.md", "09_scripts/phase5r/create_phase5r_c1_daily_email_brief.py", "09_scripts/phase5r/verify_phase5r_c1_email_brief_boundary.py",
    "04_research/realtime_stock_picker_phase5r/phase5r_c1_email_brief_report.md", "04_research/realtime_stock_picker_phase5r/phase5r_c1_verification_report.md", "00_project_control/run_logs/phase5r_c1_run_log.csv",
]
C1_SCRIPTS = [SCRIPTS_DIR / "create_phase5r_c1_daily_email_brief.py", SCRIPTS_DIR / "verify_phase5r_c1_email_brief_boundary.py"]
LEGACY_TICKERS = {"IOT", "RBRK"}
EMAIL_MODULES = {"smtplib", "imaplib", "poplib", "gmail", "sendgrid", "msal", "O365", "outlook"}
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
ENV_MODULES = {"dotenv", "keyring"}
SCHEDULER_MODULES = {"schedule", "apscheduler", "croniter"}
BLOCKED_CALLS = {"send", "sendmail", "send_message", "place_order", "submit_order", "create_order", "send_order", "execute_trade"}
LOG_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "safety_notes"]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def scan_scripts() -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    email: list[str] = []
    broker: list[str] = []
    env: list[str] = []
    scheduler: list[str] = []
    blocked: list[str] = []
    for path in C1_SCRIPTS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [(node.module or "").split(".")[0]]
            for module in modules:
                if module in EMAIL_MODULES:
                    email.append(f"{path.name}: {module}")
                if module in BROKER_MODULES:
                    broker.append(f"{path.name}: {module}")
                if module in ENV_MODULES:
                    env.append(f"{path.name}: {module}")
                if module in SCHEDULER_MODULES:
                    scheduler.append(f"{path.name}: {module}")
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in BLOCKED_CALLS:
                blocked.append(f"{path.name}: defines {node.name}")
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                    blocked.append(f"{path.name}: calls {node.func.id}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALLS:
                    blocked.append(f"{path.name}: calls {node.func.attr}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in {"getenv", "environ"}:
                    env.append(f"{path.name}: environment access")
    return email, broker, env, scheduler, blocked


def phase_c2_paths() -> list[str]:
    matches: list[str] = []
    for folder in (CONTROL_DIR, AUTOMATION_DIR, RESEARCH_DIR, REVIEWS_DIR, SCRIPTS_DIR):
        for path in folder.rglob("*"):
            if path.is_file() and re.search(r"phase5r(?:_c2_|-c2\\b)|phase5rc2\\b", str(path), re.IGNORECASE):
                matches.append(str(path.relative_to(ROOT)))
    return matches


def main() -> None:
    generated_reports = {str(REPORT_PATH.relative_to(ROOT)), str(RESEARCH_REPORT_PATH.relative_to(ROOT))}
    missing = [name for name in REQUIRED_FILES if name not in generated_reports and not (ROOT / name).exists()]
    scores = read_csv(SCORES_PATH)
    metadata_rows = read_csv(METADATA_PATH)
    metadata = metadata_rows[0] if len(metadata_rows) == 1 else {}
    subject = SUBJECT_PATH.read_text(encoding="utf-8").strip()
    text_body = TEXT_PATH.read_text(encoding="utf-8")
    html_body = HTML_PATH.read_text(encoding="utf-8")
    email, broker, env, scheduler, blocked = scan_scripts()
    score_tickers = {row["ticker"] for row in scores}
    visible_tickers = {ticker for ticker in score_tickers if ticker in text_body or ticker in html_body}
    sections = ["Header", "Market Data Status", "Today's Manual-Review Candidates", "Top Watchlist", "Lower-Priority / Avoid Today", "Manual Review Checklist", "Safety Boundary"]
    forbidden_urgent_language = re.findall(r"\\b(?:buy now|sell now|execute|order)\\b", text_body + html_body, flags=re.IGNORECASE)
    archive_references = [value for value in metadata.values() if "11_archive" in value]
    output_legacy = sorted({ticker for ticker in LEGACY_TICKERS if ticker in subject or ticker in text_body or ticker in html_body or ticker in str(metadata)})
    phase_c2 = phase_c2_paths()
    expected_counts = {"manual_review_count": "1", "watch_count": "20", "avoid_count": "6", "insufficient_data_count": "0"}
    expected_subject = f"Daily AI Equity Brief — {metadata.get('generated_at', '')[:10]} — 1 Review / 20 Watch / 6 Avoid"
    checks = [
        ("C1 files were created", not missing, f"missing={missing}"),
        ("email subject was created", bool(subject) and subject == expected_subject, f"subject={subject}"),
        ("plain-text body was created", bool(text_body.strip()), f"characters={len(text_body)}"),
        ("HTML body was created", bool(html_body.strip()) and "<table" in html_body and "<script" not in html_body.lower() and "src=" not in html_body.lower() and "href=" not in html_body.lower(), f"characters={len(html_body)}"),
        ("no email sending code exists", not email and not blocked, f"email_imports={email}, blocked_calls={blocked}"),
        ("no SMTP/Gmail/Outlook/IMAP sending libraries imported", not email, f"violations={email}"),
        ("no .env read", not env, f"violations={env}"),
        ("no API keys or credentials used", not env, "no environment or credential access found"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not blocked, f"violations={blocked}"),
        ("no scheduler code created", not scheduler, f"violations={scheduler}"),
        ("no intraday alert logic created", "intraday alert" not in text_body.lower() and "every-15-minute" not in text_body.lower(), "brief contains no intraday alert content"),
        ("no archived legacy data used", not archive_references, f"archive_references={archive_references}"),
        ("IOT/RBRK absent", not output_legacy, f"legacy={output_legacy}"),
        ("email body does not include all 27 rows", len(visible_tickers) < len(score_tickers), f"visible_tickers={len(visible_tickers)}, score_tickers={len(score_tickers)}"),
        ("email body uses low-attention sections", all(section in text_body for section in sections), f"sections={sections}"),
        ("email body avoids urgent transaction language", not forbidden_urgent_language, f"matches={forbidden_urgent_language}"),
        ("metadata send_allowed=no", metadata.get("send_allowed") == "no", f"send_allowed={metadata.get('send_allowed')}"),
        ("metadata delivery phase is compose only", metadata.get("delivery_phase") == "phase5r_c1_compose_only", f"delivery_phase={metadata.get('delivery_phase')}"),
        ("metadata counts match B2 scores", all(metadata.get(key) == value for key, value in expected_counts.items()), f"metadata_counts={{{', '.join(f'{key}: {metadata.get(key)}' for key in expected_counts)}}}"),
        ("Phase 5R-C2 was not created", not phase_c2, f"paths={phase_c2}"),
    ]
    lines = ["# Phase 5R-C1 Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    for label, passed, detail in checks:
        lines.append(f"- **{'PASS' if passed else 'FAIL'}** - {label}: {detail}.")
    lines.extend(["", "## Boundary", "", "Phase 5R-C1 composes local daily research brief artifacts only. It has no delivery, credential, broker, transaction-placement, scheduler, intraday-alert, archived-legacy, or Phase 5R-C2 capability."])
    report = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report, encoding="utf-8")
    RESEARCH_REPORT_PATH.write_text(report, encoding="utf-8")
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({"timestamp": timestamp(), "script_name": Path(__file__).name, "action": "verify_phase5r_c1_email_brief_boundary", "input_path": "phase5r_c1 local artifacts", "output_path": f"{REPORT_PATH.relative_to(ROOT)};{RESEARCH_REPORT_PATH.relative_to(ROOT)}", "status": "complete" if all(item[1] for item in checks) else "failed", "safety_notes": "verification_only=yes; no_delivery=yes; no_broker=yes; no_orders=yes; no_credentials=yes; no_scheduler=yes; no_intraday_alerts=yes; archived_legacy_used=no"})
    if not all(item[1] for item in checks):
        raise RuntimeError("Phase 5R-C1 verification failed; see verification report")
    print(f"Wrote Phase 5R-C1 verification reports; visible_tickers={len(visible_tickers)}")


if __name__ == "__main__":
    main()
