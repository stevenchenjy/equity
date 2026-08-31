from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_c5_run_log.csv"

LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
CONCENTRATION = POSITION_DIR / "phase5r_c4r_portfolio_concentration_report.csv"
B2_SCORES = DATA_DIR / "phase5r_b2_signal_scores.csv"
OUTPUT = RESEARCH_DIR / "phase5r_c5_research_queue.csv"

CONTROLLED_RESEARCH_TICKERS = {"META", "AVGO", "PANW", "MU", "AMD", "ARM", "SPY"}

QUEUE_FIELDS = [
    "priority", "ticker", "research_role", "queue_reason", "current_position_status",
    "position_pct", "portfolio_concentration_status", "market_rank", "market_score",
    "market_action_label", "theme", "source_position_path", "source_market_path",
    "human_review_required",
]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "research_rows", "current_position_rows", "new_candidate_rows", "eligible_buy_review_count",
    "email_sent", "scheduler_used", "broker_used", "smtp_config_modified",
    "archived_legacy_used", "safety_notes",
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


def append_log(rows: list[dict[str, str]]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5", "script_name": Path(__file__).name,
            "action": "create_weekly_research_queue",
            "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [LOCAL_POSITIONS, CONCENTRATION, B2_SCORES]),
            "output_paths": str(OUTPUT.relative_to(ROOT)), "status": "complete",
            "research_rows": str(len(rows)),
            "current_position_rows": str(sum(row["research_role"] == "current_position_risk_review" for row in rows)),
            "new_candidate_rows": str(sum(row["research_role"] != "current_position_risk_review" for row in rows)),
            "eligible_buy_review_count": "0", "email_sent": "no", "scheduler_used": "no",
            "broker_used": "no", "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "weekly_only=yes; current_positions_local_only=yes; manual_review_only=yes",
        })


def main() -> None:
    positions = read_csv(LOCAL_POSITIONS)
    concentration_rows = read_csv(CONCENTRATION)
    scores = read_csv(B2_SCORES)
    concentration = {
        row["ticker"].upper(): row["concentration_status"]
        for row in concentration_rows if row["record_type"] == "position"
    }
    score_by_ticker = {row["ticker"].upper(): row for row in scores}

    rows: list[dict[str, str]] = []
    current_tickers: set[str] = set()
    sorted_positions = sorted(positions, key=lambda row: -float(row["position_pct"]))
    for index, position in enumerate(sorted_positions, start=1):
        ticker = position["ticker"].strip().upper()
        current_tickers.add(ticker)
        pct = float(position["position_pct"])
        status = concentration.get(ticker, "not_evaluable")
        rows.append({
            "priority": str(index), "ticker": ticker, "research_role": "current_position_risk_review",
            "queue_reason": f"Current local position at {pct:.2f}% requires thesis and concentration review before new ideas.",
            "current_position_status": "current_local_position", "position_pct": f"{pct:.2f}",
            "portfolio_concentration_status": status, "market_rank": "", "market_score": "",
            "market_action_label": "current_position", "theme": "Connected operations software" if ticker == "IOT" else "Cybersecurity",
            "source_position_path": str(LOCAL_POSITIONS.relative_to(ROOT)), "source_market_path": "",
            "human_review_required": "yes",
        })

    candidate_rows: list[tuple[dict[str, str], str, str]] = []
    for score in scores:
        ticker = score["ticker"].upper()
        if ticker in current_tickers or ticker not in CONTROLLED_RESEARCH_TICKERS:
            continue
        if score["action_label"] == "possible_buy_manual_review":
            candidate_rows.append((score, "top_manual_review_candidate", "Top B2 manual-review candidate."))
    watch_added = 0
    for score in scores:
        ticker = score["ticker"].upper()
        if ticker in current_tickers or ticker not in CONTROLLED_RESEARCH_TICKERS or score["action_label"] != "watch" or watch_added >= 5:
            continue
        candidate_rows.append((score, "top_watch_candidate", "Top B2 watch candidate; weekly research cap applies."))
        watch_added += 1

    diversification = score_by_ticker.get("SPY")
    selected = {score["ticker"].upper() for score, _, _ in candidate_rows}
    if diversification and "SPY" not in selected and "SPY" not in current_tickers:
        candidate_rows.append((diversification, "diversification_candidate", "Broad-market reference may improve diversification analysis."))

    for offset, (score, role, reason) in enumerate(candidate_rows, start=len(rows) + 1):
        rows.append({
            "priority": str(offset), "ticker": score["ticker"].upper(), "research_role": role,
            "queue_reason": reason, "current_position_status": "not_held", "position_pct": "0.00",
            "portfolio_concentration_status": "active_sleeve_above_target",
            "market_rank": score["rank"], "market_score": score["total_score"],
            "market_action_label": score["action_label"], "theme": score["theme"],
            "source_position_path": "", "source_market_path": str(B2_SCORES.relative_to(ROOT)),
            "human_review_required": "yes",
        })

    if [row["ticker"] for row in rows[:2]] != ["IOT", "RBRK"]:
        raise RuntimeError("Current positions must be the first two weekly risk-review rows")
    write_csv(OUTPUT, rows, QUEUE_FIELDS)
    append_log(rows)
    print(f"Created Phase 5R-C5 research queue: rows={len(rows)}")


if __name__ == "__main__":
    main()
