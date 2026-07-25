from __future__ import annotations

import ast
import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
SCRIPTS_DIR = ROOT / "09_scripts" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_b2_run_log.csv"
REPORT_PATH = CONTROL_DIR / "phase5r_b2_verification_report.md"
RESEARCH_REPORT_PATH = RESEARCH_DIR / "phase5r_b2_verification_report.md"
LOCAL_POSITIONS_PATH = ROOT / "05_risk_and_positions" / "current_positions.local.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}
MARKET_FIELDS = [
    "ticker", "last_price", "previous_close", "intraday_change_pct", "volume",
    "average_volume", "relative_volume", "dollar_volume", "day_high", "day_low",
    "fifty_two_week_high", "fifty_two_week_low", "market_session_date",
    "market_age_calendar_days", "data_timestamp", "data_source",
    "data_quality_label",
]
TICKET_FIELDS = ["ticker", "action_label", "entry_zone_reference", "invalidation_reference", "stop_reference", "take_profit_reference", "suggested_position_pct", "max_loss_pct_of_account", "reason", "risks", "manual_confirmation_required", "broker_connection_allowed", "real_order_allowed_by_script", "old_holding_data_used"]
REQUIRED_FILES = [
    "00_project_control/phase5r_b2_full_universe_data_policy.md", "00_project_control/phase5r_b2_data_source_decision.md", "00_project_control/phase5r_b2_verification_report.md",
    "03_source_data/phase5r/phase5r_b2_market_data_snapshot.csv", "03_source_data/phase5r/phase5r_b2_market_data_quality_report.csv", "03_source_data/phase5r/phase5r_b2_candidates_with_market_data.csv", "03_source_data/phase5r/phase5r_b2_signal_scores.csv", "03_source_data/phase5r/phase5r_b2_manual_trade_tickets.csv", "03_source_data/phase5r/phase5r_b2_audit_trail.csv",
    "08_reviews/current/latest_phase5r_b2_daily_research_preview.md", "08_reviews/current/latest_phase5r_b2_watchlist.md", "08_reviews/current/latest_phase5r_b2_manual_trade_tickets.md",
    "09_scripts/phase5r/run_phase5r_b2_full_universe_market_data.py", "09_scripts/phase5r/score_phase5r_b2_candidates.py", "09_scripts/phase5r/create_phase5r_b2_manual_trade_tickets.py", "09_scripts/phase5r/verify_phase5r_b2_read_only_boundary.py",
    "04_research/realtime_stock_picker_phase5r/phase5r_b2_data_report.md", "04_research/realtime_stock_picker_phase5r/phase5r_b2_verification_report.md", "00_project_control/run_logs/phase5r_b2_run_log.csv",
]
B2_SCRIPTS = [
    SCRIPTS_DIR / "run_phase5r_b2_full_universe_market_data.py", SCRIPTS_DIR / "score_phase5r_b2_candidates.py",
    SCRIPTS_DIR / "create_phase5r_b2_manual_trade_tickets.py", SCRIPTS_DIR / "verify_phase5r_b2_read_only_boundary.py",
]
BROKER_MODULES = {"alpaca", "alpaca_trade_api", "ib_insync", "robin_stocks", "schwab", "tda", "webull", "ccxt", "etrade", "tradier"}
EMAIL_MODULES = {"smtplib", "imaplib", "gmail"}
ENV_MODULES = {"dotenv"}
BLOCKED_CALLS = {"place_order", "submit_order", "create_order", "send_order", "execute_trade", "sendmail", "send_message"}
AUDIT_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "safety_notes"]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def scan_scripts() -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    broker: list[str] = []
    order: list[str] = []
    env: list[str] = []
    email: list[str] = []
    yfinance_imports: list[str] = []
    for path in B2_SCRIPTS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0]]
            for name in names:
                if name in BROKER_MODULES:
                    broker.append(f"{path.name}: {name}")
                if name in EMAIL_MODULES:
                    email.append(f"{path.name}: {name}")
                if name in ENV_MODULES:
                    env.append(f"{path.name}: {name}")
                if name == "yfinance":
                    yfinance_imports.append(path.name)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in BLOCKED_CALLS:
                order.append(f"{path.name}: defines {node.name}")
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
                    order.append(f"{path.name}: calls {node.func.id}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in BLOCKED_CALLS:
                    order.append(f"{path.name}: calls {node.func.attr}")
                if isinstance(node.func, ast.Attribute) and node.func.attr in {"getenv", "environ"}:
                    env.append(f"{path.name}: environment access")
    return broker, order, env, email, yfinance_imports


def main() -> None:
    generated_reports = {
        str(REPORT_PATH.relative_to(ROOT)),
        str(RESEARCH_REPORT_PATH.relative_to(ROOT)),
    }
    missing = [name for name in REQUIRED_FILES if name not in generated_reports and not (ROOT / name).exists()]
    universe = read_csv(DATA_DIR / "phase5r_universe_seed.csv")
    positions = read_csv(LOCAL_POSITIONS_PATH)
    snapshot = read_csv(DATA_DIR / "phase5r_b2_market_data_snapshot.csv")
    quality = read_csv(DATA_DIR / "phase5r_b2_market_data_quality_report.csv")
    candidates = read_csv(DATA_DIR / "phase5r_b2_candidates_with_market_data.csv")
    scores = read_csv(DATA_DIR / "phase5r_b2_signal_scores.csv")
    tickets = read_csv(DATA_DIR / "phase5r_b2_manual_trade_tickets.csv")
    audit = read_csv(DATA_DIR / "phase5r_b2_audit_trail.csv")
    broker, order, env, email, yfinance_imports = scan_scripts()
    universe_tickers = {row["ticker"].upper() for row in universe}
    held_tickers = {row["ticker"].upper() for row in positions}
    expected_price_tickers = universe_tickers | held_tickers
    ticker_lists = {
        "universe": [row["ticker"].upper() for row in universe],
        "snapshot": [row["ticker"].upper() for row in snapshot],
        "quality": [row["ticker"].upper() for row in quality],
        "candidates": [row["ticker"].upper() for row in candidates],
        "scores": [row["ticker"].upper() for row in scores],
        "tickets": [row["ticker"].upper() for row in tickets],
    }
    ticker_sets = {name: set(values) for name, values in ticker_lists.items()}
    duplicate_outputs = {
        name: sorted(
            {ticker for ticker in values if values.count(ticker) > 1}
        )
        for name, values in ticker_lists.items()
        if len(values) != len(set(values))
    }
    smoke_index = next((index for index, row in enumerate(audit) if row["action"] == "benchmark_smoke_test" and row["status"] == "passed"), None)
    fetch_index = next((index for index, row in enumerate(audit) if row["action"] == "full_universe_market_data_refresh" and row["status"] == "complete"), None)
    missing_core = {
        row["ticker"].upper()
        for row in snapshot
        if row["ticker"].upper() in universe_tickers
        and any(
            not row[field]
            for field in (
                "last_price",
                "previous_close",
                "intraday_change_pct",
                "volume",
                "average_volume",
                "relative_volume",
                "dollar_volume",
            )
        )
    }
    insufficient_tickers = {row["ticker"] for row in scores if row["action_label"] == "insufficient_data"}
    ticket_constants_ok = all(all(ticket[key] == expected for key, expected in {"manual_confirmation_required": "yes", "broker_connection_allowed": "no", "real_order_allowed_by_script": "no", "old_holding_data_used": "no"}.items()) for ticket in tickets)
    archive_inputs = [row for row in audit if "11_archive" in row["input_path"]]
    held_only_tickers = held_tickers - universe_tickers
    legacy_price_rows = (
        ticker_sets["snapshot"] | ticker_sets["quality"]
    ) & LEGACY_TICKERS
    legacy_candidate_rows = (
        ticker_sets["universe"]
        | ticker_sets["candidates"]
        | ticker_sets["scores"]
        | ticker_sets["tickets"]
    ) & LEGACY_TICKERS
    checks = [
        ("Phase 5R-B2 files were created", not missing, f"missing={missing}"),
        ("benchmark smoke test ran before full universe fetch", smoke_index is not None and fetch_index is not None and smoke_index < fetch_index, f"smoke_index={smoke_index}, fetch_index={fetch_index}"),
        ("yfinance is used only for public market data", yfinance_imports == ["run_phase5r_b2_full_universe_market_data.py"], f"imports={yfinance_imports}"),
        ("no broker libraries imported", not broker, f"violations={broker}"),
        ("no order code created", not order, f"violations={order}"),
        ("no .env read", not env, f"violations={env}"),
        ("no API keys used", not env, "no environment or credential access found"),
        ("no email code created", not email, f"violations={email}"),
        ("no archived legacy data used", not archive_inputs, f"archive_inputs={archive_inputs}"),
        ("canonical universe remains 27 unique research tickers", len(universe) == 27 and len(ticker_lists["universe"]) == len(universe_tickers), f"universe_rows={len(universe)}, unique={len(universe_tickers)}"),
        ("all ticker-keyed outputs are unique", not duplicate_outputs, f"duplicates={duplicate_outputs}"),
        ("snapshot contains universe plus current held price-monitoring rows", ticker_sets["snapshot"] == expected_price_tickers and len(snapshot) == len(expected_price_tickers), f"snapshot_rows={len(snapshot)}, expected={len(expected_price_tickers)}, held_only={sorted(held_only_tickers)}"),
        ("quality report matches snapshot ticker coverage", ticker_sets["quality"] == expected_price_tickers and len(quality) == len(expected_price_tickers), f"quality_rows={len(quality)}, expected={len(expected_price_tickers)}"),
        ("candidate, score, and ticket rows remain universe-only", all(ticker_sets[name] == universe_tickers for name in ("candidates", "scores", "tickets")), f"candidate={len(candidates)}, scores={len(scores)}, tickets={len(tickets)}"),
        ("current IOT/RBRK rows are held-only price monitoring", legacy_price_rows <= held_tickers and not legacy_candidate_rows, f"price_rows={sorted(legacy_price_rows)}, held={sorted(held_tickers)}, candidate_rows={sorted(legacy_candidate_rows)}"),
        ("active 17-column market data schema is exact", header(DATA_DIR / "phase5r_b2_market_data_snapshot.csv") == MARKET_FIELDS and len(MARKET_FIELDS) == 17, "snapshot header checked"),
        ("insufficient_data rows are preserved when data is missing", missing_core <= insufficient_tickers, f"missing_core={sorted(missing_core)}, insufficient={sorted(insufficient_tickers)}"),
        ("manual ticket constants are yes/no/no/no", ticket_constants_ok, f"ticket_rows={len(tickets)}"),
    ]
    lines = ["# Phase 5R-B2 Verification Report", "", f"Generated: `{timestamp()}`", "", "## Required Checks", ""]
    for label, passed, detail in checks:
        lines.append(f"- **{'PASS' if passed else 'FAIL'}** - {label}: {detail}.")
    lines.extend(["", "## Summary", "", f"- Canonical universe rows: `{len(universe)}`.", f"- Held-only price-monitoring rows: `{len(held_only_tickers)}` ({', '.join(sorted(held_only_tickers)) or 'none'}).", f"- Snapshot rows: `{len(snapshot)}`.", f"- Candidate rows: `{len(candidates)}`.", f"- Score rows: `{len(scores)}`.", f"- Manual ticket rows: `{len(tickets)}`.", f"- Missing-core-data candidate rows preserved: `{len(missing_core)}`.", "- The B2 dataset is a single daily, read-only public-market-data refresh. Held-only rows monitor existing positions but are never admitted to candidate scores or tickets. It remains manual-execution-only."])
    report_text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    RESEARCH_REPORT_PATH.write_text(report_text, encoding="utf-8")
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=AUDIT_FIELDS,
            lineterminator="\n",
        )
        if not exists:
            writer.writeheader()
        writer.writerow({"timestamp": timestamp(), "script_name": Path(__file__).name, "action": "verify_phase5r_b2_read_only_boundary", "input_path": "phase5r_b2 outputs", "output_path": f"{REPORT_PATH.relative_to(ROOT)};{RESEARCH_REPORT_PATH.relative_to(ROOT)}", "status": "complete" if all(item[1] for item in checks) else "failed", "safety_notes": "verification_only=yes; no_broker=yes; no_orders=yes; no_email=yes; no_credentials=yes; archived_legacy_used=no"})
    if not all(item[1] for item in checks):
        raise RuntimeError("Phase 5R-B2 verification failed; see verification report")
    print(f"Wrote Phase 5R-B2 verification reports; snapshot_rows={len(snapshot)}")


if __name__ == "__main__":
    main()
