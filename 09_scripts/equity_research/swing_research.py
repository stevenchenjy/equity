"""Bounded, offline daily swing research; no canonical capital or execution authority.

The current projection uses independently admitted full OHLCV history. A separate
append-only namespace freezes actual first captures and evaluates future paths.
An observation, modeled path, software pass or review threshold is never a trade.
"""
from __future__ import annotations

import ast
import copy
import csv
from datetime import date, datetime, time, timedelta
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
from statistics import mean

from daily_common import ET, ExclusiveFileLock, is_us_market_session_date, latest_published_market_session
from investment_plans import regular_close
import market_backup

POLICY = Path("01_policies/swing_research.json")
SNAPSHOT = Path("03_source_data/equity_research/market_data_snapshot.csv")
UNIVERSE = Path("03_source_data/equity_research/universe_seed.csv")
HOLDINGS = Path("05_risk_and_positions/current_positions.local.csv")
OUTPUT = Path("08_reviews/swing_research.local")
SCHEMA = "equity_swing_research_v1"
STRATEGIES = ("breakout", "pullback_reclaim", "trend_continuation")
VERSION = "daily-swing-forward-v1-20261027"
AUTHORITY = {"research_only": True, "capital_authority": False,
             "actionable_quantity": 0, "automatic_action_allowed": False}


class SwingResearchError(ValueError):
    pass


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_bytes(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _hash(value) -> str:
    return _digest(_json_bytes(value))


def _aware(value) -> datetime:
    current = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise SwingResearchError("swing_clock_unverified")
    return current.astimezone(ET)


def _number(value) -> float:
    if type(value) not in (int, float) or not math.isfinite(value):
        raise SwingResearchError("swing_numeric_unverified")
    return float(value)


def _file(root: Path, relative: Path | str) -> bytes:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise SwingResearchError("swing_source_missing_or_linked")
    return path.read_bytes()


def _sessions_after(day: date, count: int) -> list[str]:
    result = []
    while len(result) < count:
        day += timedelta(days=1)
        if is_us_market_session_date(day):
            regular_close(day.isoformat())
            result.append(day.isoformat())
    return result


def _open(session: str) -> datetime:
    day = date.fromisoformat(session)
    if not is_us_market_session_date(day):
        raise SwingResearchError("swing_session_unverified")
    regular_close(session)
    return datetime.combine(day, time(9, 30), tzinfo=ET)


def _next_open(current: datetime) -> str:
    today = current.date().isoformat()
    if is_us_market_session_date(current.date()) and _open(today) > current:
        return today
    return _sessions_after(current.date(), 1)[0]


def _validate_policy(policy: dict) -> None:
    if (policy.get("schema_version") != "equity_swing_research_policy_v1"
            or policy.get("version") != VERSION or policy.get("status") != "experimental"
            or any(policy.get(k) != v for k, v in AUTHORITY.items())
            or policy.get("holding_sessions") != [5, 10, 14]
            or policy.get("one_way_cost_bps") != [10, 25, 50]
            or policy.get("commission_per_share_usd") != 0
            or policy.get("maximum_gap_r") != 0.25
            or policy.get("hypothetical_profit_reference_r") != 2
            or policy.get("stop_lookback_sessions") != 5
            or set(policy.get("strategies", {})) != set(STRATEGIES)
            or policy.get("adoption", {}).get("automatic_promotion") is not False
            or policy.get("adoption", {}).get("owner_adoption_required") is not True
            or policy.get("adoption", {}).get("capital_and_risk_review_required") is not True):
        raise SwingResearchError("swing_policy_unverified")


def _implementation() -> tuple[str, dict[str, bytes]]:
    """Bind the local import closure, not only the mutable entry module."""
    directory = Path(__file__).resolve().parent
    pending, files = [Path(__file__).name], {}
    while pending:
        name = pending.pop()
        if name in files:
            continue
        path = directory / name
        raw = path.read_bytes()
        files[name] = raw
        for node in ast.walk(ast.parse(raw)):
            names = ([alias.name.split(".")[0] for alias in node.names]
                     if isinstance(node, ast.Import) else
                     [node.module.split(".")[0]] if isinstance(node, ast.ImportFrom) and node.module else [])
            for module in names:
                candidate = module + ".py"
                if (directory / candidate).is_file() and candidate not in files:
                    pending.append(candidate)
    return _hash({name: _digest(raw) for name, raw in sorted(files.items())}), files


def _inputs(root: Path, current: datetime):
    policy_raw = _file(root, POLICY)
    policy = json.loads(policy_raw)
    _validate_policy(policy)
    snapshot_raw = _file(root, SNAPSHOT)
    rows = list(csv.DictReader(io.StringIO(snapshot_raw.decode())))
    tickers = [row.get("ticker") for row in rows]
    if not rows or any(not t for t in tickers) or len(set(tickers)) != len(tickers):
        raise SwingResearchError("swing_snapshot_scope_unverified")
    universe_raw, holdings_raw = _file(root, UNIVERSE), _file(root, HOLDINGS)
    configured = [row.get("ticker", "").upper() for row in csv.DictReader(io.StringIO(universe_raw.decode()))]
    held = [row.get("ticker", "").upper() for row in csv.DictReader(io.StringIO(holdings_raw.decode()))]
    if (not configured or len(set(configured)) != len(configured) or len(set(held)) != len(held)
            or any(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) is None for ticker in [*configured, *held])
            or set(tickers) != set(configured) | set(held)):
        raise SwingResearchError("swing_configured_and_held_scope_incomplete")
    pointer_raw = _file(root, market_backup.CURRENT)
    pointer = json.loads(pointer_raw)
    bundle = market_backup.load_baseline(root, tickers)
    expected = latest_published_market_session(current).isoformat()
    if bundle["market_session"] != expected:
        raise SwingResearchError("swing_latest_completed_close_missing")
    if (_aware(bundle["generated_at"]) > current
            or _aware(bundle["generated_at"]) < regular_close(expected)
            or bundle.get("snapshot_sha256") != _digest(snapshot_raw)):
        raise SwingResearchError("swing_history_snapshot_unbound")
    series = bundle["tickers"]
    for row in rows:
        ticker = row["ticker"]
        try:
            close = float(row["last_price"])
        except (ValueError, TypeError, KeyError):
            raise SwingResearchError("swing_snapshot_price_unverified") from None
        if (row.get("data_quality_label") != "ok" or row.get("market_session_date") != expected
                or not math.isfinite(close) or close <= 0
                or abs(close - series[ticker]["bars"][-1]["close"]) > 0.000051
                or _aware(row["data_timestamp"]) > current):
            raise SwingResearchError("swing_snapshot_row_unverified")
    history_relative = Path(market_backup.REL) / pointer["history_path"]
    history_raw = _file(root, history_relative)
    implementation, implementation_files = _implementation()
    raws = {str(POLICY): policy_raw, str(SNAPSHOT): snapshot_raw, str(UNIVERSE): universe_raw, str(HOLDINGS): holdings_raw,
            market_backup.CURRENT: pointer_raw, str(history_relative): history_raw}
    if any(_file(root, path) != raw for path, raw in raws.items()):
        raise SwingResearchError("swing_inputs_changed_during_read")
    bindings = {"policy_sha256": _digest(policy_raw), "snapshot_sha256": _digest(snapshot_raw),
                "universe_sha256": _digest(universe_raw), "holdings_sha256": _digest(holdings_raw),
                "history_pointer_sha256": _digest(pointer_raw), "history_path": str(history_relative),
                "history_sha256": _digest(history_raw), "implementation_sha256": implementation,
                "market_session": expected, "scope": sorted(tickers), "data_source": bundle["data_source"]}
    return policy, bundle, bindings, raws, implementation_files


def _features(bars: list[dict]) -> dict:
    if len(bars) < 51:
        raise SwingResearchError("swing_51_sessions_required")
    current, prior = bars[-1], bars[-2]
    close, previous = _number(current["close"]), _number(prior["close"])
    sma20 = mean(_number(b["close"]) for b in bars[-20:])
    sma50 = mean(_number(b["close"]) for b in bars[-50:])
    prior20 = mean(_number(b["close"]) for b in bars[-21:-1])
    prior_high = max(_number(b["high"]) for b in bars[-20:-1])
    volume_mean = mean(_number(b["volume"]) for b in bars[-20:-1])
    relative_volume = _number(current["volume"]) / volume_mean if volume_mean > 0 else None
    stop = min(_number(b["low"]) for b in bars[-5:])
    trend = sma20 > sma50 and close > sma20
    reclaim = close > _number(prior["high"])
    selected = {
        "breakout": close > prior_high and close > previous and relative_volume is not None and relative_volume >= 2,
        "pullback_reclaim": trend and previous <= prior20 and reclaim,
        "trend_continuation": trend and previous > prior20 and reclaim and close < prior_high
                              and relative_volume is not None and relative_volume >= 1,
    }
    return {"close": close, "prior_close": previous, "sma20": sma20, "sma50": sma50,
            "prior_sma20": prior20, "prior_19_session_high": prior_high,
            "daily_volume_over_prior_19_mean": relative_volume, "observed_five_session_low": stop,
            "selected": {key: bool(value and close > stop) for key, value in selected.items()}}


def _baseline(root: Path, decision: dict | None, bindings: dict, current: datetime) -> dict:
    """Freeze contemporaneous baseline eligibility, never infer unknown as false."""
    day = current.date().isoformat()
    is_open = bool(is_us_market_session_date(current.date()) and _open(day) <= current < regular_close(day))
    clock = {"recorded_at": current.isoformat(), "regular_session_open": is_open,
             "earliest_modeled_entry_session": _next_open(current)}
    result = {"status": "unverified", "reason": "current_canonical_baseline_not_supplied",
              "comparability": "unverified", "capture_clock": clock,
              "proof": None, "canonical": {}, "existing_tactical": {},
              "observed_canonical": {}, "observed_tactical": {}, "rejection_codes": {}}
    if not isinstance(decision, dict):
        return result
    try:
        from capital_decision import validate
        from daily_common import canonical_sha256
        capital = decision["capital_decision"]
        validate(capital, current=current, root=root)
        if (_aware(capital["generated_at"]) > current
                or _aware(capital["generated_at"]).date() != current.date()
                or capital["market_data_timestamp"] != bindings["market_session"]
                or decision["market_gate"].get("expected_market_session") != bindings["market_session"]):
            raise SwingResearchError("swing_baseline_not_current")
        rows = capital["decisions"]
        if len({row["ticker"] for row in rows}) != len(rows):
            raise SwingResearchError("swing_baseline_duplicate_ticker")
        result = {"status": "verified_current", "reason": None if is_open else "baseline_capture_outside_regular_session",
                  "comparability": "capture_window_matched" if is_open else "unverified_outside_regular_session",
                  "capture_clock": clock,
                  "proof": {"capital_content_sha256": capital["content_sha256"],
                            "capital_source_bindings_sha256": canonical_sha256(capital["source_bindings"]),
                            "generated_at": capital["generated_at"], "market_session": capital["market_data_timestamp"]},
                  "canonical": {}, "existing_tactical": {},
                  "observed_canonical": {row["ticker"]: bool(row["decision"] in {"ACTIONABLE_BUY", "ACTIONABLE_ADD"} and row["shares"] > 0)
                                         for row in rows}, "observed_tactical": {},
                  "rejection_codes": {row["ticker"]: list(row.get("blockers", [])) for row in rows}}
        result["canonical"] = dict(result["observed_canonical"]) if is_open else {}
        tactical = decision.get("tactical_review", {})
        if (tactical.get("market_session") == bindings["market_session"]
                and _aware(tactical["as_of"]) <= current and _aware(tactical["as_of"]).date() == current.date()):
            for row in tactical.get("drafts", []):
                evidence = row.get("price_evidence", {})
                if (evidence.get("validated") is True
                        and evidence.get("snapshot_sha256") == bindings["snapshot_sha256"]
                        and evidence.get("history_session") == bindings["market_session"]):
                    result["observed_tactical"][row["ticker"]] = bool(row.get("eligible") is True and row.get("quantity", 0) > 0)
                    if is_open:
                        result["existing_tactical"][row["ticker"]] = result["observed_tactical"][row["ticker"]]
        return result
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return {**result, "status": "unverified", "reason": "current_canonical_baseline_unverified",
                "comparability": "unverified", "proof": None, "canonical": {}, "existing_tactical": {},
                "observed_canonical": {}, "observed_tactical": {}, "rejection_codes": {}}


def _read_ledger(path: Path, current: datetime) -> list[dict]:
    if not path.exists():
        return []
    if path.is_symlink():
        raise SwingResearchError("swing_ledger_linked")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line]
    previous, identities, observations, signature = "", set(), {}, None
    last_clock = None
    for row in rows:
        body = {key: value for key, value in row.items() if key != "record_hash"}
        identity = (row.get("kind"), row.get("observation_id"), row.get("horizon_sessions"))
        clock = _aware(row["recorded_at"])
        if (row.get("previous_hash") != previous or row.get("record_hash") != _hash(body)
                or identity in identities or clock > current or last_clock and clock < last_clock
                or any(row.get(k) != v for k, v in AUTHORITY.items())):
            raise SwingResearchError("swing_ledger_integrity_failure")
        if row.get("kind") == "observation":
            sig = (row.get("version"), row.get("policy_sha256"), row.get("implementation_sha256"))
            if signature is not None and signature != sig:
                raise SwingResearchError("swing_version_identity_changed")
            signature = sig
            expected_id = _hash({"version": row["version"], "ticker": row["ticker"], "session": row["source_session"]})
            if (row["observation_id"] != expected_id or regular_close(row["source_session"]) > clock
                    or _open(row["entry_session"]) <= clock):
                raise SwingResearchError("swing_observation_chronology_failure")
            observations[row["observation_id"]] = row
        elif row.get("kind") == "outcome":
            observation = observations.get(row.get("observation_id"))
            horizon = row.get("horizon_sessions")
            if observation is None or horizon not in (5, 10, 14):
                raise SwingResearchError("swing_outcome_unbound")
            expected = [observation["entry_session"], *_sessions_after(date.fromisoformat(observation["entry_session"]), horizon - 1)]
            if ([bar.get("session_date") for bar in row.get("forward_bars", [])] != expected
                    or regular_close(expected[-1]) > clock):
                raise SwingResearchError("swing_outcome_chronology_failure")
        else:
            raise SwingResearchError("swing_ledger_record_unknown")
        previous, last_clock = row["record_hash"], clock
        identities.add(identity)
    return rows


def _chain(rows: list[dict], row: dict) -> dict:
    record = copy.deepcopy(row)
    record["previous_hash"] = rows[-1]["record_hash"] if rows else ""
    record["record_hash"] = _hash(record)
    rows.append(record)
    return record


def _verify_retained_inputs(output: Path, rows: list[dict]) -> None:
    checked, histories, policies, observations = set(), {}, {}, {}
    for row in rows:
        inputs = row["inputs"]
        for key in ("policy_sha256", "snapshot_sha256", "history_pointer_sha256", "history_sha256", "universe_sha256", "holdings_sha256"):
            digest = inputs[key]
            if not isinstance(digest, str) or re.fullmatch(r"[a-f0-9]{64}", digest) is None:
                raise SwingResearchError("swing_retained_input_locator_unverified")
            if digest not in checked:
                if _digest(_file(output, Path("input_history") / digest)) != digest:
                    raise SwingResearchError("swing_retained_input_changed")
                checked.add(digest)
        implementation = inputs["implementation_sha256"]
        if not isinstance(implementation, str) or re.fullmatch(r"[a-f0-9]{64}", implementation) is None:
            raise SwingResearchError("swing_retained_input_locator_unverified")
        if implementation not in checked:
            directory = output / "implementations" / implementation
            if directory.is_symlink() or not directory.is_dir():
                raise SwingResearchError("swing_retained_implementation_missing")
            files = {path.name: _digest(_file(directory, path.name)) for path in directory.glob("*.py")}
            if _hash(files) != implementation:
                raise SwingResearchError("swing_retained_implementation_changed")
            checked.add(implementation)
        if inputs["history_sha256"] not in histories:
            histories[inputs["history_sha256"]] = json.loads(_file(output, Path("input_history") / inputs["history_sha256"]))
        history = histories[inputs["history_sha256"]]
        if history.get("snapshot_sha256") != inputs["snapshot_sha256"] or history.get("market_session") != inputs["market_session"]:
            raise SwingResearchError("swing_retained_history_unbound")
        bars = history.get("tickers", {}).get(row["ticker"], {}).get("bars", [])
        if row["kind"] == "observation":
            if row.get("bars_at_observation") != bars[-51:] or row.get("features") != _features(bars):
                raise SwingResearchError("swing_retained_observation_unbound")
            observations[row["observation_id"]] = row
        else:
            lookup = {bar["session_date"]: bar for bar in bars}
            if any(lookup.get(bar["session_date"]) != bar for bar in row.get("forward_bars", [])):
                raise SwingResearchError("swing_retained_outcome_unbound")
            if inputs["policy_sha256"] not in policies:
                policies[inputs["policy_sha256"]] = json.loads(_file(output, Path("input_history") / inputs["policy_sha256"]))
            expected = _outcome(observations[row["observation_id"]], bars, row["horizon_sessions"],
                                policies[inputs["policy_sha256"]], _aware(row["recorded_at"]), inputs=inputs)
            if expected != {key: value for key, value in row.items() if key not in {"previous_hash", "record_hash"}}:
                raise SwingResearchError("swing_retained_outcome_calculation_unverified")


def _retain(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise SwingResearchError("swing_retained_input_linked")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise SwingResearchError("swing_retained_input_conflict") from None
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _append(path: Path, before: bytes, rows: list[dict]) -> None:
    if path.exists() and path.read_bytes() != before:
        raise SwingResearchError("swing_ledger_changed_during_read")
    if path.is_symlink():
        raise SwingResearchError("swing_ledger_linked")
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "ab") as handle:
        handle.write(b"".join(_json_bytes(row) for row in rows))
        handle.flush()
        os.fsync(handle.fileno())


def _net(entry: float, exit_price: float, policy: dict) -> dict:
    commission = policy["commission_per_share_usd"]
    return {str(bps): round(100 * ((exit_price * (1 - bps / 10000) - commission)
                                  / (entry * (1 + bps / 10000) + commission) - 1), 6)
            for bps in policy["one_way_cost_bps"]}


def _model(window: list[dict], features: dict, policy: dict) -> dict:
    entry = _number(window[0]["open"])
    reference, stop = features["close"], features["observed_five_session_low"]
    maximum = reference + policy["maximum_gap_r"] * (reference - stop)
    if not stop < entry or not reference <= entry <= maximum:
        return {"status": "skipped_unfilled_or_gap", "actual_fill": False}
    target = entry + policy["hypothetical_profit_reference_r"] * (entry - stop)
    exit_price, reason, session, ambiguous = window[-1]["close"], "time_exit", window[-1]["session_date"], False
    for bar in window:
        op, low, high = (_number(bar[key]) for key in ("open", "low", "high"))
        if low <= stop:
            exit_price, reason, session = min(op, stop), "stop_or_gap_loss", bar["session_date"]
            ambiguous = high >= target
            break
        if high >= target:
            exit_price, reason, session = target, "hypothetical_2R_profit", bar["session_date"]
            break
    return {"status": "modeled", "actual_fill": False, "entry": entry, "exit": exit_price,
            "exit_session": session, "reason": reason, "same_bar_sequence_ambiguous": ambiguous,
            "stop": stop, "profit_reference": target,
            "profit_reference_kind": "hypothetical_2R_not_observed_resistance",
            "raw_price_cost_sensitivity_pct_by_one_way_bps": _net(entry, exit_price, policy)}


def _outcome(observation: dict, bars: list[dict], horizon: int, policy: dict, current: datetime, *, inputs: dict | None = None):
    start = observation["entry_session"]
    expected = [start, *_sessions_after(date.fromisoformat(start), horizon - 1)]
    lookup = {bar["session_date"]: bar for bar in bars}
    if regular_close(expected[-1]) > current or any(day not in lookup for day in expected):
        return None
    window = [lookup[day] for day in expected]
    original = {bar["session_date"]: bar for bar in observation["bars_at_observation"]}
    corrected = any(day in lookup and lookup[day] != bar for day, bar in original.items())
    result = {"kind": "outcome", "version": VERSION, "observation_id": observation["observation_id"],
              "ticker": observation["ticker"], "recorded_at": current.isoformat(),
              "horizon_sessions": horizon, "forward_bars": window,
              "inputs": copy.deepcopy(inputs),
              "status": "correction_review_required" if corrected else "unadjusted_price_paths_pending_corporate_action_review",
              "corporate_action_review_required": True, "corporate_action_review_status": "unreviewed",
              "performance_eligible": False,
              "interpretation": "Raw unadjusted price path and hypothetical costs only. Splits, dividends, distributions and other corporate actions require independent source-bound review before economic-performance interpretation.", **AUTHORITY}
    if not corrected:
        result["raw_common_price_cost_sensitivity_pct_by_one_way_bps"] = _net(window[0]["open"], window[-1]["close"], policy)
        result["models"] = {strategy: _model(window, observation["features"], policy)
                            if selected else {"status": "not_selected", "actual_fill": False}
                            for strategy, selected in observation["features"]["selected"].items()}
    return result


def _performance(rows: list[dict]) -> dict:
    observations = [row for row in rows if row["kind"] == "observation"]
    outcomes = [row for row in rows if row["kind"] == "outcome"]
    groups = []
    for strategy in STRATEGIES:
        for horizon in (5, 10, 14):
            selected = {row["observation_id"] for row in observations if row["features"]["selected"][strategy]}
            eligible = [row for row in outcomes if row["horizon_sessions"] == horizon and row["observation_id"] in selected]
            modeled = [row["models"][strategy] for row in eligible
                       if row["status"] == "unadjusted_price_paths_pending_corporate_action_review" and row["models"][strategy]["status"] == "modeled"]
            groups.append({"setup": strategy, "horizon_sessions": horizon, "selected_observations": len(selected),
                           "matured_observations": len(eligible), "modeled_entries": len(modeled),
                           "skipped_entries": sum(row.get("models", {}).get(strategy, {}).get("status") == "skipped_unfilled_or_gap" for row in eligible),
                           "correction_required": sum(row["status"] == "correction_review_required" for row in eligible),
                           "corporate_action_review_required": len(eligible), "performance_eligible_entries": 0,
                           "mean_modeled_net_pct_by_one_way_bps": {str(bps): None for bps in (10, 25, 50)},
                           "raw_unadjusted_price_cost_sensitivity_mean_pct_by_one_way_bps": {
                               str(bps): round(mean(model["raw_price_cost_sensitivity_pct_by_one_way_bps"][str(bps)] for model in modeled), 6)
                               if modeled else None for bps in (10, 25, 50)}})
    common = []
    for cohort in ("canonical", "existing_tactical", "swing_selected", "swing_unselected", "all_covered"):
        for horizon in (5, 10, 14):
            def member(row):
                if cohort in {"canonical", "existing_tactical"}:
                    return row.get("baseline", {}).get(cohort)
                chosen = any(row["features"]["selected"].values())
                return chosen if cohort == "swing_selected" else not chosen if cohort == "swing_unselected" else True
            selected = {row["observation_id"] for row in observations if member(row) is True}
            pending_baseline = sum(member(row) is None for row in observations)
            matured = [row for row in outcomes if row["horizon_sessions"] == horizon
                       and row["observation_id"] in selected and row["status"] == "unadjusted_price_paths_pending_corporate_action_review"]
            label = {"canonical": "canonical_actionable_at_capture", "existing_tactical": "existing_tactical_actionable_at_capture"}.get(cohort, cohort)
            common.append({"cohort": label, "horizon_sessions": horizon, "selected_observations": len(selected),
                           "baseline_unknown_observations": pending_baseline, "matured_common_paths": len(matured),
                           "corporate_action_review_required": len(matured), "performance_eligible_paths": 0,
                           "mean_common_path_net_pct_by_one_way_bps": {str(bps): None for bps in (10, 25, 50)},
                           "raw_unadjusted_price_cost_sensitivity_mean_pct_by_one_way_bps": {
                               str(bps): round(mean(row["raw_common_price_cost_sensitivity_pct_by_one_way_bps"][str(bps)] for row in matured), 6)
                               if matured else None for bps in (10, 25, 50)}})
    return {"status": "prospective_research_only", "observations": len(observations), "outcomes": len(outcomes),
            "distinct_signal_sessions": len({row["source_session"] for row in observations}), "groups": groups,
            "common_path_comparisons": common,
            "profitability_established": False, "reliable_win_rate": None, "portfolio_return": None,
            "corporate_action_review_required": len(outcomes), "performance_eligible_paths": 0,
            "interpretation": "Unadjusted paths require independent split/dividend/distribution/corporate-action review; unreviewed paths are excluded from effectiveness-qualified means. Raw price/cost sensitivities preserve apparent losses, not economic returns. Selection comparisons use the identical first-future-open to named-session-close path for all cohorts; canonical/tactical execution is unmodeled. Baselines describe actionable-at-capture state, not pure stock selection. Captures outside the regular session and unknown baseline state are excluded from baseline membership, never counted rejected. Even matched clocks do not model original conditional entry execution. Overlapping ticker/session paths are not independent trades. Costs are sensitivities, not observed spreads/fills. No portfolio capacity, total return, drawdown, tax or halt claim is established."}


def _unavailable(current: datetime, reason: str, policy: dict | None = None) -> dict:
    return {"schema_version": SCHEMA, "version": VERSION, "generated_at": current.isoformat(),
            "status": "waiting_on_data", "source_session": None, "required_session": latest_published_market_session(current).isoformat(),
            "blockers": [reason], "candidates": [], "coverage": {"current": False, "screened": 0},
            "adoption": (policy or {}).get("adoption", {"automatic_promotion": False, "owner_adoption_required": True,
                                                        "capital_and_risk_review_required": True}), **AUTHORITY}


def _record_attempt(root: Path, attempt: dict, current: datetime) -> None:
    """One original receipt per actual input/dependency state, not per recompose."""
    fingerprints = {}
    for relative in (POLICY, SNAPSHOT, UNIVERSE, HOLDINGS, Path(market_backup.CURRENT)):
        try:
            fingerprints[str(relative)] = _digest(_file(root, relative))
        except OSError:
            fingerprints[str(relative)] = "unreadable"
        except SwingResearchError:
            fingerprints[str(relative)] = "missing_or_linked"
    meaning = {key: attempt.get(key) for key in ("capture_requested", "status", "reason", "source_bindings")}
    meaning.update(required_session=latest_published_market_session(current).isoformat(),
                   observed_inputs=fingerprints, version=VERSION,
                   entry_module_sha256=_digest(Path(__file__).read_bytes()))
    identity = _hash(meaning)
    path = root / OUTPUT / "attempts" / (identity + ".json")
    if path.exists():
        original = json.loads(_file(root, OUTPUT / "attempts" / (identity + ".json")))
        if original.get("attempt_id") != identity or original.get("meaning") != meaning:
            raise SwingResearchError("swing_attempt_history_conflict")
        return
    _retain(path, _json_bytes({**attempt, "attempt_id": identity, "meaning": meaning}))


def _candidate(observation: dict, strategy: str, policy: dict) -> dict:
    feature = observation["features"]
    reference, stop = feature["close"], feature["observed_five_session_low"]
    return {"ticker": observation["ticker"], "setup": strategy, "state": "research_setup",
            "horizon_sessions": policy["holding_sessions"], "source_session": observation["source_session"],
            "first_observed_at": observation.get("first_observed_at"), "observation_id": observation["observation_id"],
            "observation_status": observation.get("observation_status", "immutable_capture"),
            "entry_session": observation["entry_session"], "entry_trigger": round(reference, 4),
            "max_entry": round(reference + policy["maximum_gap_r"] * (reference - stop), 4),
            "invalidation": round(stop, 4), "profit_reference": round(reference + 2 * (reference - stop), 4),
            "profit_reference_kind": "hypothetical_2R_not_observed_resistance",
            "review_deadline": _open(observation["entry_session"]).isoformat(),
            "expires_at": _open(observation["entry_session"]).isoformat(),
            "time_exits": [{"holding_sessions": horizon,
                            "session": ([observation["entry_session"], *_sessions_after(date.fromisoformat(observation["entry_session"]), horizon - 1)])[-1]}
                           for horizon in policy["holding_sessions"]],
            "entry_rule": policy["entry_rule"], "exit_rule": policy["exit_rule"],
            "skip_reasons": ["Experimental strategy has not been adopted for capital.",
                             "Independent corporate-action and current catalyst/event review remains required.",
                             "Executable quotes, spreads and practical response timing remain unverified."],
            "thesis": policy["strategies"][strategy], "catalyst_status": "requires_analyst_direction_review",
            "corporate_action_status": "unreviewed_unadjusted_history",
            "evidence_quality": "validated_completed_daily_OHLCV_only",
            "uncertainty": ["Experimental selection has no proven investment edge or capital authority.",
                            "Daily bars cannot verify an intraday rebound, executable quote, stop fill or actual liquidity.",
                            "Current news/event direction, account commitments, response timing and capital allocation require separate review.",
                            "Composite provider volume definitions may differ; daily-volume ratios are exploratory, not live time-of-day relative volume.",
                            "The displayed 2R level is hypothetical; modeled profit reference is recomputed from an admitted future open."],
            **AUTHORITY}


def build(root: Path, current: datetime, *, capture: bool = False, baseline: dict | None = None) -> dict:
    """Project research; only explicit pipeline capture writes the private study."""
    root, current = Path(root), _aware(current)
    attempt = {"recorded_at": current.isoformat(), "capture_requested": capture, **AUTHORITY}
    result = None
    try:
        policy, bundle, bindings, raws, implementations = _inputs(root, current)
        baseline_context = _baseline(root, baseline, bindings, current)
        output = root / OUTPUT
        lock = ExclusiveFileLock(output / "study.lock") if capture else None
        if lock:
            lock.__enter__()
        try:
            ledger = output / "ledger.jsonl"
            original = ledger.read_bytes() if ledger.exists() else b""
            rows = _read_ledger(ledger, current)
            _verify_retained_inputs(output, rows)
            for row in rows:
                if row["kind"] == "observation" and (row["policy_sha256"] != bindings["policy_sha256"]
                        or row["implementation_sha256"] != bindings["implementation_sha256"]):
                    raise SwingResearchError("swing_version_identity_changed")
            previous = len(rows)
            observations = {row["observation_id"]: row for row in rows if row["kind"] == "observation"}
            outcomes = {(row["observation_id"], row["horizon_sessions"]) for row in rows if row["kind"] == "outcome"}
            current_rows = []
            for ticker, series in sorted(bundle["tickers"].items()):
                identity = _hash({"version": VERSION, "ticker": ticker, "session": bundle["market_session"]})
                observed = observations.get(identity)
                if observed is None:
                    observed = {"kind": "observation", "version": VERSION, "observation_id": identity,
                                "ticker": ticker, "source_session": bundle["market_session"],
                                "recorded_at": current.isoformat(), "first_observed_at": current.isoformat() if capture else None,
                                "entry_session": _next_open(current), "policy_sha256": bindings["policy_sha256"],
                                "implementation_sha256": bindings["implementation_sha256"], "inputs": bindings,
                                "baseline": {"status": baseline_context["status"], "reason": baseline_context["reason"],
                                             "comparability": baseline_context["comparability"],
                                             "capture_clock": baseline_context["capture_clock"],
                                             "proof": baseline_context["proof"],
                                             "canonical": baseline_context["canonical"].get(ticker),
                                             "existing_tactical": baseline_context["existing_tactical"].get(ticker),
                                             "canonical_actionable_at_capture": baseline_context["observed_canonical"].get(ticker),
                                             "existing_tactical_actionable_at_capture": baseline_context["observed_tactical"].get(ticker),
                                             "rejection_codes_at_capture": baseline_context["rejection_codes"].get(ticker, [])},
                                "bars_at_observation": series["bars"][-51:], "features": _features(series["bars"]), **AUTHORITY}
                    if capture:
                        _chain(rows, observed)
                        observations[identity] = rows[-1]
                        observed = rows[-1]
                    else:
                        observed["observation_status"] = "not_captured_read_only"
                elif observed["inputs"] != bindings:
                    # An unchanged signal session cannot be recaptured using corrected prices or later source clocks.
                    raise SwingResearchError("swing_same_session_inputs_changed")
                current_rows.append(observed)
            if capture:
                for observed in list(observations.values()):
                    series = bundle["tickers"].get(observed["ticker"])
                    if series is None:
                        continue  # Retired/unavailable symbol remains pending; never invent a flat exit.
                    for horizon in policy["holding_sessions"]:
                        if (observed["observation_id"], horizon) not in outcomes:
                            result = _outcome(observed, series["bars"], horizon, policy, current, inputs=bindings)
                            if result is not None:
                                _chain(rows, result)
                for raw in raws.values():
                    _retain(output / "input_history" / _digest(raw), raw)
                for name, raw in implementations.items():
                    _retain(output / "implementations" / bindings["implementation_sha256"] / name, raw)
                _read_preview(rows, current)
                if any(_file(root, path) != raw for path, raw in raws.items()):
                    raise SwingResearchError("swing_inputs_changed_during_read")
                _append(ledger, original, rows[previous:])
            candidates = [_candidate(row, strategy, policy) for row in current_rows for strategy in STRATEGIES
                          if row["features"]["selected"][strategy]
                          and _open(row["entry_session"]) > current]
            result = {"schema_version": SCHEMA, "version": VERSION, "generated_at": current.isoformat(),
                      "status": "experimental_current", "source_session": bundle["market_session"],
                      "required_session": bindings["market_session"], "source_bindings": bindings,
                      "blockers": [], "candidates": candidates[:12], "additional_setup_count": max(0, len(candidates) - 12),
                      "coverage": {"current": True, "screened": len(current_rows), "scope": bindings["scope"],
                                   "setups": len(candidates), "unselected": sum(not any(row["features"]["selected"].values()) for row in current_rows),
                                   "expired_entry_observations": sum(_open(row["entry_session"]) <= current for row in current_rows)},
                      "strategies": policy["strategies"], "performance": _performance(rows), "adoption": policy["adoption"],
                      "baseline_status": baseline_context["status"], "baseline_dependency": baseline_context["reason"],
                      "baseline_comparability": baseline_context["comparability"],
                      "interpretation": "Research setups only. An empty result means no current experimental setup, not a buy/sell judgment on existing holdings. Growth valuations remain separate.", **AUTHORITY}
            attempt.update(status="passed", source_bindings=bindings,
                           captured_observations=sum(row["kind"] == "observation" for row in rows[previous:]) if capture else 0,
                           captured_outcomes=sum(row["kind"] == "outcome" for row in rows[previous:]) if capture else 0)
            return result
        finally:
            if lock:
                lock.__exit__(None, None, None)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, (SwingResearchError, market_backup.BackupError)) else "swing_input_or_history_unverified"
        attempt.update(status="failed", reason=reason)
        result = _unavailable(current, reason)
        return result
    finally:
        if capture:
            # Original failures remain separate immutable attempts, never overwritten by a later pass.
            try:
                _record_attempt(Path(root), attempt, current)
            except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                # This advisory lane cannot take down an independently valid capital publication.
                # Preserve bad original bytes and report the inability to record a trustworthy attempt.
                unavailable = _unavailable(current, "swing_attempt_history_unavailable")
                if attempt.get("reason"):
                    unavailable["blockers"].append(attempt["reason"])
                if isinstance(result, dict):
                    result.clear(); result.update(unavailable)
                try:
                    observed = {path.name: _digest(path.read_bytes()) for path in (root / OUTPUT / "attempts").glob("*.json")
                                if path.is_file() and not path.is_symlink()}
                    failure = {"reason": "swing_attempt_history_unavailable", "observed_attempts": observed,
                               "required_session": latest_published_market_session(current).isoformat(), **AUTHORITY}
                    target = root / OUTPUT / "attempt_history_failures" / (_hash(failure) + ".json")
                    if not target.exists():
                        _retain(target, _json_bytes({**failure, "recorded_at": current.isoformat()}))
                except (OSError, ValueError, KeyError, TypeError, RuntimeError):
                    # The parent pipeline retains the unavailable result even when the study store is unwritable.
                    pass


def _read_preview(rows: list[dict], current: datetime) -> None:
    """Use the same full-chain validator before making the append durable."""
    # Kept in memory: reuse validation by adapting the read-only path boundary.
    previous, identities = "", set()
    observations = {}
    for row in rows:
        key = (row.get("kind"), row.get("observation_id"), row.get("horizon_sessions"))
        if (row.get("previous_hash") != previous
                or row.get("record_hash") != _hash({k: v for k, v in row.items() if k != "record_hash"})
                or key in identities or _aware(row["recorded_at"]) > current):
            raise SwingResearchError("swing_ledger_integrity_failure")
        if row["kind"] == "observation":
            observations[row["observation_id"]] = row
        elif row.get("observation_id") not in observations:
            raise SwingResearchError("swing_outcome_unbound")
        previous = row["record_hash"]
        identities.add(key)


def revalidate_projection(root: Path, view: dict, current: datetime) -> dict:
    """Read-time freshness/source suppression; never capture, append or renew."""
    current = _aware(current)
    try:
        if (not isinstance(view, dict) or view.get("schema_version") != SCHEMA
                or view.get("version") != VERSION or _aware(view.get("generated_at")) > current
                or any(view.get(k) != v for k, v in AUTHORITY.items())):
            raise SwingResearchError("swing_projection_unverified")
        policy, bundle, bindings, _, _ = _inputs(Path(root), current)
        if view.get("source_bindings") != bindings:
            raise SwingResearchError("swing_projection_sources_changed")
        rows = _read_ledger(Path(root) / OUTPUT / "ledger.jsonl", current)
        _verify_retained_inputs(Path(root) / OUTPUT, rows)
        observations = {row["observation_id"]: row for row in rows if row["kind"] == "observation"}
        seen = set()
        for row in view.get("candidates", []):
            key = (row["observation_id"], row["setup"])
            if key in seen or row["ticker"] not in bundle["tickers"] or row["setup"] not in STRATEGIES:
                raise SwingResearchError("swing_projection_candidate_unverified")
            observed = observations.get(row["observation_id"])
            if observed is None:
                if row.get("observation_status") != "not_captured_read_only":
                    raise SwingResearchError("swing_projection_observation_missing")
                observed = {"observation_id": _hash({"version": VERSION, "ticker": row["ticker"], "session": bundle["market_session"]}),
                            "ticker": row["ticker"], "source_session": bundle["market_session"],
                            "first_observed_at": None, "entry_session": _next_open(_aware(view["generated_at"])),
                            "features": _features(bundle["tickers"][row["ticker"]]["bars"]),
                            "observation_status": "not_captured_read_only"}
            if (not observed["features"]["selected"][row["setup"]]
                    or row != _candidate(observed, row["setup"], policy)):
                raise SwingResearchError("swing_projection_candidate_unverified")
            seen.add(key)
        result = copy.deepcopy(view)
        result["candidates"] = [row for row in result.get("candidates", [])
                                if _open(row["entry_session"]) > current]
        result["read_time"] = current.isoformat()
        result["expired_candidates_suppressed"] = len(view.get("candidates", [])) - len(result["candidates"])
        return result
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, (SwingResearchError, market_backup.BackupError)) else "swing_projection_unverified"
        result = _unavailable(current, reason)
        result["read_time"] = current.isoformat()
        return result
