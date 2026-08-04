"""Repository-provider-free, noncanonical quality guards for future Phase 5R work.

These helpers do not decide whether a claim is true and never authorize a
research classification, promotion, trading action, or model call.  They turn
known evidence-scope risk patterns into explicit manual-review flags and can
describe critic overlap against a caller-supplied reference set without
establishing that set's independence.
"""

from __future__ import annotations

import re
from typing import Any


QUALITY_GUARD_SCHEMA_VERSION = "phase5r_internal_quality_guard_v1"

_COMPARATIVE_PATTERN = re.compile(
    r"\b(?:improved|increased|decreased|declined|higher|lower|grew|fell)\b",
    re.IGNORECASE,
)
_PERIOD_SIGNAL_PATTERN = re.compile(
    r"\b(?:fiscal\s+year|year|quarter|months?\s+ended|as\s+of)\b|\b20\d{2}\b",
    re.IGNORECASE,
)
_SCOPE_PATTERN = re.compile(
    r"\b(?:largest|smallest|only|overall\s+dependence|customer\s+dependence|"
    r"concentration)\b",
    re.IGNORECASE,
)
_INCORPORATED_MATERIAL_PATTERN = re.compile(
    r"\b(?:attached|attachment|incorporated\s+by\s+reference|press\s+release)\b",
    re.IGNORECASE,
)
_TRANSACTION_TERMS_PATTERN = re.compile(
    r"\b(?:pricing\s+terms?|transaction\s+terms?|specific\s+terms?)\b",
    re.IGNORECASE,
)


class InternalQualityGuardError(ValueError):
    """A proposed noncanonical quality-check input is malformed."""


def _required_text(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InternalQualityGuardError(f"{label} must be a non-empty string")
    return " ".join(value.split())


def _source_texts(cited_excerpts: Any) -> list[str]:
    if not isinstance(cited_excerpts, list) or not cited_excerpts:
        raise InternalQualityGuardError("cited_excerpts must be a non-empty list")
    seen: set[str] = set()
    texts: list[str] = []
    for index, row in enumerate(cited_excerpts):
        if not isinstance(row, dict):
            raise InternalQualityGuardError(
                f"cited_excerpts[{index}] must be an object"
            )
        source_id = _required_text(
            row.get("source_id"), label=f"cited_excerpts[{index}].source_id"
        )
        if source_id in seen:
            raise InternalQualityGuardError("cited_excerpts source_ids must be unique")
        seen.add(source_id)
        texts.append(
            _required_text(
                row.get("excerpt_text"),
                label=f"cited_excerpts[{index}].excerpt_text",
            )
        )
    return texts


def _flag(code: str, reason: str) -> dict[str, str]:
    return {"code": code, "severity": "manual_review", "reason": reason}


def lint_claim_evidence_scope(
    *,
    claim: Any,
    period: Any,
    unit: Any,
    cited_excerpts: Any,
) -> dict[str, Any]:
    """Return deterministic manual-review flags for a single cited claim.

    Lexical flags are deliberately conservative.  A flag means that a human or
    separately authorized internal process must inspect the cited excerpt; it
    is not a finding that the claim is false or that a source is inaccurate.
    """

    normalized_claim = _required_text(claim, label="claim")
    normalized_period = _required_text(period, label="period")
    normalized_unit = _required_text(unit, label="unit")
    excerpts = _source_texts(cited_excerpts)
    joined_excerpts = " ".join(excerpts)
    flags: list[dict[str, str]] = []

    if _COMPARATIVE_PATTERN.search(normalized_claim):
        flags.append(
            _flag(
                "comparative_direction_requires_baseline_check",
                "A directional comparison needs an explicit baseline, period, and unit check against the cited excerpt.",
            )
        )
        if not _PERIOD_SIGNAL_PATTERN.search(joined_excerpts):
            flags.append(
                _flag(
                    "period_binding_not_visible_in_excerpt",
                    "The cited excerpt has no obvious period signal for a comparative claim; verify the period directly or cite a period-specific reconciliation.",
                )
            )

    if _SCOPE_PATTERN.search(normalized_claim):
        flags.append(
            _flag(
                "scope_or_superlative_requires_explicit_support",
                "A superlative, concentration, or aggregate-dependence term requires direct support in the cited excerpt.",
            )
        )

    if (
        _TRANSACTION_TERMS_PATTERN.search(normalized_claim)
        and _INCORPORATED_MATERIAL_PATTERN.search(joined_excerpts)
    ):
        flags.append(
            _flag(
                "incorporated_material_scope_check",
                "The excerpt refers to attached or incorporated material; verify that the claimed detail appears in the excerpt itself rather than only in the referenced material.",
            )
        )

    return {
        "schema_version": QUALITY_GUARD_SCHEMA_VERSION,
        "claim": normalized_claim,
        "period": normalized_period,
        "unit": normalized_unit,
        "manual_review_required": bool(flags),
        "flags": flags,
        "canonical_effect": False,
        "repository_provider_called": False,
        "network_called": False,
    }


def _unique_identifier_set(value: Any, *, label: str) -> set[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise InternalQualityGuardError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise InternalQualityGuardError(f"{label} must not contain duplicates")
    return set(value)


def evaluate_critic_incremental_value(
    *,
    reference_material_issue_claim_ids: list[str] | None,
    committee_issue_claim_ids: list[str],
    critic_issue_claim_ids: list[str],
) -> dict[str, Any]:
    """Describe unverified issue-set overlap without claiming critic value.

    A supplied identifier list does not establish an independent reviewer or
    bind to a reference artifact, so incremental value remains
    ``not_established`` even when overlap is observed.
    """

    committee_ids = _unique_identifier_set(
        committee_issue_claim_ids, label="committee_issue_claim_ids"
    )
    critic_ids = _unique_identifier_set(
        critic_issue_claim_ids, label="critic_issue_claim_ids"
    )
    if reference_material_issue_claim_ids is None:
        return {
            "schema_version": QUALITY_GUARD_SCHEMA_VERSION,
            "reference_set_available": False,
            "input_binding_status": "caller_supplied_unverified",
            "identified_material_issue_claim_ids": [],
            "missed_material_issue_claim_ids": [],
            "incremental_material_issue_claim_ids": [],
            "incremental_value_status": "not_established",
            "reference_alignment_status": "not_available",
            "reviewer_independence_status": "not_established",
            "canonical_effect": False,
        }

    reference_ids = _unique_identifier_set(
        reference_material_issue_claim_ids,
        label="reference_material_issue_claim_ids",
    )
    identified = critic_ids & reference_ids
    missed = reference_ids - critic_ids
    incremental = identified - committee_ids
    return {
        "schema_version": QUALITY_GUARD_SCHEMA_VERSION,
        "reference_set_available": True,
        "input_binding_status": "caller_supplied_unverified",
        "identified_material_issue_claim_ids": sorted(identified),
        "missed_material_issue_claim_ids": sorted(missed),
        "incremental_material_issue_claim_ids": sorted(incremental),
        "incremental_value_status": "not_established",
        "reference_alignment_status": "observed_against_unverified_reference",
        "reviewer_independence_status": "not_established",
        "canonical_effect": False,
    }


FUTURE_ANALYST_SCOPE_ADDENDUM = """
For every comparative, superlative, aggregate-dependence, or transaction-term
claim, use only wording directly established by the cited excerpt. State the
comparison baseline, period, and unit. Do not promote an attachment or
incorporated reference into a claim that its specific contents are visible.
When the excerpt does not establish the scope, qualify the claim or abstain.
""".strip()


FUTURE_CRITIC_SCOPE_ADDENDUM = """
Before approving a claim, explicitly test: (1) comparison direction against
the identified baseline, period, and unit; (2) whether terms such as largest,
overall dependence, concentration, or specific transaction terms are directly
shown; and (3) whether the cited excerpt itself, rather than only an
attached or incorporated document, contains the claimed detail. Record a
cited issue or mark support/citation accuracy partial when any check is not
established.
""".strip()
