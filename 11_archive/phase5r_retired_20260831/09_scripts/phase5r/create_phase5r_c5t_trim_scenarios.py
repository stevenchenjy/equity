from __future__ import annotations

import csv
import math
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POSITION_DIR = ROOT / "05_risk_and_positions"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
CONTROL_DIR = ROOT / "00_project_control"

LOCAL_POSITIONS = POSITION_DIR / "current_positions.local.csv"
C5_RECOMMENDATIONS = RESEARCH_DIR / "phase5r_c5_position_review_recommendations.csv"
CONCENTRATION_POLICY = CONTROL_DIR / "phase5r_c4_concentration_policy.md"
OUTPUT = POSITION_DIR / "phase5r_c5t_trim_scenario_table.csv"
RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c5t_run_log.csv"

FIELDS = [
    "scenario_order", "scenario_id", "ticker", "account_value_usd", "account_value_source",
    "current_position_pct", "current_estimated_value", "current_shares", "current_reference_price",
    "target_position_pct", "target_value", "approximate_shares_to_hold", "approximate_shares_to_trim",
    "estimated_remaining_position_pct", "estimated_cash_released", "scenario_total_sleeve_pct",
    "scenario_total_cash_released", "concentration_status_after", "fractional_shares_assumed",
    "pros", "risks", "human_decision_needed", "automatic_action_allowed",
]
LOG_FIELDS = [
    "timestamp", "phase", "script_name", "action", "input_paths", "output_paths", "status",
    "account_value_usd", "position_rows", "scenario_count", "scenario_rows", "email_sent",
    "scheduler_used", "broker_used", "smtp_config_modified", "archived_legacy_used", "safety_notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def extract_account_value(rows: list[dict[str, str]]) -> tuple[float, str]:
    values: list[float] = []
    pattern = re.compile(r"account value assumed\s+\$?([0-9,]+(?:\.[0-9]+)?)", re.IGNORECASE)
    for row in rows:
        match = pattern.search(row.get("notes", ""))
        if match:
            values.append(float(match.group(1).replace(",", "")))
    if values and all(math.isclose(value, values[0], abs_tol=0.01) for value in values):
        return values[0], "current_positions.local.csv notes"
    return 1000.0, "phase_default_fallback"


def extract_reference_price(row: dict[str, str], account_value: float) -> float:
    match = re.search(r"current visible price\s+\$?([0-9,]+(?:\.[0-9]+)?)", row.get("notes", ""), re.IGNORECASE)
    if match:
        return float(match.group(1).replace(",", ""))
    shares = float(row["shares_optional"])
    return account_value * float(row["position_pct"]) / 100.0 / shares


def concentration_status(position_pct: float) -> str:
    if position_pct > 8.0 + 1e-9:
        return "above_hard_cap"
    if position_pct > 6.0 + 1e-9:
        return "above_default_cap"
    return "within_default_cap"


def append_log(account_value: float, position_count: int, scenario_count: int, row_count: int) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = RUN_LOG.exists()
    with RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "timestamp": timestamp(), "phase": "phase5r_c5t", "script_name": Path(__file__).name,
            "action": "create_manual_trim_scenarios",
            "input_paths": ";".join(str(path.relative_to(ROOT)) for path in [LOCAL_POSITIONS, C5_RECOMMENDATIONS, CONCENTRATION_POLICY]),
            "output_paths": str(OUTPUT.relative_to(ROOT)), "status": "complete",
            "account_value_usd": f"{account_value:.2f}", "position_rows": str(position_count),
            "scenario_count": str(scenario_count), "scenario_rows": str(row_count),
            "email_sent": "no", "scheduler_used": "no", "broker_used": "no",
            "smtp_config_modified": "no", "archived_legacy_used": "no",
            "safety_notes": "scenario_only=yes; human_decision_required=yes; automatic_action_allowed=no",
        })


def main() -> None:
    positions = read_csv(LOCAL_POSITIONS)
    recommendations = {row["ticker"].upper(): row for row in read_csv(C5_RECOMMENDATIONS)}
    if {row["ticker"].upper() for row in positions} != set(recommendations):
        raise RuntimeError("Current local positions and C5 position recommendations must match")
    if any(row["recommendation_label"] != "trim_review" for row in recommendations.values()):
        raise RuntimeError("C5T requires current C5 trim_review labels")

    account_value, account_source = extract_account_value(positions)
    current_sleeve = sum(float(row["position_pct"]) for row in positions)
    position_data: list[dict[str, float | str]] = []
    for row in positions:
        ticker = row["ticker"].strip().upper()
        shares = float(row["shares_optional"])
        if shares <= 0:
            raise RuntimeError(f"Positive shares_optional is required for {ticker}")
        price = extract_reference_price(row, account_value)
        position_data.append({
            "ticker": ticker, "pct": float(row["position_pct"]), "shares": shares,
            "price": price, "value": shares * price,
        })

    scenario_specs = [
        (1, "no_action_until_next_review", "current", "Preserves exposure and allows the scheduled weekly review to occur.", "Both positions remain above the hard cap."),
        (2, "trim_to_active_stock_sleeve_target_30pct", "active_30", "Reduces the combined active sleeve to 30% while preserving current relative weights.", "Both positions remain above the 8% hard cap."),
        (3, "trim_each_position_to_8pct_hard_cap", "cap_8", "Brings each fractional-share estimate to the stated hard cap.", "Large concentration reduction may have tax, timing, and thesis-participation effects."),
        (4, "trim_each_position_to_6pct_default_cap", "cap_6", "Brings each fractional-share estimate to the default cap and creates the most concentration headroom.", "Largest reduction among fractional scenarios and greatest risk of reducing exposure before a favorable move."),
        (5, "whole_share_practical_scenario", "whole", "Uses whole shares and makes the fractional-share constraint visible.", "One RBRK share is about 8.88% of the assumed account, so retaining one share remains above the hard cap."),
        (6, "light_trim_review_25pct_of_each_position", "light_25", "Provides a gradual 25% reduction comparison without targeting a policy cap immediately.", "The active sleeve and both single-stock weights remain above policy limits."),
    ]

    rows: list[dict[str, str]] = []
    for order, scenario_id, mode, pros, risks in scenario_specs:
        pending: list[dict[str, float | str]] = []
        for position in position_data:
            pct = float(position["pct"])
            shares = float(position["shares"])
            price = float(position["price"])
            if mode == "current":
                shares_to_hold = shares
                target_pct = pct
            elif mode == "active_30":
                target_pct = pct * 30.0 / current_sleeve
                shares_to_hold = account_value * target_pct / 100.0 / price
            elif mode == "cap_8":
                target_pct = min(pct, 8.0)
                shares_to_hold = account_value * target_pct / 100.0 / price
            elif mode == "cap_6":
                target_pct = min(pct, 6.0)
                shares_to_hold = account_value * target_pct / 100.0 / price
            elif mode == "whole":
                cap_shares = math.floor(account_value * 0.08 / price)
                shares_to_hold = min(shares, float(max(1, cap_shares)))
                target_pct = shares_to_hold * price / account_value * 100.0
            else:
                shares_to_hold = shares * 0.75
                target_pct = pct * 0.75
            shares_to_hold = max(0.0, min(shares, shares_to_hold))
            shares_to_trim = shares - shares_to_hold
            remaining_value = shares_to_hold * price
            cash_released = shares_to_trim * price
            pending.append({
                **position, "target_pct": target_pct, "shares_to_hold": shares_to_hold,
                "shares_to_trim": shares_to_trim, "remaining_pct": remaining_value / account_value * 100.0,
                "target_value": remaining_value, "cash_released": cash_released,
            })
        total_sleeve = sum(float(item["remaining_pct"]) for item in pending)
        total_cash = sum(float(item["cash_released"]) for item in pending)
        for item in pending:
            rows.append({
                "scenario_order": str(order), "scenario_id": scenario_id, "ticker": str(item["ticker"]),
                "account_value_usd": f"{account_value:.2f}", "account_value_source": account_source,
                "current_position_pct": f"{float(item['pct']):.2f}",
                "current_estimated_value": f"{float(item['value']):.2f}",
                "current_shares": f"{float(item['shares']):.4f}",
                "current_reference_price": f"{float(item['price']):.2f}",
                "target_position_pct": f"{float(item['target_pct']):.2f}",
                "target_value": f"{float(item['target_value']):.2f}",
                "approximate_shares_to_hold": f"{float(item['shares_to_hold']):.4f}",
                "approximate_shares_to_trim": f"{float(item['shares_to_trim']):.4f}",
                "estimated_remaining_position_pct": f"{float(item['remaining_pct']):.2f}",
                "estimated_cash_released": f"{float(item['cash_released']):.2f}",
                "scenario_total_sleeve_pct": f"{total_sleeve:.2f}",
                "scenario_total_cash_released": f"{total_cash:.2f}",
                "concentration_status_after": concentration_status(float(item["remaining_pct"])),
                "fractional_shares_assumed": "no" if mode in {"current", "whole"} else "yes",
                "pros": pros, "risks": risks, "human_decision_needed": "yes",
                "automatic_action_allowed": "no",
            })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    append_log(account_value, len(position_data), len(scenario_specs), len(rows))
    print(f"Created C5T trim scenarios: scenarios={len(scenario_specs)} rows={len(rows)} account={account_value:.2f}")


if __name__ == "__main__":
    main()
