#!/usr/bin/env python3
"""Fresh, independently authorized Phase 5R v6 shadow-only collection.

This runner cannot resume or combine v1-v5.  It seals a new 30-call plan in
its own quarantine directory, uses one physical attempt per request, and
stops permanently on every started failure.  Authentication stays entirely in
the injected external OpenAI client; this module neither reads nor stores it.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from phase5r_llm_contract import ContractError
from phase5r_llm_provider import (
    ModelProvider,
    OpenAIResponsesProvider,
    ProviderResult,
    safe_provider_failure_code,
)
from phase5r_model_pilot_v6_contract import (
    SOURCE_LOCKED_V6_INSTRUCTIONS,
    hydrate_source_locked_assessment_v6,
    source_locked_input_view_v6,
    strict_schema_for_stage_v6,
)
import run_phase5r_model_pilot as v1


V6_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_replacement_plan_v6"
V6_EXECUTION_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_execution_plan_v6"
V6_AUTHORIZATION_SCHEMA_VERSION = "phase5r_model_pilot_v6_authorization_v1"

V6_PLAN_PATH = (
    v1.ROOT
    / "08_reviews"
    / "phase5r_model_pilot"
    / "replacement_v6"
    / "phase5r_model_pilot_v6_plan.json"
)
V6_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v6"
V6_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v6_execution_plan.json"
V6_AUTHORIZATION_NAME = "phase5r_model_pilot_v6_authorization.json"
V6_JOURNAL_NAME = "phase5r_model_pilot_v6_journal.jsonl"

_PREDECESSORS = {
    "v1": (
        v1.QUARANTINE_ROOT / "v1" / v1.PLAN_NAME,
        v1.QUARANTINE_ROOT / "v1" / v1.JOURNAL_NAME,
    ),
    "v2": (
        v1.QUARANTINE_ROOT / "v2" / "phase5r_model_pilot_v2_execution_plan.json",
        v1.QUARANTINE_ROOT / "v2" / "phase5r_model_pilot_v2_journal.jsonl",
    ),
    "v3": (
        v1.QUARANTINE_ROOT / "v3" / "phase5r_model_pilot_v3_execution_plan.json",
        v1.QUARANTINE_ROOT / "v3" / "phase5r_model_pilot_v3_journal.jsonl",
    ),
    "v4": (
        v1.QUARANTINE_ROOT / "v4" / "phase5r_model_pilot_v4_execution_plan.json",
        v1.QUARANTINE_ROOT / "v4" / "phase5r_model_pilot_v4_journal.jsonl",
    ),
    "v5": (
        v1.QUARANTINE_ROOT / "v5" / "phase5r_model_pilot_v5_execution_plan.json",
        v1.QUARANTINE_ROOT / "v5" / "phase5r_model_pilot_v5_journal.jsonl",
    ),
}


def _load_v6_plan(path: Path = V6_PLAN_PATH) -> dict[str, Any]:
    plan = v1._read_json_object(path, label="v6 replacement plan")
    claimed = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    boundaries = plan.get("boundaries")
    authorization = plan.get("authorization")
    layout = plan.get("collection_layout")
    gate = plan.get("capability_gate")
    if (
        plan.get("schema_version") != V6_PLAN_SCHEMA_VERSION
        or plan.get("status") != "authorized_pending_sealed_execution_plan"
        or plan.get("execution_prohibited_without_explicit_runtime_authorization")
        is not True
        or v1._canonical_sha256(unsigned) != claimed
        or not isinstance(boundaries, dict)
        or not isinstance(authorization, dict)
        or not isinstance(layout, dict)
        or not isinstance(gate, dict)
        or authorization.get("new_independent_model_call_cap")
        != v1.MAXIMUM_PHYSICAL_MODEL_CALLS
        or authorization.get("new_independent_usd_cap")
        != "5.00"
        or authorization.get("sdk_max_retries") != 0
        or authorization.get("execution_requires_sealed_plan_offline_tests_and_capability_gate")
        is not True
        or layout
        != {
            "analyst_calls": 20,
            "committee_calls": 5,
            "critic_calls": 5,
            "total_calls": 30,
            "collection_must_complete_atomically": True,
            "partial_receipts_cannot_be_combined_with_v1_to_v5": True,
        }
        or gate
        != {
            "provider": "openai_responses_api",
            "strict_json_schema": True,
            "minLength": 1,
            "first_accepted_request_is_collection_call_one": True,
            "schema_rejection_before_inference_is_terminal": True,
            "raw_failure_or_provider_response_id_persisted": False,
        }
        or any(
            boundaries.get(name) is not False
            for name in (
                "email_effect",
                "canonical_effect",
                "automatic_action_allowed",
                "broker_used",
                "account_read",
                "order_code_created",
            )
        )
        or boundaries.get("shadow_only") is not True
        or boundaries.get("store") is not False
        or boundaries.get("tools") != []
        or boundaries.get("sdk_max_retries") != 0
        or boundaries.get("no_credential_persistence") is not True
        or boundaries.get("no_raw_failed_response_persistence") is not True
        or boundaries.get("no_provider_response_id_persistence") is not True
    ):
        raise v1.PilotStop("v6 replacement plan is invalid")
    return plan


def _validate_terminal_predecessors(replacement: dict[str, Any]) -> dict[str, str]:
    """Revalidate all sealed predecessors without modifying any of them."""

    states: dict[str, str] = {}
    for version, (plan_path, journal_path) in _PREDECESSORS.items():
        predecessor = replacement.get(f"source_{version}")
        if not isinstance(predecessor, dict):
            raise v1.PilotStop(f"v6 predecessor {version} binding is missing")
        plan = v1._read_json_object(plan_path, label=f"{version} execution plan")
        plan_sha256 = plan.get("plan_sha256")
        if (
            not isinstance(plan_sha256, str)
            or v1._sha256_file(journal_path)
            != predecessor.get("journal_file_sha256")
            or predecessor.get("action")
            not in {
                "preserve_immutable_no_resume_no_reset",
                "preserve_terminal_no_resume_no_retry",
            }
        ):
            raise v1.PilotStop(f"v6 predecessor {version} hash binding is invalid")
        if version == "v1" and predecessor.get("plan_sha256") != plan_sha256:
            raise v1.PilotStop("v6 predecessor v1 plan binding is invalid")
        events = v1._load_journal(journal_path, plan_sha256=plan_sha256)
        if not events or events[-1].get("event_kind") != "pilot_stopped":
            raise v1.PilotStop(f"v6 predecessor {version} is not terminal")
        if any(event.get("event_kind") == "model_calls_completed" for event in events):
            raise v1.PilotStop(f"v6 predecessor {version} cannot be reused")
        states[version] = v1._sha256_file(journal_path)
    return states


def _schema_profile() -> dict[str, str]:
    schemas = {
        stage: strict_schema_for_stage_v6(stage)
        for stage in (
            "luna_assessment",
            "terra_assessment",
            "sol_committee",
            "sol_critic",
        )
    }
    for schema in schemas.values():
        stack: list[Any] = [schema]
        while stack:
            current = stack.pop()
            if not isinstance(current, dict):
                continue
            if current.get("type") == "string" and current.get("minLength") != 1:
                raise v1.PilotStop("v6 string capability gate is incomplete")
            if current.get("type") == "object" and current.get(
                "additionalProperties"
            ) is not False:
                raise v1.PilotStop("v6 strict object schema is incomplete")
            stack.extend(current.get("properties", {}).values())
            stack.append(current.get("items"))
            stack.extend(current.get("$defs", {}).values())
            stack.extend(current.get("anyOf", []))
    return {
        stage: v1._canonical_sha256(schema)
        for stage, schema in schemas.items()
    }


def _build_execution_plan(
    replacement: dict[str, Any],
    *,
    base_plan: dict[str, Any],
    predecessor_journals: dict[str, str],
) -> dict[str, Any]:
    execution = copy.deepcopy(base_plan)
    execution.pop("plan_sha256", None)
    execution.update(
        {
            "schema_version": V6_EXECUTION_PLAN_SCHEMA_VERSION,
            "pilot_schema_version": "phase5r_model_pilot_v6",
            "replacement_plan_sha256": replacement["plan_sha256"],
            "predecessor_journal_sha256": copy.deepcopy(predecessor_journals),
            "contract": {
                "analyst_adapter": "one_deterministic_same_ticker_primary_source_v6",
                "analyst_instruction_sha256": v1._canonical_sha256(
                    SOURCE_LOCKED_V6_INSTRUCTIONS
                ),
                "strict_stage_schema_sha256": _schema_profile(),
                "provider_capability_gate": "strict_minLength_one_in_first_accepted_collection_request",
                "provider_response_ids_persisted": False,
                "failed_raw_responses_persisted": False,
            },
        "authorization": {
            "source": "interactive_user_approval",
                "new_independent_model_call_cap": 30,
                "new_independent_usd_cap": "5.00",
                "sdk_max_retries": 0,
                "physical_attempts_per_call": 1,
            },
        }
    )
    execution["boundaries"].update(
        {
            "email_effect": False,
            "no_credential_persistence": True,
            "no_raw_failed_response_persistence": True,
            "no_provider_response_id_persistence": True,
        }
    )
    execution["plan_sha256"] = v1._canonical_sha256(execution)
    return execution


def check_v6_readiness(
    *,
    replacement_plan_path: Path = V6_PLAN_PATH,
    quarantine_root: Path = v1.QUARANTINE_ROOT,
) -> dict[str, Any]:
    """Run all read-only v6 gates without constructing a provider."""

    try:
        replacement = _load_v6_plan(replacement_plan_path)
        predecessors = _validate_terminal_predecessors(replacement)
        policy, contexts, base_plan, strict_audit, sentinels = (
            v1._readiness_components(quarantine_root=quarantine_root)
        )
        execution = _build_execution_plan(
            replacement,
            base_plan=base_plan,
            predecessor_journals=predecessors,
        )
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
        "status": "ready_for_authorized_execution_pending_provider_capability_gate",
        "packet_count": len(contexts),
        "planned_model_calls": len(execution["calls"]),
        "worst_case_reserved_usd": execution["budget"]["worst_case_reserved_usd"],
        "maximum_usd": execution["budget"]["maximum_usd"],
        "replacement_plan_sha256": replacement["plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "strict_audit_sha256": strict_audit["audit_sha256"],
        "policy_file_sha256": policy["file_sha256"],
        "stage_schema_sha256": execution["contract"]["strict_stage_schema_sha256"],
        "daily_monitoring_preserved": sentinels[
            "daily_refresh_launchd_job"
        ]["state"] == "loaded"
        and sentinels["daily_decision_launchd_job"]["state"] == "loaded",
        "shadow_scheduler_absent": sentinels["shadow_scheduler_plist"][
            "state"
        ] == "absent",
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
    authorization = execution.get("authorization")
    if not isinstance(authorization, dict):
        raise v1.PilotStop("v6 execution authorization is invalid")
    receipt = {
        "schema_version": V6_AUTHORIZATION_SCHEMA_VERSION,
        "replacement_plan_sha256": execution["replacement_plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "authorization_source": "interactive_user_approval",
        "new_independent_model_call_cap": authorization.get(
            "new_independent_model_call_cap"
        ),
        "new_independent_usd_cap": authorization.get(
            "new_independent_usd_cap"
        ),
        "email_effect": False,
        "trading": False,
        "broker_or_account_access": False,
        "canonical_influence": False,
        "sdk_max_retries": 0,
        "credential_storage": False,
    }
    receipt["authorization_sha256"] = v1._canonical_sha256(receipt)
    return receipt


def _instructions_for_call(call: dict[str, Any]) -> str:
    if call["stage"] in {"luna_assessment", "terra_assessment"}:
        return SOURCE_LOCKED_V6_INSTRUCTIONS
    return v1._instructions_for_stage(call["stage"])


def _input_for_call(
    call: dict[str, Any],
    context: v1.PacketContext,
    results: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, str]],
) -> dict[str, Any]:
    if call["stage"] in {"luna_assessment", "terra_assessment"}:
        return {
            "pilot_mode": "offline_shadow_noncanonical",
            "source_locked_evidence_view": source_locked_input_view_v6(
                context.runtime_packet
            ),
        }
    return v1._input_for_call(call, context, results, assignments)


def _validate_payload(
    call: dict[str, Any],
    context: v1.PacketContext,
    payload: dict[str, Any],
    results: dict[str, dict[str, Any]],
    assignments: dict[str, dict[str, str]],
) -> dict[str, Any]:
    normalized = (
        hydrate_source_locked_assessment_v6(context.runtime_packet, payload)
        if call["stage"] in {"luna_assessment", "terra_assessment"}
        else payload
    )
    return v1._validate_stage_payload(
        call, context, normalized, results, assignments
    )


def _redacted_provider_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Persist exact metering metadata but never a provider response identifier."""

    response_id = metadata.get("provider_response_id")
    if not isinstance(response_id, str) or not response_id:
        raise v1.PilotStop("provider response ID is missing before redaction")
    required = (
        "transport",
        "model",
        "resolved_model",
        "requested_service_tier",
        "resolved_service_tier",
        "request_timeout_seconds",
        "billing_scope_attestation",
        "client_library_name",
        "client_library_version",
        "python_runtime_version",
        "credential_read",
        "tools_enabled",
        "store",
        "usage",
    )
    if any(key not in metadata for key in required):
        raise v1.PilotStop("provider metadata cannot be safely redacted")
    return {key: copy.deepcopy(metadata[key]) for key in required}


def _assert_v6_execution_root(
    output_root: Path,
    *,
    quarantine_root: Path,
    allow_test_provider: bool,
) -> None:
    if not allow_test_provider and (
        output_root.expanduser().resolve() != V6_OUTPUT_ROOT.resolve()
        or quarantine_root.expanduser().resolve() != v1.QUARANTINE_ROOT.resolve()
    ):
        raise v1.PilotStop("v6 output root is pinned to its separate quarantine")
    if allow_test_provider:
        try:
            quarantine_root.expanduser().resolve().relative_to(v1.ROOT.resolve())
        except ValueError:
            return
        raise v1.PilotStop("v6 fixture quarantine must stay outside the repository")


def execute_model_pilot_v6(
    *,
    provider_factory: Callable[[], ModelProvider],
    explicit_user_authorization: bool,
    replacement_plan_path: Path = V6_PLAN_PATH,
    output_root: Path = V6_OUTPUT_ROOT,
    allow_test_provider: bool = False,
    test_quarantine_root: Path | None = None,
) -> dict[str, Any]:
    """Run the one authorized v6 collection, terminally stopping on failure."""

    if (
        not callable(provider_factory)
        or explicit_user_authorization is not True
        or not isinstance(allow_test_provider, bool)
    ):
        raise v1.PilotStop("v6 execution requires explicit interactive user approval")
    quarantine_root = (
        test_quarantine_root if allow_test_provider else v1.QUARANTINE_ROOT
    )
    if allow_test_provider and test_quarantine_root is None:
        raise v1.PilotStop("v6 fixture execution requires a fixture quarantine")
    readiness = check_v6_readiness(
        replacement_plan_path=replacement_plan_path,
        quarantine_root=quarantine_root,
    )
    if readiness.get("passed") is not True:
        raise v1.PilotStop("v6 readiness is blocked")
    replacement = _load_v6_plan(replacement_plan_path)
    predecessors = _validate_terminal_predecessors(replacement)
    policy, contexts, base_plan, _strict_audit, before_sentinels = (
        v1._readiness_components(quarantine_root=quarantine_root)
    )
    execution = _build_execution_plan(
        replacement,
        base_plan=base_plan,
        predecessor_journals=predecessors,
    )
    if readiness.get("execution_plan_sha256") != execution["plan_sha256"]:
        raise v1.PilotStop("v6 sealed readiness plan changed before execution")
    _assert_v6_execution_root(
        output_root,
        quarantine_root=quarantine_root,
        allow_test_provider=allow_test_provider,
    )
    execution_mode = "test_fixture" if allow_test_provider else "openai_responses_api"
    with v1._pilot_lock(quarantine_root):
        root = v1._validate_output_root(output_root, quarantine_root)
        _write_or_validate(
            root / V6_EXECUTION_PLAN_NAME,
            execution,
            label="v6 execution plan",
        )
        _write_or_validate(
            root / V6_AUTHORIZATION_NAME,
            _authorization_receipt(execution),
            label="v6 authorization receipt",
        )
        assignments, assignments_sha256 = v1._load_or_create_blind_assignments(
            root, execution
        )
        journal_path = root / V6_JOURNAL_NAME
        events = v1._load_journal(journal_path, plan_sha256=execution["plan_sha256"])
        v1._assert_receipt_journal_coherence(
            output_root=root, plan=execution, events=events
        )
        completed = v1._completed_pilot(
            root,
            execution,
            journal_path=journal_path,
            events=events,
            execution_mode=execution_mode,
            prices=policy["prices"],
            allow_test_provider=allow_test_provider,
            allow_redacted_provider_response_id=True,
        )
        if completed is not None:
            return completed
        if any(event["event_kind"] == "pilot_stopped" for event in events):
            raise v1.PilotStop("v6 has a durable stop event and cannot resume or retry")
        if not events:
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="pilot_opened",
                call_id=None,
                details={
                    "maximum_model_calls": execution["budget"][
                        "maximum_physical_model_calls"
                    ],
                    "maximum_usd": execution["budget"]["maximum_usd"],
                    "provider": execution_mode,
                    "sdk_max_retries": 0,
                },
            )
        v1._recover_or_stop_pending(
            output_root=root,
            plan=execution,
            events=events,
            prices=policy["prices"],
            allow_test_provider=allow_test_provider,
            allow_redacted_provider_response_id=True,
        )
        contexts_by_id = {context.packet_id: context for context in contexts}
        results: dict[str, dict[str, Any]] = {}
        for call in execution["calls"]:
            terminal = v1._terminal_event(events, call["call_id"])
            if terminal is not None:
                if terminal["event_kind"] != "call_completed":
                    raise v1.PilotStop("v6 call is terminal and cannot retry")
                receipt = v1._validate_receipt(
                    v1._receipt_path(root, call["call_id"]),
                    call=call,
                    plan_sha256=execution["plan_sha256"],
                    prices=policy["prices"],
                    allow_test_provider=allow_test_provider,
                    allow_redacted_provider_response_id=True,
                )
                context = contexts_by_id[call["packet_id"]]
                v1._validate_stage_payload(
                    call, context, receipt["payload"], results, assignments
                )
                results[call["call_id"]] = v1._result_from_receipt(receipt)
                continue
            if v1._reserved_event(events, call["call_id"]) is not None:
                raise v1.PilotStop("v6 has an unrecovered reservation")
            if any(dependency not in results for dependency in call["dependencies"]):
                raise v1.PilotStop("v6 call dependency is incomplete")
            context = contexts_by_id[call["packet_id"]]
            schema = strict_schema_for_stage_v6(call["stage"])
            instructions = _instructions_for_call(call)
            input_payload = _input_for_call(call, context, results, assignments)
            envelope_bytes = v1._request_envelope_bytes(
                call,
                schema=schema,
                instructions=instructions,
                input_payload=input_payload,
            )
            if envelope_bytes > v1.MAXIMUM_REQUEST_ENVELOPE_BYTES:
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={
                        "reason": "request_envelope_exceeded",
                        "call_id": call["call_id"],
                        "request_envelope_bytes": envelope_bytes,
                    },
                )
                raise v1.PilotStop("v6 request envelope exceeds its byte cap")
            binding: dict[str, Any] = {
                "call_id": call["call_id"],
                "packet_id": call["packet_id"],
                "stage": call["stage"],
                "role": call["role"],
                "model": call["model"],
                "reasoning_effort": call["reasoning_effort"],
                "service_tier": "default",
                "request_timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS,
                "billing_scope_attestation": "global_standard_no_regional_processing",
                "schema_sha256": v1._canonical_sha256(schema),
                "instructions_sha256": v1._canonical_sha256(instructions),
                "input_sha256": v1._canonical_sha256(input_payload),
                "dependency_result_sha256s": {
                    dependency: v1._canonical_sha256(results[dependency]["payload"])
                    for dependency in call["dependencies"]
                },
                "request_envelope_bytes": envelope_bytes,
                "store": False,
                "tools": [],
                "sdk_max_retries": 0,
            }
            if call["stage"] in {"sol_committee", "sol_critic"}:
                binding["blind_mapping_sha256"] = v1._canonical_sha256(
                    v1._blind_mapping(call["packet_id"], assignments)
                )
            v1._enforce_runtime_safety(
                journal_path=journal_path,
                events=events,
                plan_sha256=execution["plan_sha256"],
                call_id=call["call_id"],
                opening_sentinels=before_sentinels,
                corpus_root=v1.CORPUS_ROOT,
                quarantine_root=quarantine_root,
            )
            try:
                provider = provider_factory()
                if isinstance(provider, OpenAIResponsesProvider):
                    provider.max_output_tokens = call["maximum_output_tokens"]
                v1._strict_provider(
                    provider,
                    allow_test_provider=allow_test_provider,
                    maximum_output_tokens=call["maximum_output_tokens"],
                )
                exact_input_tokens = provider.count_input_tokens(
                    role=call["role"],
                    model=call["model"],
                    reasoning_effort=call["reasoning_effort"],
                    schema=copy.deepcopy(schema),
                    instructions=instructions,
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
                        "runtime_safety_issue": v1._runtime_safety_issue(
                            opening_sentinels=before_sentinels,
                            corpus_root=v1.CORPUS_ROOT,
                            quarantine_root=quarantine_root,
                        ),
                    },
                )
                raise v1.PilotStop("v6 provider or capability gate failed pre-inference") from exc
            if (
                type(exact_input_tokens) is not int
                or exact_input_tokens < 0
                or exact_input_tokens > call["maximum_input_tokens"]
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
                raise v1.PilotStop("v6 exact input token count exceeds reservation")
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
            reservation = v1._decimal(call["reservation_usd"], label="v6 reservation")
            if (
                charged["used_model_calls"] + 1
                > execution["budget"]["maximum_physical_model_calls"]
                or charged["charged_usd"] + reservation
                > v1._decimal(
                    execution["budget"]["maximum_usd"],
                    label="v6 execution USD cap",
                )
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
                raise v1.PilotStop("v6 pre-inference budget gate failed")
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
            # This is deliberately a finite, content-free state label.  The
            # terminal journal cannot retain a failed payload, response ID, or
            # exception message, but a future forensic review still needs to
            # distinguish a provider method that never returned from a local
            # check after a parsed ProviderResult was available.
            result_received = False
            failure_phase = "provider_result_not_returned"
            try:
                result = provider.generate(
                    role=call["role"],
                    model=call["model"],
                    reasoning_effort=call["reasoning_effort"],
                    schema=copy.deepcopy(schema),
                    instructions=instructions,
                    input_payload=copy.deepcopy(input_payload),
                )
                result_received = True
                failure_phase = "post_parse_provider_result_type_check"
                if not isinstance(result, ProviderResult):
                    raise v1.PilotStop("v6 provider returned an invalid result")
                failure_phase = "post_parse_contract_validation"
                payload = _validate_payload(
                    call, context, result.payload, results, assignments
                )
                failure_phase = "post_parse_metering_validation"
                metered = v1._metered_usage(
                    call,
                    result.metadata,
                    policy["prices"],
                    allow_test_provider=allow_test_provider,
                )
                failure_phase = "post_parse_usage_reconciliation"
                if metered["total_input_tokens"] != exact_input_tokens:
                    raise v1.PilotStop("v6 provider usage differs from preflight")
                receipt: dict[str, Any] = {
                    "schema_version": v1.RECEIPT_SCHEMA_VERSION,
                    "plan_sha256": execution["plan_sha256"],
                    "call_id": call["call_id"],
                    "request_binding": binding,
                    "request_binding_sha256": binding_sha256,
                    "payload": copy.deepcopy(payload),
                    "payload_sha256": v1._canonical_sha256(payload),
                    "metered_usage": metered,
                    "canonical_effect": False,
                    "email_effect": False,
                }
                failure_phase = "post_parse_provider_metadata_redaction"
                receipt["provider_metadata"] = _redacted_provider_metadata(
                    result.metadata
                )
                failure_phase = "post_parse_receipt_persistence"
                receipt["receipt_sha256"] = v1._canonical_sha256(receipt)
                v1._write_json_exclusive(
                    v1._receipt_path(root, call["call_id"]), receipt
                )
            except Exception as exc:
                details: dict[str, Any] = {
                    "charged_reservation_usd": call["reservation_usd"],
                    "failure_phase": failure_phase,
                    "failure_type": type(exc).__name__,
                    "provider_failure_code": safe_provider_failure_code(exc),
                    "retry_allowed": False,
                    "runtime_safety_issue": v1._runtime_safety_issue(
                        opening_sentinels=before_sentinels,
                        corpus_root=v1.CORPUS_ROOT,
                        quarantine_root=quarantine_root,
                    ),
                }
                if isinstance(exc, ContractError):
                    details["redacted_contract_diagnostic"] = v1._redacted_contract_diagnostic(
                        call, exc
                    )
                event_kind = "call_failed" if result_received else "call_outcome_unknown"
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
                raise v1.PilotStop(f"v6 stopped at {call['call_id']}") from exc
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="call_completed",
                call_id=call["call_id"],
                details={
                    "actual_cost_usd": metered["cost_usd"],
                    "metered_usage": metered,
                    "receipt_sha256": receipt["receipt_sha256"],
                    "recovered_after_interruption": False,
                },
            )
            results[call["call_id"]] = v1._result_from_receipt(receipt)
            v1._enforce_runtime_safety(
                journal_path=journal_path,
                events=events,
                plan_sha256=execution["plan_sha256"],
                call_id=call["call_id"],
                opening_sentinels=before_sentinels,
                corpus_root=v1.CORPUS_ROOT,
                quarantine_root=quarantine_root,
            )
        if len(results) != 30:
            raise v1.PilotStop("v6 ended without all thirty results")
        charged = v1._validate_complete_call_audit(
            output_root=root,
            plan=execution,
            events=events,
            execution_mode=execution_mode,
            prices=policy["prices"],
            allow_test_provider=allow_test_provider,
            require_model_calls_completed=False,
            allow_redacted_provider_response_id=True,
        )
        v1._append_event(
            journal_path,
            events,
            plan_sha256=execution["plan_sha256"],
            event_kind="model_calls_completed",
            call_id=None,
            details={
                "physical_model_calls": charged["used_model_calls"],
                "charged_usd": v1._decimal_text(charged["charged_usd"]),
                "promotion_eligible": False,
            },
        )
        charged = v1._validate_complete_call_audit(
            output_root=root,
            plan=execution,
            events=events,
            execution_mode=execution_mode,
            prices=policy["prices"],
            allow_test_provider=allow_test_provider,
            require_model_calls_completed=True,
            allow_redacted_provider_response_id=True,
        )
        return v1._publish_final_artifacts(
            output_root=root,
            contexts=contexts,
            plan=execution,
            results=results,
            charged=charged,
            before_sentinels=before_sentinels,
            execution_mode=execution_mode,
            blind_assignments=assignments,
            blind_assignment_file_sha256=assignments_sha256,
            journal_binding=v1._journal_binding(journal_path, events),
            corpus_root=v1.CORPUS_ROOT,
            quarantine_root=quarantine_root,
        )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(check_v6_readiness(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
