"""Read-only, source-bound held-risk observations for separately approved notices.

This module neither grants email permission nor writes a delivery baseline. A
condition is an observed state, not evidence that it just began. Delivery owns
verified prior coverage, recurrence, recipient, calendar and send admission.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

import held_position_risk as held_risk
import market_backup
from account_authority import load_authority
from account_common import validate_account_state
from daily_common import ET, canonical_sha256
from investment_plans import regular_close, stamp
from plan_source_resolutions import read_regular, safe_path

SCHEMA = "equity_risk_review_alert_v1"
HEADLINE = "Held-position risk review — no new order"
CROSSED = "approved_risk_condition_crossed"
UNAVAILABLE = "held_review_or_protection_unavailable"
INTRADAY = "04_research/company_research/intraday_portfolio_risk.local.json"
ACCOUNT = "05_risk_and_positions/current_account_state.local.json"
PLAN = "05_risk_and_positions/investment_plans.local.json"
RESOLUTIONS = "05_risk_and_positions/plan_source_resolutions.local.json"
KINDS = {"company_invalidation": "at_or_below", "company_reassessment": "at_or_above",
         "recorded_stop_reference": "at_or_below"}
INTRADAY_KINDS = {"reviewed_allocation_invalidation_price": "company_invalidation",
                  "reviewed_allocation_reassessment_price": "company_reassessment",
                  "recorded_stop_review": "recorded_stop_reference"}
ROW_FIELDS = {"ticker", "recorded_shares", "plan_state", "plan_id", "plan_version", "plan_record_hash",
              "quote", "recorded_average_basis", "basis_label", "basis_price_change_pct", "unrealized_change_usd",
              "dependencies", "broker_protection", "rationale", "next_step", "review_due_by", "conditions", "state"}
CONDITION_FIELDS = {"ticker", "recorded_shares", "plan_id", "plan_version", "plan_record_hash", "trigger", "kind",
                    "reference", "direction", "reference_shares", "episode_key", "active", "observed_price", "observation_basis",
                    "observation_at", "observation_session", "expires_at", "plan_state", "summary"}
FIELDS = {"schema_version", "generated_at", "cycle_date", "headline", "source_bindings", "inventory_available",
          "risk_rows", "conditions", "active_episode_keys", "recovered_episode_keys", "automatic_action_allowed",
          "trading_eligibility_granted", "email_authorized", "limitations", "content_sha256"}


def _risk_dependencies(row):
    # This standing manual execution check applies to every protective draft.
    # It cannot suppress a dated risk condition or manufacture a risk outage.
    return [code for code in row.get("dependencies", []) if code != "fresh_quote_and_available_shares_required"]


def _json(root, relative):
    try:
        value = json.loads(read_regular(root, relative))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, UnicodeError, json.JSONDecodeError):
        return {}


def _digest(root, relative):
    path = safe_path(root, relative)
    return hashlib.sha256(read_regular(root, relative)).hexdigest() if path.exists() else None


def _bindings(root):
    """Bind mutable inputs and every retained proof read by the narrow validators."""
    from account_access import ACCOUNT_INPUTS
    from intraday_prices import CURRENT as price_pointer
    paths = set(held_risk.INPUTS) | set(ACCOUNT_INPUTS) | {INTRADAY, price_pointer, market_backup.CURRENT}
    plan = _json(root, PLAN)
    for record in plan.get("records", []) if isinstance(plan.get("records"), list) else []:
        for source in record.get("sources", []) if isinstance(record, dict) else []:
            if isinstance(source, dict) and isinstance(source.get("path"), str):
                paths.add(source["path"])
    registry = _json(root, RESOLUTIONS)
    # The registry uses receipts; tolerate an invalid shape only as unavailable
    # plan evidence, never as permission to use its conditions.
    for value in registry.values():
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict) and isinstance(row.get("retained_path"), str):
                    paths.add(row["retained_path"])
    pointer = _json(root, market_backup.CURRENT)
    relative = market_backup.REL + "/" + pointer["history_path"] if isinstance(pointer.get("history_path"), str) else None
    seen = set()
    while relative and relative not in seen and len(seen) < 513:
        seen.add(relative); paths.add(relative)
        bundle = _json(root, relative)
        for source in bundle.get("observations", []) if isinstance(bundle.get("observations"), list) else []:
            if isinstance(source, dict) and isinstance(source.get("path"), str):
                paths.add(source["path"])
        parent = bundle.get("parent_history_sha256")
        relative = market_backup.REL + "/history/" + parent + ".json" if isinstance(parent, str) else None
    # Optional observations do not cause missing-risk events. Their exact bytes
    # and underlying inputs still fence a current crossing and concurrent writes.
    receipt = _json(root, INTRADAY)
    assessment = receipt.get("assessment", {})
    sources = assessment.get("source_bindings", []) if isinstance(assessment, dict) else []
    sources = sources if isinstance(sources, list) else []
    for source in [receipt.get("source", {}), *sources,
                   assessment.get("price_snapshot_binding", {})] if isinstance(assessment, dict) else []:
        if isinstance(source, dict) and isinstance(source.get("path"), str):
            paths.add(source["path"])
    return {path: _digest(root, path) for path in sorted(paths)}


def _inventory(root, current):
    account = validate_account_state(_json(root, ACCOUNT))
    if stamp(account["last_updated"]) > current:
        raise ValueError("risk_alert_account_observation_future")
    # This service uses the explicit owner-approved local record authority. A
    # different account contract requires its existing verified-snapshot path,
    # not implicit promotion of a CSV to brokerage truth.
    if load_authority(root, current).get("local_planning_enabled") is not True:
        raise ValueError("risk_alert_local_account_authority_unavailable")
    rows, available = held_risk._inventory(root)
    if not available:
        raise ValueError("risk_alert_inventory_unavailable")
    seen = set()
    for row in rows:
        ticker = row.get("ticker", "")
        try:
            quantity = Decimal(row.get("shares_optional", ""))
        except (InvalidOperation, TypeError):
            raise ValueError("risk_alert_inventory_invalid") from None
        if (re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) is None or ticker in seen
                or not quantity.is_finite() or quantity < 0 or quantity != quantity.to_integral_value()):
            raise ValueError("risk_alert_inventory_invalid")
        seen.add(ticker)
    return rows


def _market_gate(root, current):
    rows = held_risk._csv(root, held_risk.MARKET)
    failures = []
    try:
        # Verify the exact present snapshot scope, not the full research universe
        # or new missing holding. Per-ticker quote checks remain in held_risk.
        tickers = [row["ticker"] for row in rows]
        if (not rows or any(row.get("data_source") not in {market_backup.PRIMARY, market_backup.SOURCE} for row in rows)
                or not market_backup.verify_binding(root, tickers, rows, _digest(root, held_risk.MARKET))):
            raise ValueError("risk_alert_market_provenance_unavailable")
        bundle = market_backup.load_baseline(root, tickers)
        if stamp(bundle["generated_at"]) > current:
            raise ValueError("risk_alert_market_observation_future")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        failures.append(str(exc))
    return {"passed": not failures, "failures": failures}


def _intraday(root, current):
    from intraday_assessment import publication_context
    from intraday_portfolio_risk import projection
    try:
        original = publication_context(root, current)
        if not original or original.get("status") != "current":
            return {}
        value = projection(root, original, current)
        value["prior_verified_price_times"] = {row["ticker"]: row["price_as_of"] for row in original.get("positions", [])}
        return value
    except (KeyError, TypeError, ValueError, OSError):
        return {}


def _identity(row, trigger, kind, reference=None, direction=None, reference_shares=None):
    return {"ticker": row["ticker"], "recorded_shares": row["recorded_shares"],
            "plan_id": row.get("plan_id"), "plan_version": row.get("plan_version"),
            "plan_record_hash": row.get("plan_record_hash"), "trigger": trigger,
            "kind": kind, "reference": reference, "direction": direction, "reference_shares": reference_shares}


def _condition(row, trigger, kind, active, *, reference=None, direction=None,
               reference_shares=None, observed_price=None, observation_basis=None,
               observation_at=None, observation_session=None, expires_at=None):
    identity = _identity(row, trigger, kind, reference, direction, reference_shares)
    return {**identity, "episode_key": "risk-review:" + canonical_sha256(identity),
            "active": active, "observed_price": observed_price,
            "observation_basis": observation_basis, "observation_at": observation_at,
            "observation_session": observation_session, "expires_at": expires_at,
            "plan_state": row.get("plan_state"),
            "summary": ((f"An existing approved stop reference for {reference_shares:g} of {row['recorded_shares']:g} recorded shares is observed; review is required. No new order is authorized."
                         if kind == "recorded_stop_reference" else
                         "An existing approved condition is observed; review is required. No new order is authorized.")
                        if trigger == CROSSED else
                        "The recorded positive holding lacks a current verified risk review or usable risk evidence. No replacement instruction is authorized.")}


def _projection(report, intraday=None, plans=()):
    """Shared semantic extraction; callers must validate the originating artifact."""
    rows, conditions = [], []
    intraday = intraday or {}
    current = stamp(report["generated_at"]).astimezone(ET)
    for raw in report.get("holdings", []):
        row = deepcopy(raw)
        if held_risk.number(row.get("recorded_shares")) is None:
            continue
        current_plan = (row.get("plan_state") == "maintained" and row.get("plan_id")
                        and type(row.get("plan_version")) is int and row.get("plan_record_hash"))
        risk_dependencies = _risk_dependencies(row)
        healthy = bool(current_plan and row.get("quote") and not risk_dependencies)
        conditions.append(_condition(row, UNAVAILABLE, "held_risk_evidence", not healthy, observation_at=current.isoformat()))
        observed_conditions = []
        if current_plan and not risk_dependencies:
            for ref in row.get("conditions", []):
                kind = ref.get("kind")
                if (kind not in KINDS or ref.get("direction") != KINDS[kind]
                        or ref.get("reference_expired") is not False
                        or ref.get("reference_requires_revalidation") is not False
                        or ref.get("plan_id") != row["plan_id"] or ref.get("plan_version") != row["plan_version"]
                        or held_risk.number(ref.get("reference")) is None):
                    continue
                reference_shares = None
                if kind == "recorded_stop_reference":
                    matching = [p for p in plans if p.get("plan_id") == row["plan_id"]
                                and p.get("version") == row["plan_version"] and p.get("record_hash") == row["plan_record_hash"]]
                    draft = (matching[0].get("historical_order_draft", matching[0].get("order_draft")) or {}) if len(matching) == 1 else {}
                    starts = stamp(draft["starts_at"]) if draft.get("starts_at") else current.replace(hour=9, minute=30, second=0, microsecond=0)
                    reference_shares = draft.get("quantity")
                    scope = held_risk.number(reference_shares)
                    if (draft.get("session_date") != current.date().isoformat() or draft.get("side") != "sell"
                            or draft.get("type") != "STOP" or scope is None or scope > Decimal(str(row["recorded_shares"]))
                            or draft.get("stop_price") != ref["reference"] or current < starts):
                        continue
                active = ref.get("crossed_at_observation") if row.get("quote") else None
                price = (row.get("quote") or {}).get("price")
                basis = "canonical completed close; not live"
                session = (row.get("quote") or {}).get("session")
                # The market observation happened at that session's close;
                # recollecting the same bar does not create a newer recovery.
                observed_at = regular_close(session).isoformat() if session else None
                expires_at = None
                prior_live = intraday.get("prior_verified_price_times", {}).get(row["ticker"])
                if prior_live and observed_at and stamp(prior_live) > stamp(observed_at):
                    # An older close cannot rearm a later live episode or report
                    # a stale crossing after its newer healthy mark expires.
                    active = None; price = None
                # A fully validated current last-sale observation supersedes
                # the same condition's older close, including explicit recovery.
                if intraday.get("status") == "current":
                    matches = [x for x in intraday.get("plan_conditions", []) if
                        x.get("ticker") == row["ticker"] and INTRADAY_KINDS.get(x.get("kind")) == kind
                        and x.get("plan_id") == row["plan_id"] and x.get("plan_version") == row["plan_version"]
                        and x.get("plan_record_hash") == row["plan_record_hash"]
                        and x.get("reference_price") == ref["reference"]]
                    if len(matches) == 1 and held_risk.number(matches[0].get("observed_price")) is not None:
                        item = matches[0]
                        if item.get("status") in {"price_condition_met_reassessment_required", "price_condition_not_met"}:
                            active = item["status"] == "price_condition_met_reassessment_required"
                            price = item["observed_price"]; basis = "validated current intraday last sale; not an executable quote"
                            position = next((x for x in intraday.get("positions", []) if x.get("ticker") == row["ticker"]), {})
                            observed_at = position.get("price_as_of")
                            session = intraday.get("session_date"); expires_at = intraday.get("expires_at")
                if type(active) is not bool:
                    active = None
                condition = _condition(row, CROSSED, kind, active, reference=ref["reference"],
                    direction=ref["direction"], reference_shares=reference_shares, observed_price=price, observation_basis=basis,
                    observation_at=observed_at, observation_session=session, expires_at=expires_at)
                conditions.append(condition); observed_conditions.append(condition)
        # Standalone text may show dated basis loss, but never an expired stop or
        # an unrelated capital/order draft. These are the complete display facts.
        keep = ("ticker", "recorded_shares", "plan_state", "plan_id", "plan_version", "plan_record_hash",
                "quote", "recorded_average_basis", "basis_label", "basis_price_change_pct", "unrealized_change_usd",
                "dependencies", "broker_protection", "rationale", "next_step", "review_due_by")
        visible = {key: row.get(key) for key in keep}
        visible.update(conditions=observed_conditions, state="RISK_ALERT" if any(x["active"] is True for x in observed_conditions)
                       else "REVIEW_REQUIRED" if not healthy else "REVIEWED_HOLD")
        rows.append(visible)
    return sorted(rows, key=lambda r: r["ticker"]), sorted(conditions, key=lambda c: c["episode_key"])


def build(root: Path, current: datetime) -> dict:
    """Fresh offline projection; never depends on a published full decision."""
    root = root.resolve(); current = stamp(current.isoformat()).astimezone(ET)
    before = _bindings(root)
    _inventory(root, current)
    intraday = _intraday(root, current)
    decision = {"market_gate": _market_gate(root, current), "intraday_portfolio_risk": intraday}
    report = held_risk.build(decision, root=root, current=current)
    rows, conditions = _projection(report, intraday, _json(root, PLAN).get("records", []))
    if before != _bindings(root):
        raise ValueError("risk_alert_inputs_changed_during_build")
    value = {"schema_version": SCHEMA, "generated_at": current.isoformat(), "cycle_date": current.date().isoformat(),
             "headline": HEADLINE, "source_bindings": before, "inventory_available": True,
             "risk_rows": rows, "conditions": conditions,
             "active_episode_keys": sorted(c["episode_key"] for c in conditions if c["active"] is True),
             "recovered_episode_keys": sorted(c["episode_key"] for c in conditions if c["active"] is False),
             "automatic_action_allowed": False, "trading_eligibility_granted": False, "email_authorized": False,
             "limitations": ["Existing observed conditions; this check does not establish when an episode began.",
                 "Recorded basis changes are not acquisition fills, realized returns or peak drawdowns.",
                 "No new risk limits, renewed plans, replacement orders or execution authority are created."]}
    value["content_sha256"] = canonical_sha256(value)
    return value


def validate_archive(artifact: dict) -> dict:
    """Check retained content, not mutable current sources or delivery authenticity.

    The delivery layer must independently verify its immutable archive/receipt
    binding before using this result as evidence of prior recipient coverage.
    """
    try:
        if (not isinstance(artifact, dict) or set(artifact) != FIELDS or artifact.get("schema_version") != SCHEMA
                or artifact.get("headline") != HEADLINE or artifact.get("inventory_available") is not True
                or any(artifact.get(k) is not False for k in ("automatic_action_allowed", "trading_eligibility_granted", "email_authorized"))
                or artifact.get("content_sha256") != canonical_sha256({k: v for k, v in artifact.items() if k != "content_sha256"})
                or stamp(artifact["generated_at"]).astimezone(ET).date().isoformat() != artifact["cycle_date"]):
            raise ValueError()
        bindings = artifact["source_bindings"]
        if (not isinstance(bindings, dict) or not set(held_risk.INPUTS) <= set(bindings)
                or any(v is not None and re.fullmatch(r"[a-f0-9]{64}", str(v)) is None for v in bindings.values())):
            raise ValueError()
        for path in bindings:
            if (not isinstance(path, str) or not path or Path(path).is_absolute() or ".." in Path(path).parts
                    or "\\" in path or Path(path).as_posix() != path):
                raise ValueError()
        identities = set()
        rows = {row["ticker"]: row for row in artifact["risk_rows"]}
        if len(rows) != len(artifact["risk_rows"]):
            raise ValueError()
        for row in rows.values():
            quantity = held_risk.number(row["recorded_shares"])
            if (set(row) != ROW_FIELDS or quantity is None or quantity != quantity.to_integral_value()
                    or re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", row["ticker"]) is None
                    or not isinstance(row["dependencies"], list) or any(not isinstance(x, str) for x in row["dependencies"])):
                raise ValueError()
            quote = row["quote"]
            if quote is not None:
                if (not isinstance(quote, dict) or set(quote) != {"price", "session", "collected_at", "source", "basis"}
                        or held_risk.number(quote["price"]) is None or stamp(quote["collected_at"]) > stamp(artifact["generated_at"])):
                    raise ValueError()
        for c in artifact["conditions"]:
            row = rows[c["ticker"]]
            if (set(c) != CONDITION_FIELDS or type(c["active"]) is not bool and c["active"] is not None
                    or c["trigger"] not in {CROSSED, UNAVAILABLE}
                    or c["episode_key"] in identities
                    or held_risk.number(row["recorded_shares"]) is None
                    or c["episode_key"] != "risk-review:" + canonical_sha256(_identity(row, c["trigger"], c["kind"], c["reference"], c["direction"], c["reference_shares"]))):
                raise ValueError()
            if c != _condition(row, c["trigger"], c["kind"], c["active"], reference=c["reference"], direction=c["direction"],
                    reference_shares=c["reference_shares"], observed_price=c["observed_price"], observation_basis=c["observation_basis"], observation_at=c["observation_at"],
                    observation_session=c["observation_session"], expires_at=c["expires_at"]):
                raise ValueError()
            if c["kind"] == "recorded_stop_reference":
                scope = held_risk.number(c["reference_shares"])
                if scope is None or scope != scope.to_integral_value() or scope > Decimal(str(row["recorded_shares"])):
                    raise ValueError()
            elif c["reference_shares"] is not None:
                raise ValueError()
            if c["observation_at"] is not None and stamp(c["observation_at"]) > stamp(artifact["generated_at"]):
                raise ValueError()
            if c["trigger"] == CROSSED and (row["plan_state"] != "maintained" or c["kind"] not in KINDS
                    or c["direction"] != KINDS[c["kind"]] or held_risk.number(c["reference"]) is None):
                raise ValueError()
            if c["trigger"] == CROSSED and c["active"] is not None:
                price = held_risk.number(c["observed_price"])
                if (price is None or c["active"] != (price <= Decimal(str(c["reference"])) if c["direction"] == "at_or_below" else price >= Decimal(str(c["reference"])))
                        or stamp(c["observation_at"]) > stamp(artifact["generated_at"])):
                    raise ValueError()
                if c["expires_at"] is not None and not stamp(artifact["generated_at"]) < stamp(c["expires_at"]):
                    raise ValueError()
            if c["trigger"] == UNAVAILABLE and (c["kind"] != "held_risk_evidence" or c["reference"] is not None or c["direction"] is not None):
                raise ValueError()
            identities.add(c["episode_key"])
        for row in rows.values():
            own = [c for c in artifact["conditions"] if c["ticker"] == row["ticker"]]
            cross = [c for c in own if c["trigger"] == CROSSED]
            unavailable = [c for c in own if c["trigger"] == UNAVAILABLE]
            healthy = bool(row["plan_state"] == "maintained" and row["plan_id"] and type(row["plan_version"]) is int
                           and row["plan_record_hash"] and row["quote"] and not _risk_dependencies(row))
            if (len(unavailable) != 1 or unavailable[0]["active"] != (not healthy)
                    or sorted(row["conditions"], key=lambda c: c["episode_key"]) != cross
                    or row["state"] != ("RISK_ALERT" if any(c["active"] is True for c in cross) else "REVIEW_REQUIRED" if not healthy else "REVIEWED_HOLD")):
                raise ValueError()
        if (artifact["active_episode_keys"] != sorted(c["episode_key"] for c in artifact["conditions"] if c["active"] is True)
                or artifact["recovered_episode_keys"] != sorted(c["episode_key"] for c in artifact["conditions"] if c["active"] is False)):
            raise ValueError()
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("risk_alert_archive_invalid") from None
    return artifact


def validate_current(artifact: dict, root: Path, current: datetime) -> dict:
    validate_archive(artifact)
    recorded = stamp(artifact["generated_at"])
    current = stamp(current.isoformat()).astimezone(ET)
    if recorded > current:
        raise ValueError("risk_alert_observation_future")
    if build(root, recorded) != artifact:
        raise ValueError("risk_alert_recomposition_mismatch")
    fresh = build(root, current)
    # A changed date alone is a delivery-window concern. Changed plan deadlines,
    # market-session admissibility or optional live marks require a fresh build.
    # Unavailable-state observation_at is the time of this verified check, not
    # a new price observation. Ignore only that clock noise after the original
    # bytes have already passed exact recorded-time recomposition above.
    def current_conditions(value):
        return [{k: v for k, v in condition.items() if not (condition["trigger"] == UNAVAILABLE and k == "observation_at")}
                for condition in value["conditions"]]
    if (fresh["source_bindings"] != artifact["source_bindings"] or fresh["risk_rows"] != artifact["risk_rows"]
            or current_conditions(fresh) != current_conditions(artifact)):
        raise ValueError("risk_alert_current_projection_changed")
    return artifact


def episode_keys(artifact: dict) -> list[str]:
    return list(validate_archive(artifact)["active_episode_keys"])


def recovered_episode_keys(artifact: dict) -> list[str]:
    return list(validate_archive(artifact)["recovered_episode_keys"])


def coverage_conditions_from_decision(decision: dict) -> list[dict]:
    """Semantic conditions with actual observation clocks, after archive admission."""
    report = decision.get("held_position_risk")
    if not isinstance(report, dict) or report.get("schema_version") != held_risk.SCHEMA or report.get("inventory_available") is not True:
        return []
    _, conditions = _projection(report, decision.get("intraday_portfolio_risk"), decision.get("plan_continuity", {}).get("plans", []))
    return conditions


def coverage_state_from_decision(decision: dict) -> dict:
    conditions = coverage_conditions_from_decision(decision)
    return {"active": sorted(c["episode_key"] for c in conditions if c["active"] is True),
            "recovered": sorted(c["episode_key"] for c in conditions if c["active"] is False)}


def coverage_from_decision(decision: dict) -> list[str]:
    """Only after delivery independently verifies actual displayed risk cards."""
    return coverage_state_from_decision(decision)["active"]
