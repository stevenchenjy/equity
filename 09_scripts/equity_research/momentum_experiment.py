"""Private, point-in-time EOD experiment; no canonical decisions or network calls.

Every covered ticker is retained, including unavailable and unselected names.
Frozen observations and later outcomes share a hash-chained append-only ledger.
Daily bars cannot establish intraday entries, executable stops, or actual returns.
"""
from __future__ import annotations

import copy
import math
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean
from uuid import uuid4

from daily_common import (ET, ExclusiveFileLock, atomic_write_json, atomic_write_text,
    canonical_sha256, is_us_market_session_date, latest_published_market_session,
    read_csv, read_json, sha256_file)
from investment_plans import regular_close
from tactical_review import _validated_bars
from workflow_evaluation import append_record, aware, read_jsonl

POLICY = Path("01_policies/momentum_experiment.json")
OUTPUT = Path("08_reviews/momentum_experiment.local")
HISTORY = Path("03_source_data/equity_research/tactical_price_history.local.json")
SNAPSHOT = Path("03_source_data/equity_research/market_data_snapshot.csv")
DECISION = Path("04_research/company_research/daily_decision.json")
NEWS = Path("03_source_data/equity_research/official_news_events.local.json")
COHORTS = ("existing_canonical", "existing_tactical", "breakout_only", "breakout_with_volume")
RUN_REASONS = frozenset({"completed", "started", "file_missing", "io_error", "invalid_input",
    "malformed_input", "internal_error", "run_history_unavailable",
    "experiment_policy_invalid", "experiment_threshold_invalid", "experiment_costs_invalid",
    "experiment_price_session_stale_or_future", "experiment_history_timestamp_invalid",
    "duplicate_market_ticker", "experiment_decision_not_current", "experiment_input_changed_during_read",
    "experiment_implementation_changed_without_new_version",
    "experiment_ledger_hash_chain_invalid_preserve_evidence", "experiment_duplicate_or_invalid_record",
    "experiment_policy_changed_without_new_version", "experiment_ledger_chronology_invalid",
    "experiment_outcome_observation_mismatch", "experiment_comparison_evidence_mismatch"})


def number(value):
    if isinstance(value, bool):
        raise ValueError("boolean_is_not_numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite_number")
    return result


def sessions_after(day: date, count: int) -> list[str]:
    result = []
    while len(result) < count:
        day += timedelta(days=1)
        if is_us_market_session_date(day):
            # Do not silently extrapolate the supported holiday calendar.
            regular_close(day.isoformat())
            result.append(day.isoformat())
    return result


def regular_open(session: str) -> datetime:
    """Validate the session/calendar before constructing its regular open."""
    day = date.fromisoformat(session)
    if not is_us_market_session_date(day):
        raise ValueError("experiment_ledger_chronology_invalid")
    regular_close(session)
    return datetime.combine(day, time(9, 30), tzinfo=ET)


def next_open_session(current: datetime) -> str:
    current = aware(current.isoformat()).astimezone(ET)
    today = current.date()
    if is_us_market_session_date(today) and regular_open(today.isoformat()) > current:
        return today.isoformat()
    return sessions_after(today, 1)[0]


def failure_reason(exc: Exception) -> str:
    """Only fixed reason codes can enter durable operational records."""
    if isinstance(exc, ValueError) and str(exc) in RUN_REASONS:
        return str(exc)
    if isinstance(exc, FileNotFoundError):
        return "file_missing"
    if isinstance(exc, OSError):
        return "io_error"
    if isinstance(exc, ValueError):
        return "invalid_input"
    if isinstance(exc, (TypeError, KeyError, AttributeError)):
        return "malformed_input"
    return "internal_error"


def _attempt_summary(rows):
    latest = {}
    for row in rows:
        if (row.get("schema_version") != "equity_momentum_run_attempt_v1"
                or row.get("state") not in {"started", "passed", "failed"}
                or row.get("reason_code") not in RUN_REASONS
                or not isinstance(row.get("attempt_id"), str)):
            raise ValueError("run_history_unavailable")
        aware(row["recorded_at"])
        latest[row["attempt_id"]] = row
    counts = Counter(r["state"] for r in latest.values())
    return {"status": "verified_local_history", "attempts": len(latest),
        "succeeded": counts["passed"], "failed": counts["failed"], "unfinished": counts["started"],
        "failure_reason_counts": dict(Counter(r["reason_code"] for r in latest.values() if r["state"] == "failed")),
        "event_records": len(rows)}


def run_attempt_summary(output: Path):
    with ExclusiveFileLock(output / "run_attempts.lock"):
        return _attempt_summary(read_jsonl(output / "run_attempts.jsonl"))


def record_run_attempt(output: Path, *, attempt_id: str, current: datetime, state: str, reason: str):
    row = {"schema_version": "equity_momentum_run_attempt_v1", "attempt_id": attempt_id,
        "recorded_at": current.isoformat(), "state": state, "reason_code": reason,
        "automatic_action_allowed": False}
    with ExclusiveFileLock(output / "run_attempts.lock"):
        path = output / "run_attempts.jsonl"
        rows = read_jsonl(path)
        _attempt_summary([*rows, row])
        append_record(path, row)
        return _attempt_summary([*rows, row])


def validate_policy(policy):
    if (policy.get("schema_version") != "equity_momentum_experiment_v1"
            or policy.get("status") != "experimental" or policy.get("research_only") is not True
            or policy.get("automatic_action_allowed") is not False
            or policy.get("changes_canonical_eligibility") is not False
            or not policy.get("version") or policy.get("lookback_sessions") != 19
            or policy.get("stop_lookback_sessions") != 5 or policy.get("holding_sessions") != 5):
        raise ValueError("experiment_policy_invalid")
    for key in ("relative_volume_min", "profit_reference_r", "maximum_gap_r"):
        if number(policy[key]) <= 0:
            raise ValueError("experiment_threshold_invalid")
    costs = policy.get("one_way_cost_bps")
    if (not isinstance(costs, list) or not costs or len(set(costs)) != len(costs)
            or any(not 0 < number(v) < 10000 for v in costs)
            or number(policy.get("commission_per_share_usd")) < 0):
        raise ValueError("experiment_costs_invalid")


def validated_series(history, market, digest, current):
    day = date.fromisoformat(history["market_session"])
    if day != latest_published_market_session(current) or current < regular_close(day.isoformat()):
        raise ValueError("experiment_price_session_stale_or_future")
    generated = aware(history.get("generated_at"))
    if generated > current or generated < regular_close(day.isoformat()):
        raise ValueError("experiment_history_timestamp_invalid")
    by_ticker, rejected = {}, {}
    if len({r.get("ticker") for r in market}) != len(market):
        raise ValueError("duplicate_market_ticker")
    for row in market:
        ticker = row["ticker"]
        bars, errors = _validated_bars(history, ticker, day, digest, row.get("last_price"))
        if row.get("data_quality_label") != "ok" or row.get("market_session_date") != day.isoformat():
            errors.append("market_row_unverified")
        try:
            if aware(row["data_timestamp"]) > current:
                errors.append("future_market_observation")
        except (ValueError, KeyError, TypeError):
            errors.append("market_timestamp_unverified")
        if errors:
            rejected[ticker] = sorted(set(errors))
        else:
            by_ticker[ticker] = bars
    return by_ticker, rejected


def observe(*, policy, decision, market, history, news, current, inputs):
    validate_policy(policy)
    by_ticker, rejected = validated_series(history, market, inputs["market_sha256"], current)
    decision_time = aware(decision["generated_at"])
    if (decision_time > current or decision_time.astimezone(ET).date() != current.astimezone(ET).date()
            or decision_time < aware(history["generated_at"])
            or decision.get("market_gate", {}).get("expected_market_session") != history["market_session"]):
        raise ValueError("experiment_decision_not_current")
    baseline = {r["ticker"]: r for r in decision.get("tactical_review", {}).get("drafts", [])}
    canonical = set(decision.get("eligible_action_review_candidates", [])) | set(decision.get("eligible_new_position_review_candidates", []))
    next_session = next_open_session(current)
    result = []
    for row in sorted(market, key=lambda r: r["ticker"]):
        ticker = row["ticker"]
        bars = by_ticker.get(ticker, [])
        features, setup = {}, False
        if bars:
            prior_high = max(number(b["high"]) for b in bars[:-1])
            average_volume = mean(number(b["volume"]) for b in bars[:-1])
            close = number(bars[-1]["close"])
            stop = min(number(b["low"]) for b in bars[-5:])
            rvol = number(bars[-1]["volume"]) / average_volume if average_volume else None
            setup = close > prior_high and close > number(bars[-2]["close"]) and close > stop
            features = {"close": close, "prior_19_session_high": prior_high,
                "daily_volume_over_prior_19_mean": rvol,
                "close_change_pct": 100 * (close / number(bars[-2]["close"]) - 1),
                "average_close_times_volume_usd": mean(number(b["close"]) * number(b["volume"]) for b in bars[:-1]),
                "breakout": setup, "entry_reference": close, "invalidation_reference": stop,
                "maximum_entry_reference": close + policy["maximum_gap_r"] * (close - stop),
                "profit_reference": close + policy["profit_reference_r"] * (close - stop),
                "profit_reference_kind": "hypothetical_R_multiple_not_observed_target",
                "float_status": "unverified", "spread_depth_halts_status": "unverified"}
        events = []
        for event in news.get("events", []):
            if event.get("ticker") != ticker:
                continue
            try:
                published, seen = aware(event["published_at"]), aware(event["first_seen_at"])
                if published <= current and seen <= current and current - published <= timedelta(days=7):
                    events.append({k: event.get(k) for k in ("event_id", "title", "url", "published_at", "first_seen_at", "direction")})
            except (KeyError, ValueError, TypeError):
                continue
        selected = setup and features.get("daily_volume_over_prior_19_mean") is not None and features["daily_volume_over_prior_19_mean"] >= policy["relative_volume_min"]
        record = {"kind": "observation", "experiment_version": policy["version"], "policy": copy.deepcopy(policy),
            "policy_sha256": canonical_sha256(policy), "ticker": ticker,
            "signal_session": history["market_session"], "recorded_at": current.isoformat(),
            "first_observed_at": current.isoformat(),
            "earliest_modeled_entry_session": next_session, "expires_at": regular_close(next_session).isoformat(),
            "inputs": inputs, "bars_at_observation": bars, "features": features,
            "baseline_canonical_eligible": ticker in canonical,
            "baseline_tactical": copy.deepcopy(baseline.get(ticker, {})),
            "cohorts": {"breakout_only": setup, "breakout_with_volume": bool(selected), "existing_canonical": ticker in canonical,
                "existing_tactical": baseline.get(ticker, {}).get("eligible") is True},
            "official_announcements": events, "catalyst_status": "unassessed_official_announcement" if events else "unverified",
            "business_quality_status": "separate_existing_fundamental_research_not_inferred_from_price_float_volume",
            "regime_at_observation": decision.get("market_regime", {}),
            "coverage_errors": rejected.get(ticker, []),
            "classification": "watchlist", "actionable": False, "quantity": 0,
            "disposition": "experimental_setup" if selected else "skipped_or_unverified",
            "actionability_blockers": ["experimental_strategy_unvalidated", "live_quote_spread_depth_halts_unverified",
                "cash_settlement_orders_and_attention_require_recheck", "intraday_patterns_unverified_with_EOD_data"],
            "entry_rule": "Model only the next regular-session open after actual observation; skip below breakout or beyond gap bound. Never backfill the already elapsed open.",
            "failure_rule": "Below the observed five-session low, expiry without valid open, or missing evidence; no conversion to a longer holding.",
            "automatic_action_allowed": False}
        record["observation_id"] = canonical_sha256({"version": policy["version"], "session": record["signal_session"], "ticker": ticker})
        result.append(record)
    return result, by_ticker


def validate_chain(records, current: datetime | None = None):
    previous = ""
    policies = {}
    identities = set()
    observations = {}
    for row in records:
        expected = canonical_sha256({k: v for k, v in row.items() if k != "record_hash"})
        if row.get("previous_hash") != previous or row.get("record_hash") != expected:
            raise ValueError("experiment_ledger_hash_chain_invalid_preserve_evidence")
        key = (row.get("kind"), row.get("observation_id"))
        if key in identities or row.get("kind") not in {"observation", "outcome"}:
            raise ValueError("experiment_duplicate_or_invalid_record")
        identities.add(key)
        recorded = aware(row["recorded_at"])
        if current is not None and recorded > current:
            raise ValueError("experiment_ledger_chronology_invalid")
        if row["kind"] == "observation":
            version, digest = row["experiment_version"], canonical_sha256(row["policy"])
            validate_policy(row["policy"])
            if digest != row["policy_sha256"] or policies.get(version, digest) != digest:
                raise ValueError("experiment_policy_changed_without_new_version")
            if (regular_close(row["signal_session"]) > recorded
                    or regular_open(row["earliest_modeled_entry_session"]) <= recorded):
                raise ValueError("experiment_ledger_chronology_invalid")
            policies[version] = digest
            observations[row["observation_id"]] = row
        else:
            observation = observations.get(row["observation_id"])
            if (observation is None or row["ticker"] != observation["ticker"]
                    or row.get("cohorts") != observation["cohorts"]
                    or row.get("experiment_version", observation["experiment_version"]) != observation["experiment_version"]
                    or row.get("policy_sha256", observation["policy_sha256"]) != observation["policy_sha256"]):
                raise ValueError("experiment_outcome_observation_mismatch")
            start = date.fromisoformat(observation["earliest_modeled_entry_session"])
            expected_sessions = [start.isoformat(), *sessions_after(start, observation["policy"]["holding_sessions"] - 1)]
            if (recorded < aware(observation["recorded_at"])
                    or [b.get("session_date") for b in row.get("forward_bars", [])] != expected_sessions
                    or regular_close(expected_sessions[-1]) > recorded):
                raise ValueError("experiment_ledger_chronology_invalid")
        previous = expected
    return policies


def append_chained(path, records, row):
    row = copy.deepcopy(row)
    row["previous_hash"] = records[-1]["record_hash"] if records else ""
    row["record_hash"] = canonical_sha256(row)
    append_record(path, row)
    records.append(row)


def path_result(bars, *, entry, stop, target, policy):
    """Long-only toy execution: gap stops, stop-first ambiguity, no fill guarantees."""
    exit_price, reason, exit_day = number(bars[-1]["close"]), "five_session_time_exit", bars[-1]["session_date"]
    for bar in bars:
        op, low, high = (number(bar[k]) for k in ("open", "low", "high"))
        if low <= stop:
            exit_price, reason, exit_day = min(op, stop), "stop_or_gap_loss", bar["session_date"]
            break
        if high >= target:
            exit_price, reason, exit_day = target, "hypothetical_profit_reference", bar["session_date"]
            break
    returns = {}
    for bps in policy["one_way_cost_bps"]:
        cost = bps / 10000
        buy = entry * (1 + cost) + policy["commission_per_share_usd"]
        sell = exit_price * (1 - cost) - policy["commission_per_share_usd"]
        returns[str(bps)] = round(100 * (sell / buy - 1), 6)
    return {"status": "modeled", "entry": entry, "exit": exit_price, "exit_session": exit_day,
            "reason": reason, "net_return_pct_by_one_way_bps": returns,
            "stop": stop, "target": target, "actual_fill": False}


def evaluate(observation, series, current):
    """Return only matured outcomes; unavailable/delisted series remain pending."""
    ticker, policy = observation["ticker"], observation["policy"]
    bars = series.get(ticker, [])
    if not bars or not observation["bars_at_observation"]:
        return None
    existing = {b["session_date"]: b for b in observation["bars_at_observation"]}
    corrected = any(b["session_date"] in existing and b != existing[b["session_date"]] for b in bars)
    start = date.fromisoformat(observation["earliest_modeled_entry_session"])
    expected = [start.isoformat(), *sessions_after(start, policy["holding_sessions"] - 1)]
    lookup = {b["session_date"]: b for b in bars}
    if any(day not in lookup for day in expected) or current < regular_close(expected[-1]):
        return None
    window = [lookup[day] for day in expected]
    if corrected:
        return {"kind": "outcome", "observation_id": observation["observation_id"], "ticker": ticker,
                "experiment_version": observation["experiment_version"], "policy_sha256": observation["policy_sha256"],
                "recorded_at": current.isoformat(), "status": "corporate_action_or_correction_review_required",
                "forward_bars": window, "cohorts": observation["cohorts"]}
    op = number(window[0]["open"])
    close = number(window[-1]["close"])
    # Fixed horizon path for EVERY valid covered ticker permits missed-opportunity review.
    paths = {}
    for bps in policy["one_way_cost_bps"]:
        buy = op * (1 + bps / 10000) + policy["commission_per_share_usd"]
        sell = close * (1 - bps / 10000) - policy["commission_per_share_usd"]
        paths[str(bps)] = round(100 * (sell / buy - 1), 6)
    feature = observation["features"]
    models = {}
    for cohort, selected in observation["cohorts"].items():
        if not selected:
            models[cohort] = {"status": "not_selected"}
            continue
        if cohort in {"existing_tactical", "existing_canonical"}:
            models[cohort] = {"status": "unmodeled_intraday_entry_required" if cohort == "existing_tactical"
                else "unmodeled_strategy_entry_required", "actual_fill": False}
            continue
        trigger, stop, maximum = (feature[k] for k in ("entry_reference", "invalidation_reference", "maximum_entry_reference"))
        target = op + policy["profit_reference_r"] * (op - stop)
        if not stop < op < target or not trigger <= op <= maximum:
            models[cohort] = {"status": "expired_unfilled_or_gap_skipped"}
        else:
            models[cohort] = path_result(window, entry=op, stop=stop, target=target, policy=policy)
    return {"kind": "outcome", "observation_id": observation["observation_id"], "ticker": ticker,
        "experiment_version": observation["experiment_version"], "policy_sha256": observation["policy_sha256"],
        "recorded_at": current.isoformat(), "status": "matured_price_path_study",
        "entry_session": expected[0], "last_session": expected[-1], "forward_bars": window,
        "cohorts": observation["cohorts"], "models": models,
        "all_covered_net_path_pct_by_one_way_bps": paths,
        "common_path_rule": "identical_next_future_regular_open_to_fifth_session_close_for_all_selection_cohorts",
        "comparison_kind": "selection_only_common_price_paths_not_original_strategy_execution",
        "missed_positive_path": not observation["cohorts"]["breakout_with_volume"] and paths[str(max(policy["one_way_cost_bps"]))] > 0,
        "automatic_action_allowed": False}


def summarize(records):
    observations = [r for r in records if r["kind"] == "observation"]
    outcomes = [r for r in records if r["kind"] == "outcome"]
    by_version = {}
    for version in sorted({r["experiment_version"] for r in observations}):
        group = [r for r in observations if r["experiment_version"] == version]
        policy = group[0]["policy"]
        policy_digest = canonical_sha256(policy)
        if any(canonical_sha256(r["policy"]) != policy_digest for r in group):
            raise ValueError("experiment_policy_changed_without_new_version")
        costs = [str(v) for v in policy["one_way_cost_bps"]]
        high_cost = str(max(policy["one_way_cost_bps"]))
        ids = {r["observation_id"] for r in group}
        group_outcomes = [r for r in outcomes if r["observation_id"] in ids]
        matured = [r for r in group_outcomes if r.get("status") == "matured_price_path_study"]
        if any(set(r.get("all_covered_net_path_pct_by_one_way_bps", {})) != set(costs) for r in matured):
            raise ValueError("experiment_comparison_evidence_mismatch")
        comparison = {}
        for name in COHORTS:
            selected = [r for r in group if r["cohorts"].get(name,
                r.get("baseline_canonical_eligible", False) if name == "existing_canonical" else False)]
            selected_ids = {r["observation_id"] for r in selected}
            paths = [r for r in matured if r["observation_id"] in selected_ids]
            selected_outcomes = [r for r in group_outcomes if r["observation_id"] in selected_ids]
            comparison[name] = {"selected": len(selected), "matured_common_paths": len(paths),
                "distinct_signal_sessions": len({r["signal_session"] for r in selected}),
                "pending_or_missing": len(selected) - len(selected_outcomes),
                "correction_review_required": sum(r.get("status") == "corporate_action_or_correction_review_required" for r in selected_outcomes),
                "common_path_net_mean_pct_by_one_way_bps": {cost: mean(
                    r["all_covered_net_path_pct_by_one_way_bps"][cost] for r in paths) for cost in costs} if paths else {},
                "losing_common_paths_at_highest_cost": sum(r["all_covered_net_path_pct_by_one_way_bps"][high_cost] < 0 for r in paths),
                "execution_status_counts": dict(Counter(r.get("models", {}).get(name, {}).get("status", "unverified") for r in selected_outcomes))}
        by_version[version] = {"policy_sha256": policy_digest, "one_way_cost_bps": policy["one_way_cost_bps"],
            "commission_per_share_usd": policy["commission_per_share_usd"], "cohorts": comparison,
            "comparison_kind": "selection_only_identical_future_open_to_fifth_close_paths",
            "portfolio_constraints_applied": False, "original_strategy_execution_modeled": False,
            "nonindependent_overlapping_observations": True}
    return {"observations": len(observations), "outcomes": len(outcomes),
        "pending_or_missing": len(observations) - len(outcomes),
        "skipped_or_unverified": sum(r["disposition"] != "experimental_setup" for r in observations),
        "missed_positive_paths": sum(r.get("missed_positive_path", False) for r in outcomes),
        "comparison": "See comparison_by_version; policies and cost grids are never pooled.",
        "comparison_by_version": by_version, "performance_evidence": "unvalidated_forward_price_path_study",
        "incremental_value_established": False}


def comparison_markdown(summary):
    lines = [f"Observations: **{summary['observations']}** · outcomes: **{summary['outcomes']}** · "
        f"pending or missing: **{summary['pending_or_missing']}** · skipped or unverified: **{summary['skipped_or_unverified']}**.",
        f"Unselected positive common paths: **{summary['missed_positive_paths']}**. Incremental value remains unestablished."]
    labels = {"existing_canonical": "Existing canonical eligibility", "existing_tactical": "Existing tactical eligibility",
        "breakout_only": "Breakout only", "breakout_with_volume": "Breakout + volume"}
    for version, group in summary["comparison_by_version"].items():
        lines.extend(["", f"### {version}", "",
            "| Selection cohort | Selected | Matured common paths | Pending or missing | Common net mean by per-side cost |",
            "|---|---:|---:|---:|---|"])
        for name, row in group["cohorts"].items():
            means = "; ".join(f"{cost} bps: {value:+.2f}%" for cost, value in row["common_path_net_mean_pct_by_one_way_bps"].items()) or "No matured evidence"
            lines.append(f"| {labels[name]} | {row['selected']} | {row['matured_common_paths']} | {row['pending_or_missing']} | {means} |")
        corrections = max((row["correction_review_required"] for row in group["cohorts"].values()), default=0)
        if corrections:
            lines.extend(["", "Some outcomes require corporate-action/data-correction review and are excluded from path means; see the JSON counts per cohort."])
    return lines


def _run(root: Path, current: datetime, output: Path):
    implementation = {name: sha256_file(Path(__file__).parent / name) for name in
        ("momentum_experiment.py", "tactical_review.py", "investment_plans.py", "daily_common.py", "archived_momentum.py")}
    implementation_hash = canonical_sha256(implementation)
    source_paths = {"market_sha256": SNAPSHOT, "history_sha256": HISTORY, "decision_sha256": DECISION, "news_sha256": NEWS}
    inputs = {key: sha256_file(root / path) for key, path in source_paths.items()}
    inputs["implementation_sha256"] = implementation_hash
    inputs["implementation_files"] = implementation
    policy, history, decision = (read_json(root / p) for p in (POLICY, HISTORY, DECISION))
    market = read_csv(root / SNAPSHOT)
    observations, series = observe(policy=policy, history=history, decision=decision, market=market,
        news=read_json(root / NEWS, {}), current=current, inputs=inputs)
    if any(sha256_file(root / path) != inputs[key] for key, path in source_paths.items()):
        raise ValueError("experiment_input_changed_during_read")
    with ExclusiveFileLock(output / "ledger.lock"):
        ledger = output / "ledger.jsonl"
        records = read_jsonl(ledger)
        versions = validate_chain(records, current)
        if versions.get(policy["version"], canonical_sha256(policy)) != canonical_sha256(policy):
            raise ValueError("experiment_policy_changed_without_new_version")
        if any(r["kind"] == "observation" and r["experiment_version"] == policy["version"]
                and r["inputs"].get("implementation_sha256") != implementation_hash for r in records):
            raise ValueError("experiment_implementation_changed_without_new_version")
        seen = {r["observation_id"] for r in records if r["kind"] == "observation"}
        for row in observations:
            if row["observation_id"] not in seen:
                append_chained(ledger, records, row)
        frozen = {r["observation_id"]: r for r in records if r["kind"] == "observation"}
        receipts = [{"observation_id": row["observation_id"], "ticker": row["ticker"],
            "first_observed_at": frozen[row["observation_id"]]["recorded_at"],
            "current_received_at": current.isoformat(),
            "inputs_changed_since_first_observation": frozen[row["observation_id"]]["inputs"] != inputs}
            for row in observations]
        observations = [copy.deepcopy(frozen[row["observation_id"]]) for row in observations]
        complete = {r["observation_id"] for r in records if r["kind"] == "outcome"}
        for row in list(records):
            if row["kind"] == "observation" and row["observation_id"] not in complete:
                if row["inputs"].get("implementation_sha256") != implementation_hash:
                    continue  # Preserve older-version observations for their recorded implementation.
                outcome = evaluate(row, series, current)
                if outcome:
                    outcome["evaluation_inputs"] = inputs
                    append_chained(ledger, records, outcome)
        # Software repairs start a new implementation version, but never orphan
        # already captured cohorts. Old outcomes use their registered old code.
        from archived_momentum import evaluate_archived
        archived_outcomes = evaluate_archived(root=root, records=records, history=history,
                market=market, current=current, inputs=inputs)
        preview = copy.deepcopy(records)
        for outcome in archived_outcomes:
            candidate = copy.deepcopy(outcome)
            candidate["previous_hash"] = preview[-1]["record_hash"] if preview else ""
            candidate["record_hash"] = canonical_sha256(candidate)
            preview.append(candidate)
        validate_chain(preview, current)  # Validate the whole append before changing durable history.
        for outcome in archived_outcomes:
            append_chained(ledger, records, outcome)
        complete = {r["observation_id"] for r in records if r["kind"] == "outcome"}
        validate_chain(records, current)
        report = {"schema_version": "equity_momentum_report_v1", "generated_at": current.isoformat(),
            "market_session": history["market_session"], "status": "experimental",
            "policy_version": policy["version"], "summary": summarize(records),
            "current_observations": observations, "observation_receipts": receipts,
            "current_receipt_at": current.isoformat(), "ledger_sha256": sha256_file(ledger),
            "pending_older_implementation": sum(r["kind"] == "observation" and r["observation_id"] not in complete
                and r["inputs"].get("implementation_sha256") != implementation_hash for r in records),
            "software_run": "passed", "automatic_action_allowed": False}
        atomic_write_json(output / "report.json", report)
        lines = ["# Momentum research experiment", "", f"Generated: {current.isoformat()}; EOD evidence: {history['market_session']}.", "",
            "Experimental only. Zero actionable quantities. Canonical strategy, allocation, risk, decisions and delivery rules are unchanged.", "",
            "## Forward evidence", "", *comparison_markdown(report["summary"]), "",
            "These are overlapping ticker/session price paths, not independent trades, portfolio returns, statistical significance or proven incremental value. Selection comparisons apply an identical future-open to fifth-close path and cost grid to each cohort, separately for each policy version. Original canonical and conditional tactical entry execution is unmodeled. All unselected names remain available for missed-opportunity review.", "",
            "Entry is the first regular-session open strictly AFTER actual first observation, including today's open if the observation is premarket. No elapsed opens are filled retrospectively. The separate experimental stop/target models are gap-adjusted and assume stop first for same-bar ambiguity; their returns are not used for baseline selection comparisons. Per-side costs are the frozen policy's sensitivities, not verified live spreads or fills. Full exit at 2R is an experimental simplification. Missing/delisted observations stay pending; corrections require review. No dividends, capital constraints, halts or borrow are simulated; no leverage is used.", "",
            "Current coverage below reuses immutable first-capture observations. A new receipt does not replace the original timing, catalyst context or baseline eligibility; first-observed and current-received timestamps are recorded separately in report.json.", "",
            "First pullbacks and bull flags remain unverified without intraday data. Float, live liquidity, settled cash, account type, broker restrictions and owner attention require verification before any executable adaptation. Official announcements are unassessed context, never automatically bullish catalysts. Business quality comes from the separate maintained thesis.", "",
            "## Current coverage", "", "| Ticker | Breakout | Daily volume / prior 19 mean | Experimental selection | Baseline tactical eligible | Evidence gaps |",
            "|---|---|---:|---|---|---|"]
        for row in observations:
            f = row["features"]
            volume_ratio = f.get("daily_volume_over_prior_19_mean")
            volume_text = f"{volume_ratio:.2f}" if volume_ratio is not None else "unverified"
            lines.append(f"| {row['ticker']} | {f.get('breakout', 'unverified')} | {volume_text} | {row['cohorts']['breakout_with_volume']} | {row['cohorts']['existing_tactical']} | {', '.join(row['coverage_errors']) or 'Live actionability unverified'} |")
        lines.extend(["", "Policy versions are frozen after first capture; no automatic retuning or promotion. No minimum winning streak authorizes a change. See 00_project_control/momentum_integration_20260927.md for source distinctions and promotion requirements."])
        atomic_write_text(output / "report.md", "\n".join(lines) + "\n")
    return report


def _run_with_attempt_history(root: Path, current: datetime, output: Path):
    """Preserve every run attempt separately from the investment observations."""
    attempt_id = uuid4().hex
    try:
        record_run_attempt(output, attempt_id=attempt_id, current=current, state="started", reason="started")
        report = _run(root, current, output)
        counts = record_run_attempt(output, attempt_id=attempt_id, current=current, state="passed", reason="completed")
        report["run_attempt_history"] = counts
        report["run_attempt_id"] = attempt_id
        atomic_write_json(output / "report.json", report)
        path = output / "report.md"
        atomic_write_text(path, path.read_text() + "\n## Software run history\n\n"
            + f"Attempts: **{counts['attempts']}** · succeeded: **{counts['succeeded']}** · failed: **{counts['failed']}** · unfinished: **{counts['unfinished']}**."
            + "\n\nThese counts concern software availability only. Failed or unfinished captures provide no investment-performance evidence.\n")
        return report
    except Exception as exc:
        # Failure recording must not erase the original failure or prior evidence.
        try:
            record_run_attempt(output, attempt_id=attempt_id, current=current, state="failed", reason=failure_reason(exc))
        except Exception:
            pass
        raise


def run(root: Path, current: datetime, output: Path | None = None):
    output = output or root / OUTPUT
    # Keep report publication and its final attempt counts in one writer turn.
    with ExclusiveFileLock(output / "run.lock"):
        return _run_with_attempt_history(root, current, output)
