from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from phase5r_market_data_adapter import MARKET_DATA_FIELDS, load_market_data, read_universe


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
CONTROL_DIR = ROOT / "00_project_control"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_b_run_log.csv"

UNIVERSE_PATH = DATA_DIR / "phase5r_universe_seed.csv"
SNAPSHOT_PATH = DATA_DIR / "phase5r_b_market_data_snapshot.csv"
QUALITY_REPORT_PATH = DATA_DIR / "phase5r_b_market_data_quality_report.csv"
CANDIDATES_PATH = DATA_DIR / "phase5r_b_candidates_with_market_data.csv"
AUDIT_TRAIL = DATA_DIR / "phase5r_b_audit_trail.csv"
DATA_SOURCE_DECISION = CONTROL_DIR / "phase5r_b_data_source_decision.md"
ADAPTER_REPORT = RESEARCH_DIR / "phase5r_b_market_data_adapter_report.md"

LEGACY_TICKERS = {"IOT", "RBRK"}

QUALITY_FIELDS = [
    "ticker",
    "data_source",
    "data_quality_label",
    "missing_fields",
    "usable_for_scoring",
    "notes",
]

CANDIDATE_FIELDS = [
    "ticker",
    "company_name",
    "sector",
    "industry",
    "theme",
    "liquidity_tier",
    "volatility_tier",
    "is_benchmark",
    "max_position_pct",
    *MARKET_DATA_FIELDS[1:],
    "market_data_usable",
    "candidate_note",
]

AUDIT_FIELDS = [
    "timestamp",
    "script_name",
    "action",
    "input_path",
    "output_path",
    "status",
    "safety_notes",
]

REQUIRED_SCORING_MARKET_FIELDS = [
    "last_price",
    "previous_close",
    "intraday_change_pct",
    "volume",
    "average_volume",
    "relative_volume",
    "dollar_volume",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def missing_fields(row: dict[str, str]) -> list[str]:
    return [field for field in REQUIRED_SCORING_MARKET_FIELDS if row.get(field, "") == ""]


def write_data_source_decision(decision_source: str, yfinance_available: bool, manual_available: bool, reason: str) -> None:
    lines = [
        "# Phase 5R-B Data Source Decision",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Decision",
        "",
        f"- Selected data source: `{decision_source}`.",
        f"- yfinance available: `{'yes' if yfinance_available else 'no'}`.",
        f"- Manual CSV fallback available: `{'yes' if manual_available else 'no'}`.",
        f"- Fail-safe reason: `{reason}`.",
        "",
        "## Boundary",
        "",
        "- Canonical input read: `03_source_data/phase5r/phase5r_universe_seed.csv`.",
        "- Archived legacy folders were not read.",
        "- IOT/RBRK legacy holding data was not used.",
        "- No broker, credential, order, trade, or email system was used.",
        "- If no public or manual market data is available, rows remain `insufficient_data`; prices are not invented.",
    ]
    DATA_SOURCE_DECISION.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_adapter_report(decision_source: str, yfinance_available: bool, manual_available: bool, reason: str, rows: list[dict[str, str]]) -> None:
    quality_counts: dict[str, int] = {}
    for row in rows:
        quality_counts[row["data_quality_label"]] = quality_counts.get(row["data_quality_label"], 0) + 1
    lines = [
        "# Phase 5R-B Market Data Adapter Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Adapter Summary",
        "",
        f"- Universe rows processed: `{len(rows)}`.",
        f"- Selected data source: `{decision_source}`.",
        f"- yfinance available: `{'yes' if yfinance_available else 'no'}`.",
        f"- Manual CSV fallback available: `{'yes' if manual_available else 'no'}`.",
        f"- Data quality counts: `{quality_counts}`.",
        f"- Fail-safe note: `{reason}`.",
        "",
        "## Safety Boundary",
        "",
        "- Read-only market data only.",
        "- Manual execution only.",
        "- No archived legacy input.",
        "- No IOT/RBRK holding data.",
        "- No broker imports, broker accounts, orders, email, credentials, or environment files.",
    ]
    ADAPTER_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    universe = read_universe(UNIVERSE_PATH)
    market_rows, decision = load_market_data(universe)
    market_by_ticker = {row["ticker"].upper(): row for row in market_rows}

    snapshot_rows: list[dict[str, str]] = []
    quality_rows: list[dict[str, str]] = []
    candidate_rows: list[dict[str, str]] = []

    for seed in universe:
        ticker = seed["ticker"].upper()
        if ticker in LEGACY_TICKERS:
            raise RuntimeError("Legacy IOT/RBRK ticker cannot enter Phase 5R-B market data")
        market = market_by_ticker[ticker]
        snapshot_rows.append({field: market.get(field, "") for field in MARKET_DATA_FIELDS})
        missing = missing_fields(market)
        usable = "yes" if not missing else "no"
        quality_rows.append(
            {
                "ticker": ticker,
                "data_source": market["data_source"],
                "data_quality_label": market["data_quality_label"],
                "missing_fields": ";".join(missing),
                "usable_for_scoring": usable,
                "notes": "usable read-only market row" if usable == "yes" else "insufficient market data; no values invented",
            }
        )
        candidate = {
            "ticker": ticker,
            "company_name": seed["company_name"],
            "sector": seed["sector"],
            "industry": seed["industry"],
            "theme": seed["theme"],
            "liquidity_tier": seed["liquidity_tier"],
            "volatility_tier": seed["volatility_tier"],
            "is_benchmark": seed["is_benchmark"],
            "max_position_pct": seed["max_position_pct"],
            "market_data_usable": usable,
            "candidate_note": "read-only market data attached" if usable == "yes" else "requires manual market data before scoring",
        }
        for field in MARKET_DATA_FIELDS[1:]:
            candidate[field] = market.get(field, "")
        candidate_rows.append(candidate)

    write_csv(SNAPSHOT_PATH, snapshot_rows, MARKET_DATA_FIELDS)
    write_csv(QUALITY_REPORT_PATH, quality_rows, QUALITY_FIELDS)
    write_csv(CANDIDATES_PATH, candidate_rows, CANDIDATE_FIELDS)
    write_data_source_decision(decision.selected_source, decision.yfinance_available, decision.manual_fallback_available, decision.fail_safe_reason)
    write_adapter_report(decision.selected_source, decision.yfinance_available, decision.manual_fallback_available, decision.fail_safe_reason, snapshot_rows)

    now = timestamp()
    safety = "read_only_market_data=yes; canonical_universe_only=yes; credentialless=yes; no_broker=yes; no_orders=yes; no_email=yes; archived_legacy_used=no"
    outputs = ";".join(str(path.relative_to(ROOT)) for path in [SNAPSHOT_PATH, QUALITY_REPORT_PATH, CANDIDATES_PATH, DATA_SOURCE_DECISION, ADAPTER_REPORT])
    for log_path in (AUDIT_TRAIL, RUN_LOG):
        append_csv(
            log_path,
            {
                "timestamp": now,
                "script_name": Path(__file__).name,
                "action": "run_phase5r_b_market_data_update",
                "input_path": str(UNIVERSE_PATH.relative_to(ROOT)),
                "output_path": outputs,
                "status": "complete",
                "safety_notes": safety,
            },
            AUDIT_FIELDS,
        )
    print(f"Wrote Phase 5R-B market data snapshot rows: {len(snapshot_rows)}")


if __name__ == "__main__":
    main()
