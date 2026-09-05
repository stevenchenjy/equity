#!/usr/bin/env python3
"""Build deterministic, source-bound valuation ranges for active research."""

from __future__ import annotations

import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from phase5r_daily_common import (
    FUNDAMENTALS_PATH,
    MARKET_SNAPSHOT_PATH,
    ROOT,
    atomic_write_csv,
    atomic_write_json,
    iso_now,
    read_csv,
    read_json,
)
from phase5r_valuation_input_bundle import (
    DEFAULT_BUNDLE_PATH,
    SCHEMA_VERSION as BUNDLE_SCHEMA_VERSION,
    seal_bundle,
)


BASELINE_PATH = (
    ROOT / "04_research" / "realtime_stock_picker_phase5r"
    / "phase5r_current_research_baseline.csv"
)
SCENARIO_PATH = ROOT / "04_data" / "phase5r" / "phase5r_valuation_scenarios.local.json"
POLICY_PATH = ROOT / "01_policies" / "phase5r_valuation_scenario_policy.json"


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def utc_text(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_now_text() -> str:
    """Match the packet clock's whole-second point-in-time precision."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def line_excerpt(path: Path, ticker: str) -> tuple[int, int, str]:
    text = path.read_text(encoding="utf-8")
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.startswith(f"{ticker},"):
            excerpt = line.rstrip("\r\n")
            return offset, offset + len(excerpt), excerpt
        offset += len(line)
    raise ValueError(f"cannot bind valuation source row for {ticker}")


def source(
    *, source_id: str, ticker: str, source_type: str, accepted_at: str,
    source_url: str, path: Path, field: str, authority: str,
) -> dict[str, Any]:
    start, end, excerpt = line_excerpt(path, ticker) if ticker else (
        0, len(path.read_text(encoding="utf-8").rstrip("\n")),
        path.read_text(encoding="utf-8").rstrip("\n"),
    )
    return {
        "source_id": source_id,
        "ticker": ticker,
        "source_type": source_type,
        "accepted_at_utc": accepted_at,
        "source_url": source_url,
        "relative_path": str(path.relative_to(ROOT)),
        "char_start": start,
        "char_end": end,
        "content_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        "field": field,
        "authority": authority,
    }


def valuation_input(
    value: float, unit: str, period: str, available_at: str,
    source_ids: list[str], evidence_kind: str = "observation",
) -> dict[str, Any]:
    return {
        "value": f"{value:.8f}".rstrip("0").rstrip("."),
        "unit": unit,
        "period": period,
        "available_at_utc": available_at,
        "source_ids": source_ids,
        "evidence_kind": evidence_kind,
    }


def selected_band(policy: dict[str, Any], growth: float) -> dict[str, Any]:
    for band in policy["growth_bands"]:
        if growth >= float(band["minimum_yoy_pct"]):
            return band
    raise ValueError("valuation policy has no matching growth band")


def valuation_input_issues(fact: dict[str, Any], quote: dict[str, Any], as_of: str) -> list[str]:
    """Fail closed before producing a range, not merely before order routing."""
    issues = []
    required = {
        "share_price": quote.get("last_price"),
        "diluted_shares": fact.get("diluted_shares_latest"),
        "cash": fact.get("cash_latest"), "total_debt": fact.get("debt_latest"),
        "ttm_revenue": fact.get("ttm_revenue"), "ttm_growth": fact.get("ttm_revenue_yoy_pct"),
        "free_cash_flow_margin": fact.get("ttm_free_cash_flow_margin_pct"),
        "share_dilution": fact.get("share_dilution_pct"),
    }
    for name, raw in required.items():
        value = number(raw)
        if value is None:
            issues.append(f"missing_{name}")
        elif name in {"share_price", "diluted_shares", "ttm_revenue"} and value <= 0:
            issues.append(f"nonpositive_{name}")
        elif name in {"cash", "total_debt"} and value < 0:
            issues.append(f"negative_{name}")
    if fact.get("selection_version") != "period_bound_companyfacts_v2":
        issues.append("period_bound_financial_selection_required")
    if fact.get("data_quality") != "ok" or fact.get("valuation_input_quality") != "complete":
        issues.append("financial_input_quality_not_complete")
    anchor = fact.get("latest_period_end")
    if not anchor or fact.get("ttm_period_end") != anchor:
        issues.append("ttm_period_not_aligned")
    try:
        provenance = json.loads(fact.get("field_provenance_json", "{}"))
        cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        for name, unit in (("cash_latest", "USD"), ("debt_latest", "USD"),
                           ("ttm_revenue", "USD"), ("diluted_shares_latest", "shares")):
            item = provenance.get(name, {})
            if (item.get("status") != "available" or item.get("end") != anchor
                    or item.get("unit") != unit):
                issues.append(f"unbound_or_misaligned_{name}")
                continue
            available = datetime.fromisoformat(item.get("available_at_utc", "").replace("Z", "+00:00"))
            if available.tzinfo is None or available > cutoff:
                issues.append(f"unavailable_at_cutoff_{name}")
            # A provenance block cannot silently diverge from its CSV value.
            if number(item.get("val")) != number(fact.get(name)):
                issues.append(f"provenance_value_mismatch_{name}")
    except (ValueError, TypeError, AttributeError):
        issues.append("invalid_field_provenance")
    return sorted(set(issues))


def main() -> int:
    policy = read_json(POLICY_PATH)
    baseline = read_csv(BASELINE_PATH)
    fundamentals = {row["ticker"].upper(): row for row in read_csv(FUNDAMENTALS_PATH)}
    market = {row["ticker"].upper(): row for row in read_csv(MARKET_SNAPSHOT_PATH)}
    policy_text = POLICY_PATH.read_text(encoding="utf-8").rstrip("\n")
    # The downstream packet clock is second-resolution.  Retaining
    # microseconds here can make a bundle produced in the same second appear
    # fractionally future-dated and fail an otherwise valid refresh.
    prepared_at = utc_now_text()
    scenario_records: list[dict[str, Any]] = []
    bundle_records: list[dict[str, Any]] = []
    updated_rows: list[dict[str, str]] = []
    for row in baseline:
        ticker = row["ticker"].upper()
        if ticker == "SPY":
            row["valuation_check"] = "broad_market_core_candidate; individual-company EV/revenue model not applicable"
            row["valuation_reasonableness_score"] = "5.0"
            updated_rows.append(row)
            continue
        fact = fundamentals.get(ticker, {})
        quote = market.get(ticker, {})
        price = number(quote.get("last_price"))
        shares = number(fact.get("diluted_shares_latest"))
        cash = number(fact.get("cash_latest"))
        debt = number(fact.get("debt_latest"))
        ttm_revenue = number(fact.get("ttm_revenue"))
        revenue_basis = "period_bound_reported_or_derived_ttm"
        growth = number(fact.get("ttm_revenue_yoy_pct"))
        fcf = number(fact.get("ttm_free_cash_flow"))
        fcf_margin = number(fact.get("ttm_free_cash_flow_margin_pct"))
        dilution = number(fact.get("share_dilution_pct"))
        input_issues = valuation_input_issues(fact, quote, prepared_at)
        if input_issues:
            row["valuation_check"] = "insufficient_current_SEC_inputs_for_per_share_valuation"
            row["valuation_reasonableness_score"] = "2.0"
            updated_rows.append(row)
            scenario_records.append({
                "ticker": ticker,
                "status": "insufficient",
                "missing_inputs": [issue.removeprefix("missing_") for issue in input_issues if issue.startswith("missing_")],
                "input_limitations": input_issues,
                "financial_input_limitations": fact.get("valuation_input_limitations", ""),
                "automatic_action_allowed": False,
                "market_source_url": "",
                "fundamental_source_url": fact.get("source_url", ""),
            })
            continue
        band = selected_band(policy, growth)
        adjustment = 0.0
        adjustments: list[str] = []
        if fcf_margin is not None and fcf_margin >= 10.0:
            adjustment += float(policy["adjustments"]["positive_fcf_margin_pct_at_least_10"])
            adjustments.append("positive_fcf_margin")
        elif fcf_margin is not None and fcf_margin < 0.0:
            adjustment += float(policy["adjustments"]["negative_fcf_margin_pct"])
            adjustments.append("negative_fcf_margin")
        if (cash - debt) / ttm_revenue * 100.0 >= 20.0:
            adjustment += float(policy["adjustments"]["net_cash_to_revenue_pct_at_least_20"])
            adjustments.append("net_cash_to_revenue")
        if dilution is not None and dilution > 5.0:
            adjustment += float(policy["adjustments"]["share_dilution_pct_above_5"])
            adjustments.append("share_dilution")
        lower = float(policy["caps"]["minimum_multiple"])
        upper = float(policy["caps"]["maximum_multiple"])
        multiples = {
            key: max(lower, min(upper, float(band[f"{key}_multiple"]) + adjustment))
            for key in ("bear", "base", "bull")
        }
        market_cap = price * shares
        enterprise_value = market_cap + debt - cash
        current_multiple = enterprise_value / ttm_revenue
        prices = {
            key: max(0.0, (multiple * ttm_revenue - debt + cash) / shares)
            for key, multiple in multiples.items()
        }
        expected_upside = (prices["base"] / price - 1.0) * 100.0
        downside_pct = (prices["bear"] / price - 1.0) * 100.0
        reward_to_risk = (
            max(0.0, prices["base"] - price) / max(0.01, price - prices["bear"])
            if prices["bear"] < price else 99.0
        )
        valuation_score = (
            9.0 if price <= prices["bear"] else 7.0 if price <= prices["base"]
            else 5.0 if price <= prices["bull"] else 3.0
        )
        scenario = {
            "ticker": ticker,
            "status": "complete",
            "as_of_market_session": quote.get("market_session_date", ""),
            "current_price": round(price, 2),
            "diluted_shares": round(shares, 2),
            "cash": round(cash, 2),
            "debt": round(debt, 2),
            "revenue_ttm_or_proxy": round(ttm_revenue, 2),
            "revenue_basis": revenue_basis,
            "revenue_growth_pct": round(growth, 2),
            "free_cash_flow_ttm": None if fcf is None else round(fcf, 2),
            "free_cash_flow_margin_pct": None if fcf_margin is None else round(fcf_margin, 2),
            "share_dilution_pct": None if dilution is None else round(dilution, 2),
            "current_ev_to_revenue": round(current_multiple, 3),
            "scenario_multiples": {key: round(value, 2) for key, value in multiples.items()},
            "scenario_prices": {key: round(value, 2) for key, value in prices.items()},
            "expected_upside_pct": round(expected_upside, 2),
            "base_scenario_gap_pct": round(expected_upside, 2),
            "metric_interpretation": {
                "expected_upside_pct": "legacy_alias_of_base_scenario_gap_not_probability_weighted_expected_return",
                "reward_to_risk": "scenario_distance_ratio_not_calibrated_expected_payoff",
                "horizon": "not_estimated", "scenario_probabilities": "not_estimated",
                "method_status": "transparent_policy_comparator_not_company_specific_cash_flow_valuation",
            },
            "bear_downside_pct": round(downside_pct, 2),
            "reward_to_risk": round(reward_to_risk, 2),
            "valuation_score_0_to_10": valuation_score,
            "adjustments_applied": adjustments,
            "strongest_positive_evidence": f"revenue_growth_pct={growth:.2f}",
            "strongest_negative_evidence": (
                f"share_dilution_pct={dilution:.2f}" if dilution is not None and dilution > 5
                else f"current_ev_to_revenue={current_multiple:.2f}"
            ),
            "assumption_policy": str(POLICY_PATH.relative_to(ROOT)),
            "market_source": str(MARKET_SNAPSHOT_PATH.relative_to(ROOT)),
            "fundamental_source": str(FUNDAMENTALS_PATH.relative_to(ROOT)),
            "fundamental_source_url": fact.get("source_url", ""),
            "automatic_action_allowed": False,
        }
        scenario_records.append(scenario)
        row["valuation_check"] = (
            f"current_EV/revenue={current_multiple:.2f}x; bear/base/bull="
            f"${prices['bear']:.2f}/${prices['base']:.2f}/${prices['bull']:.2f}; "
            f"revenue_basis={revenue_basis}"
        )
        row["valuation_reasonableness_score"] = f"{valuation_score:.1f}"
        updated_rows.append(row)

        market_id = f"valuation-market:{ticker}:{quote.get('market_session_date', '')}"
        sec_id = f"valuation-sec:{ticker}:{fact.get('latest_period_end', '')}"
        policy_id = f"valuation-policy:{ticker}:{policy['effective_from']}"
        accepted_market = utc_text(quote.get("data_timestamp") or prepared_at)
        field_provenance = json.loads(fact["field_provenance_json"])
        accepted_sec = utc_text(max(
            item["available_at_utc"] for item in field_provenance.values()
            if isinstance(item, dict) and item.get("status") == "available"
        ))
        policy_source = {
            "source_id": policy_id,
            "ticker": ticker,
            "source_type": "deterministic_valuation_policy",
            "accepted_at_utc": f"{policy['effective_from']}T00:00:00Z",
            "source_url": "",
            "relative_path": str(POLICY_PATH.relative_to(ROOT)),
            "char_start": 0,
            "char_end": len(policy_text),
            "content_sha256": hashlib.sha256(policy_text.encode("utf-8")).hexdigest(),
            "field": "growth_bands_and_adjustments",
            "authority": "deterministic_policy",
        }
        sources = [
            source(
                source_id=market_id, ticker=ticker,
                source_type="public_market_valuation_observation",
                accepted_at=accepted_market, source_url="",
                path=MARKET_SNAPSHOT_PATH, field="last_price",
                authority="secondary_public_market_context",
            ),
            source(
                source_id=sec_id, ticker=ticker, source_type="sec_valuation_fact",
                accepted_at=accepted_sec, source_url=fact.get("source_url", ""),
                path=FUNDAMENTALS_PATH,
                field="diluted_shares,cash,debt,revenue,free_cash_flow",
                authority="primary_official",
            ),
            policy_source,
        ]
        inputs = {
            "share_price": valuation_input(price, "USD_per_share", quote.get("market_session_date", ""), accepted_market, [market_id]),
            "diluted_shares": valuation_input(shares, "shares", fact.get("latest_period_end", ""), accepted_sec, [sec_id]),
            "cash_and_equivalents": valuation_input(cash, "USD", fact.get("latest_period_end", ""), accepted_sec, [sec_id]),
            "total_debt": valuation_input(debt, "USD", fact.get("latest_period_end", ""), accepted_sec, [sec_id]),
            "target_price_assumption": valuation_input(prices["base"], "USD_per_share", policy["effective_from"], f"{policy['effective_from']}T00:00:00Z", [policy_id], "scenario_assumption"),
            "downside_price_assumption": valuation_input(prices["bear"], "USD_per_share", policy["effective_from"], f"{policy['effective_from']}T00:00:00Z", [policy_id], "scenario_assumption"),
        }
        inputs["revenue_ttm"] = valuation_input(ttm_revenue, "USD", f"TTM through {fact.get('latest_period_end', '')}", accepted_sec, [sec_id])
        if fcf is not None:
            inputs["free_cash_flow_ttm"] = valuation_input(fcf, "USD", f"TTM through {fact.get('latest_period_end', '')}", accepted_sec, [sec_id])
        prior_shares = number(fact.get("diluted_shares_prior_year"))
        if prior_shares is not None and prior_shares > 0:
            inputs["prior_diluted_shares"] = valuation_input(prior_shares, "shares", "prior-year comparable quarter", accepted_sec, [sec_id])
        bundle_records.append({"ticker": ticker, "inputs": inputs, "sources": sources})

    atomic_write_csv(BASELINE_PATH, list(updated_rows[0].keys()), updated_rows)
    scenario_payload = {
        "schema_version": "phase5r_valuation_scenarios_v1",
        "generated_at": iso_now(),
        "policy": str(POLICY_PATH.relative_to(ROOT)),
        "records": scenario_records,
        "boundaries": {
            "research_only": True, "automatic_action_allowed": False,
            "broker_connected": False, "order_code_created": False,
            "trade_placed": False,
        },
    }
    atomic_write_json(SCENARIO_PATH, scenario_payload)
    unsigned_bundle = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "prepared_at_utc": prepared_at,
        "records": bundle_records,
        "boundaries": {
            "research_only": True, "canonical_effect": False,
            "email_eligible": False, "automatic_action_allowed": False,
            "broker_connected": False, "broker_account_read": False,
            "order_code_created": False, "trade_placed": False,
            "network_used": False, "credentials_read": False,
            "smtp_config_read": False,
        },
        "bundle_sha256": "",
    }
    atomic_write_json(DEFAULT_BUNDLE_PATH, seal_bundle(unsigned_bundle))
    complete = sum(record["status"] == "complete" for record in scenario_records)
    print(
        f"valuation_scenarios_complete={complete} total={len(scenario_records)} "
        "source_bound=true model_used=false automatic_action_allowed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
