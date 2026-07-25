from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "04_data" / "phase5r_dry_run_candidates.csv"
SCORES_PATH = ROOT / "04_data" / "phase5r_signal_scores.csv"
WATCHLIST_PATH = ROOT / "07_reviews" / "latest_phase5r_watchlist.md"
AUDIT_TRAIL = ROOT / "04_data" / "phase5r_audit_trail.csv"
RUN_LOG = ROOT / "06_logs" / "phase5r_a_run_log.csv"

SCORE_FIELDS = [
    "rank",
    "ticker",
    "company_name",
    "theme",
    "trend_score",
    "volume_score",
    "catalyst_score",
    "quality_score",
    "risk_penalty",
    "total_score",
    "action_label",
    "formula_version",
    "score_explanation",
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

FORMULA_VERSION = "phase5r_a_static_v1"


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def total_score(row: dict[str, str]) -> float:
    if not row["trend_score"]:
        return 0.0
    return round(
        0.30 * float(row["trend_score"])
        + 0.25 * float(row["volume_score"])
        + 0.20 * float(row["catalyst_score"])
        + 0.15 * float(row["quality_score"])
        - 0.10 * float(row["risk_penalty"]),
        2,
    )


def action_label(score: float, row: dict[str, str]) -> str:
    if not row["trend_score"]:
        return "insufficient_data"
    if score >= 7.00:
        return "possible_buy_manual_review"
    if score >= 5.25:
        return "watch"
    return "avoid"


def explanation(row: dict[str, str], score: float) -> str:
    return (
        f"Static dry-run score {score:.2f}; trend={row['trend_score']}, "
        f"volume={row['volume_score']}, catalyst={row['catalyst_score']}, "
        f"quality={row['quality_score']}, risk_penalty={row['risk_penalty']}."
    )


def write_watchlist(rows: list[dict[str, str]]) -> None:
    lines = [
        "# Latest Phase 5R Watchlist",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "This watchlist is a dry-run artifact using local/static placeholder data only. It is not live market data and is not an order recommendation.",
        "",
        "| Rank | Ticker | Company | Theme | Score | Action |",
        "| ---: | --- | --- | --- | ---: | --- |",
    ]
    for row in rows:
        if row["action_label"] in {"possible_buy_manual_review", "watch"}:
            lines.append(
                f"| {row['rank']} | {row['ticker']} | {row['company_name']} | {row['theme']} | {row['total_score']} | {row['action_label']} |"
            )
    lines.extend(
        [
            "",
            "Manual execution boundary: no broker connection, no order placement, no email automation, no old IOT/RBRK holding data.",
        ]
    )
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    with CANDIDATES_PATH.open(newline="", encoding="utf-8") as handle:
        candidates = list(csv.DictReader(handle))

    score_rows: list[dict[str, str]] = []
    for candidate in candidates:
        ticker = candidate["ticker"]
        if ticker in {"IOT", "RBRK"}:
            raise RuntimeError("Legacy IOT/RBRK ticker cannot enter Phase 5R signal scores")
        score = total_score(candidate)
        label = action_label(score, candidate)
        score_rows.append(
            {
                "rank": "",
                "ticker": ticker,
                "company_name": candidate["company_name"],
                "theme": candidate["theme"],
                "trend_score": candidate["trend_score"],
                "volume_score": candidate["volume_score"],
                "catalyst_score": candidate["catalyst_score"],
                "quality_score": candidate["quality_score"],
                "risk_penalty": candidate["risk_penalty"],
                "total_score": f"{score:.2f}",
                "action_label": label,
                "formula_version": FORMULA_VERSION,
                "score_explanation": explanation(candidate, score),
            }
        )

    score_rows.sort(key=lambda item: (-float(item["total_score"]), item["ticker"]))
    for index, row in enumerate(score_rows, start=1):
        row["rank"] = str(index)

    SCORES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SCORES_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SCORE_FIELDS)
        writer.writeheader()
        writer.writerows(score_rows)

    write_watchlist(score_rows)

    now = timestamp()
    safety = "formula_recomputed=yes; static_placeholder_data_only=yes; no_env_read=yes; no_broker=yes; old_iot_rbrk_data_used=no"
    for log_path in (AUDIT_TRAIL, RUN_LOG):
        append_csv(
            log_path,
            {
                "timestamp": now,
                "script_name": Path(__file__).name,
                "action": "score_phase5r_candidates",
                "input_path": str(CANDIDATES_PATH.relative_to(ROOT)),
                "output_path": f"{SCORES_PATH.relative_to(ROOT)};{WATCHLIST_PATH.relative_to(ROOT)}",
                "status": "complete",
                "safety_notes": safety,
            },
            AUDIT_FIELDS,
        )
    print(f"Wrote {len(score_rows)} signal score rows to {SCORES_PATH}")


if __name__ == "__main__":
    main()
