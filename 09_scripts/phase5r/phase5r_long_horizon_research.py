"""Pure long-horizon research arithmetic; sensitivities never authorize actions."""
from __future__ import annotations

from datetime import date, datetime
import json
import math
from typing import Any

FACT_FIELDS = (
    "revenue_latest", "revenue_yoy_pct", "ttm_revenue", "ttm_revenue_yoy_pct",
    "net_margin_pct", "ttm_free_cash_flow", "ttm_free_cash_flow_margin_pct",
    "cash_latest", "debt_latest", "diluted_shares_latest", "share_dilution_pct",
    "revenue_yoy_prior_quarter_pct", "net_margin_prior_quarter_pct",
)


def number(value: Any) -> float | None:
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def timestamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result if result.tzinfo else None
    except ValueError:
        return None


def provenance(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("field_provenance_json", {})
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def source_facts(row: dict[str, Any], observed_at: str) -> dict[str, Any]:
    """Keep observations separate from assumptions; reject unbound/future facts."""
    result = {}
    bound = provenance(row)
    now = timestamp(observed_at)
    for key in FACT_FIELDS:
        receipt = bound.get(key, {})
        receipt = receipt if isinstance(receipt, dict) else {}
        value = number(row.get(key))
        available = timestamp(receipt.get("available_at_utc"))
        issues = []
        if value is None:
            issues.append("missing_numeric_observation")
        if not row.get("source_url") or receipt.get("status") != "available":
            issues.append("missing_source_provenance")
        if now is None or available is None or available > now:
            issues.append("missing_or_future_availability")
        prior_quarter = key in {"revenue_yoy_prior_quarter_pct", "net_margin_prior_quarter_pct"}
        aligned = (bool(receipt.get("end")) and receipt["end"] < row.get("latest_period_end", "")) if prior_quarter else receipt.get("end") == row.get("latest_period_end")
        if not receipt.get("end") or not aligned:
            issues.append("financial_period_not_aligned")
        if row.get("data_quality") != "ok":
            issues.append("source_quality_not_ok")
        receipt_value = number(receipt.get("val"))
        if value is not None and receipt_value is not None and not math.isclose(value, receipt_value, rel_tol=1e-8, abs_tol=0.011):
            issues.append("observation_provenance_value_mismatch")
        result[key] = {
            "value": value if not issues else None,
            "reported_value": value,
            "evidence_kind": "source_observation",
            "source_url": row.get("source_url", ""),
            "financial_period_end": row.get("latest_period_end", ""),
            "fetched_at": row.get("fetched_at", ""),
            "provenance": receipt,
            "issues": issues,
        }
    return result


def fundamentals_candidate_queue(
    fundamentals: list[dict[str, Any]], held: set[str], policy: dict[str, Any],
) -> list[dict[str, Any]]:
    """Discovery priority only: no price momentum, trade eligibility or conviction."""
    excluded = held | set(policy.get("excluded_benchmarks", ["SPY", "QQQ", "XLK"]))
    result = []
    for row in fundamentals:
        ticker = str(row.get("ticker", "")).upper()
        growth = number(row.get("ttm_revenue_yoy_pct"))
        if growth is None:
            growth = number(row.get("revenue_yoy_pct"))
        if not ticker or ticker in excluded or row.get("data_quality") != "ok" or growth is None or not row.get("source_url"):
            continue
        fcf = number(row.get("ttm_free_cash_flow_margin_pct"))
        dilution = number(row.get("share_dilution_pct"))
        # Missing observations contribute no favorable evidence and remain explicit.
        priority = max(-50.0, min(60.0, growth))
        if fcf is not None:
            priority += max(-20.0, min(30.0, fcf)) * 0.5
        if dilution is not None:
            priority -= max(0.0, dilution) * 2.0
        result.append({
            "ticker": ticker, "research_priority": round(priority, 4),
            "observed_growth_pct": growth, "observed_fcf_margin_pct": fcf,
            "observed_dilution_pct": dilution,
            "missing_metrics": [key for key, val in (("fcf_margin", fcf), ("dilution", dilution)) if val is None],
            "source_url": row["source_url"], "financial_period_end": row.get("latest_period_end", ""),
            "selection_basis": "fundamental_growth_cash_conversion_dilution_no_price_momentum",
            "is_recommendation": False,
        })
    result.sort(key=lambda row: (-row["research_priority"], row["ticker"]))
    return result


def review_signals(
    current: dict[str, Any], previous: dict[str, Any] | None, policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Numerical changes request research; they do not confirm a thesis break."""
    rules = policy["review_thresholds"]
    signals: list[dict[str, Any]] = []
    missing: list[str] = []
    def add(code: str, reason: str, values: dict[str, Any]) -> None:
        signals.append({"code": code, "status": "review_required", "reason": reason,
                        "observations": values, "source_url": current.get("source_url", ""),
                        "evidence_date": current.get("latest_period_end", ""),
                        "available_at_utc": current.get("available_at_utc", ""),
                        "confirmed_thesis_break": False})
    growth = number(current.get("revenue_yoy_pct"))
    ttm_growth = number(current.get("ttm_revenue_yoy_pct"))
    dilution = number(current.get("share_dilution_pct"))
    fcf = number(current.get("ttm_free_cash_flow_margin_pct"))
    if growth is not None and growth < 0:
        add("revenue_contraction", "Latest comparable revenue is below prior year", {"revenue_yoy_pct": growth})
    if growth is not None and ttm_growth is not None and ttm_growth-growth >= rules["latest_vs_ttm_growth_gap_percentage_points"]:
        add("latest_growth_below_ttm", "Latest-period growth trails TTM growth; examine mix and seasonality before concluding deterioration", {"latest_growth_pct": growth, "ttm_growth_pct": ttm_growth})
    if dilution is not None and dilution > rules["share_dilution_yoy_pct_above"]:
        add("elevated_share_dilution", "Share growth exceeds research review threshold", {"share_dilution_pct": dilution})
    if fcf is not None and fcf < 0:
        add("negative_free_cash_flow", "TTM cash flow after reported capex is negative", {"ttm_free_cash_flow_margin_pct": fcf})
    prior_growth = number(current.get("revenue_yoy_prior_quarter_pct"))
    prior_margin = number(current.get("net_margin_prior_quarter_pct"))
    if current.get("prior_quarter_period_end") and (prior_growth is not None or prior_margin is not None):
        previous = {"latest_period_end": current["prior_quarter_period_end"],
                    "revenue_yoy_pct": prior_growth, "net_margin_pct": prior_margin,
                    "source_url": current.get("source_url", ""), "financial_period_type": "quarterly"}
    try:
        quarter_gap_days = (date.fromisoformat(current["latest_period_end"])-date.fromisoformat(previous["latest_period_end"])).days if previous else None
    except (ValueError, KeyError):
        quarter_gap_days = None
    if current.get("financial_period_type") not in {"quarter", "quarterly"}:
        missing.append("quarterly_financial_period_for_sequential_comparison")
    elif not previous or not previous.get("latest_period_end") or previous["latest_period_end"] >= current.get("latest_period_end", ""):
        missing.append("prior_distinct_quarter_for_sequential_comparison")
    elif previous.get("financial_period_type") not in {"quarter", "quarterly"} or quarter_gap_days is None or not 50 <= quarter_gap_days <= 140:
        missing.append("adjacent_comparable_quarter_for_sequential_comparison")
    else:
        for field, threshold, code in (
            ("revenue_yoy_pct", "revenue_yoy_slowdown_percentage_points", "revenue_growth_slowdown"),
            ("net_margin_pct", "net_margin_decline_percentage_points", "net_margin_deterioration"),
            ("ttm_free_cash_flow_margin_pct", "fcf_margin_decline_percentage_points", "fcf_margin_deterioration"),
        ):
            before, after = number(previous.get(field)), number(current.get(field))
            if before is None or after is None:
                missing.append("sequential_comparison:" + field)
            elif before-after >= rules[threshold]:
                add(code, "Comparable reported metric declined beyond research review threshold", {
                    "field": field, "previous": before, "current": after,
                    "decline_percentage_points": round(before-after, 4),
                    "previous_period_end": previous["latest_period_end"],
                    "previous_source_url": previous.get("source_url", ""),
                })
    return signals, missing


def scenario_math(facts: dict[str, Any], price: float | None, policy: dict[str, Any]) -> dict[str, Any]:
    """Equity P/FCF sensitivity including annual dilution.

    Operating cash flow less capex is a levered cash-flow proxy. Terminal equity
    value is that proxy times a P/FCF multiple; cash/debt are NOT added/subtracted.
    Assumed future levered margins are sensitivities, not company forecasts.
    """
    values = {key: facts.get(key, {}).get("value") for key in ("ttm_revenue", "diluted_shares_latest")}
    missing = [key for key, value in values.items() if value is None]
    if price is None or price <= 0:
        missing.append("current_completed_close")
    if values["ttm_revenue"] is not None and values["ttm_revenue"] <= 0:
        missing.append("positive_ttm_revenue")
    if values["diluted_shares_latest"] is not None and values["diluted_shares_latest"] <= 0:
        missing.append("positive_diluted_shares")
    result: dict[str, Any] = {"status": "insufficient" if missing else "sensitivity_only", "missing_inputs": missing,
        "forward": [], "reverse_hurdles": [], "is_forecast": False, "scenario_probabilities": None,
        "assumption_source": policy["assumption_source"], "assumption_date": policy["effective_from"],
        "limitations": ["No dividend or interim distributions; price appreciation is not total return",
            "Equity P/FCF sensitivity; cash and debt are not separately added or subtracted",
            "Reported operating cash flow less capex is a levered proxy, not guaranteed distributable shareholder cash",
            "Future financing, leverage, repurchases and reinvestment feasibility are not independently modelled",
            "A uniform sensitivity grid does not establish company-specific growth feasibility"]}
    if missing:
        return result
    revenue, shares = values["ttm_revenue"], values["diluted_shares_latest"]
    for assumptions in policy.get("sensitivities", []):
        required = ("revenue_cagr_pct", "terminal_fcf_margin_pct", "annual_dilution_pct", "terminal_price_to_fcf_multiple")
        parsed = {key: number(assumptions.get(key)) for key in required}
        if any(value is None for value in parsed.values()):
            result["missing_inputs"].append("sensitivity_assumptions:" + assumptions.get("name", "unnamed"))
            continue
        growth, margin, dilution, multiple = (parsed[key] for key in required)
        if growth <= -100 or not 0 < margin <= 100 or dilution <= -100 or multiple <= 0:
            result["missing_inputs"].append("invalid_sensitivity_assumptions:" + assumptions.get("name", "unnamed"))
            continue
        for years in policy["horizons_years"]:
            if not isinstance(years, int) or years <= 0:
                raise ValueError("sensitivity horizon must be positive whole years")
            future_revenue = revenue * (1+growth/100)**years
            future_shares = shares * (1+dilution/100)**years
            future_fcf = future_revenue*margin/100
            equity_value = future_fcf*multiple
            terminal_price = max(0.0, equity_value)/future_shares
            result["forward"].append({"sensitivity": assumptions["name"], "years": years,
                "assumptions": assumptions, "assumption_kind": policy["assumption_status"],
                "terminal_revenue": round(future_revenue, 2), "terminal_cash_flow_proxy": round(future_fcf, 2),
                "terminal_diluted_shares": round(future_shares, 2), "terminal_cash_flow_per_share": round(future_fcf/future_shares, 4),
                "terminal_price": round(terminal_price, 4), "price_multiple": round(terminal_price/price, 4),
                "price_cagr_pct": round(((terminal_price/price)**(1/years)-1)*100, 4)})
            for hurdle in policy["reverse_price_multiples"]:
                required_equity_value = price*hurdle*future_shares
                required_revenue = required_equity_value/(margin/100*multiple)
                result["reverse_hurdles"].append({"sensitivity": assumptions["name"], "years": years,
                    "price_hurdle_multiple": hurdle,
                    "required_revenue": round(required_revenue, 2) if required_revenue > 0 else None,
                    "required_revenue_cagr_pct": round(((required_revenue/revenue)**(1/years)-1)*100, 4) if required_revenue > 0 else None,
                    "status": "conditional_arithmetic" if required_revenue > 0 else "nonpositive_hurdle_no_positive_revenue_solution"})
    if not policy.get("sensitivities"):
        result["missing_inputs"].append("explicit_sensitivity_assumptions")
    if result["missing_inputs"]:
        result["status"] = "insufficient_assumptions"
    return result


def hurdle_diagnostic(scenarios: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    """Describe a conditional hurdle, never declare that growth is achievable."""
    ranges = []
    for years in sorted({row["years"] for row in scenarios["reverse_hurdles"]}):
        for hurdle in (2, 3):
            values = [row["required_revenue_cagr_pct"] for row in scenarios["reverse_hurdles"]
                      if row["years"] == years and row["price_hurdle_multiple"] == hurdle
                      and row["required_revenue_cagr_pct"] is not None]
            if values:
                ranges.append({"years": years, "price_hurdle_multiple": hurdle,
                    "minimum_required_revenue_cagr_pct": min(values), "maximum_required_revenue_cagr_pct": max(values),
                    "sensitivity_count": len(values), "range_kind": "assumption_grid_not_confidence_interval"})
    return {"status": "conditional_hurdles_available" if ranges else "insufficient_evidence",
        "historical_ttm_growth_pct": facts["ttm_revenue_yoy_pct"]["value"],
        "required_revenue_growth_ranges": ranges,
        "growth_sustainability": "not_established_by_trailing_growth_or_sensitivity_math",
        "company_specific_forecast_available": False}


def build_long_horizon_report(
    fundamentals: list[dict[str, Any]], positions: list[dict[str, Any]],
    market: list[dict[str, Any]], policy: dict[str, Any], observed_at: str,
    previous_report: dict[str, Any] | None = None, universe: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    held = {str(row["ticker"]).upper() for row in positions}
    fact_by = {str(row["ticker"]).upper(): row for row in fundamentals}
    quote_by = {str(row["ticker"]).upper(): row for row in market}
    queue = fundamentals_candidate_queue(fundamentals, held, policy)
    selected = {row["ticker"] for row in queue[:policy["candidate_limit"]]}
    companies = {}
    prior_companies = (previous_report or {}).get("companies", {})
    for ticker in sorted(held | selected):
        if ticker in policy["excluded_benchmarks"]:
            is_core = ticker == "SPY"
            companies[ticker] = {
                "readiness": "not_applicable_core" if is_core else "not_applicable_etf",
                "held": ticker in held,
                "thesis": {"status": "core_allocation_policy" if is_core else "allocation_policy_review_required"},
                "review_signals": [], "missing_evidence": [],
            }
            continue
        raw = fact_by.get(ticker, {})
        facts = source_facts(raw, observed_at)
        # Only validated, aligned source observations enter signal comparisons.
        observation = {key: facts[key]["value"] for key in FACT_FIELDS}
        observation.update({"latest_period_end": raw.get("latest_period_end", ""), "source_url": raw.get("source_url", ""),
            "financial_period_type": raw.get("financial_period_type", ""),
            "prior_quarter_period_end": raw.get("prior_quarter_period_end") or facts["revenue_yoy_prior_quarter_pct"]["provenance"].get("end", ""),
            "available_at_utc": facts["revenue_yoy_pct"]["provenance"].get("available_at_utc", "")})
        history = [item for item in prior_companies.get(ticker, {}).get("quarterly_history", [])
                   if item.get("latest_period_end") and item["latest_period_end"] < observation["latest_period_end"]]
        history.sort(key=lambda item: item["latest_period_end"])
        previous = history[-1] if history else None
        signals, comparison_missing = review_signals(observation, previous, policy)
        quote = quote_by.get(ticker, {})
        price = number(quote.get("last_price")) if quote.get("data_quality_label") == "ok" else None
        scenarios = scenario_math(facts, price, policy)
        template = policy["theses"].get(ticker, policy["theses"]["default"])
        missing = ["unresolved_business_evidence:"+item for item in template["business_evidence_required"]]
        missing += scenarios["missing_inputs"] + comparison_missing
        missing += ["unresolved_financial_evidence:"+key for key in (
            "cash_latest", "debt_latest", "ttm_free_cash_flow", "ttm_free_cash_flow_margin_pct", "share_dilution_pct"
        ) if facts[key]["issues"]]
        companies[ticker] = {"held": ticker in held, "readiness": "pending_research",
            "financial_sensitivity_readiness": scenarios["status"], "facts": facts,
            "market_reference": {"price": price, "market_session_date": quote.get("market_session_date", ""), "source": quote.get("data_source", "")},
            "thesis": {"status": "unresolved", **template, "hypotheses_are_unproven": True},
            "thesis_break": {"status": "unconfirmed", "source_url": "", "evidence_date": "", "reason": "Numerical screens require investigation, not an automatic thesis conclusion"},
            "review_signals": signals, "missing_evidence": missing,
            "quarterly_history": (history+[observation])[-8:], "sensitivity_scenarios": scenarios,
            "hurdle_diagnostic": hurdle_diagnostic(scenarios, facts)}
    required = {str(row["ticker"]).upper() for row in (universe or []) if row.get("is_benchmark") != "yes"} | (held-set(policy["excluded_benchmarks"]))
    held_sessions = {quote_by.get(ticker, {}).get("market_session_date", "") for ticker in held}
    market_session = next(iter(held_sessions)) if len(held_sessions) == 1 else ""
    return {"schema_version": "phase5r_long_horizon_research_v1", "generated_at": observed_at,
        "market_session_date": market_session,
        "policy_source": policy["assumption_source"], "candidate_queue": queue,
        "confidence_policy": policy.get("confidence_policy", {}),
        "coverage": {"fundamental_rows": len(fundamentals), "required_company_count": len(required),
            "missing_company_rows": sorted(required-set(fact_by)),
            "unusable_company_rows": sorted(t for t in required & set(fact_by) if fact_by[t].get("data_quality") != "ok")},
        "companies": companies, "canonical_influence_allowed": False,
        "recommendation_authority": False, "automatic_action_allowed": False,
        "model_calls": 0, "broker_connected": False}
