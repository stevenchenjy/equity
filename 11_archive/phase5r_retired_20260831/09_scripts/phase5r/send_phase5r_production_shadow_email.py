#!/usr/bin/env python3
"""Deliver one validated production-shadow report through an external runtime.

This module never imports an SMTP, browser, provider, or brokerage client.  It
requires a pre-existing external mail executable supplied outside this
repository through ``PHASE5R_PRODUCTION_SHADOW_MAIL_RUNTIME``.  That runtime
must support a no-send ``--check`` command and the tightly scoped JSON-stdin
delivery contract defined below.  Credentials are neither read nor stored by
this module.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

import phase5r_production_shadow_v1 as shadow
from phase5r_daily_common import ExclusiveFileLock, ROOT, canonical_sha256, cycle_date, iso_now


RECIPIENT = "stevenchenjy326@gmail.com"
OWNER_AUTHORIZATION_REFERENCE = "phase5r-production-shadow-email-limited-2026-08-04"
EXTERNAL_RUNTIME_ENV = "PHASE5R_PRODUCTION_SHADOW_MAIL_RUNTIME"

CHECK_SCHEMA_VERSION = "phase5r_external_mail_runtime_check_v1"
DELIVERY_SCHEMA_VERSION = "phase5r_external_mail_runtime_delivery_v1"
REQUEST_SCHEMA_VERSION = "phase5r_external_mail_runtime_request_v1"
RECEIPT_SCHEMA_VERSION = "phase5r_production_shadow_email_delivery_receipt_v1"

RECEIPT_PATH = shadow.LEDGER_ROOT / "production_shadow_email_delivery_receipts.jsonl"
LOCK_PATH = shadow.CONTROL_ROOT / "production_shadow_email.lock"
REPORT_FILENAME = "production_shadow_daily_report.md"
RESULT_FILENAME = "production_shadow_result.json"
VALIDATION_FILENAME = "production_shadow_validation.json"
MANIFEST_FILENAME = "production_shadow_manifest.json"
MODEL_INPUT_FILENAME = "model_input.json"

_NO_FOLLOW = getattr(os, "O_NOFOLLOW", 0)
_RUN_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,95}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_MAX_RUNTIME_OUTPUT_BYTES = 4 * 1024
_RECEIPT_EVENT_TYPES = frozenset(
    {"configuration_blocked", "send_claimed", "sent", "delivery_unknown"}
)
_BLOCKING_DELIVERY_STATUSES = frozenset(
    {
        "configuration_blocked",
        "send_claimed",
        "accepted_by_authenticated_external_runtime",
        "delivery_unknown",
    }
)


class MailBoundaryError(RuntimeError):
    """A finite, non-sensitive mail-boundary failure."""


@dataclass(frozen=True)
class ValidatedReport:
    run_id: str
    trading_day: str
    report_sha256: str
    result_sha256: str
    validation_sha256: str
    input_manifest_sha256: str
    text_body: str


def _raw_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_sha256(value: Any, *, code: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise MailBoundaryError(code)
    return value


def _safe_run_id(value: Any) -> str:
    if not isinstance(value, str) or _RUN_ID_PATTERN.fullmatch(value) is None:
        raise MailBoundaryError("shadow_run_id_invalid")
    return value


def _safe_regular_directory(path: Path, *, code: str) -> Path:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MailBoundaryError(code) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise MailBoundaryError(code)
    return path


def _read_safe_bytes(path: Path, *, code: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise MailBoundaryError(code) from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > _MAX_ARTIFACT_BYTES
    ):
        raise MailBoundaryError(code)
    try:
        descriptor = os.open(path, os.O_RDONLY | _NO_FOLLOW)
    except OSError as exc:
        raise MailBoundaryError(code) from exc
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_size != metadata.st_size
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
        ):
            raise MailBoundaryError(code)
        chunks: list[bytes] = []
        remaining = metadata.st_size + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    finally:
        os.close(descriptor)
    if len(raw) != metadata.st_size:
        raise MailBoundaryError(code)
    return raw


def _read_safe_json(path: Path, *, code: str) -> tuple[dict[str, Any], str]:
    raw = _read_safe_bytes(path, code=code)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MailBoundaryError(code) from exc
    if not isinstance(payload, dict):
        raise MailBoundaryError(code)
    return payload, _raw_sha256(raw)


def _runtime_path() -> tuple[Path | None, str | None]:
    value = os.environ.get(EXTERNAL_RUNTIME_ENV)
    if not isinstance(value, str) or not value:
        return None, "external_mail_runtime_not_configured"
    if len(value) > 1024:
        return None, "external_mail_runtime_invalid"
    path = Path(value)
    if not path.is_absolute():
        return None, "external_mail_runtime_invalid"
    try:
        metadata = path.lstat()
        resolved = path.resolve(strict=True)
        root_resolved = ROOT.resolve(strict=True)
    except OSError:
        return None, "external_mail_runtime_invalid"
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not metadata.st_mode & stat.S_IXUSR
    ):
        return None, "external_mail_runtime_invalid"
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        return resolved, None
    return None, "external_mail_runtime_must_be_outside_repository"


def _parse_runtime_json(raw: str, *, schema_version: str) -> dict[str, Any] | None:
    if not isinstance(raw, str) or len(raw.encode("utf-8", errors="ignore")) > _MAX_RUNTIME_OUTPUT_BYTES:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema_version") != schema_version:
        return None
    return value


def external_runtime_check() -> dict[str, Any]:
    """Run the external runtime's contractually no-send authentication check."""

    runtime, reason = _runtime_path()
    if runtime is None:
        return {
            "ready": False,
            "reason": reason,
            "runtime": None,
            "external_runtime_invoked": False,
        }
    try:
        completed = subprocess.run(
            [str(runtime), "--check"],
            cwd=ROOT,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "ready": False,
            "reason": "external_mail_runtime_check_failed",
            "runtime": runtime,
            "external_runtime_invoked": True,
        }
    check = _parse_runtime_json(completed.stdout, schema_version=CHECK_SCHEMA_VERSION)
    if completed.returncode != 0 or check is None:
        return {
            "ready": False,
            "reason": "external_mail_runtime_check_failed",
            "runtime": runtime,
            "external_runtime_invoked": True,
        }
    expected = {
        "schema_version",
        "available",
        "authenticated",
        "network_attempted",
        "credential_exposed",
        "supports_one_time_shadow_delivery",
    }
    if set(check) != expected or check["network_attempted"] is not False or check["credential_exposed"] is not False:
        return {
            "ready": False,
            "reason": "external_mail_runtime_contract_invalid",
            "runtime": runtime,
            "external_runtime_invoked": True,
        }
    if check["available"] is not True or check["authenticated"] is not True or check["supports_one_time_shadow_delivery"] is not True:
        return {
            "ready": False,
            "reason": "external_mail_runtime_not_authenticated",
            "runtime": runtime,
            "external_runtime_invoked": True,
        }
    return {
        "ready": True,
        "reason": None,
        "runtime": runtime,
        "external_runtime_invoked": True,
    }


def _safe_text(value: Any, *, code: str, maximum: int = 1_200) -> str:
    try:
        return shadow._safe_model_text(value, label="shadow_email_text", maximum=maximum)
    except shadow.ProductionShadowError as exc:
        raise MailBoundaryError(code) from exc


def _known_label(mapping: dict[str, str], value: Any, *, code: str) -> str:
    if not isinstance(value, str) or value not in mapping:
        raise MailBoundaryError(code)
    return mapping[value]


def _finding_lines(value: Any, *, code: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 12:
        raise MailBoundaryError(code)
    lines: list[str] = []
    for row in value:
        if not isinstance(row, dict) or set(row) != {"finding", "source_ids"}:
            raise MailBoundaryError(code)
        lines.append(_safe_text(row.get("finding"), code=code, maximum=700))
    return lines


def _safe_codes(value: Any, labels: dict[str, str], *, code: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 12:
        raise MailBoundaryError(code)
    return [_known_label(labels, item, code=code) for item in value]


def _email_text(result: dict[str, Any], exposure: dict[str, Any]) -> str:
    deterministic = _safe_text(
        result.get("deterministic_decision_code"), code="shadow_result_invalid", maximum=96
    )
    agreement = result.get("agreement_status")
    if agreement not in {"agree", "challenge", "insufficient_evidence", "manual_review"}:
        raise MailBoundaryError("shadow_result_invalid")
    validation = result.get("validation")
    if not isinstance(validation, dict):
        raise MailBoundaryError("shadow_result_invalid")
    if (
        validation.get("future_v2_citation_binding_status") != "completed"
        or validation.get("citation_quality") != "passed"
        or validation.get("assertion_span_procedure_status") != "completed"
    ):
        raise MailBoundaryError("shadow_result_not_eligible")
    valuation_status = result.get("valuation_status")
    valuation_actionable = result.get("valuation_actionable")
    if (
        valuation_status not in {"available", "unavailable"}
        or not isinstance(valuation_actionable, bool)
        or result.get("valuation_conclusion") != "abstain"
        or (
            valuation_status == "unavailable"
            and valuation_actionable is True
        )
    ):
        raise MailBoundaryError("shadow_result_invalid")
    positive = _finding_lines(result.get("positive_findings"), code="shadow_result_invalid")
    negative = _finding_lines(result.get("negative_findings"), code="shadow_result_invalid")
    missing = _safe_codes(
        result.get("missing_or_contradictory_evidence"),
        shadow._MISSING_EVIDENCE_LABELS,
        code="shadow_result_invalid",
    )
    holding = _safe_codes(
        result.get("holding_period_considerations"),
        shadow._HOLDING_PERIOD_LABELS,
        code="shadow_result_invalid",
    )
    next_review = _safe_codes(
        result.get("next_review_conditions"),
        shadow._NEXT_REVIEW_LABELS,
        code="shadow_result_invalid",
    )
    overclaims = result.get("overclaim_findings")
    if not isinstance(overclaims, list) or len(overclaims) > 12:
        raise MailBoundaryError("shadow_result_invalid")
    overclaim_lines: list[str] = []
    for row in overclaims:
        if not isinstance(row, dict):
            raise MailBoundaryError("shadow_result_invalid")
        issue_type = row.get("issue_type")
        severity = row.get("severity")
        if severity not in {"low", "medium", "high"}:
            raise MailBoundaryError("shadow_result_invalid")
        overclaim_lines.append(
            f"{severity}: {_known_label(shadow._OVERCLAIM_LABELS, issue_type, code='shadow_result_invalid')}"
        )
    confidence = result.get("confidence_calibration")
    if (
        not isinstance(confidence, dict)
        or not isinstance(confidence.get("confidence_pct"), int)
        or isinstance(confidence.get("confidence_pct"), bool)
        or not 0 <= confidence["confidence_pct"] <= 100
        or confidence.get("calibration") not in {"low", "moderate", "high"}
    ):
        raise MailBoundaryError("shadow_result_invalid")
    adjustment = result.get("proposed_classification_adjustment")
    if not isinstance(adjustment, dict):
        raise MailBoundaryError("shadow_result_invalid")
    ticker = adjustment.get("ticker")
    classification = adjustment.get("classification")
    if (
        not isinstance(ticker, str)
        or re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", ticker) is None
        or classification not in shadow._CLASSIFICATIONS
    ):
        raise MailBoundaryError("shadow_result_invalid")
    for field in (
        "daily_metered_usd",
        "monthly_metered_usd",
        "daily_reserved_usd",
        "monthly_reserved_usd",
    ):
        _safe_text(exposure.get(field), code="cost_exposure_invalid", maximum=32)
    bullet = lambda lines: "\n".join(f"- {line}" for line in lines) or "- None reported."
    return "\n".join(
        [
            "Phase 5R Production Shadow Daily Research Report",
            "",
            "This is a shadow-only, AI-assisted, noncanonical internal research report. It does not authorize trading and did not change any deterministic classification, broker, account, position, or order.",
            "",
            f"- Deterministic classification: {deterministic}",
            f"- LLM agreement status: {agreement}",
            f"- Valuation status: {valuation_status}; valuation actionable: {str(valuation_actionable).lower()}; LLM valuation conclusion: abstain.",
            "- Citation binding: completed; literal-span validation: completed; citation quality: passed.",
            f"- Current daily model cost: ${exposure['daily_metered_usd']} (reserved ${exposure['daily_reserved_usd']})",
            f"- Current monthly model cost: ${exposure['monthly_metered_usd']} (reserved ${exposure['monthly_reserved_usd']})",
            "",
            "Positive evidence-supported findings:",
            bullet(positive),
            "",
            "Negative evidence-supported findings:",
            bullet(negative),
            "",
            "Missing or contradictory evidence:",
            bullet(missing),
            "",
            "Material overclaim or confidence concerns:",
            bullet(overclaim_lines),
            f"- Confidence calibration: {confidence['confidence_pct']}% / {confidence['calibration']}",
            "",
            "Proposed adjustment (explicitly noncanonical):",
            f"- {ticker}: {classification}. This is research-only and has no execution effect.",
            "",
            "Holding-period considerations:",
            bullet(holding),
            "",
            "Conditions for the next review:",
            bullet(next_review),
            "",
            "No broker, account, position, or order action occurred.",
            "",
        ]
    )


def _validated_report(run_id: str) -> ValidatedReport:
    run_id = _safe_run_id(run_id)
    report_directory = _safe_regular_directory(
        shadow.REPORT_ROOT / run_id, code="shadow_report_directory_invalid"
    )
    validation_directory = _safe_regular_directory(
        shadow.VALIDATION_ROOT / run_id, code="shadow_validation_directory_invalid"
    )
    handoff_directory = _safe_regular_directory(
        shadow.HANDOFF_ROOT / run_id, code="shadow_handoff_directory_invalid"
    )
    result, result_sha256 = _read_safe_json(
        report_directory / RESULT_FILENAME, code="shadow_result_invalid"
    )
    validation, validation_sha256 = _read_safe_json(
        validation_directory / VALIDATION_FILENAME, code="shadow_validation_invalid"
    )
    manifest, manifest_sha256 = _read_safe_json(
        handoff_directory / MANIFEST_FILENAME, code="shadow_manifest_invalid"
    )
    model_input, model_input_sha256 = _read_safe_json(
        handoff_directory / MODEL_INPUT_FILENAME, code="shadow_model_input_invalid"
    )
    report_raw = _read_safe_bytes(report_directory / REPORT_FILENAME, code="shadow_report_invalid")
    if (
        result.get("schema_version") != shadow.RESULT_SCHEMA_VERSION
        or result.get("run_id") != run_id
        or result.get("trading_day") != cycle_date()
        or result.get("outcome") != "completed"
        or result.get("canonical_effect") is not False
        or result.get("independent_human_review_satisfied") is not False
        or result.get("email_or_scheduler_effect") is not False
        or result.get("broker_or_account_access") is not False
        or result.get("order_or_position_effect") is not False
    ):
        raise MailBoundaryError("shadow_result_not_eligible")
    missing_evidence = result.get("missing_or_contradictory_evidence")
    if (
        result.get("valuation_status") not in {"available", "unavailable"}
        or not isinstance(result.get("valuation_actionable"), bool)
        or result.get("valuation_conclusion") != "abstain"
        or (
            result.get("valuation_status") == "unavailable"
            and (
                not isinstance(missing_evidence, list)
                or "valuation_evidence_absent" not in missing_evidence
            )
        )
    ):
        raise MailBoundaryError("shadow_result_not_eligible")
    if (
        validation.get("schema_version") != shadow.VALIDATION_SCHEMA_VERSION
        or validation.get("run_id") != run_id
        or validation.get("status") != "completed"
        or validation.get("future_v2_citation_binding_status") != "completed"
        or validation.get("assertion_span_procedure_status") != "completed"
        or validation.get("canonical_effect") is not False
        or validation.get("provider_or_network_used_by_validator") is not False
    ):
        raise MailBoundaryError("shadow_validation_invalid")
    if (
        manifest.get("schema_version") != shadow.MANIFEST_SCHEMA_VERSION
        or manifest.get("run_id") != run_id
        or manifest.get("trading_day") != cycle_date()
        or manifest.get("status") != "validated_offline_pre_provider"
        or result.get("input_manifest_sha256") != manifest_sha256
    ):
        raise MailBoundaryError("shadow_manifest_invalid")
    artifacts = manifest.get("artifact_sha256")
    provider = result.get("provider")
    if (
        not isinstance(artifacts, dict)
        or artifacts.get("model_input") != model_input_sha256
        or not isinstance(provider, dict)
        or provider.get("requested_model") != shadow.MODEL
        or provider.get("reasoning_effort") != shadow.REASONING_EFFORT
        or provider.get("store") is not False
        or provider.get("tools_enabled") is not False
        or provider.get("input_payload_canonical_sha256") != canonical_sha256(model_input)
    ):
        raise MailBoundaryError("shadow_input_receipt_invalid")
    try:
        shadow._validate_model_input_privacy(model_input)
        expected_report = shadow._result_markdown(result).encode("utf-8")
    except (shadow.ProductionShadowError, KeyError, TypeError, ValueError) as exc:
        raise MailBoundaryError("shadow_report_invalid") from exc
    if _raw_sha256(report_raw) != _raw_sha256(expected_report):
        raise MailBoundaryError("shadow_report_invalid")
    exposure = shadow.current_cost_exposure()
    text_body = _email_text(result, exposure)
    return ValidatedReport(
        run_id=run_id,
        trading_day=cycle_date(),
        report_sha256=_raw_sha256(report_raw),
        result_sha256=result_sha256,
        validation_sha256=validation_sha256,
        input_manifest_sha256=_require_sha256(
            result.get("input_manifest_sha256"), code="shadow_manifest_invalid"
        ),
        text_body=text_body,
    )


def _recipient_sha256() -> str:
    return _raw_sha256(RECIPIENT.encode("utf-8"))


def _parse_receipts() -> list[dict[str, Any]]:
    if not RECEIPT_PATH.exists():
        return []
    raw = _read_safe_bytes(RECEIPT_PATH, code="shadow_email_receipt_invalid")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise MailBoundaryError("shadow_email_receipt_invalid") from exc
    if not lines:
        raise MailBoundaryError("shadow_email_receipt_invalid")
    previous = ""
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MailBoundaryError("shadow_email_receipt_invalid") from exc
        if not isinstance(event, dict):
            raise MailBoundaryError("shadow_email_receipt_invalid")
        claimed = event.get("event_sha256")
        unsigned = dict(event)
        unsigned.pop("event_sha256", None)
        if (
            event.get("schema_version") != RECEIPT_SCHEMA_VERSION
            or event.get("event_type") not in _RECEIPT_EVENT_TYPES
            or event.get("previous_event_sha256") != previous
            or not isinstance(claimed, str)
            or claimed != canonical_sha256(unsigned)
        ):
            raise MailBoundaryError("shadow_email_receipt_invalid")
        previous = claimed
        events.append(event)
    return events


def _append_receipt(event: dict[str, Any]) -> dict[str, Any]:
    events = _parse_receipts()
    unsigned = dict(event)
    unsigned.update(
        {
            "schema_version": RECEIPT_SCHEMA_VERSION,
            "previous_event_sha256": events[-1]["event_sha256"] if events else "",
        }
    )
    unsigned["event_sha256"] = canonical_sha256(unsigned)
    raw = (json.dumps(unsigned, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | _NO_FOLLOW
    try:
        descriptor = os.open(RECEIPT_PATH, flags, 0o600)
    except OSError as exc:
        raise MailBoundaryError("shadow_email_receipt_unavailable") from exc
    try:
        offset = 0
        while offset < len(raw):
            offset += os.write(descriptor, raw[offset:])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return unsigned


def _delivery_blocked(events: list[dict[str, Any]], *, trading_day: str) -> bool:
    return any(
        event.get("trading_day") == trading_day
        and event.get("recipient_sha256") == _recipient_sha256()
        and (
            event.get("event_type") in _RECEIPT_EVENT_TYPES
            or event.get("delivery_status") in _BLOCKING_DELIVERY_STATUSES
        )
        for event in events
    )


def _receipt_base(report: ValidatedReport, *, event_type: str, delivery_status: str, email_attempted: bool, email_sent: str, runtime_check: str) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "recorded_at_et": iso_now(),
        "trading_day": report.trading_day,
        "run_id": report.run_id,
        "recipient_sha256": _recipient_sha256(),
        "report_raw_sha256": report.report_sha256,
        "result_raw_sha256": report.result_sha256,
        "validation_raw_sha256": report.validation_sha256,
        "input_manifest_sha256": report.input_manifest_sha256,
        "authorization_reference": OWNER_AUTHORIZATION_REFERENCE,
        "external_runtime_check": runtime_check,
        "email_attempted": email_attempted,
        "email_sent": email_sent,
        "delivery_status": delivery_status,
        "canonical_effect": False,
        "broker_or_account_access": False,
        "order_or_position_effect": False,
    }


def _runtime_delivery(runtime: Path, report: ValidatedReport) -> bool:
    envelope = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "recipient": RECIPIENT,
        "subject": f"[Phase 5R shadow-only] Daily research — {report.trading_day}",
        "text_body": report.text_body,
        "run_id": report.run_id,
        "canonical_effect": False,
        "trading_authority_created": False,
    }
    try:
        completed = subprocess.run(
            [str(runtime), "--send-phase5r-production-shadow-json-stdin"],
            cwd=ROOT,
            text=True,
            input=json.dumps(envelope, ensure_ascii=False, sort_keys=True),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    ack = _parse_runtime_json(completed.stdout, schema_version=DELIVERY_SCHEMA_VERSION)
    expected = {
        "schema_version",
        "accepted",
        "network_attempted",
        "credential_exposed",
        "recipient_count",
    }
    return bool(
        completed.returncode == 0
        and ack is not None
        and set(ack) == expected
        and ack["accepted"] is True
        and ack["network_attempted"] is True
        and ack["credential_exposed"] is False
        and ack["recipient_count"] == 1
    )


def send_run(run_id: str) -> dict[str, Any]:
    """Validate, claim, and make exactly one external delivery attempt."""

    try:
        report = _validated_report(run_id)
    except MailBoundaryError as exc:
        return {"outcome": "blocked", "reason": str(exc), "email_attempted": False}
    with ExclusiveFileLock(LOCK_PATH):
        try:
            events = _parse_receipts()
        except MailBoundaryError as exc:
            return {"outcome": "blocked", "reason": str(exc), "email_attempted": False}
        if _delivery_blocked(events, trading_day=report.trading_day):
            return {
                "outcome": "deduplicated",
                "reason": "prior_shadow_email_receipt_blocks_delivery",
                "email_attempted": False,
            }
        checked = external_runtime_check()
        if checked["ready"] is not True:
            _append_receipt(
                _receipt_base(
                    report,
                    event_type="configuration_blocked",
                    delivery_status="configuration_blocked",
                    email_attempted=False,
                    email_sent="no",
                    runtime_check=str(checked["reason"]),
                )
            )
            return {
                "outcome": "blocked",
                "reason": str(checked["reason"]),
                "email_attempted": False,
            }
        runtime = checked["runtime"]
        if not isinstance(runtime, Path):
            return {"outcome": "blocked", "reason": "external_mail_runtime_invalid", "email_attempted": False}
        # Revalidate just before the irreversible durable claim.  This binds
        # the report and input receipt again after any earlier runtime check.
        try:
            report = _validated_report(report.run_id)
        except MailBoundaryError as exc:
            return {"outcome": "blocked", "reason": str(exc), "email_attempted": False}
        _append_receipt(
            _receipt_base(
                report,
                event_type="send_claimed",
                delivery_status="send_claimed",
                email_attempted=False,
                email_sent="no",
                runtime_check="passed",
            )
        )
        if _runtime_delivery(runtime, report):
            _append_receipt(
                _receipt_base(
                    report,
                    event_type="sent",
                    delivery_status="accepted_by_authenticated_external_runtime",
                    email_attempted=True,
                    email_sent="accepted",
                    runtime_check="passed",
                )
            )
            return {
                "outcome": "sent",
                "reason": "accepted_by_authenticated_external_runtime",
                "email_attempted": True,
            }
        _append_receipt(
            _receipt_base(
                report,
                event_type="delivery_unknown",
                delivery_status="delivery_unknown",
                email_attempted=True,
                email_sent="unknown",
                runtime_check="passed",
            )
        )
        return {
            "outcome": "delivery_unknown",
            "reason": "external_mail_delivery_unknown_after_claim",
            "email_attempted": True,
        }


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--send-run-id")
    args = parser.parse_args()
    if args.check:
        checked = external_runtime_check()
        _print(
            {
                "schema_version": "phase5r_production_shadow_email_check_v1",
                "outcome": "ready" if checked["ready"] is True else "blocked",
                "reason": checked["reason"],
                "recipient_configured": True,
                "external_runtime_invoked": checked["external_runtime_invoked"],
                "network_attempted": False,
                "credential_exposed": False,
                "canonical_effect": False,
                "email_attempted": False,
            }
        )
        return 0 if checked["ready"] is True else 2
    try:
        result = send_run(str(args.send_run_id))
    except MailBoundaryError as exc:
        result = {
            "outcome": "blocked",
            "reason": str(exc),
            "email_attempted": False,
        }
    except (OSError, TypeError, ValueError):
        result = {
            "outcome": "blocked",
            "reason": "shadow_email_internal_failure",
            "email_attempted": False,
        }
    _print(
        {
            "schema_version": "phase5r_production_shadow_email_send_v1",
            "outcome": result["outcome"],
            "reason": result["reason"],
            "canonical_effect": False,
            "email_attempted": result["email_attempted"],
        }
    )
    return 1 if result["outcome"] == "delivery_unknown" else 0


if __name__ == "__main__":
    raise SystemExit(main())
