#!/usr/bin/env python3
"""Sealed, non-collection reliability qualification for the Phase 5R client.

This is not a continuation of v6 or v7 and cannot repair either terminal
pilot.  It makes at most three new, content-free, tool-free Responses calls to
qualify the exact ``gpt-5.6-sol``/``high`` provider shape before a future
separately authorized fresh collection.  Every started call has one physical
attempt, the SDK has zero retries, and the first failure is terminal.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from phase5r_llm_provider import (
    ModelProvider,
    OpenAIResponsesProvider,
    ProviderResult,
    safe_provider_failure_code,
)
import run_phase5r_model_pilot as v1


V8_PLAN_PATH = (
    v1.ROOT
    / "08_reviews/phase5r_model_pilot/replacement_v8"
    / "phase5r_model_pilot_v8_qualification_plan.json"
)
V8_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v8_qualification"
V8_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v8_qualification_execution_plan.json"
V8_AUTHORIZATION_NAME = "phase5r_model_pilot_v8_qualification_authorization.json"
V8_JOURNAL_NAME = "phase5r_model_pilot_v8_qualification_journal.jsonl"
V8_COMPLETION_NAME = "phase5r_model_pilot_v8_qualification_completion.json"
V8_MAXIMUM_MODEL_CALLS = 3
V8_MAXIMUM_USD = Decimal("0.87120")
V8_CALL_RESERVATION_USD = Decimal("0.29040")

QUALIFICATION_SCHEMA = {
    "type": "object",
    "properties": {
        "qualification": {"type": "string", "enum": ["passed"]}
    },
    "required": ["qualification"],
    "additionalProperties": False,
}
QUALIFICATION_INSTRUCTIONS = (
    "This is a non-collection provider reliability qualification. "
    "Return exactly the strict JSON-schema object with "
    "qualification set to passed. Do not use tools or external data."
)
QUALIFICATION_RESULT = {"qualification": "passed"}


def _load_v8_plan(path: Path = V8_PLAN_PATH) -> dict[str, Any]:
    plan = v1._read_json_object(path, label="v8 qualification plan")
    claimed = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    authorization = plan.get("authorization")
    boundaries = plan.get("boundaries")
    qualification = plan.get("qualification")
    if (
        plan.get("schema_version")
        != "phase5r_model_pilot_v8_qualification_plan_v1"
        or plan.get("status") != "authorized_pending_sealed_execution_plan"
        or plan.get("execution_prohibited_without_explicit_runtime_authorization")
        is not False
        or claimed != v1._canonical_sha256(unsigned)
        or not isinstance(authorization, dict)
        or authorization
        != {
            "execution_requires_explicit_runtime_authorization": True,
            "physical_attempts_per_call": 1,
            "sdk_max_retries": 0,
            "training_budget_usd": "15.00",
            "v8_qualification_call_cap": V8_MAXIMUM_MODEL_CALLS,
            "v8_qualification_usd_cap": v1._decimal_text(V8_MAXIMUM_USD),
        }
        or not isinstance(boundaries, dict)
        or any(
            boundaries.get(name) is not False
            for name in (
                "broker_or_account_access",
                "canonical_effect",
                "credential_storage",
                "email_effect",
                "scheduler_effect",
                "trading",
            )
        )
        or boundaries.get("shadow_only") is not True
        or boundaries.get("store") is not False
        or boundaries.get("tools") != []
        or boundaries.get("no_provider_response_id_persistence") is not True
        or boundaries.get("no_raw_failed_response_persistence") is not True
        or not isinstance(qualification, dict)
        or qualification
        != {
            "calls_are_non_collection_diagnostics": True,
            "input_payload_classification": "synthetic_content_free",
            "instructions_sha256": v1._canonical_sha256(
                QUALIFICATION_INSTRUCTIONS
            ),
            "maximum_input_tokens_per_call": v1.MAXIMUM_INPUT_TOKENS,
            "maximum_output_tokens_per_call": v1.MAXIMUM_OUTPUT_TOKENS,
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "required_payload": QUALIFICATION_RESULT,
            "role": "critic",
            "schema_sha256": v1._canonical_sha256(QUALIFICATION_SCHEMA),
            "timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS,
        }
    ):
        raise v1.PilotStop("v8 qualification plan is invalid")
    return plan


def _input_payload(sequence: int) -> dict[str, Any]:
    if not 1 <= sequence <= V8_MAXIMUM_MODEL_CALLS:
        raise v1.PilotStop("v8 qualification sequence is invalid")
    return {
        "qualification_protocol": "phase5r_v8_provider_reliability_gate",
        "sequence": sequence,
        "input_payload_classification": "synthetic_content_free",
    }


def _build_execution_plan(
    replacement: dict[str, Any], *, prices: dict[str, dict[str, Decimal]]
) -> dict[str, Any]:
    reservation = v1._reservation_usd("gpt-5.6-sol", prices)
    if reservation != V8_CALL_RESERVATION_USD:
        raise v1.PilotStop("v8 qualification reservation is not pinned")
    calls = [
        {
            "call_id": f"v8-provider-qualification-{sequence}",
            "sequence": sequence,
            "role": "critic",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "maximum_input_tokens": v1.MAXIMUM_INPUT_TOKENS,
            "maximum_output_tokens": v1.MAXIMUM_OUTPUT_TOKENS,
            "reservation_usd": v1._decimal_text(reservation),
        }
        for sequence in range(1, V8_MAXIMUM_MODEL_CALLS + 1)
    ]
    execution: dict[str, Any] = {
        "schema_version": "phase5r_model_pilot_v8_qualification_execution_plan_v1",
        "replacement_plan_sha256": replacement["plan_sha256"],
        "calls": calls,
        "budget": {
            "maximum_physical_model_calls": V8_MAXIMUM_MODEL_CALLS,
            "maximum_usd": v1._decimal_text(V8_MAXIMUM_USD),
            "worst_case_reserved_usd": v1._decimal_text(
                reservation * V8_MAXIMUM_MODEL_CALLS
            ),
            "sdk_max_retries": 0,
            "maximum_output_tokens_per_call": v1.MAXIMUM_OUTPUT_TOKENS,
        },
        "boundaries": copy.deepcopy(replacement["boundaries"]),
        "qualification": {
            "non_collection": True,
            "schema_sha256": v1._canonical_sha256(QUALIFICATION_SCHEMA),
            "instructions_sha256": v1._canonical_sha256(
                QUALIFICATION_INSTRUCTIONS
            ),
            "required_payload_sha256": v1._canonical_sha256(
                QUALIFICATION_RESULT
            ),
            "input_payload_classification": "synthetic_content_free",
            "failure_diagnostics": [
                "failure_phase",
                "failure_type",
                "provider_failure_code",
                "retry_allowed",
            ],
            "prohibited_failure_diagnostics": [
                "credential",
                "exception_message",
                "provider_error_code",
                "provider_request_id",
                "provider_response_body",
                "provider_response_id",
                "provider_response_headers",
            ],
        },
        "canonical_effect": False,
        "email_effect": False,
        "trading": False,
    }
    execution["plan_sha256"] = v1._canonical_sha256(execution)
    return execution


def check_v8_qualification_readiness(
    *, replacement_plan_path: Path = V8_PLAN_PATH,
    quarantine_root: Path = v1.QUARANTINE_ROOT,
) -> dict[str, Any]:
    """Check the sealed qualification without constructing a provider."""

    try:
        replacement = _load_v8_plan(replacement_plan_path)
        policy, _contexts, _base_plan, _audit, sentinels = (
            v1._readiness_components(quarantine_root=quarantine_root)
        )
        execution = _build_execution_plan(replacement, prices=policy["prices"])
    except Exception as exc:
        return {
            "passed": False,
            "status": "blocked",
            "issues": [f"{type(exc).__name__}:{exc}"],
            "provider_constructed": False,
            "network_used": False,
            "model_calls": 0,
            "files_written": False,
        }
    return {
        "passed": True,
        "status": "ready_for_explicit_v8_qualification_execution",
        "planned_model_calls": len(execution["calls"]),
        "maximum_usd": execution["budget"]["maximum_usd"],
        "worst_case_reserved_usd": execution["budget"]["worst_case_reserved_usd"],
        "training_budget_usd": replacement["authorization"]["training_budget_usd"],
        "replacement_plan_sha256": replacement["plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "daily_monitoring_preserved": sentinels[
            "daily_refresh_launchd_job"
        ]["state"]
        == "loaded"
        and sentinels["daily_decision_launchd_job"]["state"] == "loaded",
        "shadow_scheduler_absent": sentinels["shadow_scheduler_plist"][
            "state"
        ]
        == "absent",
        "provider_constructed": False,
        "network_used": False,
        "model_calls": 0,
        "files_written": False,
        "canonical_effect": False,
        "email_effect": False,
    }


def _write_or_validate(path: Path, payload: dict[str, Any], *, label: str) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise v1.PilotStop(f"{label} is not a regular file")
        if v1._read_json_object(path, label=label) != payload:
            raise v1.PilotStop(f"{label} is not immutable")
        return
    v1._write_json_exclusive(path, payload)


def _authorization_receipt(execution: dict[str, Any]) -> dict[str, Any]:
    receipt = {
        "schema_version": "phase5r_model_pilot_v8_qualification_authorization_v1",
        "replacement_plan_sha256": execution["replacement_plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "authorization_source": "interactive_user_training_budget_15",
        "training_budget_usd": "15.00",
        "maximum_new_model_calls": V8_MAXIMUM_MODEL_CALLS,
        "maximum_new_usd": v1._decimal_text(V8_MAXIMUM_USD),
        "sdk_max_retries": 0,
        "credential_storage": False,
        "canonical_effect": False,
        "email_effect": False,
        "trading": False,
        "broker_or_account_access": False,
    }
    receipt["authorization_sha256"] = v1._canonical_sha256(receipt)
    return receipt


def _assert_execution_root(
    output_root: Path,
    *,
    quarantine_root: Path,
    allow_test_provider: bool,
) -> None:
    if not allow_test_provider and (
        output_root.expanduser().resolve() != V8_OUTPUT_ROOT.resolve()
        or quarantine_root.expanduser().resolve() != v1.QUARANTINE_ROOT.resolve()
    ):
        raise v1.PilotStop("v8 qualification output root is pinned")
    if allow_test_provider:
        try:
            quarantine_root.expanduser().resolve().relative_to(v1.ROOT.resolve())
        except ValueError:
            return
        raise v1.PilotStop("v8 fixture quarantine must stay outside the repository")


def _binding(call: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    input_payload = _input_payload(call["sequence"])
    envelope = {
        "model": call["model"],
        "reasoning_effort": call["reasoning_effort"],
        "schema": QUALIFICATION_SCHEMA,
        "instructions": QUALIFICATION_INSTRUCTIONS,
        "input_payload": input_payload,
        "store": False,
        "tools": [],
        "timeout": v1.REQUEST_TIMEOUT_SECONDS,
        "max_output_tokens": v1.MAXIMUM_OUTPUT_TOKENS,
    }
    envelope_bytes = len(v1._canonical_bytes(envelope))
    if envelope_bytes > v1.MAXIMUM_REQUEST_ENVELOPE_BYTES:
        raise v1.PilotStop("v8 qualification request envelope exceeds byte cap")
    return (
        {
            "call_id": call["call_id"],
            "role": call["role"],
            "model": call["model"],
            "reasoning_effort": call["reasoning_effort"],
            "service_tier": "default",
            "request_timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS,
            "billing_scope_attestation": "global_standard_no_regional_processing",
            "schema_sha256": v1._canonical_sha256(QUALIFICATION_SCHEMA),
            "instructions_sha256": v1._canonical_sha256(
                QUALIFICATION_INSTRUCTIONS
            ),
            "input_sha256": v1._canonical_sha256(input_payload),
            "request_envelope_bytes": envelope_bytes,
            "store": False,
            "tools": [],
            "sdk_max_retries": 0,
        },
        input_payload,
    )


def _completion(
    execution: dict[str, Any], *, events: list[dict[str, Any]]
) -> dict[str, Any]:
    charged = v1._charged_budget(execution, events)
    if (
        charged["used_model_calls"] != V8_MAXIMUM_MODEL_CALLS
        or charged["charged_usd"] > V8_MAXIMUM_USD
    ):
        raise v1.PilotStop("v8 qualification completion accounting is invalid")
    completion = {
        "schema_version": "phase5r_model_pilot_v8_qualification_completion_v1",
        "execution_plan_sha256": execution["plan_sha256"],
        "passed": True,
        "physical_model_calls": charged["used_model_calls"],
        "exact_model_cost_usd": v1._decimal_text(charged["charged_usd"]),
        "collection_authorized": False,
        "canonical_effect": False,
        "email_effect": False,
        "trading": False,
    }
    completion["completion_sha256"] = v1._canonical_sha256(completion)
    return completion


def execute_v8_qualification(
    *,
    provider_factory: Callable[[], ModelProvider],
    explicit_user_authorization: bool,
    replacement_plan_path: Path = V8_PLAN_PATH,
    output_root: Path = V8_OUTPUT_ROOT,
    allow_test_provider: bool = False,
    test_quarantine_root: Path | None = None,
) -> dict[str, Any]:
    """Run the three-call qualification, terminally stopping on first failure."""

    if (
        not callable(provider_factory)
        or explicit_user_authorization is not True
        or not isinstance(allow_test_provider, bool)
    ):
        raise v1.PilotStop("v8 qualification requires explicit user authorization")
    quarantine_root = (
        test_quarantine_root if allow_test_provider else v1.QUARANTINE_ROOT
    )
    if allow_test_provider and quarantine_root is None:
        raise v1.PilotStop("v8 fixture execution requires a fixture quarantine")
    assert quarantine_root is not None
    readiness = check_v8_qualification_readiness(
        replacement_plan_path=replacement_plan_path,
        quarantine_root=quarantine_root,
    )
    if readiness.get("passed") is not True:
        raise v1.PilotStop("v8 qualification readiness is blocked")
    replacement = _load_v8_plan(replacement_plan_path)
    policy, _contexts, _base_plan, _audit, opening_sentinels = (
        v1._readiness_components(quarantine_root=quarantine_root)
    )
    execution = _build_execution_plan(replacement, prices=policy["prices"])
    if readiness["execution_plan_sha256"] != execution["plan_sha256"]:
        raise v1.PilotStop("v8 sealed readiness plan changed before execution")
    _assert_execution_root(
        output_root,
        quarantine_root=quarantine_root,
        allow_test_provider=allow_test_provider,
    )
    with v1._pilot_lock(quarantine_root):
        root = v1._validate_output_root(output_root, quarantine_root)
        _write_or_validate(
            root / V8_EXECUTION_PLAN_NAME,
            execution,
            label="v8 qualification execution plan",
        )
        _write_or_validate(
            root / V8_AUTHORIZATION_NAME,
            _authorization_receipt(execution),
            label="v8 qualification authorization receipt",
        )
        journal_path = root / V8_JOURNAL_NAME
        events = v1._load_journal(
            journal_path, plan_sha256=execution["plan_sha256"]
        )
        completion_path = root / V8_COMPLETION_NAME
        if completion_path.exists():
            completion = v1._read_json_object(
                completion_path, label="v8 qualification completion"
            )
            if completion != _completion(execution, events=events):
                raise v1.PilotStop("v8 qualification completion is invalid")
            return completion
        if any(event["event_kind"] == "pilot_stopped" for event in events):
            raise v1.PilotStop("v8 qualification has a durable stop event")
        if not events:
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="pilot_opened",
                call_id=None,
                details={
                    "maximum_model_calls": V8_MAXIMUM_MODEL_CALLS,
                    "maximum_usd": v1._decimal_text(V8_MAXIMUM_USD),
                    "provider": "test_fixture"
                    if allow_test_provider
                    else "openai_responses_api",
                    "sdk_max_retries": 0,
                    "non_collection": True,
                },
            )
        for call in execution["calls"]:
            terminal = v1._terminal_event(events, call["call_id"])
            if terminal is not None:
                if terminal["event_kind"] != "call_completed":
                    raise v1.PilotStop("v8 qualification call is terminal")
                continue
            if v1._reserved_event(events, call["call_id"]) is not None:
                raise v1.PilotStop("v8 qualification has an unrecovered reservation")
            binding, input_payload = _binding(call)
            v1._enforce_runtime_safety(
                journal_path=journal_path,
                events=events,
                plan_sha256=execution["plan_sha256"],
                call_id=call["call_id"],
                opening_sentinels=opening_sentinels,
                corpus_root=v1.CORPUS_ROOT,
                quarantine_root=quarantine_root,
            )
            try:
                provider = provider_factory()
                v1._strict_provider(
                    provider, allow_test_provider=allow_test_provider
                )
                exact_input_tokens = provider.count_input_tokens(
                    role=call["role"],
                    model=call["model"],
                    reasoning_effort=call["reasoning_effort"],
                    schema=copy.deepcopy(QUALIFICATION_SCHEMA),
                    instructions=QUALIFICATION_INSTRUCTIONS,
                    input_payload=copy.deepcopy(input_payload),
                )
            except Exception as exc:
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={
                        "reason": "provider_or_input_count_preflight_failed",
                        "call_id": call["call_id"],
                        "failure_type": type(exc).__name__,
                        "provider_failure_code": safe_provider_failure_code(exc),
                        "model_calls_charged": 0,
                    },
                )
                raise v1.PilotStop("v8 qualification preflight failed") from exc
            if (
                type(exact_input_tokens) is not int
                or not 0 <= exact_input_tokens <= call["maximum_input_tokens"]
            ):
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={
                        "reason": "exact_input_token_ceiling_exceeded",
                        "call_id": call["call_id"],
                        "model_calls_charged": 0,
                    },
                )
                raise v1.PilotStop("v8 qualification input count exceeds cap")
            binding["exact_input_tokens"] = exact_input_tokens
            binding_sha256 = v1._canonical_sha256(binding)
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="input_count_completed",
                call_id=call["call_id"],
                details={
                    "request_binding_sha256": binding_sha256,
                    "exact_input_tokens": exact_input_tokens,
                    "model_inference_started": False,
                },
            )
            charged = v1._charged_budget(execution, events)
            reservation = v1._decimal(
                call["reservation_usd"], label="v8 qualification reservation"
            )
            if (
                charged["used_model_calls"] + 1 > V8_MAXIMUM_MODEL_CALLS
                or charged["charged_usd"] + reservation > V8_MAXIMUM_USD
            ):
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={
                        "reason": "pre_inference_budget_gate_failed",
                        "call_id": call["call_id"],
                    },
                )
                raise v1.PilotStop("v8 qualification budget gate failed")
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="call_reserved",
                call_id=call["call_id"],
                details={
                    "request_binding": binding,
                    "request_binding_sha256": binding_sha256,
                    "reservation_usd": call["reservation_usd"],
                    "provider_constructed": True,
                    "sdk_max_retries": 0,
                    "maximum_physical_attempts": 1,
                },
            )
            result_received = False
            failure_phase = "provider_result_not_returned"
            try:
                result = provider.generate(
                    role=call["role"],
                    model=call["model"],
                    reasoning_effort=call["reasoning_effort"],
                    schema=copy.deepcopy(QUALIFICATION_SCHEMA),
                    instructions=QUALIFICATION_INSTRUCTIONS,
                    input_payload=copy.deepcopy(input_payload),
                )
                result_received = True
                failure_phase = "post_parse_provider_result_type_check"
                if not isinstance(result, ProviderResult):
                    raise v1.PilotStop("v8 provider returned an invalid result")
                failure_phase = "post_parse_qualification_contract_validation"
                if result.payload != QUALIFICATION_RESULT:
                    raise v1.PilotStop("v8 qualification payload is invalid")
                failure_phase = "post_parse_metering_validation"
                metered = v1._metered_usage(
                    call,
                    result.metadata,
                    policy["prices"],
                    allow_test_provider=allow_test_provider,
                )
                failure_phase = "post_parse_usage_reconciliation"
                if metered["total_input_tokens"] != exact_input_tokens:
                    raise v1.PilotStop("v8 provider usage differs from preflight")
            except Exception as exc:
                details = {
                    "charged_reservation_usd": call["reservation_usd"],
                    "failure_phase": failure_phase,
                    "failure_type": type(exc).__name__,
                    "provider_failure_code": safe_provider_failure_code(exc),
                    "retry_allowed": False,
                    "runtime_safety_issue": v1._runtime_safety_issue(
                        opening_sentinels=opening_sentinels,
                        corpus_root=v1.CORPUS_ROOT,
                        quarantine_root=quarantine_root,
                    ),
                }
                event_kind = (
                    "call_failed" if result_received else "call_outcome_unknown"
                )
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution["plan_sha256"],
                    event_kind=event_kind,
                    call_id=call["call_id"],
                    details=details,
                )
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={"reason": event_kind, "call_id": call["call_id"]},
                )
                raise v1.PilotStop(
                    f"v8 qualification stopped at {call['call_id']}"
                ) from exc
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="call_completed",
                call_id=call["call_id"],
                details={
                    "actual_cost_usd": metered["cost_usd"],
                    "metered_usage": metered,
                    "qualification_payload_accepted": True,
                    "recovered_after_interruption": False,
                },
            )
            v1._enforce_runtime_safety(
                journal_path=journal_path,
                events=events,
                plan_sha256=execution["plan_sha256"],
                call_id=call["call_id"],
                opening_sentinels=opening_sentinels,
                corpus_root=v1.CORPUS_ROOT,
                quarantine_root=quarantine_root,
            )
        completion = _completion(execution, events=events)
        _write_or_validate(
            completion_path, completion, label="v8 qualification completion"
        )
        return completion


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(
        json.dumps(
            check_v8_qualification_readiness(),
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
