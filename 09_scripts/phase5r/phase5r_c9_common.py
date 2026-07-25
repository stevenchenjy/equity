from __future__ import annotations

import csv
import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
POSITION_DIR = ROOT / "05_risk_and_positions"
DATA_DIR = ROOT / "03_source_data" / "phase5r"
RESEARCH_DIR = ROOT / "04_research" / "realtime_stock_picker_phase5r"
SCHEDULER_DIR = ROOT / "07_automation" / "scheduler"

ACCOUNT_STATE = POSITION_DIR / "current_account_state.local.json"
CURRENT_POSITIONS = POSITION_DIR / "current_positions.local.csv"
MARKET_SNAPSHOT = DATA_DIR / "phase5r_b2_market_data_snapshot.csv"
MARKET_QUALITY = DATA_DIR / "phase5r_b2_market_data_quality_report.csv"
C5_PACKETS = RESEARCH_DIR / "phase5r_c5_company_research_packets.csv"
C9_INHIBIT = SCHEDULER_DIR / "phase5r_c9_maintenance_inhibit.local.json"
C9_RUN_LOG = CONTROL_DIR / "run_logs" / "phase5r_c9_run_log.csv"

DYNAMIC_WEIGHTS = POSITION_DIR / "phase5r_c9_dynamic_position_weights.csv"
PORTFOLIO_SUMMARY = POSITION_DIR / "phase5r_c9_current_portfolio_summary.csv"
EXACT_ACTION_PLAN = POSITION_DIR / "phase5r_c9_exact_action_plan.csv"
CASH_DEPLOYMENT_PLAN = POSITION_DIR / "phase5r_c9_cash_deployment_plan.csv"
TARGET_ALLOCATION_REPORT = POSITION_DIR / "phase5r_c9_target_allocation_report.csv"
REVIEW_QUEUE = POSITION_DIR / "phase5r_c9_account_aware_review_queue.csv"
WEEKLY_DECISION_SUMMARY = POSITION_DIR / "phase5r_c9_weekly_decision_summary.md"

C9_SCORES = RESEARCH_DIR / "phase5r_c9_account_aware_conviction_scores.csv"
C9_POSITION_RECOMMENDATIONS = RESEARCH_DIR / "phase5r_c9_position_recommendations.csv"
C9_NEW_RECOMMENDATIONS = RESEARCH_DIR / "phase5r_c9_new_candidate_recommendations.csv"
C9_MEMO = RESEARCH_DIR / "phase5r_c9_account_aware_memo.md"
C9_ALLOCATION_REPORT = RESEARCH_DIR / "phase5r_c9_allocation_report.md"

ACCOUNT_FIELDS = {
    "account_total_value",
    "prior_account_value",
    "new_external_cash",
    "cash_available",
    "cash_reserved",
    "investment_horizon_years",
    "cash_needed_within_three_years",
    "core_allocation_target_pct",
    "active_stock_target_pct",
    "active_stock_hard_cap_pct",
    "cash_target_pct",
    "single_stock_default_cap_pct",
    "single_stock_hard_cap_pct",
    "last_updated",
}
NUMERIC_ACCOUNT_FIELDS = ACCOUNT_FIELDS - {"cash_needed_within_three_years", "last_updated"}
POSITION_REQUIRED_FIELDS = {
    "ticker",
    "entry_date",
    "entry_price",
    "position_pct",
    "shares_optional",
    "thesis",
    "horizon_class",
    "planned_review_date",
    "invalidation_rule",
}
RUN_LOG_FIELDS = [
    "timestamp",
    "phase",
    "script_name",
    "action",
    "status",
    "input_paths",
    "output_paths",
    "account_total_value",
    "cash_available",
    "position_count",
    "email_sent",
    "c7_mode",
    "d3_inhibit_active",
    "broker_used",
    "order_code_created",
    "archived_legacy_used",
    "notes",
]


def timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def csv_fields(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle).fieldnames or [])


def write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def as_float(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def load_account_state() -> dict[str, object]:
    if not ACCOUNT_STATE.exists():
        raise FileNotFoundError("current_account_state.local.json is required")
    try:
        state = json.loads(ACCOUNT_STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("current account state is invalid JSON") from exc
    if not isinstance(state, dict) or set(state) != ACCOUNT_FIELDS:
        raise ValueError("current account state fields do not match the C9 contract")
    for field in NUMERIC_ACCOUNT_FIELDS:
        value = as_float(state[field], field)
        if value < 0:
            raise ValueError(f"{field} cannot be negative")
    if as_float(state["account_total_value"], "account_total_value") <= 0:
        raise ValueError("account_total_value must be positive")
    contribution_history = (
        as_float(state["prior_account_value"], "prior_account_value")
        + as_float(state["new_external_cash"], "new_external_cash")
    )
    if contribution_history <= 0:
        raise ValueError("prior account value plus new external cash must be positive")
    if as_float(state["cash_reserved"], "cash_reserved") > as_float(state["cash_available"], "cash_available"):
        raise ValueError("cash_reserved cannot exceed cash_available")
    allocation_total = sum(
        as_float(state[field], field)
        for field in ("core_allocation_target_pct", "active_stock_target_pct", "cash_target_pct")
    )
    if not math.isclose(allocation_total, 100.0, abs_tol=0.01):
        raise ValueError("core active-stock and cash targets must sum to 100")
    if as_float(state["active_stock_target_pct"], "active_stock_target_pct") > as_float(
        state["active_stock_hard_cap_pct"], "active_stock_hard_cap_pct"
    ):
        raise ValueError("active-stock target cannot exceed its hard cap")
    if as_float(state["single_stock_default_cap_pct"], "single_stock_default_cap_pct") > as_float(
        state["single_stock_hard_cap_pct"], "single_stock_hard_cap_pct"
    ):
        raise ValueError("single-stock default cap cannot exceed its hard cap")
    if state["cash_needed_within_three_years"] != "no":
        raise ValueError("C9 requires cash_needed_within_three_years=no for this confirmed state")
    updated = state["last_updated"]
    if not isinstance(updated, str):
        raise ValueError("last_updated must be an ISO timestamp")
    try:
        parsed = datetime.fromisoformat(updated)
    except ValueError as exc:
        raise ValueError("last_updated must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("last_updated must include a timezone")
    return state


def load_positions() -> list[dict[str, object]]:
    if not CURRENT_POSITIONS.exists():
        raise FileNotFoundError("current_positions.local.csv is required")
    fields = set(csv_fields(CURRENT_POSITIONS))
    missing = POSITION_REQUIRED_FIELDS - fields
    if missing:
        raise ValueError("current positions missing fields: " + ",".join(sorted(missing)))
    parsed: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in read_csv(CURRENT_POSITIONS):
        ticker = row["ticker"].strip().upper()
        if not ticker or ticker in seen:
            raise ValueError("current position tickers must be non-empty and unique")
        seen.add(ticker)
        shares = as_float(row["shares_optional"], f"{ticker}.shares_optional")
        if shares <= 0:
            raise ValueError(f"{ticker} shares must be positive")
        historical_pct = as_float(row["position_pct"], f"{ticker}.position_pct")
        parsed.append(
            {
                "ticker": ticker,
                "shares": shares,
                "stored_historical_position_pct": historical_pct,
                "entry_date": row["entry_date"].strip(),
                "entry_price": as_float(row["entry_price"], f"{ticker}.entry_price"),
                "thesis": row["thesis"].strip(),
                "horizon_class": row["horizon_class"].strip(),
                "planned_review_date": row["planned_review_date"].strip(),
                "invalidation_rule": row["invalidation_rule"].strip(),
            }
        )
    if not parsed:
        raise ValueError("at least one current position is required")
    return parsed


def load_market_rows(required_tickers: Iterable[str]) -> dict[str, dict[str, str]]:
    if not MARKET_SNAPSHOT.exists():
        raise FileNotFoundError("canonical B2 market snapshot is required")
    selected: dict[str, dict[str, str]] = {}
    for row in read_csv(MARKET_SNAPSHOT):
        ticker = row.get("ticker", "").strip().upper()
        if not ticker:
            continue
        if ticker in selected:
            raise ValueError(f"duplicate B2 market row for {ticker}")
        selected[ticker] = row
    for ticker in sorted(set(required_tickers)):
        row = selected.get(ticker)
        if row is None:
            raise ValueError(f"canonical B2 market snapshot is missing {ticker}")
        if row.get("data_quality_label") != "ok":
            raise ValueError(f"canonical B2 market row for {ticker} is not quality=ok")
        if as_float(row.get("last_price"), f"{ticker}.last_price") <= 0:
            raise ValueError(f"canonical B2 market price for {ticker} must be positive")
        if not row.get("data_timestamp", "").strip() or not row.get("data_source", "").strip():
            raise ValueError(f"canonical B2 market row for {ticker} lacks provenance")
    return selected


def load_packets() -> dict[str, dict[str, str]]:
    packets: dict[str, dict[str, str]] = {}
    for row in read_csv(C5_PACKETS):
        ticker = row.get("ticker", "").strip().upper()
        if not ticker or ticker in packets:
            raise ValueError("C5 packet tickers must be non-empty and unique")
        packets[ticker] = row
    return packets


def load_active_inhibit() -> dict[str, object]:
    try:
        state = json.loads(C9_INHIBIT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("C9 maintenance inhibit is missing or invalid") from exc
    if not isinstance(state, dict):
        raise ValueError("C9 maintenance inhibit must be an object")
    active = state.get("active")
    allowed_pipeline = state.get("allowed_pipeline")
    if active is True and allowed_pipeline != "none":
        raise ValueError("active C9 maintenance must allow no pipeline")
    if active is False and allowed_pipeline != "phase5r_daily":
        raise ValueError("cleared C9 maintenance must authorize only phase5r_daily")
    if not isinstance(active, bool):
        raise ValueError("C9 maintenance active flag must be boolean")
    return state


def concentration_status(weight: float, account: dict[str, object]) -> str:
    hard = as_float(account["single_stock_hard_cap_pct"], "single_stock_hard_cap_pct")
    default = as_float(account["single_stock_default_cap_pct"], "single_stock_default_cap_pct")
    if weight > hard + 1e-9:
        return "above_hard_cap"
    if weight > default + 1e-9:
        return "above_default_cap"
    return "within_default_cap"


def dynamic_position_fit(weight: float, account: dict[str, object]) -> float:
    status = concentration_status(weight, account)
    return {"above_hard_cap": 2.0, "above_default_cap": 6.0, "within_default_cap": 8.0}[status]


def dynamic_candidate_fit(theme: str, active_weight: float, account: dict[str, object]) -> float:
    target = as_float(account["active_stock_target_pct"], "active_stock_target_pct")
    hard = as_float(account["active_stock_hard_cap_pct"], "active_stock_hard_cap_pct")
    fit = 7.0 if active_weight <= target + 1e-9 else 5.0 if active_weight <= hard + 1e-9 else 1.0
    if theme == "AI infrastructure":
        fit -= 2.0
    return max(1.0, min(10.0, fit))


def score_from_packet(packet: dict[str, str], portfolio_fit: float) -> float:
    components = [
        as_float(packet["business_quality_score"], "business_quality_score"),
        as_float(packet["earnings_revenue_trend_score"], "earnings_revenue_trend_score"),
        as_float(packet["valuation_reasonableness_score"], "valuation_reasonableness_score"),
        as_float(packet["catalyst_news_quality_score"], "catalyst_news_quality_score"),
        as_float(packet["technical_entry_discipline_score"], "technical_entry_discipline_score"),
    ]
    return round(
        0.25 * components[0]
        + 0.20 * components[1]
        + 0.15 * components[2]
        + 0.15 * components[3]
        + 0.15 * components[4]
        + 0.10 * portfolio_fit,
        2,
    )


def next_thursday(reference: date | None = None) -> str:
    current = reference or date.today()
    days = (3 - current.weekday()) % 7
    if days == 0:
        days = 7
    return (current + timedelta(days=days)).isoformat()


def append_run_log(
    script_name: str,
    action: str,
    status: str,
    inputs: Iterable[Path],
    outputs: Iterable[Path],
    *,
    position_count: int = 0,
    notes: str = "",
    c7_mode: str = "not_invoked",
) -> None:
    account_total = ""
    cash_available = ""
    try:
        account = load_account_state()
        account_total = f"{as_float(account['account_total_value'], 'account_total_value'):.2f}"
        cash_available = f"{as_float(account['cash_available'], 'cash_available'):.2f}"
    except (FileNotFoundError, ValueError):
        pass
    inhibit_active = "no"
    try:
        inhibit_active = "yes" if load_active_inhibit().get("active") is True else "no"
    except ValueError:
        inhibit_active = "invalid"
    C9_RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    exists = C9_RUN_LOG.exists() and C9_RUN_LOG.stat().st_size > 0
    with C9_RUN_LOG.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUN_LOG_FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow(
            {
                "timestamp": timestamp(),
                "phase": "phase5r_c9",
                "script_name": script_name,
                "action": action,
                "status": status,
                "input_paths": ";".join(str(path.relative_to(ROOT)) for path in inputs),
                "output_paths": ";".join(str(path.relative_to(ROOT)) for path in outputs),
                "account_total_value": account_total,
                "cash_available": cash_available,
                "position_count": str(position_count),
                "email_sent": "no",
                "c7_mode": c7_mode,
                "d3_inhibit_active": inhibit_active,
                "broker_used": "no",
                "order_code_created": "no",
                "archived_legacy_used": "no",
                "notes": notes,
            }
        )
