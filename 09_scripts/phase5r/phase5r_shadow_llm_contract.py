#!/usr/bin/env python3
"""Closed contracts for the noncanonical Phase 5R SHADOW_LLM evaluator."""

from __future__ import annotations

import copy
import json
import re
import stat
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from phase5r_daily_common import canonical_sha256
from phase5r_packet_contract import validate_packet


ANALYST_SCHEMA_VERSION = "phase5r_shadow_analyst_v1"
CRITIC_SCHEMA_VERSION = "phase5r_shadow_critic_v1"
JUDGE_SCHEMA_VERSION = "phase5r_shadow_blind_judge_v1"
BUNDLE_SCHEMA_VERSION = "phase5r_shadow_bundle_v2"
LEGACY_BUNDLE_SCHEMA_VERSION = "phase5r_shadow_bundle_v1"

SEMANTIC_STATES = {
    "strengthened",
    "weakened",
    "unchanged",
    "mixed",
    "insufficient",
}
CLAIM_CATEGORIES = {
    "guidance",
    "risk",
    "accounting",
    "unit_economics",
    "competition",
    "capital_allocation",
    "dilution",
    "customer_concentration",
    "fundamental_trend",
    "evidence_conflict",
    "other",
}
CLAIM_DIRECTIONS = {"positive", "negative", "neutral", "mixed", "unknown"}
MATERIALITIES = {"low", "medium", "high"}
NOVELTY_LABELS = {
    "baseline_already_captures",
    "new_evidence",
    "new_contradiction",
    "new_qualification",
}
CRITIC_VERDICTS = {"supported", "partial", "unsupported", "not_assessable"}
CRITIC_TICKER_DECISIONS = {"accept", "qualify", "abstain"}
JUDGE_SUPPORT = {"supported", "partial", "unsupported", "not_assessable"}
JUDGE_MATERIALITY = {"material", "nonmaterial", "not_assessable"}
BASELINE_CAPTURE = {"yes", "no", "not_assessable"}

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{1,159}$")
_CLAIM_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)?")
_IMPERATIVE = re.compile(
    r"(?:\b(?:should|must|recommend(?:s|ed|ing)?)\s+"
    r"(?:buy|sell|add|trim|exit|order)\b|"
    r"\b(?:buy|sell)\s+(?:the\s+)?(?:stock|shares?)\b|"
    r"买入|卖出|增仓|加仓|减仓|清仓|下单)",
    re.IGNORECASE,
)


class ShadowContractError(ValueError):
    """A packet or model artifact violated the closed shadow contract."""


def _object(value: Any, *, label: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ShadowContractError(f"{label} fields do not match the contract")
    return value


def _text(
    value: Any,
    *,
    label: str,
    maximum: int = 2000,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ShadowContractError(f"{label} must be text")
    normalized = " ".join(value.split())
    if not normalized and not allow_empty:
        raise ShadowContractError(f"{label} must not be empty")
    if len(normalized) > maximum or "\x00" in normalized:
        raise ShadowContractError(f"{label} is outside the text boundary")
    return normalized


def _identifier(value: Any, *, label: str) -> str:
    normalized = _text(value, label=label, maximum=160)
    if _IDENTIFIER.fullmatch(normalized) is None:
        raise ShadowContractError(f"{label} is not a valid identifier")
    return normalized


def _text_list(
    value: Any,
    *,
    label: str,
    maximum_items: int,
    allow_empty: bool = True,
) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ShadowContractError(f"{label} must be a bounded list")
    if not allow_empty and not value:
        raise ShadowContractError(f"{label} must not be empty")
    normalized = [
        _text(item, label=f"{label}[{index}]", maximum=500)
        for index, item in enumerate(value)
    ]
    if len(normalized) != len(set(normalized)):
        raise ShadowContractError(f"{label} must not contain duplicates")
    return normalized


def _identifier_list(
    value: Any,
    *,
    label: str,
    maximum_items: int,
    allow_empty: bool = True,
) -> list[str]:
    values = _text_list(
        value,
        label=label,
        maximum_items=maximum_items,
        allow_empty=allow_empty,
    )
    for item in values:
        if _IDENTIFIER.fullmatch(item) is None:
            raise ShadowContractError(f"{label} contains an invalid identifier")
    return values


def _enum(value: Any, *, label: str, allowed: set[str]) -> str:
    normalized = _text(value, label=label, maximum=80)
    if normalized not in allowed:
        raise ShadowContractError(f"{label} is outside the closed enum")
    return normalized


def _assert_nonimperative(text: str, *, label: str) -> None:
    if _IMPERATIVE.search(text):
        raise ShadowContractError(f"{label} contains prohibited action language")


def _read_regular_json(path: Path, *, maximum_bytes: int = 5_000_000) -> dict[str, Any]:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ShadowContractError("input must not be a symlink")
    target = expanded.resolve()
    metadata = target.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ShadowContractError("input must be a non-linked regular file")
    if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
        raise ShadowContractError("input file size is outside the boundary")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowContractError("input is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ShadowContractError("input JSON must be one object")
    return payload


def load_packet(path: Path) -> dict[str, Any]:
    packet = _read_regular_json(path)
    try:
        validate_packet(packet)
    except Exception as exc:
        raise ShadowContractError("evidence packet failed its canonical contract") from exc
    boundaries = packet.get("boundaries", {})
    required = {
        "research_only": True,
        "canonical_effect": False,
        "email_eligible": False,
        "automatic_action_allowed": False,
        "broker_connected": False,
        "order_code_available": False,
        "exact_account_dollars_included": False,
    }
    if any(boundaries.get(key) is not expected for key, expected in required.items()):
        raise ShadowContractError("evidence packet violates the shadow boundary")
    if packet.get("gates", {}).get("prompt_injection_text_detected") is True:
        raise ShadowContractError("live shadow rejects prompt-injection-marked packets")
    return packet


def _source_index(packet: dict[str, Any]) -> dict[str, dict[str, str]]:
    sources: dict[str, dict[str, str]] = {}
    for row in packet.get("source_catalog", []):
        if not isinstance(row, dict) or not row.get("source_id"):
            continue
        sources[str(row["source_id"])] = {
            "ticker": str(row.get("ticker", "")).upper(),
            "authority": str(row.get("authority", "")),
            "source_type": str(row.get("source_type", "")),
        }
    for row in packet.get("fundamental_observations", []):
        if not isinstance(row, dict) or not row.get("source_id"):
            continue
        sources.setdefault(
            str(row["source_id"]),
            {
                "ticker": str(row.get("ticker", "")).upper(),
                "authority": "primary_official",
                "source_type": "sec_xbrl_observation",
            },
        )
    for row in packet.get("research_context", []):
        if not isinstance(row, dict) or not row.get("source_id"):
            continue
        sources.setdefault(
            str(row["source_id"]),
            {
                "ticker": str(row.get("ticker", "")).upper(),
                "authority": "deterministic_derivative",
                "source_type": "research_context",
            },
        )
    return sources


def _calculation_index(packet: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in packet.get("calculations", []):
        if isinstance(row, dict) and row.get("calculation_id"):
            result[str(row["calculation_id"])] = str(row.get("ticker", "")).upper()
    return result


def _entity_tickers(packet: dict[str, Any]) -> set[str]:
    return {
        str(row.get("ticker", "")).upper()
        for row in packet.get("entities", [])
        if isinstance(row, dict) and row.get("ticker")
    }


def primary_source_registry(packet: dict[str, Any]) -> list[dict[str, str]]:
    """Expose only primary source identifiers needed to audit human omissions."""

    rows = []
    for source_id, source in _source_index(packet).items():
        if (
            source["authority"] == "primary_official"
            or source["source_type"].startswith("sec_")
            or source["source_type"].startswith("sec-")
        ):
            rows.append({"source_id": source_id, **source})
    return sorted(rows, key=lambda row: (row["ticker"], row["source_id"]))


def _finite_number(value: Any) -> Decimal | None:
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def build_deterministic_baseline(packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Give the judge the facts/calculations already available without an LLM.

    These are observations, not new investment opinions. Keeping limitations is
    essential: a number from an incomplete observation is not promoted to truth.
    """
    rows = copy.deepcopy(packet.get("research_context", []))
    for observation in packet.get("fundamental_observations", []):
        assertions = []
        for field, positive, negative in (
            ("net_income_latest", "positive GAAP net income", "GAAP net loss"),
            ("net_margin_pct", "positive net margin", "negative net margin"),
            ("revenue_yoy_pct", "revenue grew year over year", "revenue declined year over year"),
            ("fcf_margin_pct", "positive free cash flow margin", "negative free cash flow margin"),
        ):
            value = _finite_number(observation.get(field))
            if value is not None:
                assertions.append({"field": field, "value": str(value),
                                   "statement": positive if value > 0 else negative if value < 0 else "zero " + field})
        rows.append({
            "baseline_kind": "deterministic_fact_and_sign_checklist",
            "ticker": observation.get("ticker"),
            "period": observation.get("latest_frame"),
            "period_end": observation.get("latest_period_end"),
            "source_id": observation.get("source_id"),
            "facts_reference": "All same-ticker fields in fundamental_observations are already deterministic baseline facts, subject to their recorded quality/period limitations.",
            "data_quality": observation.get("data_quality"),
            "mechanical_sign_assertions": assertions,
            "interpretation": "Existing facts and simple signs are not incremental semantic discoveries; preserve input limitations.",
        })
    if packet.get("calculations"):
        rows.append({"baseline_kind": "existing_deterministic_calculation",
                     "reference": "All rows in semantic_view.calculations (including reconciled values, signs, changes and formulas) are baseline, not new semantic research."})
    return rows


def deterministic_claim_check(packet: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    """Conservative one-fact sign check, never a generic semantic truth judge.

    Complex, causal, segment-level, forward-looking and ambiguous-period claims
    are not mechanically resolved. Matching a sign never validates those extras.
    """
    statement = str(claim.get("statement", "")).lower()
    base = {"checkable": False, "captured": False, "support": "not_assessable",
            "reason": "not_a_supported_single_fact_sign_template"}
    fcf = re.fullmatch(r"(?:trailing )?free cash flow margin (?:was|remained) (negative|positive)( despite positive quarterly net income)?\.?", statement)
    if fcf:
        for calculation in packet.get("calculations", []):
            if calculation.get("ticker") != claim.get("ticker") or calculation.get("metric") not in {"valuation_free_cash_flow_margin_pct", "free_cash_flow_margin_pct", "fcf_margin_pct"}:
                continue
            value = _finite_number(calculation.get("value"))
            if calculation.get("reconciled") is not True or value is None or value != _finite_number(calculation.get("recomputed_value")):
                continue
            input_periods = {item.get("period") for item in calculation.get("inputs", [])}
            period_matches = claim.get("period") == calculation.get("period") or input_periods == {claim.get("period")}
            if not period_matches:
                continue
            supported = value < 0 if fcf.group(1) == "negative" else value > 0
            if fcf.group(2):
                observation = next((row for row in packet.get("fundamental_observations", []) if row.get("ticker") == claim.get("ticker") and row.get("data_quality") == "ok" and claim.get("period") == "TTM through " + str(row.get("latest_period_end"))), None)
                income = _finite_number(observation.get("net_income_latest")) if observation else None
                if income is None:
                    return {**base, "reason": "quarterly_net_income_period_or_quality_unverified"}
                supported = supported and income > 0
            return {"checkable": True, "captured": supported,
                    "support": "supported" if supported else "unsupported",
                    "reason": "existing_reconciled_cash_flow_sign_and_optional_same_end_net_income",
                    "ticker": claim["ticker"], "period": claim["period"],
                    "field": "fcf_margin_pct", "operator": "lt" if fcf.group(1) == "negative" else "gt",
                    "threshold": "0", "observed_value": str(value),
                    "calculation_id": calculation.get("calculation_id"),
                    "source_ids": calculation.get("source_ids", [])}
        return {**base, "reason": "reconciled_exact_period_cash_flow_calculation_required"}
    if re.search(r"\b(?:expects?|outlook|future|may|could|will|because|despite|while|although|but|and|continued? operating|segment|reality labs|non-gaap)\b", statement):
        return base
    match = None
    # Restrict net-income phrases so operating losses are never inferred from
    # net income; reject embedded numeric/compound assertions as out of scope.
    if re.search(r"\b(?:gaap net[- ]?(?:income )?loss|gaap net loss|loss-making on a gaap net-income basis|net income (?:was|remained) negative|negative net margin)\b", statement):
        match = ("net_margin_pct", "lt", Decimal(0))
    elif re.search(r"\b(?:positive (?:gaap )?net income|positive net margin)\b", statement):
        match = ("net_margin_pct", "gt", Decimal(0))
    elif re.search(r"\brevenue (?:grew|increased|declined|decreased) year.over.year\b", statement):
        match = ("revenue_yoy_pct", "lt" if re.search(r"declined|decreased", statement) else "gt", Decimal(0))
    if match is None or _NUMBER.search(statement):
        return base
    field, operator, threshold = match
    for observation in packet.get("fundamental_observations", []):
        if observation.get("ticker") != claim.get("ticker"):
            continue
        if claim.get("period") not in {observation.get("latest_frame"), observation.get("latest_period_end")}:
            continue
        if observation.get("data_quality") != "ok":
            return {**base, "reason": "deterministic_observation_quality_not_ok"}
        value = _finite_number(observation.get(field))
        if value is None:
            continue
        supported = value < threshold if operator == "lt" else value > threshold
        return {"checkable": True, "captured": supported,
                "support": "supported" if supported else "unsupported",
                "reason": "existing_deterministic_single_fact_sign",
                "ticker": claim["ticker"], "period": claim["period"],
                "field": field, "operator": operator, "threshold": str(threshold),
                "observed_value": str(value), "source_id": observation.get("source_id", "")}
    return {**base, "reason": "exact_period_and_valid_observation_required"}


def deterministic_claim_capture(packet: dict[str, Any], claim: dict[str, Any]) -> bool:
    return deterministic_claim_check(packet, claim)["captured"]


def build_semantic_view(packet: dict[str, Any]) -> dict[str, Any]:
    """Return the only packet view eligible for external shadow inference."""

    source_rows = []
    for source in packet.get("source_catalog", []):
        if not isinstance(source, dict):
            continue
        source_rows.append(
            {
                key: copy.deepcopy(source.get(key))
                for key in (
                    "source_id",
                    "ticker",
                    "source_type",
                    "authority",
                    "accepted_at",
                    "source_url",
                    "locator",
                    "content_sha256",
                    "excerpt_text",
                )
            }
        )
    return {
        "view_schema_version": "phase5r_shadow_semantic_view_v2",
        "packet_identity": {
            key: packet.get(key)
            for key in (
                "schema_version",
                "packet_id",
                "as_of_et",
                "cycle_date",
                "decision_fingerprint",
            )
        },
        "entities": copy.deepcopy(packet.get("entities", [])),
        "gates": copy.deepcopy(packet.get("gates", {})),
        "fundamental_observations": copy.deepcopy(
            packet.get("fundamental_observations", [])
        ),
        "filing_evidence": copy.deepcopy(packet.get("filing_evidence", [])),
        "deterministic_baseline": build_deterministic_baseline(packet),
        "evidence_freshness": copy.deepcopy(packet.get("evidence_freshness", [])),
        "calculations": copy.deepcopy(packet.get("calculations", [])),
        "sources": source_rows,
        "boundaries": {
            "semantic_research_only": True,
            "canonical_effect": False,
            "email_eligible": False,
            "exact_account_dollars_included": False,
            "tools_allowed": False,
        },
    }


def _provider_schema_subset(value: Any) -> Any:
    """Keep provider-side schemas in the portable Structured Outputs subset.

    The Python validators below remain the authority for length, uniqueness,
    identifier, citation, and action-language constraints.
    """

    if isinstance(value, list):
        return [_provider_schema_subset(item) for item in value]
    if not isinstance(value, dict):
        return value
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in {"minLength", "maxLength", "uniqueItems"}:
            continue
        if key == "const":
            result["enum"] = [item]
            continue
        result[key] = _provider_schema_subset(item)
    return result


def analyst_schema(
    maximum_claims: int = 24,
    *,
    packet_id: str | None = None,
    entity_tickers: list[str] | None = None,
) -> dict[str, Any]:
    claim = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{2,63}$"},
            "ticker": {"type": "string", "minLength": 1, "maxLength": 16},
            "category": {"type": "string", "enum": sorted(CLAIM_CATEGORIES)},
            "direction": {"type": "string", "enum": sorted(CLAIM_DIRECTIONS)},
            "materiality": {"type": "string", "enum": sorted(MATERIALITIES)},
            "novelty": {"type": "string", "enum": sorted(NOVELTY_LABELS)},
            "statement": {"type": "string", "minLength": 1, "maxLength": 1200},
            "period": {"type": "string", "minLength": 1, "maxLength": 160},
            "source_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 2, "maxLength": 160},
            },
            "calculation_ids": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 2, "maxLength": 160},
            },
            "uncertainty": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": [
            "claim_id",
            "ticker",
            "category",
            "direction",
            "materiality",
            "novelty",
            "statement",
            "period",
            "source_ids",
            "calculation_ids",
            "uncertainty",
        ],
    }
    ticker_review = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ticker": {"type": "string", "minLength": 1, "maxLength": 16},
            "semantic_state": {"type": "string", "enum": sorted(SEMANTIC_STATES)},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
            "key_claim_ids": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9_-]{2,63}$",
                },
            },
            "missing_evidence": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1, "maxLength": 300},
            },
        },
        "required": [
            "ticker",
            "semantic_state",
            "confidence",
            "summary",
            "key_claim_ids",
            "missing_evidence",
        ],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": ANALYST_SCHEMA_VERSION},
            "packet_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "claims": {
                "type": "array",
                "maxItems": maximum_claims,
                "items": claim,
            },
            "ticker_reviews": {"type": "array", "items": ticker_review},
        },
        "required": ["schema_version", "packet_id", "claims", "ticker_reviews"],
    }
    if packet_id:
        schema["properties"]["packet_id"] = {"type": "string", "enum": [packet_id]}
    if entity_tickers:
        tickers = sorted(set(entity_tickers))
        claim["properties"]["ticker"] = {"type": "string", "enum": tickers}
        ticker_review["properties"]["ticker"] = {"type": "string", "enum": tickers}
        schema["properties"]["ticker_reviews"].update(
            {"minItems": len(tickers), "maxItems": len(tickers)}
        )
    return _provider_schema_subset(schema)


def critic_schema(
    maximum_omissions: int = 12,
    *,
    packet_id: str | None = None,
    analyst_output_sha256: str | None = None,
    claim_ids: list[str] | None = None,
    entity_tickers: list[str] | None = None,
) -> dict[str, Any]:
    claim_review = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claim_id": {"type": "string", "minLength": 3, "maxLength": 64},
            "verdict": {"type": "string", "enum": sorted(CRITIC_VERDICTS)},
            "reason": {"type": "string", "minLength": 1, "maxLength": 800},
            "source_ids": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 2, "maxLength": 160},
            },
        },
        "required": ["claim_id", "verdict", "reason", "source_ids"],
    }
    omission = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "omission_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{2,63}$"},
            "ticker": {"type": "string", "minLength": 1, "maxLength": 16},
            "category": {"type": "string", "enum": sorted(CLAIM_CATEGORIES)},
            "materiality": {"type": "string", "enum": sorted(MATERIALITIES)},
            "statement": {"type": "string", "minLength": 1, "maxLength": 1200},
            "period": {"type": "string", "minLength": 1, "maxLength": 160},
            "source_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 2, "maxLength": 160},
            },
            "calculation_ids": {
                "type": "array",
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 2, "maxLength": 160},
            },
        },
        "required": [
            "omission_id",
            "ticker",
            "category",
            "materiality",
            "statement",
            "period",
            "source_ids",
            "calculation_ids",
        ],
    }
    ticker_review = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "ticker": {"type": "string", "minLength": 1, "maxLength": 16},
            "decision": {"type": "string", "enum": sorted(CRITIC_TICKER_DECISIONS)},
            "reason_claim_ids": {
                "type": "array",
                "maxItems": 12,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 3, "maxLength": 64},
            },
            "reason": {"type": "string", "minLength": 1, "maxLength": 800},
        },
        "required": ["ticker", "decision", "reason_claim_ids", "reason"],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": CRITIC_SCHEMA_VERSION},
            "packet_id": {"type": "string", "minLength": 64, "maxLength": 64},
            "analyst_output_sha256": {"type": "string", "minLength": 64, "maxLength": 64},
            "claim_reviews": {"type": "array", "items": claim_review},
            "omissions": {
                "type": "array",
                "maxItems": maximum_omissions,
                "items": omission,
            },
            "ticker_reviews": {"type": "array", "items": ticker_review},
        },
        "required": [
            "schema_version",
            "packet_id",
            "analyst_output_sha256",
            "claim_reviews",
            "omissions",
            "ticker_reviews",
        ],
    }
    if packet_id:
        schema["properties"]["packet_id"] = {"type": "string", "enum": [packet_id]}
    if analyst_output_sha256:
        schema["properties"]["analyst_output_sha256"] = {
            "type": "string",
            "enum": [analyst_output_sha256],
        }
    if claim_ids is not None:
        claim_count = len(claim_ids)
        schema["properties"]["claim_reviews"].update(
            {"minItems": claim_count, "maxItems": claim_count}
        )
        if claim_ids:
            claim_review["properties"]["claim_id"] = {
                "type": "string",
                "enum": sorted(set(claim_ids)),
            }
    if entity_tickers:
        tickers = sorted(set(entity_tickers))
        omission["properties"]["ticker"] = {"type": "string", "enum": tickers}
        ticker_review["properties"]["ticker"] = {"type": "string", "enum": tickers}
        schema["properties"]["ticker_reviews"].update(
            {"minItems": len(tickers), "maxItems": len(tickers)}
        )
    return _provider_schema_subset(schema)


def build_blind_judge_target(
    analyst: dict[str, Any], critic: dict[str, Any] | None,
    *, packet: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    """Create a deterministic candidate set without origin or model labels."""

    candidates: list[dict[str, Any]] = []
    mapping: dict[str, dict[str, str]] = {}

    def add_item(item: dict[str, Any], *, item_id: str, origin: str) -> None:
        blind_id = "blind_" + canonical_sha256(
            {
                "item_id": item_id,
                "ticker": item["ticker"],
                "statement": item["statement"],
                "period": item["period"],
                "source_ids": item["source_ids"],
                "calculation_ids": item["calculation_ids"],
            }
        )[:20]
        if blind_id in mapping:
            raise ShadowContractError("blind judge candidate ids are not unique")
        mapping[blind_id] = {"item_id": item_id, "origin": origin}
        candidates.append(
            {
                "blind_item_id": blind_id,
                "ticker": item["ticker"],
                "statement": item["statement"],
                "period": item["period"],
                "source_ids": item["source_ids"],
                "calculation_ids": item["calculation_ids"],
            }
        )

    for claim in analyst["claims"]:
        add_item(claim, item_id=claim["claim_id"], origin="analyst")
    if critic is not None:
        for omission in critic["omissions"]:
            add_item(
                omission,
                item_id=omission["omission_id"],
                origin="critic_omission",
            )
    if packet is not None:
        for observation in sorted(packet.get("fundamental_observations", []), key=lambda row: str(row.get("ticker", ""))):
            value = _finite_number(observation.get("net_margin_pct"))
            if value is None or observation.get("data_quality") != "ok" or not observation.get("latest_frame") or not observation.get("source_id"):
                continue
            for positive in (False, True):
                item_id = "control_net_margin_" + ("positive" if positive else "negative")
                control = {"ticker": observation["ticker"],
                           "statement": "Positive net margin was reported." if positive else "Net income was negative.",
                           "period": observation["latest_frame"],
                           "source_ids": [observation["source_id"]], "calculation_ids": []}
                add_item(control, item_id=item_id, origin="deterministic_control")
                binding = next(row for row in mapping.values() if row["item_id"] == item_id)
                binding["expected_support"] = "supported" if (value > 0 if positive else value < 0) else "unsupported"
            break
    candidates.sort(key=lambda row: row["blind_item_id"])
    target = {
        "candidates": candidates,
        "candidate_set_sha256": canonical_sha256(candidates),
    }
    return target, mapping


def judge_schema(
    maximum_missed_issues: int = 12,
    *,
    packet_id: str | None = None,
    candidate_set_sha256: str | None = None,
    blind_item_ids: list[str] | None = None,
    entity_tickers: list[str] | None = None,
) -> dict[str, Any]:
    item_review = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "blind_item_id": {"type": "string"},
            "support": {"type": "string", "enum": sorted(JUDGE_SUPPORT)},
            "materiality": {"type": "string", "enum": sorted(JUDGE_MATERIALITY)},
            "baseline_captured": {"type": "string", "enum": sorted(BASELINE_CAPTURE)},
            "reason": {"type": "string"},
            "source_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "blind_item_id",
            "support",
            "materiality",
            "baseline_captured",
            "reason",
            "source_ids",
        ],
    }
    missed_issue = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "issue_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{2,63}$"},
            "ticker": {"type": "string"},
            "category": {"type": "string", "enum": sorted(CLAIM_CATEGORIES)},
            "materiality": {"type": "string", "enum": ["medium", "high"]},
            "statement": {"type": "string"},
            "period": {"type": "string"},
            "source_ids": {"type": "array", "items": {"type": "string"}},
            "calculation_ids": {"type": "array", "items": {"type": "string"}},
            "baseline_captured": {"type": "string", "enum": sorted(BASELINE_CAPTURE)},
        },
        "required": [
            "issue_id",
            "ticker",
            "category",
            "materiality",
            "statement",
            "period",
            "source_ids",
            "calculation_ids",
            "baseline_captured",
        ],
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "schema_version": {"type": "string", "const": JUDGE_SCHEMA_VERSION},
            "packet_id": {"type": "string"},
            "candidate_set_sha256": {"type": "string"},
            "item_reviews": {"type": "array", "items": item_review},
            "missed_material_issues": {
                "type": "array",
                "maxItems": maximum_missed_issues,
                "items": missed_issue,
            },
            "overall_confidence": {
                "type": "string",
                "enum": ["low", "medium", "high"],
            },
        },
        "required": [
            "schema_version",
            "packet_id",
            "candidate_set_sha256",
            "item_reviews",
            "missed_material_issues",
            "overall_confidence",
        ],
    }
    if packet_id:
        schema["properties"]["packet_id"] = {"type": "string", "enum": [packet_id]}
    if candidate_set_sha256:
        schema["properties"]["candidate_set_sha256"] = {
            "type": "string",
            "enum": [candidate_set_sha256],
        }
    if blind_item_ids is not None:
        count = len(blind_item_ids)
        schema["properties"]["item_reviews"].update(
            {"minItems": count, "maxItems": count}
        )
        if blind_item_ids:
            item_review["properties"]["blind_item_id"] = {
                "type": "string",
                "enum": sorted(set(blind_item_ids)),
            }
    if entity_tickers:
        missed_issue["properties"]["ticker"] = {
            "type": "string",
            "enum": sorted(set(entity_tickers)),
        }
    return _provider_schema_subset(schema)


def _validate_claim(
    packet: dict[str, Any],
    claim: Any,
    *,
    label: str,
    id_field: str,
    allowed_fields: set[str],
) -> tuple[str, str, list[str], list[str]]:
    row = _object(claim, label=label, fields=allowed_fields)
    item_id = _text(row[id_field], label=f"{label}.{id_field}", maximum=64)
    if _CLAIM_ID.fullmatch(item_id) is None:
        raise ShadowContractError(f"{label}.{id_field} is invalid")
    ticker = _text(row["ticker"], label=f"{label}.ticker", maximum=16).upper()
    if ticker not in _entity_tickers(packet):
        raise ShadowContractError(f"{label}.ticker is not a packet entity")
    _enum(row["category"], label=f"{label}.category", allowed=CLAIM_CATEGORIES)
    if "direction" in row:
        _enum(row["direction"], label=f"{label}.direction", allowed=CLAIM_DIRECTIONS)
    _enum(row["materiality"], label=f"{label}.materiality", allowed=MATERIALITIES)
    if "novelty" in row:
        _enum(row["novelty"], label=f"{label}.novelty", allowed=NOVELTY_LABELS)
    statement = _text(row["statement"], label=f"{label}.statement", maximum=1200)
    _assert_nonimperative(statement, label=f"{label}.statement")
    _text(row["period"], label=f"{label}.period", maximum=160)
    if "uncertainty" in row:
        uncertainty = _text(
            row["uncertainty"], label=f"{label}.uncertainty", maximum=500
        )
        _assert_nonimperative(uncertainty, label=f"{label}.uncertainty")
    source_ids = _identifier_list(
        row["source_ids"],
        label=f"{label}.source_ids",
        maximum_items=8,
        allow_empty=False,
    )
    calculation_ids = _identifier_list(
        row["calculation_ids"],
        label=f"{label}.calculation_ids",
        maximum_items=8,
    )
    source_index = _source_index(packet)
    if any(source_id not in source_index for source_id in source_ids):
        raise ShadowContractError(f"{label} cites an unknown packet source")
    if any(
        source_index[source_id]["ticker"] not in {"", ticker}
        for source_id in source_ids
    ):
        raise ShadowContractError(f"{label} cites another ticker's source")
    primary = any(
        source_index[source_id]["authority"] == "primary_official"
        or source_index[source_id]["source_type"].startswith("sec_")
        or source_index[source_id]["source_type"].startswith("sec-")
        for source_id in source_ids
    )
    if not primary:
        raise ShadowContractError(f"{label} lacks a same-ticker primary source")
    calculation_index = _calculation_index(packet)
    if any(calculation_id not in calculation_index for calculation_id in calculation_ids):
        raise ShadowContractError(f"{label} cites an unknown calculation")
    if any(
        calculation_index[calculation_id] not in {"", ticker}
        for calculation_id in calculation_ids
    ):
        raise ShadowContractError(f"{label} cites another ticker's calculation")
    if _NUMBER.search(statement) and not calculation_ids:
        raise ShadowContractError(
            f"{label} contains numeric prose without a deterministic calculation"
        )
    return item_id, ticker, source_ids, calculation_ids


def validate_analyst(
    packet: dict[str, Any],
    payload: dict[str, Any],
    *,
    maximum_claims: int = 24,
) -> None:
    result = _object(
        payload,
        label="analyst",
        fields={"schema_version", "packet_id", "claims", "ticker_reviews"},
    )
    if result["schema_version"] != ANALYST_SCHEMA_VERSION:
        raise ShadowContractError("analyst schema version is invalid")
    if result["packet_id"] != packet.get("packet_id"):
        raise ShadowContractError("analyst packet binding is invalid")
    claims = result["claims"]
    if not isinstance(claims, list) or len(claims) > maximum_claims:
        raise ShadowContractError("analyst claims are not a bounded list")
    claim_tickers: dict[str, str] = {}
    for index, claim in enumerate(claims):
        claim_id, ticker, _, _ = _validate_claim(
            packet,
            claim,
            label=f"analyst.claims[{index}]",
            id_field="claim_id",
            allowed_fields={
                "claim_id",
                "ticker",
                "category",
                "direction",
                "materiality",
                "novelty",
                "statement",
                "period",
                "source_ids",
                "calculation_ids",
                "uncertainty",
            },
        )
        if claim_id in claim_tickers:
            raise ShadowContractError("analyst claim ids must be unique")
        claim_tickers[claim_id] = ticker
    reviews = result["ticker_reviews"]
    tickers = _entity_tickers(packet)
    if not isinstance(reviews, list) or len(reviews) != len(tickers):
        raise ShadowContractError("analyst must review every packet ticker exactly once")
    seen: set[str] = set()
    for index, review in enumerate(reviews):
        row = _object(
            review,
            label=f"analyst.ticker_reviews[{index}]",
            fields={
                "ticker",
                "semantic_state",
                "confidence",
                "summary",
                "key_claim_ids",
                "missing_evidence",
            },
        )
        ticker = _text(row["ticker"], label="analyst review ticker", maximum=16).upper()
        if ticker in seen or ticker not in tickers:
            raise ShadowContractError("analyst ticker reviews are not one-per-entity")
        seen.add(ticker)
        state = _enum(
            row["semantic_state"],
            label="analyst semantic_state",
            allowed=SEMANTIC_STATES,
        )
        _enum(
            row["confidence"],
            label="analyst confidence",
            allowed={"low", "medium", "high"},
        )
        summary = _text(row["summary"], label="analyst summary", maximum=1000)
        _assert_nonimperative(summary, label="analyst summary")
        key_claim_ids = _identifier_list(
            row["key_claim_ids"],
            label="analyst key_claim_ids",
            maximum_items=8,
        )
        if any(claim_tickers.get(claim_id) != ticker for claim_id in key_claim_ids):
            raise ShadowContractError("analyst review references an invalid claim")
        _text_list(
            row["missing_evidence"],
            label="analyst missing_evidence",
            maximum_items=8,
        )
        if state in {"strengthened", "weakened", "mixed"} and not key_claim_ids:
            raise ShadowContractError("changed analyst review needs a key claim")
    if seen != tickers:
        raise ShadowContractError("analyst ticker coverage is incomplete")


def validate_critic(
    packet: dict[str, Any],
    analyst: dict[str, Any],
    payload: dict[str, Any],
    *,
    maximum_omissions: int = 12,
) -> None:
    result = _object(
        payload,
        label="critic",
        fields={
            "schema_version",
            "packet_id",
            "analyst_output_sha256",
            "claim_reviews",
            "omissions",
            "ticker_reviews",
        },
    )
    if result["schema_version"] != CRITIC_SCHEMA_VERSION:
        raise ShadowContractError("critic schema version is invalid")
    if result["packet_id"] != packet.get("packet_id"):
        raise ShadowContractError("critic packet binding is invalid")
    if result["analyst_output_sha256"] != canonical_sha256(analyst):
        raise ShadowContractError("critic analyst binding is invalid")
    analyst_claims = {row["claim_id"]: row for row in analyst["claims"]}
    claim_reviews = result["claim_reviews"]
    if not isinstance(claim_reviews, list) or len(claim_reviews) != len(analyst_claims):
        raise ShadowContractError("critic must review every analyst claim exactly once")
    reviewed: set[str] = set()
    for index, review in enumerate(claim_reviews):
        row = _object(
            review,
            label=f"critic.claim_reviews[{index}]",
            fields={"claim_id", "verdict", "reason", "source_ids"},
        )
        claim_id = _text(row["claim_id"], label="critic claim_id", maximum=64)
        if claim_id in reviewed or claim_id not in analyst_claims:
            raise ShadowContractError("critic claim coverage is invalid")
        reviewed.add(claim_id)
        _enum(row["verdict"], label="critic verdict", allowed=CRITIC_VERDICTS)
        reason = _text(row["reason"], label="critic reason", maximum=800)
        _assert_nonimperative(reason, label="critic reason")
        source_ids = _identifier_list(
            row["source_ids"],
            label="critic source_ids",
            maximum_items=8,
        )
        if not set(source_ids).issubset(set(analyst_claims[claim_id]["source_ids"])):
            raise ShadowContractError("critic review cites outside the analyst claim")
    omissions = result["omissions"]
    if not isinstance(omissions, list) or len(omissions) > maximum_omissions:
        raise ShadowContractError("critic omissions are not a bounded list")
    omission_tickers: dict[str, str] = {}
    for index, omission in enumerate(omissions):
        omission_id, ticker, _, _ = _validate_claim(
            packet,
            omission,
            label=f"critic.omissions[{index}]",
            id_field="omission_id",
            allowed_fields={
                "omission_id",
                "ticker",
                "category",
                "materiality",
                "statement",
                "period",
                "source_ids",
                "calculation_ids",
            },
        )
        if omission_id in omission_tickers or omission_id in analyst_claims:
            raise ShadowContractError("critic omission ids must be globally unique")
        omission_tickers[omission_id] = ticker
    tickers = _entity_tickers(packet)
    reviews = result["ticker_reviews"]
    if not isinstance(reviews, list) or len(reviews) != len(tickers):
        raise ShadowContractError("critic must review every packet ticker exactly once")
    seen: set[str] = set()
    all_items = {
        **{claim_id: str(row["ticker"]).upper() for claim_id, row in analyst_claims.items()},
        **omission_tickers,
    }
    for index, review in enumerate(reviews):
        row = _object(
            review,
            label=f"critic.ticker_reviews[{index}]",
            fields={"ticker", "decision", "reason_claim_ids", "reason"},
        )
        ticker = _text(row["ticker"], label="critic review ticker", maximum=16).upper()
        if ticker in seen or ticker not in tickers:
            raise ShadowContractError("critic ticker reviews are not one-per-entity")
        seen.add(ticker)
        _enum(
            row["decision"],
            label="critic ticker decision",
            allowed=CRITIC_TICKER_DECISIONS,
        )
        ids = _identifier_list(
            row["reason_claim_ids"],
            label="critic reason_claim_ids",
            maximum_items=12,
        )
        if any(all_items.get(item_id) != ticker for item_id in ids):
            raise ShadowContractError("critic ticker review references an invalid item")
        reason = _text(row["reason"], label="critic ticker reason", maximum=800)
        _assert_nonimperative(reason, label="critic ticker reason")


def validate_judge(
    packet: dict[str, Any],
    target: dict[str, Any],
    payload: dict[str, Any],
    *,
    maximum_missed_issues: int = 12,
) -> None:
    result = _object(
        payload,
        label="judge",
        fields={
            "schema_version",
            "packet_id",
            "candidate_set_sha256",
            "item_reviews",
            "missed_material_issues",
            "overall_confidence",
        },
    )
    if result["schema_version"] != JUDGE_SCHEMA_VERSION:
        raise ShadowContractError("judge schema version is invalid")
    if result["packet_id"] != packet.get("packet_id"):
        raise ShadowContractError("judge packet binding is invalid")
    if result["candidate_set_sha256"] != target.get("candidate_set_sha256"):
        raise ShadowContractError("judge candidate binding is invalid")
    candidates = {
        row["blind_item_id"]: row for row in target.get("candidates", [])
    }
    reviews = result["item_reviews"]
    if not isinstance(reviews, list) or len(reviews) != len(candidates):
        raise ShadowContractError("judge must review every blind item exactly once")
    seen: set[str] = set()
    for index, review in enumerate(reviews):
        row = _object(
            review,
            label=f"judge.item_reviews[{index}]",
            fields={
                "blind_item_id",
                "support",
                "materiality",
                "baseline_captured",
                "reason",
                "source_ids",
            },
        )
        blind_id = _identifier(
            row["blind_item_id"], label="judge blind_item_id"
        )
        if blind_id in seen or blind_id not in candidates:
            raise ShadowContractError("judge blind item coverage is invalid")
        seen.add(blind_id)
        support = _enum(
            row["support"], label="judge support", allowed=JUDGE_SUPPORT
        )
        _enum(
            row["materiality"],
            label="judge materiality",
            allowed=JUDGE_MATERIALITY,
        )
        _enum(
            row["baseline_captured"],
            label="judge baseline capture",
            allowed=BASELINE_CAPTURE,
        )
        reason = _text(row["reason"], label="judge reason", maximum=800)
        _assert_nonimperative(reason, label="judge reason")
        source_ids = _identifier_list(
            row["source_ids"],
            label="judge source_ids",
            maximum_items=8,
        )
        if not set(source_ids).issubset(set(candidates[blind_id]["source_ids"])):
            raise ShadowContractError("judge review cites outside the blind item")
        if support in {"supported", "partial"} and not source_ids:
            raise ShadowContractError("supported judge review requires cited evidence")
    if seen != set(candidates):
        raise ShadowContractError("judge blind item coverage is incomplete")

    missed = result["missed_material_issues"]
    if not isinstance(missed, list) or len(missed) > maximum_missed_issues:
        raise ShadowContractError("judge missed issues are not a bounded list")
    known_ids = set(candidates)
    for index, issue in enumerate(missed):
        if not isinstance(issue, dict):
            raise ShadowContractError("judge missed issue must be an object")
        issue_copy = {
            key: value for key, value in issue.items() if key != "baseline_captured"
        }
        issue_id, _, _, _ = _validate_claim(
            packet,
            issue_copy,
            label=f"judge.missed_material_issues[{index}]",
            id_field="issue_id",
            allowed_fields={
                "issue_id",
                "ticker",
                "category",
                "materiality",
                "statement",
                "period",
                "source_ids",
                "calculation_ids",
            },
        )
        if issue.get("materiality") not in {"medium", "high"}:
            raise ShadowContractError("judge missed issue must be material")
        _enum(
            issue.get("baseline_captured"),
            label="judge missed issue baseline capture",
            allowed=BASELINE_CAPTURE,
        )
        if issue_id in known_ids:
            raise ShadowContractError("judge missed issue ids must be unique")
        known_ids.add(issue_id)
    _enum(
        result["overall_confidence"],
        label="judge overall confidence",
        allowed={"low", "medium", "high"},
    )


def build_automatic_evaluation(
    analyst: dict[str, Any],
    critic: dict[str, Any] | None,
    target: dict[str, Any],
    mapping: dict[str, dict[str, str]],
    judge: dict[str, Any],
    *, schema_version: str = "phase5r_shadow_automatic_evaluation_v2",
    packet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del packet  # Baseline remeasurement is separately bound to the sealed packet.
    if schema_version not in {"phase5r_shadow_automatic_evaluation_v1", "phase5r_shadow_automatic_evaluation_v2"}:
        raise ShadowContractError("unknown automatic evaluation schema version")
    legacy = schema_version.endswith("_v1")
    analyst_by_id = {row["claim_id"]: row for row in analyst["claims"]}
    critic_omissions = (
        {row["omission_id"]: row for row in critic["omissions"]}
        if critic is not None
        else {}
    )
    critic_verdicts = (
        {row["claim_id"]: row["verdict"] for row in critic["claim_reviews"]}
        if critic is not None
        else {}
    )
    critic_reasons = ({row["claim_id"]: row["reason"] for row in critic["claim_reviews"]}
                      if critic is not None else {})
    candidate_by_blind = {
        row["blind_item_id"]: row for row in target["candidates"]
    }
    items: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    disagreements = 0
    for review in judge["item_reviews"]:
        blind_id = review["blind_item_id"]
        binding = mapping[blind_id]
        item_id = binding["item_id"]
        origin = binding["origin"]
        if origin == "deterministic_control":
            support_passed = review["support"] == binding["expected_support"]
            baseline_correct = review["baseline_captured"] == "yes" if binding["expected_support"] == "supported" else None
            controls.append({"blind_item_id": blind_id, "expected_support": binding["expected_support"],
                             "judge_support": review["support"],
                             "support_passed": support_passed,
                             "passed": support_passed and baseline_correct is not False,
                             "baseline_correct": baseline_correct})
            continue
        source = (
            analyst_by_id[item_id]
            if origin == "analyst"
            else critic_omissions[item_id]
        )
        critic_verdict = critic_verdicts.get(item_id, "not_routed")
        disagreement = (
            origin == "analyst"
            and (
                (
                    critic_verdict in {"supported", "partial"}
                    and review["support"] in {"unsupported", "not_assessable"}
                )
                or (
                    critic_verdict in {"unsupported", "not_assessable"}
                    and review["support"] == "supported"
                )
            )
        )
        if not legacy and origin == "analyst" and critic_verdict != "not_routed":
            disagreement = disagreement or (
                critic_verdict != review["support"]
                and "supported" in {critic_verdict, review["support"]}
            )
        disagreements += int(disagreement)
        items.append(
            {
                "item_id": item_id,
                "blind_item_id": blind_id,
                "origin": origin,
                "ticker": candidate_by_blind[blind_id]["ticker"],
                "statement": candidate_by_blind[blind_id]["statement"],
                "period": candidate_by_blind[blind_id]["period"],
                "source_ids": candidate_by_blind[blind_id]["source_ids"],
                "calculation_ids": candidate_by_blind[blind_id]["calculation_ids"],
                "model_materiality": source["materiality"],
                "model_novelty": source.get("novelty", "new_critic_omission"),
                "critic_verdict": critic_verdict,
                "judge_support": review["support"],
                "judge_materiality": review["materiality"],
                "judge_baseline_captured": review["baseline_captured"],
                "judge_reason": review["reason"],
                "judge_source_ids": review["source_ids"],
                "critic_judge_disagreement": disagreement,
            }
        )
        if not legacy:
            items[-1]["critic_reason"] = critic_reasons.get(item_id, "")
    incremental_material = [
        row
        for row in items
        if row["judge_support"] == "supported"
        and row["judge_materiality"] == "material"
        and row["judge_baseline_captured"] == "no"
        and not row["critic_judge_disagreement"]
    ]
    result = {
        "schema_version": schema_version,
        "candidate_set_sha256": target["candidate_set_sha256"],
        "blindness": {
            "candidate_origin_hidden_from_judge": True,
            "model_materiality_hidden_from_judge": True,
            "model_novelty_hidden_from_judge": True,
            "critic_verdict_hidden_from_judge": True,
        },
        "items": items,
        "missed_material_issues": copy.deepcopy(judge["missed_material_issues"]),
        "critic_judge_disagreements": disagreements,
        "incremental_supported_material_items": len(incremental_material),
        "semantic_value_status": (
            "incremental_material_value_observed"
            if incremental_material
            else "no_incremental_material_value_observed"
        ),
        "judge_overall_confidence": judge["overall_confidence"],
        "canonical_effect": False,
        "production_influence": False,
        "email_eligible": False,
        "automatic_action_allowed": False,
    }
    if not legacy:
        result["deterministic_controls"] = controls
        result["semantic_quality_interpretation"] = "model_estimated_not_independent_ground_truth"
    return result


__all__ = [
    "ANALYST_SCHEMA_VERSION",
    "BUNDLE_SCHEMA_VERSION",
    "LEGACY_BUNDLE_SCHEMA_VERSION",
    "CRITIC_SCHEMA_VERSION",
    "JUDGE_SCHEMA_VERSION",
    "ShadowContractError",
    "analyst_schema",
    "build_automatic_evaluation",
    "build_blind_judge_target",
    "build_deterministic_baseline",
    "build_semantic_view",
    "deterministic_claim_capture",
    "deterministic_claim_check",
    "critic_schema",
    "judge_schema",
    "load_packet",
    "primary_source_registry",
    "validate_analyst",
    "validate_critic",
    "validate_judge",
]
