"""Dated combined-account planning evidence. Brokerage cash and orders stay account-specific."""
from __future__ import annotations

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR
from hashlib import sha256
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

MANIFEST = "05_risk_and_positions/household_planning.local.json"
RESEARCH_MANIFEST = "05_risk_and_positions/household_research.local.json"
SOURCE_DIR = Path("05_risk_and_positions/household_sources.local")
CONFIG = "00_project_control/active_production_config.json"
SCHEMA = "equity_household_planning_v1"
CENT = Decimal("0.01")
CORE = {"SPY", "QQQM"}


def _check(condition, code):
    if not condition:
        raise ValueError(code)


def _amount(value):
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("household_amount_invalid") from exc
    _check(number.is_finite() and number >= 0, "household_amount_invalid")
    return number


def _cash(value):
    return format(value.quantize(CENT), "f")


def _quantity(value):
    return format(value.normalize(), "f")


def _clock(value, current):
    moment = datetime.fromisoformat(value)
    _check(moment.tzinfo is not None and moment <= current, "household_observation_clock_invalid")
    return moment


def _positions(rows):
    result = {}
    for row in rows:
        symbol = row["ticker"]
        _check(isinstance(symbol, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,12}", symbol)
               and symbol not in result, "household_position_invalid")
        qty, value = _amount(row["quantity_shares"]), _amount(row["market_value_usd"])
        _check(qty > 0, "household_position_invalid")
        result[symbol] = qty, value
    return result


def _observed(root, current, manifest):
    _check(manifest["schema_version"] == "equity_household_planning_input_v1", "household_manifest_invalid")
    path, digest = manifest["broker_observation_path"], manifest["broker_observation_sha256"]
    _check(isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest)
           and path == str(SOURCE_DIR / (digest + ".json")), "household_source_binding_invalid")
    raw = (root / path).read_bytes()
    _check(sha256(raw).hexdigest() == digest, "household_broker_observation_changed")
    observation = json.loads(raw)
    _check(observation["schema"] == "private_brokerage_observation_v1", "household_observation_invalid")
    policy = json.loads((root / CONFIG).read_bytes())["account"]
    core_pct = _amount(policy["core_minimum_pct"])
    stock_pct = _amount(policy["research_risk_limits"]["active_stock_hard_cap_pct"])
    _check(core_pct <= 100 and stock_pct <= 100 and set(policy["core_allocation_tickers"]) == CORE,
           "household_allocation_policy_unverified")
    chase, moomoo = (observation["accounts"][key] for key in ("chase", "moomoo"))
    _check(chase["currency"] == moomoo["currency"] == "USD", "household_currency_unverified")
    chase_time = chase["source"]["positions_and_balances_reported_asof_et"]
    moomoo_time = moomoo["source"]["local_screen_clock_et"]
    approval = _clock(manifest["observed_at"], current)
    _check(max(_clock(chase_time, current), _clock(moomoo_time, current)) <= approval,
           "household_observation_after_approval")
    outside = _amount(manifest["external_assets_usd"])
    listed = [_positions(broker["positions"]) for broker in (chase, moomoo)]
    c, m = listed
    balances = chase["balances_usd"]
    chase_cash = _amount(balances["cash_and_sweep_funds"])
    reported = _amount(balances["account_value"])
    moomoo_total = _amount(moomoo["assets"]["displayed_total_assets_usd"])
    _check(abs(sum(v for _, v in c.values()) + chase_cash - reported) <= CENT,
           "household_chase_total_conflict")
    # A margin account's published total is net of liabilities. Long holdings
    # may exceed total equity and must still count toward portfolio exposure.
    household_total = reported + moomoo_total + outside
    _check(household_total > 0, "household_total_invalid")
    rows = []
    core = Decimal(0)
    stocks = Decimal(0)
    for symbol in sorted(c.keys() | m.keys()):
        c_qty, c_value = c.get(symbol, (Decimal(0), Decimal(0)))
        m_qty, m_value = m.get(symbol, (Decimal(0), Decimal(0)))
        value = c_value + m_value
        if symbol in CORE:
            core += value
        else:
            stocks += value
        rows.append(dict(ticker=symbol, chase_shares=_quantity(c_qty), moomoo_shares=_quantity(m_qty),
                         observed_value_usd=_cash(value), moomoo_value_usd=_cash(m_value)))
    # An altered broker inventory or cash invalidates the paired observation
    # until the updated cross-account scope and any transfers are reconciled.
    state = json.loads((root / "05_risk_and_positions/current_account_state.local.json").read_bytes())
    with (root / "05_risk_and_positions/current_positions.local.csv").open(newline="") as stream:
        records = list(csv.DictReader(stream))
    ledger = {r["ticker"]: _amount(r["shares_optional"]) for r in records}
    same_chase = (len(ledger) == len(records) and ledger == {s: q for s, (q, _) in c.items()}
                  and _amount(state["cash_available"]) == _amount(balances["cash_available_to_trade"]))
    return dict(schema_version=SCHEMA, status="observed", observed_at=manifest["observed_at"],
                broker_observation_sha256=digest, chase_observation_at=chase_time, moomoo_observed_at=moomoo_time,
                chase_total_usd=_cash(reported), moomoo_total_usd=_cash(moomoo_total),
                external_assets_usd=_cash(outside), household_total_usd=_cash(household_total),
                core_value_usd=_cash(core), individual_stock_value_usd=_cash(stocks),
                core_minimum_pct=_quantity(core_pct), stock_maximum_pct=_quantity(stock_pct),
                core_gap_usd=_cash(max(Decimal(0), (household_total * core_pct / 100 - core).quantize(CENT, rounding=ROUND_CEILING))),
                stock_headroom_usd=_cash(max(Decimal(0), (household_total * stock_pct / 100 - stocks).quantize(CENT, rounding=ROUND_FLOOR))),
                chase_ledger_matches=same_chase,
                moomoo_provisional=not bool(moomoo["source"].get("broker_account_data_asof"))
                    or bool(moomoo["source"].get("connection_notice")),
                positions=rows)


def planning_context(root: Path, current: datetime):
    """Return only source-verified observations or a scoped unavailable result."""
    path = root / MANIFEST
    try:
        config_path = root / CONFIG
        config = json.loads(config_path.read_bytes()).get("account", {}) if config_path.is_file() else {}
        if config.get("household_planning_effective_from") and current < datetime.fromisoformat(config["household_planning_effective_from"]):
            return None
        if not path.exists():
            if not config.get("household_planning_required"):
                return None
            raise ValueError("household_manifest_missing")
        return _observed(root, current, json.loads(path.read_bytes()))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as exc:
        code = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("household_") else "household_input_unverified"
        return dict(schema_version=SCHEMA, status="unavailable", reason=code)


def summary_card(context, *, status_only=False, allocation=None):
    if not context:
        return None
    if context["status"] == "unavailable":
        lines = ["The combined Chase, Moomoo and outside-assets record needs verification.",
                 "Dependency: " + context["reason"] + "."]
    else:
        def usd(key):
            return f"${Decimal(context[key]):,.2f}"
        lines = [f"Recorded household assets {usd('household_total_usd')}: Chase {usd('chase_total_usd')}, "
                 f"Moomoo {usd('moomoo_total_usd')} and outside assets {usd('external_assets_usd')}.",
                 f"Chase observed {context['chase_observation_at']}. Moomoo displayed {context['moomoo_observed_at']}."
                 + (" Moomoo's account refresh, open orders and buying power are unverified." if context['moomoo_provisional'] else ""),
                 f"Combined SPY and QQQM {usd('core_value_usd')}; gap to the {context['core_minimum_pct']}% minimum {usd('core_gap_usd')}. "
                 f"Individual stocks {usd('individual_stock_value_usd')}.",
                 "Outside assets count once toward planning. Any manual order requires available funds or shares in its named account."]
        if not status_only:
            if allocation and allocation["status"] == "marked":
                lines.append(f"Allocation sizing at the {allocation['market_session']} regular close: "
                             f"${Decimal(str(allocation['planning_total_usd'])):,.2f} combined. "
                             f"Index core ${Decimal(str(allocation['core_before_usd'])):,.2f}; "
                             f"individual stock exposure ${Decimal(str(allocation['stocks_before_usd'])):,.2f}. "
                             "Only Chase cash funds Chase drafts.")
            elif allocation:
                lines.append("Combined allocation sizing is unavailable: " + allocation["reason"] + ".")
            holdings = [f"{r['ticker']} {r['chase_shares']} Chase / {r['moomoo_shares']} Moomoo"
                        for r in context["positions"] if Decimal(r["moomoo_shares"]) > 0]
            if holdings:
                lines.append("Cross-account share inventory: " + ", ".join(holdings) + ".")
        if not context["chase_ledger_matches"]:
            lines.append("The Chase observation and production ledger differ. Refresh the household evidence before sizing.")
    if status_only:
        lines.append("Approved shares for this checkpoint: 0. Entry or exit price and time are unavailable.")
    return dict(title="Combined portfolio planning", body="\n".join(lines), sources=[], group="background")


def validate_archive(context, generated_at):
    """Check the archived report's typed evidence without consulting live files."""
    _check(isinstance(context, dict) and context.get("schema_version") == SCHEMA,
           "household_archive_schema_invalid")
    if context.get("status") == "unavailable":
        _check(set(context) == {"schema_version", "status", "reason"} and isinstance(context["reason"], str)
               and re.fullmatch(r"household_[a-z_]{1,70}", context["reason"]), "household_archive_invalid")
        return
    amounts = ("chase_total_usd", "moomoo_total_usd", "external_assets_usd", "household_total_usd",
               "core_value_usd", "individual_stock_value_usd", "core_gap_usd", "stock_headroom_usd")
    required = {"schema_version", "status", "observed_at", "broker_observation_sha256", "chase_observation_at",
                "moomoo_observed_at", "chase_ledger_matches", "moomoo_provisional", "positions",
                "core_minimum_pct", "stock_maximum_pct", *amounts}
    _check(set(context) == required and context["status"] == "observed"
           and re.fullmatch(r"[0-9a-f]{64}", context["broker_observation_sha256"])
           and all(type(context[key]) is bool for key in ("chase_ledger_matches", "moomoo_provisional"))
           and all(isinstance(context[key], str) and re.fullmatch(r"[0-9]+\.[0-9]{2}", context[key]) for key in amounts),
           "household_archive_invalid")
    clock = _clock(context["observed_at"], generated_at)
    for key in ("chase_observation_at", "moomoo_observed_at"):
        _clock(context[key], clock)
    core_pct, stock_pct = (_amount(context[key]) for key in ("core_minimum_pct", "stock_maximum_pct"))
    _check(core_pct <= 100 and stock_pct <= 100, "household_archive_allocation_invalid")
    total = _amount(context["household_total_usd"])
    _check(total > 0 and total == sum(_amount(context[key]) for key in amounts[:3]), "household_archive_total_invalid")
    value = {}
    for row in context["positions"]:
        _check(set(row) == {"ticker", "chase_shares", "moomoo_shares", "observed_value_usd", "moomoo_value_usd"}
               and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,12}", row["ticker"]) and row["ticker"] not in value,
               "household_archive_position_invalid")
        _check(_amount(row["chase_shares"]) + _amount(row["moomoo_shares"]) > 0
               and _amount(row["moomoo_value_usd"]) <= _amount(row["observed_value_usd"]), "household_archive_position_invalid")
        value[row["ticker"]] = _amount(row["observed_value_usd"])
    core = sum(v for ticker, v in value.items() if ticker in CORE)
    stocks = sum(value.values()) - core
    _check(_amount(context["core_value_usd"]) == core and _amount(context["individual_stock_value_usd"]) == stocks
           and _amount(context["core_gap_usd"]) == max(0, (total * core_pct / 100 - core).quantize(CENT, rounding=ROUND_CEILING))
           and _amount(context["stock_headroom_usd"]) == max(0, (total * stock_pct / 100 - stocks).quantize(CENT, rounding=ROUND_FLOOR)),
           "household_archive_allocation_invalid")



def research_context(root, current, household):
    """Return dated research scenarios. Eligibility remains in the capital decision."""
    path = root / RESEARCH_MANIFEST
    if not household or not path.exists():
        return None
    try:
        payload = json.loads(path.read_bytes())
        _check(payload["schema_version"] == "equity_household_research_input_v1", "household_research_schema_invalid")
        _check(household and household["status"] == "observed" and
               payload["broker_observation_sha256"] == household["broker_observation_sha256"],
               "household_research_inventory_changed")
        digest = payload["plan_source_sha256"]
        _check(isinstance(digest, str) and re.fullmatch("[0-9a-f]{64}", digest)
               and payload["plan_source_path"] == str(SOURCE_DIR / (digest + ".md")), "household_research_binding_invalid")
        source = (root / payload["plan_source_path"]).read_bytes()
        _check(sha256(source).hexdigest() == digest, "household_research_source_changed")
        authored = _clock(payload["authored_at"], current)
        _check(authored >= datetime.fromisoformat(household["chase_observation_at"])
               and authored >= datetime.fromisoformat(household["moomoo_observed_at"]), "household_research_inventory_predates_plan")
        holdings = {row["ticker"]: row for row in household["positions"]}
        active = []
        expired_today = []
        seen = set()
        _check(isinstance(payload["calls"], list), "household_research_calls_invalid")
        for row in payload["calls"]:
            _check(set(row) == {"ticker", "broker", "side", "shares", "price_usd", "price_relation",
                               "opens_at", "expires_at", "condition", "next_check"},
                   "household_research_call_invalid")
            ticker, broker, side = row["ticker"], row["broker"], row["side"]
            _check(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,12}", ticker) and broker in {"Chase", "Moomoo"}
                   and (ticker, broker) not in seen, "household_research_call_scope_invalid")
            seen.add((ticker, broker))
            shares, price = _amount(row["shares"]), _amount(row["price_usd"])
            _check(shares > 0 and price > 0 and Decimal(_cash(price)) == price
                   and (side, row["price_relation"]) in {("SELL", "at_or_above"), ("BUY", "at_or_below")},
                   "household_research_price_or_size_invalid")
            if side == "SELL":
                held = holdings.get(ticker, {})
                _check(shares <= _amount(held.get(broker.lower()+"_shares", 0)), "household_research_insufficient_shares")
            start, end = (datetime.fromisoformat(row[k]) for k in ("opens_at", "expires_at"))
            _check(start.tzinfo is not None and end.tzinfo is not None and authored < end and start < end,
                   "household_research_window_invalid")
            _check(all(isinstance(row[key], str) and 0 < len(row[key].strip()) <= 1000
                       and not any(c in row[key] for c in "\r\n") for key in ("condition", "next_check")),
                   "household_research_condition_invalid")
            from investment_plans import regular_close
            start_et = start.astimezone(ZoneInfo("America/New_York"))
            session_close = regular_close(start_et.date().isoformat())
            _check(session_close.replace(hour=9, minute=30) <= start < end <= session_close,
                   "household_research_regular_session_required")
            if current < end:
                active.append(row)
            elif broker == "Chase" and current.astimezone(start_et.tzinfo).date() == start_et.date():
                expired_today.append(ticker)
        return dict(status="research_only" if active else "expired", plan_source_sha256=digest,
                    authored_at=payload["authored_at"], calls=active, expired_chase_tickers=sorted(expired_today))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation) as exc:
        reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("household_") else "household_research_unverified"
        return dict(status="unavailable", reason=reason, calls=[])


def research_cards(decision):
    report = decision.get("household_research")
    if not report:
        return []
    if report["status"] != "research_only":
        reason = ("The review window expired. Re-underwrite any proposed trade using current holdings, prices and company evidence."
                  if report["status"] == "expired" else "Dependency: " + report["reason"] + ".")
        return [dict(title="Household research update", body=reason, group="background", sources=[])]
    household = decision.get("household_planning") or {}
    if not household.get("chase_ledger_matches") or decision.get("account_conflicts"):
        return [dict(title="Household research pending", group="background", sources=[],
                     body="Account or evidence checks require a fresh review. Current household order size is zero.")]
    rows = decision.get("capital_decision", {}).get("decisions", [])
    active_tickers = {r["ticker"] for r in rows if r.get("order_draft")}
    result = []
    for row in report["calls"]:
        if row["ticker"] in active_tickers:
            continue
        start, end = (datetime.fromisoformat(row[k]).astimezone(ZoneInfo("America/New_York"))
                      for k in ("opens_at", "expires_at"))
        condition = "at or below" if row["price_relation"] == "at_or_below" else "at or above"
        blockers = next((r.get("blockers", []) for r in rows if r["ticker"] == row["ticker"]), [])
        blockers = list(dict.fromkeys([*blockers,
            *[key + "_failed" for key in ("market_gate", "evidence_gate", "fundamental_gate")
              if decision.get(key, {}).get("passed") is False],
            *decision.get("capital_decision", {}).get("global_blockers", [])]))
        pending = ", ".join(str(code).replace("_", " ") for code in blockers[:3]) or "a current, approved account-specific order"
        size = _quantity(_amount(row['shares']))
        price = _amount(row['price_usd'])
        result.append(dict(title=f"{row['ticker']} decision to review in {row['broker']}", group="background", sources=[],
                           body=f"Research case: {row['side']} {size} {'share' if size == '1' else 'shares'} {condition} ${price:,.2f} "
                                f"(about ${price * _amount(row['shares']):,.2f}). Approved order size: 0.\n"
                                f"Review window: {start:%Y-%m-%d %H:%M %Z} to {end:%Y-%m-%d %H:%M %Z}.\n"
                                + row["condition"] + "\nPending: " + pending + ".\nNext check: " + row["next_check"]))
    return result


def marked_allocation(scope, market_rows, expected_session, broker_total, broker_core, broker_stocks):
    """Bridge Chase's marked ledger to the same close for Moomoo, exactly once."""
    if scope is None:
        return None
    if scope["status"] != "observed":
        return {"status": "unavailable", "reason": scope.get("reason", "household_input_unverified")}
    if not scope["chase_ledger_matches"]:
        return {"status": "unavailable", "reason": "household_chase_ledger_requires_reconciliation"}
    try:
        rows = {r["ticker"]: r for r in market_rows}
        chase_total, chase_core, chase_stocks = map(_amount, (broker_total, broker_core, broker_stocks))
        _check(chase_total > 0 and chase_total + CENT >= chase_core + chase_stocks, "household_chase_marks_unverified")
        _check(isinstance(expected_session, str) and len(expected_session) == 10, "household_market_session_unverified")
        chase_core_check = chase_stocks_check = Decimal(0)
        moomoo_observed = moomoo_marked = extra_core = Decimal(0)
        external_positions = {}
        for position in scope["positions"]:
            qty = _amount(position["moomoo_shares"])
            chase_qty = _amount(position["chase_shares"])
            ticker = position["ticker"]
            row = rows.get(ticker, {})
            _check(row.get("market_session_date") == expected_session and row.get("data_quality_label") == "ok"
                   and row.get("data_source") and row.get("data_timestamp") and _amount(row.get("last_price", 0)) > 0,
                   ("household_moomoo_close_unverified_" if qty else "household_chase_close_unverified_") + ticker)
            close = _amount(row["last_price"])
            if ticker in CORE:
                chase_core_check += chase_qty * close
            else:
                chase_stocks_check += chase_qty * close
            if not qty:
                continue
            value = qty * close
            external_positions[ticker] = value
            moomoo_observed += _amount(position["moomoo_value_usd"])
            moomoo_marked += value
            if ticker in CORE:
                extra_core += value
        _check(abs(chase_core - chase_core_check) <= CENT and abs(chase_stocks - chase_stocks_check) <= CENT,
               "household_chase_allocation_marks_conflict")
        outside = _amount(scope["external_assets_usd"])
        second_account = _amount(scope["moomoo_total_usd"]) - moomoo_observed + moomoo_marked
        total = chase_total + second_account + outside
        _check(total > 0, "household_total_invalid")
        return {"status": "marked", "session": expected_session, "total": total, "core": chase_core + extra_core,
                "stocks": chase_stocks + moomoo_marked - extra_core, "moomoo_positions": external_positions,
                "chase_total": chase_total, "moomoo_total": second_account, "external": outside}
    except (ValueError, InvalidOperation, KeyError, TypeError) as exc:
        reason = str(exc) if str(exc).startswith("household_") else "household_allocation_inputs_unverified"
        return {"status": "unavailable", "reason": reason}


def current_allocation(root, current, summary, market_rows, session):
    return marked_allocation(planning_context(root, current), market_rows, session,
                             summary["account_total_value"], summary["current_core_value"],
                             summary["current_active_stock_value"])


def bounded_elective_terms(report, ticker, side, quantity, price, start, end, current):
    """Narrow elective Chase terms to a still-current, same-ticker household review."""
    if not report:
        return quantity, start, end, None
    if report["status"] == "unavailable":
        raise ValueError(report["reason"])
    if ticker in report.get("expired_chase_tickers", []):
        raise ValueError("household_research_window_expired")
    call = next((c for c in report["calls"] if c["ticker"] == ticker and c["broker"] == "Chase"), None)
    if not call:
        return quantity, start, end, None
    if call["side"].lower() != side:
        raise ValueError("household_research_side_conflict")
    boundary = _amount(call["price_usd"])
    if (side == "buy" and price > boundary) or (side == "sell" and price < boundary):
        raise ValueError("household_research_price_conflict")
    start = max(start, datetime.fromisoformat(call["opens_at"]))
    end = min(end, datetime.fromisoformat(call["expires_at"]))
    if start >= end or current >= end:
        raise ValueError("household_research_window_conflict")
    quantity = min(quantity, int(_amount(call["shares"])))
    if quantity < 1:
        raise ValueError("household_research_whole_share_unavailable")
    return quantity, start, end, call
