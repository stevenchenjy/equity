#!/usr/bin/env python3
"""Dedicated, separately-authorized executor for the one-call Phase 5R v5 pilot.

v5 stays inert until an authenticated provider is injected and a new explicit
user authorization is supplied.  Its source-locked adapter deterministically
adds the sole primary source, identity, and safety fields before the unchanged
closed assessment validator runs.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from phase5r_llm_provider import ModelProvider, ProviderResult
from phase5r_model_pilot_v5_contract import (
    SOURCE_LOCKED_APPENDIX,
    SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS,
    _single_primary_source,
    hydrate_source_locked_assessment,
    source_locked_assessment_schema,
)
import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v3 as v3
import run_phase5r_model_pilot_v4 as v4


V5_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_replacement_plan_v5"
V5_EXECUTION_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_execution_plan_v5"
V5_AUTHORIZATION_SCHEMA_VERSION = "phase5r_model_pilot_v5_authorization_v1"
V5_RECEIPT_SCHEMA_VERSION = "phase5r_model_pilot_v5_call_receipt_v1"
V5_COMPLETION_SCHEMA_VERSION = "phase5r_model_pilot_v5_completion_v1"

V5_PLAN_PATH = (
    v1.ROOT / "08_reviews" / "phase5r_model_pilot" / "replacement_v5"
    / "phase5r_model_pilot_v5_plan.json"
)
V4_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v4"
V5_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v5"
V5_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v5_execution_plan.json"
V5_AUTHORIZATION_NAME = "phase5r_model_pilot_v5_authorization.json"
V5_JOURNAL_NAME = "phase5r_model_pilot_v5_journal.jsonl"
V5_COMPLETION_NAME = "phase5r_model_pilot_v5_completion.json"

_PRIOR_CHARGED_USD = Decimal("0.595922")
_PRIOR_CHARGED_CALLS = 17
_V5_CALL_COUNT = 1
_V5_MAXIMUM_RESERVATION_USD = Decimal("0.05808")
_CUMULATIVE_CALL_CAP = 30
_CUMULATIVE_USD_CAP = Decimal("5")
_READY_STATUS = "ready_for_explicit_user_authorization_execution_prohibited"


def _load_v5_plan(path: Path = V5_PLAN_PATH) -> dict[str, Any]:
    plan = v1._read_json_object(path, label="replacement v5 pilot plan")
    claimed = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if (
        plan.get("schema_version") != V5_PLAN_SCHEMA_VERSION
        or v1._canonical_sha256(unsigned) != claimed
        or plan.get("status") != _READY_STATUS
        or plan.get("execution_prohibited") is not True
    ):
        raise v1.PilotStop("replacement v5 plan is not a sealed ready plan")
    budget = plan.get("budget")
    boundaries = plan.get("boundaries")
    layout = plan.get("call_layout")
    if (
        not isinstance(budget, dict)
        or budget.get("charged_or_reserved_before_v5_usd")
        != v1._decimal_text(_PRIOR_CHARGED_USD)
        or budget.get("charged_model_calls_before_v5") != _PRIOR_CHARGED_CALLS
        or budget.get("maximum_new_model_calls") != _V5_CALL_COUNT
        or budget.get("maximum_new_reservation_usd")
        != v1._decimal_text(_V5_MAXIMUM_RESERVATION_USD)
        or not isinstance(boundaries, dict)
        or boundaries.get("shadow_only") is not True
        or any(
            boundaries.get(field) is not False
            for field in (
                "email_effect",
                "canonical_effect",
                "automatic_action_allowed",
                "broker_used",
                "order_code_created",
            )
        )
        or boundaries.get("store") is not False
        or boundaries.get("tools") != []
        or boundaries.get("sdk_max_retries") != 0
        or not isinstance(layout, list)
        or layout
        != [
            {
                "stage": "luna_assessment",
                "model": "gpt-5.6-luna",
                "maximum_physical_attempts": 1,
                "retry_count": 0,
                "reservation_usd": "0.05808",
            }
        ]
    ):
        raise v1.PilotStop("replacement v5 budget or safety boundary is invalid")
    change = plan.get("diagnostic_change")
    if (
        not isinstance(change, dict)
        or change.get("validator_or_schema_relaxation") is not False
        or change.get("exclude_v4_terminal_packet") is not True
        or change.get("forbid_calculated_evidence") is not True
        or change.get("adapter")
        != "injects the sole same-ticker primary source, immutable identity, empty calculation list, and false safety flags"
    ):
        raise v1.PilotStop("replacement v5 diagnostic change is invalid")
    validation = plan.get("local_validation")
    if (
        not isinstance(validation, dict)
        or validation.get("v5_contract_regression") != "passed"
        or validation.get("v5_executor_regression") != "passed_targeted_offline"
        or validation.get("v5_check_entrypoint") != "passed"
        or validation.get("complete_phase5r_suite")
        != "passed_complete_phase5r_suite_after_v5_executor"
        or validation.get("new_api_calls_during_planning") is not False
    ):
        raise v1.PilotStop("replacement v5 local validation is incomplete")
    return plan


def _validate_v4_state(source_v4: dict[str, Any]) -> dict[str, str]:
    plan = v4._load_v4_plan()
    execution_path = V4_OUTPUT_ROOT / v4.V4_EXECUTION_PLAN_NAME
    journal_path = V4_OUTPUT_ROOT / v4.V4_JOURNAL_NAME
    execution = v1._read_json_object(execution_path, label="v4 execution plan")
    unsigned = dict(execution)
    claimed = unsigned.pop("plan_sha256", None)
    if (
        plan.get("plan_sha256") != source_v4.get("replacement_plan_sha256")
        or execution.get("schema_version") != v4.V4_EXECUTION_PLAN_SCHEMA_VERSION
        or v1._canonical_sha256(unsigned) != claimed
        or claimed != source_v4.get("execution_plan_sha256")
        or v1._sha256_file(journal_path) != source_v4.get("journal_file_sha256")
        or source_v4.get("action") != "preserve_terminal_no_resume_no_retry"
    ):
        raise v1.PilotStop("replacement v5 is not bound to terminal v4")
    events = v1._load_journal(journal_path, plan_sha256=claimed)
    v1._assert_receipt_journal_coherence(
        output_root=V4_OUTPUT_ROOT, plan=execution, events=events
    )
    charged = v4._charged_budget(execution, events)
    failed = [event for event in events if event["event_kind"] == "call_failed"]
    calls_by_id = {call["call_id"]: call for call in execution["calls"]}
    receipts = list((V4_OUTPUT_ROOT / v1.RESPONSE_DIRECTORY_NAME).glob("*.json"))
    if (
        len(events) != 5
        or charged["used_model_calls"] != 1
        or charged["charged_usd"] != _V5_MAXIMUM_RESERVATION_USD
        or receipts
        or (V4_OUTPUT_ROOT / v4.V4_COMPLETION_NAME).exists()
        or len(failed) != 1
        or failed[0].get("call_id") != source_v4.get("terminal_call_id")
        or failed[0].get("call_id") not in calls_by_id
        or failed[0].get("details", {}).get("redacted_contract_diagnostic", {}).get(
            "code"
        )
        != source_v4.get("finite_failure_code")
    ):
        raise v1.PilotStop("v4 terminal state or charge changed")
    return {
        "execution_plan_sha256": claimed,
        "journal_file_sha256": v1._sha256_file(journal_path),
        "terminal_call_id": str(failed[0]["call_id"]),
        "terminal_packet_id": str(calls_by_id[str(failed[0]["call_id"])]["packet_id"]),
    }


def _selected_context(
    plan: dict[str, Any], contexts: list[v1.PacketContext], v4_state: dict[str, str]
) -> v1.PacketContext:
    packet_id = plan.get("precommitted_packet_id")
    by_id = {context.packet_id: context for context in contexts}
    failed_packet_id = v4_state["terminal_packet_id"]
    if (
        not isinstance(packet_id, str)
        or packet_id not in by_id
        or packet_id == failed_packet_id
    ):
        raise v1.PilotStop("replacement v5 packet selection is invalid")
    context = by_id[packet_id]
    _single_primary_source(context.runtime_packet)
    return context


def _call(context: v1.PacketContext, prices: dict[str, dict[str, Decimal]]) -> dict[str, Any]:
    return {
        "call_id": v1._call_id(context.packet_id, "luna_assessment"),
        "packet_id": context.packet_id,
        "ticker": context.ticker,
        "stage": "luna_assessment",
        "role": v1.ROLE_BY_STAGE["luna_assessment"],
        "model": v1.MODEL_BY_STAGE["luna_assessment"],
        "reasoning_effort": v1.EFFORT_BY_STAGE["luna_assessment"],
        "dependencies": [],
        "maximum_input_tokens": v1.MAXIMUM_INPUT_TOKENS,
        "maximum_output_tokens": v1.MAXIMUM_OUTPUT_TOKENS,
        "reservation_usd": v1._decimal_text(
            v1._reservation_usd(v1.MODEL_BY_STAGE["luna_assessment"], prices)
        ),
    }


def _build_execution_plan(
    replacement: dict[str, Any],
    *,
    readiness: dict[str, str],
    context: v1.PacketContext,
    policy: dict[str, Any],
    v1_state: dict[str, str],
    v2_state: dict[str, str],
    v3_state: dict[str, str],
    v4_state: dict[str, str],
) -> dict[str, Any]:
    call = _call(context, policy["prices"])
    if call["reservation_usd"] != v1._decimal_text(_V5_MAXIMUM_RESERVATION_USD):
        raise v1.PilotStop("replacement v5 reservation changed")
    execution: dict[str, Any] = {
        "schema_version": V5_EXECUTION_PLAN_SCHEMA_VERSION,
        "replacement_plan_sha256": replacement["plan_sha256"],
        "source_journals": {
            "v1": v1_state["journal_file_sha256"],
            "v2": v2_state["journal_file_sha256"],
            "v3": v3_state["journal_file_sha256"],
            "v4": v4_state["journal_file_sha256"],
        },
        "strict_audit_sha256": readiness["strict_audit_sha256"],
        "policy_file_sha256": readiness["policy_file_sha256"],
        "opening_sentinel_sha256": v1._canonical_sha256(v1._sentinel_snapshot()),
        "packet_id": context.packet_id,
        "assessment_view_sha256": v1._canonical_sha256(context.assessment_view),
        "source_locked_assessment_schema_sha256": v1._canonical_sha256(
            source_locked_assessment_schema()
        ),
        "source_locked_instructions_sha256": v1._canonical_sha256(
            SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS
        ),
        "source_locked_appendix_sha256": v1._canonical_sha256(
            list(SOURCE_LOCKED_APPENDIX)
        ),
        "call": call,
        "budget": {
            "prior_charged_model_calls": _PRIOR_CHARGED_CALLS,
            "prior_charged_usd": v1._decimal_text(_PRIOR_CHARGED_USD),
            "maximum_new_model_calls": _V5_CALL_COUNT,
            "maximum_new_reservation_usd": v1._decimal_text(
                _V5_MAXIMUM_RESERVATION_USD
            ),
            "cumulative_maximum_model_calls": _CUMULATIVE_CALL_CAP,
            "cumulative_maximum_usd": v1._decimal_text(_CUMULATIVE_USD_CAP),
            "maximum_input_tokens_per_call": v1.MAXIMUM_INPUT_TOKENS,
            "maximum_output_tokens_per_call": v1.MAXIMUM_OUTPUT_TOKENS,
            "maximum_request_envelope_bytes": v1.MAXIMUM_REQUEST_ENVELOPE_BYTES,
            "sdk_max_retries": 0,
        },
        "boundaries": {
            "shadow_only": True,
            "canonical_effect": False,
            "email_effect": False,
            "automatic_action_allowed": False,
            "broker_used": False,
            "order_code_created": False,
            "store": False,
            "tools": [],
            "retry_count": 0,
        },
    }
    execution["plan_sha256"] = v1._canonical_sha256(execution)
    return execution


def check_v5_readiness(*, replacement_plan_path: Path = V5_PLAN_PATH) -> dict[str, Any]:
    """Verify v5 locally without constructing a provider or writing files."""

    replacement = _load_v5_plan(replacement_plan_path)
    v1_state = v3._validate_v1_state(replacement["source_v1"])
    v2_state = v3._validate_v2_state(replacement["source_v2"])
    v3_state = v4._validate_v3_state(replacement["source_v3"])
    v4_state = _validate_v4_state(replacement["source_v4"])
    readiness = v1.check_pilot_readiness()
    if readiness.get("passed") is not True:
        raise v1.PilotStop("strict pilot corpus or runtime readiness failed")
    policy, contexts, _unused, _audit, _sentinels = v1._readiness_components()
    context = _selected_context(replacement, contexts, v4_state)
    execution = _build_execution_plan(
        replacement,
        readiness=readiness,
        context=context,
        policy=policy,
        v1_state=v1_state,
        v2_state=v2_state,
        v3_state=v3_state,
        v4_state=v4_state,
    )
    return {
        "passed": True,
        "provider_constructed": False,
        "network_used": False,
        "files_written": False,
        "model_calls": 0,
        "replacement_plan_sha256": replacement["plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "strict_audit_sha256": readiness["strict_audit_sha256"],
        "policy_file_sha256": readiness["policy_file_sha256"],
        "new_model_calls": 1,
        "new_reserved_usd": v1._decimal_text(_V5_MAXIMUM_RESERVATION_USD),
        "cumulative_reserved_usd": v1._decimal_text(
            _PRIOR_CHARGED_USD + _V5_MAXIMUM_RESERVATION_USD
        ),
        "canonical_effect": False,
        "email_effect": False,
        "automatic_action_allowed": False,
    }


def _charged_budget(execution: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    call = execution["call"]
    if v1._reserved_event(events, call["call_id"]) is None:
        return {"used_model_calls": 0, "charged_usd": Decimal(0)}
    terminal = v1._terminal_event(events, call["call_id"])
    charged = (
        v1._decimal(terminal["details"]["actual_cost_usd"], label="completed cost")
        if terminal is not None and terminal["event_kind"] == "call_completed"
        else v1._decimal(call["reservation_usd"], label="v5 reservation")
    )
    if (
        charged > _V5_MAXIMUM_RESERVATION_USD
        or _PRIOR_CHARGED_USD + charged > _CUMULATIVE_USD_CAP
        or _PRIOR_CHARGED_CALLS + 1 > _CUMULATIVE_CALL_CAP
    ):
        raise v1.PilotStop("replacement v5 cumulative budget exceeded")
    return {"used_model_calls": 1, "charged_usd": charged}


def _write_or_validate(path: Path, payload: dict[str, Any], *, label: str) -> None:
    if path.exists():
        if v1._read_json_object(path, label=label) != payload:
            raise v1.PilotStop(f"existing {label} differs from sealed value")
        return
    v1._write_json_exclusive(path, payload)


def _authorization_receipt(execution: dict[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": V5_AUTHORIZATION_SCHEMA_VERSION,
        "replacement_plan_sha256": execution["replacement_plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"],
        "authorization_source": "interactive_user_approval",
        "scope": {
            "maximum_new_model_calls": 1,
            "maximum_new_reservation_usd": v1._decimal_text(
                _V5_MAXIMUM_RESERVATION_USD
            ),
            "shadow_only": True,
            "email_effect": False,
            "canonical_effect": False,
            "automatic_action_allowed": False,
            "broker_used": False,
        },
    }
    receipt["authorization_sha256"] = v1._canonical_sha256(receipt)
    return receipt


def _completion(
    output_root: Path, execution: dict[str, Any]
) -> dict[str, Any] | None:
    path = output_root / V5_COMPLETION_NAME
    if not path.exists():
        return None
    completion = v1._read_json_object(path, label="v5 completion")
    unsigned = dict(completion)
    claimed = unsigned.pop("completion_sha256", None)
    call_id = execution["call"]["call_id"]
    receipts = completion.get("receipt_file_sha256")
    if (
        completion.get("schema_version") != V5_COMPLETION_SCHEMA_VERSION
        or completion.get("execution_plan_sha256") != execution["plan_sha256"]
        or completion.get("physical_model_calls") != 1
        or completion.get("canonical_effect") is not False
        or completion.get("email_effect") is not False
        or completion.get("automatic_action_allowed") is not False
        or completion.get("broker_used") is not False
        or not isinstance(receipts, dict)
        or set(receipts) != {call_id}
        or v1._sha256_file(
            output_root / v1.RESPONSE_DIRECTORY_NAME / f"{call_id}.json"
        )
        != receipts[call_id]
        or v1._canonical_sha256(unsigned) != claimed
    ):
        raise v1.PilotStop("existing v5 completion is invalid")
    return completion


def execute_model_pilot_v5(
    *,
    provider_factory: Callable[[], ModelProvider],
    explicit_user_authorization: bool,
    replacement_plan_path: Path = V5_PLAN_PATH,
    output_root: Path = V5_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Run the single v5 call once; all started outcomes are terminal."""

    if not callable(provider_factory) or explicit_user_authorization is not True:
        raise v1.PilotStop("v5 execution requires explicit interactive user approval")
    report = check_v5_readiness(replacement_plan_path=replacement_plan_path)
    replacement = _load_v5_plan(replacement_plan_path)
    v1_state = v3._validate_v1_state(replacement["source_v1"])
    v2_state = v3._validate_v2_state(replacement["source_v2"])
    v3_state = v4._validate_v3_state(replacement["source_v3"])
    v4_state = _validate_v4_state(replacement["source_v4"])
    policy, contexts, _unused, _audit, sentinels = v1._readiness_components()
    context = _selected_context(replacement, contexts, v4_state)
    execution = _build_execution_plan(
        replacement,
        readiness={
            "strict_audit_sha256": report["strict_audit_sha256"],
            "policy_file_sha256": report["policy_file_sha256"],
        },
        context=context,
        policy=policy,
        v1_state=v1_state,
        v2_state=v2_state,
        v3_state=v3_state,
        v4_state=v4_state,
    )
    if output_root.expanduser().resolve() != V5_OUTPUT_ROOT.resolve():
        raise v1.PilotStop("v5 output root is pinned to its separate quarantine")
    with v1._pilot_lock(v1.QUARANTINE_ROOT):
        root = v1._validate_output_root(output_root, v1.QUARANTINE_ROOT)
        _write_or_validate(
            root / V5_EXECUTION_PLAN_NAME, execution, label="v5 execution plan"
        )
        _write_or_validate(
            root / V5_AUTHORIZATION_NAME,
            _authorization_receipt(execution),
            label="v5 authorization receipt",
        )
        completed = _completion(root, execution)
        if completed is not None:
            return completed
        journal_path = root / V5_JOURNAL_NAME
        events = v1._load_journal(journal_path, plan_sha256=execution["plan_sha256"])
        v1._assert_receipt_journal_coherence(
            output_root=root, plan={"calls": [execution["call"]]}, events=events
        )
        if events:
            raise v1.PilotStop("v5 has durable journal state and cannot resume or retry")
        call = execution["call"]
        v1._append_event(
            journal_path,
            events,
            plan_sha256=execution["plan_sha256"],
            event_kind="pilot_opened",
            call_id=None,
            details={
                "maximum_new_model_calls": 1,
                "maximum_new_reservation_usd": v1._decimal_text(
                    _V5_MAXIMUM_RESERVATION_USD
                ),
                "prior_charged_model_calls": _PRIOR_CHARGED_CALLS,
                "prior_charged_usd": v1._decimal_text(_PRIOR_CHARGED_USD),
                "provider": "openai_responses_api",
                "sdk_max_retries": 0,
                "email_effect": False,
                "canonical_effect": False,
            },
        )
        schema = source_locked_assessment_schema()
        input_payload = v1._input_for_call(call, context, {}, {})
        envelope = v1._request_envelope_bytes(
            call,
            schema=schema,
            instructions=SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS,
            input_payload=input_payload,
        )
        if envelope > v1.MAXIMUM_REQUEST_ENVELOPE_BYTES:
            raise v1.PilotStop("v5 request envelope exceeds its byte cap")
        v1._assert_runtime_safety(
            opening_sentinels=sentinels,
            corpus_root=v1.CORPUS_ROOT,
            quarantine_root=v1.QUARANTINE_ROOT,
        )
        try:
            provider = provider_factory()
            v1._strict_provider(provider, allow_test_provider=False)
            exact_tokens = provider.count_input_tokens(
                role=call["role"],
                model=call["model"],
                reasoning_effort=call["reasoning_effort"],
                schema=copy.deepcopy(schema),
                instructions=SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS,
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
                    "model_calls_charged": 0,
                },
            )
            raise v1.PilotStop("v5 provider or input count preflight failed") from exc
        if (
            type(exact_tokens) is not int
            or exact_tokens < 0
            or exact_tokens > call["maximum_input_tokens"]
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
            raise v1.PilotStop("v5 exact input token count exceeds reservation")
        binding = {
            "call_id": call["call_id"],
            "packet_id": call["packet_id"],
            "stage": call["stage"],
            "role": call["role"],
            "model": call["model"],
            "reasoning_effort": call["reasoning_effort"],
            "schema_sha256": v1._canonical_sha256(schema),
            "instructions_sha256": v1._canonical_sha256(
                SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS
            ),
            "input_sha256": v1._canonical_sha256(input_payload),
            "request_envelope_bytes": envelope,
            "exact_input_tokens": exact_tokens,
            "store": False,
            "tools": [],
            "request_timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS,
            "sdk_max_retries": 0,
        }
        binding_sha256 = v1._canonical_sha256(binding)
        v1._append_event(
            journal_path,
            events,
            plan_sha256=execution["plan_sha256"],
            event_kind="input_count_completed",
            call_id=call["call_id"],
            details={
                "request_binding_sha256": binding_sha256,
                "exact_input_tokens": exact_tokens,
                "model_inference_started": False,
            },
        )
        v1._assert_runtime_safety(
            opening_sentinels=sentinels,
            corpus_root=v1.CORPUS_ROOT,
            quarantine_root=v1.QUARANTINE_ROOT,
        )
        charged = _charged_budget(execution, events)
        reservation = v1._decimal(call["reservation_usd"], label="v5 reservation")
        if (
            charged["used_model_calls"] + 1 > 1
            or _PRIOR_CHARGED_USD + charged["charged_usd"] + reservation
            > _CUMULATIVE_USD_CAP
        ):
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="pilot_stopped",
                call_id=None,
                details={
                    "reason": "pre_inference_cumulative_budget_gate_failed",
                    "call_id": call["call_id"],
                },
            )
            raise v1.PilotStop("v5 pre-inference cumulative budget gate failed")
        v1._append_event(
            journal_path,
            events,
            plan_sha256=execution["plan_sha256"],
            event_kind="call_reserved",
            call_id=call["call_id"],
            details={
                "request_binding_sha256": binding_sha256,
                "reservation_usd": call["reservation_usd"],
                "provider_constructed": True,
                "sdk_max_retries": 0,
                "maximum_physical_attempts": 1,
            },
        )
        result_received = False
        try:
            result = provider.generate(
                role=call["role"],
                model=call["model"],
                reasoning_effort=call["reasoning_effort"],
                schema=copy.deepcopy(schema),
                instructions=SOURCE_LOCKED_ASSESSMENT_INSTRUCTIONS,
                input_payload=copy.deepcopy(input_payload),
            )
            result_received = True
            if not isinstance(result, ProviderResult):
                raise v1.PilotStop("v5 provider returned an invalid result")
            payload = hydrate_source_locked_assessment(context.runtime_packet, result.payload)
            v1._validate_assessment(context, payload)
            usage = v1._metered_usage(
                call, result.metadata, policy["prices"], allow_test_provider=False
            )
            if usage["total_input_tokens"] != exact_tokens:
                raise v1.PilotStop("v5 provider usage differs from preflight count")
            receipt: dict[str, Any] = {
                "schema_version": V5_RECEIPT_SCHEMA_VERSION,
                "execution_plan_sha256": execution["plan_sha256"],
                "call_id": call["call_id"],
                "request_binding_sha256": binding_sha256,
                "payload": copy.deepcopy(payload),
                "payload_sha256": v1._canonical_sha256(payload),
                "citation_hashes": "deterministically_injected_from_sole_primary_source",
                "provider_metadata": v4._redacted_provider_metadata(result.metadata),
                "metered_usage": usage,
                "canonical_effect": False,
                "email_effect": False,
                "automatic_action_allowed": False,
            }
            receipt["receipt_sha256"] = v1._canonical_sha256(receipt)
            v1._write_json_exclusive(
                root / v1.RESPONSE_DIRECTORY_NAME / f"{call['call_id']}.json",
                receipt,
            )
        except Exception as exc:
            details: dict[str, Any] = {
                "charged_reservation_usd": call["reservation_usd"],
                "failure_type": type(exc).__name__,
                "retry_allowed": False,
            }
            if isinstance(exc, v1.ContractError):
                details["redacted_contract_diagnostic"] = v1._redacted_contract_diagnostic(
                    call, exc
                )
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="call_failed" if result_received else "call_outcome_unknown",
                call_id=call["call_id"],
                details=details,
            )
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="pilot_stopped",
                call_id=None,
                details={"reason": "call_failed", "call_id": call["call_id"]},
            )
            raise v1.PilotStop(f"v5 stopped at {call['call_id']}") from exc
        v1._append_event(
            journal_path,
            events,
            plan_sha256=execution["plan_sha256"],
            event_kind="call_completed",
            call_id=call["call_id"],
            details={
                "actual_cost_usd": usage["cost_usd"],
                "metered_usage": usage,
                "receipt_sha256": receipt["receipt_sha256"],
            },
        )
        v1._assert_runtime_safety(
            opening_sentinels=sentinels,
            corpus_root=v1.CORPUS_ROOT,
            quarantine_root=v1.QUARANTINE_ROOT,
        )
        charged = _charged_budget(execution, events)
        completion: dict[str, Any] = {
            "schema_version": V5_COMPLETION_SCHEMA_VERSION,
            "execution_plan_sha256": execution["plan_sha256"],
            "physical_model_calls": 1,
            "prior_charged_usd": v1._decimal_text(_PRIOR_CHARGED_USD),
            "v5_charged_usd": v1._decimal_text(charged["charged_usd"]),
            "cumulative_charged_usd": v1._decimal_text(
                _PRIOR_CHARGED_USD + charged["charged_usd"]
            ),
            "canonical_effect": False,
            "email_effect": False,
            "automatic_action_allowed": False,
            "broker_used": False,
            "receipt_file_sha256": {
                call["call_id"]: v1._sha256_file(
                    root / v1.RESPONSE_DIRECTORY_NAME / f"{call['call_id']}.json"
                )
            },
        }
        completion["completion_sha256"] = v1._canonical_sha256(completion)
        v1._write_json_exclusive(root / V5_COMPLETION_NAME, completion)
        return completion


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(check_v5_readiness(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
