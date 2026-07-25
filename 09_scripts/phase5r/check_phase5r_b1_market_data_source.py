from __future__ import annotations

import csv
import importlib
import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
UNIVERSE_PATH = DATA_DIR / "phase5r_universe_seed.csv"
SMOKE_TEST_PATH = DATA_DIR / "phase5r_b1_data_source_smoke_test.csv"
READINESS_REPORT = CONTROL_DIR / "phase5r_b1_data_readiness_report.md"
INSTALL_INSTRUCTIONS = CONTROL_DIR / "phase5r_b1_install_instructions.md"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_b1_run_log.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}
SMOKE_TEST_TICKERS = ["QQQ", "XLK", "SPY"]

SMOKE_FIELDS = [
    "ticker",
    "yfinance_available",
    "smoke_test_attempted",
    "last_price",
    "previous_close",
    "volume",
    "data_timestamp",
    "data_source",
    "data_quality_label",
    "status",
    "notes",
]

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


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def append_log(action: str, output_paths: list[Path], status: str, notes: str) -> None:
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
                "action": action,
                "input_path": str(UNIVERSE_PATH.relative_to(ROOT)),
                "output_path": ";".join(str(path.relative_to(ROOT)) for path in output_paths),
                "status": status,
                "safety_notes": f"read_only_smoke_test=yes; qqq_xlk_spy_only=yes; no_full_universe_fetch=yes; no_broker=yes; no_orders=yes; no_email=yes; archived_legacy_used=no; {notes}",
            }
        )


def yfinance_available() -> bool:
    return importlib.util.find_spec("yfinance") is not None


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, "item"):
            value = value.item()
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result


def fmt_float(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def fmt_int(value: float | None) -> str:
    return "" if value is None else str(int(round(value)))


def blank_row(ticker: str, available: bool, status: str, notes: str) -> dict[str, str]:
    return {
        "ticker": ticker,
        "yfinance_available": "yes" if available else "no",
        "smoke_test_attempted": "yes" if available else "no",
        "last_price": "",
        "previous_close": "",
        "volume": "",
        "data_timestamp": timestamp(),
        "data_source": "yfinance_public_market_data" if available else "none_yfinance_missing",
        "data_quality_label": "insufficient_data",
        "status": status,
        "notes": notes,
    }


def yfinance_smoke_rows() -> tuple[list[dict[str, str]], str]:
    yf = importlib.import_module("yfinance")
    rows: list[dict[str, str]] = []
    for ticker in SMOKE_TEST_TICKERS:
        row = blank_row(ticker, True, "failed", "read-only smoke test attempted")
        try:
            ticker_obj = yf.Ticker(ticker)
            fast_info = getattr(ticker_obj, "fast_info", {}) or {}
            history = ticker_obj.history(period="5d", interval="1d", auto_adjust=False)
            last_price = as_float(fast_info.get("last_price") or fast_info.get("lastPrice"))
            previous_close = as_float(fast_info.get("previous_close") or fast_info.get("previousClose"))
            volume = as_float(fast_info.get("last_volume") or fast_info.get("lastVolume"))
            if last_price is None and not history.empty:
                last_price = as_float(history["Close"].iloc[-1])
            if previous_close is None and len(history.index) >= 2:
                previous_close = as_float(history["Close"].iloc[-2])
            if volume is None and not history.empty:
                volume = as_float(history["Volume"].iloc[-1])
            row.update(
                {
                    "last_price": fmt_float(last_price),
                    "previous_close": fmt_float(previous_close),
                    "volume": fmt_int(volume),
                    "data_timestamp": timestamp(),
                    "data_quality_label": "ok" if last_price is not None and previous_close is not None else "partial",
                    "status": "passed" if last_price is not None and previous_close is not None else "partial",
                    "notes": "public market data read only; no full universe fetch",
                }
            )
        except Exception as exc:
            row["notes"] = f"read-only smoke test failed safely: {exc.__class__.__name__}"
        rows.append(row)
    overall = "passed" if all(row["status"] == "passed" for row in rows) else "partial_or_failed"
    return rows, overall


def write_install_instructions(has_yfinance: bool) -> None:
    status = "installed" if has_yfinance else "missing"
    lines = [
        "# Phase 5R-B1 Install Instructions",
        "",
        f"Generated: `{timestamp()}`",
        "",
        f"Current `yfinance` status: `{status}`.",
        "",
        "## Install Command",
        "",
        "```bash",
        "python3 -m pip install yfinance",
        "```",
        "",
        "After installation, rerun:",
        "",
        "```bash",
        "python3 09_scripts/phase5r/check_phase5r_b1_market_data_source.py",
        "python3 09_scripts/phase5r/verify_phase5r_b1_data_enablement.py",
        "```",
        "",
        "This enables only read-only public market data checks. It does not connect to a broker, place orders, read `.env`, use API keys, or send email.",
    ]
    INSTALL_INSTRUCTIONS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_readiness_report(has_yfinance: bool, smoke_rows: list[dict[str, str]], overall_status: str, universe_count: int) -> None:
    quality_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for row in smoke_rows:
        quality_counts[row["data_quality_label"]] = quality_counts.get(row["data_quality_label"], 0) + 1
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    lines = [
        "# Phase 5R-B1 Data Readiness Report",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "## Project Direction",
        "",
        "- AI Investment Research Assistant.",
        "- Low-attention daily email workflow later, not in this phase.",
        "- Manual execution only.",
        "- No day-trading rhythm.",
        "",
        "## Source Status",
        "",
        f"- Canonical universe rows read: `{universe_count}`.",
        f"- yfinance available: `{'yes' if has_yfinance else 'no'}`.",
        f"- Smoke-test tickers: `{', '.join(SMOKE_TEST_TICKERS)}`.",
        f"- Smoke-test overall status: `{overall_status}`.",
        f"- Smoke-test row statuses: `{status_counts}`.",
        f"- Smoke-test data quality: `{quality_counts}`.",
        "",
        "## Readiness Decision",
        "",
    ]
    if has_yfinance and overall_status == "passed":
        lines.append("Readiness: `ready_for_limited_read_only_market_data`.")
        lines.append("Next safe step would be a full-universe read-only update after explicit approval.")
    elif has_yfinance:
        lines.append("Readiness: `not_ready_full_universe_fetch`.")
        lines.append("The adapter library is installed, but the QQQ/XLK/SPY smoke test did not fully pass.")
    else:
        lines.append("Readiness: `install_yfinance_or_fill_manual_csv_required`.")
        lines.append("Install `yfinance` with the documented command or fill the manual fallback CSV template before expecting usable market values.")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "- No broker connection.",
            "- No order code.",
            "- No `.env` read.",
            "- No API keys.",
            "- No email sending.",
            "- No archived legacy files.",
            "- IOT/RBRK excluded.",
        ]
    )
    READINESS_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    universe = read_csv(UNIVERSE_PATH)
    tickers = {row["ticker"].upper() for row in universe}
    legacy = sorted(tickers & LEGACY_TICKERS)
    if legacy:
        raise RuntimeError(f"Legacy tickers are not allowed in Phase 5R-B1 source checks: {legacy}")
    missing_smoke = sorted(set(SMOKE_TEST_TICKERS) - tickers)
    if missing_smoke:
        raise RuntimeError(f"Smoke-test benchmark tickers missing from canonical universe: {missing_smoke}")

    has_yfinance = yfinance_available()
    write_install_instructions(has_yfinance)
    if has_yfinance:
        smoke_rows, overall = yfinance_smoke_rows()
    else:
        smoke_rows = [
            blank_row(ticker, False, "not_attempted", "yfinance missing; install instructions written; no market values invented")
            for ticker in SMOKE_TEST_TICKERS
        ]
        overall = "not_attempted_yfinance_missing"

    write_csv(SMOKE_TEST_PATH, smoke_rows, SMOKE_FIELDS)
    write_readiness_report(has_yfinance, smoke_rows, overall, len(universe))
    append_log(
        "check_phase5r_b1_market_data_source",
        [SMOKE_TEST_PATH, READINESS_REPORT, INSTALL_INSTRUCTIONS],
        "complete",
        f"yfinance_available={'yes' if has_yfinance else 'no'}; smoke_status={overall}",
    )
    print(f"Phase 5R-B1 yfinance_available={has_yfinance}; smoke_status={overall}")


if __name__ == "__main__":
    main()
