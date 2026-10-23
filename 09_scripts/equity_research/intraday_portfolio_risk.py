"""Source-bound intraday marking of the approved local portfolio.

This overlay never replaces the canonical completed-close decision. It measures
price movement of today's *current recorded inventory* with current ledger cash
held constant at both endpoints. It is not the account's actual daily return,
a peak drawdown, a risk forecast, a new stop, or permission to submit an order.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import account_access
from account_authority import load_authority
from account_common import validate_account_state
from active_config import (load_active_config, validate_allocation_targets,
                           validate_core_allocation_tickers,
                           validate_research_risk_limits)
from daily_common import ET, canonical_sha256, now_et
from investment_plans import TERMINAL, evaluate_plans, regular_close, stamp
from tactical_review import review_open_orders

SCHEMA = "intraday_portfolio_risk_v1"
INPUTS = (
    "00_project_control/active_production_config.json",
    "01_policies/tactical_trade_policy.json",
    "03_source_data/equity_research/universe_seed.csv",
    "05_risk_and_positions/current_account_state.local.json",
    "05_risk_and_positions/current_positions.local.csv",
    "05_risk_and_positions/current_open_orders.local.json",
    "05_risk_and_positions/investment_plans.local.json",
)
POLICY_PATH = "05_risk_and_positions/account_record_policy.local.json"
AGGREGATES = ("portfolio_nav", "baseline_portfolio_nav", "value_change_usd", "value_change_pct")
LIMITATIONS = [
    "Price movement is for the current recorded shares and current ledger cash held fixed at both price endpoints; it is not actual account performance, a peak drawdown, or a flow-adjusted return.",
    "Intraday last-sale marks are time-limited observations, not executable bids, offers, fills, or guaranteed liquidation values; spread and slippage are unverified.",
    "Local ledger cash and known orders govern conditional research; broker buying power, settlement and unrecorded changes remain manual execution checks.",
    "Allocation or plan-condition crossings require source-bound reassessment; they do not create an order, override a company gate, or authorize an email.",
    "Single observations cannot estimate volatility, VaR, expected shortfall, correlation, or a probability of loss. Index overlap with direct stocks remains unquantified.",
]


def _number(value: Any, field: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("intraday_risk_invalid_number:" + field)
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError("intraday_risk_invalid_number:" + field) from exc
    if not result.is_finite() or not math.isfinite(float(result)) or result < 0 or (positive and result <= 0):
        raise ValueError("intraday_risk_invalid_number:" + field)
    return result


def _float(value: Decimal, places: int = 8) -> float:
    return round(float(value), places)


def _read(root: Path, relative: str) -> tuple[bytes, dict]:
    root = root.resolve()
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
        raise ValueError("intraday_risk_unsafe_source_path")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("intraday_risk_source_missing:" + relative)
    if any(parent.is_symlink() for parent in path.parents if parent != root.parent):
        raise ValueError("intraday_risk_unsafe_source_path")
    raw = path.read_bytes()
    return raw, {"path": relative, "sha256": hashlib.sha256(raw).hexdigest()}


def _source(root: Path, source: dict) -> dict:
    if not isinstance(source, dict) or not isinstance(source.get("path"), str):
        raise ValueError("intraday_risk_source_binding_invalid")
    _, current = _read(root, source["path"])
    if current["sha256"] != source.get("sha256"):
        raise ValueError("intraday_risk_source_changed:" + source["path"])
    return current


def _validated_feed(root: Path, snapshot: dict, current: datetime, version: str, symbols: dict, *, historical: bool = False) -> dict:
    # The feed owns raw-response normalization, timestamp/delay admission,
    # previous-close agreement and latest completed-session validation.
    from intraday_prices import validate_snapshot
    scope = snapshot.get("asset_classes", {})
    if not isinstance(scope, dict) or any(scope.get(ticker) != asset for ticker, asset in symbols.items()):
        raise ValueError("intraday_risk_held_price_scope_missing_or_conflicting")
    return validate_snapshot(root, snapshot, current=current, account_version=version,
                             symbols=scope, claim_id=snapshot.get("claim_id"), require_latest=not historical)


def _context(root: Path, current: datetime) -> dict:
    """Capture exact inputs together; the caller later rejects concurrent writes."""
    raws, bindings = {}, []
    for relative in INPUTS:
        raw, source = _read(root, relative)
        raws[relative] = raw
        bindings.append(source)
    authority = load_authority(root, current)
    if (root / POLICY_PATH).exists():
        _, source = _read(root, POLICY_PATH)
        bindings.append(source)
    config = load_active_config(root / INPUTS[0])
    targets = validate_allocation_targets(config["account"])
    caps = validate_research_risk_limits(config["account"]["research_risk_limits"])
    core = set(validate_core_allocation_tickers(config["account"]))
    account = validate_account_state(json.loads(raws[INPUTS[3]]))
    if stamp(account["last_updated"]) > current:
        raise ValueError("intraday_risk_account_observation_after_assessment")
    orders = json.loads(raws[INPUTS[5]])
    positions = list(csv.DictReader(io.StringIO(raws[INPUTS[4]].decode("utf-8"))))
    metadata = {row["ticker"]: row for row in csv.DictReader(io.StringIO(raws[INPUTS[2]].decode("utf-8")))}
    seen, inventory = set(), []
    for row in positions:
        ticker = row.get("ticker", "").strip().upper()
        if not ticker or ticker in seen:
            raise ValueError("intraday_risk_position_inventory_invalid")
        seen.add(ticker)
        qty = _number(row.get("shares_optional"), ticker + ".shares", positive=True)
        if qty != qty.to_integral_value():
            raise ValueError("intraday_risk_nonwhole_recorded_shares")
        is_etf = metadata.get(ticker, {}).get("sector", "").upper() == "ETF"
        if ticker in core and (not is_etf or metadata[ticker].get("is_benchmark") != "yes"):
            raise ValueError("intraday_risk_core_metadata_invalid:" + ticker)
        inventory.append({"ticker": ticker, "shares": int(qty), "sleeve": "core" if ticker in core else "other_etf" if is_etf else "stock"})
    if not isinstance(orders, dict) or not isinstance(orders.get("orders"), list):
        raise ValueError("intraday_risk_order_inventory_invalid")
    held = [{"ticker": x["ticker"], "current_shares": x["shares"]} for x in inventory]
    order_review = review_open_orders(orders, current, current.date(), held,
                                     local_authority=authority.get("local_planning_enabled") is True)
    plans = json.loads(raws[INPUTS[6]])
    plan_context = evaluate_plans(plans, held, current=current, open_orders=orders, root=root)
    latest = {}
    if plan_context.get("status") != "invalid":
        for row in plans["records"]:
            latest[row["plan_id"]] = row
    active = {}
    for row in latest.values():
        if row["state"] not in TERMINAL:
            active.setdefault(row["ticker"], []).append(row)
    tactical = json.loads(raws[INPUTS[1]])
    if (tactical.get("schema_version") != "phase5r_tactical_policy_v1"
            or tactical.get("research_only") is not True or tactical.get("automatic_action_allowed") is not False):
        raise ValueError("intraday_risk_tactical_policy_invalid")
    for key in ("ordinary_risk_pct", "event_risk_pct", "combined_risk_pct", "max_position_pct", "min_reward_to_risk", "max_holding_sessions"):
        _number(tactical.get(key), key, positive=True)
    return {"bindings": bindings, "account": account, "orders": orders, "inventory": inventory,
            "symbols": {x["ticker"]: "etf" if x["sleeve"] in {"core", "other_etf"} else "stocks" for x in inventory},
            "authority": authority, "targets": targets, "caps": caps, "core": sorted(core),
            "order_review": order_review, "plans": active, "plan_context": plan_context, "tactical": tactical}


def _conditions(context: dict, prices: dict, current: datetime) -> tuple[list, list]:
    conditions, triggers = [], []
    states = {x["ticker"]: x for x in context["plan_context"].get("plans", [])}
    for holding in context["inventory"]:
        ticker = holding["ticker"]
        rows = context["plans"].get(ticker, [])
        state = states.get(ticker, {})
        base = {"ticker": ticker, "reference_price": None, "observed_price": prices.get(ticker)}
        if len(rows) != 1:
            item = {**base, "kind": "plan_integrity", "condition": "Current held position needs one valid source-bound plan.",
                    "status": "plan_unverified", "plan_id": None, "plan_version": None, "plan_record_hash": None}
            conditions.append(item); triggers.append(item)
            continue
        plan = rows[0]
        base.update(plan_id=plan["plan_id"], plan_version=plan["version"], plan_record_hash=plan["record_hash"])
        purpose = plan.get("purpose", {})
        for key in ("entry_validity", "exit_rule", "failure_condition"):
            if purpose.get(key):
                conditions.append({**base, "kind": key, "condition": purpose[key], "status": "requires_primary_evidence"})
        if state.get("status") != "maintained":
            item = {**base, "kind": "plan_review", "condition": "Maintained plan status: " + str(state.get("status", "unverified")) + "; do not renew its instruction from a price observation.",
                    "status": state.get("status", "plan_unverified")}
            conditions.append(item); triggers.append(item)
        allocation = plan.get("reviewed_allocation") or {}
        if state.get("status") == "maintained" and ticker in prices and allocation:
            for key, direction in (("invalidation_price", "at_or_below"), ("maximum_entry_price", "at_or_below"), ("reassessment_price", "at_or_above")):
                threshold = float(_number(allocation[key], ticker + "." + key, positive=True))
                crossed = prices[ticker] <= threshold if direction == "at_or_below" else prices[ticker] >= threshold
                item = {**base, "kind": "reviewed_allocation_" + key, "reference_price": threshold,
                    "condition": "Existing source-bound " + key.replace("_", " ") + " observed " + direction.replace("_", " ") + "; reassess the company case and all entry/exit gates. A price alone does not establish eligibility or execution.",
                    "status": "price_condition_met_reassessment_required" if crossed else "price_condition_not_met"}
                conditions.append(item)
                if crossed:
                    triggers.append(item)
        draft = plan.get("order_draft") or {}
        # A threshold is only observable when an existing structured draft is
        # still current. Never extract a dollar amount from prose or a scenario.
        active = (state.get("status") == "maintained" and draft.get("side") == "sell"
                  and draft.get("session_date") == current.date().isoformat()
                  and plan.get("expected_shares") == holding["shares"])
        if active and draft.get("type") == "STOP" and draft.get("stop_price") is not None and ticker in prices:
            threshold = float(_number(draft["stop_price"], ticker + ".stop_price", positive=True))
            crossed = prices[ticker] <= threshold
            item = {**base, "kind": "recorded_stop_review", "reference_price": threshold,
                    "condition": "Observed last sale at or below the existing current structured stop reference requires reassessment; no execution or fill is inferred.",
                    "status": "price_condition_met_reassessment_required" if crossed else "price_condition_not_met"}
            conditions.append(item)
            if crossed:
                triggers.append(item)
    return conditions, triggers


def assess(root: Path, snapshot: dict, current: datetime | None = None, *, _historical: bool = False) -> dict:
    """Build an immutable-data assessment; this function never mutates stores."""
    root = root.resolve(); current = stamp((current or now_et()).isoformat()).astimezone(ET)
    with account_access.account_lock(root, shared=True):
        version = account_access.input_version(root)
        context = _context(root, current)
    result = {"schema_version": SCHEMA, "status": "unavailable", "generated_at": current.isoformat(),
        "session_date": current.date().isoformat(), "mark_as_of": None, "expires_at": None,
        "baseline_session": (snapshot.get("baseline") or {}).get("market_session"),
        **{key: None for key in AGGREGATES}, "cash_usd": float(context["account"]["cash_available"]),
        "cash_basis": context["account"].get("cash_basis", "owner_recorded"),
        "account_input_version": version, "claim_id": snapshot.get("claim_id"),
        "price_snapshot_sha256": canonical_sha256(snapshot),
        "price_snapshot_binding": {"path": snapshot.get("snapshot_path"), "sha256": snapshot.get("snapshot_sha256")}, "positions": [], "allocation": {}, "concentration": {},
        "plan_conditions": [], "reassessment_triggers": [], "tactical_limits": {}, "limitations": list(LIMITATIONS),
        "source_bindings": context["bindings"], "dependencies": [], "performance_is_actual": False,
        "return_basis": "current_recorded_inventory_and_cash_marked_at_prior_close_and_intraday_last_sale",
        "automatic_action_allowed": False, "trading_eligibility_granted": False,
        "email_authorized": False, "new_order_quantities": 0}
    dependencies = result["dependencies"]
    # Retain and verify even failed/partial observations. A failed collection is
    # evidence of a dependency, never a license to drop its original bytes.
    collection_sources = [result["price_snapshot_binding"]]
    for ticker, reason in (snapshot.get("failures") or {}).items():
        dependencies.append("intraday_price:" + str(ticker) + ":" + str(reason))
    for attempt in snapshot.get("attempts", []):
        if isinstance(attempt, dict):
            collection_sources.append(attempt)
            if attempt.get("response"):
                collection_sources.append(attempt["response"])
    for source in collection_sources:
        try:
            result["source_bindings"].append(_source(root, source))
        except (ValueError, OSError, TypeError) as exc:
            dependencies.append(str(exc))
    dependencies.extend(context["order_review"].get("global_blockers", []))
    dependencies.extend(context["plan_context"].get("global_blockers", []))
    try:
        feed = _validated_feed(root, snapshot, current, version, context["symbols"], historical=_historical)
        if feed.get("status") != "current" or feed.get("complete") is not True:
            raise ValueError("intraday_prices_not_complete_current")
        if not set(context["symbols"]) <= set(feed.get("rows", {})):
            raise ValueError("intraday_risk_held_price_coverage_incomplete")
        expires = stamp(feed["expires_at"])
        if not current < expires <= regular_close(current.date().isoformat()):
            raise ValueError("intraday_risk_prices_expired")
        baseline_source = _source(root, feed["baseline"])
        result["source_bindings"].append(baseline_source)
        result["source_bindings"].append(_source(root, result["price_snapshot_binding"]))
        for quote in feed["rows"].values():
            result["source_bindings"].append(_source(root, quote["source"]))
            result["source_bindings"].append(_source(root, quote["source"]["response"]))
        quotes = {ticker: feed["rows"][ticker] for ticker in context["symbols"]}
        cash = _number(context["account"]["cash_available"], "cash_available")
        marked, baseline = cash, cash
        rows, prices = [], {}
        for holding in context["inventory"]:
            ticker, quantity = holding["ticker"], Decimal(holding["shares"])
            quote = quotes[ticker]
            price = _number(quote["price"], ticker + ".price", positive=True)
            prior = _number(quote["previous_close"], ticker + ".previous_close", positive=True)
            if quote.get("previous_close_session") != feed["baseline"]["market_session"]:
                raise ValueError("intraday_risk_baseline_session_conflict")
            price_at, observed = stamp(quote["trade_at"]), stamp(quote["observed_at"])
            if not price_at <= observed <= current or price_at.date() != current.date() or current - price_at > timedelta(seconds=300):
                raise ValueError("intraday_risk_quote_timestamp_invalid")
            value = quantity * price
            marked += value; baseline += quantity * prior; prices[ticker] = float(price)
            rows.append({**holding, "price": float(price), "price_as_of": quote["trade_at"],
                "baseline_price": float(prior), "price_change_pct": _float((price / prior - 1) * 100),
                "market_value": _float(value), "weight_pct": None, "source": quote.get("source_label", "Validated public last sale"),
                "source_url": quote.get("source_url"), "delay_label": quote.get("delay_status", "unverified"), "status": "current"})
        if marked <= 0 or baseline <= 0:
            raise ValueError("intraday_risk_nav_invalid")
        for row in rows:
            row["weight_pct"] = _float(Decimal(str(row["market_value"])) / marked * 100)
        sleeve = {name: sum(Decimal(str(r["market_value"])) for r in rows if r["sleeve"] == name) for name in ("core", "stock", "other_etf")}
        core_pct, stock_pct = sleeve["core"] / marked * 100, sleeve["stock"] / marked * 100
        core_min, stock_max = context["targets"].get("core_minimum_pct", context["targets"]["core_target_pct"]), context["caps"]["active_stock_hard_cap_pct"]
        result["allocation"] = {"core_weight_pct": _float(core_pct), "stock_weight_pct": _float(stock_pct),
            "cash_weight_pct": _float(cash / marked * 100), "other_etf_weight_pct": _float(sleeve["other_etf"] / marked * 100),
            "core_minimum_pct": core_min, "stock_maximum_pct": stock_max, "core_tickers": context["core"],
            "core_status": "below_minimum_reassessment_required" if core_pct < Decimal(str(core_min)) else "within_minimum",
            "stock_status": "above_maximum_reassessment_required" if stock_pct > Decimal(str(stock_max)) else "within_maximum"}
        largest = max(rows, key=lambda r: r["market_value"], default={})
        largest_stock = max((r for r in rows if r["sleeve"] == "stock"), key=lambda r: r["market_value"], default={})
        result["concentration"] = {"largest_position_ticker": largest.get("ticker"), "largest_position_weight_pct": largest.get("weight_pct"),
            "largest_stock_ticker": largest_stock.get("ticker"), "largest_stock_weight_pct": largest_stock.get("weight_pct"),
            "single_stock_cap_pct": context["caps"]["single_stock_hard_cap_pct"],
            "fixed_single_stock_cap": context["caps"]["single_stock_hard_cap_pct"] is not None, "overlap_assessed": False}
        result.update(status="current", positions=rows, portfolio_nav=_float(marked), baseline_portfolio_nav=_float(baseline),
            value_change_usd=_float(marked - baseline), value_change_pct=_float((marked / baseline - 1) * 100),
            mark_as_of=min(q["trade_at"] for q in quotes.values()) if quotes else current.isoformat(),
            expires_at=feed["expires_at"], baseline_session=feed["baseline"]["market_session"])
        result["plan_conditions"], result["reassessment_triggers"] = _conditions(context, prices, current)
        for sleeve_name, status_key in (("core", "core_status"), ("stock", "stock_status")):
            if result["allocation"][status_key] not in {"within_minimum", "within_maximum"}:
                result["reassessment_triggers"].append({"ticker": "PORTFOLIO", "kind": "allocation", "status": result["allocation"][status_key],
                    "condition": "Current marked " + sleeve_name + " allocation crosses the existing approved boundary; reassess without an automatic rebalance.",
                    "reference_price": None, "observed_price": None})
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result["status"] = "partial" if snapshot.get("status") == "partial" else "unavailable"
        dependencies.append(str(exc))
        for key in AGGREGATES:
            result[key] = None
        result.update(positions=[], allocation={}, concentration={}, mark_as_of=None, expires_at=None)
        result["plan_conditions"], result["reassessment_triggers"] = _conditions(context, {}, current)
    tactical = context["tactical"]
    held_tactical = [x["ticker"] for x in context["inventory"] if any(p.get("role") == "tactical" for p in context["plans"].get(x["ticker"], []))]
    plans_classified = all(len(context["plans"].get(x["ticker"], [])) == 1
        and context["plans"][x["ticker"]][0].get("role") in {"broad_core", "long_term_growth"}
        for x in context["inventory"])
    no_tactical_exposure = (plans_classified and not held_tactical and not context["order_review"].get("active_tickers")
        and not context["order_review"].get("global_blockers") and context["plan_context"].get("status") != "invalid" and not context["plan_context"].get("conflicts"))
    confirmed = context["orders"].get("existing_tactical_risk_confirmed") is True
    risk = context["orders"].get("existing_tactical_risk_usd") if confirmed else 0.0 if no_tactical_exposure else None
    if risk is not None:
        risk = float(_number(risk, "existing_tactical_risk_usd"))
    result["tactical_limits"] = {key: tactical[key] for key in ("ordinary_risk_pct", "event_risk_pct", "combined_risk_pct", "max_position_pct", "min_reward_to_risk", "max_holding_sessions")}
    result["tactical_limits"].update(existing_planned_risk_usd=risk,
        existing_planned_risk_basis="recorded_confirmed" if confirmed else "no_tactical_positions_or_known_active_orders_in_local_ledger" if no_tactical_exposure else "unverified",
        risk_budget_basis="Current marked NAV when complete; planned risk is not a guaranteed maximum loss.",
        combined_planned_risk_pct=_float(Decimal(str(risk)) / Decimal(str(result["portfolio_nav"])) * 100) if risk is not None and result["portfolio_nav"] else None,
        known_buy_reservations_usd=context["order_review"].get("cash_reservation_usd"), held_tactical_tickers=held_tactical)
    if result["tactical_limits"]["combined_planned_risk_pct"] is not None:
        result["tactical_limits"]["combined_status"] = "above_existing_budget_reassessment_required" if result["tactical_limits"]["combined_planned_risk_pct"] > tactical["combined_risk_pct"] else "within_existing_budget"
    else:
        result["tactical_limits"]["combined_status"] = "unverified"
    if result["tactical_limits"]["combined_status"] == "above_existing_budget_reassessment_required":
        result["reassessment_triggers"].append({"ticker": "PORTFOLIO", "kind": "tactical_budget",
            "condition": "Recorded existing tactical planned loss exceeds the unchanged combined risk budget on current marked NAV; reassessment required, with no automatic order.",
            "status": "above_existing_budget_reassessment_required", "reference_price": None, "observed_price": None})
    try:
        for source in result["source_bindings"]:
            _source(root, source)
    except (ValueError, OSError) as exc:
        result["status"] = "unavailable"
        result["dependencies"].append(str(exc))
        _suppress_marks(result)
    if account_access.capture_version(root) != version:
        result["status"] = "account_changed"
        result["dependencies"].append("intraday_risk_account_changed_reassess_required")
        _suppress_marks(result)
    result["source_bindings"] = list({x["path"]: x for x in result["source_bindings"]}.values())
    result["dependencies"] = sorted(set(result["dependencies"]))
    result["assessment_sha256"] = canonical_sha256(result)
    return result


def _suppress_marks(result: dict) -> None:
    for key in AGGREGATES:
        result[key] = None
    result["allocation"], result["concentration"] = {}, {}
    if isinstance(result.get("tactical_limits"), dict):
        result["tactical_limits"]["combined_planned_risk_pct"] = None
        result["tactical_limits"]["combined_status"] = "unverified"
    for row in result.get("positions", []):
        row.update(price=None, price_change_pct=None, market_value=None, weight_pct=None, status="unavailable")
    for condition in result.get("plan_conditions", []):
        condition["observed_price"] = None
        if condition.get("kind") == "recorded_stop_review" or str(condition.get("kind", "")).startswith("reviewed_allocation_"):
            condition["status"] = "intraday_observation_unavailable"
    result["reassessment_triggers"] = [x for x in result.get("reassessment_triggers", []) if x.get("kind") not in {"allocation", "recorded_stop_review", "tactical_budget"} and not str(x.get("kind", "")).startswith("reviewed_allocation_")]


def projection(root: Path, assessment: dict, current: datetime | None = None) -> dict:
    """Read-time projection: expired/changed evidence never keeps live totals."""
    current = stamp((current or now_et()).isoformat()).astimezone(ET)
    result = copy.deepcopy(assessment)
    if not isinstance(result, dict) or result.get("schema_version") != SCHEMA:
        return {"schema_version": SCHEMA, "status": "unavailable", "positions": [], "dependencies": ["intraday_risk_assessment_missing_or_invalid"]}
    original_verified = False
    try:
        validate_assessment(root, assessment, current=current)
        original_verified = True
        if result.get("assessment_sha256") != canonical_sha256({k: v for k, v in result.items() if k != "assessment_sha256"}):
            raise ValueError("intraday_risk_assessment_hash_invalid")
        if stamp(result["generated_at"]) > current:
            raise ValueError("intraday_risk_assessment_future")
        if result.get("account_input_version") != account_access.capture_version(root):
            raise ValueError("intraday_risk_account_changed_reassess_required")
        for source in result["source_bindings"]:
            _source(root.resolve(), source)
        if result.get("status") == "current":
            from intraday_prices import load_latest
            latest = load_latest(root)
            if (latest.get("snapshot_path") != result["price_snapshot_binding"].get("path")
                    or latest.get("snapshot_sha256") != result["price_snapshot_binding"].get("sha256")):
                raise ValueError("intraday_risk_newer_price_attempt_requires_recomposition")
            if result.get("session_date") != current.date().isoformat() or not current < stamp(result["expires_at"]):
                result["status"] = "expired"
                raise ValueError("intraday_risk_marks_expired")
            if current >= regular_close(current.date().isoformat()):
                result["status"] = "expired"
                raise ValueError("intraday_risk_regular_session_closed")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        if result.get("status") != "expired":
            result["status"] = "unavailable"
        result["dependencies"] = sorted(set([*result.get("dependencies", []), str(exc)]))
        _suppress_marks(result)
    if original_verified:
        try:
            # A plan can become due inside a still-fresh price observation.
            # Re-evaluate only its current deadline/status, preserving the
            # original source-bound assessment and all numerical limits.
            context = _context(root.resolve(), current)
            for source in assessment["source_bindings"]:
                _source(root, source)
            if account_access.capture_version(root) != assessment["account_input_version"]:
                raise ValueError("intraday_risk_account_changed_reassess_required")
            current_prices = {row["ticker"]: row["price"] for row in result.get("positions", [])
                              if row.get("price") is not None} if result.get("status") == "current" else {}
            retained = [x for x in result.get("reassessment_triggers", []) if x.get("kind") in {"allocation", "tactical_budget"}]
            result["plan_conditions"], result["reassessment_triggers"] = _conditions(context, current_prices, current)
            result["reassessment_triggers"].extend(retained)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result["status"] = "unavailable"
            result["dependencies"] = sorted(set([*result.get("dependencies", []), str(exc)]))
            _suppress_marks(result)
    result["projected_at"] = current.isoformat()
    return result


def validate_assessment(root: Path, assessment: dict, current: datetime | None = None) -> dict:
    """Recompute the original observation against current exact input bytes.

    Publication validates at its observation clock; later expiry is handled by
    the optional overlay projection and never turns a dated EOD decision into
    an intraday claim. This validates arithmetic, not merely a resealable hash.
    """
    if not isinstance(assessment, dict) or assessment.get("schema_version") != SCHEMA:
        raise ValueError("intraday_risk_assessment_schema_invalid")
    if assessment.get("assessment_sha256") != canonical_sha256({k: v for k, v in assessment.items() if k != "assessment_sha256"}):
        raise ValueError("intraday_risk_assessment_hash_invalid")
    for source in assessment.get("source_bindings", []):
        _source(root, source)
    recorded = stamp(assessment["generated_at"])
    # An explicitly supplied time is a publication observation clock, not a way
    # to freshen the original feed or extend its immutable expiry.
    if current is not None and stamp(current.isoformat()) < recorded:
        raise ValueError("intraday_risk_assessment_future")
    binding = assessment.get("price_snapshot_binding", {})
    _source(root, binding)
    raw, _ = _read(root, binding["path"])
    snapshot = json.loads(raw)
    snapshot.update(snapshot_path=binding["path"], snapshot_sha256=binding["sha256"])
    expected = assess(root, snapshot, recorded, _historical=True)
    if expected != assessment:
        raise ValueError("intraday_risk_assessment_recomposition_mismatch")
    return copy.deepcopy(expected)


build = assess
