#!/usr/bin/env python3
"""Run the isolated, offline-only future-v2 internal-quality workflow.

This CLI accepts only a future handoff and a local assertion-span bundle from
dedicated new directories.  It verifies evidence/citation bindings, checks
claim-to-excerpt spans, and records critic/committee quality signals.  Every
created artifact has ``canonical_effect: false``.  It never reads v10 sealed
artifacts, blind keys, completion records, credentials, or historical runner
state, and it imports no provider, browser, network, execution, broker, email,
or scheduler component.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from zoneinfo import ZoneInfo

from phase5r_assertion_span_contract_v3 import (
    AssertionSpanV3Error,
    evaluate_assertion_span_procedure_v3,
)
from phase5r_llm_evidence_contract_v2_handoff import (
    EvidenceContractV2HandoffError,
    verify_future_v2_handoff,
)


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_ROOT = (
    ROOT / "08_reviews/phase5r_model_pilot/future_v2_offline_integration_v1"
)
HANDOFF_ROOT = INTEGRATION_ROOT / "handoffs"
OUTPUT_ROOT = INTEGRATION_ROOT / "outputs"
OWNER_APPROVAL_ROOT = (
    ROOT / "00_project_control/future_v2_offline_integration_v1/owner_approvals"
)
ASSERTION_SPAN_FILENAME = "assertion_span_bundle_v3.json"
MAX_LOCAL_JSON_BYTES = 8 * 1024 * 1024
RUN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")
_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)


class FutureV2OfflineIntegrationError(ValueError):
    """A future-v2 local input or offline workflow boundary was invalid."""


def _require_direct_child(path: Path, *, root: Path, label: str) -> None:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as exc:
        raise FutureV2OfflineIntegrationError(
            f"{label}: must be inside its dedicated future-v2 root"
        ) from exc
    if len(relative.parts) != 1:
        raise FutureV2OfflineIntegrationError(
            f"{label}: must be a direct child of its dedicated future-v2 root"
        )


def _require_directory(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FutureV2OfflineIntegrationError(f"{label}: missing directory") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise FutureV2OfflineIntegrationError(f"{label}: expected real directory")


def _require_regular_file(path: Path, *, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FutureV2OfflineIntegrationError(f"{label}: missing file") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size == 0
        or metadata.st_size > MAX_LOCAL_JSON_BYTES
    ):
        raise FutureV2OfflineIntegrationError(f"{label}: expected bounded regular file")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise FutureV2OfflineIntegrationError("local JSON has duplicate object key")
        result[key] = value
    return result


def _reject_json_constant(_: str) -> Any:
    raise FutureV2OfflineIntegrationError("local JSON has nonstandard numeric constant")


def _read_local_json(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    """Read one bounded non-symlinked JSON file without normalizing its bytes."""

    _require_regular_file(path, label=label)
    flags = os.O_RDONLY | _NO_FOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise FutureV2OfflineIntegrationError(f"{label}: could not open safely") from exc
    try:
        metadata = os.fstat(descriptor)
        listed = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size == 0
            or metadata.st_size > MAX_LOCAL_JSON_BYTES
            or (metadata.st_dev, metadata.st_ino)
            != (listed.st_dev, listed.st_ino)
        ):
            raise FutureV2OfflineIntegrationError(f"{label}: file changed or is unsafe")
        chunks: list[bytes] = []
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise FutureV2OfflineIntegrationError(f"{label}: truncated while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise FutureV2OfflineIntegrationError(f"{label}: changed while reading")
    finally:
        os.close(descriptor)
    raw = b"".join(chunks)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FutureV2OfflineIntegrationError(f"{label}: must be UTF-8") from exc
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
        raise FutureV2OfflineIntegrationError(f"{label}: must use UTF-8 without BOM and LF")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, FutureV2OfflineIntegrationError) as exc:
        raise FutureV2OfflineIntegrationError(f"{label}: expected strict JSON object") from exc
    if not isinstance(value, dict):
        raise FutureV2OfflineIntegrationError(f"{label}: expected JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _write_new_file(path: Path, *, raw: bytes) -> None:
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NO_FOLLOW,
            0o600,
        )
    except OSError as exc:
        raise FutureV2OfflineIntegrationError(
            f"output file already exists or cannot be created: {path.name}"
        ) from exc
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
    finally:
        os.close(descriptor)


def _write_json(path: Path, value: dict[str, Any]) -> str:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    _write_new_file(path, raw=raw)
    return hashlib.sha256(raw).hexdigest()


def _timestamp_et() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _create_run_directory(run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise FutureV2OfflineIntegrationError("run_id: expected 1-64 lowercase safe characters")
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    _require_directory(OUTPUT_ROOT, label="future-v2 output root")
    run_directory = OUTPUT_ROOT / run_id
    try:
        run_directory.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise FutureV2OfflineIntegrationError("run_id: output directory already exists") from exc
    _require_directory(run_directory, label="future-v2 run output")
    return run_directory


def _critic_disagreement_log(
    *,
    local_artifacts: dict[str, Any],
    packet_id: str,
) -> dict[str, Any]:
    """Record observed critic/committee signals without adjudicating them."""

    decisions = local_artifacts["committee_ticker_decisions"]["decisions"]
    reviews = local_artifacts["critic_coverage"]["ticker_reviews"]
    decisions_by_ticker = {row["ticker"]: row for row in decisions}
    entries: list[dict[str, Any]] = []
    for review in reviews:
        decision = decisions_by_ticker[review["ticker"]]
        failed_dimensions = sorted(
            field
            for field in (
                "factual_grounding_pass",
                "citation_integrity_pass",
                "numeric_reconciliation_pass",
                "long_term_reasoning_pass",
                "action_proportionality_pass",
                "policy_boundary_pass",
            )
            if review[field] is False
        )
        material_issues = [issue for issue in review["issues"] if issue["material"]]
        entries.append(
            {
                "ticker": review["ticker"],
                "committee_claim_ids": decision["claim_ids"],
                "critic_reviewed_claim_ids": review["reviewed_claim_ids"],
                "claim_set_disagreement": (
                    sorted(decision["claim_ids"]) != sorted(review["reviewed_claim_ids"])
                ),
                "critic_verdict": review["verdict"],
                "failed_quality_dimensions": failed_dimensions,
                "material_issue_ids": [issue["issue_id"] for issue in material_issues],
                "issue_count": len(review["issues"]),
                "material_issue_count": len(material_issues),
                "adjudicated": False,
            }
        )
    return {
        "schema_version": "phase5r_future_v2_offline_disagreement_log_v1",
        "packet_id": packet_id,
        "canonical_effect": False,
        "procedure_status": "completed",
        "interpretation": "observed_critic_committee_quality_signals_not_adjudicated",
        "entries": entries,
        "total_material_issue_count": sum(
            entry["material_issue_count"] for entry in entries
        ),
        "provider_or_network_used": False,
        "execution_authority": False,
    }


def _report_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Future-v2 Offline Internal-Quality Report",
        "",
        "This is an offline, noncanonical internal research-quality output. It is not an independent human review, adjudication, promotion, or authorization to act.",
        "",
        f"- Run ID: `{report['run_id']}`",
        f"- Packet ID: `{report['packet_id']}`",
        f"- Procedure status: `{report['procedure_status']}`",
        "- canonical_effect: `false`",
        "- Provider, browser, and network use: `false`",
        "- Execution, broker, account, email, scheduler, and order authority: `false`",
        "",
        "## Checks",
        "",
        f"- Evidence and citation binding: `{report['evidence_and_citation_checks']['status']}`",
        f"- Claim-span procedure: `{report['claim_span_checks']['procedure_status']}`; anchored `{report['claim_span_checks']['span_anchored_count']}` of `{report['claim_span_checks']['assertion_count']}` assertions.",
        f"- Critic/committee log: `{report['disagreement_summary']['entry_count']}` ticker entries, `{report['disagreement_summary']['material_issue_count']}` material issues; not adjudicated.",
        "",
        "The workflow establishes only raw-byte integrity, specified evidence/citation bindings, and declared local claim spans. It does not establish semantic truth, investment suitability, numeric reconciliation beyond the validated sidecar contract, reviewer independence, or any canonical effect.",
        "",
        f"Disagreement-log raw SHA-256: `{report['disagreement_log_raw_file_sha256']}`",
    ]
    return "\n".join(lines) + "\n"


def run_future_v2_offline_integration(
    *,
    handoff_directory: Path,
    owner_approval_reference_path: Path,
    run_id: str,
) -> dict[str, Any]:
    """Execute one future-v2 local workflow and write isolated new outputs."""

    _require_direct_child(handoff_directory, root=HANDOFF_ROOT, label="handoff directory")
    _require_directory(HANDOFF_ROOT, label="future-v2 handoff root")
    _require_directory(handoff_directory, label="handoff directory")
    _require_direct_child(
        owner_approval_reference_path,
        root=OWNER_APPROVAL_ROOT,
        label="owner approval reference",
    )
    _require_directory(OWNER_APPROVAL_ROOT, label="future-v2 owner-approval root")
    owner_approval_reference, owner_reference_sha256 = _read_local_json(
        owner_approval_reference_path,
        label="owner approval reference",
    )
    assertion_bundle, assertion_bundle_sha256 = _read_local_json(
        handoff_directory / ASSERTION_SPAN_FILENAME,
        label="assertion span bundle",
    )
    handoff = verify_future_v2_handoff(
        handoff_root=handoff_directory,
        owner_approval_reference=owner_approval_reference,
    )
    local_artifacts = handoff["verified_local_artifacts"]
    span_result = evaluate_assertion_span_procedure_v3(
        packet=local_artifacts["packet"],
        bundle=assertion_bundle,
    )
    disagreement_log = _critic_disagreement_log(
        local_artifacts=local_artifacts,
        packet_id=handoff["packet_id"],
    )
    run_directory = _create_run_directory(run_id)
    disagreement_log_sha256 = _write_json(
        run_directory / "future_v2_disagreement_log.json",
        disagreement_log,
    )
    critic_reviews = local_artifacts["critic_coverage"]["ticker_reviews"]
    report = {
        "schema_version": "phase5r_future_v2_offline_integration_report_v1",
        "run_id": run_id,
        "created_at_et": _timestamp_et(),
        "procedure_status": (
            "completed" if span_result["procedure_status"] == "completed" else "incomplete"
        ),
        "substantive_recommendation": "not_established",
        "packet_id": handoff["packet_id"],
        "canonical_effect": False,
        "evidence_and_citation_checks": {
            "status": "raw_bytes_and_contract_bindings_validated",
            "sidecar_integrity_validated": handoff["sidecar_integrity_validated"],
            "citation_integrity_pass_by_ticker": [
                {
                    "ticker": review["ticker"],
                    "citation_integrity_pass": review["citation_integrity_pass"],
                }
                for review in critic_reviews
            ],
            "semantic_truth_established": False,
        },
        "claim_span_checks": span_result,
        "disagreement_summary": {
            "entry_count": len(disagreement_log["entries"]),
            "material_issue_count": disagreement_log["total_material_issue_count"],
            "adjudicated": False,
            "status": disagreement_log["interpretation"],
        },
        "input_raw_file_sha256": {
            "owner_approval_reference": owner_reference_sha256,
            "assertion_span_bundle": assertion_bundle_sha256,
            "handoff_manifest": handoff["manifest_sha256"],
        },
        "disagreement_log_raw_file_sha256": disagreement_log_sha256,
        "human_review_status": "not_performed",
        "independent_human_review_satisfied": False,
        "provider_or_network_used": False,
        "repository_initiated_provider_call_authorized": False,
        "blind_key_access_authorized": False,
        "unblinding_authorized": False,
        "execution_authority": False,
        "broker_or_account_authority": False,
        "email_or_scheduler_authority": False,
    }
    report_sha256 = _write_json(
        run_directory / "future_v2_offline_integration_report.json",
        report,
    )
    _write_new_file(
        run_directory / "future_v2_offline_integration_report.md",
        raw=_report_markdown(report).encode("utf-8"),
    )
    return {
        "procedure_status": report["procedure_status"],
        "canonical_effect": False,
        "packet_id": report["packet_id"],
        "output_directory": str(run_directory),
        "report_raw_file_sha256": report_sha256,
        "disagreement_log_raw_file_sha256": disagreement_log_sha256,
        "provider_or_network_used": False,
        "execution_authority": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-dir", type=Path, required=True)
    parser.add_argument("--owner-approval-reference", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    try:
        result = run_future_v2_offline_integration(
            handoff_directory=args.handoff_dir,
            owner_approval_reference_path=args.owner_approval_reference,
            run_id=args.run_id,
        )
    except (
        AssertionSpanV3Error,
        EvidenceContractV2HandoffError,
        FutureV2OfflineIntegrationError,
    ) as exc:
        print(
            json.dumps(
                {
                    "procedure_status": "invalidated",
                    "canonical_effect": False,
                    "error": str(exc),
                    "provider_or_network_used": False,
                    "execution_authority": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
