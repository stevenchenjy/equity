from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_b_run_log.csv"

UNIVERSE_PATH = DATA_DIR / "phase5r_universe_seed.csv"
SCORES_PATH = DATA_DIR / "phase5r_b_signal_scores.csv"
TICKETS_PATH = DATA_DIR / "phase5r_b_manual_trade_tickets.csv"
TICKETS_MD_PATH = REVIEWS_DIR / "latest_phase5r_b_manual_trade_tickets.md"
AUDIT_TRAIL = DATA_DIR / "phase5r_b_audit_trail.csv"

LEGACY_TICKERS = {"IOT", "RBRK"}

TICKET_FIELDS = [
    "ticker",
    "action_label",
    "entry_zone_reference",
    "invalidation_reference",
    "stop_reference",
    "take_profit_reference",
    "suggested_position_pct",
    "max_loss_pct_of_account",
    "reason",
    "risks",
    "manual_confirmation_required",
    "broker_connection_allowed",
    "real_order_allowed_by_script",
    "old_holding_data_used",
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


def append_csv(path: Path, row: dict[str, str], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def suggested_position(action_label: str, score: float, max_position_pct: float) -> float:
    if action_label != "possible_buy_manual_review":
        return 0.0
    if score >= 8.0:
        return min(max_position_pct, 2.0)
    return min(max_position_pct, 1.0)


def max_loss_for_position(position_pct: float) -> float:
    if position_pct <= 0:
        return 0.0
    return min(0.50, round(position_pct * 0.20, 2))


def references_for(action: str, data_quality: str) -> tuple[str, str, str, str]:
    if action == "possible_buy_manual_review":
        return (
            "Manual review of current price versus previous close, day range, liquidity, and current news; no automated entry.",
            "Manual invalidation if market data quality weakens, catalyst disappears, or score drops below watch threshold.",
            "Human-defined stop only after independent review; script cannot place or route stops.",
            "Human-defined take-profit plan only; script cannot place or route targets.",
        )
    if action == "watch":
        return (
            "Watch only; require stronger market trend/volume and manual confirmation before any action.",
            "Remove from watch if score falls below 5.25 or data quality becomes insufficient.",
            "Not applicable while watch-only.",
            "Not applicable while watch-only.",
        )
    if data_quality == "insufficient_data":
        return (
            "No entry; read-only market data is insufficient.",
            "Provide manual CSV fallback data or wait for public market adapter availability.",
            "Not applicable.",
            "Not applicable.",
        )
    return (
        "No entry; signal not acceptable for manual review.",
        "Not applicable.",
        "Not applicable.",
        "Not applicable.",
    )


def main() -> None:
    universe_by_ticker = {row["ticker"]: row for row in read_csv(UNIVERSE_PATH)}
    scores = read_csv(SCORES_PATH)

    tickets: list[dict[str, str]] = []
    for row in scores:
        ticker = row["ticker"].upper()
        if ticker in LEGACY_TICKERS:
            raise RuntimeError("Legacy IOT/RBRK ticker cannot enter Phase 5R-B manual tickets")
        seed = universe_by_ticker[ticker]
        score = float(row["total_score"])
        position_pct = suggested_position(row["action_label"], score, float(seed["max_position_pct"]))
        max_loss_pct = max_loss_for_position(position_pct)
        entry, invalidation, stop, take_profit = references_for(row["action_label"], row["data_quality_label"])
        tickets.append(
            {
                "ticker": ticker,
                "action_label": row["action_label"],
                "entry_zone_reference": entry,
                "invalidation_reference": invalidation,
                "stop_reference": stop,
                "take_profit_reference": take_profit,
                "suggested_position_pct": f"{position_pct:.2f}",
                "max_loss_pct_of_account": f"{max_loss_pct:.2f}",
                "reason": f"{row['theme']} Phase 5R-B score {row['total_score']} using {row['data_source']} with {row['data_quality_label']} quality.",
                "risks": f"Read-only market data may be stale or incomplete; {seed['volatility_tier']} volatility tier; human must review liquidity, news, spread, and market regime.",
                "manual_confirmation_required": "yes",
                "broker_connection_allowed": "no",
                "real_order_allowed_by_script": "no",
                "old_holding_data_used": "no",
            }
        )

    write_csv(TICKETS_PATH, tickets, TICKET_FIELDS)

    lines = [
        "# Latest Phase 5R-B Manual Trade Tickets",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "These are manual review tickets only. Scripts cannot connect to a broker, send email, or place orders.",
        "",
        "| Ticker | Action | Suggested Position % | Max Loss % | Reason |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for ticket in tickets:
        lines.append(
            f"| {ticket['ticker']} | {ticket['action_label']} | {ticket['suggested_position_pct']} | {ticket['max_loss_pct_of_account']} | {ticket['reason']} |"
        )
    lines.extend(
        [
            "",
            "Required constants for every CSV ticket: `manual_confirmation_required=yes`, `broker_connection_allowed=no`, `real_order_allowed_by_script=no`, `old_holding_data_used=no`.",
        ]
    )
    TICKETS_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    now = timestamp()
    safety = "manual_tickets_only=yes; broker_connection_allowed=no; real_order_allowed_by_script=no; old_holding_data_used=no; archived_legacy_used=no"
    outputs = f"{TICKETS_PATH.relative_to(ROOT)};{TICKETS_MD_PATH.relative_to(ROOT)}"
    for log_path in (AUDIT_TRAIL, RUN_LOG):
        append_csv(
            log_path,
            {
                "timestamp": now,
                "script_name": Path(__file__).name,
                "action": "create_phase5r_b_manual_trade_tickets",
                "input_path": f"{SCORES_PATH.relative_to(ROOT)};{UNIVERSE_PATH.relative_to(ROOT)}",
                "output_path": outputs,
                "status": "complete",
                "safety_notes": safety,
            },
            AUDIT_FIELDS,
        )
    print(f"Wrote Phase 5R-B manual trade ticket rows: {len(tickets)}")


if __name__ == "__main__":
    main()
