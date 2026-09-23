"""Point-in-time, bounded market context for research pacing, never execution."""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from daily_common import ROOT, read_json

POLICY_PATH = ROOT / "01_policies/market_regime_policy.json"
STATE_PATH = ROOT / "04_research/company_research/market_regime.local.json"
REPORT_PATH = ROOT / "08_reviews/current/market_regime.local.md"


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def build_regime(rows: list[dict], universe: list[dict], prior: dict, policy: dict,
                 expected_session: str, observed_at: str) -> dict:
    """Use a single complete public close; repeated intraday runs add no votes."""
    session = date.fromisoformat(expected_session)
    observed = datetime.fromisoformat(observed_at)
    if observed.tzinfo is None or session > observed.date():
        raise ValueError("regime requires an aware observation after its market session")
    observed_et = observed.astimezone(ZoneInfo("America/New_York"))
    if session > observed_et.date() or (session == observed_et.date() and observed_et.strftime("%H:%M") < "16:15"):
        raise ValueError("regime requires a completed close, never an intraday observation")
    names = {str(row.get("ticker", "")).upper() for row in universe}
    benchmarks = set(policy["benchmarks"])
    companies = {str(row.get("ticker", "")).upper() for row in universe
                 if row.get("is_benchmark") != "yes"}
    quotes = {}
    seen_tickers = set()
    duplicate_tickers = set()
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        if ticker in seen_tickers:
            duplicate_tickers.add(ticker)
        seen_tickers.add(ticker)
        price, high = number(row.get("last_price")), number(row.get("fifty_two_week_high"))
        change = number(row.get("intraday_change_pct"))
        if (row.get("market_session_date") == expected_session
                and row.get("data_quality_label") == "ok"
                and price is not None and high is not None and change is not None
                and 0 < price <= high * 1.001):
            quotes[ticker] = {"drawdown_pct": (price / high - 1) * 100,
                              "daily_return_pct": change}
    coverage = len(names & quotes.keys()) / max(1, len(names)) * 100
    breadth = [quotes[ticker] for ticker in sorted(companies & quotes.keys())]
    enough = (not duplicate_tickers and benchmarks.issubset(quotes) and len(breadth) >= policy["minimum_breadth_names"]
              and coverage >= policy["minimum_snapshot_coverage_pct"])
    reasons = []
    deep = sum(row["drawdown_pct"] <= policy["stress_breadth_drawdown_pct"] for row in breadth) / max(1, len(breadth)) * 100
    decliners = sum(row["daily_return_pct"] < 0 for row in breadth) / max(1, len(breadth)) * 100
    spy_dd = quotes.get("SPY", {}).get("drawdown_pct")
    raw = "unknown"
    if enough:
        broad_drawdown = (spy_dd <= policy["stress_benchmark_drawdown_pct"]
                          and deep >= policy["stress_breadth_fraction_pct"])
        shock = (all(quotes[t]["daily_return_pct"] <= policy["shock_daily_return_pct"] for t in benchmarks)
                 and decliners >= policy["shock_decliners_fraction_pct"])
        raw = "stress" if broad_drawdown or shock else "caution" if (
            spy_dd <= policy["caution_benchmark_drawdown_pct"]
            or deep >= policy["caution_breadth_fraction_pct"]
        ) else "normal"
        reasons += [name for name, applies in (("broad_drawdown", broad_drawdown), ("broad_market_shock", shock)) if applies]
    else:
        reasons.append("insufficient_same_session_benchmark_or_breadth_coverage")
        if duplicate_tickers:
            reasons.append("duplicate_snapshot_tickers")
    # Do not reuse regime votes across a policy revision. An observation's
    # state is keyed by source close, so weekends and reruns cannot confirm it.
    history = prior.get("observations", []) if prior.get("policy_version") == policy["policy_version"] else []
    history = [row for row in history if isinstance(row, dict)
               and str(row.get("market_session_date", "")) < expected_session
               and row.get("raw_regime") in {"normal", "caution", "stress", "unknown"}]
    by_session = {row["market_session_date"]: row for row in history}
    by_session[expected_session] = {"market_session_date": expected_session, "raw_regime": raw}
    history = [by_session[key] for key in sorted(by_session)][-60:]
    effective = "normal"
    stress_run = recovery_run = 0
    for item in history:
        candidate = item["raw_regime"]
        stress_run = stress_run + 1 if candidate == "stress" else 0
        recovery_run = recovery_run + 1 if candidate == "normal" else 0
        if candidate == "unknown":
            continue
        if stress_run >= policy["stress_confirmation_closes"]:
            effective = "stress"
        elif effective == "stress":
            if recovery_run >= policy["recovery_confirmation_closes"]:
                effective = "normal"
        else:
            effective = "normal" if candidate == "normal" else "caution"
    if not enough:
        effective = "unknown"
    required = policy["stress_required_distinct_closes"] if effective == "stress" else policy["normal_required_distinct_closes"]
    return {
        "schema_version": "phase5r_market_regime_v1", "policy_version": policy["policy_version"],
        "generated_at": observed_at, "market_session_date": expected_session,
        "status": "current" if enough else "insufficient", "regime": effective,
        "raw_regime": raw, "required_distinct_closes": required,
        "reasons": reasons, "observations": history,
        "metrics": {"benchmark_metrics": {t: quotes.get(t) for t in sorted(benchmarks)},
                    "snapshot_coverage_pct": round(coverage, 2), "breadth_names": len(breadth),
                    "deep_drawdown_breadth_pct": round(deep, 2), "decliners_pct": round(decliners, 2)},
        "research_priority": "balance_sheet_cash_flow_and_thesis_resilience" if effective in {"stress", "caution"} else "durable_growth_and_valuation",
        "interpretation": "Heuristic market context, not an expected-return forecast; unadjusted provider highs may require corporate-action review",
        "hard_risk_caps_changed": False, "strategic_targets_changed": False,
        "holding_exit_authority": False, "automatic_action_allowed": False,
    }


def load_regime_controls(expected_market_session: str) -> dict:
    fallback = {"status": "insufficient", "regime": "unknown", "required_distinct_closes": 2,
                "market_session_date": expected_market_session, "reasons": ["regime_report_missing_invalid_or_stale"]}
    try:
        value = read_json(STATE_PATH, {})
        if (value.get("schema_version") != "phase5r_market_regime_v1"
                or value.get("status") != "current"
                or value.get("market_session_date") != expected_market_session
                or value.get("regime") not in {"normal", "caution", "stress"}
                or type(value.get("required_distinct_closes")) is not int
                or value["required_distinct_closes"] != (3 if value["regime"] == "stress" else 2)):
            return fallback
        return {key: value[key] for key in ("status", "regime", "required_distinct_closes", "market_session_date", "reasons")}
    except (OSError, ValueError, TypeError, KeyError):
        return fallback
