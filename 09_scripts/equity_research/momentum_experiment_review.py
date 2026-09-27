"""Prepare an early manual-review packet without changing the frozen experiment."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path

from daily_common import (BASIC_EOD_PUBLICATION_TIME, ET, ExclusiveFileLock,
    atomic_write_json, atomic_write_text, canonical_sha256, latest_published_market_session)
import momentum_experiment as experiment
from workflow_evaluation import aware

POLICY = Path("01_policies/momentum_experiment_review.json")
OUTPUT = Path("08_reviews/momentum_experiment_review.local")
SCHEMA = "equity_momentum_manual_review_v1"
PRICE_PATH_STATUS = "matured_price_path_study"


class ReviewError(ValueError):
    """Finite operational reason, suitable for a local status artifact."""


def validate_review_policy(policy):
    if (policy.get("schema_version") != "equity_momentum_manual_review_policy_v1"
            or not isinstance(policy.get("version"), str) or not policy["version"]
            or policy.get("review_trigger") != "first_complete_five_session_cohort"
            or type(policy.get("minimum_complete_cohorts")) is not int
            or policy["minimum_complete_cohorts"] != 1
            or type(policy.get("required_holding_sessions")) is not int
            or policy["required_holding_sessions"] != 5
            or policy.get("owner_review_required") is not True
            or any(policy.get(field) is not False for field in (
                "automatic_promotion", "changes_canonical_eligibility", "automatic_action_allowed"))):
        raise ReviewError("review_policy_invalid")


def _validate_matured_outcome(outcome, observation):
    """Check recorded evidence/schema; never re-run an older trading model."""
    costs = {str(value) for value in observation["policy"]["one_way_cost_bps"]}

    def returns_grid(values):
        if not isinstance(values, dict) or set(values) != costs:
            raise ValueError("cost_grid")
        for value in values.values():
            experiment.number(value)

    try:
        returns_grid(outcome.get("all_covered_net_path_pct_by_one_way_bps"))
        for bar in outcome["forward_bars"]:
            values = {name: experiment.number(bar[name]) for name in ("open", "high", "low", "close")}
            if (min(values.values()) <= 0 or experiment.number(bar["volume"]) < 0
                    or not values["low"] <= min(values["open"], values["close"])
                    <= max(values["open"], values["close"]) <= values["high"]):
                raise ValueError("bars")
        models = outcome.get("models")
        if not isinstance(models, dict) or set(models) != set(experiment.COHORTS):
            raise ValueError("models")
        for name in experiment.COHORTS:
            model = models[name]
            status = model.get("status")
            if not observation["cohorts"][name]:
                if status != "not_selected":
                    raise ValueError("selection")
            elif name in {"existing_canonical", "existing_tactical"}:
                expected = "unmodeled_strategy_entry_required" if name == "existing_canonical" else "unmodeled_intraday_entry_required"
                if status != expected or model.get("actual_fill") is not False:
                    raise ValueError("baseline_model")
            elif status == "modeled":
                returns_grid(model.get("net_return_pct_by_one_way_bps"))
                prices = {key: experiment.number(model[key]) for key in ("entry", "exit", "stop", "target")}
                if (min(prices.values()) <= 0 or not prices["stop"] < prices["entry"] < prices["target"]
                        or model.get("actual_fill") is not False
                        or model.get("reason") not in {"stop_or_gap_loss", "hypothetical_profit_reference", "five_session_time_exit"}
                        or model.get("exit_session") not in {bar["session_date"] for bar in outcome["forward_bars"]}):
                    raise ValueError("execution_model")
            elif status != "expired_unfilled_or_gap_skipped":
                raise ValueError("selected_model")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ReviewError("review_recorded_outcome_evidence_invalid") from exc


def _cohort(observations, outcomes):
    first = observations[0]
    policy = first["policy"]
    entry = date.fromisoformat(first["earliest_modeled_entry_session"])
    sessions = [entry.isoformat(), *experiment.sessions_after(entry, policy["holding_sessions"] - 1)]
    publication = datetime.combine(date.fromisoformat(sessions[-1]) + timedelta(days=1),
                                   BASIC_EOD_PUBLICATION_TIME, tzinfo=ET)
    matched = [outcomes[row["observation_id"]] for row in observations if row["observation_id"] in outcomes]
    matured = [row for row in matched if row["status"] == PRICE_PATH_STATUS]
    corrections = [row for row in matched if row["status"] != PRICE_PATH_STATUS]
    missing = [row for row in observations if row["observation_id"] not in outcomes]
    for outcome in matured:
        observation = next(row for row in observations if row["observation_id"] == outcome["observation_id"])
        if (outcome.get("evaluation_inputs", {}).get("implementation_sha256")
                != observation["inputs"].get("implementation_sha256")):
            raise ReviewError("review_outcome_implementation_mismatch")
        if latest_published_market_session(aware(outcome["recorded_at"])) < date.fromisoformat(sessions[-1]):
            raise ReviewError("review_outcome_precedes_data_publication")
    summary = experiment.summarize([*observations, *matched])
    comparison = summary["comparison_by_version"][first["experiment_version"]]
    selected = comparison["cohorts"]["breakout_with_volume"]
    cohort_id = canonical_sha256({"experiment_version": first["experiment_version"],
        "signal_session": first["signal_session"], "entry_session": entry.isoformat(),
        "policy_sha256": first["policy_sha256"]})
    return {
        "cohort_id": cohort_id, "experiment_version": first["experiment_version"],
        "policy_sha256": first["policy_sha256"],
        "implementation_sha256": first["inputs"]["implementation_sha256"],
        "signal_session": first["signal_session"], "earliest_model_entry_session": entry.isoformat(),
        "earliest_complete_session": sessions[-1], "modeled_sessions": sessions,
        "earliest_publication_at": publication.isoformat(),
        "observations": len(observations), "matured_price_paths": len(matured),
        "pending_or_missing_outcomes": len(missing), "correction_required_outcomes": len(corrections),
        "complete": bool(observations) and len(matured) == len(observations),
        "selected_strategy_evidence_status": (
            "no_selected_breakout_with_volume_observations" if not selected["selected"]
            else "selection_price_paths_only_execution_and_incremental_value_unvalidated"),
        "baseline_comparison_status": (
            "frozen_baseline_selection_available" if any(comparison["cohorts"][name]["selected"]
                for name in ("existing_canonical", "existing_tactical"))
            else "no_frozen_eligible_baseline_in_this_cohort"),
        "comparison": comparison, "missed_positive_paths": summary["missed_positive_paths"],
        "skipped_or_unverified_observations": summary["skipped_or_unverified"],
        "observation_refs": [{"ticker": row["ticker"], "observation_id": row["observation_id"],
            "observation_record_hash": row["record_hash"], "first_observed_at": row["recorded_at"],
            "coverage_errors": row["coverage_errors"], "cohorts": row["cohorts"],
            "outcome_status": outcomes.get(row["observation_id"], {}).get("status", "pending_or_missing"),
            "outcome_record_hash": outcomes.get(row["observation_id"], {}).get("record_hash", ""),
            "modeled_execution": outcomes.get(row["observation_id"], {}).get("models", {}),
            "all_covered_net_path_pct_by_one_way_bps": outcomes.get(row["observation_id"], {}).get("all_covered_net_path_pct_by_one_way_bps", {}),
        } for row in sorted(observations, key=lambda row: row["ticker"])],
    }


def build_review(*, policy, frozen_policy, records, experiment_report, experiment_status,
                 ledger_sha256, current, input_hashes):
    validate_review_policy(policy)
    try:
        experiment.validate_policy(frozen_policy)
        versions = experiment.validate_chain(records, current)
    except (ValueError, TypeError, KeyError) as exc:
        raise ReviewError("review_experiment_ledger_invalid") from exc
    observations_by_id = {row["observation_id"]: row for row in records if row["kind"] == "observation"}
    for row in records:
        if row["kind"] != "outcome":
            continue
        if row.get("status") not in {PRICE_PATH_STATUS, "corporate_action_or_correction_review_required"}:
            raise ReviewError("review_recorded_outcome_status_invalid")
        if row["status"] == PRICE_PATH_STATUS:
            _validate_matured_outcome(row, observations_by_id[row["observation_id"]])
    summary = experiment.summarize(records)
    version = frozen_policy["version"]
    if versions.get(version, canonical_sha256(frozen_policy)) != canonical_sha256(frozen_policy):
        raise ReviewError("review_frozen_policy_mismatch")
    if (experiment_report.get("software_run") != "passed"
            or experiment_report.get("status") != "experimental"
            or experiment_status.get("status") != "experimental"
            or experiment_status.get("generated_at") != experiment_report.get("generated_at")
            or experiment_status.get("run_attempt_id") != experiment_report.get("run_attempt_id")
            or experiment_report.get("policy_version") != version
            or experiment_report.get("automatic_action_allowed") is not False):
        raise ReviewError("review_experiment_not_successful")
    if (experiment_report.get("ledger_sha256") != ledger_sha256
            or experiment_report.get("summary") != summary
            or aware(experiment_report["generated_at"]) > current
            or any(aware(row["recorded_at"]) > aware(experiment_report["generated_at"]) for row in records)):
        raise ReviewError("review_experiment_report_mismatch")
    expected_session = latest_published_market_session(current).isoformat()
    if (aware(experiment_report["generated_at"]).astimezone(ET).date() != current.astimezone(ET).date()
            or experiment_report.get("market_session") != expected_session
            or experiment_status.get("market_session") != expected_session):
        raise ReviewError("review_experiment_report_stale")
    observations = [row for row in records if row["kind"] == "observation"]
    outcomes = {row["observation_id"]: row for row in records if row["kind"] == "outcome"}
    implementations = {}
    groups = {}
    for row in observations:
        digest = row.get("inputs", {}).get("implementation_sha256")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or implementations.get(row["experiment_version"], digest) != digest):
            raise ReviewError("review_experiment_implementation_mismatch")
        implementations[row["experiment_version"]] = digest
        key = (row["experiment_version"], row["signal_session"], row["earliest_modeled_entry_session"])
        groups.setdefault(key, []).append(row)
    cohorts = [_cohort(rows, outcomes) for _, rows in sorted(groups.items())]
    active = [row for row in cohorts if row["experiment_version"] == version]
    complete = [row for row in active if row["complete"]]
    first = min(complete or active, key=lambda row: (row["earliest_complete_session"], row["signal_session"])) if active else {}
    ready = bool(complete)
    # This stable key identifies the first complete review even as later cohorts
    # arrive. It is never a promotion, recommendation or delivery identifier.
    review_key = canonical_sha256({"review_policy": policy, "experiment_version": version,
        "cohort_id": first.get("cohort_id"), "complete": ready,
        "record_refs": first.get("observation_refs", [])})
    return {"schema_version": SCHEMA, "generated_at": current.isoformat(),
        "status": "ready_for_owner_review" if ready else "waiting_for_complete_cohort",
        "market_session": experiment_report.get("market_session", ""),
        "active_experiment_version": version, "review_policy": policy,
        "review_policy_sha256": canonical_sha256(policy), "review_key": review_key,
        "ready_for_owner_review": ready, "complete_cohorts": len(complete),
        "active_cohorts": len(active), "cohorts_by_version": dict(Counter(row["experiment_version"] for row in cohorts)),
        "first_review_cohort_id": first.get("cohort_id", ""),
        "earliest_model_entry_session": first.get("earliest_model_entry_session", ""),
        "earliest_complete_session": first.get("earliest_complete_session", ""),
        "earliest_publication_at": first.get("earliest_publication_at", ""),
        "cohorts": cohorts, "source_hashes": input_hashes, "ledger_sha256": ledger_sha256,
        "experiment_report_generated_at": experiment_report["generated_at"],
        "source_ledger": str(experiment.OUTPUT / "ledger.jsonl"),
        "scope": "manual_review_of_frozen_five_session_price_paths_not_strategy_validation_or_trade_authority",
        "limitations": ["One complete time cohort is the owner's review-timing preference, not evidence of a profitable edge.",
            "Ticker observations within a cohort are correlated; versions and different entry windows are reported separately.",
            "Selection comparisons use identical open-to-fifth-close price paths, not original strategy fills or portfolio returns.",
            "Live quotes, spreads, halts, settled funds, current orders and response latency remain independently unverified.",
            "A cohort with no selected breakout-plus-volume observations provides no selected-strategy result.",
            "Missing, delisted, incomplete or correction-required observations remain visible and prevent that cohort counting as complete."],
        "owner_review_required": True, "incremental_value_established": False,
        "automatic_promotion": False, "changes_canonical_eligibility": False,
        "automatic_action_allowed": False, "email_sent": False, "trade_placed": False}


def markdown(report):
    lines = ["# First complete momentum cohort: manual review", "",
        f"Status: **{report['status']}** · active version: `{report['active_experiment_version']}`.",
        f"Generated: {report['generated_at']}. Complete active cohorts: {report['complete_cohorts']}.", "",
        "This packet opens an owner review. It does not establish profitability or change recommendation eligibility, risk limits or execution authority.", "",
        f"Earliest modeled entry: {report['earliest_model_entry_session'] or 'not yet observed'}; fifth session: {report['earliest_complete_session'] or 'unavailable'}; earliest provider publication boundary: {report['earliest_publication_at'] or 'unavailable'}.",
        "The publication boundary is conditional on complete validated data and a successful scheduled refresh.", ""]
    for cohort in report["cohorts"]:
        lines.extend([f"## {cohort['experiment_version']} · signal {cohort['signal_session']} · entry {cohort['earliest_model_entry_session']}", "",
            f"Complete: {cohort['complete']}. Frozen observations: {cohort['observations']}; matured: {cohort['matured_price_paths']}; pending/missing: {cohort['pending_or_missing_outcomes']}; correction review: {cohort['correction_required_outcomes']}.",
            f"Selected-strategy evidence: `{cohort['selected_strategy_evidence_status']}`. Baseline: `{cohort['baseline_comparison_status']}`.",
            f"Unselected positive common paths: {cohort['missed_positive_paths']}; skipped/unverified observations: {cohort['skipped_or_unverified_observations']}.", "",
            "| Selection | Selected | Matured | Losing at highest cost | Net mean by per-side cost | Execution outcomes |",
            "|---|---:|---:|---:|---|---|"])
        for name, row in cohort["comparison"]["cohorts"].items():
            means = "; ".join(f"{cost} bps: {value:+.2f}%" for cost, value in row["common_path_net_mean_pct_by_one_way_bps"].items()) or "unavailable"
            execution = "; ".join(f"{key}: {value}" for key, value in row["execution_status_counts"].items()) or "none observed"
            lines.append(f"| {name} | {row['selected']} | {row['matured_common_paths']} | {row['losing_common_paths_at_highest_cost']} | {means} | {execution} |")
    lines.extend(["", "## Evidence limits", "", *[f"- {value}" for value in report["limitations"]], "",
        f"Frozen ledger SHA-256: `{report['ledger_sha256']}`. The JSON packet includes every observation/outcome reference and source hash."])
    return "\n".join(lines) + "\n"


def run(root: Path, current: datetime, output: Path | None = None):
    output = output or root / OUTPUT
    if output.resolve() == (root / experiment.OUTPUT).resolve():
        raise ReviewError("review_output_conflicts_with_frozen_experiment")
    source_paths = [POLICY, experiment.POLICY, experiment.OUTPUT / "ledger.jsonl",
                    experiment.OUTPUT / "report.json", experiment.OUTPUT / "status.json"]
    with ExclusiveFileLock(output / "run.lock"):
        originals = {path: (root / path).read_bytes() for path in source_paths}
        hashes = {str(path): hashlib.sha256(data).hexdigest() for path, data in originals.items()}
        ledger_path = experiment.OUTPUT / "ledger.jsonl"
        report = build_review(policy=json.loads(originals[POLICY]), frozen_policy=json.loads(originals[experiment.POLICY]),
            records=[json.loads(line) for line in originals[ledger_path].splitlines() if line.strip()],
            experiment_report=json.loads(originals[experiment.OUTPUT / "report.json"]),
            experiment_status=json.loads(originals[experiment.OUTPUT / "status.json"]),
            ledger_sha256=hashes[str(ledger_path)], current=current, input_hashes=hashes)
        if any((root / path).read_bytes() != value for path, value in originals.items()):
            raise ReviewError("review_inputs_changed_during_read")
        atomic_write_json(output / "report.json", report)
        atomic_write_text(output / "report.md", markdown(report))
        status_fields = ("schema_version", "generated_at", "status", "market_session", "active_experiment_version",
            "review_key", "complete_cohorts", "ready_for_owner_review", "earliest_model_entry_session",
            "earliest_complete_session", "earliest_publication_at", "automatic_action_allowed",
            "incremental_value_established", "automatic_promotion", "changes_canonical_eligibility")
        atomic_write_json(output / "status.json", {key: report[key] for key in status_fields})
        return report
