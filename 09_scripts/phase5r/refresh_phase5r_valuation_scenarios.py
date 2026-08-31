#!/usr/bin/env python3
"""Build deterministic, source-bound valuation ranges for active research."""

from __future__ import annotations

import csv
import hashlib
import json
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
    return result if result == result else None


def utc_text(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def main() -> int:
    policy = read_json(POLICY_PATH)
    baseline = read_csv(BASELINE_PATH)
    fundamentals = {row["ticker"].upper(): row for row in read_csv(FUNDAMENTALS_PATH)}
    market = {row["ticker"].upper(): row for row in read_csv(MARKET_SNAPSHOT_PATH)}
    policy_text = POLICY_PATH.read_text(encoding="utf-8").rstrip("\n")
    prepared_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
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
        revenue_basis = "reported_trailing_four_quarters"
        if ttm_revenue is None:
            latest_revenue = number(fact.get("revenue_latest"))
            ttm_revenue = latest_revenue * 4.0 if latest_revenue is not None else None
            revenue_basis = "latest_quarter_annualized_due_to_missing_trailing_four_quarters"
        growth = number(fact.get("ttm_revenue_yoy_pct"))
        if growth is None:
            growth = number(fact.get("revenue_yoy_pct"))
        growth = growth if growth is not None else 0.0
        fcf = number(fact.get("ttm_free_cash_flow"))
        fcf_margin = number(fact.get("ttm_free_cash_flow_margin_pct"))
        dilution = number(fact.get("share_dilution_pct"))
        if None in {price, shares, cash, ttm_revenue} or not price or not shares or not ttm_revenue:
            row["valuation_check"] = "insufficient_current_SEC_inputs_for_per_share_valuation"
            row["valuation_reasonableness_score"] = "2.0"
            updated_rows.append(row)
            scenario_records.append({
                "ticker": ticker,
                "status": "insufficient",
                "missing_inputs": [
                    name for name, value in {
                        "share_price": price, "diluted_shares": shares,
                        "cash": cash, "revenue": ttm_revenue,
                    }.items() if value is None
                ],
                "market_source_url": "",
                "fundamental_source_url": fact.get("source_url", ""),
            })
            continue
        debt = debt or 0.0
        band = selected_band(policy, growth)
        adjustment = 0.0
        adjustments: list[str] = []
        if fcf_margin is not None and fcf_margin >= 10.0:
            adjustment += float(policy["adjustments"]["positive_fcf_margin_pct_at_least_10"])
            adjustments.append("positive_fcf_margin")
        elif fcf_margin is not None and fcf_margin < 0.0:
            adjustment += float(policy["adjustments"]["negative_fcf_margin_pct"])
            adjustments.append("negative_fcf_margin")
        if cash / ttm_revenue * 100.0 >= 20.0:
            adjustment += float(policy["adjustments"]["net_cash_to_revenue_pct_at_least_20"])
            adjustments.append("cash_to_revenue")
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
        accepted_sec = utc_text(fact.get("fetched_at") or prepared_at)
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
        if revenue_basis == "reported_trailing_four_quarters":
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
