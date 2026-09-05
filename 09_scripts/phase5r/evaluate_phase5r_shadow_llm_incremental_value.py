#!/usr/bin/env python3
"""Aggregate autonomous, noncanonical SHADOW_LLM evaluation evidence."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import re
import stat
import sys
from pathlib import Path
from statistics import median
from typing import Any

from phase5r_daily_common import ROOT, canonical_sha256, iso_now
from phase5r_shadow_llm_contract import (
    BUNDLE_SCHEMA_VERSION,
    LEGACY_BUNDLE_SCHEMA_VERSION,
    build_automatic_evaluation,
    build_blind_judge_target,
    deterministic_claim_check,
    load_packet,
)
from run_phase5r_shadow_llm_evaluation import (
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PACKET_ARCHIVE_ROOT,
    LEDGER_PATH,
    load_config,
    semantic_event_fingerprint,
)


DEFAULT_SNAPSHOT_PATH = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_snapshots.local.jsonl"
)
DEFAULT_OUTCOME_PATH = (
    ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_recommendation_outcomes.local.csv"
)
EVALUATION_CLASSES = {"fixture_validation", "replay", "live_shadow"}
TOKEN_USAGE_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
    "total_tokens",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ShadowEvaluationError(ValueError):
    """Evaluation evidence is incomplete, mutable, or out of contract."""


def _read_regular_json(path: Path, *, maximum_bytes: int = 10_000_000) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ShadowEvaluationError(f"symlink input is prohibited: {path.name}")
    target = expanded.resolve()
    try:
        metadata = target.lstat()
    except OSError as exc:
        raise ShadowEvaluationError(f"input is unavailable: {path.name}") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > maximum_bytes
    ):
        raise ShadowEvaluationError(f"input metadata is invalid: {path.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowEvaluationError(f"input is not valid JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise ShadowEvaluationError(f"input must be one JSON object: {path.name}")
    return payload


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _valid_usage(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and all(type(value.get(key)) is int and value[key] >= 0 for key in TOKEN_USAGE_KEYS)
        and value["cached_input_tokens"] <= value["input_tokens"]
        and value["total_tokens"] == value["input_tokens"] + value["output_tokens"]
    )


def _validate_boundaries(boundaries: Any) -> None:
    if boundaries != {
        "research_only": True,
        "production_influence": False,
        "canonical_effect": False,
        "email_eligible": False,
        "email_attempted": False,
        "broker_connected": False,
        "broker_account_read": False,
        "order_code_created": False,
        "trade_placed": False,
        "automatic_action_allowed": False,
    }:
        raise ShadowEvaluationError("bundle production boundary is invalid")


def _validate_bundle(bundle: dict[str, Any], *, packet: dict[str, Any] | None = None) -> None:
    required = {
        "schema_version",
        "run_id",
        "packet_id",
        "cycle_date",
        "completed_at",
        "transport",
        "evaluation_class",
        "evaluation_stage",
        "semantic_event_fingerprint",
        "entity_tickers",
        "primary_source_registry",
        "run_identity",
        "critic_routing",
        "analyst",
        "critic",
        "judge_target",
        "blind_candidate_mapping",
        "judge",
        "provider_metadata",
        "automatic_evaluation",
        "spot_check_recommended",
        "boundaries",
    }
    event_v2_fields = {"semantic_event_version", "issuer_semantic_components", "point_in_time_receipt", "event_scope", "sampling_receipt"}
    if set(bundle) not in (required, required | event_v2_fields) or bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ShadowEvaluationError("bundle fields or schema version are invalid")
    run_id = bundle.get("run_id")
    identity = bundle.get("run_identity")
    if not isinstance(run_id, str) or _SHA256.fullmatch(run_id) is None:
        raise ShadowEvaluationError("bundle run id is invalid")
    if not isinstance(identity, dict) or identity.get("run_id") != run_id:
        raise ShadowEvaluationError("bundle run identity is invalid")
    if canonical_sha256({k: v for k, v in identity.items() if k != "run_id"}) != run_id:
        raise ShadowEvaluationError("bundle run identity hash is invalid")
    if event_v2_fields.issubset(bundle):
        for field in ("semantic_event_version", "issuer_semantic_components"):
            if bundle[field] != identity.get(field):
                raise ShadowEvaluationError(f"bundle {field} identity is invalid")
    for field in (
        "packet_id",
        "cycle_date",
        "transport",
        "evaluation_class",
        "evaluation_stage",
        "semantic_event_fingerprint",
    ):
        if identity.get(field) != bundle.get(field):
            raise ShadowEvaluationError(f"bundle {field} binding is invalid")
    evaluation_class = bundle["evaluation_class"]
    if evaluation_class not in EVALUATION_CLASSES:
        raise ShadowEvaluationError("bundle evaluation class is invalid")
    if (
        evaluation_class == "fixture_validation"
        and bundle["transport"] != "fixture"
    ) or (
        evaluation_class in {"replay", "live_shadow"}
        and bundle["transport"] != "codex_cli_external_auth"
    ):
        raise ShadowEvaluationError("bundle transport cannot support its evaluation class")
    tickers = bundle.get("entity_tickers")
    if (
        not isinstance(tickers, list)
        or not tickers
        or len(tickers) != len(set(tickers))
        or any(not isinstance(ticker, str) or not ticker for ticker in tickers)
    ):
        raise ShadowEvaluationError("bundle entity registry is invalid")
    sources = bundle.get("primary_source_registry")
    if not isinstance(sources, list):
        raise ShadowEvaluationError("bundle primary source registry is invalid")
    source_ids: set[str] = set()
    for row in sources:
        if not isinstance(row, dict) or set(row) != {
            "source_id",
            "ticker",
            "authority",
            "source_type",
        }:
            raise ShadowEvaluationError("bundle primary source registry row is invalid")
        source_id = row.get("source_id")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in source_ids
            or row.get("ticker") not in {"", *tickers}
        ):
            raise ShadowEvaluationError("bundle primary source registry binding is invalid")
        source_ids.add(source_id)
    if type(bundle.get("spot_check_recommended")) is not bool:
        raise ShadowEvaluationError("bundle spot-check flag is invalid")
    _validate_boundaries(bundle.get("boundaries"))
    routing = bundle.get("critic_routing")
    if (
        not isinstance(routing, dict)
        or set(routing) != {"routed", "reasons"}
        or type(routing["routed"]) is not bool
        or not isinstance(routing["reasons"], list)
        or any(not isinstance(reason, str) or not reason for reason in routing["reasons"])
        or routing["routed"] is not (bundle.get("critic") is not None)
    ):
        raise ShadowEvaluationError("bundle critic routing is invalid")
    target = bundle.get("judge_target")
    judge = bundle.get("judge")
    automatic = bundle.get("automatic_evaluation")
    mapping = bundle.get("blind_candidate_mapping")
    if not all(isinstance(value, dict) for value in (target, judge, automatic, mapping)):
        raise ShadowEvaluationError("bundle automatic evaluation objects are invalid")
    candidates = target.get("candidates")
    if (
        not isinstance(candidates, list)
        or target.get("candidate_set_sha256") != canonical_sha256(candidates)
        or judge.get("candidate_set_sha256") != target.get("candidate_set_sha256")
        or automatic.get("candidate_set_sha256") != target.get("candidate_set_sha256")
    ):
        raise ShadowEvaluationError("bundle blind candidate binding is invalid")
    blind_ids = {row.get("blind_item_id") for row in candidates if isinstance(row, dict)}
    reviews = judge.get("item_reviews")
    if (
        len(blind_ids) != len(candidates)
        or not isinstance(reviews, list)
        or {row.get("blind_item_id") for row in reviews if isinstance(row, dict)} != blind_ids
        or set(mapping) != blind_ids
    ):
        raise ShadowEvaluationError("bundle blind candidate coverage is invalid")
    blindness = automatic.get("blindness")
    if blindness != {
        "candidate_origin_hidden_from_judge": True,
        "model_materiality_hidden_from_judge": True,
        "model_novelty_hidden_from_judge": True,
        "critic_verdict_hidden_from_judge": True,
    }:
        raise ShadowEvaluationError("bundle judge blindness record is invalid")
    expected_target, expected_mapping = build_blind_judge_target(
        bundle["analyst"], bundle["critic"],
        packet=packet if any(row.get("origin") == "deterministic_control" for row in mapping.values()) else None,
    )
    if target != expected_target or mapping != expected_mapping:
        raise ShadowEvaluationError("bundle blind target derivation is invalid")
    if automatic != build_automatic_evaluation(
        bundle["analyst"], bundle["critic"], target, mapping, judge,
        schema_version=automatic.get("schema_version", ""),
    ):
        raise ShadowEvaluationError("bundle automatic evaluation binding is invalid")
    for key in (
        "canonical_effect",
        "production_influence",
        "email_eligible",
        "automatic_action_allowed",
    ):
        if automatic.get(key) is not False:
            raise ShadowEvaluationError("automatic evaluation authority boundary is invalid")
    metadata = bundle.get("provider_metadata")
    expected_roles = {"analyst", "judge"} | ({"critic"} if routing["routed"] else set())
    if (
        not isinstance(metadata, list)
        or len(metadata) != len(expected_roles)
        or {row.get("role") for row in metadata if isinstance(row, dict)} != expected_roles
        or any(
            not isinstance(row, dict)
            or row.get("credential_read_by_repository") is not False
            or row.get("tools_enabled") is not False
            or row.get("transport") != bundle["transport"]
            for row in metadata
        )
    ):
        raise ShadowEvaluationError("bundle provider isolation metadata is invalid")
    metadata_by_role = {row["role"]: row for row in metadata}
    outputs = {"analyst": bundle["analyst"], "judge": bundle["judge"]}
    if routing["routed"]:
        outputs["critic"] = bundle["critic"]
    if any(
        metadata_by_role[role].get("output_sha256") != canonical_sha256(output)
        for role, output in outputs.items()
    ):
        raise ShadowEvaluationError("bundle provider output binding is invalid")
    if metadata_by_role["analyst"].get("model") == metadata_by_role["judge"].get("model"):
        raise ShadowEvaluationError("analyst and blind judge must use different models")
    if evaluation_class != "fixture_validation":
        for row in metadata:
            usage = row.get("authoritative_token_usage")
            if not _valid_usage(usage) or row.get("authoritative_billing_cost_usd") is not None:
                raise ShadowEvaluationError("live bundle exact cost accounting is invalid")


def _read_ledger(path: Path = LEDGER_PATH) -> list[dict[str, Any]]:
    target = path.expanduser()
    if not target.exists():
        return []
    if target.is_symlink():
        raise ShadowEvaluationError("shadow call ledger must not be a symlink")
    metadata = target.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ShadowEvaluationError("shadow call ledger metadata is invalid")
    previous = ""
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ShadowEvaluationError("shadow call ledger contains invalid JSON") from exc
        if not isinstance(row, dict):
            raise ShadowEvaluationError("shadow call ledger row is invalid")
        event_hash = row.get("event_sha256")
        unsigned = {key: value for key, value in row.items() if key != "event_sha256"}
        if row.get("previous_event_sha256") != previous or canonical_sha256(unsigned) != event_hash:
            raise ShadowEvaluationError("shadow call ledger hash chain is invalid")
        previous = event_hash
        rows.append(row)
    return rows


def _validate_live_ledger(bundle: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    matching = [row for row in rows if row.get("run_id") == bundle["run_id"]]
    expected_roles = {row["role"] for row in bundle["provider_metadata"]}
    started = [row for row in matching if row.get("event") == "started"]
    completed = [row for row in matching if row.get("event") == "completed"]
    if (
        len(started) != len(expected_roles)
        or len(completed) != len(expected_roles)
        or {row.get("role") for row in started} != expected_roles
        or {row.get("role") for row in completed} != expected_roles
        or any(row.get("event") == "failed" for row in matching)
    ):
        raise ShadowEvaluationError("live bundle lacks one completed call per routed role")
    outputs = {"analyst": bundle["analyst"], "judge": bundle["judge"]}
    if bundle["critic"] is not None:
        outputs["critic"] = bundle["critic"]
    if any(
        row.get("output_sha256") != canonical_sha256(outputs[row["role"]])
        for row in completed
    ):
        raise ShadowEvaluationError("live bundle does not match the call ledger")


def load_automatic_bundle(
    path: Path, *, ledger_rows: list[dict[str, Any]] | None = None,
    packet_archive_root: Path | None = None,
) -> dict[str, Any]:
    bundle = _read_regular_json(path)
    packet = _packet_for_bundle(bundle, packet_archive_root or path.parent.parent.parent / "packets.local")
    if packet is None and bundle.get("evaluation_class") == "fixture_validation":
        packet = _packet_for_bundle(bundle, path.parent.parent / "packets.local")
    _validate_bundle(bundle, packet=packet)
    if bundle["evaluation_class"] != "fixture_validation":
        _validate_live_ledger(
            bundle, _read_ledger() if ledger_rows is None else ledger_rows
        )
    return bundle


def _packet_for_bundle(bundle: dict[str, Any], archive_root: Path) -> dict[str, Any] | None:
    paths = [archive_root / f"{bundle['packet_id']}.json", archive_root / f"{bundle['semantic_event_fingerprint']}.json"]
    path = next((candidate for candidate in paths if candidate.exists()), None)
    if path is None:
        return None
    packet = load_packet(path)
    if packet.get("packet_id") != bundle.get("packet_id"):
        raise ShadowEvaluationError("sealed packet does not match bundle packet identity")
    return packet


def _discover(runs_root: Path, ledger_rows: list[dict[str, Any]], *, packet_archive_root: Path | None = None) -> dict[str, Any]:
    automatic: list[dict[str, Any]] = []
    legacy_run_ids: list[str] = []
    current_failures: list[dict[str, Any]] = []
    commissioning_failures: list[dict[str, Any]] = []
    if not runs_root.exists():
        return {
            "automatic": automatic,
            "legacy_run_ids": legacy_run_ids,
            "current_failures": current_failures,
            "commissioning_failures": commissioning_failures,
        }
    for path in sorted(runs_root.glob("*/bundle.json")):
        raw = _read_regular_json(path)
        if raw.get("schema_version") == BUNDLE_SCHEMA_VERSION:
            automatic.append(load_automatic_bundle(path, ledger_rows=ledger_rows, packet_archive_root=packet_archive_root))
        elif raw.get("schema_version") == LEGACY_BUNDLE_SCHEMA_VERSION:
            run_id = raw.get("run_id")
            if isinstance(run_id, str) and _SHA256.fullmatch(run_id):
                legacy_run_ids.append(run_id)
            else:
                raise ShadowEvaluationError("legacy bundle run id is invalid")
        else:
            raise ShadowEvaluationError("unknown bundle schema version")
    for path in sorted(runs_root.glob("*/failure.json")):
        failure = _read_regular_json(path)
        if failure.get("schema_version") == "phase5r_shadow_failure_v2":
            current_failures.append(failure)
        elif failure.get("schema_version") == "phase5r_shadow_failure_v1":
            commissioning_failures.append(failure)
        else:
            raise ShadowEvaluationError("unknown failure schema version")
    return {
        "automatic": automatic,
        "legacy_run_ids": legacy_run_ids,
        "current_failures": current_failures,
        "commissioning_failures": commissioning_failures,
    }


def _threshold_checks(metrics: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, bool]:
    mapping = {
        "minimum_automatically_judged_events": "automatically_judged_events",
        "minimum_distinct_issuers": "distinct_issuers",
        "minimum_material_reference_issues": "material_reference_issues",
        "minimum_incremental_supported_material_items": "incremental_supported_material_items",
        "minimum_incremental_material_precision": "incremental_material_precision",
        "minimum_material_issue_recall": "estimated_incremental_model_reference_recall",
        "minimum_completed_event_rate": "completed_event_rate",
        "maximum_unsupported_claim_rate": "unsupported_claim_rate",
        "maximum_policy_boundary_violations": "policy_boundary_violations",
    }
    return {
        threshold_name: (
            metrics[metric_name] is not None
            and (
                metrics[metric_name] <= thresholds[threshold_name]
                if threshold_name.startswith("maximum_")
                else metrics[metric_name] >= thresholds[threshold_name]
            )
        )
        for threshold_name, metric_name in mapping.items()
    }


def _authority_checks(metrics: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, bool]:
    mapping = {
        "minimum_replay_packets": "replay_packets",
        "minimum_distinct_issuers": "distinct_issuers",
        "minimum_material_reference_issues": "independent_material_reference_issues",
        "minimum_live_shadow_events": "live_shadow_events",
        "maximum_live_shadow_events_before_review": "live_shadow_events",
        "minimum_incremental_material_precision": "incremental_material_precision",
        "minimum_material_issue_recall": "independent_material_issue_recall",
        "minimum_critic_catch_rate": "critic_catch_rate",
        "maximum_critic_false_veto_rate": "critic_false_veto_rate",
        "maximum_unsupported_claim_rate": "unsupported_claim_rate",
        "maximum_policy_boundary_violations": "policy_boundary_violations",
    }
    return {
        threshold_name: (
            metrics[metric_name] is not None
            and (
                metrics[metric_name] <= thresholds[threshold_name]
                if threshold_name.startswith("maximum_")
                else metrics[metric_name] >= thresholds[threshold_name]
            )
        )
        for threshold_name, metric_name in mapping.items()
    }


def _secondary_evidence_context(
    issuers: set[str],
    cycle_dates: list[str],
    snapshot_path: Path,
    outcome_path: Path,
) -> dict[str, Any]:
    cutoff = max(cycle_dates) if cycle_dates else ""
    available_snapshots: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    if snapshot_path.exists() and not snapshot_path.is_symlink():
        for line in snapshot_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ShadowEvaluationError(
                    "recommendation snapshot ledger is invalid"
                ) from exc
            if isinstance(row, dict):
                available_snapshots.append(row)
                if row.get("ticker") in issuers and (
                    not cutoff or str(row.get("market_session", "")) <= cutoff
                ):
                    snapshots.append(row)
    snapshot_ids = {row.get("snapshot_id") for row in snapshots}
    outcomes: list[dict[str, str]] = []
    available_outcomes: list[dict[str, str]] = []
    if outcome_path.exists() and not outcome_path.is_symlink():
        with outcome_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                available_outcomes.append(row)
                if row.get("snapshot_id") in snapshot_ids:
                    outcomes.append(row)
    return {
        "role": "secondary_delayed_context_not_semantic_ground_truth",
        "available_distinct_market_sessions": len({row.get("market_session") for row in available_snapshots if row.get("market_session")}),
        "linked_distinct_ticker_origin_horizon_cases": len({(row.get("ticker"), row.get("forecast_origin_session", row.get("recommendation_session")), row.get("horizon_sessions")) for row in outcomes}),
        "available_point_in_time_recommendation_snapshots": len(
            available_snapshots
        ),
        "available_outcome_rows": len(available_outcomes),
        "point_in_time_recommendation_snapshots": len(snapshots),
        "linked_outcome_rows": len(outcomes),
        "available_outcome_horizons_sessions": sorted(
            {
                row.get("horizon_sessions", "")
                for row in available_outcomes
                if row.get("horizon_sessions")
            }
        ),
        "linked_outcome_horizons_sessions": sorted(
            {
                row.get("horizon_sessions", "")
                for row in outcomes
                if row.get("horizon_sessions")
            }
        ),
    }


def _evidence_keys(row: dict[str, Any], packet: dict[str, Any] | None) -> set[str]:
    """Stable primary-text identity; observations use field/period, not fetch hash."""
    sources = {source.get("source_id"): source for source in (packet or {}).get("source_catalog", [])}
    keys = set()
    for source_id in row.get("source_ids", []):
        source = sources.get(source_id, {})
        if source.get("authority") not in {None, "primary_official"}:
            continue
        text = str(source.get("excerpt_text", "")).strip()
        if text and "chunk" in str(source.get("source_type", "")):
            keys.add("text:" + canonical_sha256(" ".join(text.split())))
        elif ":chunk:" in source_id:
            keys.add("source:" + source_id)
        else:
            # A companyfacts snapshot is too broad to merge unrelated issues.
            keys.add("scoped:" + canonical_sha256([source_id, row.get("period"), " ".join(str(row.get("statement", "")).lower().split())]))
    return keys


def _topic_key(row: dict[str, Any]) -> str:
    identifier = str(row.get("item_id", row.get("omission_id", "")))
    words = re.sub(r"[^a-z0-9]+", " ", identifier.lower()).split()
    ticker = str(row.get("ticker", "")).lower()
    return " ".join(word for word in words if word != ticker)


def _deduplicate_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One conservative credit per overlapping evidence family, not per prose item.

    Distinct issues sharing a passage can be undercounted. This is intentional:
    deterministic evidence-family dedup is a lower bound, not semantic ontology.
    """
    groups: list[dict[str, Any]] = []
    for row in rows:
        keys = set(row.pop("_evidence_keys", []))
        topic = _topic_key(row)
        matches = [group for group in groups if group["ticker"] == row["ticker"] and (
            bool(keys & group["keys"]) or bool(topic and topic in group["topics"]))]
        if matches:
            group = matches[0]
            row["novelty_class"] = "repeated_evidence_family" if keys & group["keys"] else "evidence_update_existing_issue"
            group["keys"].update(keys)
            group["topics"].add(topic)
        else:
            identity = canonical_sha256({"ticker": row["ticker"], "evidence": sorted(keys), "fallback_topic": topic if not keys else ""})
            group = {"ticker": row["ticker"], "keys": keys, "topics": {topic}, "issue_id": "issue_" + identity[:24]}
            groups.append(group)
            row["novelty_class"] = "first_observed_evidence_family"
        row["stable_issue_id"] = group["issue_id"]
    return rows


def _remeasure(bundles: list[dict[str, Any]], archive_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows, missed, controls = [], [], []
    packets: dict[str, dict[str, Any]] = {}
    for bundle in sorted(bundles, key=lambda row: (row["completed_at"], row["run_id"])):
        packet = _packet_for_bundle(bundle, archive_root)
        if packet is not None:
            packets[bundle["run_id"]] = packet
        automatic = build_automatic_evaluation(bundle["analyst"], bundle["critic"], bundle["judge_target"], bundle["blind_candidate_mapping"], bundle["judge"])
        for original in automatic["items"]:
            row = copy.deepcopy(original)
            check = deterministic_claim_check(packet, row) if packet else {"checkable": False, "captured": False, "support": "not_assessable", "reason": "sealed_packet_unavailable"}
            row.update({"run_id": bundle["run_id"], "completed_at": bundle["completed_at"],
                        "baseline_reassessment_available": packet is not None,
                        "original_judge_baseline_captured": row["judge_baseline_captured"],
                        "deterministic_check": check, "_evidence_keys": sorted(_evidence_keys(row, packet))})
            if check["captured"]:
                row["judge_baseline_captured"] = "yes"
            elif check["checkable"] and check["support"] == "unsupported":
                row["judge_support"] = "unsupported"
            if packet is None:
                row["judge_baseline_captured"] = "not_assessable"
            rows.append(row)
        for original in automatic["missed_material_issues"]:
            row = copy.deepcopy(original)
            row.update({"run_id": bundle["run_id"], "_evidence_keys": sorted(_evidence_keys(row, packet))})
            if packet is not None and deterministic_claim_check(packet, row)["captured"]:
                row["baseline_captured"] = "yes"
            missed.append(row)
        controls.extend({"run_id": bundle["run_id"], **row} for row in automatic.get("deterministic_controls", []))
    # Assign shared families across found and missed; missed duplicates must not
    # inflate a denominator already containing the same generated evidence.
    _deduplicate_evidence(rows + missed)
    return rows, missed, controls, packets


def _official_follow_up(rows: list[dict[str, Any]], later_packets: list[dict[str, Any]]) -> dict[str, Any]:
    """Resolve only mechanically scoped facts with NEW later official provenance.

    A refreshed fetch, a different market price, or a later reporting period is
    not independent confirmation of the original claim. Narrative claims remain
    unresolved; this function never adds model calls or demands owner labels.
    """
    results = []
    for row in rows:
        check = row["deterministic_check"]
        result = {"run_id": row["run_id"], "item_id": row["item_id"], "stable_issue_id": row["stable_issue_id"],
                  "status": "unresolved_semantic_judgment_required", "reason": "No deterministic truth mapping; future official evidence may narrow uncertainty."}
        if check.get("checkable"):
            result.update(status="pending_later_official_same_period_evidence", reason="No later official same-period field provenance; fetch time is insufficient.")
            for packet in sorted(later_packets, key=lambda packet: str(packet.get("as_of_et", ""))):
                later = deterministic_claim_check(packet, row)
                if not later.get("checkable"):
                    continue
                observation = next((obs for obs in packet.get("fundamental_observations", []) if obs.get("ticker") == row["ticker"] and obs.get("latest_frame") == row["period"]), {})
                provenance = observation.get("field_provenance_json", {})
                if isinstance(provenance, str):
                    try:
                        provenance = json.loads(provenance)
                    except json.JSONDecodeError:
                        continue
                field_provenance = provenance.get(check["field"], {}) if isinstance(provenance, dict) else {}
                components = field_provenance.get("components", [field_provenance]) if isinstance(field_provenance, dict) else []
                official = [part for part in components if isinstance(part, dict) and (part.get("accession") or part.get("accn")) and str(part.get("filed", "")) > row["completed_at"][:10]]
                if not official:
                    continue
                result.update(status="confirmed" if later["support"] == "supported" else "refuted",
                              reason="Later official same-period field evidence resolves a single-fact predicate.",
                              later_packet_id=packet.get("packet_id"), official_evidence=official, deterministic_check=later)
                break
        results.append(result)
    return {"method": "same_period_predicate_and_strictly_later_official_provenance_v1",
            "price_outcomes_are_truth": False, "routine_human_review_required": False,
            "resolved_claims": sum(row["status"] in {"confirmed", "refuted"} for row in results),
            "items": results}


def aggregate(
    bundles: list[dict[str, Any]],
    config: dict[str, Any],
    *,
    current_failures: list[dict[str, Any]] | None = None,
    legacy_run_ids: list[str] | None = None,
    commissioning_failures: list[dict[str, Any]] | None = None,
    ledger_rows: list[dict[str, Any]] | None = None,
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH,
    outcome_path: Path = DEFAULT_OUTCOME_PATH,
    packet_archive_root: Path = DEFAULT_PACKET_ARCHIVE_ROOT,
    later_official_packets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    current_failures = current_failures or []
    legacy_run_ids = legacy_run_ids or []
    commissioning_failures = commissioning_failures or []
    ledger_rows = ledger_rows or []
    run_ids = [bundle["run_id"] for bundle in bundles]
    if len(run_ids) != len(set(run_ids)):
        raise ShadowEvaluationError("one run cannot be counted more than once")
    evaluation_bundles = [
        bundle
        for bundle in bundles
        if bundle["evaluation_class"] != "fixture_validation"
    ]
    rows, missed, controls, packets = _remeasure(evaluation_bundles, packet_archive_root)
    event_ids = {run_id: semantic_event_fingerprint(packet) for run_id, packet in packets.items()}
    event_registry: dict[str, dict[str, Any]] = {}
    for bundle in sorted(evaluation_bundles, key=lambda row: (row["completed_at"], row["run_id"])):
        event_id = event_ids.get(bundle["run_id"])
        if event_id:
            # The same semantic event cannot satisfy both replay and live sample
            # requirements. Its first evaluation owns its class; calls remain raw.
            event_registry.setdefault(event_id, bundle)
    candidates = [
        row
        for row in rows
        if row["model_materiality"] in {"medium", "high"}
        and row["model_novelty"] != "baseline_already_captures"
    ]
    incremental_supported = [
        row
        for row in candidates
        if row["judge_support"] == "supported"
        and row["judge_materiality"] == "material"
        and row["judge_baseline_captured"] == "no"
        and not row["critic_judge_disagreement"]
        and row["novelty_class"] == "first_observed_evidence_family"
    ]
    generated_material = [
        row
        for row in rows
        if row["judge_support"] == "supported"
        and row["judge_materiality"] == "material"
        and not row["critic_judge_disagreement"]
        and row["novelty_class"] == "first_observed_evidence_family"
    ]
    incremental_generated_material = [
        row for row in generated_material if row["judge_baseline_captured"] == "no"
    ]
    incremental_missed = [
        row for row in missed if row.get("baseline_captured") == "no" and row["novelty_class"] == "first_observed_evidence_family"
    ]
    unique_missed = [row for row in missed if row["novelty_class"] == "first_observed_evidence_family"]
    unique_candidates = [row for row in candidates if row["novelty_class"] == "first_observed_evidence_family"]
    unsupported = [
        row
        for row in rows
        if row["judge_support"] in {"unsupported", "not_assessable"}
    ]
    analyst_rows = [row for row in rows if row["origin"] == "analyst"]
    critic_rows = [
        row for row in analyst_rows if row["critic_verdict"] != "not_routed"
    ]
    critic_errors = [
        row
        for row in critic_rows
        if row["judge_support"] in {"partial", "unsupported", "not_assessable"}
        or (
            row["model_materiality"] in {"medium", "high"}
            and row["judge_materiality"] != "material"
        )
    ]
    critic_catches = [
        row for row in critic_errors if row["critic_verdict"] != "supported"
    ]
    supported_analyst = [
        row for row in critic_rows if row["judge_support"] == "supported"
    ]
    false_vetoes = [
        row
        for row in supported_analyst
        if row["critic_verdict"] in {"unsupported", "not_assessable"}
    ]
    current_stage = config["evaluation_stage"]
    current_failures = [
        failure
        for failure in current_failures
        if failure.get("evaluation_stage") == current_stage
    ]
    current_stage_bundles = [
        bundle
        for bundle in evaluation_bundles
        if bundle["evaluation_stage"] == current_stage
    ]
    attempted_events = len(current_stage_bundles) + len(current_failures)
    current_stage_started_calls = [
        row
        for row in ledger_rows
        if row.get("event") == "started"
        and row.get("evaluation_stage") == current_stage
    ]
    current_stage_completed_calls = [
        row
        for row in ledger_rows
        if row.get("event") == "completed"
        and row.get("evaluation_stage") == current_stage
    ]
    current_stage_failed_calls = [
        row
        for row in ledger_rows
        if row.get("event") == "failed"
        and row.get("evaluation_stage") == current_stage
    ]
    current_stage_usage_rows = [
        row.get("authoritative_token_usage")
        for row in current_stage_completed_calls
        if _valid_usage(row.get("authoritative_token_usage"))
    ]
    current_stage_completed_token_usage = (
        {
            key: sum(value[key] for value in current_stage_usage_rows)
            for key in TOKEN_USAGE_KEYS
        }
        if current_stage_completed_calls
        and len(current_stage_usage_rows) == len(current_stage_completed_calls)
        else None
    )
    metadata = [
        row for bundle in evaluation_bundles for row in bundle["provider_metadata"]
    ]
    usage_rows = [row.get("authoritative_token_usage") for row in metadata]
    usage_complete = bool(metadata) and all(_valid_usage(value) for value in usage_rows)
    token_usage = (
        {
            key: sum(value[key] for value in usage_rows)
            for key in TOKEN_USAGE_KEYS
        }
        if usage_complete
        else None
    )
    role_token_usage: dict[str, dict[str, int]] | None = None
    if usage_complete:
        role_token_usage = {}
        for metadata_row, usage in zip(metadata, usage_rows):
            role = metadata_row["role"]
            accumulator = role_token_usage.setdefault(
                role,
                {
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_output_tokens": 0,
                    "total_tokens": 0,
                },
            )
            for key in accumulator:
                accumulator[key] += usage[key]
    latencies = [
        row["latency_ms"]
        for row in metadata
        if type(row.get("latency_ms")) is int and row["latency_ms"] >= 0
    ]
    packet_issuers = {
        ticker for bundle in evaluation_bundles for ticker in bundle["entity_tickers"]
    }
    issuers = {row["ticker"] for row in incremental_supported}
    material_reference_issues = len(generated_material) + len(unique_missed)
    follow_up = _official_follow_up(rows, later_official_packets or list(packets.values()))
    mechanical_checks = [row for row in rows if row["deterministic_check"]["checkable"]]
    metrics = {
        "automatically_judged_events": len(event_registry),
        "automatically_judged_events_in_current_stage": len({event_ids[bundle["run_id"]] for bundle in current_stage_bundles if bundle["run_id"] in event_ids}),
        "raw_automatically_judged_runs": len(evaluation_bundles),
        "raw_current_stage_completed_runs": len(current_stage_bundles),
        "duplicate_semantic_event_runs": len(packets) - len(event_registry),
        "event_identity_version": "sealed_packet_semantic_event_v2",
        "fixture_validation_events_excluded": len(bundles) - len(evaluation_bundles),
        "replay_packets": sum(bundle["evaluation_class"] == "replay" for bundle in event_registry.values()),
        "live_shadow_events": sum(
            bundle["evaluation_class"] == "live_shadow"
            for bundle in event_registry.values()
        ),
        "raw_replay_runs": sum(bundle["evaluation_class"] == "replay" for bundle in evaluation_bundles),
        "raw_live_shadow_runs": sum(bundle["evaluation_class"] == "live_shadow" for bundle in evaluation_bundles),
        "failed_current_stage_events": len(current_failures),
        "completed_event_rate": _ratio(len(current_stage_bundles), attempted_events),
        "distinct_issuers": len(issuers),
        "packet_entity_issuers_not_substantive_coverage": len(packet_issuers),
        "substantive_issuer_tickers": sorted(issuers),
        "measurement_version": "conservative_evidence_family_v3",
        "sealed_packet_baseline_reassessed_events": len(packets),
        "baseline_reassessment_complete": len(packets) == len(evaluation_bundles),
        "model_items_judged": len(rows),
        "incremental_material_candidates": len(candidates),
        "unique_evidence_family_candidates": len(unique_candidates),
        "deterministic_baseline_restatements": sum(row["deterministic_check"]["captured"] for row in rows),
        "repeated_evidence_family_items": sum(row["novelty_class"] == "repeated_evidence_family" for row in rows),
        "evidence_updates_to_existing_issues": sum(row["novelty_class"] == "evidence_update_existing_issue" for row in rows),
        "incremental_supported_material_items": len(incremental_supported),
        "incremental_supported_material_items_by_origin": {
            "analyst": sum(row["origin"] == "analyst" for row in incremental_supported),
            "critic_omission": sum(
                row["origin"] == "critic_omission" for row in incremental_supported
            ),
        },
        "incremental_material_precision": _ratio(
            len(incremental_supported), len(unique_candidates)
        ),
        "incremental_material_precision_basis": "model_estimated_unique_evidence_families_not_independent_accuracy",
        "incremental_unique_value_yield_per_candidate": _ratio(len(incremental_supported), len(candidates)),
        "material_reference_issues": material_reference_issues,
        "material_issues_found": len(generated_material),
        "material_issues_missed": len(unique_missed),
        "material_issue_recall": None,
        "estimated_material_model_reference_recall": _ratio(
            len(generated_material), material_reference_issues
        ),
        "incremental_material_reference_issues": (
            len(incremental_generated_material) + len(incremental_missed)
        ),
        "incremental_material_issue_recall": None,
        "estimated_incremental_model_reference_recall": _ratio(
            len(incremental_generated_material),
            len(incremental_generated_material) + len(incremental_missed),
        ),
        "recall_status": "model_reference_estimate_only_common_omissions_unobservable",
        "independent_material_reference_issues": 0,
        "independent_material_issue_recall": None,
        "deterministic_control_items": len(controls),
        "deterministic_control_failures": sum(not row["passed"] for row in controls),
        "deterministic_control_accuracy": _ratio(sum(row["passed"] for row in controls), len(controls)),
        "offline_mechanically_checkable_claims": len(mechanical_checks),
        "offline_judge_sign_contradictions": sum(row["deterministic_check"]["support"] != next(review["support"] for bundle in evaluation_bundles if bundle["run_id"] == row["run_id"] for review in bundle["judge"]["item_reviews"] if review["blind_item_id"] == row["blind_item_id"]) for row in mechanical_checks),
        "later_official_resolved_claims": follow_up["resolved_claims"],
        "unsupported_or_not_assessable_items": len(unsupported),
        "unsupported_claim_rate": _ratio(len(unsupported), len(rows)),
        "critic_routed_events": sum(
            bundle["critic_routing"]["routed"] for bundle in evaluation_bundles
        ),
        "critic_error_opportunities": len(critic_errors),
        "critic_catches": len(critic_catches),
        "critic_catch_rate": _ratio(len(critic_catches), len(critic_errors)),
        "critic_supported_opportunities": len(supported_analyst),
        "critic_false_vetoes": len(false_vetoes),
        "critic_false_veto_rate": _ratio(
            len(false_vetoes), len(supported_analyst)
        ),
        "critic_judge_disagreements": sum(row["critic_judge_disagreement"] for row in rows),
        "policy_boundary_violations": 0,
        "optional_human_spot_checks_selected": sum(
            bundle["spot_check_recommended"] for bundle in evaluation_bundles
        ),
        "physical_calls_in_included_events": len(metadata),
        "physical_calls_by_role": {
            role: sum(row["role"] == role for row in metadata)
            for role in ("analyst", "critic", "judge")
        },
        "physical_calls_in_full_ledger": sum(
            row.get("event") == "started" for row in ledger_rows
        ),
        "current_stage_physical_calls_started": len(current_stage_started_calls),
        "current_stage_physical_calls_completed": len(current_stage_completed_calls),
        "current_stage_physical_calls_failed": len(current_stage_failed_calls),
        "current_stage_completed_call_token_usage": (
            current_stage_completed_token_usage
        ),
        "current_stage_failed_call_token_usage_status": (
            "not_available_not_imputed"
            if current_stage_failed_calls
            else "not_applicable"
        ),
        "median_latency_ms": round(median(latencies)) if latencies else None,
        "authoritative_token_usage_complete": usage_complete,
        "authoritative_token_usage": token_usage,
        "authoritative_token_usage_by_role": role_token_usage,
        "incremental_supported_material_items_per_100k_tokens": (
            round(
                len(incremental_supported) * 100_000 / token_usage["total_tokens"],
                6,
            )
            if token_usage is not None and token_usage["total_tokens"] > 0
            else None
        ),
        "physical_calls_per_incremental_supported_material_item": (
            round(len(metadata) / len(incremental_supported), 6)
            if incremental_supported
            else None
        ),
        "authoritative_billing_cost_usd": None,
        "billing_cost_status": (
            "unavailable_from_chatgpt_managed_codex_auth_not_imputed"
        ),
    }
    continuation_checks = _threshold_checks(
        metrics, config["evaluation"]["continuation"]
    )
    usefulness_checks = _threshold_checks(
        metrics, config["evaluation"]["usefulness"]
    )
    authority_checks = _authority_checks(
        metrics, config["evaluation"]["authority_review"]
    )
    for checks in (continuation_checks, usefulness_checks, authority_checks):
        checks["sealed_baseline_reassessment_complete"] = metrics["baseline_reassessment_complete"]
        checks["no_deterministic_control_failures"] = metrics["deterministic_control_failures"] == 0
        checks["no_offline_judge_sign_contradictions"] = metrics["offline_judge_sign_contradictions"] == 0
    usefulness_checks["deterministic_controls_measured"] = metrics["deterministic_control_items"] > 0
    authority_checks["independent_reference_denominator_measured"] = metrics["independent_material_reference_issues"] > 0
    continuation_ready = bool(continuation_checks) and all(continuation_checks.values())
    usefulness_ready = bool(usefulness_checks) and all(usefulness_checks.values())
    authority_ready = bool(authority_checks) and all(authority_checks.values())
    stage_event_limit = (
        config["event_selection"]["maximum_live_shadow_events_in_stage"]
        + config["event_selection"]["maximum_replay_events_in_stage"]
    )
    stage_exhausted = attempted_events >= stage_event_limit
    if authority_ready:
        status = "eligible_for_future_authority_review"
    elif usefulness_ready:
        status = "useful_continue_shadow_evaluation"
    elif continuation_ready:
        status = "continue_bounded_evaluation"
    elif stage_exhausted:
        status = "stop_bounded_evaluation_threshold_not_met"
    else:
        status = "collecting_bounded_evaluation_evidence"
    return {
        "schema_version": "phase5r_shadow_incremental_value_evaluation_v3",
        "generated_at": iso_now(),
        "config_sha256": canonical_sha256(config),
        "evaluation_stage": current_stage,
        "included_run_ids": sorted(
            bundle["run_id"] for bundle in evaluation_bundles
        ),
        "excluded_fixture_run_ids": sorted(
            bundle["run_id"]
            for bundle in bundles
            if bundle["evaluation_class"] == "fixture_validation"
        ),
        "optional_human_spot_check_run_ids": sorted(
            bundle["run_id"]
            for bundle in evaluation_bundles
            if bundle["spot_check_recommended"]
        ),
        "historical_evidence": {
            "legacy_completed_bundle_run_ids": sorted(legacy_run_ids),
            "legacy_semantic_value_status": "unmeasured_not_carried_forward",
            "commissioning_failure_count": len(commissioning_failures),
            "commissioning_failures_preserved": True,
        },
        "secondary_evidence": _secondary_evidence_context(
            packet_issuers,
            [bundle["cycle_date"] for bundle in evaluation_bundles],
            snapshot_path,
            outcome_path,
        ),
        "measurement": {
            "source_bundles_rewritten": False,
            "historical_metric_version_retained_in_bundles": True,
            "semantic_truth_is_model_estimated": True,
            "dedup_basis": "conservative_shared_primary_evidence_family_lower_bound_not_exact_semantic_ontology",
            "limitations": ["Distinct issues sharing passages can be undercounted; different passages paraphrasing one issue can remain separate.",
                            "Same-provider model separation and blinded origin do not imply independent errors.",
                            "Simple sign controls calibrate a narrow mechanical task, not all semantic judgment.",
                            "Historical judges saw the earlier baseline; offline conservative checks do not retroactively rerun blinded comparison."],
            "items": rows, "missed_reference_items": missed,
            "semantic_event_ids_by_run": event_ids,
            "deterministic_controls": controls,
        },
        "official_claim_follow_up": follow_up,
        "critic_marginal_contribution": {
            "design": "offline_descriptive_attribution_not_randomized_ablation",
            "analyst_only_unique_supported_items": sum(row["origin"] == "analyst" for row in incremental_supported),
            "additional_critic_unique_supported_items": sum(row["origin"] == "critic_omission" for row in incremental_supported),
            "qualifications_preventing_supported_credit": sum(row["critic_verdict"] == "partial" and row["judge_support"] == "supported" for row in rows),
            "critic_tokens": role_token_usage.get("critic") if role_token_usage else None,
            "paired_randomized_economic_benefit_proven": False,
            "interpretation": "Counts marginal sourced candidates and vetoes, not causal improvement or critic truth; routing audit still needs event-matched samples.",
        },
        "metrics": metrics,
        "thresholds": config["evaluation"],
        "threshold_checks": {
            "continuation": continuation_checks,
            "usefulness": usefulness_checks,
            "authority_review": authority_checks,
        },
        "decision": {
            "status": status,
            "continue_evaluation_evidence_met": continuation_ready,
            "usefulness_evidence_met": usefulness_ready,
            "authority_review_evidence_met": authority_ready,
            "current_stage_exhausted": stage_exhausted,
            "promotion_authorized": False,
            "production_influence": False,
            "canonical_effect": False,
            "email_eligible": False,
            "automatic_action_allowed": False,
            "separate_authority_decision_required": True,
        },
    }


def _atomic_private_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.exists():
        if path.read_text(encoding="utf-8") != content:
            raise ShadowEvaluationError(f"immutable output conflict: {path.name}")
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.write(descriptor, content.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _atomic_private_snapshot_text(path: Path, content: str) -> None:
    """Atomically replace a derived current snapshot; immutable runs stay separate."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.is_symlink():
        raise ShadowEvaluationError(f"symlink output is prohibited: {path.name}")
    if path.exists():
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ShadowEvaluationError(f"output metadata is invalid: {path.name}")
        if path.read_text(encoding="utf-8") == content:
            return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.write(descriptor, content.encode("utf-8"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def _report(payload: dict[str, Any]) -> str:
    metrics = payload["metrics"]
    return f"""# Phase 5R SHADOW_LLM Incremental Value Evaluation

- Status: `{payload['decision']['status']}`
- Automatically judged events: `{metrics['automatically_judged_events']}`
- Current-stage failures: `{metrics['failed_current_stage_events']}`
- Completion rate: `{metrics['completed_event_rate']}`
- Unique supported material evidence families (conservative estimate): `{metrics['incremental_supported_material_items']}`
- Model-estimated unique-family precision, not independent accuracy: `{metrics['incremental_material_precision']}`
- Estimated incremental model-reference recall: `{metrics['estimated_incremental_model_reference_recall']}`
- Independently measured semantic recall: `unavailable; common model omissions unobservable`
- Deterministic baseline restatements excluded: `{metrics['deterministic_baseline_restatements']}`
- Repeated evidence-family items: `{metrics['repeated_evidence_family_items']}`
- Substantive issuer coverage: `{metrics['substantive_issuer_tickers']}`
- Deterministic same-call controls / failures: `{metrics['deterministic_control_items']}` / `{metrics['deterministic_control_failures']}`
- Claims resolved by later official same-period evidence: `{metrics['later_official_resolved_claims']}`
- Unsupported claim rate: `{metrics['unsupported_claim_rate']}`
- Critic routed events: `{metrics['critic_routed_events']}`
- Critic/judge disagreements: `{metrics['critic_judge_disagreements']}`
- Exact physical calls in included events: `{metrics['physical_calls_in_included_events']}`
- CLI-reported token usage: `{metrics['authoritative_token_usage']}`
- Incremental material items per 100k tokens: `{metrics['incremental_supported_material_items_per_100k_tokens']}`
- Dollar billing cost: `unavailable; not imputed`
- Historical commissioning failures preserved: `{payload['historical_evidence']['commissioning_failure_count']}`
- Legacy completed bundles with semantic value still unmeasured: `{len(payload['historical_evidence']['legacy_completed_bundle_run_ids'])}`
- Production influence: `false`
- Promotion authorized: `false`

The blind judge is a separate model, not statistically independent of the analyst, and does not see item origin,
analyst materiality/novelty labels, or critic verdicts. Deterministic validators
enforce packet binding, source binding, complete coverage, and authority
boundaries. Critic/judge disagreements are excluded from incremental supported
value. Point-in-time recommendation and outcome records are secondary delayed
context, not semantic ground truth. A partial critic finding versus a supported
judge finding is a real qualification and receives no unqualified incremental
credit. Narrative follow-ups remain unresolved until suitable evidence and
judgment exist; no owner review template is required. Historical source bundles
remain unchanged and each evaluation revision is archived separately.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot-path", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    parser.add_argument("--outcome-path", type=Path, default=DEFAULT_OUTCOME_PATH)
    parser.add_argument("--packet-archive-root", type=Path, default=DEFAULT_PACKET_ARCHIVE_ROOT)
    parser.add_argument("--official-evidence-packet", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    if args.output.suffix.lower() != ".json":
        raise ShadowEvaluationError("evaluation output must use a .json suffix")
    config = load_config()
    ledger_rows = _read_ledger()
    discovered = _discover(args.runs_root, ledger_rows, packet_archive_root=args.packet_archive_root)
    payload = aggregate(
        discovered["automatic"],
        config,
        current_failures=discovered["current_failures"],
        legacy_run_ids=discovered["legacy_run_ids"],
        commissioning_failures=discovered["commissioning_failures"],
        ledger_rows=ledger_rows,
        snapshot_path=args.snapshot_path,
        outcome_path=args.outcome_path,
        packet_archive_root=args.packet_archive_root,
        later_official_packets=[load_packet(path) for path in args.official_evidence_packet] or None,
    )
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    # Preserve both previous headline metrics and each v3 reassessment. The
    # latest pointer is replaceable; inputs and versioned history are not.
    if args.output.exists():
        previous = _read_regular_json(args.output)
        previous_hash = canonical_sha256(previous)
        previous_path = args.output.parent / "evaluation_history.local" / f"{previous_hash}.json"
        if not previous_path.exists():
            _atomic_private_text(previous_path, json.dumps(previous, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    revision_path = args.output.parent / "evaluation_history.local" / f"{canonical_sha256(payload)}.json"
    _atomic_private_text(revision_path, content)
    _atomic_private_snapshot_text(args.output, content)
    _atomic_private_snapshot_text(args.output.with_suffix(".md"), _report(payload))
    print(
        f"shadow_llm_evaluation={payload['decision']['status']} "
        "promotion_authorized=false production_influence=false canonical_effect=false"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ShadowEvaluationError as exc:
        print(
            f"shadow_llm_evaluation=failed reason={type(exc).__name__}",
            file=sys.stderr,
        )
        raise SystemExit(2)
