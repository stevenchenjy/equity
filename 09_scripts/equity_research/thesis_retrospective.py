"""Thesis-bound learning inside the maintained company-review ledger.

The original review is immutable. A later review can assess its process and
later business evidence; close-price paths remain a separate observation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from daily_common import canonical_sha256

SCHEMA = "thesis_retrospective_v1"
PROCESS_STATES = {"process_supported", "process_gap", "unresolved"}
BUSINESS_STATES = {"supported", "mixed", "challenged", "not_yet_observable"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("retrospective_" + message)


def _stamp(value: Any) -> datetime:
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    _require(stamp.tzinfo is not None and stamp.utcoffset() is not None, "timestamp_requires_timezone")
    return stamp


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def original_reasoning_time(record: dict[str, Any]) -> datetime:
    """An annotation cannot become prospective before it was actually authored."""
    reviewed = _stamp(record["reviewed_at"])
    method = record.get("research_method")
    authored = method.get("authored_at") if isinstance(method, dict) else None
    return max(reviewed, _stamp(authored)) if authored else reviewed


def method_features(record: dict[str, Any]) -> dict[str, bool]:
    """Useful authored coverage, never a decision score or investment authority."""
    method = record.get("research_method") if isinstance(record.get("research_method"), dict) else {}
    difference = method.get("differentiated_view", {})
    return {"price_conditions_assessed": method.get("price_implied_conditions", {}).get("status") == "assessed",
            "loss_paths_assessed": method.get("loss_analysis", {}).get("status") == "assessed",
            "falsifiable_difference": difference.get("status") == "hypothesis" and _text(difference.get("falsifier"))}


def retrospective_template(original: dict[str, Any]) -> dict[str, Any]:
    """Unassessed starting point for a new version; never edits the original."""
    return {"schema_version": SCHEMA, "original_review_id": original["review_id"],
            "original_record_sha256": original["record_sha256"],
            "decision_process": {"assessment": "unresolved",
                "rationale": "Assess only the assumptions, counterevidence and loss paths recorded in this original review."},
            "business_outcome": {"status": "not_yet_observable", "claim_ids": [],
                "assessment": "Name the next discriminating evidence; later observed business facts are not yet recorded."},
            "lesson": "Record one change to the next research decision, or explain why the evidence remains insufficient."}


def validate_retrospective(record: dict[str, Any], prior_records: list[dict[str, Any]]) -> None:
    if "retrospective" not in record:
        return
    item = record["retrospective"]
    fields = {"schema_version", "original_review_id", "original_record_sha256", "decision_process", "business_outcome", "lesson"}
    _require(isinstance(item, dict) and set(item) == fields and item["schema_version"] == SCHEMA, "fields_invalid")
    original = next((row for row in prior_records if row.get("review_id") == item["original_review_id"]), None)
    _require(original is not None and original.get("record_sha256") == item["original_record_sha256"], "original_identity_or_hash_missing")
    _require(original["ticker"] == record["ticker"] and original["version"] < record["version"]
             and original_reasoning_time(original) < _stamp(record["reviewed_at"]), "original_must_be_earlier_same_ticker")
    process = item["decision_process"]
    _require(isinstance(process, dict) and set(process) == {"assessment", "rationale"}
             and process["assessment"] in PROCESS_STATES and _text(process["rationale"]), "decision_process_invalid")
    # Adding a method today cannot establish what was reasoned before outcomes.
    if not original.get("research_method"):
        _require(process["assessment"] == "unresolved", "legacy_process_cannot_be_reconstructed")
    if process["assessment"] == "process_supported":
        _require(all(method_features(original).values()), "supported_process_needs_substantive_original_method")
    outcome = item["business_outcome"]
    _require(isinstance(outcome, dict) and set(outcome) == {"status", "assessment", "claim_ids"}
             and outcome["status"] in BUSINESS_STATES and _text(outcome["assessment"]), "business_outcome_invalid")
    ids = outcome["claim_ids"]
    claims = {row["claim_id"]: row for row in record["claims"]}
    sources = {row["source_id"]: row for row in record["sources"]}
    _require(isinstance(ids, list) and all(isinstance(key, str) and key in claims for key in ids)
             and len(ids) == len(set(ids)), "outcome_claims_invalid")
    if outcome["status"] != "not_yet_observable":
        _require(bool(ids), "observed_business_outcome_needs_facts")
        for key in ids:
            claim = claims[key]
            _require(claim["kind"] == "reported_fact", "outcome_cannot_be_inference_only")
            _require(any(citation.get("source_id") in sources
                         and original_reasoning_time(original) < _stamp(sources[citation["source_id"]]["published_at"])
                         <= _stamp(record["reviewed_at"]) for citation in claim["citations"]),
                     "outcome_needs_evidence_published_after_original")
    _require(_text(item["lesson"]), "lesson_missing")


def reasoning_fingerprint(record: dict[str, Any]) -> str:
    """Exclude version/date restamps while preserving authored argument changes."""
    keys = ("ticker", "financial_period_end", "research_method", "claims", "business_case",
            "per_share_economics", "valuation", "portfolio_role_and_alternatives", "conclusion",
            "invalidation_conditions", "unresolved_questions", "valuation_model")
    semantic = {key: record.get(key) for key in keys}
    if isinstance(semantic["research_method"], dict):
        semantic["research_method"] = {key: value for key, value in semantic["research_method"].items() if key != "authored_at"}
    return canonical_sha256(semantic)


def price_observations(original: dict[str, Any], snapshots: list[dict[str, Any]],
                       outcomes: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any]:
    """Use the first exact-version snapshot; never borrow a later thesis path."""
    from investment_plans import regular_close
    import math

    eligible = []
    for row in snapshots:
        if (row.get("ticker") != original["ticker"] or row.get("thesis_id") != "company_thesis:" + original["ticker"]
                or str(row.get("thesis_version")) != str(original["version"]) or not row.get("snapshot_id")):
            continue
        try:
            if original_reasoning_time(original) <= _stamp(row.get("created_at")) <= cutoff:
                eligible.append(row)
        except (ValueError, TypeError):
            continue
    if not eligible:
        return {"status": "no_original_version_snapshot", "snapshot_id": None, "horizons": []}
    selected = min(eligible, key=lambda row: (_stamp(row["created_at"]), str(row["snapshot_id"])))
    observed = {}
    for row in outcomes:
        if row.get("snapshot_id") != selected["snapshot_id"]:
            continue
        if (row.get("ticker") != original["ticker"] or row.get("thesis_id") != selected["thesis_id"]
                or str(row.get("thesis_version")) != str(original["version"])):
            continue
        try:
            horizon = int(row["horizon_sessions"])
            origin = row.get("forecast_origin_session") or row.get("recommendation_session")
            entry_at, evaluation_at = regular_close(origin), regular_close(row["evaluation_session"])
            if (horizon not in {1, 5, 20, 60} or evaluation_at > cutoff
                    or not max(original_reasoning_time(original), _stamp(selected["created_at"])) <= entry_at < evaluation_at):
                continue
            entry, end, change = (float(row[key]) for key in ("entry_close", "evaluation_close", "absolute_return_pct"))
            if (not all(math.isfinite(value) for value in (entry, end, change)) or min(entry, end) <= 0
                    or abs(change - (end / entry - 1) * 100) > 0.011):
                continue
            if not str(row.get("evaluation_basis", "")).startswith("forward_next_session_close_v2"):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        candidate = {key: row.get(key) for key in ("horizon_sessions", "evaluation_session", "absolute_return_pct",
            "spy_relative_return_pct", "qqq_relative_return_pct", "price_basis", "corporate_action_review_required")}
        # Conflicting duplicate source rows cannot silently choose a result.
        observed[horizon] = candidate if horizon not in observed else (candidate if observed[horizon] == candidate else None)
    rows = [observed[key] for key in sorted(observed) if observed[key] is not None]
    return {"status": "observed_price_path" if rows else "pending_forward_price_path", "snapshot_id": selected["snapshot_id"],
            "horizons": rows, "basis": "original_version_first_snapshot; close_price_path_not_execution_or_causal_attribution"}
