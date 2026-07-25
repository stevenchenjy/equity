from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "03_source_data" / "phase5r"
REVIEWS_DIR = ROOT / "08_reviews" / "current"
RUN_LOG = ROOT / "00_project_control" / "run_logs" / "phase5r_b2_run_log.csv"
UNIVERSE_PATH = DATA_DIR / "phase5r_universe_seed.csv"
SCORES_PATH = DATA_DIR / "phase5r_b2_signal_scores.csv"
TICKETS_PATH = DATA_DIR / "phase5r_b2_manual_trade_tickets.csv"
AUDIT_PATH = DATA_DIR / "phase5r_b2_audit_trail.csv"
TICKETS_MD_PATH = REVIEWS_DIR / "latest_phase5r_b2_manual_trade_tickets.md"

LEGACY_TICKERS = {"IOT", "RBRK"}
TICKET_FIELDS = [
    "ticker", "action_label", "entry_zone_reference", "invalidation_reference", "stop_reference", "take_profit_reference",
    "suggested_position_pct", "max_loss_pct_of_account", "reason", "risks", "manual_confirmation_required",
    "broker_connection_allowed", "real_order_allowed_by_script", "old_holding_data_used",
]
AUDIT_FIELDS = ["timestamp", "script_name", "action", "input_path", "output_path", "status", "safety_notes"]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def references(action: str, quality: str) -> tuple[str, str, str, str]:
    if action == "possible_buy_manual_review":
        return (
            "Review the latest public price, daily range, liquidity, market regime, and current company news before any manual decision.",
            "Reject the idea if the catalyst changes, data quality weakens, or the independently reviewed setup no longer fits the risk policy.",
            "Human-defined stop after independent review only; this script cannot create, route, or transmit one.",
            "Human-defined exit plan after independent review only; this script cannot create, route, or transmit one.",
        )
    if action == "watch":
        return ("Watch only; require a later independent review before any manual action.", "Remove from watch if the daily score or data quality deteriorates.", "Not applicable while watch-only.", "Not applicable while watch-only.")
    if quality == "insufficient_data":
        return ("No entry; public market data is incomplete.", "Wait for a later complete daily refresh and independently verify the data.", "Not applicable.", "Not applicable.")
    return ("No entry; daily research score is below the manual-review threshold.", "Not applicable.", "Not applicable.", "Not applicable.")


def main() -> None:
    universe = {row["ticker"].upper(): row for row in read_csv(UNIVERSE_PATH)}
    tickets: list[dict[str, str]] = []
    for score in read_csv(SCORES_PATH):
        ticker = score["ticker"].upper()
        if ticker in LEGACY_TICKERS:
            raise RuntimeError("Legacy IOT/RBRK tickers are excluded from Phase 5R-B2 tickets")
        seed = universe[ticker]
        action = score["action_label"]
        total = float(score["total_score"])
        suggested = min(float(seed["max_position_pct"]), 2.0 if total >= 8.0 else 1.0) if action == "possible_buy_manual_review" else 0.0
        maximum_loss = min(0.50, round(suggested * 0.20, 2)) if suggested else 0.0
        entry, invalidation, stop, take_profit = references(action, score["data_quality_label"])
        tickets.append({
            "ticker": ticker, "action_label": action, "entry_zone_reference": entry, "invalidation_reference": invalidation,
            "stop_reference": stop, "take_profit_reference": take_profit, "suggested_position_pct": f"{suggested:.2f}",
            "max_loss_pct_of_account": f"{maximum_loss:.2f}",
            "reason": f"{score['theme']} daily research score {score['total_score']} using {score['data_source']} with {score['data_quality_label']} quality.",
            "risks": f"Public data may be delayed or incomplete; {seed['volatility_tier']} volatility tier; independent human review is required.",
            "manual_confirmation_required": "yes", "broker_connection_allowed": "no", "real_order_allowed_by_script": "no", "old_holding_data_used": "no",
        })
    write_csv(TICKETS_PATH, tickets, TICKET_FIELDS)
    lines = [
        "# Latest Phase 5R-B2 Manual Trade Tickets", "", f"Generated: `{timestamp()}`", "",
        "Manual review records only. They cannot access a broker, place an order, send an email, or use legacy holdings.", "",
        "| Ticker | Action | Suggested Position % | Max Loss % | Data Review Reason |", "| --- | --- | ---: | ---: | --- |",
    ]
    for ticket in tickets:
        lines.append(f"| {ticket['ticker']} | {ticket['action_label']} | {ticket['suggested_position_pct']} | {ticket['max_loss_pct_of_account']} | {ticket['reason']} |")
    lines.extend(["", "Every ticket retains: `manual_confirmation_required=yes`, `broker_connection_allowed=no`, `real_order_allowed_by_script=no`, and `old_holding_data_used=no`."])
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    TICKETS_MD_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    audit = {
        "timestamp": timestamp(), "script_name": Path(__file__).name, "action": "create_phase5r_b2_manual_trade_tickets",
        "input_path": f"{SCORES_PATH.relative_to(ROOT)};{UNIVERSE_PATH.relative_to(ROOT)}",
        "output_path": f"{TICKETS_PATH.relative_to(ROOT)};{TICKETS_MD_PATH.relative_to(ROOT)}", "status": "complete",
        "safety_notes": "manual_tickets_only=yes; manual_confirmation_required=yes; broker_connection_allowed=no; real_order_allowed_by_script=no; old_holding_data_used=no; no_email=yes; archived_legacy_used=no",
    }
    for path in (AUDIT_PATH, RUN_LOG):
        exists = path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow(audit)
    print(f"Wrote Phase 5R-B2 manual ticket rows: {len(tickets)}")


if __name__ == "__main__":
    main()
