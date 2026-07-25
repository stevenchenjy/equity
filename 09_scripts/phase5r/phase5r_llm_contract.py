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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from phase5r_daily_common import canonical_sha256
from phase5r_evidence_freshness import (
    EvidenceFreshnessError,
    freshness_action_review_reasons,
    validate_evidence_freshness_receipt,
)
from phase5r_return_objective import validate_return_objective_payload
from phase5r_valuation_evidence_v1 import (
    ValuationEvidenceError,
    validate_valuation_evidence_v1,
    valuation_packet_calculations,
)


PACKET_SCHEMA_VERSION = "phase5r_llm_evidence_packet_v1"
ANALYST_SCHEMA_VERSION = "phase5r_llm_evidence_analysis_v1"
COMMITTEE_SCHEMA_VERSION = "phase5r_llm_committee_decision_v1"
CRITIC_SCHEMA_VERSION = "phase5r_llm_critic_review_v1"
CHALLENGER_SCHEMA_VERSION = "phase5r_llm_blinded_challenger_v1"
BLINDED_COMPARISON_SCHEMA_VERSION = (
    "phase5r_llm_blinded_comparison_v1"
)
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

# This is a structural sanity floor, not an empirical calibration threshold.
# Confidence fields use whole percentages, so 0 and 1 are treated as
# absent/placeholder signal and cannot support an action-changing transition.
_TRANSITION_CONFIDENCE_SANITY_FLOOR_PCT = 1

_ALLOWED_CRITIC_DOWNGRADES = {
    "abstain": {"abstain"},
    "reject": {"reject", "abstain"},
    "watchlist": {"watchlist", "reject", "abstain"},
    "hold_existing": {"hold_existing", "watchlist", "reject", "abstain"},
    "paper_trade_candidate": {
        "paper_trade_candidate",
        "watchlist",
        "reject",
        "abstain",
    },
    "real_trade_candidate": {
        "real_trade_candidate",
        "paper_trade_candidate",
        "watchlist",
        "reject",
        "abstain",
    },
    "trim_review": {"trim_review", "hold_existing", "watchlist", "abstain"},
    "exit_review": {"exit_review", "trim_review", "hold_existing", "abstain"},
}

_PORTFOLIO_TRANSITION_PRIORITY = {
    "paper_trade_candidate": 1,
    "real_trade_candidate": 2,
    "trim_review": 3,
    "exit_review": 4,
}

_PORTFOLIO_ROLLUP_PRIORITY = {
    "abstain": 0,
    "reject": 1,
    "watchlist": 2,
    "hold_existing": 3,
    "paper_trade_candidate": 4,
    "real_trade_candidate": 5,
    "trim_review": 6,
    "exit_review": 7,
}

_ROLE_ALLOWED_CLASSIFICATIONS = {
    "held": {
        "hold_existing",
        "paper_trade_candidate",
        "real_trade_candidate",
        "trim_review",
        "exit_review",
        "abstain",
    },
    "candidate": {
        "reject",
        "watchlist",
        "paper_trade_candidate",
        "real_trade_candidate",
        "abstain",
    },
}

_CRITIC_PASS_FIELDS = (
    "factual_grounding_pass",
    "citation_integrity_pass",
    "numeric_reconciliation_pass",
    "long_term_reasoning_pass",
    "action_proportionality_pass",
    "policy_boundary_pass",
)
_CRITIC_VERDICT_PRIORITY = {
    "approve": 0,
    "revise": 1,
    "reject": 2,
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

_EFFECTIVE_DECISION_COPY = {
    "reject": (
        "明确研究结论：否决该候选",
        "当前证据不支持进入仓位复核；只有新的可验证一手证据才应触发重评。",
    ),
    "watchlist": (
        "明确研究结论：保留观察，尚不进入仓位复核",
        "长期逻辑仍值得跟踪，但证据、估值或稳定性门槛尚未同时满足。",
    ),
    "hold_existing": (
        "明确研究结论：继续持有研究状态",
        "现有长期逻辑未被可靠证据推翻，本次不改变仓位研究结论。",
    ),
    "paper_trade_candidate": (
        "明确研究结论：进入模拟仓位候选复核",
        "证据支持进入模拟验证，但这不是交易授权或真实仓位指令。",
    ),
    "real_trade_candidate": (
        "明确研究结论：进入真实仓位候选复核",
        "证据支持进入人工仓位复核；任何真实动作仍须在仓库外单独确认。",
    ),
    "trim_review": (
        "明确研究结论：进入减仓复核",
        "证据支持人工检查是否降低现有暴露；本结论不执行任何动作。",
    ),
    "exit_review": (
        "明确研究结论：进入退出复核",
        "长期逻辑可能已实质受损，应进行人工退出复核；本结论不执行任何动作。",
    ),
    "abstain": (
        "明确研究结论：证据不足，本次不改变仓位",
        "模型、数据或验证门槛未通过；先补足证据，再重新评估。",
    ),
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
_FORBIDDEN_PACKET_KEYS = {
    "api_key",
    "app_password",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "email_address",
    "account_number",
    "routing_number",
    "account_balance",
    "account_total_value",
    "cash_available",
    "cash_reserved",
    "current_shares",
    "target_shares",
    "entry_price",
    "order_quantity",
}
_FORBIDDEN_PACKET_KEY_TOKENS = {
    re.sub(r"[^a-z0-9]+", "", key.lower()) for key in _FORBIDDEN_PACKET_KEYS
}
_EMAIL_PATTERN = re.compile(
    r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b"
)
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
    r"password|secret|credential|smtp[_ -]?password|broker[_ -]?token)"
    r"[A-Z0-9_-]*\s*[:=]\s*[^\s,;]+"
)
_SECRET_TOKEN_PATTERN = re.compile(
    r"(?i)\b(?:sk-proj-[A-Z0-9_-]{6,}|"
    r"sk-svcacct-[A-Z0-9_-]{6,}|"
    r"gh[opusr]_[A-Z0-9]{12,}|"
    r"xox[baprs]-[A-Z0-9-]{10,})\b"
)
_LOCAL_PATH_PATTERN = re.compile(
    r"(?i)(?:file://|/Users/[^/\s]+/|[A-Z]:\\Users\\[^\\\s]+\\)"
)
_PRIVATE_CURRENCY_PATTERN = re.compile(
    r"(?i)(?:[$€£]\s*\d[\d,]*(?:\.\d+)?|"
    r"\b\d[\d,]*(?:\.\d+)?\s*(?:USD|dollars?)\b)"
)
_NUMERIC_TEXT_PATTERN = re.compile(r"\d")
_PROHIBITED_ACTION_LANGUAGE = (
    re.compile(r"(?i)\b(?:buy|sell)\b"),
    re.compile(
        r"(?im)(?:^|[.!?;:\n]\s*)(?:please\s+)?"
        r"(?:purchase|acquire|liquidate|dispose\s+of|close\s+out)\b"
    ),
    re.compile(
        r"(?i)\b(?:recommend|advise|advises|should|must)\s+"
        r"(?:that\s+you\s+|you\s+)?"
        r"(?:purchase|acquire|liquidate|dispose\s+of|close\s+out)\b"
    ),
    re.compile(
        r"(?i)\b(?:place|submit|execute|route)\s+(?:an?\s+)?(?:order|trade)\b"
    ),
    re.compile(
        r"(?i)\b(?:buy|sell|purchase|acquire|liquidate|dispose\s+of|"
        r"close\s+out|add|trim|exit|reduce)\s+"
        r"(?:now|today|immediately)\b"
    ),
    re.compile(r"(?:立即|马上|现在)?(?:买入|卖出|下单|建仓|加仓|减仓|清仓)"),
)
_PROHIBITED_RETURN_OBJECTIVE_LANGUAGE = (
    re.compile(
        r"(?i)\b(?:guarantee(?:d)?|quota)\b.{0,40}\b(?:return|performance)\b"
    ),
    re.compile(
        r"(?i)\b(?:chase|force|increase)\b.{0,40}\b"
        r"(?:turnover|trading|return target)\b"
    ),
    re.compile(r"(?:保证|承诺).{0,20}(?:收益|回报)"),
    re.compile(r"(?:追逐|强求).{0,20}(?:收益目标|回报目标|换手)"),
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
                    "rationale": {"type": "string"},
                    "fact_type": {
                        "type": "string",
                        "enum": [
                            "fact",
                            "estimate",
                            "management_opinion",
                            "independent_analysis",
                        ],
                    },
                    "evidence_origin": {
                        "type": "string",
                        "enum": [
                            "management_reported",
                            "independently_reported",
                            "calculated",
                        ],
                    },
                    "unit": {"type": "string"},
                    "period": {"type": "string"},
                    "source_ids": _string_array(),
                    "cited_excerpt_sha256": _string_array(),
                    "calculation_ids": _string_array(),
                },
                [
                    "claim_id",
                    "ticker",
                    "claim",
                    "stance",
                    "time_horizon",
                    "materiality",
                    "rationale",
                    "fact_type",
                    "evidence_origin",
                    "unit",
                    "period",
                    "source_ids",
                    "cited_excerpt_sha256",
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
        "confidence_components": _closed_object(
            {
                "evidence_coverage_pct": {"type": "integer"},
                "thesis_clarity_pct": {"type": "integer"},
                "valuation_clarity_pct": {"type": "integer"},
                "portfolio_fit_pct": {"type": "integer"},
            },
            [
                "evidence_coverage_pct",
                "thesis_clarity_pct",
                "valuation_clarity_pct",
                "portfolio_fit_pct",
            ],
        ),
        "supporting_facts": {
            "type": "array",
            "items": _closed_object(
                {
                    "ticker": {"type": "string"},
                    "fact": {"type": "string"},
                    "source_ids": _string_array(),
                    "calculation_ids": _string_array(),
                },
                ["ticker", "fact", "source_ids", "calculation_ids"],
            ),
        },
        "disconfirming_facts": {
            "type": "array",
            "items": _closed_object(
                {
                    "ticker": {"type": "string"},
                    "fact": {"type": "string"},
                    "source_ids": _string_array(),
                    "calculation_ids": _string_array(),
                },
                ["ticker", "fact", "source_ids", "calculation_ids"],
            ),
        },
        "scenarios": _closed_object(
            {
                "bull": {"type": "string"},
                "base": {"type": "string"},
                "bear": {"type": "string"},
            },
            ["bull", "base", "bear"],
        ),
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
                    "claim_ids": _string_array(),
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
                    "claim_ids",
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
        "confidence_components",
        "supporting_facts",
        "disconfirming_facts",
        "scenarios",
        "ticker_decisions",
        "dissent",
        "automatic_action_allowed",
    ],
)


CHALLENGER_SCHEMA = copy.deepcopy(COMMITTEE_SCHEMA)
CHALLENGER_SCHEMA["properties"]["schema_version"] = {
    "type": "string",
    "const": CHALLENGER_SCHEMA_VERSION,
}
CHALLENGER_SCHEMA["properties"]["committee_proposal_seen"] = {
    "type": "boolean",
    "const": False,
}
CHALLENGER_SCHEMA["properties"]["independent_precommitment"] = {
    "type": "boolean",
    "const": True,
}
CHALLENGER_SCHEMA["required"].extend(
    ["committee_proposal_seen", "independent_precommitment"]
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
        "ticker_reviews": {
            "type": "array",
            "items": _closed_object(
                {
                    "ticker": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["approve", "revise", "reject"],
                    },
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
                },
                [
                    "ticker",
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
                ],
            ),
        },
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
        "ticker_reviews",
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
    serialized_original = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    serialized = serialized_original.lower()
    found = [marker for marker in _SENSITIVE_MARKERS if marker in serialized]
    if found:
        raise ContractError(f"{label}: sensitive/local marker present: {','.join(found)}")
    if _EMAIL_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: email address is prohibited")
    if _SECRET_ASSIGNMENT_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: secret-like assignment is prohibited")
    if _SECRET_TOKEN_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: secret-like token is prohibited")
    if _LOCAL_PATH_PATTERN.search(serialized_original):
        raise ContractError(f"{label}: local path is prohibited")


def _assert_no_forbidden_packet_keys(value: Any, path: str = "packet") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(
                r"[^a-z0-9]+",
                "",
                str(key).strip().lower(),
            )
            if normalized in _FORBIDDEN_PACKET_KEY_TOKENS:
                raise ContractError(f"{path}: forbidden field {key}")
            _assert_no_forbidden_packet_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_forbidden_packet_keys(child, f"{path}[{index}]")


def _assert_no_private_currency(packet: dict[str, Any]) -> None:
    private_context = {
        "entities": packet.get("entities", []),
        "portfolio_constraints": packet.get("portfolio_constraints", {}),
        "research_context": packet.get("research_context", []),
    }
    serialized = json.dumps(private_context, ensure_ascii=False, sort_keys=True)
    if _PRIVATE_CURRENCY_PATTERN.search(serialized):
        raise ContractError("packet: exact local/account currency value is prohibited")


def _assert_no_imperative_action_language(response: dict[str, Any]) -> None:
    text_fields: list[str] = [
        str(response.get("headline", "")),
        str(response.get("decisive_advice", "")),
        str(response.get("long_term_portfolio_case", "")),
    ]
    text_fields.extend(str(value) for value in response.get("dissent", []))
    for decision in response.get("ticker_decisions", []):
        text_fields.extend(
            [
                str(decision.get("rationale", "")),
                str(decision.get("long_term_case", "")),
            ]
        )
        text_fields.extend(str(value) for value in decision.get("risks", []))
        text_fields.extend(
            str(value) for value in decision.get("invalidation_conditions", [])
        )
    combined = "\n".join(text_fields)
    if any(pattern.search(combined) for pattern in _PROHIBITED_ACTION_LANGUAGE):
        raise ContractError("committee: imperative buy/sell/order language is prohibited")
    if any(
        pattern.search(combined)
        for pattern in _PROHIBITED_RETURN_OBJECTIVE_LANGUAGE
    ):
        raise ContractError(
            "committee: return guarantee, quota, or target-chasing language "
            "is prohibited"
        )


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


def _entity_roles(packet: dict[str, Any]) -> dict[str, str]:
    return {
        str(row.get("ticker", "")).upper(): str(row.get("role", ""))
        for row in packet.get("entities", [])
        if row.get("ticker")
    }


def _rollup_classifications(classifications: list[str]) -> str:
    if not classifications:
        return "abstain"
    return max(
        classifications,
        key=lambda classification: _PORTFOLIO_ROLLUP_PRIORITY[classification],
    )


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


def _validate_ticker_references(
    packet: dict[str, Any],
    ticker: str,
    source_values: list[str],
    calculation_values: list[str],
    *,
    path: str,
    require_source: bool,
    require_primary: bool,
) -> None:
    """Require cited evidence and calculations to belong to the stated ticker."""

    _validate_references(
        packet,
        source_values,
        calculation_values,
        path=path,
        require_source=require_source,
    )
    normalized_ticker = ticker.upper()
    source_map = {
        str(row["source_id"]): row for row in packet["source_catalog"]
    }
    calculation_map = {
        str(row["calculation_id"]): row for row in packet["calculations"]
    }
    wrong_sources = sorted(
        source_id
        for source_id in source_values
        if str(source_map[source_id].get("ticker", "")).upper()
        != normalized_ticker
    )
    if wrong_sources:
        raise ContractError(
            f"{path}: cross-ticker source ids {','.join(wrong_sources)}"
        )
    wrong_calculations = sorted(
        calculation_id
        for calculation_id in calculation_values
        if str(calculation_map[calculation_id].get("ticker", "")).upper()
        != normalized_ticker
    )
    if wrong_calculations:
        raise ContractError(
            f"{path}: cross-ticker calculation ids "
            f"{','.join(wrong_calculations)}"
        )
    if require_primary and not any(
        source_map[source_id].get("authority") == "primary_official"
        for source_id in source_values
    ):
        raise ContractError(
            f"{path}: at least one ticker-matched primary source is required"
        )


def _normalized_utc_or_empty(value: Any) -> str:
    if value in {"", None}:
        return ""
    try:
        parsed = datetime.fromisoformat(
            str(value)[:-1] + "+00:00"
            if str(value).endswith("Z")
            else str(value)
        )
    except ValueError as exc:
        raise ContractError(
            "packet: freshness-bound timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise ContractError(
            "packet: freshness-bound timestamp must include a timezone"
        )
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _date_from_period(value: Any) -> str:
    match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", str(value or ""))
    return match.group(0) if match else ""


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
        "valuation_evidence",
        "calculations",
        "source_catalog",
        "boundaries",
    }
    optional = {"evidence_freshness"}
    missing = sorted(required - set(packet))
    extras = sorted(set(packet) - required - optional)
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
    entity_rows = packet["entities"]
    if not isinstance(entity_rows, list):
        raise ContractError("packet: entities must be an array")
    entity_tickers = [
        str(row.get("ticker", "")).upper()
        for row in entity_rows
        if isinstance(row, dict)
    ]
    if (
        len(entity_tickers) != len(entity_rows)
        or len(entity_tickers) != len(set(entity_tickers))
    ):
        raise ContractError("packet: entities must have unique ticker identities")
    for index, entity in enumerate(entity_rows):
        role = str(entity.get("role", ""))
        if role not in _ROLE_ALLOWED_CLASSIFICATIONS:
            raise ContractError(
                f"packet.entities[{index}]: role must be held or candidate"
            )
    constraints = packet["portfolio_constraints"]
    required_constraint_fields = {
        "account_size_band",
        "active_stock_hard_cap_pct",
        "active_stock_target_pct",
        "cash_target_pct",
        "core_allocation_target_pct",
        "investment_horizon_years",
        "manual_execution_only",
        "return_objective",
        "single_stock_default_cap_pct",
        "single_stock_hard_cap_pct",
    }
    if (
        not isinstance(constraints, dict)
        or set(constraints) != required_constraint_fields
    ):
        raise ContractError(
            "packet: portfolio constraint fields do not match policy"
        )
    if (
        not isinstance(constraints["account_size_band"], str)
        or not constraints["account_size_band"].strip()
    ):
        raise ContractError(
            "packet: account size band must be non-empty"
        )
    horizon = constraints["investment_horizon_years"]
    if (
        not isinstance(horizon, int)
        or isinstance(horizon, bool)
        or not 1 <= horizon <= 30
    ):
        raise ContractError(
            "packet: investment horizon must be 1..30 years"
        )
    if constraints["manual_execution_only"] is not True:
        raise ContractError(
            "packet: portfolio execution must remain manual"
        )
    percentage_fields = (
        "active_stock_hard_cap_pct",
        "active_stock_target_pct",
        "cash_target_pct",
        "core_allocation_target_pct",
        "single_stock_default_cap_pct",
        "single_stock_hard_cap_pct",
    )
    parsed_percentages: dict[str, Decimal] = {}
    for field in percentage_fields:
        raw = constraints[field]
        if isinstance(raw, bool):
            raise ContractError(
                f"packet: portfolio constraint {field} is invalid"
            )
        try:
            parsed = Decimal(str(raw))
        except (InvalidOperation, ValueError) as exc:
            raise ContractError(
                f"packet: portfolio constraint {field} is invalid"
            ) from exc
        if not parsed.is_finite() or not Decimal("0") <= parsed <= Decimal("100"):
            raise ContractError(
                f"packet: portfolio constraint {field} is out of range"
            )
        parsed_percentages[field] = parsed
    if (
        parsed_percentages["active_stock_hard_cap_pct"] <= 0
        or parsed_percentages["single_stock_hard_cap_pct"] <= 0
        or parsed_percentages["single_stock_default_cap_pct"] <= 0
        or parsed_percentages["active_stock_target_pct"]
        > parsed_percentages["active_stock_hard_cap_pct"]
        or parsed_percentages["single_stock_default_cap_pct"]
        > parsed_percentages["single_stock_hard_cap_pct"]
        or parsed_percentages["single_stock_hard_cap_pct"]
        > parsed_percentages["active_stock_hard_cap_pct"]
    ):
        raise ContractError(
            "packet: portfolio cap ordering or positive-cap policy failed"
        )
    target_total = sum(
        (
            parsed_percentages["core_allocation_target_pct"],
            parsed_percentages["active_stock_target_pct"],
            parsed_percentages["cash_target_pct"],
        ),
        Decimal("0"),
    )
    if target_total != Decimal("100"):
        raise ContractError(
            "packet: core, active, and cash targets must sum to 100"
        )
    try:
        validate_return_objective_payload(
            constraints.get("return_objective")
        )
    except ValueError as exc:
        raise ContractError(
            "packet: return objective must remain a non-guaranteed "
            "long-horizon objective with no risk-gate override"
        ) from exc
    gates = packet["gates"]
    allowed_classifications_by_ticker = gates.get(
        "allowed_classifications_by_ticker"
    )
    if (
        not isinstance(allowed_classifications_by_ticker, dict)
        or set(allowed_classifications_by_ticker) != set(tickers)
    ):
        raise ContractError(
            "packet: allowed classifications must exactly match entities"
        )
    role_by_ticker = {
        str(entity["ticker"]).upper(): str(entity["role"])
        for entity in entity_rows
    }
    for ticker in tickers:
        values = allowed_classifications_by_ticker.get(ticker)
        role_allowed = _ROLE_ALLOWED_CLASSIFICATIONS[role_by_ticker[ticker]]
        if (
            not isinstance(values, list)
            or not values
            or any(
                not isinstance(value, str) or value not in role_allowed
                for value in values
            )
            or len(values) != len(set(values))
            or "abstain" not in values
        ):
            raise ContractError(
                f"packet: allowed classifications are invalid for {ticker}"
            )
    market_data_action_grade = gates.get("market_data_action_grade")
    if not isinstance(market_data_action_grade, bool):
        raise ContractError("packet: market_data_action_grade must be boolean")
    close_count = gates.get("deterministic_action_stability_distinct_closes", 0)
    if (
        not isinstance(close_count, int)
        or isinstance(close_count, bool)
        or close_count < 0
    ):
        raise ContractError("packet: deterministic close count is invalid")
    for gate_name in (
        "market_data_action_grade_tickers",
        "valuation_action_grade_tickers",
        "deterministic_transition_pending_tickers",
        "deterministic_transition_eligible_tickers",
    ):
        values = gates.get(gate_name, [])
        if (
            not isinstance(values, list)
            or any(
                not isinstance(value, str)
                or value != value.upper()
                or value not in tickers
                for value in values
            )
            or len(values) != len(set(values))
        ):
            raise ContractError(f"packet: {gate_name} is invalid")
    market_data_action_grade_tickers = gates.get(
        "market_data_action_grade_tickers",
        [],
    )
    if market_data_action_grade is not bool(market_data_action_grade_tickers):
        raise ContractError(
            "packet: market_data_action_grade must equal per-ticker eligibility"
        )
    verified_session = gates.get("verified_close_session", "")
    if not isinstance(verified_session, str):
        raise ContractError("packet: verified close session is invalid")
    if verified_session and (
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified_session) is None
        or verified_session != packet["cycle_date"]
    ):
        raise ContractError("packet: verified close session is invalid")
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
    valuation_evidence = packet["valuation_evidence"]
    if not isinstance(valuation_evidence, list):
        raise ContractError("packet: valuation_evidence must be an array")
    valuation_tickers: list[str] = []
    valuation_action_grade_tickers: list[str] = []
    validated_valuation_by_ticker: dict[str, dict[str, Any]] = {}
    calculation_map = {
        str(row["calculation_id"]): row for row in packet["calculations"]
    }
    source_map = {
        str(row["source_id"]): row for row in packet["source_catalog"]
    }
    for index, receipt in enumerate(valuation_evidence):
        try:
            validated_receipt = validate_valuation_evidence_v1(receipt)
        except ValuationEvidenceError as exc:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: invalid receipt"
            ) from exc
        ticker = validated_receipt["ticker"]
        if ticker not in tickers:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: unknown ticker"
            )
        valuation_tickers.append(ticker)
        validated_valuation_by_ticker[ticker] = validated_receipt
        try:
            receipt_as_of = datetime.fromisoformat(
                validated_receipt["as_of_utc"].replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: invalid as-of"
            ) from exc
        if receipt_as_of != as_of.astimezone(receipt_as_of.tzinfo):
            raise ContractError(
                f"packet.valuation_evidence[{index}]: as-of mismatch"
            )
        receipt_source_ids = {
            str(source_id)
            for input_receipt in validated_receipt["input_receipts"]
            for source_id in input_receipt["source_ids"]
        }
        unknown_receipt_sources = sorted(receipt_source_ids - known_sources)
        if unknown_receipt_sources:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: unknown sources "
                + ",".join(unknown_receipt_sources)
            )
        wrong_ticker_sources = sorted(
            source_id
            for source_id in receipt_source_ids
            if str(source_map[source_id].get("ticker", "")).upper() != ticker
        )
        if wrong_ticker_sources:
            raise ContractError(
                f"packet.valuation_evidence[{index}]: cross-ticker sources "
                + ",".join(wrong_ticker_sources)
            )
        for projected in valuation_packet_calculations(validated_receipt):
            if calculation_map.get(projected["calculation_id"]) != projected:
                raise ContractError(
                    f"packet.valuation_evidence[{index}]: projected "
                    f"calculation mismatch {projected['calculation_id']}"
                )
        if (
            validated_receipt["sufficiency"]["decision_sufficient"] is True
            and validated_receipt["guardrails"][
                "action_grade_valuation_permitted"
            ]
            is True
        ):
            valuation_action_grade_tickers.append(ticker)
    if len(valuation_tickers) != len(set(valuation_tickers)):
        raise ContractError(
            "packet: valuation evidence must have at most one receipt per ticker"
        )
    if gates.get("valuation_action_grade_tickers", []) != sorted(
        valuation_action_grade_tickers
    ):
        raise ContractError(
            "packet: valuation action-grade tickers must equal validated receipts"
        )
    evidence_freshness = packet.get("evidence_freshness", [])
    if not isinstance(evidence_freshness, list):
        raise ContractError("packet: evidence_freshness must be an array")
    freshness_tickers: list[str] = []
    market_by_ticker = {
        str(row.get("ticker", "")).upper(): row
        for row in packet["market_observations"]
        if isinstance(row, dict) and row.get("ticker")
    }
    packet_as_of_utc = as_of.astimezone(timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    for index, raw_receipt in enumerate(evidence_freshness):
        try:
            freshness_receipt = validate_evidence_freshness_receipt(
                raw_receipt
            )
        except EvidenceFreshnessError as exc:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: invalid receipt"
            ) from exc
        ticker = freshness_receipt["ticker"]
        if ticker not in tickers:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: unknown ticker"
            )
        freshness_tickers.append(ticker)
        if freshness_receipt["as_of_utc"] != packet_as_of_utc:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: as-of mismatch"
            )

        durable_source_ids = set(
            freshness_receipt["durable_sec_source_ids"]
        )
        unknown_durable_sources = sorted(
            durable_source_ids - known_sources
        )
        if unknown_durable_sources:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: unknown durable SEC "
                f"sources {','.join(unknown_durable_sources)}"
            )
        cross_ticker_durable_sources = sorted(
            source_id
            for source_id in durable_source_ids
            if str(source_map[source_id].get("ticker", "")).upper()
            != ticker
        )
        if cross_ticker_durable_sources:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: cross-ticker source "
                f"in durable SEC receipt "
                f"{','.join(cross_ticker_durable_sources)}"
            )
        non_primary_durable_sources = sorted(
            source_id
            for source_id in durable_source_ids
            if (
                not str(
                    source_map[source_id].get("source_type", "")
                ).startswith("sec_")
                or source_map[source_id].get("authority")
                != "primary_official"
            )
        )
        if non_primary_durable_sources:
            raise ContractError(
                f"packet.evidence_freshness[{index}]: durable evidence "
                f"requires a primary source "
                f"{','.join(non_primary_durable_sources)}"
            )

        market_row = market_by_ticker.get(ticker, {})
        market_freshness = freshness_receipt["market"]
        market_binding_mismatch = (
            market_freshness["observed_at_utc"]
            != _normalized_utc_or_empty(
                market_row.get("data_timestamp", "")
            )
            or market_freshness["market_session_date"]
            != str(market_row.get("market_session_date", ""))
            or market_freshness["expected_market_session_date"]
            != verified_session
            or market_freshness["complete_close"]
            is not (market_row.get("bar_state") == "complete_close")
        )
        if (
            market_binding_mismatch
            and gates.get("market_data_current") is True
            and bool(verified_session)
        ):
            raise ContractError(
                f"packet.evidence_freshness[{index}]: market binding mismatch"
            )

        valuation_receipt = validated_valuation_by_ticker.get(ticker)
        valuation_freshness = freshness_receipt["valuation"]
        if valuation_receipt is None:
            expected_valuation = {
                "valuation_receipt_sha256": "",
                "receipt_as_of_utc": "",
                "market_input_at_utc": "",
                "market_session_date": "",
                "expected_market_session_date": verified_session,
                "scenario_refreshed_at_utc": "",
                "complete": False,
            }
        else:
            valuation_inputs = {
                str(row["input_id"]): row
                for row in valuation_receipt["input_receipts"]
            }
            share_price = valuation_inputs.get("share_price", {})
            scenario_times = sorted(
                {
                    _normalized_utc_or_empty(
                        valuation_inputs.get(input_id, {}).get(
                            "available_at_utc",
                            "",
                        )
                    )
                    for input_id in (
                        "target_price_assumption",
                        "downside_price_assumption",
                    )
                    if valuation_inputs.get(input_id, {}).get(
                        "available_at_utc"
                    )
                }
            )
            expected_valuation = {
                "valuation_receipt_sha256": valuation_receipt[
                    "receipt_sha256"
                ],
                "receipt_as_of_utc": valuation_receipt["as_of_utc"],
                "market_input_at_utc": _normalized_utc_or_empty(
                    share_price.get("available_at_utc", "")
                ),
                "market_session_date": _date_from_period(
                    share_price.get("period", "")
                ),
                "expected_market_session_date": verified_session,
                "scenario_refreshed_at_utc": (
                    scenario_times[-1] if scenario_times else ""
                ),
                "complete": (
                    valuation_receipt["sufficiency"][
                        "decision_sufficient"
                    ]
                    is True
                    and valuation_receipt["guardrails"][
                        "action_grade_valuation_permitted"
                    ]
                    is True
                ),
            }
        supplied_valuation = {
            key: valuation_freshness[key]
            for key in expected_valuation
        }
        if (
            supplied_valuation != expected_valuation
            and ticker
            in set(gates.get("valuation_action_grade_tickers", []))
            and bool(verified_session)
        ):
            raise ContractError(
                f"packet.evidence_freshness[{index}]: valuation binding mismatch"
            )
    if len(freshness_tickers) != len(set(freshness_tickers)):
        raise ContractError(
            "packet: evidence freshness must have at most one receipt per ticker"
        )
    _assert_no_forbidden_packet_keys(packet)
    _assert_no_private_currency(packet)
    _assert_no_sensitive_markers(packet, "packet")
    return packet


def validate_analyst(
    packet: dict[str, Any], response: dict[str, Any]
) -> dict[str, Any]:
    validate_packet(packet)
    validate_schema(response, ANALYST_SCHEMA)
    if response["packet_id"] != packet["packet_id"]:
        raise ContractError("analyst: packet_id mismatch")
    if response["as_of_et"] != packet["as_of_et"]:
        raise ContractError("analyst: as_of_et must exactly match the packet")
    if (
        packet["gates"].get("prompt_injection_text_detected") is True
        and response["prompt_injection_detected"] is not True
    ):
        raise ContractError("analyst: deterministic prompt-injection flag was ignored")
    known_tickers = _tickers(packet)
    source_map = {
        str(row["source_id"]): row for row in packet["source_catalog"]
    }
    claim_ids: list[str] = []
    for index, claim in enumerate(response["claims"]):
        ticker = claim["ticker"].upper()
        if ticker not in known_tickers:
            raise ContractError(f"analyst.claims[{index}]: unknown ticker {ticker}")
        for field in ("claim_id", "claim", "rationale", "unit", "period"):
            if not str(claim[field]).strip():
                raise ContractError(
                    f"analyst.claims[{index}]: {field} must be non-empty"
                )
        claim_ids.append(claim["claim_id"])
        _validate_ticker_references(
            packet,
            ticker,
            claim["source_ids"],
            claim["calculation_ids"],
            path=f"analyst.claims[{index}]",
            require_source=claim["materiality"] in {"medium", "high"},
            require_primary=claim["materiality"] in {"medium", "high"},
        )
        if len(claim["source_ids"]) != len(set(claim["source_ids"])):
            raise ContractError(
                f"analyst.claims[{index}]: source_ids must be unique"
            )
        cited_hashes = claim["cited_excerpt_sha256"]
        if len(cited_hashes) != len(claim["source_ids"]):
            raise ContractError(
                f"analyst.claims[{index}]: cited excerpt hashes must align "
                "one-to-one with source_ids"
            )
        for source_index, (source_id, cited_hash) in enumerate(
            zip(claim["source_ids"], cited_hashes, strict=True)
        ):
            source = source_map[source_id]
            excerpt = str(source.get("excerpt_text", ""))
            if not excerpt:
                raise ContractError(
                    f"analyst.claims[{index}].source_ids[{source_index}]: "
                    "cited source excerpt is empty"
                )
            if _SHA256_PATTERN.fullmatch(cited_hash) is None:
                raise ContractError(
                    f"analyst.claims[{index}].cited_excerpt_sha256"
                    f"[{source_index}]: invalid sha256"
                )
            expected_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            if cited_hash != expected_hash or cited_hash != source["content_sha256"]:
                raise ContractError(
                    f"analyst.claims[{index}].cited_excerpt_sha256"
                    f"[{source_index}]: excerpt binding mismatch"
                )
        if (
            claim["evidence_origin"] == "calculated"
            and not claim["calculation_ids"]
        ):
            raise ContractError(
                f"analyst.claims[{index}]: calculated evidence requires a "
                "reconciled calculation"
            )
        if (
            _NUMERIC_TEXT_PATTERN.search(claim["claim"])
            and not claim["calculation_ids"]
        ):
            raise ContractError(
                f"analyst.claims[{index}]: numeric text requires a "
                "reconciled calculation"
            )
    if len(claim_ids) != len(set(claim_ids)):
        raise ContractError("analyst: claim_ids must be unique")
    coverage_tickers = [row["ticker"].upper() for row in response["ticker_coverage"]]
    if len(coverage_tickers) != len(set(coverage_tickers)):
        raise ContractError("analyst: ticker coverage must be unique")
    if set(coverage_tickers) != known_tickers:
        raise ContractError(
            "analyst: ticker coverage must exactly match packet entities"
        )
    _assert_no_sensitive_markers(response, "analyst")
    return response


def validate_committee(
    packet: dict[str, Any],
    response: dict[str, Any],
    analyst: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_packet(packet)
    if analyst is not None:
        validate_analyst(packet, analyst)
    validate_schema(response, COMMITTEE_SCHEMA)
    if response["packet_id"] != packet["packet_id"]:
        raise ContractError("committee: packet_id mismatch")
    if not 0 <= response["confidence_pct"] <= 100:
        raise ContractError("committee: confidence_pct must be 0..100")
    components = response["confidence_components"]
    for name, value in components.items():
        if not 0 <= value <= 100:
            raise ContractError(
                f"committee.confidence_components.{name} must be 0..100"
            )
    if response["confidence_pct"] > min(components.values()):
        raise ContractError(
            "committee: overall confidence cannot exceed its weakest component"
        )
    valuation_action_grade_tickers = set(
        packet["gates"].get("valuation_action_grade_tickers", [])
    )
    if (
        components["valuation_clarity_pct"] > 0
        and not valuation_action_grade_tickers
    ):
        raise ContractError(
            "committee: valuation clarity must be zero without a "
            "reconciled valuation receipt"
        )
    known_tickers = _tickers(packet)
    entity_roles = _entity_roles(packet)
    analyst_claims = (
        {str(claim["claim_id"]): claim for claim in analyst["claims"]}
        if analyst is not None
        else {}
    )
    required_fact_count = (
        3
        if response["portfolio_classification"]
        in TRANSITION_CLASSIFICATIONS
        else 1
        if response["portfolio_classification"] != "abstain"
        else 0
    )
    for field in ("supporting_facts", "disconfirming_facts"):
        facts = response[field]
        if not required_fact_count <= len(facts) <= 3:
            raise ContractError(
                f"committee.{field}: expected {required_fact_count}..3 facts"
            )
        for index, fact in enumerate(facts):
            ticker = fact["ticker"].upper()
            if ticker not in known_tickers:
                raise ContractError(
                    f"committee.{field}[{index}]: unknown ticker"
                )
            if not str(fact["fact"]).strip():
                raise ContractError(
                    f"committee.{field}[{index}]: fact is empty"
                )
            _validate_ticker_references(
                packet,
                ticker,
                fact["source_ids"],
                fact["calculation_ids"],
                path=f"committee.{field}[{index}]",
                require_source=True,
                require_primary=True,
            )
            if (
                _NUMERIC_TEXT_PATTERN.search(fact["fact"])
                and not fact["calculation_ids"]
            ):
                raise ContractError(
                    f"committee.{field}[{index}]: numeric text requires a "
                    "reconciled calculation"
                )
    if any(
        not isinstance(response["scenarios"][name], str)
        or not response["scenarios"][name].strip()
        for name in ("bull", "base", "bear")
    ):
        raise ContractError("committee: bull/base/bear scenarios must be non-empty")
    portfolio_text = "\n".join(
        [
            response["headline"],
            response["decisive_advice"],
            response["long_term_portfolio_case"],
            response["scenarios"]["bull"],
            response["scenarios"]["base"],
            response["scenarios"]["bear"],
            *response["dissent"],
        ]
    )
    portfolio_calculations = {
        calculation_id
        for decision in response["ticker_decisions"]
        for calculation_id in decision["calculation_ids"]
    }
    if (
        _NUMERIC_TEXT_PATTERN.search(portfolio_text)
        and not portfolio_calculations
    ):
        raise ContractError(
            "committee: numeric portfolio text requires a reconciled calculation"
        )
    decision_tickers: list[str] = []
    for index, decision in enumerate(response["ticker_decisions"]):
        ticker = decision["ticker"].upper()
        if ticker not in known_tickers:
            raise ContractError(f"committee.ticker_decisions[{index}]: unknown ticker")
        decision_tickers.append(ticker)
        role = entity_roles[ticker]
        if decision["classification"] not in _ROLE_ALLOWED_CLASSIFICATIONS[role]:
            raise ContractError(
                f"committee.ticker_decisions[{index}]: classification "
                f"{decision['classification']} is invalid for entity role {role}"
            )
        if not 0 <= decision["confidence_pct"] <= 100:
            raise ContractError(
                f"committee.ticker_decisions[{index}]: confidence must be 0..100"
            )
        for field in ("rationale", "long_term_case"):
            if not str(decision[field]).strip():
                raise ContractError(
                    f"committee.ticker_decisions[{index}]: {field} is empty"
                )
        if len(decision["claim_ids"]) != len(set(decision["claim_ids"])):
            raise ContractError(
                f"committee.ticker_decisions[{index}]: claim_ids must be unique"
            )
        if decision["classification"] != "abstain" and not decision["claim_ids"]:
            raise ContractError(
                f"committee.ticker_decisions[{index}]: non-abstain decision "
                "requires analyst claim_ids"
            )
        _validate_ticker_references(
            packet,
            ticker,
            decision["source_ids"],
            decision["calculation_ids"],
            path=f"committee.ticker_decisions[{index}]",
            require_source=decision["classification"] != "abstain",
            require_primary=decision["classification"]
            in {
                "hold_existing",
                "paper_trade_candidate",
                "real_trade_candidate",
                "trim_review",
                "exit_review",
            },
        )
        decision_text = "\n".join(
            [
                decision["rationale"],
                decision["long_term_case"],
                *decision["risks"],
                *decision["invalidation_conditions"],
            ]
        )
        if (
            _NUMERIC_TEXT_PATTERN.search(decision_text)
            and not decision["calculation_ids"]
        ):
            raise ContractError(
                f"committee.ticker_decisions[{index}]: numeric text requires "
                "a reconciled calculation"
            )
        if analyst is not None:
            unknown_claims = sorted(
                set(decision["claim_ids"]) - set(analyst_claims)
            )
            if unknown_claims:
                raise ContractError(
                    f"committee.ticker_decisions[{index}]: unknown analyst "
                    f"claim_ids {','.join(unknown_claims)}"
                )
            wrong_ticker_claims = sorted(
                claim_id
                for claim_id in decision["claim_ids"]
                if str(analyst_claims[claim_id]["ticker"]).upper() != ticker
            )
            if wrong_ticker_claims:
                raise ContractError(
                    f"committee.ticker_decisions[{index}]: cross-ticker analyst "
                    f"claim_ids {','.join(wrong_ticker_claims)}"
                )
            claim_sources = {
                source_id
                for claim_id in decision["claim_ids"]
                for source_id in analyst_claims[claim_id]["source_ids"]
            }
            claim_calculations = {
                calculation_id
                for claim_id in decision["claim_ids"]
                for calculation_id in analyst_claims[claim_id]["calculation_ids"]
            }
            if not claim_sources.issubset(set(decision["source_ids"])):
                raise ContractError(
                    f"committee.ticker_decisions[{index}]: decision sources "
                    "do not cover cited analyst claims"
                )
            if not claim_calculations.issubset(set(decision["calculation_ids"])):
                raise ContractError(
                    f"committee.ticker_decisions[{index}]: decision calculations "
                    "do not cover cited analyst claims"
                )
    if len(decision_tickers) != len(set(decision_tickers)):
        raise ContractError("committee: ticker decisions must be unique")
    if set(decision_tickers) != known_tickers:
        raise ContractError(
            "committee: ticker decisions must exactly match packet entities"
        )
    if response["automatic_action_allowed"] is not False:
        raise ContractError("committee: automatic action must remain false")
    buy_candidate_labels = {"paper_trade_candidate", "real_trade_candidate"}
    has_broken_exit = any(
        row["thesis_direction"] == "broken"
        and row["classification"] == "exit_review"
        for row in response["ticker_decisions"]
    )
    if response["material_thesis_break"] is not has_broken_exit:
        raise ContractError(
            "committee: material thesis break must equal the per-ticker "
            "broken exit-review rollup"
        )
    if any(
        row["thesis_direction"] == "broken"
        and row["classification"] not in {"exit_review", "abstain"}
        for row in response["ticker_decisions"]
    ):
        raise ContractError(
            "committee: broken ticker thesis must resolve to exit review or abstain"
        )
    if any(
        row["thesis_direction"] == "broken"
        and row["classification"] in buy_candidate_labels
        for row in response["ticker_decisions"]
    ):
        raise ContractError(
            "committee: broken ticker thesis cannot produce a buy candidate"
        )
    transition_labels = {
        row["classification"]
        for row in response["ticker_decisions"]
        if row["classification"] in TRANSITION_CLASSIFICATIONS
    }
    portfolio_transition = (
        response["portfolio_classification"] in TRANSITION_CLASSIFICATIONS
    )
    if transition_labels and not portfolio_transition:
        raise ContractError(
            "committee: ticker transition requires a portfolio transition"
        )
    if portfolio_transition:
        if not transition_labels:
            raise ContractError(
                "committee: portfolio transition requires a ticker transition"
            )
        expected_portfolio_transition = max(
            transition_labels,
            key=lambda label: _PORTFOLIO_TRANSITION_PRIORITY[label],
        )
        if response["portfolio_classification"] != expected_portfolio_transition:
            raise ContractError(
                "committee: portfolio transition must equal the highest-risk "
                "ticker transition"
            )
    if any(
        row["classification"] in TRANSITION_CLASSIFICATIONS
        and row["human_review_needed"] is not True
        for row in response["ticker_decisions"]
    ):
        raise ContractError(
            "committee: every ticker transition requires human review"
        )
    expected_rollup = _rollup_classifications(
        [row["classification"] for row in response["ticker_decisions"]]
    )
    if response["portfolio_classification"] != expected_rollup:
        raise ContractError(
            "committee: portfolio classification must equal the deterministic "
            "ticker-decision rollup"
        )
    _assert_no_imperative_action_language(response)
    _assert_no_sensitive_markers(response, "committee")
    return response


def validate_challenger(
    packet: dict[str, Any],
    response: dict[str, Any],
    analyst: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a source-bound decision made before seeing the committee.

    Structural blindness is proved by the caller's hashed input binding, not
    by the model's declaration alone. Reusing the committee's semantic
    validator keeps both independent proposals on exactly the same evidence,
    numeric, role, and action-language contract.
    """

    validate_schema(response, CHALLENGER_SCHEMA)
    if response["committee_proposal_seen"] is not False:
        raise ContractError(
            "challenger: committee proposal must not be visible"
        )
    if response["independent_precommitment"] is not True:
        raise ContractError(
            "challenger: independent precommitment must remain true"
        )
    normalized = copy.deepcopy(response)
    normalized.pop("committee_proposal_seen")
    normalized.pop("independent_precommitment")
    normalized["schema_version"] = COMMITTEE_SCHEMA_VERSION
    validate_committee(packet, normalized, analyst)
    _assert_no_sensitive_markers(response, "challenger")
    return response


def compare_blinded_challenger(
    packet: dict[str, Any],
    analyst: dict[str, Any],
    committee: dict[str, Any],
    challenger: dict[str, Any],
) -> dict[str, Any]:
    """Compare two independently formed source-bound research proposals.

    The challenger may preserve or reduce the committee's research ceiling.
    Any disagreement involving an action-changing class, or an unsafe
    cross-direction disagreement, resolves to ``abstain``. No branch can
    upgrade the committee proposal.
    """

    validate_committee(packet, committee, analyst)
    validate_challenger(packet, challenger, analyst)
    committee_by_ticker = {
        str(row["ticker"]).upper(): row
        for row in committee["ticker_decisions"]
    }
    challenger_by_ticker = {
        str(row["ticker"]).upper(): row
        for row in challenger["ticker_decisions"]
    }
    direction_score = {
        "strengthening": 2,
        "stable": 1,
        "unclear": 0,
        "weakening": -1,
        "broken": -2,
    }
    rows: list[dict[str, Any]] = []
    for entity in packet["entities"]:
        ticker = str(entity["ticker"]).upper()
        committee_row = committee_by_ticker[ticker]
        challenger_row = challenger_by_ticker[ticker]
        committee_class = committee_row["classification"]
        challenger_class = challenger_row["classification"]
        committee_direction = committee_row["thesis_direction"]
        challenger_direction = challenger_row["thesis_direction"]
        class_agreement = committee_class == challenger_class
        direction_agreement = committee_direction == challenger_direction
        opposing_direction = (
            direction_score[committee_direction]
            * direction_score[challenger_direction]
            < 0
            or (
                "broken"
                in {committee_direction, challenger_direction}
                and not direction_agreement
            )
        )

        if challenger["data_sufficiency"] == "insufficient":
            agreement_type = "challenger_data_insufficient"
            research_ceiling = "abstain"
        elif class_agreement and not opposing_direction:
            agreement_type = (
                "exact"
                if direction_agreement
                else "classification_only"
            )
            research_ceiling = committee_class
        elif (
            committee_class in TRANSITION_CLASSIFICATIONS
            or challenger_class in TRANSITION_CLASSIFICATIONS
        ):
            agreement_type = "transition_disagreement"
            research_ceiling = "abstain"
        elif (
            challenger_class
            in _ALLOWED_CRITIC_DOWNGRADES[committee_class]
        ):
            agreement_type = "safe_no_action_downgrade"
            research_ceiling = challenger_class
        else:
            agreement_type = "opposing_or_unsafe_direction"
            research_ceiling = "abstain"

        rows.append(
            {
                "ticker": ticker,
                "committee_classification": committee_class,
                "challenger_classification": challenger_class,
                "committee_thesis_direction": committee_direction,
                "challenger_thesis_direction": challenger_direction,
                "classification_agreement": class_agreement,
                "thesis_direction_agreement": direction_agreement,
                "agreement_type": agreement_type,
                "research_classification_ceiling": research_ceiling,
                "human_review_required": agreement_type
                in {
                    "transition_disagreement",
                    "opposing_or_unsafe_direction",
                },
            }
        )

    return {
        "schema_version": BLINDED_COMPARISON_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "committee_proposal_excluded_from_challenger_input": True,
        "ticker_comparisons": rows,
        "research_classification_ceiling": _rollup_classifications(
            [
                row["research_classification_ceiling"]
                for row in rows
            ]
        ),
        "full_classification_agreement": all(
            row["classification_agreement"] for row in rows
        ),
        "full_thesis_direction_agreement": all(
            row["thesis_direction_agreement"] for row in rows
        ),
        "human_review_required": any(
            row["human_review_required"] for row in rows
        ),
        "challenger_can_upgrade": False,
        "automatic_action_allowed": False,
    }


def validate_critic(
    packet: dict[str, Any],
    committee: dict[str, Any],
    response: dict[str, Any],
    analyst: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_committee(packet, committee, analyst)
    validate_schema(response, CRITIC_SCHEMA)
    if response["packet_id"] != packet["packet_id"]:
        raise ContractError("critic: packet_id mismatch")
    decisions = committee["ticker_decisions"]
    review_tickers = [
        str(review["ticker"]).upper() for review in response["ticker_reviews"]
    ]
    decision_tickers = [
        str(decision["ticker"]).upper() for decision in decisions
    ]
    if review_tickers != decision_tickers:
        raise ContractError(
            "critic: ticker reviews must exactly match committee decision order"
        )
    entity_roles = _entity_roles(packet)
    flattened_issues: list[dict[str, Any]] = []
    approved_source_union: set[str] = set()
    for index, (decision, review) in enumerate(
        zip(decisions, response["ticker_reviews"], strict=True)
    ):
        ticker = str(decision["ticker"]).upper()
        original_ticker_classification = decision["classification"]
        reviewed_classification = review["downgrade_to"]
        if (
            reviewed_classification
            not in _ALLOWED_CRITIC_DOWNGRADES[original_ticker_classification]
        ):
            raise ContractError(
                f"critic.ticker_reviews[{index}]: cannot upgrade or cross an "
                "unsafe classification direction"
            )
        if (
            reviewed_classification
            not in _ROLE_ALLOWED_CLASSIFICATIONS[entity_roles[ticker]]
        ):
            raise ContractError(
                f"critic.ticker_reviews[{index}]: classification "
                f"{reviewed_classification} is invalid for entity role "
                f"{entity_roles[ticker]}"
            )
        if len(review["approved_source_ids"]) != len(
            set(review["approved_source_ids"])
        ):
            raise ContractError(
                f"critic.ticker_reviews[{index}]: approved source ids "
                "must be unique"
            )
        _validate_ticker_references(
            packet,
            ticker,
            review["approved_source_ids"],
            [],
            path=f"critic.ticker_reviews[{index}].approved_source_ids",
            require_source=(
                review["verdict"] == "approve"
                and bool(decision["source_ids"])
            ),
            require_primary=False,
        )
        for issue_index, issue in enumerate(review["issues"]):
            _validate_ticker_references(
                packet,
                ticker,
                issue["source_ids"],
                [],
                path=(
                    f"critic.ticker_reviews[{index}].issues[{issue_index}]"
                ),
                require_source=False,
                require_primary=False,
            )
        if review["verdict"] == "approve":
            if not all(review[field] is True for field in _CRITIC_PASS_FIELDS):
                raise ContractError(
                    f"critic.ticker_reviews[{index}]: approve requires all "
                    "critic checks to pass"
                )
            if reviewed_classification != original_ticker_classification:
                raise ContractError(
                    f"critic.ticker_reviews[{index}]: approve cannot downgrade"
                )
            if not set(decision["source_ids"]).issubset(
                set(review["approved_source_ids"])
            ):
                raise ContractError(
                    f"critic.ticker_reviews[{index}]: approved sources do not "
                    "cover the committee ticker decision"
                )
        else:
            if all(review[field] is True for field in _CRITIC_PASS_FIELDS):
                raise ContractError(
                    f"critic.ticker_reviews[{index}]: revise/reject requires "
                    "at least one failed critic check"
                )
            if not review["issues"]:
                raise ContractError(
                    f"critic.ticker_reviews[{index}]: revise/reject requires "
                    "an inspectable issue"
                )
            if not any(
                issue["severity"] in {"medium", "high", "critical"}
                for issue in review["issues"]
            ):
                raise ContractError(
                    f"critic.ticker_reviews[{index}]: revise/reject requires "
                    "a medium-or-higher issue"
                )
            if reviewed_classification == original_ticker_classification:
                if original_ticker_classification != "abstain":
                    raise ContractError(
                        f"critic.ticker_reviews[{index}]: revise/reject must "
                        "produce a real downgrade"
                    )
        flattened_issues.extend(copy.deepcopy(review["issues"]))
        approved_source_union.update(review["approved_source_ids"])
    expected_verdict = max(
        (review["verdict"] for review in response["ticker_reviews"]),
        key=lambda verdict: _CRITIC_VERDICT_PRIORITY[verdict],
    )
    if response["verdict"] != expected_verdict:
        raise ContractError(
            "critic: global verdict must summarize per-ticker reviews"
        )
    for field in _CRITIC_PASS_FIELDS:
        expected_pass = all(
            review[field] is True for review in response["ticker_reviews"]
        )
        if response[field] is not expected_pass:
            raise ContractError(
                f"critic: global {field} must summarize per-ticker reviews"
            )
    expected_downgrade = _rollup_classifications(
        [review["downgrade_to"] for review in response["ticker_reviews"]]
    )
    if response["downgrade_to"] != expected_downgrade:
        raise ContractError(
            "critic: global downgrade must equal the per-ticker rollup"
        )
    if response["issues"] != flattened_issues:
        raise ContractError(
            "critic: global issues must equal flattened per-ticker issues"
        )
    if response["approved_source_ids"] != sorted(approved_source_union):
        raise ContractError(
            "critic: global approved sources must equal the sorted per-ticker union"
        )
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


def _transition_confidence_sanity_reasons(
    committee: dict[str, Any],
    decision: dict[str, Any],
) -> list[str]:
    """Reject structurally empty confidence without claiming calibration."""

    if decision["classification"] not in TRANSITION_CLASSIFICATIONS:
        return []
    ticker = str(decision["ticker"]).upper()
    reasons: list[str] = []
    if (
        int(committee["confidence_pct"])
        <= _TRANSITION_CONFIDENCE_SANITY_FLOOR_PCT
    ):
        reasons.append(
            "transition_confidence_sanity_failed:"
            f"committee_overall_at_or_below_"
            f"{_TRANSITION_CONFIDENCE_SANITY_FLOOR_PCT}:{ticker}"
        )
    for component_name, component_value in sorted(
        committee["confidence_components"].items()
    ):
        if (
            int(component_value)
            <= _TRANSITION_CONFIDENCE_SANITY_FLOOR_PCT
        ):
            reasons.append(
                "transition_confidence_sanity_failed:"
                f"committee_component_at_or_below_"
                f"{_TRANSITION_CONFIDENCE_SANITY_FLOOR_PCT}:"
                f"{ticker}:{component_name}"
            )
    if (
        int(decision["confidence_pct"])
        <= _TRANSITION_CONFIDENCE_SANITY_FLOOR_PCT
    ):
        reasons.append(
            "transition_confidence_sanity_failed:"
            f"ticker_at_or_below_"
            f"{_TRANSITION_CONFIDENCE_SANITY_FLOOR_PCT}:{ticker}"
        )
    return reasons


def adjudicate(
    packet: dict[str, Any],
    analyst: dict[str, Any],
    committee: dict[str, Any],
    critic: dict[str, Any] | None,
    *,
    challenger: dict[str, Any] | None = None,
    require_blinded_challenger_for_transitions: bool = False,
    distinct_valid_closes: int = 1,
    distinct_valid_closes_by_ticker: dict[str, int] | None = None,
    mode: str = "shadow",
) -> dict[str, Any]:
    """Return a deterministic, fail-closed research classification.

    The returned object is never an order and cannot authorize automatic action.
    Shadow mode can never affect the canonical decision or email.
    """

    validate_analyst(packet, analyst)
    validate_committee(packet, committee, analyst)
    if critic is not None:
        validate_critic(packet, committee, critic, analyst)
    if challenger is not None:
        validate_challenger(packet, challenger, analyst)

    proposed = committee["portfolio_classification"]
    proposed_ticker_decisions = copy.deepcopy(committee["ticker_decisions"])
    transition = any(
        row["classification"] in TRANSITION_CLASSIFICATIONS
        for row in proposed_ticker_decisions
    )
    critic_required = transition or committee["material_thesis_break"]
    challenger_required = (
        transition and require_blinded_challenger_for_transitions
    )
    blinded_comparison = (
        compare_blinded_challenger(
            packet,
            analyst,
            committee,
            challenger,
        )
        if challenger is not None
        else None
    )

    evidence_rows = (
        list(analyst["claims"])
        + list(committee["supporting_facts"])
        + list(committee["disconfirming_facts"])
        + list(committee["ticker_decisions"])
    )
    if challenger is not None:
        evidence_rows.extend(challenger["supporting_facts"])
        evidence_rows.extend(challenger["disconfirming_facts"])
        evidence_rows.extend(challenger["ticker_decisions"])
    calculation_ids = sorted(
        {
            calculation_id
            for row in evidence_rows
            for calculation_id in row["calculation_ids"]
        }
    )
    global_research_reasons: list[str] = []
    global_action_review_reasons: list[str] = []
    try:
        reconcile_calculations(packet, calculation_ids)
    except ContractError as exc:
        global_research_reasons.append(str(exc))

    gates = packet["gates"]
    if gates.get("point_in_time_safe") is not True:
        global_research_reasons.append(
            "hard_gate_failed:point_in_time_safe"
        )
    for gate in ("market_data_current", "account_state_consistent"):
        if gates.get(gate) is not True:
            global_action_review_reasons.append(
                f"action_gate_failed:{gate}"
            )
    if analyst["prompt_injection_detected"]:
        global_research_reasons.append("prompt_injection_detected")
    if gates.get("prompt_injection_text_detected") is True:
        global_research_reasons.append(
            "prompt_injection_text_detected"
        )
    if committee["data_sufficiency"] == "insufficient":
        global_research_reasons.append("committee_data_insufficient")

    def _is_fatal(reason: str) -> bool:
        return (
            reason.startswith("hard_gate_failed:")
            or reason.startswith("calculation ")
            or reason.startswith("not a finite decimal:")
            or reason.startswith("official_evidence_insufficient:")
            or reason.startswith("contradictory_evidence_unresolved:")
            or reason.startswith("transition_confidence_sanity_failed:")
            or reason
            in {
                "committee_data_insufficient",
                "prompt_injection_detected",
                "prompt_injection_text_detected",
            }
        )

    def _needs_human(reason: str) -> bool:
        return (
            reason.startswith("transition_gate_failed:")
            or reason.startswith("transition_")
            or reason.startswith("hard_gate_failed:")
            or reason.startswith("calculation ")
            or reason.startswith("not a finite decimal:")
            or reason.startswith("critic_")
            or reason.startswith("challenger_")
            or reason.startswith("official_evidence_insufficient:")
            or reason.startswith("contradictory_evidence_unresolved:")
            or reason
            in {
                "committee_data_insufficient",
                "material_thesis_break_lacks_high_primary_support",
                "prompt_injection_detected",
                "prompt_injection_text_detected",
            }
        )

    coverage_by_ticker = {
        str(row["ticker"]).upper(): row for row in analyst["ticker_coverage"]
    }
    supported_break_claim_ids = {
        str(claim["claim_id"])
        for claim in analyst["claims"]
        if claim["stance"] == "weakens"
        and claim["materiality"] == "high"
        and claim["time_horizon"] in {"medium_term", "long_term"}
    }
    critic_reviews = (
        {
            str(review["ticker"]).upper(): review
            for review in critic["ticker_reviews"]
        }
        if critic is not None
        else {}
    )
    challenger_comparisons = (
        {
            str(row["ticker"]).upper(): row
            for row in blinded_comparison["ticker_comparisons"]
        }
        if blinded_comparison is not None
        else {}
    )
    transition_required_gates = (
        "sec_held_coverage_complete",
        "fundamental_held_coverage_complete",
        "filing_artifact_provenance_complete",
    )
    deterministic_transition_eligible_tickers = {
        str(ticker).upper()
        for ticker in gates.get(
            "deterministic_transition_eligible_tickers",
            [],
        )
    }
    market_data_action_grade_tickers = {
        str(ticker).upper()
        for ticker in gates.get("market_data_action_grade_tickers", [])
    }
    valuation_action_grade_tickers = {
        str(ticker).upper()
        for ticker in gates.get("valuation_action_grade_tickers", [])
    }
    freshness_receipts_by_ticker = {
        str(receipt["ticker"]).upper(): receipt
        for receipt in packet.get("evidence_freshness", [])
    }
    allowed_classifications_by_ticker = {
        str(ticker).upper(): set(values)
        for ticker, values in gates["allowed_classifications_by_ticker"].items()
    }
    role_by_ticker = {
        str(entity["ticker"]).upper(): str(entity["role"])
        for entity in packet["entities"]
    }

    def _c9_policy_fallback(ticker: str) -> str:
        allowed = allowed_classifications_by_ticker[ticker]
        if role_by_ticker[ticker] == "held" and "hold_existing" in allowed:
            return "hold_existing"
        if role_by_ticker[ticker] == "candidate" and "watchlist" in allowed:
            return "watchlist"
        if role_by_ticker[ticker] == "candidate" and "reject" in allowed:
            return "reject"
        return "abstain"

    def _intersect_research_ceiling(
        current: str,
        ceiling: str,
    ) -> str:
        if current == ceiling or current == "abstain":
            return current
        if ceiling == "abstain":
            return "abstain"
        if (
            current in TRANSITION_CLASSIFICATIONS
            or ceiling in TRANSITION_CLASSIFICATIONS
        ):
            return "abstain"
        if ceiling in _ALLOWED_CRITIC_DOWNGRADES[current]:
            return ceiling
        if current in _ALLOWED_CRITIC_DOWNGRADES[ceiling]:
            return current
        return "abstain"

    effective_ticker_decisions: list[dict[str, Any]] = []
    all_reasons: list[str] = []
    for decision in proposed_ticker_decisions:
        ticker = str(decision["ticker"]).upper()
        proposed_ticker_classification = decision["classification"]
        research_ticker_classification = proposed_ticker_classification
        research_reasons = list(global_research_reasons)
        proposed_transition = (
            proposed_ticker_classification in TRANSITION_CLASSIFICATIONS
        )
        break_claim_supported = (
            proposed_ticker_classification == "exit_review"
            and decision["thesis_direction"] == "broken"
            and bool(
                set(decision["claim_ids"]).intersection(
                    supported_break_claim_ids
                )
            )
        )
        coverage = coverage_by_ticker[ticker]
        if coverage["official_evidence_sufficient"] is not True:
            research_reasons.append(
                f"official_evidence_insufficient:{ticker}"
            )
        if coverage["contradictory_evidence"] is True:
            research_reasons.append(
                f"contradictory_evidence_unresolved:{ticker}"
            )

        if proposed_transition:
            research_reasons.extend(
                _transition_confidence_sanity_reasons(
                    committee,
                    decision,
                )
            )
            if critic is None:
                research_reasons.append("critic_required_but_missing")
            for gate in transition_required_gates:
                if gates.get(gate) is not True:
                    research_reasons.append(f"transition_gate_failed:{gate}")
            if committee["data_sufficiency"] != "sufficient":
                research_reasons.append(
                    "transition_requires_sufficient_committee_data"
                )
            if coverage["official_evidence_sufficient"] is not True:
                research_reasons.append(
                    f"transition_official_evidence_insufficient:{ticker}"
                )
            if coverage["contradictory_evidence"] is True:
                research_reasons.append(
                    f"transition_contradictory_evidence_unresolved:{ticker}"
                )
            if analyst["unresolved_questions"]:
                research_reasons.append(
                    "transition_has_unresolved_analyst_questions"
                )
            if (
                proposed_ticker_classification == "exit_review"
                and decision["thesis_direction"] == "broken"
                and not break_claim_supported
            ):
                research_reasons.append(
                    "material_thesis_break_lacks_high_primary_support"
                )

        review = critic_reviews.get(ticker)
        if review is not None:
            critic_passes = all(
                review[field] is True for field in _CRITIC_PASS_FIELDS
            )
            if review["verdict"] != "approve" or not critic_passes:
                research_ticker_classification = review["downgrade_to"]
                research_reasons.append(
                    f"critic_{review['verdict']}:{ticker}"
                )

        challenger_comparison = challenger_comparisons.get(ticker)
        if (
            proposed_transition
            and challenger_required
            and challenger_comparison is None
        ):
            research_reasons.append(
                f"challenger_required_but_missing:{ticker}"
            )
        if challenger_comparison is not None:
            research_ceiling = challenger_comparison[
                "research_classification_ceiling"
            ]
            intersected = _intersect_research_ceiling(
                research_ticker_classification,
                research_ceiling,
            )
            if (
                intersected != research_ticker_classification
                or challenger_comparison["agreement_type"] != "exact"
            ):
                research_reasons.append(
                    "challenger_"
                    f"{challenger_comparison['agreement_type']}:{ticker}"
                )
            research_ticker_classification = intersected

        fatal_validation_failure = any(
            _is_fatal(reason) for reason in research_reasons
        )
        if fatal_validation_failure or (
            research_reasons
            and research_ticker_classification
            in TRANSITION_CLASSIFICATIONS
        ):
            research_ticker_classification = "abstain"

        # Research judgment and deterministic action-review eligibility are
        # deliberately separate.  C9 may block an action review, but it must
        # not silently rewrite a source-bound model thesis into HOLD/WATCH.
        # The action-facing ``classification`` remains fail-closed for
        # backward compatibility; ``research_classification`` preserves the
        # independently validated judgment for evaluation and publication.
        effective_ticker_classification = research_ticker_classification
        action_review_reasons: list[str] = list(
            global_action_review_reasons
        )
        if (
            effective_ticker_classification
            not in allowed_classifications_by_ticker[ticker]
        ):
            action_review_reasons.append(
                "c9_classification_not_allowed:"
                f"{ticker}:{effective_ticker_classification}"
            )
            effective_ticker_classification = _c9_policy_fallback(ticker)

        if research_ticker_classification in TRANSITION_CLASSIFICATIONS:
            if not (
                research_ticker_classification == "exit_review"
                and break_claim_supported
            ):
                if gates.get("market_data_action_grade") is not True:
                    action_review_reasons.append(
                        "transition_gate_failed:market_data_action_grade"
                    )
                elif ticker not in market_data_action_grade_tickers:
                    action_review_reasons.append(
                        "transition_gate_failed:"
                        f"market_data_action_grade_ticker:{ticker}"
                    )
                if ticker not in valuation_action_grade_tickers:
                    action_review_reasons.append(
                        "transition_gate_failed:"
                        f"valuation_action_grade_ticker:{ticker}"
                    )
            if action_review_reasons:
                effective_ticker_classification = _c9_policy_fallback(
                    ticker
                )
            freshness_reasons = freshness_action_review_reasons(
                freshness_receipts_by_ticker.get(ticker),
                ticker=ticker,
                require_market_and_valuation=not (
                    research_ticker_classification == "exit_review"
                    and break_claim_supported
                ),
            )
            if freshness_reasons:
                action_review_reasons.extend(freshness_reasons)
                effective_ticker_classification = _c9_policy_fallback(
                    ticker
                )
            if (
                not (
                    research_ticker_classification == "exit_review"
                    and break_claim_supported
                )
                and not gates.get("verified_close_session")
            ):
                action_review_reasons.append(
                    f"transition_verified_close_session_missing:{ticker}"
                )
                effective_ticker_classification = _c9_policy_fallback(
                    ticker
                )

        ticker_distinct_valid_closes = distinct_valid_closes
        if distinct_valid_closes_by_ticker is not None:
            raw_ticker_closes = distinct_valid_closes_by_ticker.get(
                ticker,
                distinct_valid_closes,
            )
            if (
                not isinstance(raw_ticker_closes, int)
                or isinstance(raw_ticker_closes, bool)
                or raw_ticker_closes < 0
            ):
                action_review_reasons.append(
                    f"invalid_distinct_valid_closes:{ticker}"
                )
                ticker_distinct_valid_closes = 0
            else:
                ticker_distinct_valid_closes = raw_ticker_closes

        if (
            effective_ticker_classification
            in {"paper_trade_candidate", "real_trade_candidate"}
            and ticker_distinct_valid_closes < 2
        ):
            effective_ticker_classification = _c9_policy_fallback(ticker)
            action_review_reasons.append(
                "two_distinct_valid_closes_not_met"
            )
        if (
            effective_ticker_classification
            in {"paper_trade_candidate", "real_trade_candidate"}
            and ticker not in deterministic_transition_eligible_tickers
        ):
            effective_ticker_classification = _c9_policy_fallback(ticker)
            action_review_reasons.append(
                f"transition_eligibility_pending_or_unknown:{ticker}"
            )

        action_review_aligned = (
            effective_ticker_classification
            == research_ticker_classification
        )
        if (
            research_ticker_classification
            in TRANSITION_CLASSIFICATIONS
            and not action_review_aligned
        ):
            action_review_reasons.append(
                f"research_action_review_divergence:{ticker}"
            )
        ticker_reasons = research_reasons + action_review_reasons
        ticker_validation_passed = not fatal_validation_failure
        risk_reduction_divergence = (
            research_ticker_classification
            in {"trim_review", "exit_review"}
            and not action_review_aligned
        )
        ticker_human_review = (
            effective_ticker_classification
            in TRANSITION_CLASSIFICATIONS
            or risk_reduction_divergence
            or any(
                _needs_human(reason) for reason in research_reasons
            )
        )
        effective_row = copy.deepcopy(decision)
        effective_row["proposed_classification"] = (
            proposed_ticker_classification
        )
        effective_row["research_classification"] = (
            research_ticker_classification
        )
        effective_row["action_review_classification"] = (
            effective_ticker_classification
        )
        effective_row["action_review_status"] = (
            "eligible"
            if research_ticker_classification
            in TRANSITION_CLASSIFICATIONS
            and action_review_aligned
            else "blocked"
            if research_ticker_classification
            in TRANSITION_CLASSIFICATIONS
            else "not_applicable"
        )
        effective_row["classification"] = effective_ticker_classification
        effective_row["validation_passed"] = ticker_validation_passed
        effective_row["research_reasons"] = sorted(
            set(research_reasons)
        )
        effective_row["action_review_reasons"] = sorted(
            set(action_review_reasons)
        )
        effective_row["reasons"] = sorted(set(ticker_reasons))
        effective_row["human_review_needed"] = ticker_human_review
        effective_row["critic_verdict"] = (
            review["verdict"] if review is not None else "missing"
        )
        effective_row["challenger_classification"] = (
            challenger_comparison["challenger_classification"]
            if challenger_comparison is not None
            else "missing"
        )
        effective_row["challenger_agreement_type"] = (
            challenger_comparison["agreement_type"]
            if challenger_comparison is not None
            else "missing"
        )
        research_confidence = int(decision["confidence_pct"])
        if research_ticker_classification == "abstain":
            research_confidence = 0
        elif (
            research_ticker_classification
            != proposed_ticker_classification
            or research_reasons
        ):
            research_confidence = min(research_confidence, 50)
        effective_row["research_confidence_pct"] = research_confidence
        if effective_ticker_classification == "abstain":
            effective_row["confidence_pct"] = 0
        elif (
            effective_ticker_classification
            != research_ticker_classification
            or ticker_reasons
        ):
            effective_row["confidence_pct"] = min(
                int(decision["confidence_pct"]),
                50,
            )
        effective_ticker_decisions.append(effective_row)
        all_reasons.extend(ticker_reasons)

    research_effective = _rollup_classifications(
        [
            row["research_classification"]
            for row in effective_ticker_decisions
        ]
    )
    effective = _rollup_classifications(
        [row["classification"] for row in effective_ticker_decisions]
    )
    reasons = sorted(set(all_reasons))
    accepted = all(
        row["validation_passed"] for row in effective_ticker_decisions
    )
    human_review_required = any(
        row["human_review_needed"] for row in effective_ticker_decisions
    )
    def _copy_for(
        classification: str,
        *,
        field: str,
    ) -> tuple[str, str]:
        transition_labels = {
            row[field]
            for row in effective_ticker_decisions
            if row[field] in TRANSITION_CLASSIFICATIONS
        }
        if len(transition_labels) <= 1:
            return _EFFECTIVE_DECISION_COPY[classification]
        label_text = {
            "paper_trade_candidate": "模拟候选",
            "real_trade_candidate": "真实仓位候选",
            "trim_review": "减仓复核",
            "exit_review": "退出复核",
        }
        ordered_labels = sorted(
            transition_labels,
            key=lambda label: _PORTFOLIO_TRANSITION_PRIORITY[label],
            reverse=True,
        )
        return (
            "明确研究结论：进入多项行动复核，风险降低项优先",
            "本次同时出现"
            + "、".join(label_text[label] for label in ordered_labels)
            + "；逐项复核，任何真实动作仍不由模型执行。",
        )

    research_headline, research_advice = _copy_for(
        research_effective,
        field="research_classification",
    )
    action_headline, action_advice = _copy_for(
        effective,
        field="classification",
    )
    action_review_aligned = all(
        row["research_classification"] == row["classification"]
        for row in effective_ticker_decisions
    )
    if action_review_aligned:
        effective_headline = research_headline
        effective_advice = research_advice
    else:
        effective_headline = (
            f"{research_headline}｜C9 动作资格未完全通过"
        )
        effective_advice = (
            f"{research_advice} 确定性动作层仍保持"
            f"“{action_headline}”；不要把研究结论误当作交易授权。"
        )
    if research_effective == "abstain":
        research_confidence = 0
    elif research_effective != proposed or reasons:
        research_confidence = min(int(committee["confidence_pct"]), 50)
    else:
        research_confidence = int(committee["confidence_pct"])
    if effective == "abstain":
        effective_confidence = 0
    elif effective != research_effective or reasons:
        effective_confidence = min(int(committee["confidence_pct"]), 50)
    else:
        effective_confidence = int(committee["confidence_pct"])
    return {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "mode": mode,
        "validation_passed": accepted,
        "proposed_classification": proposed,
        "research_classification": research_effective,
        "action_review_classification": effective,
        "effective_classification": effective,
        "action_review_aligned": action_review_aligned,
        "critic_required": critic_required,
        "critic_present": critic is not None,
        "blinded_challenger_required": challenger_required,
        "blinded_challenger_present": challenger is not None,
        "blinded_challenger_comparison": blinded_comparison,
        "distinct_valid_closes": distinct_valid_closes,
        "distinct_valid_closes_by_ticker": (
            {
                str(ticker).upper(): count
                for ticker, count in sorted(
                    (distinct_valid_closes_by_ticker or {}).items()
                )
            }
        ),
        "reasons": reasons,
        # Prominent copy is derived from the effective classification, never
        # from an unvalidated proposal.  If C9 blocks action eligibility, the
        # validated research conclusion remains visible and the divergence is
        # explicit instead of being silently rewritten.
        "headline": effective_headline,
        "decisive_advice": effective_advice,
        "research_headline": research_headline,
        "research_decisive_advice": research_advice,
        "action_review_headline": action_headline,
        "action_review_decisive_advice": action_advice,
        "research_confidence_pct": research_confidence,
        "confidence_pct": effective_confidence,
        "proposed_ticker_decisions": proposed_ticker_decisions,
        "ticker_decisions": effective_ticker_decisions,
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
        "challenger": CHALLENGER_SCHEMA,
    }
    try:
        return copy.deepcopy(schemas[role])
    except KeyError as exc:
        raise ContractError(f"unknown model role: {role}") from exc
