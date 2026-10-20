"""Read-only workflow evaluation and explicitly confirmed private performance records.

No recommendation, account mutation, network request, email, or brokerage action.
Price-path studies are not investment returns. Performance never uses planning cash.
"""
from __future__ import annotations

import json
import math
import os
import statistics
from collections import Counter
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from daily_common import ROOT, ExclusiveFileLock, canonical_sha256, iso_now, is_us_market_session_date

ET = ZoneInfo("America/New_York")
PERFORMANCE_PATH = ROOT / "05_risk_and_positions/performance_observations.local.jsonl"
REFRESH_HISTORY_PATH = ROOT / "00_project_control/run_logs/refresh_history.local.jsonl"
EVALUATION_JSON_PATH = ROOT / "08_reviews/current/workflow_evaluation.local.json"
EVALUATION_MD_PATH = ROOT / "08_reviews/current/workflow_evaluation.local.md"
# Engineering target after the bounded provider publication retries, not a market-data SLA.
DEFAULT_READY_DEADLINE_ET = "13:30"


def aware(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must have a timezone")
    return parsed


def finite(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("numeric value required")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("finite value required")
    return result


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("ledger row must be an object")
            rows.append(row)
    return rows


def append_record(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def record_refresh(state: dict[str, Any], path: Path = REFRESH_HISTORY_PATH) -> bool:
    """Called after a finished refresh; idempotent by exact run start timestamp."""
    aware(state["started_at"])
    aware(state["completed_at"])
    run_id = canonical_sha256({"cycle_date": state["cycle_date"], "started_at": state["started_at"]})
    # Retain only bounded local statuses, never third-party response diagnostics.
    record = {key: state.get(key) for key in ("cycle_date", "started_at", "completed_at", "outcome",
              "hard_failures", "soft_failures", "advisory_failures", "market_snapshot_mode", "expected_market_session")}
    record["steps"] = [{key: step.get(key) for key in ("name", "exit_code", "outcome", "result_code", "duration_seconds")}
                       for step in state.get("steps", []) if isinstance(step, dict)]
    record.update(schema_version="workflow_refresh_history_v1", run_id=run_id)
    with ExclusiveFileLock(path.with_suffix(".lock")):
        if any(row.get("run_id") == run_id for row in read_jsonl(path)):
            return False
        append_record(path, record)
    return True


def operational_summary(scheduler: dict[str, Any], run_log: list[dict[str, Any]], runtime_log: list[dict[str, Any]],
                        refresh_history: list[dict[str, Any]], *, now: datetime,
                        ready_deadline_et: str = DEFAULT_READY_DEADLINE_ET) -> dict[str, Any]:
    """Distinguish retained calendar cycles from exchange sessions and recoveries.

    Deadline denominators include missing calendar days inside retained scheduler
    coverage; today's cycle is not failed before its deadline. Legacy evidence
    without first success timestamps is explicitly unknown, never on-time.
    """
    deadline_clock = time.fromisoformat(ready_deadline_et)
    states = scheduler.get("dates", {})
    dates = sorted(day for day in states if day <= now.astimezone(ET).date().isoformat())
    completions: dict[str, list[datetime]] = {}
    for row in run_log:
        if row.get("component") == "daily_refresh" and row.get("outcome") == "passed":
            try:
                stamp = aware(row.get("logged_at"))
                completions.setdefault(str(row.get("cycle_date", stamp.date())), []).append(stamp)
            except (ValueError, TypeError):
                pass
    for row in refresh_history:
        if row.get("outcome") == "passed":
            completions.setdefault(str(row["cycle_date"]), []).append(aware(row["completed_at"]))
    cycles = []
    if dates:
        start = date.fromisoformat(dates[0])
        end = now.astimezone(ET).date()
        for offset in range((end - start).days + 1):
            day = start + timedelta(days=offset)
            key = day.isoformat()
            state = states.get(key, {})
            deadline = datetime.combine(day, deadline_clock, ET)
            passed = completions.get(key, [])
            # Last-success can prove on-time but cannot prove earlier absence.
            latest = state.get("refresh_last_passed_at")
            if latest:
                passed = [*passed, aware(latest)]
            first = min(passed) if passed else None
            eventual = bool(first or state.get("refresh_fully_passed"))
            status = ("on_time" if first and first <= deadline else "late" if first
                      else "unknown_completion_time" if eventual else "not_yet_due" if now < deadline
                      else "not_ready_observed" if state else "no_observation")
            cycles.append({"cycle_date": key, "exchange_session": is_us_market_session_date(day),
                           "deadline_at": deadline.isoformat(), "status": status,
                           "first_observed_success_at": first.isoformat() if first else None,
                           "eventually_ready": eventual,
                           "delivery_terminal_reason": state.get("decision_terminal_reason", "")})
    eligible = [row for row in cycles if row["status"] != "not_yet_due"]
    counts = Counter(row["status"] for row in eligible)
    failures = Counter()
    for row in runtime_log:
        if dates and not dates[0] <= str(row.get("timestamp", ""))[:10] <= now.astimezone(ET).date().isoformat():
            continue
        if row.get("outcome") in {"failed", "error", "blocked"}:
            # The existing detail string may contain remote fragments; expose a finite prefix only.
            detail = str(row.get("detail", "")).split(":", 1)[0]
            reason = detail if detail and all(c.isalnum() or c in "_-" for c in detail) else str(row.get("event", "runtime_failure"))
            failures[reason] += 1
    step_times: dict[str, list[float]] = {}
    run_times = []
    for row in refresh_history:
        try:
            elapsed = (aware(row["completed_at"]) - aware(row["started_at"])).total_seconds()
            if elapsed >= 0:
                run_times.append(elapsed)
        except (KeyError, ValueError):
            pass
        for step in row.get("steps", []):
            if step.get("duration_seconds") is not None:
                duration = finite(step["duration_seconds"])
                if duration >= 0:
                    step_times.setdefault(str(step.get("name")), []).append(duration)
    return {"ready_deadline_et": ready_deadline_et, "deadline_kind": "engineering_target_after_provider_retry_window",
            "calendar_cycles_observed_or_missing": len(cycles), "due_calendar_cycles": len(eligible),
            "exchange_sessions_in_window": sum(row["exchange_session"] for row in cycles),
            "eventually_ready_cycles": sum(row["eventually_ready"] for row in eligible),
            "on_time_cycles": counts["on_time"], "late_cycles": counts["late"],
            "unknown_or_missing_cycles": sum(counts[key] for key in ("unknown_completion_time", "no_observation")),
            "on_time_pct": round(100 * counts["on_time"] / len(eligible), 2) if eligible else None,
            "failure_reason_counts": dict(failures), "cycles": cycles,
            "timed_runs": len(run_times), "median_refresh_seconds": statistics.median(run_times) if run_times else None,
            "step_timing": {name: {"observations": len(values), "median_seconds": statistics.median(values),
                                   "maximum_seconds": max(values)} for name, values in sorted(step_times.items())},
            "historical_timing_limit": "Per-step timings are available only after instrumentation; no historical timings invented."}


def outcome_coverage(snapshots: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                     history: list[dict[str, Any]]) -> dict[str, Any]:
    from track_recommendation_outcomes import HORIZONS, forecast_origin, market_sessions, observation_id
    sessions = market_sessions(history)
    origins: dict[str, dict[str, Any]] = {}
    missing_origin = 0
    material = set()
    for row in snapshots:
        origin = forecast_origin(row, sessions)
        if origin:
            origins.setdefault(observation_id(row, origin), row)
        else:
            missing_origin += 1
        if row.get("human_confirmation_required") == "yes":
            material.add(canonical_sha256({key: row.get(key, "") for key in
                ("ticker", "plan_id", "plan_version", "classification", "action_label", "invalidation", "suggested_whole_shares")}))
    matured: dict[int, set[str]] = {horizon: set() for horizon in HORIZONS}
    for row in outcomes:
        horizon = int(row.get("horizon_sessions") or 0)
        oid = row.get("independent_observation_id")
        if horizon in matured and oid and row.get("primary_observation") == "yes":
            matured[horizon].add(str(oid))
    return {"snapshot_rows": len(snapshots), "source_sessions": len({row.get("market_session") for row in snapshots}),
            "unique_origin_observations": len(origins), "snapshots_without_available_forward_origin": missing_origin,
            "unique_matured_observations": len(set().union(*matured.values())),
            "unique_material_instruction_versions": len(material),
            "completed_review_meetings": None,
            "plan_linked_snapshots": sum(bool(row.get("plan_id")) for row in snapshots),
            "thesis_linked_snapshots": sum(bool(row.get("thesis_id")) for row in snapshots),
            "horizons": [{"horizon_sessions": horizon, "matured": len(matured[horizon]),
                          "pending_or_missing": max(0, len(origins) - len(matured[horizon]))} for horizon in HORIZONS],
            "limitations": ["Correlated issuers, overlapping horizons, and repeated daily origins are not independent trials.",
                            "Close-price outcomes exclude execution costs and dividends and require corporate-action review.",
                            "Counts do not establish profitable selection, completed review meetings, or portfolio performance."]}


def empty_thesis_review() -> dict[str, Any]:
    return {"status": "not_recorded", "recorded_versions": 0, "distinct_reasoning_cases": 0,
        "recorded_method_cases": 0, "prospective_method_cases": 0,
        "price_conditions_assessed_cases": 0, "loss_paths_assessed_cases": 0, "falsifiable_difference_cases": 0,
        "retrospective_cases": 0, "business_evidence_cases": 0,
        "price_observed_cases": 0, "cases": [], "adoption_queue": [], "shared_exposures": [],
        "shared_exposure_coverage": "unknown", "validation_errors": [],
        "limitations": ["Repeated unchanged reviews count once; these cases and their price horizons remain correlated.",
            "Process assessments are authored judgments against the original record, not scores inferred from later returns.",
            "Business evidence and close-price paths are separate; no causal alpha, luck attribution or executed return is inferred.",
            "Shared exposures are qualitative; ETF look-through, portfolio weights and loss correlation are not quantified."]}


def thesis_review_summary(store: dict[str, Any] | None, snapshots: list[dict[str, Any]],
                         outcomes: list[dict[str, Any]], *, now: datetime, evidence_root: Path,
                         held_tickers: set[str] | None = None) -> dict[str, Any]:
    """An optional learning section fails visibly without stopping the report."""
    try:
        return _thesis_review_summary(store, snapshots, outcomes, now=now, evidence_root=evidence_root,
                                      held_tickers=held_tickers)
    except (ValueError, KeyError, TypeError, OSError, AttributeError) as exc:
        result = empty_thesis_review()
        result.update(status="invalid_evidence", validation_errors=[str(exc)])
        return result


def _thesis_review_summary(store: dict[str, Any] | None, snapshots: list[dict[str, Any]],
                          outcomes: list[dict[str, Any]], *, now: datetime, evidence_root: Path,
                          held_tickers: set[str] | None = None) -> dict[str, Any]:
    """Join immutable versions; unchanged reasoning is grouped, never rewritten."""
    from thesis_evidence import evidence_context, validate_review, validate_store
    from thesis_retrospective import method_features, original_reasoning_time, price_observations, reasoning_fingerprint

    result = empty_thesis_review()
    held = held_tickers or set()
    if store is None:
        result["adoption_queue"] = [{"ticker": ticker, "priority": "held", "reason": "company_review_not_recorded",
            "next_evidence": "Create a source-bound company review with explicit unknowns for unavailable expectations and loss evidence."}
            for ticker in sorted(held)]
        return result
    try:
        latest = validate_store(store)
        context = evidence_context(evidence_root)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result.update(status="invalid_evidence", validation_errors=[str(exc)])
        return result
    records = [row for row in store["records"] if aware(row["reviewed_at"]) <= now]
    # Do not show future-authored assessments when rendering an earlier cutoff.
    latest = {row["ticker"]: row for row in records}
    result["recorded_versions"] = len(records)
    by_id = {row["review_id"]: row for row in records}
    by_version = {(row["ticker"], str(row["version"])): row for row in records}
    verified, invalid = set(), {}
    retrospective_originals = {row["retrospective"]["original_review_id"] for row in records if row.get("retrospective")}
    for row in records:
        if row.get("research_method") or row.get("retrospective") or row["review_id"] in retrospective_originals:
            try:
                validate_review(row, evidence_root, context, now.isoformat())
                if original_reasoning_time(row) <= now:
                    verified.add(row["review_id"])
            except (ValueError, KeyError, TypeError, OSError) as exc:
                invalid[row["review_id"]] = str(exc)
    result["validation_errors"] = [f"{key}: {value}" for key, value in invalid.items()]
    # The ledger supplies the anchor. Snapshot linkage never backfills a method.
    anchors = {row["review_id"]: row for row in records if row.get("research_method") and row["review_id"] in verified}
    for snapshot in snapshots:
        row = by_version.get((snapshot.get("ticker"), str(snapshot.get("thesis_version"))))
        if row and row["review_id"] not in invalid and snapshot.get("thesis_id") == "company_thesis:" + row["ticker"]:
            anchors[row["review_id"]] = row
    retrospectives: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        retrospective = row.get("retrospective")
        if retrospective and row["review_id"] in verified:
            original_id = retrospective["original_review_id"]
            anchors[original_id] = by_id[original_id]
            retrospectives.setdefault(original_id, []).append(row)
    groups: dict[str, list[dict[str, Any]]] = {}
    for original in anchors.values():
        groups.setdefault(reasoning_fingerprint(original), []).append(original)
    for fingerprint, originals in groups.items():
        originals.sort(key=lambda row: (original_reasoning_time(row), row["version"]))
        reviews = [review for original in originals for review in retrospectives.get(original["review_id"], [])]
        retrospective_record = max(reviews, key=lambda row: (aware(row["reviewed_at"]), row["version"])) if reviews else None
        # A review of a later duplicate remains bound to that exact duplicate.
        original = by_id[retrospective_record["retrospective"]["original_review_id"]] if retrospective_record else originals[0]
        retrospective = retrospective_record["retrospective"] if retrospective_record else None
        method_valid = bool(original.get("research_method")) and original["review_id"] in verified
        original_verified = original["review_id"] in verified
        features = {key: value and method_valid for key, value in method_features(original).items()}
        cutoff = aware(retrospective_record["reviewed_at"]) if retrospective_record else now
        prices = price_observations(original, snapshots, outcomes, cutoff)
        blockers = []
        if not method_valid:
            blockers.append("original_method_unavailable_or_unverified")
        if retrospective and not original_verified:
            blockers.append("original_source_evidence_unverified")
        if not retrospective:
            blockers.append("retrospective_not_recorded")
        if not retrospective or not original_verified or retrospective["business_outcome"]["status"] == "not_yet_observable":
            blockers.append("later_business_evidence_not_assessed")
        if prices["status"] != "observed_price_path":
            blockers.append(prices["status"])
        waiting = (original.get("research_method") or {}).get("waiting_for", {}) if method_valid else {}
        next_evidence = retrospective["business_outcome"]["assessment"] if retrospective else (
            waiting.get("next_evidence") or waiting.get("condition") or "; ".join(original.get("unresolved_questions", [])[:2]))
        case = {"case_fingerprint": fingerprint, "ticker": original["ticker"],
            "position_scope": "held" if original["ticker"] in held else "research_only",
            "original_review_id": original["review_id"], "original_record_sha256": original["record_sha256"],
            "original_version": original["version"], "equivalent_recorded_versions": [row["version"] for row in originals],
            "original_evidence_verified": original_verified,
            "method_recorded": method_valid, "prospective_method_recorded": method_valid and all(features.values()),
            "method_features": features,
            "retrospective_review_id": retrospective_record["review_id"] if retrospective_record else None,
            "retrospective_reviewed_at": retrospective_record["reviewed_at"] if retrospective_record else None,
            "decision_process": retrospective["decision_process"] if retrospective and method_valid else {"assessment": "unresolved",
                "rationale": "Original prospective method unavailable or later process review not recorded."},
            "business_outcome": retrospective["business_outcome"] if retrospective and original_verified else {
                "status": "not_yet_observable", "assessment": "No later evidence assessment with a verified original source record.", "claim_ids": []},
            "lesson": retrospective["lesson"] if retrospective else None, "price_observations": prices,
            "pending_reasons": blockers, "next_evidence": next_evidence,
            "scheduled_review_due": aware(original["next_review_at"]) <= now and not retrospective}
        result["cases"].append(case)
    result["cases"].sort(key=lambda row: (row["ticker"], row["original_version"]))
    result["distinct_reasoning_cases"] = len(result["cases"])
    result["recorded_method_cases"] = sum(row["method_recorded"] for row in result["cases"])
    result["prospective_method_cases"] = sum(row["prospective_method_recorded"] for row in result["cases"])
    for field in ("price_conditions_assessed", "loss_paths_assessed", "falsifiable_difference"):
        result[field + "_cases"] = sum(row["method_features"][field] for row in result["cases"])
    result["retrospective_cases"] = sum(bool(row["retrospective_review_id"]) for row in result["cases"])
    result["business_evidence_cases"] = sum(row["business_outcome"]["status"] != "not_yet_observable" for row in result["cases"])
    result["price_observed_cases"] = sum(row["price_observations"]["status"] == "observed_price_path" for row in result["cases"])
    exposure_members: dict[str, list[dict[str, str]]] = {}
    with_exposures = 0
    for ticker in sorted(set(latest) | held):
        row = latest.get(ticker, {})
        method = row.get("research_method") if row.get("review_id") in verified else None
        missing = []
        if not method:
            missing.append("current_research_method_not_recorded_or_unverified")
        else:
            # Unknown external consensus is valid disclosure, not mandatory work
            # when the analyst can compare a thesis against price conditions.
            for field in ("price_implied_conditions", "differentiated_view", "loss_analysis"):
                if method.get(field, {}).get("status") == "unknown":
                    missing.append(field + "_unknown")
        if missing:
            waiting = (method or {}).get("waiting_for", {})
            result["adoption_queue"].append({"ticker": ticker, "priority": "held" if ticker in held else "research",
                "reason": "; ".join(missing), "next_evidence": waiting.get("next_evidence") or waiting.get("condition")
                or "; ".join(row.get("unresolved_questions", [])[:2]) or "Record the next source-bound discriminating evidence in the existing company review."})
        drivers = (method or {}).get("loss_analysis", {}).get("shared_exposures", [])
        if drivers:
            with_exposures += 1
        for driver in drivers:
            exposure_members.setdefault(driver["risk_tag"], []).append({"ticker": ticker, "mechanism": driver["mechanism"],
                "position_scope": "held" if ticker in held else "research_only"})
    result["adoption_queue"].sort(key=lambda row: (row["priority"] != "held", row["ticker"]))
    result["shared_exposures"] = [{"driver": driver, "tickers": sorted({row["ticker"] for row in members}),
        "held_tickers": sorted(row["ticker"] for row in members if row["position_scope"] == "held"),
        "mechanisms": members, "basis": "authored_qualitative_exposure"}
        for driver, members in sorted(exposure_members.items()) if len({row["ticker"] for row in members}) > 1]
    result["shared_exposure_coverage"] = "partial" if with_exposures else "unknown"
    result["status"] = "partial_evidence" if invalid else "available"
    return result


def validate_performance_record(record: dict[str, Any]) -> None:
    for key in ("record_id", "kind", "source_reference", "source_sha256", "confirmed_by", "confirmed_at"):
        if not str(record.get(key, "")).strip():
            raise ValueError(f"missing {key}")
    aware(record["confirmed_at"])
    digest = str(record["source_sha256"])
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("source_sha256 must be a SHA-256 digest")
    if record.get("currency") != "USD":
        raise ValueError("only explicit USD records are supported")
    if record["kind"] == "nav":
        if aware(record["observed_at"]) > aware(record["confirmed_at"]):
            raise ValueError("NAV observation cannot postdate its confirmation")
        if record.get("cash_basis") != "broker_observed_actual" or record.get("complete_account") is not True:
            raise ValueError("NAV requires complete actual broker account; planning cash is prohibited")
        nav, cash, securities = (finite(record[key]) for key in ("nav", "actual_cash", "securities_value"))
        if nav <= 0 or abs(nav - cash - securities) > .011:
            raise ValueError("NAV must reconcile actual cash plus securities")
        if record.get("valuation_basis") not in {"broker_intraday", "broker_close"}:
            raise ValueError("explicit broker valuation basis required")
    elif record["kind"] == "external_flow":
        if aware(record["occurred_at"]) > aware(record["confirmed_at"]):
            raise ValueError("flow cannot postdate its confirmation")
        if not record.get("transaction_id"):
            raise ValueError("broker/source transaction_id required to prevent duplicate flows")
        if record.get("flow_type") not in {"deposit", "withdrawal"}:
            raise ValueError("internal sweeps, trades, dividends and fees are not external flows")
        amount = finite(record["amount"])
        if amount == 0 or (amount > 0) != (record["flow_type"] == "deposit"):
            raise ValueError("deposit must be positive; withdrawal negative")
        if record.get("status") != "posted_confirmed":
            raise ValueError("unconfirmed flows are not performance evidence")
    elif record["kind"] == "interval_review":
        for key in ("start_nav_id", "end_nav_id"):
            if not record.get(key):
                raise ValueError(f"missing {key}")
        if not isinstance(record.get("external_flow_ids"), list):
            raise ValueError("explicit exhaustive external_flow_ids required, including [] for none")
        for key in ("cash_flow_history_complete", "holdings_history_reconciled", "fees_income_corporate_actions_reconciled"):
            if not isinstance(record.get(key), bool):
                raise ValueError(f"explicit {key} confirmation required")
    else:
        raise ValueError("unsupported performance record kind")


def load_performance_records(path: Path = PERFORMANCE_PATH) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    previous = ""
    ids = set()
    for row in rows:
        expected = canonical_sha256({key: value for key, value in row.items() if key != "entry_sha256"})
        if row.get("previous_entry_sha256") != previous or row.get("entry_sha256") != expected:
            raise ValueError("performance ledger chain is invalid")
        if row.get("record_id") in ids:
            raise ValueError("duplicate performance record ID")
        validate_performance_record(row)
        ids.add(row["record_id"])
        previous = row["entry_sha256"]
    return rows


def record_performance(record: dict[str, Any], *, path: Path = PERFORMANCE_PATH, apply: bool = False) -> dict[str, Any]:
    """Preview by default; immutable same-ID replays deduplicate, conflicts fail."""
    forbidden = {"entry_sha256", "previous_entry_sha256", "recorded_at"} & set(record)
    if forbidden:
        raise ValueError("ledger chain fields are system assigned")
    validate_performance_record(record)
    with ExclusiveFileLock(path.with_suffix(".lock")):
        rows = load_performance_records(path)
        for row in rows:
            if row["record_id"] == record["record_id"]:
                original = {k: v for k, v in row.items() if k not in {"entry_sha256", "previous_entry_sha256", "recorded_at"}}
                if original != record:
                    raise ValueError("record ID already exists with different facts; append an explicit correction")
                return {"status": "already_recorded", "record_id": record["record_id"]}
        if record.get("supersedes_record_id"):
            target = next((row for row in rows if row["record_id"] == record["supersedes_record_id"]), None)
            superseded = {row.get("supersedes_record_id") for row in rows}
            if not target or target["kind"] != record["kind"] or target["record_id"] in superseded:
                raise ValueError("correction must supersede a current record of the same kind")
        current_rows = [row for row in rows if row["record_id"] not in {r.get("supersedes_record_id") for r in rows}]
        identity_fields = {"nav": ("observed_at",), "external_flow": ("transaction_id",),
                           "interval_review": ("start_nav_id", "end_nav_id")}[record["kind"]]
        for row in current_rows:
            if (row["kind"] == record["kind"] and all(row.get(k) == record.get(k) for k in identity_fields)
                    and record.get("supersedes_record_id") != row["record_id"]):
                raise ValueError("duplicate economic observation; reuse record ID or append explicit correction")
        entry = {**record, "recorded_at": iso_now(), "previous_entry_sha256": rows[-1]["entry_sha256"] if rows else ""}
        entry["entry_sha256"] = canonical_sha256(entry)
        if apply:
            append_record(path, entry)
        return {"status": "recorded" if apply else "preview_only", "record_id": record["record_id"],
                "entry_sha256": entry["entry_sha256"], "performance_ready": False}


def performance_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    for row in records:
        validate_performance_record(row)
    superseded = {row.get("supersedes_record_id") for row in records}
    active = {row["record_id"]: row for row in records if row["record_id"] not in superseded}
    navs = sorted((r for r in active.values() if r["kind"] == "nav"), key=lambda r: aware(r["observed_at"]))
    flows = [r for r in active.values() if r["kind"] == "external_flow"]
    intervals = []
    for review in active.values():
        if review["kind"] != "interval_review":
            continue
        reasons = []
        start, end = active.get(review["start_nav_id"]), active.get(review["end_nav_id"])
        if not start or not end or start["kind"] != "nav" or end["kind"] != "nav":
            reasons.append("missing_or_superseded_nav")
        for key in ("cash_flow_history_complete", "holdings_history_reconciled", "fees_income_corporate_actions_reconciled"):
            if review.get(key) is not True:
                reasons.append(key)
        result = {"review_id": review["record_id"], "start_nav_id": review["start_nav_id"], "end_nav_id": review["end_nav_id"],
                  "status": "blocked", "return_pct": None, "benchmark_relative_return_pct": None,
                  "method": "Modified Dietz cash-flow-adjusted approximation, net of charges included in broker NAV", "blockers": reasons}
        if start and end and start["kind"] == "nav" and end["kind"] == "nav":
            begin, finish = aware(start["observed_at"]), aware(end["observed_at"])
            if finish <= begin:
                reasons.append("nonpositive_interval")
            if aware(review["confirmed_at"]) < finish:
                reasons.append("interval_review_predates_end_observation")
            if start["valuation_basis"] != end["valuation_basis"]:
                reasons.append("inconsistent_nav_basis")
            interval_flows = [r for r in flows if begin < aware(r["occurred_at"]) <= finish]
            flow_ids = [r["record_id"] for r in interval_flows]
            declared = review["external_flow_ids"]
            if len(declared) != len(set(declared)) or set(flow_ids) != set(declared):
                reasons.append("external_flow_list_not_reconciled")
            if not reasons:
                seconds = (finish - begin).total_seconds()
                weighted = sum(finite(r["amount"]) * (finish - aware(r["occurred_at"])).total_seconds() / seconds for r in interval_flows)
                denominator = finite(start["nav"]) + weighted
                if denominator <= 0:
                    reasons.append("nonpositive_weighted_capital")
                else:
                    total_flow = sum(finite(r["amount"]) for r in interval_flows)
                    value = (finite(end["nav"]) - finite(start["nav"]) - total_flow) / denominator * 100
                    result.update(status="ready_interval_only", return_pct=round(value, 6), net_external_flows=total_flow,
                                  start_at=begin.isoformat(), end_at=finish.isoformat())
                    # Benchmarks must be actual observed total-return indices at the exact NAV timestamps.
                    a, b = start.get("benchmark", {}), end.get("benchmark", {})
                    if (a.get("ticker") and a.get("ticker") == b.get("ticker") and a.get("basis") == b.get("basis") == "total_return_index"
                            and a.get("observed_at") == start["observed_at"] and b.get("observed_at") == end["observed_at"]
                            and a.get("source_reference") and b.get("source_reference")
                            and finite(a.get("value", 0)) > 0 and finite(b.get("value", 0)) > 0):
                        benchmark_return = (finite(b["value"]) / finite(a["value"]) - 1) * 100
                        result.update(benchmark_ticker=a["ticker"], benchmark_return_pct=round(benchmark_return, 6),
                                      benchmark_relative_return_pct=round(value - benchmark_return, 6))
        intervals.append(result)
    ready = [r for r in intervals if r["status"] == "ready_interval_only"]
    blockers = []
    if len(navs) < 2:
        blockers.append("at_least_two_confirmed_actual_nav_observations_required")
    if not intervals:
        blockers.append("complete_interval_history_review_required")
    if intervals and not ready:
        blockers.append("all_intervals_have_unresolved_history_or_basis")
    return {"status": "interval_results_available" if ready else "not_ready", "actual_nav_observations": len(navs),
            "confirmed_external_flows": len(flows), "latest_actual_nav": navs[-1] if navs else None,
            "ready_intervals": len(ready), "intervals": intervals, "blockers": blockers,
            "portfolio_lifetime_return_pct": None,
            "limitations": ["Planning cash and unconfirmed fills are never performance inputs.",
                            "Confirmed NAV alone does not prove complete flow, fee, income, or corporate-action history.",
                            "Modified Dietz is an approximation; intervals are not automatically chain-linked or treated as lifetime returns.",
                            "Benchmark comparison requires matching observation timestamps and a sourced total-return index."]}
