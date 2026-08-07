#!/usr/bin/env python3
"""Verify bounded v10 AI-review governance artifacts without unblinding.

This verifier uses only the Python standard library.  It never constructs a
provider, reads credentials, opens the blind key, or makes a network request.
It validates artifact bindings and explicitly reports that self-attested
non-access assertions cannot independently prove historical non-access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
QUARANTINE_ROOT = ROOT / "08_reviews/phase5r_model_pilot/quarantine/v10"
ANONYMOUS_REVIEW_PATH = QUARANTINE_ROOT / "phase5r_model_pilot_anonymous_review.json"
AI_REVIEW_PATH = (
    ROOT
    / "08_reviews/phase5r_model_pilot/ai_assisted_v10_review"
    / "phase5r_model_pilot_v10_ai_assisted_review.json"
)
AMENDMENT_DRAFT_PATH = (
    ROOT / "01_policies/phase5r_v10_ai_assisted_review_limited_governance_amendment_draft.md"
)
BLIND_KEY_BOUNDARY_INCIDENT_PATH = (
    ROOT
    / "08_reviews/phase5r_model_pilot/ai_assisted_v10_review"
    / "phase5r_v10_blind_key_boundary_incident.json"
)
PROJECT_OWNER_INTERNAL_USE_DECISION_PATH = (
    ROOT / "00_project_control/phase5r_v10_project_owner_internal_use_decision.json"
)

# These values pin the exact two v10 artifacts covered by the limited draft.
# They are deliberately constants rather than values read from an adoption
# record, so replacing both an artifact and an adoption record cannot pass.
EXPECTED_ANONYMOUS_REVIEW_RAW_SHA256 = (
    "011192c2ddb7a9db07e0b588499c16d9330b98da2caf82a855cc70aadc894a77"
)
EXPECTED_AI_REVIEW_RAW_SHA256 = (
    "5282ea924a564e2a2fda7a2f49f5c63643f5aa706b2f95ad023ddad678de3775"
)
EXPECTED_AI_REVIEW_LEGACY_CANONICAL_SHA256 = (
    "b8ec4c1cf2bf84525b139a99d7fd49fd2b02fbe842734bbe53b9e47bf7d97625"
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_json_sha256(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _regular_file(path: Path, *, label: str, issues: list[str]) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        issues.append(f"{label}_missing")
        return False
    if path.is_symlink() or not path.is_file() or metadata.st_size == 0:
        issues.append(f"{label}_not_regular_file")
        return False
    return True


def _utf8_without_bom_with_lf(
    path: Path, *, label: str, issues: list[str]
) -> bool:
    """Validate the text-file encoding rule without normalizing any bytes."""

    try:
        raw = path.read_bytes()
        raw.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        issues.append(f"{label}_not_utf8")
        return False
    if raw.startswith(b"\xef\xbb\xbf"):
        issues.append(f"{label}_has_utf8_bom")
        return False
    if b"\r" in raw:
        issues.append(f"{label}_has_non_lf_line_endings")
        return False
    return True


def _load_object(path: Path, *, label: str, issues: list[str]) -> dict[str, Any] | None:
    if not _regular_file(path, label=label, issues=issues):
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        issues.append(f"{label}_invalid_json")
        return None
    if not isinstance(value, dict):
        issues.append(f"{label}_not_object")
        return None
    return value


def _same_strings(left: Any, right: Any) -> bool:
    if not isinstance(left, list) or not isinstance(right, list):
        return False
    if not all(isinstance(value, str) and value for value in left + right):
        return False
    return set(left) == set(right) and len(left) == len(set(left))


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(_nonempty_string(item) for item in value)


def _valid_effective_at_et(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        return False
    return parsed.utcoffset() in {timedelta(hours=-4), timedelta(hours=-5)}


def _valid_internal_use_decision(record: dict[str, Any]) -> bool:
    required = {
        "schema_version",
        "status",
        "recorded_at_et",
        "decision_source",
        "project_owner_name",
        "formal_amendment_adopted",
        "incident_classification",
        "retained_ai_review_as_noncanonical_internal_quality_evidence",
        "human_review_requirement_waived",
        "human_review_protocol_completed",
        "independent_human_validation_claim_permitted",
        "original_protocol_status",
        "technical_collection_status",
        "allowed_internal_uses",
        "prohibited_authorities",
        "notes",
    }
    expected_uses = [
        "prompt improvement",
        "evidence handling improvement",
        "citation-check improvement",
        "critic-logic improvement",
        "confidence-calibration improvement",
        "research-presentation improvement",
    ]
    expected_prohibitions = {
        "unblind_or_infer_runtime_assignment",
        "claim_independent_human_validation",
        "canonical_buy_sell_decision",
        "trading_authority",
        "broker_or_account_access",
        "order_execution",
        "automatic_portfolio_change",
        "promotion_or_activation_authority",
    }
    name = record.get("project_owner_name")
    prohibitions = record.get("prohibited_authorities")
    return (
        set(record) == required
        and record.get("schema_version")
        == "phase5r_v10_project_owner_internal_use_decision_v1"
        and record.get("status")
        == "recorded_limited_project_owner_direction_not_formal_adoption"
        and _valid_effective_at_et(record.get("recorded_at_et"))
        and _nonempty_string(record.get("decision_source"))
        and (name is None or _nonempty_string(name))
        and record.get("formal_amendment_adopted") is False
        and record.get("incident_classification")
        == "contained_non_substantive_boundary_contact"
        and record.get("retained_ai_review_as_noncanonical_internal_quality_evidence")
        is True
        and record.get("human_review_requirement_waived") is False
        and record.get("human_review_protocol_completed") is False
        and record.get("independent_human_validation_claim_permitted") is False
        and record.get("original_protocol_status")
        == "no_go_pending_independent_review_preserved_historical"
        and record.get("technical_collection_status") == "complete"
        and _same_strings(record.get("allowed_internal_uses"), expected_uses)
        and isinstance(prohibitions, dict)
        and set(prohibitions) == expected_prohibitions
        and all(value is False for value in prohibitions.values())
        and _nonempty_string(record.get("notes"))
    )


def _verify_adoption_record(
    record: dict[str, Any],
    *,
    amendment_raw_sha256: str,
    anonymous_raw_sha256: str,
    review_raw_sha256: str,
    review_canonical_sha256: str,
    issues: list[str],
) -> None:
    required = {
        "schema_version",
        "amendment_version",
        "decision",
        "policy_owner",
        "authority",
        "same_person_proposed_and_approved",
        "effective_at_et",
        "amendment_raw_file_sha256",
        "anonymous_bundle_raw_file_sha256",
        "ai_review_artifact_raw_file_sha256",
        "ai_review_legacy_canonical_sha256",
        "interactive_ai_session",
        "human_review_requirement_waived",
        "human_review_waiver_scope",
        "human_review_protocol_completed",
        "independent_human_validation_claim_permitted",
        "original_protocol_status",
        "canonical_authority_created",
        "blind_key_access_authorized",
        "email_authority_created",
        "scheduler_authority_created",
        "account_authority_created",
        "broker_authority_created",
        "order_or_execution_authority_created",
        "revocation_authority",
        "adoption_rationale",
        "notes",
    }
    if set(record) != required:
        issues.append("adoption_record_schema_invalid")
        return
    if record["schema_version"] != "phase5r_governance_amendment_adoption_v2":
        issues.append("adoption_record_schema_version_invalid")
    if record["amendment_version"] != "v10-ai-review-limited-1":
        issues.append("adoption_record_amendment_version_invalid")
    if record["decision"] != "adopted":
        issues.append("adoption_record_not_adopted")
    if not isinstance(record["policy_owner"], str) or not record["policy_owner"].strip():
        issues.append("adoption_record_policy_owner_missing")
    if record["authority"] != "project owner":
        issues.append("adoption_record_authority_invalid")
    if type(record["same_person_proposed_and_approved"]) is not bool:
        issues.append("adoption_record_separation_flag_invalid")
    if not _valid_effective_at_et(record["effective_at_et"]):
        issues.append("adoption_record_effective_at_et_invalid")
    expected_hashes = {
        "amendment_raw_file_sha256": amendment_raw_sha256,
        "anonymous_bundle_raw_file_sha256": anonymous_raw_sha256,
        "ai_review_artifact_raw_file_sha256": review_raw_sha256,
        "ai_review_legacy_canonical_sha256": review_canonical_sha256,
    }
    for field, expected in expected_hashes.items():
        if record[field] != expected:
            issues.append(f"adoption_record_{field}_mismatch")
    session = record["interactive_ai_session"]
    if (
        not isinstance(session, dict)
        or set(session)
        != {
            "provider",
            "session_surface",
            "model_family",
            "review_date_et",
            "reasoning_configuration",
            "non_independent",
            "external_evidence_authorized",
            "repository_initiated_provider_call_authorized",
        }
        or not all(
            isinstance(session[key], str) and session[key].strip()
            for key in (
                "provider",
                "session_surface",
                "model_family",
                "review_date_et",
                "reasoning_configuration",
            )
        )
        or session.get("non_independent") is not True
        or session.get("external_evidence_authorized") is not False
        or session.get("repository_initiated_provider_call_authorized") is not False
    ):
        issues.append("adoption_record_interactive_session_invalid")
    if record["human_review_requirement_waived"] is not True:
        issues.append("adoption_record_human_review_requirement_waiver_missing")
    if (
        record["human_review_waiver_scope"]
        != "project_owner_internal_noncanonical_use_only"
    ):
        issues.append("adoption_record_human_review_waiver_scope_invalid")
    if record["human_review_protocol_completed"] is not False:
        issues.append("adoption_record_human_review_protocol_must_remain_incomplete")
    if record["independent_human_validation_claim_permitted"] is not False:
        issues.append("adoption_record_independent_human_validation_must_remain_false")
    if (
        record["original_protocol_status"]
        != "no_go_pending_independent_review_preserved_historical"
    ):
        issues.append("adoption_record_original_protocol_status_invalid")
    prohibited_true = (
        "canonical_authority_created",
        "blind_key_access_authorized",
        "email_authority_created",
        "scheduler_authority_created",
        "account_authority_created",
        "broker_authority_created",
        "order_or_execution_authority_created",
    )
    for field in prohibited_true:
        if record[field] is not False:
            issues.append(f"adoption_record_{field}_must_be_false")
    if record["revocation_authority"] != record["policy_owner"]:
        issues.append("adoption_record_revocation_authority_invalid")
    if not isinstance(record["adoption_rationale"], str) or not record["adoption_rationale"].strip():
        issues.append("adoption_record_rationale_missing")
    if not isinstance(record["notes"], str):
        issues.append("adoption_record_notes_invalid")


def verify(
    *,
    anonymous_review_path: Path = ANONYMOUS_REVIEW_PATH,
    ai_review_path: Path = AI_REVIEW_PATH,
    amendment_draft_path: Path = AMENDMENT_DRAFT_PATH,
    adoption_record_path: Path | None = None,
) -> dict[str, Any]:
    """Return a provider-free validation summary; never read the blind key."""

    issues: list[str] = []
    anonymous = _load_object(anonymous_review_path, label="anonymous_review", issues=issues)
    ai_review = _load_object(ai_review_path, label="ai_review", issues=issues)
    draft_valid = _regular_file(amendment_draft_path, label="amendment_draft", issues=issues)
    if draft_valid and not _utf8_without_bom_with_lf(
        amendment_draft_path, label="amendment_draft", issues=issues
    ):
        draft_valid = False
    draft_text = ""
    if draft_valid:
        try:
            draft_text = amendment_draft_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            issues.append("amendment_draft_unreadable")
            draft_valid = False

    boundary_incident_status = "not_recorded"
    if BLIND_KEY_BOUNDARY_INCIDENT_PATH.exists():
        incident = _load_object(
            BLIND_KEY_BOUNDARY_INCIDENT_PATH,
            label="blind_key_boundary_incident",
            issues=issues,
        )
        if incident is None:
            boundary_incident_status = "invalid"
        elif (
            incident.get("schema_version")
            != "phase5r_blind_key_boundary_incident_v1"
            or incident.get("status")
            not in {
                "open_human_disposition_required",
                "contained_non_substantive_boundary_contact",
                "closed",
            }
        ):
            boundary_incident_status = "invalid"
            issues.append("blind_key_boundary_incident_schema_invalid")
        else:
            boundary_incident_status = incident["status"]

    internal_use_authorization_status = "not_recorded"
    if boundary_incident_status == "contained_non_substantive_boundary_contact":
        direction = _load_object(
            PROJECT_OWNER_INTERNAL_USE_DECISION_PATH,
            label="project_owner_internal_use_decision",
            issues=issues,
        )
        if direction is None or not _valid_internal_use_decision(direction):
            issues.append("project_owner_internal_use_decision_invalid")
            internal_use_authorization_status = "invalid"
        else:
            internal_use_authorization_status = "recorded_limited_noncanonical"

    anonymous_raw_sha256 = _sha256_file(anonymous_review_path) if anonymous else None
    ai_review_raw_sha256 = _sha256_file(ai_review_path) if ai_review else None
    amendment_raw_sha256 = _sha256_file(amendment_draft_path) if draft_valid else None
    ai_review_canonical_sha256 = None

    if anonymous_raw_sha256 != EXPECTED_ANONYMOUS_REVIEW_RAW_SHA256:
        issues.append("anonymous_review_raw_file_hash_mismatch")
    if ai_review_raw_sha256 != EXPECTED_AI_REVIEW_RAW_SHA256:
        issues.append("ai_review_raw_file_hash_mismatch")

    if anonymous is not None:
        unsigned = {key: value for key, value in anonymous.items() if key != "review_material_sha256"}
        if anonymous.get("review_material_sha256") != _canonical_json_sha256(unsigned):
            issues.append("anonymous_review_legacy_canonical_hash_invalid")
    if ai_review is not None:
        unsigned_review = {key: value for key, value in ai_review.items() if key != "review_sha256"}
        ai_review_canonical_sha256 = _canonical_json_sha256(unsigned_review)
        if ai_review.get("review_sha256") != ai_review_canonical_sha256:
            issues.append("ai_review_legacy_canonical_hash_invalid")
        if ai_review_canonical_sha256 != EXPECTED_AI_REVIEW_LEGACY_CANONICAL_SHA256:
            issues.append("ai_review_legacy_canonical_hash_mismatch")
        if ai_review.get("review_type") != "ai_assisted_internal_review_not_independent_human_review":
            issues.append("ai_review_type_invalid")
        if ai_review.get("independent_human_review") is not False:
            issues.append("ai_review_independence_flag_invalid")
        if ai_review.get("promotion_or_canonical_authority") is not False:
            issues.append("ai_review_canonical_authority_flag_invalid")
        final_decision = ai_review.get("final_decision")
        if (
            not isinstance(final_decision, dict)
            or set(final_decision)
            != {"decision", "rationale", "recommended_next_action"}
            or final_decision.get("decision") != "no_go"
            or not _nonempty_string(final_decision.get("rationale"))
            or not _nonempty_string(final_decision.get("recommended_next_action"))
        ):
            issues.append("ai_review_final_no_go_invalid")
        freeze = ai_review.get("freeze_protocol")
        if (
            not isinstance(freeze, dict)
            or freeze.get("blind_key_accessed_before_freeze") is not False
            or freeze.get("blind_key_hashed_before_freeze") is not False
            or freeze.get("network_called") is not False
            or freeze.get("model_api_called") is not False
            or freeze.get("model_budget_spent_usd") != "0"
            or freeze.get("immutable_source_artifacts_modified") is not False
        ):
            issues.append("ai_review_freeze_attestation_invalid")

    if anonymous is not None and ai_review is not None:
        source = ai_review.get("source_bundle")
        if (
            not isinstance(source, dict)
            or source.get("path")
            != "08_reviews/phase5r_model_pilot/quarantine/v10/phase5r_model_pilot_anonymous_review.json"
            or source.get("plan_sha256") != anonymous.get("plan_sha256")
            or source.get("review_material_sha256") != anonymous.get("review_material_sha256")
            or source.get("claim_row_count") != len(anonymous.get("rows", []))
            or source.get("critic_row_count") != len(anonymous.get("critic_rows", []))
        ):
            issues.append("ai_review_source_binding_invalid")

        anonymous_rows = anonymous.get("rows")
        claim_reviews = ai_review.get("claim_reviews")
        if not isinstance(anonymous_rows, list) or not isinstance(claim_reviews, list):
            issues.append("ai_review_claim_rows_invalid")
        else:
            source_rows = {row.get("review_id"): row for row in anonymous_rows if isinstance(row, dict)}
            reviewed_ids = [row.get("review_id") for row in claim_reviews if isinstance(row, dict)]
            if (
                len(source_rows) != 48
                or len(claim_reviews) != 48
                or not _same_strings(reviewed_ids, list(source_rows))
            ):
                issues.append("ai_review_claim_row_set_invalid")
            else:
                for row in claim_reviews:
                    if not isinstance(row, dict):
                        issues.append("ai_review_claim_row_invalid")
                        break
                    if set(row) != {
                        "review_id",
                        "semantic_support",
                        "citation_reviews",
                        "period_unit_valid",
                        "unsupported_claim",
                        "notes",
                    }:
                        issues.append("ai_review_claim_row_schema_invalid")
                        break
                    if (
                        not _nonempty_string(row["review_id"])
                        or row["semantic_support"]
                        not in {"supports", "partial", "does_not_support", "not_assessable"}
                        or type(row["period_unit_valid"]) is not bool
                        or type(row["unsupported_claim"]) is not bool
                        or not _nonempty_string(row["notes"])
                    ):
                        issues.append("ai_review_claim_judgment_invalid")
                        break
                    source_row = source_rows[row["review_id"]]
                    cited = row.get("citation_reviews")
                    source_ids = [
                        item.get("source_id")
                        for item in source_row.get("cited_excerpts", [])
                        if isinstance(item, dict)
                    ]
                    if (
                        not isinstance(cited, list)
                        or not all(
                            isinstance(item, dict)
                            and set(item) == {"source_id", "citation_accuracy"}
                            and _nonempty_string(item.get("source_id"))
                            and item.get("citation_accuracy")
                            in {"accurate", "partial", "inaccurate", "uncertain"}
                            for item in cited
                        )
                    ):
                        issues.append("ai_review_citation_judgment_invalid")
                        break
                    reviewed_source_ids = [item["source_id"] for item in cited]
                    if not _same_strings(reviewed_source_ids, source_ids):
                        issues.append("ai_review_citation_scope_invalid")
                        break

        anonymous_critics = anonymous.get("critic_rows")
        critic_reviews = ai_review.get("critic_reviews")
        if not isinstance(anonymous_critics, list) or not isinstance(critic_reviews, list):
            issues.append("ai_review_critic_rows_invalid")
        else:
            source_packets = {
                row.get("packet_id"): row
                for row in anonymous_critics
                if isinstance(row, dict)
            }
            source_packet_ids = list(source_packets)
            reviewed_packet_ids = [row.get("packet_id") for row in critic_reviews if isinstance(row, dict)]
            if (
                len(source_packet_ids) != 5
                or len(critic_reviews) != 5
                or not _same_strings(reviewed_packet_ids, source_packet_ids)
            ):
                issues.append("ai_review_critic_row_set_invalid")
            else:
                for row in critic_reviews:
                    if not isinstance(row, dict):
                        issues.append("ai_review_critic_row_invalid")
                        break
                    if set(row) != {
                        "packet_id",
                        "ticker",
                        "valid_issues_caught",
                        "false_positives",
                        "missed_material_issues",
                        "downgrade_helpfulness",
                        "incremental_value",
                        "notes",
                    }:
                        issues.append("ai_review_critic_row_schema_invalid")
                        break
                    source_packet = source_packets[row["packet_id"]]
                    if (
                        not _nonempty_string(row["packet_id"])
                        or row["ticker"] != source_packet.get("ticker")
                        or not _string_list(row["valid_issues_caught"])
                        or not _string_list(row["false_positives"])
                        or not _string_list(row["missed_material_issues"])
                        or not _nonempty_string(row["downgrade_helpfulness"])
                        or not _nonempty_string(row["incremental_value"])
                        or not _nonempty_string(row["notes"])
                    ):
                        issues.append("ai_review_critic_judgment_invalid")
                        break

    required_draft_phrases = (
        "Adoption-controlled text — not effective unless a separately completed",
        "repository-initiated API or provider",
        "presumed non-independent",
        "anonymous-review protocol remains unchanged",
        "project_owner_internal_noncanonical_use_only",
        "SHA-256 over exact raw\nfile bytes",
        "phase5r_v10_ai_assisted_review_adoption_record_template.json",
    )
    if draft_valid and not all(phrase in draft_text for phrase in required_draft_phrases):
        issues.append("amendment_draft_required_boundary_missing")

    adoption_status = "not_provided"
    if adoption_record_path is not None:
        adoption_status = "provided"
        adoption_text_valid = _regular_file(
            adoption_record_path, label="adoption_record", issues=issues
        ) and _utf8_without_bom_with_lf(
            adoption_record_path, label="adoption_record", issues=issues
        )
        record = (
            _load_object(adoption_record_path, label="adoption_record", issues=issues)
            if adoption_text_valid
            else None
        )
        if (
            record is not None
            and amendment_raw_sha256 is not None
            and anonymous_raw_sha256 is not None
            and ai_review_raw_sha256 is not None
            and ai_review_canonical_sha256 is not None
        ):
            _verify_adoption_record(
                record,
                amendment_raw_sha256=amendment_raw_sha256,
                anonymous_raw_sha256=anonymous_raw_sha256,
                review_raw_sha256=ai_review_raw_sha256,
                review_canonical_sha256=ai_review_canonical_sha256,
                issues=issues,
            )
        if boundary_incident_status not in {
            "not_recorded",
            "contained_non_substantive_boundary_contact",
            "closed",
        } or internal_use_authorization_status == "invalid":
            issues.append("blind_key_boundary_incident_requires_human_disposition")

    return {
        "passed": not issues,
        "issues": sorted(set(issues)),
        "adoption_record_status": adoption_status,
        "anonymous_bundle_raw_file_sha256": anonymous_raw_sha256,
        "ai_review_raw_file_sha256": ai_review_raw_sha256,
        "ai_review_legacy_canonical_sha256": ai_review_canonical_sha256,
        "expected_anonymous_bundle_raw_file_sha256": EXPECTED_ANONYMOUS_REVIEW_RAW_SHA256,
        "expected_ai_review_raw_file_sha256": EXPECTED_AI_REVIEW_RAW_SHA256,
        "expected_ai_review_legacy_canonical_sha256": EXPECTED_AI_REVIEW_LEGACY_CANONICAL_SHA256,
        "amendment_raw_file_sha256": amendment_raw_sha256,
        "blind_key_boundary_incident_status": boundary_incident_status,
        "internal_use_authorization_status": internal_use_authorization_status,
        "verifier_direct_blind_key_file_opened": False,
        "verifier_completion_record_read": False,
        "verifier_provider_constructed": False,
        "verifier_network_called": False,
        "self_attestation_historical_non_access_proven": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--adoption-record",
        type=Path,
        help="optional proposed adoption record to validate without changing it",
    )
    args = parser.parse_args()
    result = verify(adoption_record_path=args.adoption_record)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
