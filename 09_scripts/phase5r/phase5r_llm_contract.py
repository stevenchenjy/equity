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
                },
                ["ticker", "fact", "source_ids"],
            ),
        },
        "disconfirming_facts": {
            "type": "array",
            "items": _closed_object(
                {
                    "ticker": {"type": "string"},
                    "fact": {"type": "string"},
                    "source_ids": _string_array(),
                },
                ["ticker", "fact", "source_ids"],
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
        "confidence_components",
        "supporting_facts",
        "disconfirming_facts",
        "scenarios",
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
    gates = packet["gates"]
    close_count = gates.get("deterministic_action_stability_distinct_closes", 0)
    if (
        not isinstance(close_count, int)
        or isinstance(close_count, bool)
        or close_count < 0
    ):
        raise ContractError("packet: deterministic close count is invalid")
    for gate_name in (
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
        _validate_ticker_references(
            packet,
            ticker,
            claim["source_ids"],
            claim["calculation_ids"],
            path=f"analyst.claims[{index}]",
            require_source=claim["materiality"] in {"medium", "high"},
            require_primary=claim["materiality"] in {"medium", "high"},
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
    known_tickers = _tickers(packet)
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
                [],
                path=f"committee.{field}[{index}]",
                require_source=True,
                require_primary=True,
            )
    if any(
        not isinstance(response["scenarios"][name], str)
        or not response["scenarios"][name].strip()
        for name in ("bull", "base", "bear")
    ):
        raise ContractError("committee: bull/base/bear scenarios must be non-empty")
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
    if len(decision_tickers) != len(set(decision_tickers)):
        raise ContractError("committee: ticker decisions must be unique")
    if not _held_tickers(packet).issubset(set(decision_tickers)):
        raise ContractError("committee: every held ticker requires a decision")
    if response["automatic_action_allowed"] is not False:
        raise ContractError("committee: automatic action must remain false")
    buy_candidate_labels = {"paper_trade_candidate", "real_trade_candidate"}
    if response["material_thesis_break"] and (
        response["portfolio_classification"] in buy_candidate_labels
        or any(
            row["classification"] in buy_candidate_labels
            for row in response["ticker_decisions"]
        )
    ):
        raise ContractError(
            "committee: material thesis break cannot produce a buy candidate"
        )
    if response["material_thesis_break"] and not any(
        row["thesis_direction"] == "broken"
        and row["classification"] == "exit_review"
        for row in response["ticker_decisions"]
    ):
        raise ContractError(
            "committee: material thesis break requires a broken exit-review ticker"
        )
    if any(
        row["thesis_direction"] == "broken"
        and row["classification"] not in {"exit_review", "abstain"}
        for row in response["ticker_decisions"]
    ):
        raise ContractError(
            "committee: a broken thesis must resolve to exit review or abstain"
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
        if transition_labels != {response["portfolio_classification"]}:
            raise ContractError(
                "committee: portfolio and ticker transition classifications mismatch"
            )
    if any(
        row["classification"] in TRANSITION_CLASSIFICATIONS
        and row["human_review_needed"] is not True
        for row in response["ticker_decisions"]
    ):
        raise ContractError(
            "committee: every ticker transition requires human review"
        )
    _assert_no_imperative_action_language(response)
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
    if response["verdict"] == "approve":
        committee_sources = {
            source_id
            for decision in committee["ticker_decisions"]
            for source_id in decision["source_ids"]
        }
        if not committee_sources.issubset(set(response["approved_source_ids"])):
            raise ContractError(
                "critic: approved sources do not cover committee decisions"
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
    proposed_ticker_decisions = copy.deepcopy(committee["ticker_decisions"])
    transition = proposed in TRANSITION_CLASSIFICATIONS or any(
        row["classification"] in TRANSITION_CLASSIFICATIONS
        for row in proposed_ticker_decisions
    )
    transition_decisions = [
        row
        for row in proposed_ticker_decisions
        if row["classification"] in TRANSITION_CLASSIFICATIONS
    ]
    broken_exit_tickers = {
        str(row["ticker"]).upper()
        for row in transition_decisions
        if row["classification"] == "exit_review"
        and row["thesis_direction"] == "broken"
    }
    supported_break_tickers = {
        str(claim["ticker"]).upper()
        for claim in analyst["claims"]
        if claim["stance"] == "weakens"
        and claim["materiality"] == "high"
        and claim["time_horizon"] in {"medium_term", "long_term"}
    }
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
        primary_supported_thesis_break_exit = (
            committee["material_thesis_break"] is True
            and bool(transition_decisions)
            and all(
                row["classification"] == "exit_review"
                and row["thesis_direction"] == "broken"
                for row in transition_decisions
            )
            and broken_exit_tickers.issubset(supported_break_tickers)
        )
        market_dependent_transition = not primary_supported_thesis_break_exit
        if (
            market_dependent_transition
            and gates.get("market_data_action_grade") is not True
        ):
            reasons.append(
                "transition_gate_failed:market_data_action_grade"
            )

    if analyst["prompt_injection_detected"]:
        reasons.append("prompt_injection_detected")
    if packet["gates"].get("prompt_injection_text_detected") is True:
        reasons.append("prompt_injection_text_detected")
    if committee["data_sufficiency"] == "insufficient":
        reasons.append("committee_data_insufficient")
    if transition and committee["data_sufficiency"] != "sufficient":
        reasons.append("transition_requires_sufficient_committee_data")

    coverage_by_ticker = {
        str(row["ticker"]).upper(): row for row in analyst["ticker_coverage"]
    }
    for decision in transition_decisions:
        ticker = str(decision["ticker"]).upper()
        coverage = coverage_by_ticker.get(ticker)
        if coverage is None or coverage["official_evidence_sufficient"] is not True:
            reasons.append(
                f"transition_official_evidence_insufficient:{ticker}"
            )
        if coverage is not None and coverage["contradictory_evidence"] is True:
            reasons.append(
                f"transition_contradictory_evidence_unresolved:{ticker}"
            )
    if transition and analyst["unresolved_questions"]:
        reasons.append("transition_has_unresolved_analyst_questions")

    if committee["material_thesis_break"] and (
        not broken_exit_tickers
        or not broken_exit_tickers.issubset(supported_break_tickers)
    ):
        reasons.append("material_thesis_break_lacks_high_primary_support")

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
        committee["material_thesis_break"]
        and effective in {"paper_trade_candidate", "real_trade_candidate"}
    ):
        effective = "abstain"
        reasons.append("material_thesis_break_blocks_buy_candidate")

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
        in {
            "committee_data_insufficient",
            "prompt_injection_detected",
            "prompt_injection_text_detected",
        }
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
            in {
                "committee_data_insufficient",
                "prompt_injection_detected",
                "prompt_injection_text_detected",
            }
            for reason in reasons
        )
    )
    human_review_required = effective in TRANSITION_CLASSIFICATIONS or any(
        reason.startswith("transition_gate_failed:")
        or reason.startswith("transition_")
        or reason.startswith("hard_gate_failed:")
        or reason.startswith("calculation ")
        or reason.startswith("not a finite decimal:")
        or reason.startswith("critic_")
        or reason
        in {
            "committee_data_insufficient",
            "material_thesis_break_lacks_high_primary_support",
            "prompt_injection_detected",
            "prompt_injection_text_detected",
        }
        for reason in reasons
    )
    effective_ticker_decisions = copy.deepcopy(proposed_ticker_decisions)
    if effective == "abstain":
        for row in effective_ticker_decisions:
            row["classification"] = "abstain"
            row["confidence_pct"] = 0
            row["human_review_needed"] = human_review_required
    elif effective != proposed:
        for row in effective_ticker_decisions:
            if row["classification"] in TRANSITION_CLASSIFICATIONS:
                row["classification"] = effective
                row["human_review_needed"] = human_review_required
                row["confidence_pct"] = min(
                    int(row.get("confidence_pct", 0)),
                    50,
                )
    effective_headline, effective_advice = _EFFECTIVE_DECISION_COPY[effective]
    if effective == "abstain":
        effective_confidence = 0
    elif effective != proposed or reasons:
        effective_confidence = min(int(committee["confidence_pct"]), 50)
    else:
        effective_confidence = int(committee["confidence_pct"])
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
        # Prominent copy is derived from the effective classification, never
        # from a proposal that a critic or hard gate has already downgraded.
        "headline": effective_headline,
        "decisive_advice": effective_advice,
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
    }
    try:
        return copy.deepcopy(schemas[role])
    except KeyError as exc:
        raise ContractError(f"unknown model role: {role}") from exc
