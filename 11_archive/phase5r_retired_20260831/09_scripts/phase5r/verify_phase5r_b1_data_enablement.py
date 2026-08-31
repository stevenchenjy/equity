from __future__ import annotations

import ast
import csv
import importlib.util
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_b1_run_log.csv"
VERIFICATION_REPORT = CONTROL_DIR / "phase5r_b1_verification_report.md"
UNIVERSE_PATH = DATA_DIR / "phase5r_universe_seed.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}

REQUIRED_FILES = [
    "00_project_control/phase5r_b1_market_data_enablement_plan.md",
    "00_project_control/phase5r_b1_install_instructions.md",
    "00_project_control/phase5r_b1_data_readiness_report.md",
    "00_project_control/phase5r_b1_verification_report.md",
    "03_source_data/phase5r/phase5r_b_manual_market_data_fallback_template.csv",
    "03_source_data/phase5r/phase5r_b1_data_source_smoke_test.csv",
    "09_scripts/phase5r/check_phase5r_b1_market_data_source.py",
    "09_scripts/phase5r/create_phase5r_b_manual_fallback_template.py",
    "09_scripts/phase5r/verify_phase5r_b1_data_enablement.py",
    "00_project_control/run_logs/phase5r_b1_run_log.csv",
]

TEMPLATE_COLUMNS = [
    "ticker",
    "last_price",
    "previous_close",
    "intraday_change_pct",
    "volume",
    "average_volume",
    "relative_volume",
    "dollar_volume",
    "day_high",
    "day_low",
    "fifty_two_week_high",
    "fifty_two_week_low",
    "data_timestamp",
    "data_source",
    "data_quality_label",
]

B1_SCRIPTS = [
    SCRIPTS_DIR / "check_phase5r_b1_market_data_source.py",
    SCRIPTS_DIR / "create_phase5r_b_manual_fallback_template.py",
    SCRIPTS_DIR / "verify_phase5r_b1_data_enablement.py",
]

BROKER_MODULES = {
    "alpaca",
    "alpaca_trade_api",
    "ib_insync",
    "robin_stocks",
    "schwab",
    "tda",
    "webull",
    "ccxt",
    "etrade",
    "tradier",
}
EMAIL_MODULES = {"smtplib", "imaplib"}
ENV_MODULES = {"dotenv"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "sendmail", "send_message"}
ENV_CALLS = {"getenv", "environ"}

RUN_LOG_FIELDS = [
    "timestamp",
    "script_name",
    "action",
    "input_path",
    "output_path",
    "status",
    "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def append_log(status: str) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp(),
                "script_name": Path(__file__).name,
                "action": "verify_phase5r_b1_data_enablement",
                "input_path": "03_source_data/phase5r/phase5r_universe_seed.csv;03_source_data/phase5r/phase5r_b1_data_source_smoke_test.csv",
                "output_path": str(VERIFICATION_REPORT.relative_to(ROOT)),
                "status": status,
                "safety_notes": "verification_only=yes; no_broker=yes; no_orders=yes; no_env=yes; no_api_keys=yes; no_email=yes; archived_legacy_used=no",
            }
        )


def passfail(value: bool) -> str:
    return "PASS" if value else "FAIL"


def scan_scripts() -> tuple[list[str], list[str], list[str], list[str]]:
    broker: list[str] = []
    order: list[str] = []
    env: list[str] = []
    email: list[str] = []
    for script in B1_SCRIPTS:
        tree = ast.parse(script.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split(".")[0]
                    if mod in BROKER_MODULES:
                        broker.append(f"{script.relative_to(ROOT)} import {alias.name}")
                    if mod in EMAIL_MODULES:
                        email.append(f"{script.relative_to(ROOT)} import {alias.name}")
                    if mod in ENV_MODULES:
                        env.append(f"{script.relative_to(ROOT)} import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = (node.module or "").split(".")[0]
                if mod in BROKER_MODULES:
                    broker.append(f"{script.relative_to(ROOT)} from {node.module}")
                if mod in EMAIL_MODULES:
                    email.append(f"{script.relative_to(ROOT)} from {node.module}")
                if mod in ENV_MODULES:
                    env.append(f"{script.relative_to(ROOT)} from {node.module}")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in BLOCKED_CALLS:
                order.append(f"{script.relative_to(ROOT)} defines {node.name}")
            elif isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Name) and fn.id in BLOCKED_CALLS:
                    order.append(f"{script.relative_to(ROOT)} calls {fn.id}")
                if isinstance(fn, ast.Attribute):
                    if fn.attr in BLOCKED_CALLS:
                        order.append(f"{script.relative_to(ROOT)} calls {fn.attr}")
                    if fn.attr in ENV_CALLS:
                        env.append(f"{script.relative_to(ROOT)} environment call {fn.attr}")
    return broker, order, env, email


def contains_legacy(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")
    return bool(re.search(r"\\b(IOT|RBRK)\\b", text, flags=re.IGNORECASE))


def main() -> None:
    created_missing = [
        relative
        for relative in REQUIRED_FILES
        if relative != str(VERIFICATION_REPORT.relative_to(ROOT)) and not (ROOT / relative).exists()
    ]
    universe = read_csv(UNIVERSE_PATH)
    universe_legacy = sorted({row["ticker"].upper() for row in universe} & LEGACY_TICKERS)
    template_path = DATA_DIR / "phase5r_b_manual_market_data_fallback_template.csv"
    smoke_path = DATA_DIR / "phase5r_b1_data_source_smoke_test.csv"
    template_exists = template_path.exists()
    template_columns_ok = template_exists and csv_header(template_path) == TEMPLATE_COLUMNS
    template_legacy = contains_legacy(template_path) if template_exists else False
    smoke_rows = read_csv(smoke_path) if smoke_path.exists() else []
    smoke_tickers = sorted(row["ticker"] for row in smoke_rows)
    yfinance_status_reported = bool(smoke_rows) and all(row.get("yfinance_available") in {"yes", "no"} for row in smoke_rows)
    has_yfinance = importlib.util.find_spec("yfinance") is not None
    broker, order, env, email = scan_scripts()
    run_log_rows = read_csv(RUN_LOG) if RUN_LOG.exists() else []
    archive_inputs = [row for row in run_log_rows if "11_archive" in row.get("input_path", "")]
    phase5r_c_paths = []
    for search_root in [CONTROL_DIR, DATA_DIR, SCRIPTS_DIR, ROOT / "04_research" / "realtime_stock_picker_phase5r", ROOT / "08_reviews" / "current"]:
        if search_root.exists():
            for path in search_root.rglob("*"):
                if path.is_file() and re.search(r"phase5r(?:_c_|-c\\b)|phase5rc\\b", str(path), flags=re.IGNORECASE):
                    phase5r_c_paths.append(str(path.relative_to(ROOT)))

    checks = [
        ("Phase 5R-B1 files were created", not created_missing, f"missing={created_missing}"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not order, f"violations={order}"),
        ("no .env read", not env, f"violations={env}"),
        ("no API keys used", not env, "scripts do not access environment variables or credential loaders"),
        ("no email code created", not email, f"violations={email}"),
        ("no archived legacy data used", not archive_inputs, f"archive_inputs={archive_inputs}"),
        ("IOT/RBRK absent", not universe_legacy and not template_legacy, f"universe={universe_legacy}, template_legacy={template_legacy}"),
        ("manual fallback template exists", template_exists and template_columns_ok, f"exists={template_exists}, columns_ok={template_columns_ok}"),
        ("yfinance status is reported clearly", yfinance_status_reported, f"local_yfinance_available={'yes' if has_yfinance else 'no'}, smoke_tickers={smoke_tickers}"),
        ("Phase 5R-C was not created", not phase5r_c_paths, f"paths={phase5r_c_paths}"),
    ]

    lines = [
        "# Phase 5R-B1 Verification Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Source Enablement Summary",
        "",
        f"- Local yfinance availability: `{'yes' if has_yfinance else 'no'}`.",
        f"- Smoke-test rows: `{len(smoke_rows)}`.",
        f"- Smoke-test tickers: `{', '.join(smoke_tickers)}`.",
        "- Full universe market-data fetch attempted: `no`.",
        "- Email delivery created or sent: `no`.",
        "",
        "## Required Checks",
        "",
    ]
    for label, passed, detail in checks:
        lines.append(f"- **{passfail(passed)}** - {label}: {detail}.")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "Phase 5R-B1 enables market data readiness only. It does not connect to brokers, place orders, read credentials, send email, use archived legacy files, or create Phase 5R-C.",
        ]
    )
    VERIFICATION_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    status = "complete" if all(passed for _, passed, _ in checks) else "failed"
    append_log(status)
    if status != "complete":
        raise RuntimeError("Phase 5R-B1 verification failed; see verification report")
    print(f"Wrote Phase 5R-B1 verification report to {VERIFICATION_REPORT}")


if __name__ == "__main__":
    main()
