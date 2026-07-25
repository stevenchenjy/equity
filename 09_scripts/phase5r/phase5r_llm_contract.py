#!/usr/bin/env python3
"""Closed contracts and deterministic gates for Phase 5R model research.

This module is deliberately dependency-free.  A provider may produce a response,
but only these validators and gates can classify it.  The module has no network,
email, account-write, broker, or execution capability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from phase5r_daily_common import canonical_sha256


PACKET_SCHEMA_VERSION = "phase5r_llm_evidence_packet_v1"
ANALYST_SCHEMA_VERSION = "phase5r_llm_evidence_analysis_v1"
COMMITTEE_SCHEMA_VERSION = "phase5r_llm_committee_decision_v1"
CRITIC_SCHEMA_VERSION = "phase5r_llm_critic_review_v1"
ADJUDICATION_SCHEMA_VERSION = "phase5r_llm_adjudication_v1"

RESEARCH_CLASSIFICATIONS = (
    "reject",
    "watchlist",
    "hold_existing",
    "paper_trade_candidate",
    "real_trade_candidate",
    "trim_review",
    "exit_review",
    "abstain",
)
TRANSITION_CLASSIFICATIONS = {
    "paper_trade_candidate",
    "real_trade_candidate",
    "trim_review",
    "exit_review",
}
NO_ACTION_CLASSIFICATIONS = {
    "reject",
    "watchlist",
    "hold_existing",
    "abstain",
}

_CLASSIFICATION_RANK = {
    "abstain": 0,
    "reject": 1,
    "watchlist": 2,
    "hold_existing": 3,
    "paper_trade_candidate": 4,
    "real_trade_candidate": 5,
    "trim_review": 6,
    "exit_review": 7,
}

_SENSITIVE_MARKERS = (
    "smtp",
    "app_password",
    "api_key",
    "authorization: bearer",
    "broker_login",
    "bank_account",
    "credit_card",
    "account_total_value",
    "cash_available",
    "cash_reserved",
    "current_shares",
    "target_shares",
    "entry_price",
    "/users/",
    "file://",
)


class ContractError(ValueError):
    """A structured response or evidence packet violated a closed contract."""


def _closed_object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _string_array() -> dict[str, Any]:
    return {"type": "array", "items": {"type": "string"}}


ANALYST_SCHEMA = _closed_object(
    {
        "schema_version": {"type": "string", "const": ANALYST_SCHEMA_VERSION},
        "packet_id": {"type": "string"},
        "as_of_et": {"type": "string"},
        "prompt_injection_detected": {"type": "boolean"},
        "claims": {
            "type": "array",
            "items": _closed_object(
                {
                    "claim_id": {"type": "string"},
                    "ticker": {"type": "string"},
                    "claim": {"type": "string"},
                    "stance": {
                        "type": "string",
                        "enum": ["supports", "weakens", "neutral", "uncertain"],
                    },
                    "time_horizon": {
                        "type": "string",
                        "enum": ["near_term", "medium_term", "long_term"],
                    },
                    "materiality": {
                        "type": "string",
                        "enum": ["low", "medium", "high"],
                    },
                    "source_ids": _string_array(),
                    "calculation_ids": _string_array(),
                },
                [
                    "claim_id",
                    "ticker",
                    "claim",
                    "stance",
                    "time_horizon",
                    "materiality",
                    "source_ids",
                    "calculation_ids",
                ],
            ),
        },
        "ticker_coverage": {
            "type": "array",
            "items": _closed_object(
                {
                    "ticker": {"type": "string"},
                    "official_evidence_sufficient": {"type": "boolean"},
                    "contradictory_evidence": {"type": "boolean"},
                    "missing_evidence": _string_array(),
                },
                [
                    "ticker",
                    "official_evidence_sufficient",
                    "contradictory_evidence",
                    "missing_evidence",
                ],
            ),
        },
        "unresolved_questions": _string_array(),
    },
    [
        "schema_version",
        "packet_id",
        "as_of_et",
        "prompt_injection_detected",
        "claims",
        "ticker_coverage",
        "unresolved_questions",
    ],
)


COMMITTEE_SCHEMA = _closed_object(
    {
        "schema_version": {"type": "string", "const": COMMITTEE_SCHEMA_VERSION},
        "packet_id": {"type": "string"},
        "portfolio_classification": {
            "type": "string",
            "enum": list(RESEARCH_CLASSIFICATIONS),
        },
        "headline": {"type": "string"},
        "decisive_advice": {"type": "string"},
        "long_term_portfolio_case": {"type": "string"},
        "data_sufficiency": {
            "type": "string",
            "enum": ["sufficient", "partial", "insufficient"],
        },
        "material_thesis_break": {"type": "boolean"},
        "confidence_pct": {"type": "integer"},
        "ticker_decisions": {
            "type": "array",
            "items": _closed_object(
                {
                    "ticker": {"type": "string"},
                    "classification": {
                        "type": "string",
                        "enum": list(RESEARCH_CLASSIFICATIONS),
                    },
                    "thesis_direction": {
                        "type": "string",
                        "enum": ["strengthening", "stable", "weakening", "broken", "unclear"],
                    },
                    "rationale": {"type": "string"},
                    "long_term_case": {"type": "string"},
                    "risks": _string_array(),
                    "invalidation_conditions": _string_array(),
                    "source_ids": _string_array(),
                    "calculation_ids": _string_array(),
                    "confidence_pct": {"type": "integer"},
                    "human_review_needed": {"type": "boolean"},
                },
                [
                    "ticker",
                    "classification",
                    "thesis_direction",
                    "rationale",
                    "long_term_case",
                    "risks",
                    "invalidation_conditions",
                    "source_ids",
                    "calculation_ids",
                    "confidence_pct",
                    "human_review_needed",
                ],
            ),
        },
        "dissent": _string_array(),
        "automatic_action_allowed": {"type": "boolean", "const": False},
    },
    [
        "schema_version",
        "packet_id",
        "portfolio_classification",
        "headline",
        "decisive_advice",
        "long_term_portfolio_case",
        "data_sufficiency",
        "material_thesis_break",
        "confidence_pct",
        "ticker_decisions",
        "dissent",
        "automatic_action_allowed",
    ],
)


CRITIC_SCHEMA = _closed_object(
    {
        "schema_version": {"type": "string", "const": CRITIC_SCHEMA_VERSION},
        "packet_id": {"type": "string"},
        "verdict": {"type": "string", "enum": ["approve", "revise", "reject"]},
        "downgrade_to": {
            "type": "string",
            "enum": list(RESEARCH_CLASSIFICATIONS),
        },
        "factual_grounding_pass": {"type": "boolean"},
        "citation_integrity_pass": {"type": "boolean"},
        "numeric_reconciliation_pass": {"type": "boolean"},
        "long_term_reasoning_pass": {"type": "boolean"},
        "action_proportionality_pass": {"type": "boolean"},
        "policy_boundary_pass": {"type": "boolean"},
        "issues": {
            "type": "array",
            "items": _closed_object(
                {
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "issue": {"type": "string"},
                    "source_ids": _string_array(),
                },
                ["severity", "issue", "source_ids"],
            ),
        },
        "approved_source_ids": _string_array(),
        "automatic_action_allowed": {"type": "boolean", "const": False},
    },
    [
        "schema_version",
        "packet_id",
        "verdict",
        "downgrade_to",
        "factual_grounding_pass",
        "citation_integrity_pass",
        "numeric_reconciliation_pass",
        "long_term_reasoning_pass",
        "action_proportionality_pass",
        "policy_boundary_pass",
        "issues",
        "approved_source_ids",
        "automatic_action_allowed",
    ],
)


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the supported closed JSON-Schema subset used by this project."""

    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            raise ContractError(f"{path}: expected object")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise ContractError(f"{path}: missing fields {','.join(missing)}")
        if schema.get("additionalProperties") is False:
            extras = sorted(set(value) - set(properties))
            if extras:
                raise ContractError(f"{path}: unexpected fields {','.join(extras)}")
        for key, child in properties.items():
            if key in value:
                validate_schema(value[key], child, f"{path}.{key}")
    elif expected_type == "array":
        if not isinstance(value, list):
            raise ContractError(f"{path}: expected array")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema(item, item_schema, f"{path}[{index}]")
    elif expected_type == "string":
        if not isinstance(value, str):
            raise ContractError(f"{path}: expected string")
    elif expected_type == "boolean":
        if not isinstance(value, bool):
            raise ContractError(f"{path}: expected boolean")
    elif expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContractError(f"{path}: expected integer")
    elif expected_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ContractError(f"{path}: expected number")
    elif expected_type is not None:
        raise ContractError(f"{path}: unsupported schema type {expected_type}")

    if "const" in schema and value != schema["const"]:
        raise ContractError(f"{path}: value does not match const")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: value is outside enum")


def _assert_no_sensitive_markers(payload: Any, label: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    found = [marker for marker in _SENSITIVE_MARKERS if marker in serialized]
    if found:
        raise ContractError(f"{label}: sensitive/local marker present: {','.join(found)}")


def _source_ids(packet: dict[str, Any]) -> set[str]:
    return {
        str(row.get("source_id", ""))
        for row in packet.get("source_catalog", [])
        if row.get("source_id")
    }


def _calculation_ids(packet: dict[str, Any]) -> set[str]:
    return {
        str(row.get("calculation_id", ""))
        for row in packet.get("calculations", [])
        if row.get("calculation_id")
    }


def _tickers(packet: dict[str, Any]) -> set[str]:
    return {
        str(row.get("ticker", "")).upper()
        for row in packet.get("entities", [])
        if row.get("ticker")
    }


def _held_tickers(packet: dict[str, Any]) -> set[str]:
    return {
        str(row.get("ticker", "")).upper()
        for row in packet.get("entities", [])
        if row.get("ticker") and row.get("role") == "held"
    }


def _validate_references(
    packet: dict[str, Any],
    source_values: list[str],
    calculation_values: list[str],
    *,
    path: str,
    require_source: bool,
) -> None:
    known_sources = _source_ids(packet)
    known_calculations = _calculation_ids(packet)
    if require_source and not source_values:
        raise ContractError(f"{path}: at least one packet-local source is required")
    unknown_sources = sorted(set(source_values) - known_sources)
    if unknown_sources:
        raise ContractError(f"{path}: unknown source ids {','.join(unknown_sources)}")
    unknown_calculations = sorted(set(calculation_values) - known_calculations)
    if unknown_calculations:
        raise ContractError(
            f"{path}: unknown calculation ids {','.join(unknown_calculations)}"
        )


def validate_packet(packet: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "packet_id",
        "generated_at",
        "as_of_et",
        "cycle_date",
        "decision_fingerprint",
        "entities",
        "portfolio_constraints",
        "gates",
        "market_observations",
        "fundamental_observations",
        "filing_evidence",
        "research_context",
        "calculations",
        "source_catalog",
        "boundaries",
    }
    missing = sorted(required - set(packet))
    extras = sorted(set(packet) - required)
    if missing:
        raise ContractError(f"packet: missing fields {','.join(missing)}")
    if extras:
        raise ContractError(f"packet: unexpected fields {','.join(extras)}")
    if packet["schema_version"] != PACKET_SCHEMA_VERSION:
        raise ContractError("packet: schema version mismatch")
    unsigned = copy.deepcopy(packet)
    supplied_id = str(unsigned.pop("packet_id", ""))
    expected_id = canonical_sha256(unsigned)
    if supplied_id != expected_id:
        raise ContractError("packet: packet_id does not match canonical content")
    if not isinstance(packet["boundaries"], dict):
        raise ContractError("packet: boundaries must be an object")
    required_boundaries = {
        "research_only": True,
        "canonical_effect": False,
        "email_eligible": False,
        "automatic_action_allowed": False,
        "broker_connected": False,
        "order_code_available": False,
        "exact_account_dollars_included": False,
    }
    for key, expected in required_boundaries.items():
        if packet["boundaries"].get(key) is not expected:
            raise ContractError(f"packet: boundary {key} is not fail-closed")
    ids = [row.get("source_id") for row in packet["source_catalog"]]
    if any(not isinstance(value, str) or not value for value in ids):
        raise ContractError("packet: source_id must be a non-empty string")
    if len(ids) != len(set(ids)):
        raise ContractError("packet: source_ids must be unique")
    try:
        as_of = datetime.fromisoformat(str(packet["as_of_et"]))
    except ValueError as exc:
        raise ContractError("packet: as_of_et must be an ISO timestamp") from exc
    if as_of.tzinfo is None:
        raise ContractError("packet: as_of_et must include a timezone")
    source_fields = {
        "source_id",
        "source_type",
        "ticker",
        "accepted_at",
        "source_url",
        "content_sha256",
        "locator",
        "authority",
        "excerpt_text",
    }
    for index, source in enumerate(packet["source_catalog"]):
        if not isinstance(source, dict) or set(source) != source_fields:
            raise ContractError(f"packet.source_catalog[{index}]: field mismatch")
        digest = str(source["content_sha256"])
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ContractError(
                f"packet.source_catalog[{index}]: invalid content sha256"
            )
        accepted_at = str(source["accepted_at"])
        if accepted_at:
            try:
                accepted = datetime.fromisoformat(accepted_at)
            except ValueError as exc:
                raise ContractError(
                    f"packet.source_catalog[{index}]: invalid accepted_at"
                ) from exc
            if accepted.tzinfo is None or accepted > as_of:
                raise ContractError(
                    f"packet.source_catalog[{index}]: future or naive source time"
                )
        url = str(source["source_url"])
        if url and not url.startswith("https://"):
            raise ContractError(
                f"packet.source_catalog[{index}]: source URL is not HTTPS"
            )
        if source["source_type"].startswith("sec_") and url:
            if not (
                url.startswith("https://www.sec.gov/")
                or url.startswith("https://data.sec.gov/")
            ):
                raise ContractError(
                    f"packet.source_catalog[{index}]: SEC source host mismatch"
                )
        excerpt = str(source["excerpt_text"])
        if (
            excerpt
            and hashlib.sha256(excerpt.encode("utf-8")).hexdigest() != digest
        ):
            raise ContractError(
                f"packet.source_catalog[{index}]: excerpt digest mismatch"
            )
    tickers = _tickers(packet)
    if not tickers or any(ticker != ticker.upper() for ticker in tickers):
        raise ContractError("packet: entity tickers must be non-empty uppercase values")
    known_sources = set(ids)
    calculation_ids: list[str] = []
    for index, calculation in enumerate(packet["calculations"]):
        if not isinstance(calculation, dict):
            raise ContractError(f"packet.calculations[{index}]: expected object")
        calculation_id = str(calculation.get("calculation_id", ""))
        if not calculation_id:
            raise ContractError(f"packet.calculations[{index}]: missing id")
        calculation_ids.append(calculation_id)
        unknown = sorted(set(calculation.get("source_ids", [])) - known_sources)
        if unknown:
            raise ContractError(
                f"packet.calculations[{index}]: unknown sources {','.join(unknown)}"
            )
        if not calculation.get("unit") or not calculation.get("period"):
            raise ContractError(
                f"packet.calculations[{index}]: missing unit or period"
            )
    if len(calculation_ids) != len(set(calculation_ids)):
        raise ContractError("packet: calculation_ids must be unique")
    _assert_no_sensitive_markers(packet, "packet")
    return packet


def validate_analyst(
    packet: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    validate_packet(packet)
    validate_schema(response, ANALYST_SCHEMA)
    if response["packet_id"] != packet["packet_id"]:
        raise ContractError("analyst: packet_id mismatch")
    if (
        packet["gates"].get("prompt_injection_text_detected") is True
        and response["prompt_injection_detected"] is not True
    ):
        raise ContractError("analyst: deterministic prompt-injection flag was ignored")
    known_tickers = _tickers(packet)
    claim_ids: list[str] = []
    for index, claim in enumerate(response["claims"]):
        ticker = claim["ticker"].upper()
        if ticker not in known_tickers:
            raise ContractError(f"analyst.claims[{index}]: unknown ticker {ticker}")
        claim_ids.append(claim["claim_id"])
        _validate_references(
            packet,
            claim["source_ids"],
            claim["calculation_ids"],
            path=f"analyst.claims[{index}]",
            require_source=claim["materiality"] in {"medium", "high"},
        )
    if len(claim_ids) != len(set(claim_ids)):
        raise ContractError("analyst: claim_ids must be unique")
    coverage_tickers = [row["ticker"].upper() for row in response["ticker_coverage"]]
    if len(coverage_tickers) != len(set(coverage_tickers)):
        raise ContractError("analyst: ticker coverage must be unique")
    if not _held_tickers(packet).issubset(set(coverage_tickers)):
        raise ContractError("analyst: every held ticker requires coverage")
    _assert_no_sensitive_markers(response, "analyst")
    return response


def validate_committee(
    packet: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    validate_packet(packet)
    validate_schema(response, COMMITTEE_SCHEMA)
    if response["packet_id"] != packet["packet_id"]:
        raise ContractError("committee: packet_id mismatch")
    if not 0 <= response["confidence_pct"] <= 100:
        raise ContractError("committee: confidence_pct must be 0..100")
    known_tickers = _tickers(packet)
    decision_tickers: list[str] = []
    for index, decision in enumerate(response["ticker_decisions"]):
        ticker = decision["ticker"].upper()
        if ticker not in known_tickers:
            raise ContractError(f"committee.ticker_decisions[{index}]: unknown ticker")
        decision_tickers.append(ticker)
        if not 0 <= decision["confidence_pct"] <= 100:
            raise ContractError(
                f"committee.ticker_decisions[{index}]: confidence must be 0..100"
            )
        _validate_references(
            packet,
            decision["source_ids"],
            decision["calculation_ids"],
            path=f"committee.ticker_decisions[{index}]",
            require_source=decision["classification"] != "abstain",
        )
    if len(decision_tickers) != len(set(decision_tickers)):
        raise ContractError("committee: ticker decisions must be unique")
    if not _held_tickers(packet).issubset(set(decision_tickers)):
        raise ContractError("committee: every held ticker requires a decision")
    if response["automatic_action_allowed"] is not False:
        raise ContractError("committee: automatic action must remain false")
    _assert_no_sensitive_markers(response, "committee")
    return response


def validate_critic(
    packet: dict[str, Any],
    committee: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    validate_committee(packet, committee)
    validate_schema(response, CRITIC_SCHEMA)
    if response["packet_id"] != packet["packet_id"]:
        raise ContractError("critic: packet_id mismatch")
    for index, issue in enumerate(response["issues"]):
        _validate_references(
            packet,
            issue["source_ids"],
            [],
            path=f"critic.issues[{index}]",
            require_source=False,
        )
    _validate_references(
        packet,
        response["approved_source_ids"],
        [],
        path="critic.approved_source_ids",
        require_source=response["verdict"] == "approve",
    )
    original = committee["portfolio_classification"]
    downgrade = response["downgrade_to"]
    if _CLASSIFICATION_RANK[downgrade] > _CLASSIFICATION_RANK[original]:
        raise ContractError("critic: critic cannot upgrade a classification")
    if response["automatic_action_allowed"] is not False:
        raise ContractError("critic: automatic action must remain false")
    _assert_no_sensitive_markers(response, "critic")
    return response


def decimal_round(value: Any, places: str = "0.01") -> Decimal:
    try:
        parsed = Decimal(str(value))
        if not parsed.is_finite():
            raise ContractError(f"not a finite decimal: {value!r}")
        return parsed.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(f"not a finite decimal: {value!r}") from exc


def reconcile_calculations(
    packet: dict[str, Any], referenced_calculation_ids: list[str]
) -> None:
    calculations = {
        row["calculation_id"]: row for row in packet.get("calculations", [])
    }
    for calculation_id in referenced_calculation_ids:
        row = calculations.get(calculation_id)
        if row is None:
            raise ContractError(f"calculation not found: {calculation_id}")
        if row.get("reconciled") is not True:
            raise ContractError(f"calculation is not reconciled: {calculation_id}")
        if not row.get("unit") or not row.get("period"):
            raise ContractError(f"calculation lacks unit/period: {calculation_id}")
        supplied = decimal_round(row.get("value"))
        recomputed = decimal_round(row.get("recomputed_value"))
        if supplied != recomputed:
            raise ContractError(f"calculation mismatch: {calculation_id}")


def adjudicate(
    packet: dict[str, Any],
    analyst: dict[str, Any],
    committee: dict[str, Any],
    critic: dict[str, Any] | None,
    *,
    distinct_valid_closes: int = 1,
    mode: str = "shadow",
) -> dict[str, Any]:
    """Return a deterministic, fail-closed research classification.

    The returned object is never an order and cannot authorize automatic action.
    Shadow mode can never affect the canonical decision or email.
    """

    validate_analyst(packet, analyst)
    validate_committee(packet, committee)
    proposed = committee["portfolio_classification"]
    transition = proposed in TRANSITION_CLASSIFICATIONS
    critic_required = transition or committee["material_thesis_break"]
    reasons: list[str] = []

    if critic is not None:
        validate_critic(packet, committee, critic)
    elif critic_required:
        reasons.append("critic_required_but_missing")

    calculation_ids = sorted(
        {
            calculation_id
            for row in committee["ticker_decisions"]
            for calculation_id in row["calculation_ids"]
        }
    )
    try:
        reconcile_calculations(packet, calculation_ids)
    except ContractError as exc:
        reasons.append(str(exc))

    gates = packet["gates"]
    always_required = (
        "market_data_current",
        "account_state_consistent",
        "point_in_time_safe",
    )
    transition_required = (
        "sec_held_coverage_complete",
        "fundamental_held_coverage_complete",
        "filing_artifact_provenance_complete",
    )
    for gate in always_required:
        if gates.get(gate) is not True:
            reasons.append(f"hard_gate_failed:{gate}")
    if transition:
        for gate in transition_required:
            if gates.get(gate) is not True:
                reasons.append(f"transition_gate_failed:{gate}")

    if analyst["prompt_injection_detected"]:
        reasons.append("prompt_injection_detected")
    if packet["gates"].get("prompt_injection_text_detected") is True:
        reasons.append("prompt_injection_text_detected")
    if committee["data_sufficiency"] == "insufficient":
        reasons.append("committee_data_insufficient")

    effective = proposed
    if critic is not None:
        critic_passes = all(
            critic[field] is True
            for field in (
                "factual_grounding_pass",
                "citation_integrity_pass",
                "numeric_reconciliation_pass",
                "long_term_reasoning_pass",
                "action_proportionality_pass",
                "policy_boundary_pass",
            )
        )
        if critic["verdict"] != "approve" or not critic_passes:
            effective = critic["downgrade_to"]
            reasons.append(f"critic_{critic['verdict']}")

    if (
        effective in {"paper_trade_candidate", "real_trade_candidate"}
        and distinct_valid_closes < 2
    ):
        effective = "watchlist"
        reasons.append("two_distinct_valid_closes_not_met")

    if reasons and effective in TRANSITION_CLASSIFICATIONS:
        effective = "abstain"
    fatal_validation_failure = any(
        reason.startswith("hard_gate_failed:")
        or reason.startswith("calculation ")
        or reason.startswith("not a finite decimal:")
        or reason
        in {"prompt_injection_detected", "prompt_injection_text_detected"}
        for reason in reasons
    )
    if fatal_validation_failure:
        effective = "abstain"

    accepted = not reasons or (
        effective in NO_ACTION_CLASSIFICATIONS
        and not any(
            reason.startswith("hard_gate_failed:")
            or reason.startswith("calculation ")
            or reason
            in {"prompt_injection_detected", "prompt_injection_text_detected"}
            for reason in reasons
        )
    )
    human_review_required = effective in TRANSITION_CLASSIFICATIONS or any(
        reason.startswith("transition_gate_failed:")
        or reason.startswith("critic_")
        or reason in {"prompt_injection_detected", "prompt_injection_text_detected"}
        for reason in reasons
    )
    return {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "mode": mode,
        "validation_passed": accepted,
        "proposed_classification": proposed,
        "effective_classification": effective,
        "critic_required": critic_required,
        "critic_present": critic is not None,
        "distinct_valid_closes": distinct_valid_closes,
        "reasons": sorted(set(reasons)),
        "headline": committee["headline"],
        "decisive_advice": committee["decisive_advice"],
        "confidence_pct": committee["confidence_pct"],
        "ticker_decisions": committee["ticker_decisions"],
        "human_review_required": human_review_required,
        "automatic_action_allowed": False,
        "canonical_effect": False,
        "email_eligible": False,
        "broker_connected": False,
        "order_code_created": False,
        "trade_placed": False,
    }


def response_schema(role: str) -> dict[str, Any]:
    schemas = {
        "analyst": ANALYST_SCHEMA,
        "committee": COMMITTEE_SCHEMA,
        "critic": CRITIC_SCHEMA,
    }
    try:
        return copy.deepcopy(schemas[role])
    except KeyError as exc:
        raise ContractError(f"unknown model role: {role}") from exc
