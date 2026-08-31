from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE_PATH = ROOT / "04_data" / "phase5r_universe_seed.csv"
SCORES_PATH = ROOT / "04_data" / "phase5r_signal_scores.csv"
TICKETS_PATH = ROOT / "04_data" / "phase5r_manual_trade_tickets.csv"
TICKETS_MD_PATH = ROOT / "07_reviews" / "latest_phase5r_manual_trade_tickets.md"
AUDIT_TRAIL = ROOT / "04_data" / "phase5r_audit_trail.csv"
RUN_LOG = ROOT / "06_logs" / "phase5r_a_run_log.csv"

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


def main() -> None:
    with UNIVERSE_PATH.open(newline="", encoding="utf-8") as handle:
        universe_by_ticker = {row["ticker"]: row for row in csv.DictReader(handle)}
    with SCORES_PATH.open(newline="", encoding="utf-8") as handle:
        scores = list(csv.DictReader(handle))

    tickets: list[dict[str, str]] = []
    for row in scores:
        ticker = row["ticker"]
        if ticker in {"IOT", "RBRK"}:
            raise RuntimeError("Legacy IOT/RBRK ticker cannot enter Phase 5R manual tickets")
        seed = universe_by_ticker[ticker]
        score = float(row["total_score"])
        max_position_pct = float(seed["max_position_pct"])
        position_pct = suggested_position(row["action_label"], score, max_position_pct)
        max_loss_pct = max_loss_for_position(position_pct)
        action = row["action_label"]
        if action == "possible_buy_manual_review":
            entry = "Manual review of current price vs. intraday VWAP/previous close; no automated entry."
            invalidation = "Manual invalidation if catalyst weakens, broad market breaks down, or score falls below watch threshold."
            stop = "Human-defined stop reference; placeholder max loss cap only."
            take_profit = "Human-defined scale/trim reference; no automated target."
        elif action == "watch":
            entry = "Watch only; require stronger placeholder trend/volume before manual review."
            invalidation = "Remove from watch if score falls below 5.25 in a future dry run."
            stop = "Not applicable while watch-only."
            take_profit = "Not applicable while watch-only."
        else:
            entry = "No entry; dry-run setup not acceptable."
            invalidation = "Not applicable."
            stop = "Not applicable."
            take_profit = "Not applicable."

        tickets.append(
            {
                "ticker": ticker,
                "action_label": action,
                "entry_zone_reference": entry,
                "invalidation_reference": invalidation,
                "stop_reference": stop,
                "take_profit_reference": take_profit,
                "suggested_position_pct": f"{position_pct:.2f}",
                "max_loss_pct_of_account": f"{max_loss_pct:.2f}",
                "reason": f"{row['theme']} dry-run score {row['total_score']} using static placeholders.",
                "risks": f"Placeholder data only; {seed['volatility_tier']} volatility tier; human must review liquidity, news, and market regime.",
                "manual_confirmation_required": "yes",
                "broker_connection_allowed": "no",
                "real_order_allowed_by_script": "no",
                "old_holding_data_used": "no",
            }
        )

    TICKETS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TICKETS_PATH.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TICKET_FIELDS)
        writer.writeheader()
        writer.writerows(tickets)

    lines = [
        "# Latest Phase 5R Manual Trade Tickets",
        "",
        f"Generated: `{timestamp()}`",
        "",
        "These are manual review tickets only. Scripts cannot connect to a broker or place orders.",
        "",
        "| Ticker | Action | Suggested Position % | Max Loss % | Reason |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for ticket in tickets:
        if ticket["action_label"] in {"possible_buy_manual_review", "watch"}:
            lines.append(
                f"| {ticket['ticker']} | {ticket['action_label']} | {ticket['suggested_position_pct']} | {ticket['max_loss_pct_of_account']} | {ticket['reason']} |"
            )
    lines.extend(
        [
            "",
            "Required constants for every CSV ticket: `manual_confirmation_required=yes`, `broker_connection_allowed=no`, `real_order_allowed_by_script=no`, `old_holding_data_used=no`.",
        ]
    )
    TICKETS_MD_PATH.parent.mkdir(parents=True, exist_ok=True)
    TICKETS_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    now = timestamp()
    safety = "manual_tickets_only=yes; broker_connection_allowed=no; real_order_allowed_by_script=no; old_iot_rbrk_data_used=no"
    for log_path in (AUDIT_TRAIL, RUN_LOG):
        append_csv(
            log_path,
            {
                "timestamp": now,
                "script_name": Path(__file__).name,
                "action": "create_phase5r_manual_trade_tickets",
                "input_path": f"{SCORES_PATH.relative_to(ROOT)};{UNIVERSE_PATH.relative_to(ROOT)}",
                "output_path": f"{TICKETS_PATH.relative_to(ROOT)};{TICKETS_MD_PATH.relative_to(ROOT)}",
                "status": "complete",
                "safety_notes": safety,
            },
            AUDIT_FIELDS,
        )
    print(f"Wrote {len(tickets)} manual trade ticket rows to {TICKETS_PATH}")


if __name__ == "__main__":
    main()
