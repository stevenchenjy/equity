#!/usr/bin/env python3
"""Create one decisive daily research conclusion and its email brief.

The output is research for human review, never a buy/sell command. HOLD and
WATCH do not require manual confirmation. Only portfolio-action transitions,
material evidence ambiguity, or account conflicts are escalated.
"""

from __future__ import annotations

from equity_naming import report_heading

import argparse
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from phase5r_daily_common import (
    ACCOUNT_STATE_PATH,
    DAILY_BRIEF_HTML_PATH,
    DAILY_BRIEF_TEXT_PATH,
    DAILY_DECISION_JSON_PATH,
    DAILY_DECISION_REPORT_PATH,
    DAILY_DECISION_STATE_PATH,
    EVIDENCE_LEDGER_PATH,
    EVIDENCE_STATUS_PATH,
    EXACT_ACTION_PATH,
    FUNDAMENTALS_PATH,
    MARKET_QUALITY_PATH,
    MARKET_SNAPSHOT_PATH,
    NEW_CANDIDATE_PATH,
    POSITION_RECOMMENDATION_PATH,
    PORTFOLIO_SUMMARY_PATH,
    POST_ACTION_PORTFOLIO_PATH,
    RECONCILIATION_PATH,
    ROOT,
    atomic_write_json,
    atomic_write_text,
    canonical_sha256,
    cycle_date,
    latest_published_market_session,
    iso_now,
    load_active_state,
    load_inhibit,
    notification_delivery_policy,
    notification_change_comparison,
    LEGACY_NOTIFICATION_MODE,
    WATCH_ACTION_NOTIFICATION_MODE,
    now_et,
    read_csv,
    read_json,
    sha256_file,
    log_daily_run,
    weekly_summary_due_for_published_session,
)
from phase5r_c9_common import is_core_allocation_ticker, load_account_state
from phase5r_active_config import load_active_config
from phase5r_c9b_common import applied_reconciliation_matches_current_state
from phase5r_email_brief import EMAIL_BRIEF_VERSION, render_email
from phase5r_market_regime import load_regime_controls
from phase5r_official_news import read_official_news_status
from update_phase5r_manual_account import current_manual_snapshot_matches
from create_phase5r_long_horizon_research import SIGNAL_LABELS, missing_label


CONFIRMED_EXECUTION_PATH = (
    ROOT / "06_execution_records" / "phase5r_c9b_confirmed_execution_report.csv"
)
PENDING_EXECUTION_PATH = (
    ROOT / "06_execution_records" / "phase5r_c9b_pending_execution_report.csv"
)
CANDIDATE_STABILITY_VERSION = "phase5r_candidate_stability_v2"
LONG_HORIZON_PATH = ROOT / "04_research" / "realtime_stock_picker_phase5r" / "phase5r_long_horizon_research.local.json"


def is_action_transition(action: str) -> bool:
    normalized = action.strip().lower()
    return any(
        token in normalized
        for token in ("add", "trim", "exit", "reduce", "sell", "buy")
    ) and normalized not in {"watch_only", "hold"}


def latest_applied_execution(
    rows: list[dict[str, str]],
) -> dict[str, str] | None:
    eligible = [
        (index, row)
        for index, row in enumerate(rows)
        if row.get("order_status", "").strip().lower()
        in {"filled", "partial_fill"}
        and row.get("canonical_state_applied", "").strip().lower() == "yes"
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (item[1].get("fill_date", "").strip(), item[0]),
    )[1]


def recent_applied_execution(current: datetime) -> dict[str, str]:
    """Presentation-only receipt from structured, already reconciled records."""
    row = latest_applied_execution(read_csv(CONFIRMED_EXECUTION_PATH))
    if not row:
        return {}
    try:
        age = (current.date() - date.fromisoformat(row.get("fill_date", ""))).days
    except ValueError:
        return {}
    if not 0 <= age <= 7:
        return {}
    reconciliation = next((item for item in read_csv(RECONCILIATION_PATH)
                           if item.get("execution_id") == row.get("execution_id")), {})
    if (reconciliation.get("reconciliation_status") != "applied"
            or reconciliation.get("canonical_state_applied") != "yes"):
        return {}
    result = {key: row.get(key, "") for key in (
        "execution_id", "ticker", "side", "shares", "fill_date", "fill_price",
    )}
    # Unknown or mismatched cash reconciliation must never imply zero fees.
    try:
        before = Decimal(reconciliation.get("cash_before", ""))
        after = Decimal(reconciliation.get("selected_cash_after", ""))
        difference = Decimal(reconciliation.get("cash_reconciliation_difference", ""))
        if before.is_finite() and after.is_finite() and difference == 0:
            result["net_cash_change"] = str(after - before)
    except InvalidOperation:
        pass
    return result


def load_market_gate(current: datetime, held_tickers: list[str]) -> dict[str, Any]:
    rows = {row.get("ticker", "").upper(): row for row in read_csv(MARKET_SNAPSHOT_PATH)}
    quality = {
        row.get("ticker", "").upper(): row for row in read_csv(MARKET_QUALITY_PATH)
    }
    failures: list[str] = []
    session_dates: dict[str, str] = {}
    expected = latest_published_market_session(current).isoformat()
    for ticker in held_tickers:
        row = rows.get(ticker)
        quality_row = quality.get(ticker)
        if not row:
            failures.append(f"{ticker}:market_row_missing")
            continue
        session_date = row.get("market_session_date", "").strip()
        session_dates[ticker] = session_date
        if not session_date:
            failures.append(f"{ticker}:market_session_date_missing")
        elif session_date != expected:
            failures.append(f"{ticker}:expected_{expected}_got_{session_date}")
        if row.get("data_quality_label", "").lower() != "ok":
            failures.append(f"{ticker}:market_quality_not_ok")
        if not quality_row or quality_row.get("usable_for_scoring", "").lower() != "yes":
            failures.append(f"{ticker}:not_usable_for_scoring")
    expected_date = date.fromisoformat(expected)
    session_closed = (
        current.date() > expected_date
        or (
            current.date() == expected_date
            and current.strftime("%H:%M") >= "16:15"
        )
    )
    complete_close_verified = not failures and session_closed
    return {
        "passed": not failures,
        "expected_market_session": expected,
        "held_session_dates": session_dates,
        "bar_state": (
            "complete_close"
            if complete_close_verified
            else "intraday_or_unverified"
        ),
        "complete_close_verified": complete_close_verified,
        "failures": failures,
        "source": str(MARKET_SNAPSHOT_PATH.relative_to(ROOT)),
    }


def execution_conflicts() -> list[str]:
    conflicts: list[str] = []
    pending = [
        row.get("execution_id", "").strip()
        for row in read_csv(PENDING_EXECUTION_PATH)
        if row.get("execution_id", "").strip()
    ]
    conflicts.extend(f"pending_execution:{value}" for value in pending)
    reconciliations = {
        row.get("execution_id", "").strip(): row
        for row in read_csv(RECONCILIATION_PATH)
        if row.get("execution_id", "").strip()
    }
    current_positions_hash = sha256_file(
        ROOT / "05_risk_and_positions" / "current_positions.local.csv"
    )
    current_account_hash = sha256_file(ACCOUNT_STATE_PATH)
    current_account = load_account_state()
    confirmed_rows = read_csv(CONFIRMED_EXECUTION_PATH)
    for row in confirmed_rows:
        execution_id = row.get("execution_id", "").strip()
        status = row.get("order_status", "").strip().lower()
        if status not in {"filled", "partial_fill"}:
            continue
        if row.get("canonical_state_applied", "").strip().lower() != "yes":
            conflicts.append(f"confirmed_not_applied:{execution_id}")
            continue
        reconciliation = reconciliations.get(execution_id)
        if not reconciliation:
            continue
        if reconciliation.get("reconciliation_status", "").strip().lower() != "applied":
            conflicts.append(f"reconciliation_not_applied:{execution_id}")
    # Reconciliation hashes are point-in-time evidence.  A later applied fill
    # necessarily changes the whole positions/account files, so only the most
    # recent applied transition can be required to match current canonical
    # state.  Older confirmed rows remain historical evidence and are never
    # rewritten merely because a later fill occurred.
    latest = latest_applied_execution(confirmed_rows)
    if latest and not current_manual_snapshot_matches(current_positions_hash, current_account_hash):
        latest_id = latest.get("execution_id", "").strip()
        reconciliation = reconciliations.get(latest_id)
        if not reconciliation:
            conflicts.append(f"reconciliation_missing:{latest_id}")
        else:
            if (
                reconciliation.get("positions_sha256_after", "").strip()
                != current_positions_hash
            ):
                conflicts.append(f"positions_hash_mismatch:{latest_id}")
            if not applied_reconciliation_matches_current_state(
                reconciliation,
                current_positions_sha256=current_positions_hash,
                current_account_sha256=current_account_hash,
                current_account_last_updated=current_account["last_updated"],
            ):
                conflicts.append(f"account_hash_mismatch:{latest_id}")
    return sorted(set(conflicts))


def material_events_for_cycle(
    notification_policy: dict[str, Any],
) -> list[dict[str, str]]:
    current_cycle = cycle_date()
    current_day = date.fromisoformat(current_cycle)
    lookback_days = int(notification_policy["new_filing_lookback_calendar_days"])
    earliest_filing_day = current_day - timedelta(days=lookback_days)
    events: list[dict[str, str]] = []
    for row in read_csv(EVIDENCE_LEDGER_PATH):
        if (
            row.get("cycle_date") != current_cycle
            or row.get("is_new") != "yes"
            or row.get("material_event") != "yes"
        ):
            continue
        try:
            filing_day = date.fromisoformat(row.get("filing_date", ""))
        except ValueError:
            continue
        if earliest_filing_day <= filing_day <= current_day:
            events.append(row)
    return events


def normalized_held_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    recommendations = {
        row.get("ticker", "").strip().upper(): row
        for row in read_csv(POSITION_RECOMMENDATION_PATH)
    }
    for row in read_csv(EXACT_ACTION_PATH):
        action = row.get("recommended_action", "").strip().lower() or "hold"
        recommendation = recommendations.get(row.get("ticker", "").strip().upper(), {})
        rows.append(
            {
                "ticker": row.get("ticker", "").strip().upper(),
                "asset_role": row.get("asset_role", "active_stock"),
                "action": action,
                "current_shares": row.get("current_shares", ""),
                "current_price": row.get("current_price", ""),
                "current_weight_pct": row.get("current_weight_pct", ""),
                "target_shares": row.get("target_shares", ""),
                "whole_shares_to_change": row.get("whole_shares_to_change", ""),
                "confidence": row.get("recommendation_confidence", ""),
                "reason": row.get("reason", ""),
                "invalidation": row.get("invalidation_price_or_condition", ""),
                "holding_horizon": row.get("holding_horizon", ""),
                "valuation_bear_price": recommendation.get("valuation_bear_price", ""),
                "valuation_base_price": recommendation.get("valuation_base_price", ""),
                "valuation_bull_price": recommendation.get("valuation_bull_price", ""),
                "expected_upside_pct": recommendation.get("expected_upside_pct", ""),
                "reward_to_risk_estimate": recommendation.get("reward_to_risk_estimate", ""),
                "strongest_positive_evidence": recommendation.get("strongest_positive_evidence", ""),
                "strongest_negative_evidence": recommendation.get("strongest_negative_evidence", ""),
                "valuation_source": recommendation.get("valuation_source", ""),
                "human_confirmation_required": (
                    "yes" if is_action_transition(action) else "no"
                ),
                "automatic_action_allowed": "no",
            }
        )
    return rows


def action_stability(
    state: dict[str, Any], held_rows: list[dict[str, Any]], market_session: str
) -> tuple[int, str]:
    proposals = [
        {
            "ticker": row["ticker"],
            "action": row["action"],
            "change": row["whole_shares_to_change"],
        }
        for row in held_rows
        if is_action_transition(row["action"])
    ]
    fingerprint = canonical_sha256(proposals)
    prior_fingerprint = state.get("action_proposal_fingerprint", "")
    prior_session = state.get("action_proposal_session", "")
    prior_count = int(state.get("action_proposal_distinct_closes", 0) or 0)
    if not proposals:
        return 0, fingerprint
    if not market_session:
        return (prior_count if fingerprint == prior_fingerprint else 0), fingerprint
    if fingerprint == prior_fingerprint:
        count = prior_count + (1 if market_session != prior_session else 0)
    else:
        count = 1
    return count, fingerprint


def candidate_proposal_fingerprint(row: dict[str, Any]) -> str:
    """Identify an investment proposal independently of its latest market quote."""
    def number(value: Any) -> str:
        try:
            parsed = Decimal(str(value))
            return format(parsed.normalize(), "f") if parsed.is_finite() else ""
        except InvalidOperation:
            return ""

    return canonical_sha256({
        "ticker": str(row.get("ticker", "")).strip().upper(),
        "action": row.get("recommended_action", ""),
        "eligibility": row.get("eligibility_label", ""),
        "shares": number(row.get("suggested_whole_shares", "")),
        "sizing_tier": row.get("sizing_tier", ""),
        "confidence": row.get("recommendation_confidence", ""),
        "valuation_applicability": row.get("valuation_applicability", ""),
        "valuation_prices": [number(row.get(key, "")) for key in (
            "valuation_bear_price", "valuation_base_price", "valuation_bull_price",
        )],
        "valuation_source": row.get("valuation_source", ""),
        "valuation_evidence_id": row.get("valuation_evidence_id", ""),
        "invalidation_condition": row.get("invalidation_condition", ""),
        "holding_horizon": row.get("holding_horizon", ""),
    })


def candidate_stability(
    state: dict[str, Any], proposals: list[dict[str, Any]], market_session: str,
    *, valid_close: bool,
) -> dict[str, Any]:
    """Track each currently eligible proposal on distinct, ordered valid closes.

    Old aggregate state is deliberately discarded. Removing a candidate or
    failing an evidence gate breaks its run; another candidate changing does
    not. Repeated runs or older sessions can never increment the counter.
    """
    prior = state.get("new_candidate_stability", {})
    prior_rows = prior.get("proposals", {}) if (
        isinstance(prior, dict) and prior.get("schema_version") == CANDIDATE_STABILITY_VERSION
    ) else {}
    if not isinstance(prior_rows, dict):
        prior_rows = {}
    current_rows: dict[str, Any] = {}
    for row in proposals:
        ticker = str(row.get("ticker", "")).strip().upper()
        if not ticker or ticker in current_rows:
            raise ValueError("candidate stability requires unique non-empty tickers")
        fingerprint = candidate_proposal_fingerprint(row)
        previous = prior_rows.get(ticker, {})
        if not isinstance(previous, dict):
            previous = {}
        count = 0
        observed_session = ""
        if valid_close and market_session:
            date.fromisoformat(market_session)
            observed_session = market_session
            count = 1
            if fingerprint == previous.get("fingerprint"):
                previous_session = str(previous.get("last_valid_session", ""))
                try:
                    previous_count = max(0, int(previous.get("distinct_closes", 0)))
                except (ValueError, TypeError):
                    previous_count = 0
                if previous_session and market_session >= previous_session:
                    count = previous_count + (market_session > previous_session)
                elif previous_session:
                    # Out-of-order data is not a valid continuation.
                    count = 0
                    observed_session = ""
        current_rows[ticker] = {
            "fingerprint": fingerprint, "last_valid_session": observed_session,
            "distinct_closes": count,
        }
    return {"schema_version": CANDIDATE_STABILITY_VERSION, "proposals": current_rows}


def held_research_context(
    report: dict[str, Any], held_rows: list[dict[str, Any]], expected_session: str,
) -> dict[str, Any]:
    """Expose unresolved investment evidence without turning warnings into exits."""
    current = bool(expected_session) and report.get("market_session_date") == expected_session
    companies = report.get("companies", {}) if current else {}
    if not isinstance(companies, dict):
        companies = {}
    warnings = []
    for row in held_rows:
        if row.get("asset_role") == "core_allocation":
            continue
        ticker = row["ticker"]
        company = companies.get(ticker, {})
        readiness = company.get("readiness", "pending_research")
        signals = [
            signal for signal in company.get("review_signals", [])
            if isinstance(signal, dict) and signal.get("status") == "review_required"
        ]
        if readiness == "pending_research" or signals:
            warning = {
                "ticker": ticker, "readiness": readiness,
                "missing_evidence": company.get("missing_evidence", []) if current else ["current_long_horizon_report"],
                "review_signals": signals,
                "thesis_break_confirmed": False,
            }
            warnings.append(warning)
            if row.get("action") in {"hold", "hold_pending_research"}:
                row["action"] = "hold_pending_research"
                row["human_confirmation_required"] = "no"
                row["research_review_required"] = True
                row["research_review_reason"] = (
                    "Long-horizon evidence remains incomplete or requires research review; "
                    "unchanged shares do not confirm the investment thesis."
                )
    return {
        "status": "current" if current else "unavailable_or_stale",
        "market_session_date": report.get("market_session_date", ""),
        "warnings": warnings,
        "action_authority": False,
    }


def official_news_context(current: datetime, held_company_tickers: list[str] | None = None) -> dict[str, Any]:
    try:
        result = read_official_news_status(now=current)
    except (OSError, ValueError) as exc:
        result = {
            "status": "missing", "required_coverage_complete": False,
            "reason": f"official_news_status_unavailable:{type(exc).__name__}",
            "coverage_scope": "configured_official_issuer_sources_only",
            "recent_event_count": 0, "new_event_count": 0, "recent_events": [],
        }
    covered = {
        str(row.get("ticker", "")).upper() for row in result.get("sources", [])
        if isinstance(row, dict)
    }
    unconfigured = sorted(set(held_company_tickers or []) - covered)
    result["unconfigured_held_tickers"] = unconfigured
    if unconfigured:
        result["required_coverage_complete"] = False
        if result.get("status") == "ok":
            result["status"] = "degraded"
    return result


def research_warning_lines(context: dict[str, Any]) -> str:
    lines: list[str] = []
    for row in context.get("warnings", []):
        ticker = row["ticker"]
        missing = [missing_label(str(value)) for value in row.get("missing_evidence", [])]
        if missing:
            details = "；".join(missing[:3])
            remaining = f"；另有 {len(missing) - 3} 项待补证据" if len(missing) > 3 else ""
            lines.append(f"- {ticker} 研究待补：{details}{remaining}。")
        for signal in row.get("review_signals", []):
            observations = signal.get("observations", {})
            if "share_dilution_pct" in observations:
                evidence = f"股数同比增幅 {observations['share_dilution_pct']}%"
            elif "decline_percentage_points" in observations:
                evidence = (
                    f"前季 {observations.get('previous')}% → 本期 {observations.get('current')}%，"
                    f"下降 {observations['decline_percentage_points']} 个百分点；"
                    f"比较期间 {observations.get('previous_period_end', '未知')}"
                )
            elif "latest_growth_pct" in observations:
                evidence = f"本期收入同比 {observations['latest_growth_pct']}%，TTM 同比 {observations.get('ttm_growth_pct')}%"
            elif "revenue_yoy_pct" in observations:
                evidence = f"收入同比 {observations['revenue_yoy_pct']}%"
            elif "ttm_free_cash_flow_margin_pct" in observations:
                evidence = f"TTM 自由现金流率 {observations['ttm_free_cash_flow_margin_pct']}%"
            else:
                evidence = str(signal.get("reason", "需要核对原始披露"))
            label = SIGNAL_LABELS.get(signal.get("code", ""), "基本面变化待复核")
            source = signal.get("source_url", "")
            lines.append(
                f"- {ticker}：{label}；{evidence}；财务期间截至 {signal.get('evidence_date') or '未知'}；"
                f"来源：{source or '待补'}。该信号要求研究复核，尚未确认投资逻辑失效。"
            )
    return "\n".join(lines) or "- 当前未列出新增研究警告；这不代表长期假设已经获证实。"


def plain_action(action: str) -> str:
    normalized = action.lower()
    if normalized == "hold":
        return "继续持有"
    if normalized == "hold_pending_research":
        return "继续持有，研究证据待复核"
    if "trim" in normalized or "reduce" in normalized:
        return "减仓方案待人工复核"
    if "exit" in normalized or "sell" in normalized:
        return "退出方案待人工复核"
    if "add" in normalized or "buy" in normalized:
        return "新增方案待稳定性确认"
    return "继续观察"


def valuation_display(row: dict[str, Any]) -> str:
    if row.get("valuation_applicability") == "not_applicable_broad_market_etf":
        return "不适用（宽基 ETF 使用核心配置口径）"
    values = [
        row.get("valuation_bear_price", ""),
        row.get("valuation_base_price", ""),
        row.get("valuation_bull_price", ""),
    ]
    if all(str(value).strip() for value in values):
        return "$" + "/$".join(str(value) for value in values)
    return "证据不足"


def share_display(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "证据不足"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def action_review_display(row: dict[str, Any]) -> str:
    action = str(row.get("action", "")).strip().lower()
    if not is_action_transition(action):
        return ""
    if "trim" in action or "reduce" in action:
        change_label = "减少"
    elif "exit" in action or "sell" in action:
        change_label = "退出复核涉及"
    else:
        change_label = "增加"
    return (
        f"人工复核情景：{change_label} {share_display(row.get('whole_shares_to_change'))} 股，"
        f"复核后持有 {share_display(row.get('target_shares'))} 股；"
        f"触发依据：{row.get('reason') or '证据不足'}；该情景不会自动执行。"
    )


def held_position_summary(row: dict[str, Any]) -> str:
    review_detail = action_review_display(row)
    return (
        f"{plain_action(row['action'])}; "
        f"现价 ${row['current_price'] or 'n/a'}，{row['current_shares']} 股，约占 {row['current_weight_pct']}%；"
        f"估值区间 ${row['valuation_bear_price'] or 'n/a'}/${row['valuation_base_price'] or 'n/a'}/${row['valuation_bull_price'] or 'n/a'}；"
        f"{review_detail + '；' if review_detail else ''}"
        f"期限 {row['holding_horizon'] or 'n/a'}；反证：{row['invalidation'] or 'n/a'}；"
        f"最强正面：{row['strongest_positive_evidence'] or 'n/a'}；最强负面：{row['strongest_negative_evidence'] or 'n/a'}；"
        f"人工确认={row['human_confirmation_required']}。"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    active_state = load_active_state()
    active_config = load_active_config()
    inhibit = load_inhibit()
    held_rows = normalized_held_rows()
    if not held_rows:
        raise RuntimeError("C9 exact action plan contains no held positions")
    held_tickers = [row["ticker"] for row in held_rows]
    held_company_tickers = [
        ticker for ticker in held_tickers
        if not is_core_allocation_ticker(ticker)
    ]
    if args.check:
        print(
            "safe_check_passed=true "
            f"workflow={active_state['current_workflow']} held={','.join(held_tickers)} "
            "email_attempted=no"
        )
        return 0

    current = now_et()
    official_news = official_news_context(current, held_company_tickers)
    account = read_json(ACCOUNT_STATE_PATH)
    market_gate = load_market_gate(current, held_tickers)
    long_horizon_context = held_research_context(
        read_json(LONG_HORIZON_PATH, {}), held_rows, market_gate["expected_market_session"],
    )
    evidence_status = read_json(EVIDENCE_STATUS_PATH, {})
    evidence_gate_passed = (
        evidence_status.get("scan_status") == "ok"
        and bool(evidence_status.get("held_coverage_complete"))
        and evidence_status.get("last_attempt_at", "")[:10] == cycle_date()
    )
    fundamental_rows = {
        row.get("ticker", "").upper(): row for row in read_csv(FUNDAMENTALS_PATH)
    }
    held_fundamentals = [
        fundamental_rows.get(
            ticker,
            {
                "ticker": ticker,
                "data_quality": "missing",
                "trend_label": "insufficient_trend",
            },
        )
        for ticker in held_company_tickers
    ]
    fundamental_gate_passed = (
        evidence_status.get("held_fundamental_coverage_complete") is True
        and all(row.get("data_quality") == "ok" for row in held_fundamentals)
    )
    weakening_tickers = [
        row.get("ticker", "")
        for row in held_fundamentals
        if row.get("trend_label") == "contracting"
    ]
    conflicts = execution_conflicts()
    material_events = material_events_for_cycle(active_config["notifications"])
    candidate_recommendations = read_csv(NEW_CANDIDATE_PATH)
    prior_state = read_json(DAILY_DECISION_STATE_PATH, {})
    prior_decision = read_json(DAILY_DECISION_JSON_PATH, {})
    market_session = (
        market_gate["expected_market_session"]
        if market_gate["complete_close_verified"]
        else ""
    )
    market_regime = load_regime_controls(market_gate["expected_market_session"])
    required_distinct_closes = max(2, min(3, int(market_regime["required_distinct_closes"])))
    stability_count, proposal_fingerprint = action_stability(
        prior_state, held_rows, market_session
    )

    raw_transitions = [row for row in held_rows if is_action_transition(row["action"])]
    eligible_transitions: list[dict[str, Any]] = []
    pending_stability: list[dict[str, Any]] = []
    for row in raw_transitions:
        if "add" in row["action"] or "buy" in row["action"]:
            if (
                stability_count >= required_distinct_closes
                and market_gate["passed"]
                and evidence_gate_passed
                and fundamental_gate_passed
            ):
                eligible_transitions.append(row)
            else:
                pending_stability.append(row)
                row["human_confirmation_required"] = "no"
        else:
            eligible_transitions.append(row)

    data_gate_passed = (
        market_gate["passed"] and evidence_gate_passed and fundamental_gate_passed
    )
    proposed_new_candidates = [
        row for row in candidate_recommendations
        if row.get("eligibility_label") in {
            "eligible_buy_review",
            "eligible_core_starter_review",
        }
    ]
    new_candidate_state = candidate_stability(
        prior_state, proposed_new_candidates, market_session, valid_close=data_gate_passed,
    )
    candidate_counts = {
        ticker: row["distinct_closes"]
        for ticker, row in new_candidate_state["proposals"].items()
    }
    new_candidate_fingerprint = canonical_sha256({
        ticker: row["fingerprint"]
        for ticker, row in new_candidate_state["proposals"].items()
    })
    # Compatibility summary only; per-ticker counts decide eligibility.
    new_candidate_stability_count = max(candidate_counts.values(), default=0)
    eligible_new_candidates = [
        row for row in proposed_new_candidates
        if data_gate_passed
        and candidate_counts.get(row.get("ticker", "").upper(), 0) >= required_distinct_closes
    ]
    pending_new_candidates = [row for row in proposed_new_candidates if row not in eligible_new_candidates]
    if conflicts:
        headline = "暂停新增动作｜先解决账户状态冲突"
        decisive_advice = "不要改变仓位；先校准本地账户和已确认成交状态。"
        decision_code = "account_conflict_hold"
    elif not data_gate_passed:
        headline = "不采取新动作｜数据可靠性门槛未通过"
        decisive_advice = "维持现有仓位，不新增候选；等待市场或官方证据数据恢复完整。"
        decision_code = "data_gate_hold"
    elif weakening_tickers and not eligible_transitions:
        weakening = "、".join(weakening_tickers)
        headline = f"维持现有仓位但暂停新增｜{weakening} 长期收入趋势需复核"
        decisive_advice = "不因单日价格动作；先核对最新官方财务趋势是否削弱长期逻辑。"
        decision_code = "fundamental_weakening_review"
    elif eligible_transitions or eligible_new_candidates:
        transition_text = "；".join(
            f"{row['ticker']}：{plain_action(row['action'])}"
            for row in eligible_transitions
        )
        if eligible_new_candidates:
            candidate_text = "；".join(
                f"{row['ticker']}：最多复核 {row.get('suggested_whole_shares', '0')} 股，最高 ${row.get('maximum_review_price', 'n/a')}"
                for row in eligible_new_candidates
            )
            transition_text = "；".join(filter(None, (transition_text, candidate_text)))
        headline = f"明确行动候选｜{transition_text}"
        decisive_advice = "这是需要人工判断的研究方案；仓位不会自动改变。"
        decision_code = "action_review_candidate"
    elif pending_new_candidates:
        pending_text = "、".join(
            row.get("ticker", "") for row in pending_new_candidates
        )
        headline = f"新增研究方案等待稳定性确认｜{pending_text}"
        decisive_advice = f"方案已通过当前点时门槛，仍需达到 {required_distinct_closes} 个不同有效收盘日确认；不会自动改变仓位。"
        decision_code = "pending_new_position_stability"
    elif any(row.get("action") == "hold_pending_research" for row in held_rows):
        headline = "维持现有股数｜长期持有依据仍需研究复核"
        decisive_advice = "暂不改变持仓不代表长期投资逻辑已获验证；继续补齐增长、现金流与失效条件证据。"
        decision_code = "hold_pending_research"
    else:
        headline = "继续持有现有仓位｜今天不新增仓位"
        decisive_advice = "保持长期视角；今日信息没有达到改变仓位建议的证据阈值。"
        decision_code = "hold_no_new_position"

    action_signature = [
        {
            "ticker": row["ticker"],
            "action": row["action"],
            "eligible": row in eligible_transitions,
        }
        for row in held_rows
    ]
    if conflicts:
        substantive_code = "account_conflict_hold"
    elif not data_gate_passed:
        substantive_code = "data_gate_hold"
    elif eligible_transitions or eligible_new_candidates:
        substantive_code = "action_review_candidate"
    elif pending_new_candidates:
        substantive_code = "pending_new_position_stability"
    elif weakening_tickers:
        substantive_code = "fundamental_weakening_review"
    elif any(row.get("action") == "hold_pending_research" for row in held_rows):
        substantive_code = "hold_pending_research"
    else:
        substantive_code = "hold_no_new_position"
    decision_fingerprint = canonical_sha256(
        {
            "substantive_code": substantive_code,
            "actions": action_signature,
            "material_accessions": sorted(
                row.get("accession_number", "") for row in material_events
            ),
            "account_conflicts": conflicts,
            "fundamental_trends": {
                row.get("ticker", ""): row.get("trend_label", "")
                for row in held_fundamentals
            },
            "held_research_warnings": [
                {
                    "ticker": warning["ticker"], "readiness": warning["readiness"],
                    "missing_evidence": warning["missing_evidence"],
                    "review_signals": [
                        {key: signal.get(key) for key in ("code", "observations", "evidence_date", "source_url")}
                        for signal in warning["review_signals"]
                    ],
                }
                for warning in long_horizon_context["warnings"]
            ],
            "candidate_reviews": [
                {
                    "ticker": row.get("ticker", ""),
                    "eligibility": row.get("eligibility_label", ""),
                    "action": row.get("recommended_action", ""),
                    "maximum_review_price": row.get("maximum_review_price", ""),
                    "suggested_whole_shares": row.get("suggested_whole_shares", ""),
                }
                for row in candidate_recommendations
            ],
        }
    )
    prior_fingerprint = prior_state.get("decision_fingerprint", "")
    decision_changed = bool(prior_fingerprint) and decision_fingerprint != prior_fingerprint
    is_weekend = current.weekday() >= 5
    published_session = date.fromisoformat(
        market_gate["expected_market_session"]
    )
    weekly_summary_due = weekly_summary_due_for_published_session(
        current,
        published_session,
    )
    first_material_baseline = not prior_fingerprint and bool(
        eligible_transitions
        or eligible_new_candidates
        or conflicts
        or material_events
        or weakening_tickers
    )
    if bool(inhibit.get("active")):
        send_recommended = False
        send_reason = "maintenance_inhibit_active"
    elif cycle_date() < str(active_state.get("operational_from", "")):
        send_recommended = False
        send_reason = "before_operational_from"
    else:
        send_recommended, send_reason = notification_delivery_policy(
            is_weekend=is_weekend,
            weekly_summary_due=weekly_summary_due,
            material_event=bool(material_events),
            decision_changed=decision_changed,
            account_conflict=bool(conflicts),
            fundamental_weakening=bool(weakening_tickers),
            first_material_baseline=first_material_baseline,
        )

    review_reasons: list[str] = []
    if eligible_transitions:
        review_reasons.append("portfolio_action_transition")
    if eligible_new_candidates:
        review_reasons.append("new_position_review_candidate")
    if conflicts:
        review_reasons.append("account_state_conflict")
    if material_events:
        review_reasons.append("new_material_official_filing")
    if weakening_tickers:
        review_reasons.append("long_term_fundamental_weakening")
    human_review_required = bool(review_reasons)

    watch_rows = []
    pending_candidate_tickers = {
        row.get("ticker", "") for row in pending_new_candidates
    }
    eligible_candidate_tickers = {
        row.get("ticker", "") for row in eligible_new_candidates
    }
    for row in candidate_recommendations[:5]:
        ticker = row.get("ticker", "")
        displayed_action = row.get("recommended_action", "")
        if ticker in pending_candidate_tickers:
            displayed_action = "pending_second_distinct_close"
        watch_rows.append(
            {
                "ticker": ticker,
                "label": row.get("eligibility_label", ""),
                "action": displayed_action,
                "score": row.get("account_aware_conviction_score", ""),
                "confidence": row.get("recommendation_confidence", ""),
                "human_confirmation_required": "yes" if ticker in eligible_candidate_tickers else "no",
                "current_price": row.get("current_price", ""),
                "valuation_applicability": row.get("valuation_applicability", ""),
                "valuation_bear_price": row.get("valuation_bear_price", ""),
                "valuation_base_price": row.get("valuation_base_price", ""),
                "valuation_bull_price": row.get("valuation_bull_price", ""),
                "maximum_review_price": row.get("maximum_review_price", ""),
                "suggested_whole_shares": row.get("suggested_whole_shares", ""),
                "suggested_position_pct": row.get("suggested_position_pct", ""),
                "sizing_tier": row.get("sizing_tier", ""),
                "stability_distinct_closes": candidate_counts.get(ticker.upper(), 0),
                "required_distinct_closes": required_distinct_closes,
                "gate_blockers": row.get("gate_blockers", ""),
                "holding_horizon": row.get("holding_horizon", ""),
                "invalidation": row.get("invalidation_condition", ""),
                "strongest_positive_evidence": row.get("strongest_positive_evidence", ""),
                "strongest_negative_evidence": row.get("strongest_negative_evidence", ""),
                "valuation_source": row.get("valuation_source", ""),
            }
        )

    days_to_friday = (4 - current.weekday()) % 7
    if days_to_friday == 0:
        days_to_friday = 7
    next_review_date = (current.date() + timedelta(days=days_to_friday)).isoformat()

    portfolio_summaries = read_csv(PORTFOLIO_SUMMARY_PATH)
    if len(portfolio_summaries) != 1:
        raise RuntimeError("dynamic portfolio summary must contain one row")
    portfolio_summary = portfolio_summaries[0]
    post_action_rows = read_csv(POST_ACTION_PORTFOLIO_PATH)
    post_action = next(
        (
            row for row in post_action_rows
            if row.get("scenario") == "after_position_and_core_reviews"
        ),
        {},
    )
    proposed_deployment = sum(
        float(row.get("current_price", 0) or 0)
        * float(row.get("suggested_whole_shares", 0) or 0)
        for row in proposed_new_candidates
    )
    decision = {
        "schema_version": "phase5r_daily_decision_v1",
        "generated_at": iso_now(),
        "cycle_date": cycle_date(),
        "timezone": "America/New_York",
        "headline": headline,
        "decisive_advice": decisive_advice,
        "decision_code": decision_code,
        "decision_fingerprint": decision_fingerprint,
        "decision_changed": decision_changed,
        "held_positions": held_rows,
        "long_horizon_research": long_horizon_context,
        "held_research_warnings": long_horizon_context["warnings"],
        "research_review_required": bool(long_horizon_context["warnings"]) or any(
            row.get("action") == "hold_pending_research" for row in held_rows
        ),
        "watch_candidates": watch_rows,
        "eligible_action_review_candidates": [
            row["ticker"] for row in eligible_transitions
        ],
        "pending_stability_candidates": [
            row["ticker"] for row in pending_stability
        ] + sorted(pending_candidate_tickers),
        "eligible_new_position_review_candidates": sorted(eligible_candidate_tickers),
        "action_stability_distinct_closes": stability_count,
        "new_candidate_stability_distinct_closes": new_candidate_stability_count,
        "new_candidate_stability_by_ticker": candidate_counts,
        "required_distinct_closes": required_distinct_closes,
        "market_regime": market_regime,
        "evidence_coverage": {
            "official_news": official_news,
            "news_direction_used_for_scoring": False,
        },
        "market_gate": market_gate,
        "evidence_gate": {
            "passed": evidence_gate_passed,
            "status": evidence_status.get("scan_status", "missing"),
            "last_attempt_at": evidence_status.get("last_attempt_at", ""),
            "new_material_event_count": len(material_events),
        },
        "fundamental_gate": {
            "passed": fundamental_gate_passed,
            "held_coverage_complete": evidence_status.get(
                "held_fundamental_coverage_complete", False
            ),
            "weakening_tickers": weakening_tickers,
        },
        "held_fundamentals": [
            {
                "ticker": row.get("ticker", ""),
                "period": row.get("latest_frame", ""),
                "revenue_yoy_pct": row.get("revenue_yoy_pct", ""),
                "net_margin_pct": row.get("net_margin_pct", ""),
                "cash_latest": row.get("cash_latest", ""),
                "trend_label": row.get("trend_label", ""),
                "data_quality": row.get("data_quality", ""),
                "source_url": row.get("source_url", ""),
            }
            for row in held_fundamentals
        ],
        "material_events": [
            {
                "ticker": row.get("ticker", ""),
                "form": row.get("form", ""),
                "filing_date": row.get("filing_date", ""),
                "accession_number": row.get("accession_number", ""),
                "source_url": row.get("source_url", ""),
            }
            for row in material_events
        ],
        "account": {
            "account_total_value": portfolio_summary.get("account_total_value"),
            "reported_account_total_reference": account.get("account_total_value"),
            "invested_capital": portfolio_summary.get("current_holdings_value"),
            "invested_pct": f"{100.0 - float(portfolio_summary.get('current_cash_pct', 0) or 0):.4f}",
            "cash_available": portfolio_summary.get("cash_available"),
            "cash_pct": portfolio_summary.get("current_cash_pct"),
            "cash_reserved": portfolio_summary.get("cash_reserved"),
            "investment_horizon_years": account.get("investment_horizon_years"),
            "valuation_basis": "manual cash plus current shares at canonical public close; reported total is reconciliation reference",
            "last_updated": account.get("last_updated"),
            "cash_basis": account.get("cash_basis", "owner_recorded"),
            "planning_capital_min": account.get("planning_capital_min"),
            "planning_capital_max": account.get("planning_capital_max"),
        },
        "capital_allocation": {
            "proposed_deployment_value": round(proposed_deployment, 2),
            "post_review_active_value": post_action.get("resulting_active_value", ""),
            "post_review_core_value": post_action.get("resulting_core_value", ""),
            "post_review_cash": post_action.get("resulting_cash", ""),
            "post_review_cash_pct": post_action.get("cash_weight_pct", ""),
            "cash_rationale": post_action.get("retained_cash_reason", ""),
            "automatic_action_allowed": False,
        },
        "account_conflicts": conflicts,
        "email_brief_version": EMAIL_BRIEF_VERSION,
        "pending_execution_summaries": [
            {key: row.get(key, "") for key in ("ticker", "execution_id", "order_status")}
            for row in read_csv(PENDING_EXECUTION_PATH)
            if row.get("execution_id", "").strip()
        ],
        "recent_applied_execution": (
            recent_applied_execution(current)
            if not conflicts and not current_manual_snapshot_matches(
                sha256_file(ROOT / "05_risk_and_positions" / "current_positions.local.csv"),
                sha256_file(ACCOUNT_STATE_PATH),
            ) else {}
        ),
        "human_review_required": human_review_required,
        "human_review_reasons": review_reasons,
        "automatic_action_allowed": False,
        "send_recommended": send_recommended,
        "send_reason": send_reason,
        "weekend_policy": "material_change_only",
        "notification_policy": {
            "event_driven": active_config["notifications"]["event_driven"],
            "weekly_summary_weekday": active_config["notifications"]["weekly_summary_weekday"],
            "unchanged_daily_email": active_config["notifications"]["unchanged_daily_email"],
        },
        "notification_policy_evaluation": {
            "is_weekend": is_weekend,
            "weekly_summary_due": weekly_summary_due,
            "prior_decision_present": bool(prior_fingerprint),
            "first_material_baseline": first_material_baseline,
            "long_term_fundamental_weakening": bool(weakening_tickers),
            "scheduler_time_gate_applied": False,
        },
        "next_scheduled_review": next_review_date,
        "model_assistance": {
            "used_for_deterministic_decision": False,
            "route": "no_call",
            "cycle_cost_usd": 0.0,
            "monthly_hard_cap_usd": active_config["model_policy"]["monthly_hard_cap_usd"],
            "status": active_config["model_policy"]["status"],
        },
        "boundaries": {
            "research_only": True,
            "broker_connected": False,
            "broker_account_read": False,
            "order_code_created": False,
            "trade_placed": False,
        },
    }
    notification_mode = active_config["notifications"].get("regular_delivery_mode", LEGACY_NOTIFICATION_MODE)
    if "regular_delivery_mode" in active_config["notifications"]:
        decision["notification_policy"]["regular_delivery_mode"] = notification_mode
    notification_change = notification_change_comparison(decision, prior_state, prior_decision)
    decision["notification_change"] = notification_change
    if notification_mode == WATCH_ACTION_NOTIFICATION_MODE:
        if not bool(inhibit.get("active")) and cycle_date() >= str(active_state.get("operational_from", "")):
            send_recommended, send_reason = notification_delivery_policy(
                is_weekend=is_weekend, weekly_summary_due=weekly_summary_due,
                material_event=bool(material_events), decision_changed=decision_changed,
                account_conflict=bool(conflicts), fundamental_weakening=bool(weakening_tickers),
                first_material_baseline=first_material_baseline,
                regular_delivery_mode=notification_mode, notification_changed=notification_change["changed"],
            )
            decision["send_recommended"] = send_recommended
            decision["send_reason"] = send_reason
    atomic_write_json(DAILY_DECISION_JSON_PATH, decision)

    held_lines = "\n".join(
        f"- {row['ticker']}: {held_position_summary(row)}" for row in held_rows
    )
    watch_lines = "\n".join(
        f"- {row['ticker']}: {row['action'] or row['label']}，"
        f"现价 ${row['current_price'] or 'n/a'}，估值：{valuation_display(row)}；"
        f"最多复核 {row['suggested_whole_shares'] or '0'} 股（约 {row['suggested_position_pct'] or '0'}%），最高复核价 ${row['maximum_review_price'] or 'n/a'}；"
        f"仓位层级 {row['sizing_tier'] or 'no_allocation'}；分数 {row['score'] or 'n/a'}；期限 {row['holding_horizon'] or 'n/a'}；"
        f"阻断项：{row['gate_blockers'] or '无'}；反证：{row['invalidation'] or 'n/a'}。"
        for row in watch_rows
    ) or "- 当前没有进入展示阈值的新候选。"
    gate_lines = (
        f"- 市场数据：{'通过' if market_gate['passed'] else '未通过'}；"
        f"预期交易日 {market_gate['expected_market_session']}。\n"
        f"- SEC 官方证据：{'通过' if evidence_gate_passed else '未通过'}；"
        f"今日重大新事件 {len(material_events)} 条。\n"
        f"- 基础财务数据校验：{'通过' if fundamental_gate_passed else '未通过'}；"
        f"收入趋势转弱标的 {len(weakening_tickers)} 个。\n"
        f"- 账户与成交：{'存在冲突' if conflicts else '结构化状态一致'}。"
    )
    fundamental_lines = "\n".join(
        f"- {row.get('ticker', '')}: {row.get('trend_label', 'insufficient_trend')}；"
        f"收入同比 {row.get('revenue_yoy_pct') or 'n/a'}%；"
        f"净利率 {row.get('net_margin_pct') or 'n/a'}%；"
        f"期间 {row.get('latest_frame') or 'n/a'}。"
        for row in held_fundamentals
    )
    report = f"""{report_heading("daily_decision")} — {cycle_date()}

## 决定性结论

**{headline}**

{decisive_advice}

这是研究建议，不是买卖指令；不会连接券商或自动下单。

## 账户与新资本

- 动态账户总值：${portfolio_summary.get('account_total_value', 'n/a')}。
- 已投资：${portfolio_summary.get('current_holdings_value', 'n/a')}（{100.0 - float(portfolio_summary.get('current_cash_pct', 0) or 0):.4f}%）。
- 现金：${portfolio_summary.get('cash_available', 'n/a')}（{portfolio_summary.get('current_cash_pct', 'n/a')}%）；其中战略储备 ${portfolio_summary.get('cash_reserved', 'n/a')}。
- 当前证据支持的新增复核金额：${proposed_deployment:.2f}；任何真实操作仍需人工决定。
- 全部当前复核后的假设现金：${post_action.get('resulting_cash', 'n/a')}（{post_action.get('cash_weight_pct', 'n/a')}%）。
- 保留现金原因：{post_action.get('retained_cash_reason', 'n/a')}

## 当前持仓

{held_lines}

## 新候选

{watch_lines}

## 可靠性门槛

{gate_lines}

官方新闻补充覆盖：{official_news.get('status', 'missing')}；最近事件 {official_news.get('recent_event_count', 0)} 条。范围限已配置公司官方来源，抓取成功不代表全部新闻覆盖；未评估方向的事件不作正向加分。
未配置官方新闻来源的持仓：{'、'.join(official_news.get('unconfigured_held_tickers', [])) or '无'}。

## 长期基本面

{fundamental_lines}

长期研究覆盖：{long_horizon_context['status']}；{len(long_horizon_context['warnings'])} 个持仓存在未完成或待复核证据。维持股数不等于已证实长期投资逻辑，未确认的研究警告不会自行生成退出方案。

{research_warning_lines(long_horizon_context)}

## 深度与长期约束

- 投资期限：{account.get('investment_horizon_years', 'n/a')} 年。
- 每日更新信息不等于每日改变仓位；新增方案需要 {required_distinct_closes} 个不同有效收盘日保持投资判断一致，报价独立刷新。
- HOLD / WATCH / NO NEW POSITION 不要求人工确认。
- 只有增减仓等状态变化、账户冲突或新的重大官方文件才升级复核。
- 发送策略：{'仅在观察名单或操作建议发生实质变化时发送；无变化的周报也不发送。' if notification_mode == WATCH_ACTION_NOTIFICATION_MODE else '只在重大变化时发送，另加周五周报；无变化的普通工作日不发送。'}
- 下次计划复核：{next_review_date}。
- 本次确定性决策模型成本：$0；月度模型硬上限：${active_config['model_policy']['monthly_hard_cap_usd']}。

## 运行边界

- human_review_required={'yes' if human_review_required else 'no'}
- automatic_action_allowed=no
- send_recommended={'yes' if send_recommended else 'no'}
- send_reason={send_reason}
- broker_connected=no
- broker_account_read=no
- order_code_created=no
- trade_placed=no
"""
    atomic_write_text(DAILY_DECISION_REPORT_PATH, report)

    subject, plain, html_body = render_email(decision)
    atomic_write_text(DAILY_BRIEF_TEXT_PATH, plain)
    atomic_write_text(DAILY_BRIEF_HTML_PATH, html_body)

    state = {
        "schema_version": "phase5r_daily_decision_state_v1",
        "updated_at": iso_now(),
        "cycle_date": cycle_date(),
        "decision_fingerprint": decision_fingerprint,
        "notification_change_fingerprint": notification_change["fingerprint"],
        "notification_change_anchor": notification_change["prior_fingerprint"] or notification_change["fingerprint"],
        "decision_code": decision_code,
        "action_proposal_fingerprint": proposal_fingerprint,
        "action_proposal_session": (
            market_session
            or prior_state.get("action_proposal_session", "")
        ),
        "action_proposal_distinct_closes": stability_count,
        "new_candidate_proposal_fingerprint": new_candidate_fingerprint,
        "new_candidate_proposal_session": (
            market_session or prior_state.get("new_candidate_proposal_session", "")
        ),
        "new_candidate_proposal_distinct_closes": new_candidate_stability_count,
        "new_candidate_stability": new_candidate_state,
    }
    atomic_write_json(DAILY_DECISION_STATE_PATH, state)
    log_daily_run(
        component="daily_decision",
        run_mode="compose_no_send",
        outcome="passed",
        reason=decision_code,
    )
    print(
        f"decision_created=true code={decision_code} "
        f"send_recommended={str(send_recommended).lower()} "
        f"human_review_required={str(human_review_required).lower()} email_attempted=no"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
