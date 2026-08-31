"""Offline, forward-only evidence and critic contracts for future Phase 5R work.

This module deliberately does not alter the closed v1 contracts or either
sealed pilot runner.  It validates versioned sidecars that a future, separately
authorized workflow may bind to a validated packet.  It does not construct a
provider or initiate a repository-side provider request, and it has no
network, credential, brokerage, email, or execution capability. It can only
validate a disclosed interactive-AI provenance record; that record does not
authorize a provider call or establish reviewer independence.

The source metadata catalog atomizes evidence into one normalized record per
packet-local excerpt.  A companion source-text artifact binds each excerpt's
exact bytes to the packet hash, but does not establish the metadata's semantic
interpretation.  A claim-side citation binding then states exactly which roles
that excerpt supports.  This makes citation scope claim-relative while letting
deterministic code reject period, unit, baseline, source, and critic coverage
mismatches.
"""

from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from typing import Any

from phase5r_llm_internal_quality import (
    InternalQualityGuardError,
    lint_claim_evidence_scope,
)


EVIDENCE_METADATA_V2_SCHEMA_VERSION = "phase5r_llm_evidence_metadata_v2"
EVIDENCE_SOURCE_TEXTS_V2_SCHEMA_VERSION = "phase5r_llm_evidence_source_texts_v2"
ANALYST_EVIDENCE_BINDINGS_V2_SCHEMA_VERSION = (
    "phase5r_llm_analyst_evidence_bindings_v2"
)
COMMITTEE_TICKER_DECISIONS_V2_SCHEMA_VERSION = (
    "phase5r_llm_committee_ticker_decisions_v2"
)
CRITIC_COVERAGE_V2_SCHEMA_VERSION = "phase5r_llm_critic_coverage_v2"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_METRIC_LABEL_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
_UNITS = frozenset(
    {
        "currency_usd",
        "currency_usd_thousands",
        "currency_usd_millions",
        "currency_usd_billions",
        "currency_usd_per_share",
        "percent",
        "percentage_points",
        "percent_of_revenue",
        "shares",
        "count",
        "ratio",
        "days",
        "not_applicable",
    }
)
_PERIOD_KINDS = frozenset({"timeless", "as_of", "range"})
_COMPARISON_RELATIONSHIPS = frozenset(
    {"prior_period", "same_period_prior_year", "prior_as_of"}
)
_SUPPORT_ROLES = frozenset(
    {
        "claim",
        "period",
        "unit",
        "comparison_baseline",
        "entity_scope",
        "transaction_terms",
        "context_only",
    }
)
_CLAIM_CHARACTERISTICS = frozenset(
    {
        "qualitative",
        "quantitative",
        "comparative",
        "entity_scope",
        "transaction_terms",
    }
)
_MATERIALITY = frozenset({"low", "medium", "high"})
_VERDICTS = frozenset({"approve", "revise", "reject"})
_ISSUE_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
_ISSUE_DIMENSIONS = {
    "citation_scope": "citation_integrity_pass",
    "period_binding": "citation_integrity_pass",
    "unit_binding": "citation_integrity_pass",
    "comparison_baseline": "citation_integrity_pass",
    "entity_scope": "citation_integrity_pass",
    "transaction_terms": "citation_integrity_pass",
    "numeric_reconciliation": "numeric_reconciliation_pass",
    "factual_grounding": "factual_grounding_pass",
    "long_term_reasoning": "long_term_reasoning_pass",
    "action_proportionality": "action_proportionality_pass",
    "policy_boundary": "policy_boundary_pass",
}
_ISSUE_TYPES = frozenset({*_ISSUE_DIMENSIONS, "other"})
_ISSUE_REQUIRED_SUPPORT_ROLES = {
    "period_binding": frozenset({"period"}),
    "unit_binding": frozenset({"unit"}),
    "comparison_baseline": frozenset({"comparison_baseline"}),
    "entity_scope": frozenset({"entity_scope"}),
    "transaction_terms": frozenset({"transaction_terms"}),
    "numeric_reconciliation": frozenset({"claim"}),
    "factual_grounding": frozenset({"claim"}),
}
_CRITIC_PASS_FIELDS = (
    "factual_grounding_pass",
    "citation_integrity_pass",
    "numeric_reconciliation_pass",
    "long_term_reasoning_pass",
    "action_proportionality_pass",
    "policy_boundary_pass",
)
_SOURCE_REQUIRED_FIELDS = frozenset(
    {
        "source_id",
        "ticker",
        "content_sha256",
        "metric_label",
        "unit",
        "period",
        "supported_roles",
    }
)
_CALCULATION_REQUIRED_FIELDS = frozenset(
    {
        "calculation_id",
        "ticker",
        "packet_unit",
        "packet_period",
        "metric_label",
        "unit",
        "period",
    }
)
_CLAIM_REQUIRED_FIELDS = frozenset(
    {
        "claim_id",
        "analyst_claim_sha256",
        "ticker",
        "materiality",
        "metric_label",
        "unit",
        "period",
        "claim_characteristics",
        "lexical_scope_flags",
        "citation_bindings",
        "evidence_period",
        "evidence_unit",
        "comparison_baseline",
        "calculation_ids",
    }
)
_SOURCE_TEXT_REQUIRED_FIELDS = frozenset({"source_id", "excerpt_text"})
_LEXICAL_FLAG_CHARACTERISTICS = {
    "comparative_direction_requires_baseline_check": "comparative",
    "scope_or_superlative_requires_explicit_support": "entity_scope",
    "incorporated_material_scope_check": "transaction_terms",
}
_LEXICAL_FLAG_ISSUE_TYPES = {
    "comparative_direction_requires_baseline_check": "comparison_baseline",
    "period_binding_not_visible_in_excerpt": "period_binding",
    "scope_or_superlative_requires_explicit_support": "entity_scope",
    "incorporated_material_scope_check": "transaction_terms",
}
_COMMITTEE_DECISION_BINDING_REQUIRED_FIELDS = frozenset(
    {
        "ticker",
        "claim_ids",
        "committee_decision_sha256",
    }
)


class EvidenceContractV2Error(ValueError):
    """A future-v2 evidence or critic sidecar violated its closed contract."""


def _canonical_sha256(value: Any) -> str:
    """Return a canonical-JSON digest, distinct from an artifact raw-byte hash."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvidenceContractV2Error(f"{label}: expected object")
    return value


def _require_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvidenceContractV2Error(f"{label}: expected non-empty string")
    return value


def _require_closed_keys(
    value: Any,
    *,
    required: frozenset[str],
    label: str,
) -> dict[str, Any]:
    row = _require_object(value, label=label)
    keys = set(row)
    if keys != required:
        missing = sorted(required - keys)
        extras = sorted(keys - required)
        details: list[str] = []
        if missing:
            details.append("missing " + ",".join(missing))
        if extras:
            details.append("unexpected " + ",".join(extras))
        raise EvidenceContractV2Error(f"{label}: field mismatch ({'; '.join(details)})")
    return row


def _require_identifier_list(
    value: Any,
    *,
    label: str,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise EvidenceContractV2Error(f"{label}: expected array")
    if not allow_empty and not value:
        raise EvidenceContractV2Error(f"{label}: expected a non-empty array")
    normalized = [_require_text(item, label=f"{label}[{index}]") for index, item in enumerate(value)]
    if len(normalized) != len(set(normalized)):
        raise EvidenceContractV2Error(f"{label}: values must be unique")
    return normalized


def _require_sha256(value: Any, *, label: str) -> str:
    digest = _require_text(value, label=label)
    if _SHA256_PATTERN.fullmatch(digest) is None:
        raise EvidenceContractV2Error(f"{label}: expected lowercase sha256")
    return digest


def _require_metric_label(value: Any, *, label: str) -> str:
    metric_label = _require_text(value, label=label)
    if _METRIC_LABEL_PATTERN.fullmatch(metric_label) is None:
        raise EvidenceContractV2Error(
            f"{label}: expected lowercase underscore metric label"
        )
    return metric_label


def _require_unit(value: Any, *, label: str) -> str:
    unit = _require_text(value, label=label)
    if unit not in _UNITS:
        raise EvidenceContractV2Error(f"{label}: unsupported normalized unit")
    return unit


def _period_key(value: Any, *, label: str) -> tuple[str, ...]:
    period = _require_object(value, label=label)
    kind = _require_text(period.get("kind"), label=f"{label}.kind")
    if kind not in _PERIOD_KINDS:
        raise EvidenceContractV2Error(f"{label}: unsupported period kind")
    if kind == "timeless":
        if set(period) != {"kind"}:
            raise EvidenceContractV2Error(f"{label}: timeless period field mismatch")
        return (kind,)
    if kind == "as_of":
        if set(period) != {"kind", "as_of"}:
            raise EvidenceContractV2Error(f"{label}: as_of period field mismatch")
        as_of = _require_text(period["as_of"], label=f"{label}.as_of")
        try:
            date.fromisoformat(as_of)
        except ValueError as exc:
            raise EvidenceContractV2Error(f"{label}: invalid as_of date") from exc
        return (kind, as_of)
    if set(period) != {"kind", "start_date", "end_date"}:
        raise EvidenceContractV2Error(f"{label}: range period field mismatch")
    start_date = _require_text(period["start_date"], label=f"{label}.start_date")
    end_date = _require_text(period["end_date"], label=f"{label}.end_date")
    try:
        parsed_start = date.fromisoformat(start_date)
        parsed_end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise EvidenceContractV2Error(f"{label}: invalid range date") from exc
    if parsed_start > parsed_end:
        raise EvidenceContractV2Error(f"{label}: range start must not exceed end")
    return (kind, start_date, end_date)


def _packet_source_map(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = packet.get("source_catalog")
    if not isinstance(sources, list):
        raise EvidenceContractV2Error("packet.source_catalog: expected array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(sources):
        row = _require_object(value, label=f"packet.source_catalog[{index}]")
        source_id = _require_text(row.get("source_id"), label=f"packet.source_catalog[{index}].source_id")
        _require_text(row.get("ticker"), label=f"packet.source_catalog[{index}].ticker")
        _require_sha256(
            row.get("content_sha256"),
            label=f"packet.source_catalog[{index}].content_sha256",
        )
        if source_id in result:
            raise EvidenceContractV2Error("packet.source_catalog: source_ids must be unique")
        result[source_id] = row
    return result


def _packet_calculation_map(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    calculations = packet.get("calculations")
    if not isinstance(calculations, list):
        raise EvidenceContractV2Error("packet.calculations: expected array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(calculations):
        row = _require_object(value, label=f"packet.calculations[{index}]")
        calculation_id = _require_text(
            row.get("calculation_id"),
            label=f"packet.calculations[{index}].calculation_id",
        )
        _require_text(row.get("ticker"), label=f"packet.calculations[{index}].ticker")
        _require_text(row.get("unit"), label=f"packet.calculations[{index}].unit")
        _require_text(row.get("period"), label=f"packet.calculations[{index}].period")
        if calculation_id in result:
            raise EvidenceContractV2Error("packet.calculations: calculation_ids must be unique")
        result[calculation_id] = row
    return result


def _source_text_map_v2(
    packet: dict[str, Any], source_texts: Any
) -> dict[str, str]:
    """Bind exact packet-local excerpt text to every source-catalog hash.

    This verifies byte-derived excerpt identity only. It deliberately does not
    infer metric, unit, period, or semantic support from natural language;
    those normalizations remain separately scoped in the handoff result.
    """

    source_texts = _require_closed_keys(
        source_texts,
        required=frozenset({"schema_version", "packet_id", "sources"}),
        label="evidence_source_texts_v2",
    )
    packet_id = _require_text(packet.get("packet_id"), label="packet.packet_id")
    if source_texts["schema_version"] != EVIDENCE_SOURCE_TEXTS_V2_SCHEMA_VERSION:
        raise EvidenceContractV2Error(
            "evidence_source_texts_v2: schema version mismatch"
        )
    if source_texts["packet_id"] != packet_id:
        raise EvidenceContractV2Error("evidence_source_texts_v2: packet_id mismatch")
    rows = source_texts["sources"]
    if not isinstance(rows, list):
        raise EvidenceContractV2Error("evidence_source_texts_v2.sources: expected array")
    packet_sources = _packet_source_map(packet)
    result: dict[str, str] = {}
    for index, value in enumerate(rows):
        label = f"evidence_source_texts_v2.sources[{index}]"
        row = _require_closed_keys(
            value, required=_SOURCE_TEXT_REQUIRED_FIELDS, label=label
        )
        source_id = _require_text(row["source_id"], label=f"{label}.source_id")
        excerpt_text = _require_text(
            row["excerpt_text"], label=f"{label}.excerpt_text"
        )
        packet_source = packet_sources.get(source_id)
        if packet_source is None:
            raise EvidenceContractV2Error(f"{label}: unknown packet source")
        if source_id in result:
            raise EvidenceContractV2Error(
                "evidence_source_texts_v2.sources: source_ids must be unique"
            )
        actual_hash = hashlib.sha256(excerpt_text.encode("utf-8")).hexdigest()
        if actual_hash != packet_source["content_sha256"]:
            raise EvidenceContractV2Error(f"{label}: excerpt text hash mismatch")
        result[source_id] = excerpt_text
    if set(result) != set(packet_sources):
        raise EvidenceContractV2Error(
            "evidence_source_texts_v2.sources: must exactly cover packet source_ids"
        )
    return result


def _role_set(value: Any, *, label: str) -> set[str]:
    roles = _require_identifier_list(value, label=label, allow_empty=False)
    unknown = sorted(set(roles) - _SUPPORT_ROLES)
    if unknown:
        raise EvidenceContractV2Error(f"{label}: unsupported roles {','.join(unknown)}")
    if "context_only" in roles and len(roles) != 1:
        raise EvidenceContractV2Error(f"{label}: context_only cannot be combined")
    return set(roles)


def validate_evidence_metadata_v2(
    packet: dict[str, Any],
    metadata: dict[str, Any],
    *,
    source_texts: dict[str, Any],
) -> dict[str, Any]:
    """Validate normalized source/calculation metadata against a packet's IDs.

    The caller remains responsible for first validating the packet with its own
    versioned packet validator. It verifies the supplied packet-local excerpt
    text against each packet hash, but does not fetch, dereference, or log
    evidence and does not infer semantic normalized fields from text.
    """

    packet = _require_object(packet, label="packet")
    packet_id = _require_text(packet.get("packet_id"), label="packet.packet_id")
    _source_text_map_v2(packet, source_texts)
    metadata = _require_closed_keys(
        metadata,
        required=frozenset(
            {
                "schema_version",
                "packet_id",
                "source_texts_canonical_json_sha256",
                "sources",
                "calculations",
            }
        ),
        label="evidence_metadata_v2",
    )
    if metadata["schema_version"] != EVIDENCE_METADATA_V2_SCHEMA_VERSION:
        raise EvidenceContractV2Error("evidence_metadata_v2: schema version mismatch")
    if metadata["packet_id"] != packet_id:
        raise EvidenceContractV2Error("evidence_metadata_v2: packet_id mismatch")
    _require_sha256(
        metadata["source_texts_canonical_json_sha256"],
        label="evidence_metadata_v2.source_texts_canonical_json_sha256",
    )
    if metadata["source_texts_canonical_json_sha256"] != _canonical_sha256(source_texts):
        raise EvidenceContractV2Error(
            "evidence_metadata_v2: source-text canonical-json hash mismatch"
        )

    packet_sources = _packet_source_map(packet)
    sources = metadata["sources"]
    if not isinstance(sources, list):
        raise EvidenceContractV2Error("evidence_metadata_v2.sources: expected array")
    source_map: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(sources):
        row = _require_closed_keys(
            value,
            required=_SOURCE_REQUIRED_FIELDS,
            label=f"evidence_metadata_v2.sources[{index}]",
        )
        source_id = _require_text(row["source_id"], label=f"evidence_metadata_v2.sources[{index}].source_id")
        packet_source = packet_sources.get(source_id)
        if packet_source is None:
            raise EvidenceContractV2Error(
                f"evidence_metadata_v2.sources[{index}]: unknown packet source"
            )
        if source_id in source_map:
            raise EvidenceContractV2Error("evidence_metadata_v2.sources: source_ids must be unique")
        if row["ticker"] != packet_source["ticker"]:
            raise EvidenceContractV2Error(
                f"evidence_metadata_v2.sources[{index}]: ticker mismatch"
            )
        if row["content_sha256"] != packet_source["content_sha256"]:
            raise EvidenceContractV2Error(
                f"evidence_metadata_v2.sources[{index}]: excerpt hash mismatch"
            )
        _require_text(row["ticker"], label=f"evidence_metadata_v2.sources[{index}].ticker")
        _require_sha256(
            row["content_sha256"],
            label=f"evidence_metadata_v2.sources[{index}].content_sha256",
        )
        _require_metric_label(
            row["metric_label"],
            label=f"evidence_metadata_v2.sources[{index}].metric_label",
        )
        _require_unit(row["unit"], label=f"evidence_metadata_v2.sources[{index}].unit")
        _period_key(row["period"], label=f"evidence_metadata_v2.sources[{index}].period")
        _role_set(
            row["supported_roles"],
            label=f"evidence_metadata_v2.sources[{index}].supported_roles",
        )
        source_map[source_id] = row
    if set(source_map) != set(packet_sources):
        raise EvidenceContractV2Error(
            "evidence_metadata_v2.sources: must exactly cover packet source_ids"
        )

    packet_calculations = _packet_calculation_map(packet)
    calculations = metadata["calculations"]
    if not isinstance(calculations, list):
        raise EvidenceContractV2Error("evidence_metadata_v2.calculations: expected array")
    calculation_map: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(calculations):
        row = _require_closed_keys(
            value,
            required=_CALCULATION_REQUIRED_FIELDS,
            label=f"evidence_metadata_v2.calculations[{index}]",
        )
        calculation_id = _require_text(
            row["calculation_id"],
            label=f"evidence_metadata_v2.calculations[{index}].calculation_id",
        )
        packet_calculation = packet_calculations.get(calculation_id)
        if packet_calculation is None:
            raise EvidenceContractV2Error(
                f"evidence_metadata_v2.calculations[{index}]: unknown packet calculation"
            )
        if calculation_id in calculation_map:
            raise EvidenceContractV2Error(
                "evidence_metadata_v2.calculations: calculation_ids must be unique"
            )
        if row["ticker"] != packet_calculation["ticker"]:
            raise EvidenceContractV2Error(
                f"evidence_metadata_v2.calculations[{index}]: ticker mismatch"
            )
        if (
            row["packet_unit"] != packet_calculation["unit"]
            or row["packet_period"] != packet_calculation["period"]
        ):
            raise EvidenceContractV2Error(
                f"evidence_metadata_v2.calculations[{index}]: packet unit/period mismatch"
            )
        for field in ("ticker", "packet_unit", "packet_period"):
            _require_text(
                row[field], label=f"evidence_metadata_v2.calculations[{index}].{field}"
            )
        _require_metric_label(
            row["metric_label"],
            label=f"evidence_metadata_v2.calculations[{index}].metric_label",
        )
        _require_unit(
            row["unit"], label=f"evidence_metadata_v2.calculations[{index}].unit"
        )
        _period_key(
            row["period"], label=f"evidence_metadata_v2.calculations[{index}].period"
        )
        calculation_map[calculation_id] = row
    if set(calculation_map) != set(packet_calculations):
        raise EvidenceContractV2Error(
            "evidence_metadata_v2.calculations: must exactly cover packet calculation_ids"
        )
    return metadata


def _bindings_by_source(
    claim: dict[str, Any],
    source_map: dict[str, dict[str, Any]],
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    bindings = claim["citation_bindings"]
    if not isinstance(bindings, list) or not bindings:
        raise EvidenceContractV2Error(f"{label}.citation_bindings: expected non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(bindings):
        binding = _require_closed_keys(
            value,
            required=frozenset({"source_id", "cited_excerpt_sha256", "support_roles"}),
            label=f"{label}.citation_bindings[{index}]",
        )
        source_id = _require_text(
            binding["source_id"], label=f"{label}.citation_bindings[{index}].source_id"
        )
        source = source_map.get(source_id)
        if source is None:
            raise EvidenceContractV2Error(
                f"{label}.citation_bindings[{index}]: unknown source_id"
            )
        if source_id in result:
            raise EvidenceContractV2Error(f"{label}.citation_bindings: source_ids must be unique")
        if binding["cited_excerpt_sha256"] != source["content_sha256"]:
            raise EvidenceContractV2Error(
                f"{label}.citation_bindings[{index}]: excerpt binding mismatch"
            )
        _require_sha256(
            binding["cited_excerpt_sha256"],
            label=f"{label}.citation_bindings[{index}].cited_excerpt_sha256",
        )
        roles = _role_set(
            binding["support_roles"],
            label=f"{label}.citation_bindings[{index}].support_roles",
        )
        supported_roles = _role_set(
            source["supported_roles"],
            label=f"{label}.citation_bindings[{index}].source_metadata_roles",
        )
        if not roles.issubset(supported_roles):
            raise EvidenceContractV2Error(
                f"{label}.citation_bindings[{index}]: roles not supported by source metadata"
            )
        result[source_id] = binding
    return result


def _source_ids_for_role(bindings: dict[str, dict[str, Any]], role: str) -> list[str]:
    return [
        source_id
        for source_id, binding in bindings.items()
        if role in set(binding["support_roles"])
    ]


def _assert_sources_match_claim_measure(
    source_ids: list[str],
    source_map: dict[str, dict[str, Any]],
    claim: dict[str, Any],
    *,
    label: str,
) -> None:
    expected_period = _period_key(claim["period"], label=f"{label}.period")
    for source_id in source_ids:
        source = source_map[source_id]
        if (
            source["metric_label"] != claim["metric_label"]
            or source["unit"] != claim["unit"]
            or _period_key(source["period"], label=f"{label}.source[{source_id}].period")
            != expected_period
        ):
            raise EvidenceContractV2Error(
                f"{label}: claim source metric/unit/period mismatch"
            )


def _validate_evidence_field(
    value: Any,
    *,
    field: str,
    expected_value: Any,
    bindings: dict[str, dict[str, Any]],
    source_map: dict[str, dict[str, Any]],
    label: str,
) -> None:
    row = _require_closed_keys(
        value,
        required=frozenset({"value", "source_ids"}),
        label=f"{label}.{field}",
    )
    if field == "evidence_period":
        if _period_key(row["value"], label=f"{label}.{field}.value") != _period_key(
            expected_value, label=f"{label}.{field}.expected"
        ):
            raise EvidenceContractV2Error(f"{label}.{field}: value must exactly match claim")
    elif row["value"] != expected_value:
        raise EvidenceContractV2Error(f"{label}.{field}: value must exactly match claim")
    source_ids = _require_identifier_list(
        row["source_ids"], label=f"{label}.{field}.source_ids", allow_empty=False
    )
    required_role = "period" if field == "evidence_period" else "unit"
    for source_id in source_ids:
        binding = bindings.get(source_id)
        if binding is None or required_role not in set(binding["support_roles"]):
            raise EvidenceContractV2Error(
                f"{label}.{field}: source_ids must cite the {required_role} role"
            )
        source = source_map[source_id]
        if field == "evidence_period":
            if _period_key(source["period"], label=f"{label}.{field}.source_period") != _period_key(
                expected_value, label=f"{label}.{field}.claim_period"
            ):
                raise EvidenceContractV2Error(
                    f"{label}.{field}: source period mismatch"
                )
        elif source["unit"] != expected_value:
            raise EvidenceContractV2Error(f"{label}.{field}: source unit mismatch")


def _validate_comparison_baseline(
    value: Any,
    *,
    claim: dict[str, Any],
    bindings: dict[str, dict[str, Any]],
    source_map: dict[str, dict[str, Any]],
    label: str,
) -> None:
    baseline = _require_closed_keys(
        value,
        required=frozenset(
            {"metric_label", "unit", "period", "relationship", "source_ids"}
        ),
        label=f"{label}.comparison_baseline",
    )
    metric_label = _require_metric_label(
        baseline["metric_label"], label=f"{label}.comparison_baseline.metric_label"
    )
    unit = _require_unit(baseline["unit"], label=f"{label}.comparison_baseline.unit")
    period = _period_key(
        baseline["period"], label=f"{label}.comparison_baseline.period"
    )
    relationship = _require_text(
        baseline["relationship"],
        label=f"{label}.comparison_baseline.relationship",
    )
    if relationship not in _COMPARISON_RELATIONSHIPS:
        raise EvidenceContractV2Error(
            f"{label}.comparison_baseline: unsupported relationship"
        )
    claim_period = _period_key(claim["period"], label=f"{label}.period")
    if metric_label != claim["metric_label"]:
        raise EvidenceContractV2Error(
            f"{label}.comparison_baseline: metric_label must match claim"
        )
    if unit != claim["unit"]:
        raise EvidenceContractV2Error(
            f"{label}.comparison_baseline: unit must match claim"
        )
    if "timeless" in {period[0], claim_period[0]} or period == claim_period:
        raise EvidenceContractV2Error(
            f"{label}.comparison_baseline: period must be distinct and dated"
        )
    if relationship == "prior_period":
        if period[0] != "range" or claim_period[0] != "range":
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: prior_period requires two ranges"
            )
        if date.fromisoformat(period[2]) >= date.fromisoformat(claim_period[1]):
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: prior_period must end before claim period"
            )
    elif relationship == "same_period_prior_year":
        if period[0] != "range" or claim_period[0] != "range":
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: same_period_prior_year requires two ranges"
            )
        baseline_start = date.fromisoformat(period[1])
        baseline_end = date.fromisoformat(period[2])
        claim_start = date.fromisoformat(claim_period[1])
        claim_end = date.fromisoformat(claim_period[2])
        if (
            baseline_start.year != claim_start.year - 1
            or baseline_end.year != claim_end.year - 1
            or (baseline_start.month, baseline_start.day)
            != (claim_start.month, claim_start.day)
            or (baseline_end.month, baseline_end.day)
            != (claim_end.month, claim_end.day)
        ):
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: same_period_prior_year dates mismatch"
            )
    elif relationship == "prior_as_of":
        if period[0] != "as_of" or claim_period[0] != "as_of":
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: prior_as_of requires two as_of periods"
            )
        if date.fromisoformat(period[1]) >= date.fromisoformat(claim_period[1]):
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: prior_as_of must precede claim period"
            )
    source_ids = _require_identifier_list(
        baseline["source_ids"],
        label=f"{label}.comparison_baseline.source_ids",
        allow_empty=False,
    )
    for source_id in source_ids:
        binding = bindings.get(source_id)
        if binding is None or "comparison_baseline" not in set(binding["support_roles"]):
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: source_ids must cite the comparison_baseline role"
            )
        source = source_map[source_id]
        if (
            source["metric_label"] != metric_label
            or source["unit"] != unit
            or _period_key(
                source["period"], label=f"{label}.comparison_baseline.source_period"
            )
            != period
        ):
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: source metric/unit/period mismatch"
            )


def _validate_lexical_scope_flags(
    claim: dict[str, Any],
    *,
    analyst_claim: dict[str, Any],
    characteristics: list[str],
    bindings: dict[str, dict[str, Any]],
    source_text_map: dict[str, str],
    label: str,
) -> None:
    """Require sidecar scope labels to include deterministic lexical warnings.

    The quality guard is intentionally conservative: a lexical match is not a
    truth judgment. It only prevents the sidecar from classifying a flagged
    original claim as ordinary qualitative text and thereby bypassing the
    corresponding citation structure.
    """

    cited_excerpts = [
        {"source_id": source_id, "excerpt_text": source_text_map[source_id]}
        for source_id in bindings
    ]
    try:
        lint_result = lint_claim_evidence_scope(
            claim=analyst_claim["claim"],
            period=json.dumps(
                claim["period"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ),
            unit=claim["unit"],
            cited_excerpts=cited_excerpts,
        )
    except InternalQualityGuardError as exc:
        raise EvidenceContractV2Error(f"{label}: lexical scope lint failed") from exc
    expected_flags = [row["code"] for row in lint_result["flags"]]
    supplied_flags = _require_identifier_list(
        claim["lexical_scope_flags"],
        label=f"{label}.lexical_scope_flags",
        allow_empty=True,
    )
    if supplied_flags != expected_flags:
        raise EvidenceContractV2Error(
            f"{label}.lexical_scope_flags: must exactly match deterministic scope lint"
        )
    required_characteristics = {
        _LEXICAL_FLAG_CHARACTERISTICS[flag]
        for flag in expected_flags
        if flag in _LEXICAL_FLAG_CHARACTERISTICS
    }
    if analyst_claim["calculation_ids"]:
        required_characteristics.add("quantitative")
    missing = sorted(required_characteristics - set(characteristics))
    if missing:
        raise EvidenceContractV2Error(
            f"{label}.claim_characteristics: missing lexical requirement "
            + ",".join(missing)
        )


def _validate_claim_calculations(
    claim: dict[str, Any],
    calculation_map: dict[str, dict[str, Any]],
    *,
    label: str,
) -> None:
    calculation_ids = _require_identifier_list(
        claim["calculation_ids"], label=f"{label}.calculation_ids", allow_empty=True
    )
    characteristics = set(claim["claim_characteristics"])
    if "quantitative" in characteristics and not calculation_ids:
        raise EvidenceContractV2Error(
            f"{label}.calculation_ids: quantitative claim requires a calculation"
        )
    expected_period = _period_key(claim["period"], label=f"{label}.period")
    for calculation_id in calculation_ids:
        calculation = calculation_map.get(calculation_id)
        if calculation is None:
            raise EvidenceContractV2Error(
                f"{label}.calculation_ids: unknown calculation_id"
            )
        if (
            calculation["ticker"] != claim["ticker"]
            or calculation["metric_label"] != claim["metric_label"]
            or calculation["unit"] != claim["unit"]
            or _period_key(
                calculation["period"], label=f"{label}.calculation_period"
            )
            != expected_period
        ):
            raise EvidenceContractV2Error(
                f"{label}.calculation_ids: calculation metric/unit/period mismatch"
            )


def _analyst_claim_map(
    analyst_response: Any,
    *,
    packet_id: str,
) -> dict[str, dict[str, Any]]:
    """Return the cited analyst claim universe for sidecar linkage checks.

    The caller must separately run its applicable analyst response validator.
    This helper intentionally checks only the fields the sidecar must bind, so
    it can overlay an unchanged closed v1 analyst response.
    """

    response = _require_object(analyst_response, label="analyst_response")
    if response.get("packet_id") != packet_id:
        raise EvidenceContractV2Error("analyst_response: packet_id mismatch")
    claims = response.get("claims")
    if not isinstance(claims, list) or not claims:
        raise EvidenceContractV2Error("analyst_response.claims: expected non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(claims):
        label = f"analyst_response.claims[{index}]"
        claim = _require_object(value, label=label)
        claim_id = _require_text(claim.get("claim_id"), label=f"{label}.claim_id")
        _require_text(claim.get("ticker"), label=f"{label}.ticker")
        _require_text(claim.get("claim"), label=f"{label}.claim")
        _require_text(claim.get("materiality"), label=f"{label}.materiality")
        source_ids = _require_identifier_list(
            claim.get("source_ids"), label=f"{label}.source_ids", allow_empty=True
        )
        cited_hashes = _require_identifier_list(
            claim.get("cited_excerpt_sha256"),
            label=f"{label}.cited_excerpt_sha256",
            allow_empty=True,
        )
        if len(source_ids) != len(cited_hashes):
            raise EvidenceContractV2Error(
                f"{label}: source_ids and cited_excerpt_sha256 must align"
            )
        for hash_index, cited_hash in enumerate(cited_hashes):
            _require_sha256(
                cited_hash,
                label=f"{label}.cited_excerpt_sha256[{hash_index}]",
            )
        _require_identifier_list(
            claim.get("calculation_ids"),
            label=f"{label}.calculation_ids",
            allow_empty=True,
        )
        if claim_id in result:
            raise EvidenceContractV2Error("analyst_response: claim_ids must be unique")
        result[claim_id] = claim
    return result


def validate_analyst_evidence_bindings_v2(
    packet: dict[str, Any],
    metadata: dict[str, Any],
    response: dict[str, Any],
    *,
    source_texts: dict[str, Any],
    analyst_response: dict[str, Any],
) -> dict[str, Any]:
    """Validate an analyst evidence-binding sidecar against normalized metadata.

    This is a parallel v2 sidecar, not a replacement for ``validate_analyst``.
    It requires separately validated packet and analyst inputs, binds every
    sidecar claim to the original analyst claim, and never mutates any input.
    """

    validate_evidence_metadata_v2(packet, metadata, source_texts=source_texts)
    source_text_map = _source_text_map_v2(packet, source_texts)
    response = _require_closed_keys(
        response,
        required=frozenset(
            {
                "schema_version",
                "packet_id",
                "analyst_response_sha256",
                "claims",
                "canonical_effect",
            }
        ),
        label="analyst_evidence_bindings_v2",
    )
    if response["schema_version"] != ANALYST_EVIDENCE_BINDINGS_V2_SCHEMA_VERSION:
        raise EvidenceContractV2Error(
            "analyst_evidence_bindings_v2: schema version mismatch"
        )
    if response["packet_id"] != packet.get("packet_id"):
        raise EvidenceContractV2Error("analyst_evidence_bindings_v2: packet_id mismatch")
    analyst_claims = _analyst_claim_map(
        analyst_response,
        packet_id=_require_text(packet.get("packet_id"), label="packet.packet_id"),
    )
    _require_sha256(
        response["analyst_response_sha256"],
        label="analyst_evidence_bindings_v2.analyst_response_sha256",
    )
    if response["analyst_response_sha256"] != _canonical_sha256(analyst_response):
        raise EvidenceContractV2Error(
            "analyst_evidence_bindings_v2: analyst response hash mismatch"
        )
    if response["canonical_effect"] is not False:
        raise EvidenceContractV2Error(
            "analyst_evidence_bindings_v2: canonical_effect must remain false"
        )
    claims = response["claims"]
    if not isinstance(claims, list) or not claims:
        raise EvidenceContractV2Error("analyst_evidence_bindings_v2.claims: expected non-empty array")
    source_map = {row["source_id"]: row for row in metadata["sources"]}
    calculation_map = {row["calculation_id"]: row for row in metadata["calculations"]}
    claim_ids: set[str] = set()
    for index, value in enumerate(claims):
        label = f"analyst_evidence_bindings_v2.claims[{index}]"
        claim = _require_closed_keys(value, required=_CLAIM_REQUIRED_FIELDS, label=label)
        claim_id = _require_text(claim["claim_id"], label=f"{label}.claim_id")
        if claim_id in claim_ids:
            raise EvidenceContractV2Error("analyst_evidence_bindings_v2: claim_ids must be unique")
        claim_ids.add(claim_id)
        analyst_claim = analyst_claims.get(claim_id)
        if analyst_claim is None:
            raise EvidenceContractV2Error(f"{label}: unknown analyst claim_id")
        _require_sha256(
            claim["analyst_claim_sha256"], label=f"{label}.analyst_claim_sha256"
        )
        if claim["analyst_claim_sha256"] != _canonical_sha256(analyst_claim):
            raise EvidenceContractV2Error(f"{label}: analyst claim hash mismatch")
        ticker = _require_text(claim["ticker"], label=f"{label}.ticker")
        materiality = _require_text(claim["materiality"], label=f"{label}.materiality")
        if (
            ticker != analyst_claim["ticker"]
            or materiality != analyst_claim["materiality"]
        ):
            raise EvidenceContractV2Error(f"{label}: analyst ticker/materiality mismatch")
        if materiality not in _MATERIALITY:
            raise EvidenceContractV2Error(f"{label}.materiality: unsupported value")
        _require_metric_label(claim["metric_label"], label=f"{label}.metric_label")
        _require_unit(claim["unit"], label=f"{label}.unit")
        _period_key(claim["period"], label=f"{label}.period")
        characteristics = _require_identifier_list(
            claim["claim_characteristics"],
            label=f"{label}.claim_characteristics",
            allow_empty=False,
        )
        unknown_characteristics = sorted(set(characteristics) - _CLAIM_CHARACTERISTICS)
        if unknown_characteristics:
            raise EvidenceContractV2Error(
                f"{label}.claim_characteristics: unsupported values "
                + ",".join(unknown_characteristics)
            )
        bindings = _bindings_by_source(claim, source_map, label=label)
        binding_source_ids = [binding["source_id"] for binding in claim["citation_bindings"]]
        binding_hashes = [
            binding["cited_excerpt_sha256"] for binding in claim["citation_bindings"]
        ]
        if (
            binding_source_ids != analyst_claim["source_ids"]
            or binding_hashes != analyst_claim["cited_excerpt_sha256"]
            or claim["calculation_ids"] != analyst_claim["calculation_ids"]
        ):
            raise EvidenceContractV2Error(
                f"{label}: source/hash/calculation bindings must exactly match analyst claim"
            )
        for source_id in bindings:
            if source_map[source_id]["ticker"] != ticker:
                raise EvidenceContractV2Error(f"{label}: cross-ticker citation binding")
        _validate_lexical_scope_flags(
            claim,
            analyst_claim=analyst_claim,
            characteristics=characteristics,
            bindings=bindings,
            source_text_map=source_text_map,
            label=label,
        )
        claim_sources = _source_ids_for_role(bindings, "claim")
        if not claim_sources:
            raise EvidenceContractV2Error(f"{label}: at least one claim-role source is required")
        _assert_sources_match_claim_measure(
            claim_sources, source_map, claim, label=label
        )
        _validate_evidence_field(
            claim["evidence_period"],
            field="evidence_period",
            expected_value=claim["period"],
            bindings=bindings,
            source_map=source_map,
            label=label,
        )
        _validate_evidence_field(
            claim["evidence_unit"],
            field="evidence_unit",
            expected_value=claim["unit"],
            bindings=bindings,
            source_map=source_map,
            label=label,
        )
        if "comparative" in characteristics:
            if claim["comparison_baseline"] is None:
                raise EvidenceContractV2Error(
                    f"{label}.comparison_baseline: comparative claim requires a baseline"
                )
            _validate_comparison_baseline(
                claim["comparison_baseline"],
                claim=claim,
                bindings=bindings,
                source_map=source_map,
                label=label,
            )
        elif claim["comparison_baseline"] is not None:
            raise EvidenceContractV2Error(
                f"{label}.comparison_baseline: non-comparative claim must use null"
            )
        for characteristic, role in (
            ("entity_scope", "entity_scope"),
            ("transaction_terms", "transaction_terms"),
        ):
            if characteristic in characteristics and not _source_ids_for_role(bindings, role):
                raise EvidenceContractV2Error(
                    f"{label}: {characteristic} claim requires a {role} citation role"
                )
        _validate_claim_calculations(
            claim, calculation_map, label=label
        )
    if set(claim_ids) != set(analyst_claims):
        raise EvidenceContractV2Error(
            "analyst_evidence_bindings_v2: must exactly cover analyst claim_ids"
        )
    return response


def _claim_universe(
    analyst_bindings: dict[str, Any],
    *,
    packet_id: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(analyst_bindings, dict):
        raise EvidenceContractV2Error("analyst_bindings: expected object")
    if analyst_bindings.get("schema_version") != ANALYST_EVIDENCE_BINDINGS_V2_SCHEMA_VERSION:
        raise EvidenceContractV2Error("analyst_bindings: schema version mismatch")
    if analyst_bindings.get("packet_id") != packet_id:
        raise EvidenceContractV2Error("analyst_bindings: packet_id mismatch")
    if analyst_bindings.get("canonical_effect") is not False:
        raise EvidenceContractV2Error("analyst_bindings: canonical_effect must remain false")
    _require_sha256(
        analyst_bindings.get("analyst_response_sha256"),
        label="analyst_bindings.analyst_response_sha256",
    )
    claims = analyst_bindings.get("claims")
    if not isinstance(claims, list) or not claims:
        raise EvidenceContractV2Error("analyst_bindings.claims: expected non-empty array")
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(claims):
        claim = _require_closed_keys(
            value,
            required=_CLAIM_REQUIRED_FIELDS,
            label=f"analyst_bindings.claims[{index}]",
        )
        claim_id = _require_text(claim["claim_id"], label=f"analyst_bindings.claims[{index}].claim_id")
        _require_text(claim["ticker"], label=f"analyst_bindings.claims[{index}].ticker")
        if claim_id in result:
            raise EvidenceContractV2Error("analyst_bindings: claim_ids must be unique")
        result[claim_id] = claim
    return result


def _committee_response_decision_map(
    committee_response: dict[str, Any],
    *,
    packet_id: str,
) -> dict[str, dict[str, Any]]:
    """Read only the decision fields needed to bind a v2 summary sidecar.

    This deliberately does not validate a full committee schema. A future
    runtime must validate that separately before it can treat the handoff as
    upstream-valid. The narrow map only makes a replacement or omission of a
    full committee decision detectable by the v2 sidecar.
    """

    committee_response = _require_object(committee_response, label="committee_response")
    if committee_response.get("packet_id") != packet_id:
        raise EvidenceContractV2Error("committee_response: packet_id mismatch")
    decisions = committee_response.get("ticker_decisions")
    if not isinstance(decisions, list) or not decisions:
        raise EvidenceContractV2Error(
            "committee_response.ticker_decisions: expected non-empty array"
        )
    result: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(decisions):
        row = _require_object(
            value, label=f"committee_response.ticker_decisions[{index}]"
        )
        ticker = _require_text(
            row.get("ticker"),
            label=f"committee_response.ticker_decisions[{index}].ticker",
        )
        _require_identifier_list(
            row.get("claim_ids"),
            label=f"committee_response.ticker_decisions[{index}].claim_ids",
            allow_empty=True,
        )
        if ticker in result:
            raise EvidenceContractV2Error(
                "committee_response.ticker_decisions: tickers must be unique"
            )
        result[ticker] = row
    return result


def _committee_claims_by_ticker(
    committee_ticker_decisions: dict[str, Any],
    *,
    committee_response: dict[str, Any],
    claim_map: dict[str, dict[str, Any]],
    packet_id: str,
) -> dict[str, list[str]]:
    committee_ticker_decisions = _require_closed_keys(
        committee_ticker_decisions,
        required=frozenset(
            {
                "schema_version",
                "packet_id",
                "committee_response_sha256",
                "decisions",
                "canonical_effect",
            }
        ),
        label="committee_ticker_decisions_v2",
    )
    if (
        committee_ticker_decisions["schema_version"]
        != COMMITTEE_TICKER_DECISIONS_V2_SCHEMA_VERSION
    ):
        raise EvidenceContractV2Error(
            "committee_ticker_decisions_v2: schema version mismatch"
        )
    if committee_ticker_decisions["packet_id"] != packet_id:
        raise EvidenceContractV2Error(
            "committee_ticker_decisions_v2: packet_id mismatch"
        )
    _require_sha256(
        committee_ticker_decisions["committee_response_sha256"],
        label="committee_ticker_decisions_v2.committee_response_sha256",
    )
    if (
        committee_ticker_decisions["committee_response_sha256"]
        != _canonical_sha256(committee_response)
    ):
        raise EvidenceContractV2Error(
            "committee_ticker_decisions_v2: committee response hash mismatch"
        )
    if committee_ticker_decisions["canonical_effect"] is not False:
        raise EvidenceContractV2Error(
            "committee_ticker_decisions_v2: canonical_effect must remain false"
        )
    response_decisions = _committee_response_decision_map(
        committee_response, packet_id=packet_id
    )
    decisions = committee_ticker_decisions["decisions"]
    if not isinstance(decisions, list) or not decisions:
        raise EvidenceContractV2Error(
            "committee_ticker_decisions_v2.decisions: expected non-empty array"
        )
    result: dict[str, list[str]] = {}
    for index, value in enumerate(decisions):
        label = f"committee_ticker_decisions_v2.decisions[{index}]"
        row = _require_closed_keys(
            value,
            required=_COMMITTEE_DECISION_BINDING_REQUIRED_FIELDS,
            label=label,
        )
        ticker = _require_text(row["ticker"], label=f"{label}.ticker")
        claim_ids = _require_identifier_list(
            row["claim_ids"], label=f"{label}.claim_ids", allow_empty=False
        )
        _require_sha256(
            row["committee_decision_sha256"],
            label=f"{label}.committee_decision_sha256",
        )
        response_decision = response_decisions.get(ticker)
        if response_decision is None:
            raise EvidenceContractV2Error(f"{label}: unknown committee ticker")
        if row["committee_decision_sha256"] != _canonical_sha256(response_decision):
            raise EvidenceContractV2Error(f"{label}: committee decision hash mismatch")
        if claim_ids != response_decision["claim_ids"]:
            raise EvidenceContractV2Error(
                f"{label}: claim_ids must exactly match committee decision"
            )
        if ticker in result:
            raise EvidenceContractV2Error(
                "committee_ticker_decisions_v2: tickers must be unique"
            )
        for claim_id in claim_ids:
            claim = claim_map.get(claim_id)
            if claim is None:
                raise EvidenceContractV2Error(f"{label}: unknown claim_id")
            if claim["ticker"] != ticker:
                raise EvidenceContractV2Error(f"{label}: cross-ticker claim_id")
        result[ticker] = claim_ids
    if set(result) != set(response_decisions):
        raise EvidenceContractV2Error(
            "committee_ticker_decisions_v2: must exactly cover committee tickers"
        )
    covered_claim_ids = {
        claim_id for claim_ids in result.values() for claim_id in claim_ids
    }
    if covered_claim_ids != set(claim_map):
        raise EvidenceContractV2Error(
            "committee_ticker_decisions_v2: must exactly cover analyst claim_ids"
        )
    return result


def validate_critic_coverage_v2(
    *,
    packet: dict[str, Any],
    metadata: dict[str, Any],
    source_texts: dict[str, Any],
    analyst_response: dict[str, Any],
    analyst_bindings: dict[str, Any],
    committee_response: dict[str, Any],
    committee_ticker_decisions: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    """Validate full critic claim coverage and issue-to-evidence linkage.

    The analyst bindings are revalidated on every call against the packet,
    metadata, and source analyst response. The committee summary is likewise
    bound to the full committee response and each original ticker decision.
    This prevents critic coverage from accepting fabricated or only partially
    checked analyst or committee sidecars. The validator does not create a
    promotion, recommendation, or execution decision. Lexically flagged scope
    risks must receive matching typed critic issues; structural binding alone
    cannot clear them for approval.
    """

    packet = _require_object(packet, label="packet")
    packet_id = _require_text(packet.get("packet_id"), label="packet.packet_id")
    validate_analyst_evidence_bindings_v2(
        packet,
        metadata,
        analyst_bindings,
        source_texts=source_texts,
        analyst_response=analyst_response,
    )
    claim_map = _claim_universe(analyst_bindings, packet_id=packet_id)
    lexical_issue_types_by_claim = {
        claim_id: {
            _LEXICAL_FLAG_ISSUE_TYPES[flag]
            for flag in claim["lexical_scope_flags"]
            if flag in _LEXICAL_FLAG_ISSUE_TYPES
        }
        for claim_id, claim in claim_map.items()
    }
    committee_by_ticker = _committee_claims_by_ticker(
        committee_ticker_decisions,
        committee_response=committee_response,
        claim_map=claim_map,
        packet_id=packet_id,
    )
    response = _require_closed_keys(
        response,
        required=frozenset({"schema_version", "packet_id", "ticker_reviews", "canonical_effect"}),
        label="critic_coverage_v2",
    )
    if response["schema_version"] != CRITIC_COVERAGE_V2_SCHEMA_VERSION:
        raise EvidenceContractV2Error("critic_coverage_v2: schema version mismatch")
    if response["packet_id"] != packet_id:
        raise EvidenceContractV2Error("critic_coverage_v2: packet_id mismatch")
    if response["canonical_effect"] is not False:
        raise EvidenceContractV2Error("critic_coverage_v2: canonical_effect must remain false")
    reviews = response["ticker_reviews"]
    if not isinstance(reviews, list) or not reviews:
        raise EvidenceContractV2Error("critic_coverage_v2.ticker_reviews: expected non-empty array")
    review_by_ticker: dict[str, dict[str, Any]] = {}
    issue_ids: set[str] = set()
    for index, value in enumerate(reviews):
        label = f"critic_coverage_v2.ticker_reviews[{index}]"
        review = _require_closed_keys(
            value,
            required=frozenset(
                {
                    "ticker",
                    "verdict",
                    "reviewed_claim_ids",
                    *_CRITIC_PASS_FIELDS,
                    "issues",
                }
            ),
            label=label,
        )
        ticker = _require_text(review["ticker"], label=f"{label}.ticker")
        if ticker in review_by_ticker:
            raise EvidenceContractV2Error("critic_coverage_v2.ticker_reviews: tickers must be unique")
        expected_claim_ids = committee_by_ticker.get(ticker)
        if expected_claim_ids is None:
            raise EvidenceContractV2Error(f"{label}: ticker has no committee decision")
        reviewed_claim_ids = _require_identifier_list(
            review["reviewed_claim_ids"],
            label=f"{label}.reviewed_claim_ids",
            allow_empty=False,
        )
        if reviewed_claim_ids != expected_claim_ids:
            raise EvidenceContractV2Error(
                f"{label}.reviewed_claim_ids: must exactly match committee claim_ids"
            )
        verdict = _require_text(review["verdict"], label=f"{label}.verdict")
        if verdict not in _VERDICTS:
            raise EvidenceContractV2Error(f"{label}.verdict: unsupported value")
        for field in _CRITIC_PASS_FIELDS:
            if not isinstance(review[field], bool):
                raise EvidenceContractV2Error(f"{label}.{field}: expected boolean")
        issues = review["issues"]
        if not isinstance(issues, list):
            raise EvidenceContractV2Error(f"{label}.issues: expected array")
        issue_types_by_dimension: dict[str, int] = {}
        issue_types_by_claim: dict[str, set[str]] = {
            claim_id: set() for claim_id in reviewed_claim_ids
        }
        material_issue_count = 0
        for issue_index, value in enumerate(issues):
            issue_label = f"{label}.issues[{issue_index}]"
            issue = _require_closed_keys(
                value,
                required=frozenset(
                    {
                        "issue_id",
                        "issue_type",
                        "severity",
                        "material",
                        "issue",
                        "affected_claim_ids",
                        "source_ids",
                    }
                ),
                label=issue_label,
            )
            issue_id = _require_text(issue["issue_id"], label=f"{issue_label}.issue_id")
            if issue_id in issue_ids:
                raise EvidenceContractV2Error("critic_coverage_v2: issue_ids must be unique")
            issue_ids.add(issue_id)
            issue_type = _require_text(issue["issue_type"], label=f"{issue_label}.issue_type")
            if issue_type not in _ISSUE_TYPES:
                raise EvidenceContractV2Error(f"{issue_label}.issue_type: unsupported value")
            severity = _require_text(issue["severity"], label=f"{issue_label}.severity")
            if severity not in _ISSUE_SEVERITIES:
                raise EvidenceContractV2Error(f"{issue_label}.severity: unsupported value")
            if not isinstance(issue["material"], bool):
                raise EvidenceContractV2Error(f"{issue_label}.material: expected boolean")
            if severity in {"high", "critical"} and issue["material"] is not True:
                raise EvidenceContractV2Error(
                    f"{issue_label}.material: high/critical issue must be material"
                )
            _require_text(issue["issue"], label=f"{issue_label}.issue")
            affected_claim_ids = _require_identifier_list(
                issue["affected_claim_ids"],
                label=f"{issue_label}.affected_claim_ids",
                allow_empty=False,
            )
            for claim_id in affected_claim_ids:
                if claim_id not in claim_map:
                    raise EvidenceContractV2Error(f"{issue_label}: unknown affected claim_id")
                if claim_id not in reviewed_claim_ids:
                    raise EvidenceContractV2Error(
                        f"{issue_label}: affected claim_id is outside reviewed coverage"
                    )
                if claim_map[claim_id]["ticker"] != ticker:
                    raise EvidenceContractV2Error(
                        f"{issue_label}: cross-ticker affected claim_id"
                    )
                issue_types_by_claim[claim_id].add(issue_type)
            source_ids = _require_identifier_list(
                issue["source_ids"], label=f"{issue_label}.source_ids", allow_empty=True
            )
            allowed_sources = {
                binding["source_id"]
                for claim_id in affected_claim_ids
                for binding in claim_map[claim_id]["citation_bindings"]
            }
            if not set(source_ids).issubset(allowed_sources):
                raise EvidenceContractV2Error(
                    f"{issue_label}: source_ids must belong to affected claims"
                )
            if issue_type in {
                "citation_scope",
                "period_binding",
                "unit_binding",
                "comparison_baseline",
                "entity_scope",
                "transaction_terms",
                "numeric_reconciliation",
                "factual_grounding",
            } and not source_ids:
                raise EvidenceContractV2Error(
                    f"{issue_label}: issue_type requires source_ids"
                )
            if source_ids:
                for claim_id in affected_claim_ids:
                    claim_source_ids = {
                        binding["source_id"]
                        for binding in claim_map[claim_id]["citation_bindings"]
                    }
                    if not claim_source_ids.intersection(source_ids):
                        raise EvidenceContractV2Error(
                            f"{issue_label}: source_ids must include a cited source "
                            "for every affected claim"
                        )
            required_roles = _ISSUE_REQUIRED_SUPPORT_ROLES.get(issue_type, frozenset())
            if required_roles:
                for claim_id in affected_claim_ids:
                    claim_has_required_role = any(
                        binding["source_id"] in source_ids
                        and required_roles.issubset(set(binding["support_roles"]))
                        for binding in claim_map[claim_id]["citation_bindings"]
                    )
                    if not claim_has_required_role:
                        raise EvidenceContractV2Error(
                            f"{issue_label}: source_ids lack required support role "
                            "for every affected claim"
                        )
            dimension = _ISSUE_DIMENSIONS.get(issue_type)
            if dimension is not None:
                if review[dimension] is not False:
                    raise EvidenceContractV2Error(
                        f"{issue_label}: issue_type requires {dimension} false"
                    )
                issue_types_by_dimension[dimension] = (
                    issue_types_by_dimension.get(dimension, 0) + 1
                )
            if issue["material"]:
                material_issue_count += 1
        for field in _CRITIC_PASS_FIELDS:
            if review[field] is False and issue_types_by_dimension.get(field, 0) == 0:
                raise EvidenceContractV2Error(
                    f"{label}.{field}: false but no matching typed issue"
                )
        for claim_id in reviewed_claim_ids:
            missing_lexical_issue_types = sorted(
                lexical_issue_types_by_claim[claim_id]
                - issue_types_by_claim[claim_id]
            )
            if missing_lexical_issue_types:
                raise EvidenceContractV2Error(
                    f"{label}: lexical scope flags require typed issue(s) for "
                    f"{claim_id}: {','.join(missing_lexical_issue_types)}"
                )
        if verdict == "approve" and (
            material_issue_count or any(review[field] is False for field in _CRITIC_PASS_FIELDS)
        ):
            raise EvidenceContractV2Error(
                f"{label}: approve verdict requires all pass dimensions and no material issues"
            )
        if verdict in {"revise", "reject"} and not material_issue_count:
            raise EvidenceContractV2Error(
                f"{label}: {verdict} verdict requires a material issue"
            )
        review_by_ticker[ticker] = review
    if set(review_by_ticker) != set(committee_by_ticker):
        raise EvidenceContractV2Error(
            "critic_coverage_v2.ticker_reviews: must exactly cover committee tickers"
        )
    return response


def evaluate_critic_incremental_value_v2(
    *,
    valid_claim_ids: list[str],
    committee_material_issue_claim_ids: list[str],
    critic_material_issue_claim_ids: list[str],
    reference_material_issue_claim_ids: list[str] | None,
) -> dict[str, Any]:
    """Describe caller-supplied issue-set overlap without claiming critic value.

    These lists are not cryptographically or procedurally bound to an
    independent review artifact. They may show observed overlap, but cannot
    establish critic incremental value, reviewer independence, error rates, or
    promotion readiness. A separately authorized future evaluation contract
    would need to bind the actual source artifacts and their provenance.
    """

    valid_ids = set(
        _require_identifier_list(
            valid_claim_ids, label="valid_claim_ids", allow_empty=False
        )
    )

    def issue_set(value: Any, *, label: str) -> set[str]:
        identifiers = set(_require_identifier_list(value, label=label, allow_empty=True))
        unknown = sorted(identifiers - valid_ids)
        if unknown:
            raise EvidenceContractV2Error(f"{label}: unknown claim_ids {','.join(unknown)}")
        return identifiers

    committee_ids = issue_set(
        committee_material_issue_claim_ids,
        label="committee_material_issue_claim_ids",
    )
    critic_ids = issue_set(
        critic_material_issue_claim_ids,
        label="critic_material_issue_claim_ids",
    )
    if reference_material_issue_claim_ids is None:
        return {
            "reference_set_available": False,
            "input_binding_status": "caller_supplied_unverified",
            "identified_material_issue_claim_ids": [],
            "missed_material_issue_claim_ids": [],
            "incremental_material_issue_claim_ids": [],
            "incremental_value_status": "not_established",
            "reference_alignment_status": "not_available",
            "reviewer_independence_status": "not_established",
            "canonical_effect": False,
            "repository_provider_called": False,
            "network_called": False,
        }
    reference_ids = issue_set(
        reference_material_issue_claim_ids,
        label="reference_material_issue_claim_ids",
    )
    identified = critic_ids & reference_ids
    missed = reference_ids - critic_ids
    incremental = identified - committee_ids
    return {
        "reference_set_available": True,
        "input_binding_status": "caller_supplied_unverified",
        "identified_material_issue_claim_ids": sorted(identified),
        "missed_material_issue_claim_ids": sorted(missed),
        "incremental_material_issue_claim_ids": sorted(incremental),
        "incremental_value_status": "not_established",
        "reference_alignment_status": "observed_against_unverified_reference",
        "reviewer_independence_status": "not_established",
        "canonical_effect": False,
        "repository_provider_called": False,
        "network_called": False,
    }
