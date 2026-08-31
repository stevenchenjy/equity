from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
UNIVERSE_PATH = DATA_DIR / "phase5r_universe_seed.csv"
TEMPLATE_PATH = DATA_DIR / "phase5r_b_manual_market_data_fallback_template.csv"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_b1_run_log.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}

TEMPLATE_FIELDS = [
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


def append_log(action: str, output_path: Path, status: str) -> None:
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
                "output_path": str(output_path.relative_to(ROOT)),
                "status": status,
                "safety_notes": "canonical_universe_only=yes; template_only=yes; no_broker=yes; no_orders=yes; no_email=yes; archived_legacy_used=no",
            }
        )


def main() -> None:
    universe = read_csv(UNIVERSE_PATH)
    legacy = sorted({row["ticker"].upper() for row in universe} & LEGACY_TICKERS)
    if legacy:
        raise RuntimeError(f"Legacy tickers are not allowed in Phase 5R-B1 fallback template: {legacy}")

    rows = []
    for seed in universe:
        row = {field: "" for field in TEMPLATE_FIELDS}
        row["ticker"] = seed["ticker"].upper()
        row["data_source"] = "manual_csv_fallback"
        row["data_quality_label"] = "manual_fill_required"
        rows.append(row)

    write_csv(TEMPLATE_PATH, rows, TEMPLATE_FIELDS)
    append_log("create_phase5r_b_manual_fallback_template", TEMPLATE_PATH, "complete")
    print(f"Wrote Phase 5R-B manual fallback template rows: {len(rows)}")


if __name__ == "__main__":
    main()
