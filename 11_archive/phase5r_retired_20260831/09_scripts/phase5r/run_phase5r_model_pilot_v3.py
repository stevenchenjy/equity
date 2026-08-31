#!/usr/bin/env python3
"""Dedicated, separately-authorized executor for the Phase 5R v3 pilot.

The module is inert by default: its CLI performs only local read-only checks.
Execution requires an injected, already-authenticated provider and a fresh
explicit approval.  It cannot email, trade, write canonical state, retry, or
resume a stopped pilot.
"""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from phase5r_llm_provider import ModelProvider, ProviderResult
from phase5r_model_pilot_v3_prompt import (
    CITATION_BINDING_APPENDIX,
    assessment_instructions,
)
import run_phase5r_model_pilot as v1


V3_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_replacement_plan_v3"
V3_EXECUTION_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_execution_plan_v3"
V3_AUTHORIZATION_SCHEMA_VERSION = "phase5r_model_pilot_v3_authorization_v1"
V3_RECEIPT_SCHEMA_VERSION = "phase5r_model_pilot_v3_call_receipt_v1"
V3_COMPLETION_SCHEMA_VERSION = "phase5r_model_pilot_v3_completion_v1"
V3_BLIND_ASSIGNMENT_SCHEMA_VERSION = "phase5r_model_pilot_v3_blind_assignment_v1"

V3_PLAN_PATH = (
    v1.ROOT / "08_reviews" / "phase5r_model_pilot" / "replacement_v3"
    / "phase5r_model_pilot_v3_plan.json"
)
V1_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v1"
V2_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v2"
V3_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v3"
V3_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v3_execution_plan.json"
V3_AUTHORIZATION_NAME = "phase5r_model_pilot_v3_authorization.json"
V3_JOURNAL_NAME = "phase5r_model_pilot_v3_journal.jsonl"
V3_BLIND_ASSIGNMENT_NAME = ".phase5r_model_pilot_v3_blind_assignments.json"
V3_COMPLETION_NAME = "phase5r_model_pilot_v3_completion.json"

_V1_CHARGED_USD = Decimal("0.2044525")
_V1_CHARGED_CALLS = 4
_V2_CHARGED_USD = Decimal("0.05808")
_V2_CHARGED_CALLS = 1
_V3_CALL_COUNT = 24
_V3_MAXIMUM_RESERVATION_USD = Decimal("3.9494400")
_CUMULATIVE_CALL_CAP = 30
_CUMULATIVE_USD_CAP = Decimal("5")
_READY_STATUS = "ready_for_explicit_user_authorization_execution_prohibited"


def _load_v3_plan(path: Path = V3_PLAN_PATH) -> dict[str, Any]:
    plan = v1._read_json_object(path, label="replacement v3 pilot plan")
    claimed = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if (
        plan.get("schema_version") != V3_PLAN_SCHEMA_VERSION
        or v1._canonical_sha256(unsigned) != claimed
        or plan.get("status") != _READY_STATUS
        or plan.get("execution_prohibited") is not True
    ):
        raise v1.PilotStop("replacement v3 plan is not a sealed ready plan")
    change = plan.get("diagnostic_change")
    if (
        not isinstance(change, dict)
        or change.get("instruction_appendix") != list(CITATION_BINDING_APPENDIX)
        or change.get("validator_or_schema_relaxation") is not False
        or change.get("raw_failed_response_retention") is not False
        or change.get("provider_response_id_retention") is not False
        or change.get("retry_of_v2") is not False
    ):
        raise v1.PilotStop("replacement v3 prompt repair is not sealed")
    validation = plan.get("local_validation")
    if (
        not isinstance(validation, dict)
        or validation.get("phase5r_suite")
        != "passed_complete_phase5r_suite_after_v3_executor"
        or validation.get("v3_executor_regression") != "passed"
        or validation.get("new_api_calls_made_during_v3_planning") is not False
    ):
        raise v1.PilotStop("replacement v3 local validation is incomplete")
    return plan


def _validate_v1_state(source_v1: dict[str, Any]) -> dict[str, Any]:
    plan_path = V1_OUTPUT_ROOT / v1.PLAN_NAME
    journal_path = V1_OUTPUT_ROOT / v1.JOURNAL_NAME
    plan = v1._read_json_object(plan_path, label="v1 pilot plan")
    unsigned = dict(plan)
    claimed = unsigned.pop("plan_sha256", None)
    if (
        v1._canonical_sha256(unsigned) != claimed
        or source_v1.get("plan_sha256") != claimed
        or source_v1.get("journal_file_sha256") != v1._sha256_file(journal_path)
        or source_v1.get("v1_action") != "preserve_immutable_no_resume_no_reset"
    ):
        raise v1.PilotStop("replacement v3 is not bound to immutable v1")
    events = v1._load_journal(journal_path, plan_sha256=claimed)
    v1._assert_receipt_journal_coherence(
        output_root=V1_OUTPUT_ROOT, plan=plan, events=events
    )
    charged = v1._charged_budget(plan, events)
    if (
        len(events) != 14
        or charged["used_model_calls"] != _V1_CHARGED_CALLS
        or charged["charged_usd"] != _V1_CHARGED_USD
        or (V1_OUTPUT_ROOT / v1.RESPONSE_DIRECTORY_NAME
            / "41103ccfe5365c841f39-terra-assessment.json").exists()
    ):
        raise v1.PilotStop("v1 charged state or terminal response set changed")
    return {"plan_sha256": claimed, "journal_file_sha256": v1._sha256_file(journal_path)}


def _validate_v2_state(source_v2: dict[str, Any]) -> dict[str, Any]:
    plan_path = V2_OUTPUT_ROOT / V3_EXECUTION_PLAN_NAME.replace("v3", "v2")
    journal_path = V2_OUTPUT_ROOT / V3_JOURNAL_NAME.replace("v3", "v2")
    plan = v1._read_json_object(plan_path, label="v2 execution plan")
    unsigned = dict(plan)
    claimed = unsigned.pop("plan_sha256", None)
    if (
        plan.get("schema_version") != "phase5r_model_pilot_execution_plan_v2"
        or v1._canonical_sha256(unsigned) != claimed
        or source_v2.get("execution_plan_file_sha256") != v1._sha256_file(plan_path)
        or source_v2.get("journal_file_sha256") != v1._sha256_file(journal_path)
        or source_v2.get("v2_action") != "preserve_terminal_no_resume_no_retry"
    ):
        raise v1.PilotStop("replacement v3 is not bound to terminal v2")
    events = v1._load_journal(journal_path, plan_sha256=claimed)
    v1._assert_receipt_journal_coherence(
        output_root=V2_OUTPUT_ROOT, plan=plan, events=events
    )
    charged = _charged_budget(plan, events, maximum_calls=26, maximum_usd=Decimal("4.5302400"))
    failed = [event for event in events if event["event_kind"] == "call_failed"]
    if (
        len(events) != 5
        or charged != {"used_model_calls": _V2_CHARGED_CALLS, "charged_usd": _V2_CHARGED_USD}
        or len(failed) != 1
        or failed[0].get("call_id") != source_v2.get("terminal_call_id")
        or failed[0].get("details", {}).get("failure_type") != source_v2.get("failure_type")
        or failed[0].get("details", {}).get("redacted_contract_diagnostic", {}).get("code")
        != source_v2.get("finite_failure_code")
        or any((V2_OUTPUT_ROOT / v1.RESPONSE_DIRECTORY_NAME).glob("*.json"))
    ):
        raise v1.PilotStop("v2 terminal state, charge, or response set changed")
    return {"execution_plan_sha256": claimed, "journal_file_sha256": v1._sha256_file(journal_path)}


def _selected_contexts(
    plan: dict[str, Any], contexts: list[v1.PacketContext]
) -> tuple[list[v1.PacketContext], list[v1.PacketContext]]:
    selected = plan.get("precommitted_packet_ids")
    if not isinstance(selected, dict):
        raise v1.PilotStop("replacement v3 packet selection is missing")
    analyst_ids = selected.get("analyst_pair_packets")
    committee_ids = selected.get("committee_and_critic_packets")
    if (
        not isinstance(analyst_ids, list)
        or not isinstance(committee_ids, list)
        or len(analyst_ids) != 8
        or len(committee_ids) != 4
        or any(not isinstance(value, str) for value in analyst_ids + committee_ids)
        or len(analyst_ids) != len(set(analyst_ids))
        or len(committee_ids) != len(set(committee_ids))
        or not set(committee_ids).issubset(analyst_ids)
    ):
        raise v1.PilotStop("replacement v3 packet selection is invalid")
    by_id = {context.packet_id: context for context in contexts}
    if not set(analyst_ids).issubset(by_id):
        raise v1.PilotStop("replacement v3 packets are not in frozen corpus")
    return ([by_id[value] for value in analyst_ids], [by_id[value] for value in committee_ids])


def _calls(
    analyst_contexts: list[v1.PacketContext],
    committee_contexts: list[v1.PacketContext],
    prices: dict[str, dict[str, Decimal]],
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for context in analyst_contexts:
        for stage in ("luna_assessment", "terra_assessment"):
            calls.append(_call(context, stage, [], prices))
    for index, context in enumerate(committee_contexts, start=1):
        assessments = [
            v1._call_id(context.packet_id, "luna_assessment"),
            v1._call_id(context.packet_id, "terra_assessment"),
        ]
        calls.append(_call(context, "sol_committee", assessments, prices))
        calls.append(_call(
            context, "sol_critic", [*assessments, v1._call_id(context.packet_id, "sol_committee")],
            prices, control_probe_id=f"critic-control-{index:02d}",
            control_expected="unsupported" if index <= 3 else "supported",
        ))
    reservation = sum((v1._decimal(call["reservation_usd"], label="v3 reservation") for call in calls), Decimal(0))
    if len(calls) != _V3_CALL_COUNT or len({call["call_id"] for call in calls}) != _V3_CALL_COUNT or reservation != _V3_MAXIMUM_RESERVATION_USD:
        raise v1.PilotStop("replacement v3 call layout or reservation changed")
    return calls


def _call(
    context: v1.PacketContext, stage: str, dependencies: list[str],
    prices: dict[str, dict[str, Decimal]], **extra: str,
) -> dict[str, Any]:
    call = {
        "call_id": v1._call_id(context.packet_id, stage), "packet_id": context.packet_id,
        "ticker": context.ticker, "stage": stage, "role": v1.ROLE_BY_STAGE[stage],
        "model": v1.MODEL_BY_STAGE[stage], "reasoning_effort": v1.EFFORT_BY_STAGE[stage],
        "dependencies": dependencies, "maximum_input_tokens": v1.MAXIMUM_INPUT_TOKENS,
        "maximum_output_tokens": v1.MAXIMUM_OUTPUT_TOKENS,
        "reservation_usd": v1._decimal_text(v1._reservation_usd(v1.MODEL_BY_STAGE[stage], prices)),
    }
    return {**call, **extra}


def _build_execution_plan(
    replacement: dict[str, Any], *, readiness: dict[str, Any],
    contexts: list[v1.PacketContext], policy: dict[str, Any],
    v1_state: dict[str, Any], v2_state: dict[str, Any],
) -> dict[str, Any]:
    analysts, committees = _selected_contexts(replacement, contexts)
    calls = _calls(analysts, committees, policy["prices"])
    budget = replacement.get("cumulative_budget")
    layout = replacement.get("v3_call_layout")
    if (
        not isinstance(budget, dict) or not isinstance(layout, dict)
        or v1._decimal(budget.get("v1_charged_usd"), label="v1 charge") != _V1_CHARGED_USD
        or v1._decimal(budget.get("v2_charged_reservation_usd"), label="v2 charge") != _V2_CHARGED_USD
        or budget.get("charged_model_calls_before_v3") != _V1_CHARGED_CALLS + _V2_CHARGED_CALLS
        or budget.get("remaining_authorized_model_calls_before_v3") != 25
        or layout.get("maximum_new_model_calls") != _V3_CALL_COUNT
        or v1._decimal(layout.get("maximum_new_reservation_usd"), label="v3 reservation") != _V3_MAXIMUM_RESERVATION_USD
        or _V1_CHARGED_USD + _V2_CHARGED_USD + _V3_MAXIMUM_RESERVATION_USD > _CUMULATIVE_USD_CAP
    ):
        raise v1.PilotStop("replacement v3 cumulative budget is invalid")
    plan: dict[str, Any] = {
        "schema_version": V3_EXECUTION_PLAN_SCHEMA_VERSION,
        "replacement_plan_sha256": replacement["plan_sha256"], "source_v1": copy.deepcopy(v1_state),
        "source_v2": copy.deepcopy(v2_state), "strict_audit_sha256": readiness["strict_audit_sha256"],
        "policy_file_sha256": readiness["policy_file_sha256"],
        "opening_sentinel_sha256": v1._canonical_sha256(v1._sentinel_snapshot()),
        "packet_count": len(analysts), "committee_packet_ids": [item.packet_id for item in committees],
        "assessment_instructions_sha256": v1._canonical_sha256(assessment_instructions()),
        "citation_binding_appendix_sha256": v1._canonical_sha256(list(CITATION_BINDING_APPENDIX)),
        "packet_input_bindings": {item.packet_id: {"assessment_view_sha256": v1._canonical_sha256(item.assessment_view), "audit_view_sha256": v1._canonical_sha256(item.audit_view)} for item in analysts},
        "calls": calls,
        "budget": {
            "v1_charged_model_calls": _V1_CHARGED_CALLS, "v1_charged_usd": v1._decimal_text(_V1_CHARGED_USD),
            "v2_charged_model_calls": _V2_CHARGED_CALLS, "v2_charged_usd": v1._decimal_text(_V2_CHARGED_USD),
            "maximum_new_model_calls": _V3_CALL_COUNT, "maximum_new_reservation_usd": v1._decimal_text(_V3_MAXIMUM_RESERVATION_USD),
            "cumulative_maximum_model_calls": _CUMULATIVE_CALL_CAP, "cumulative_maximum_usd": v1._decimal_text(_CUMULATIVE_USD_CAP),
            "maximum_input_tokens_per_call": v1.MAXIMUM_INPUT_TOKENS, "maximum_output_tokens_per_call": v1.MAXIMUM_OUTPUT_TOKENS,
            "maximum_request_envelope_bytes": v1.MAXIMUM_REQUEST_ENVELOPE_BYTES, "sdk_max_retries": 0,
        },
        "boundaries": {"shadow_only": True, "canonical_effect": False, "email_effect": False,
                       "automatic_action_allowed": False, "broker_used": False, "order_code_created": False,
                       "provider": "openai_responses_injected_client", "store": False, "tools": [], "retry_count": 0},
    }
    plan["plan_sha256"] = v1._canonical_sha256(plan)
    return plan


def check_v3_readiness(*, replacement_plan_path: Path = V3_PLAN_PATH) -> dict[str, Any]:
    """Read and verify all v3 gates without a provider, network, or writes."""
    replacement = _load_v3_plan(replacement_plan_path)
    v1_state = _validate_v1_state(replacement["source_v1"])
    v2_state = _validate_v2_state(replacement["source_v2"])
    readiness = v1.check_pilot_readiness()
    if readiness.get("passed") is not True:
        raise v1.PilotStop("strict pilot corpus or runtime readiness failed")
    policy, contexts, _unused, _audit, _sentinels = v1._readiness_components()
    execution = _build_execution_plan(replacement, readiness=readiness, contexts=contexts, policy=policy, v1_state=v1_state, v2_state=v2_state)
    return {"passed": True, "provider_constructed": False, "network_used": False, "files_written": False,
            "model_calls": 0, "replacement_plan_sha256": replacement["plan_sha256"],
            "execution_plan_sha256": execution["plan_sha256"], "new_model_calls": len(execution["calls"]),
            "new_reserved_usd": execution["budget"]["maximum_new_reservation_usd"],
            "strict_audit_sha256": readiness["strict_audit_sha256"],
            "policy_file_sha256": readiness["policy_file_sha256"],
            "cumulative_reserved_usd": v1._decimal_text(_V1_CHARGED_USD + _V2_CHARGED_USD + _V3_MAXIMUM_RESERVATION_USD),
            "canonical_effect": False, "email_effect": False, "automatic_action_allowed": False}


def _charged_budget(plan: dict[str, Any], events: list[dict[str, Any]], *, maximum_calls: int, maximum_usd: Decimal) -> dict[str, Any]:
    calls = {call["call_id"]: call for call in plan["calls"]}
    used, charged = 0, Decimal(0)
    for call_id, call in calls.items():
        if v1._reserved_event(events, call_id) is None:
            continue
        used += 1
        terminal = v1._terminal_event(events, call_id)
        charged += (v1._decimal(terminal["details"]["actual_cost_usd"], label="completed cost")
                    if terminal is not None and terminal["event_kind"] == "call_completed"
                    else v1._decimal(call["reservation_usd"], label="reserved cost"))
    if used > maximum_calls or charged > maximum_usd:
        raise v1.PilotStop("replacement pilot budget exceeded")
    return {"used_model_calls": used, "charged_usd": charged}


def _write_or_validate(path: Path, payload: dict[str, Any], *, label: str) -> None:
    if path.exists():
        if v1._read_json_object(path, label=label) != payload:
            raise v1.PilotStop(f"existing {label} differs from sealed value")
        return
    v1._write_json_exclusive(path, payload)


def _authorization_receipt(execution: dict[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": V3_AUTHORIZATION_SCHEMA_VERSION,
        "replacement_plan_sha256": execution["replacement_plan_sha256"],
        "execution_plan_sha256": execution["plan_sha256"], "authorization_source": "interactive_user_approval",
        "scope": {"maximum_new_model_calls": _V3_CALL_COUNT, "maximum_new_reservation_usd": v1._decimal_text(_V3_MAXIMUM_RESERVATION_USD),
                  "shadow_only": True, "email_effect": False, "canonical_effect": False,
                  "automatic_action_allowed": False, "broker_used": False},
    }
    receipt["authorization_sha256"] = v1._canonical_sha256(receipt)
    return receipt


def _assignments(output_root: Path, execution: dict[str, Any]) -> dict[str, dict[str, str]]:
    path = output_root / V3_BLIND_ASSIGNMENT_NAME
    if path.exists():
        payload = v1._read_json_object(path, label="v3 blind assignments")
        claimed = payload.get("assignment_sha256")
        unsigned = dict(payload)
        unsigned.pop("assignment_sha256", None)
        rows = payload.get("rows")
        if payload.get("schema_version") != V3_BLIND_ASSIGNMENT_SCHEMA_VERSION or payload.get("plan_sha256") != execution["plan_sha256"] or v1._canonical_sha256(unsigned) != claimed:
            raise v1.PilotStop("existing v3 blind assignments are invalid")
    else:
        packet_ids = [call["packet_id"] for call in execution["calls"] if call["stage"] == "luna_assessment"]
        shuffled = list(packet_ids)
        secrets.SystemRandom().shuffle(shuffled)
        luna_a = set(shuffled[:4])
        rows = {packet_id: ({"A": "luna_assessment", "B": "terra_assessment"} if packet_id in luna_a else {"A": "terra_assessment", "B": "luna_assessment"}) for packet_id in packet_ids}
        payload = {"schema_version": V3_BLIND_ASSIGNMENT_SCHEMA_VERSION, "plan_sha256": execution["plan_sha256"], "mapping_method": "system_random_balanced_four_four", "rows": rows}
        payload["assignment_sha256"] = v1._canonical_sha256(payload)
        v1._write_json_exclusive(path, payload)
    if not isinstance(rows, dict) or len(rows) != 8 or any(not isinstance(mapping, dict) or set(mapping) != {"A", "B"} or set(mapping.values()) != {"luna_assessment", "terra_assessment"} for mapping in rows.values()):
        raise v1.PilotStop("v3 blind assignments are malformed")
    return copy.deepcopy(rows)


def _redacted_provider_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(metadata)
    response_id = redacted.pop("provider_response_id", None)
    if not isinstance(response_id, str) or not response_id:
        raise v1.PilotStop("provider response ID is missing before redaction")
    redacted["provider_response_id_sha256"] = hashlib.sha256(response_id.encode("utf-8")).hexdigest()
    return redacted


def _instructions(stage: str) -> str:
    return assessment_instructions() if stage in {"luna_assessment", "terra_assessment"} else v1._instructions_for_stage(stage)


def _completion(output_root: Path, execution: dict[str, Any]) -> dict[str, Any] | None:
    path = output_root / V3_COMPLETION_NAME
    if not path.exists():
        return None
    completed = v1._read_json_object(path, label="v3 completion")
    unsigned = dict(completed)
    claimed = unsigned.pop("completion_sha256", None)
    hashes = completed.get("receipt_file_sha256")
    if (completed.get("schema_version") != V3_COMPLETION_SCHEMA_VERSION or completed.get("execution_plan_sha256") != execution["plan_sha256"] or completed.get("physical_model_calls") != _V3_CALL_COUNT or completed.get("canonical_effect") is not False or completed.get("email_effect") is not False or completed.get("automatic_action_allowed") is not False or not isinstance(hashes, dict) or set(hashes) != {call["call_id"] for call in execution["calls"]} or any(v1._sha256_file(output_root / v1.RESPONSE_DIRECTORY_NAME / f"{call_id}.json") != digest for call_id, digest in hashes.items()) or v1._canonical_sha256(unsigned) != claimed):
        raise v1.PilotStop("existing v3 completion is invalid")
    return completed


def execute_model_pilot_v3(*, provider_factory: Callable[[], ModelProvider], explicit_user_authorization: bool, replacement_plan_path: Path = V3_PLAN_PATH, output_root: Path = V3_OUTPUT_ROOT) -> dict[str, Any]:
    """Execute v3 once; any started inference creates a durable no-retry stop."""
    if not callable(provider_factory) or explicit_user_authorization is not True:
        raise v1.PilotStop("v3 execution requires explicit interactive user approval")
    report = check_v3_readiness(replacement_plan_path=replacement_plan_path)
    replacement = _load_v3_plan(replacement_plan_path)
    v1_state = _validate_v1_state(replacement["source_v1"])
    v2_state = _validate_v2_state(replacement["source_v2"])
    policy, contexts, _unused, _audit, sentinels = v1._readiness_components()
    execution = _build_execution_plan(
        replacement,
        readiness={
            "strict_audit_sha256": report["strict_audit_sha256"],
            "policy_file_sha256": report["policy_file_sha256"],
        },
        contexts=contexts,
        policy=policy,
        v1_state=v1_state,
        v2_state=v2_state,
    )
    if output_root.expanduser().resolve() != V3_OUTPUT_ROOT.resolve():
        raise v1.PilotStop("v3 output root is pinned to its separate quarantine")
    with v1._pilot_lock(v1.QUARANTINE_ROOT):
        root = v1._validate_output_root(output_root, v1.QUARANTINE_ROOT)
        _write_or_validate(root / V3_EXECUTION_PLAN_NAME, execution, label="v3 execution plan")
        _write_or_validate(root / V3_AUTHORIZATION_NAME, _authorization_receipt(execution), label="v3 authorization receipt")
        complete = _completion(root, execution)
        if complete is not None:
            return complete
        assignments = _assignments(root, execution)
        journal_path = root / V3_JOURNAL_NAME
        events = v1._load_journal(journal_path, plan_sha256=execution["plan_sha256"])
        v1._assert_receipt_journal_coherence(output_root=root, plan=execution, events=events)
        if events:
            raise v1.PilotStop("v3 has durable journal state and cannot resume or retry")
        v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_opened", call_id=None, details={"maximum_new_model_calls": _V3_CALL_COUNT, "maximum_new_reservation_usd": v1._decimal_text(_V3_MAXIMUM_RESERVATION_USD), "prior_charged_model_calls": _V1_CHARGED_CALLS + _V2_CHARGED_CALLS, "prior_charged_usd": v1._decimal_text(_V1_CHARGED_USD + _V2_CHARGED_USD), "provider": "openai_responses_api", "sdk_max_retries": 0, "email_effect": False, "canonical_effect": False})
        by_id = {context.packet_id: context for context in contexts}
        results: dict[str, dict[str, Any]] = {}
        for call in execution["calls"]:
            context, schema, instructions = by_id[call["packet_id"]], v1._schema_for_stage(call["stage"]), _instructions(call["stage"])
            input_payload = v1._input_for_call(call, context, results, assignments)
            envelope = v1._request_envelope_bytes(call, schema=schema, instructions=instructions, input_payload=input_payload)
            if envelope > v1.MAXIMUM_REQUEST_ENVELOPE_BYTES:
                raise v1.PilotStop("v3 request envelope exceeds its byte cap")
            v1._assert_runtime_safety(opening_sentinels=sentinels, corpus_root=v1.CORPUS_ROOT, quarantine_root=v1.QUARANTINE_ROOT)
            try:
                provider = provider_factory()
                v1._strict_provider(provider, allow_test_provider=False)
                exact_tokens = provider.count_input_tokens(role=call["role"], model=call["model"], reasoning_effort=call["reasoning_effort"], schema=copy.deepcopy(schema), instructions=instructions, input_payload=copy.deepcopy(input_payload))
            except Exception as exc:
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_stopped", call_id=None, details={"reason": "provider_or_input_count_preflight_failed", "call_id": call["call_id"], "failure_type": type(exc).__name__, "model_calls_charged": 0})
                raise v1.PilotStop("v3 provider or input count preflight failed") from exc
            if type(exact_tokens) is not int or exact_tokens < 0 or exact_tokens > call["maximum_input_tokens"]:
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_stopped", call_id=None, details={"reason": "exact_input_token_ceiling_exceeded", "call_id": call["call_id"], "model_calls_charged": 0})
                raise v1.PilotStop("v3 exact input token count exceeds reservation")
            binding = {"call_id": call["call_id"], "packet_id": call["packet_id"], "stage": call["stage"], "role": call["role"], "model": call["model"], "reasoning_effort": call["reasoning_effort"], "schema_sha256": v1._canonical_sha256(schema), "instructions_sha256": v1._canonical_sha256(instructions), "input_sha256": v1._canonical_sha256(input_payload), "dependency_result_sha256s": {dependency: v1._canonical_sha256(results[dependency]["payload"]) for dependency in call["dependencies"]}, "request_envelope_bytes": envelope, "exact_input_tokens": exact_tokens, "store": False, "tools": [], "request_timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS, "sdk_max_retries": 0}
            if call["stage"] in {"sol_committee", "sol_critic"}:
                binding["blind_mapping_sha256"] = v1._canonical_sha256(v1._blind_mapping(call["packet_id"], assignments))
            binding_sha = v1._canonical_sha256(binding)
            v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="input_count_completed", call_id=call["call_id"], details={"request_binding_sha256": binding_sha, "exact_input_tokens": exact_tokens, "model_inference_started": False})
            v1._assert_runtime_safety(opening_sentinels=sentinels, corpus_root=v1.CORPUS_ROOT, quarantine_root=v1.QUARANTINE_ROOT)
            charged = _charged_budget(execution, events, maximum_calls=_V3_CALL_COUNT, maximum_usd=_V3_MAXIMUM_RESERVATION_USD)
            reservation = v1._decimal(call["reservation_usd"], label="v3 reservation")
            if charged["used_model_calls"] + 1 > _V3_CALL_COUNT or _V1_CHARGED_USD + _V2_CHARGED_USD + charged["charged_usd"] + reservation > _CUMULATIVE_USD_CAP:
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_stopped", call_id=None, details={"reason": "pre_inference_cumulative_budget_gate_failed", "call_id": call["call_id"]})
                raise v1.PilotStop("v3 pre-inference cumulative budget gate failed")
            v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="call_reserved", call_id=call["call_id"], details={"request_binding_sha256": binding_sha, "reservation_usd": call["reservation_usd"], "provider_constructed": True, "sdk_max_retries": 0, "maximum_physical_attempts": 1})
            received = False
            try:
                result = provider.generate(role=call["role"], model=call["model"], reasoning_effort=call["reasoning_effort"], schema=copy.deepcopy(schema), instructions=instructions, input_payload=copy.deepcopy(input_payload))
                received = True
                if not isinstance(result, ProviderResult):
                    raise v1.PilotStop("v3 provider returned an invalid result")
                payload = v1._validate_stage_payload(call, context, result.payload, results, assignments)
                usage = v1._metered_usage(call, result.metadata, policy["prices"], allow_test_provider=False)
                if usage["total_input_tokens"] != exact_tokens:
                    raise v1.PilotStop("v3 provider usage differs from preflight count")
                receipt: dict[str, Any] = {"schema_version": V3_RECEIPT_SCHEMA_VERSION, "execution_plan_sha256": execution["plan_sha256"], "call_id": call["call_id"], "request_binding_sha256": binding_sha, "payload": copy.deepcopy(payload), "payload_sha256": v1._canonical_sha256(payload), "provider_metadata": _redacted_provider_metadata(result.metadata), "metered_usage": usage, "canonical_effect": False, "email_effect": False, "automatic_action_allowed": False}
                receipt["receipt_sha256"] = v1._canonical_sha256(receipt)
                v1._write_json_exclusive(root / v1.RESPONSE_DIRECTORY_NAME / f"{call['call_id']}.json", receipt)
            except Exception as exc:
                details: dict[str, Any] = {"charged_reservation_usd": call["reservation_usd"], "failure_type": type(exc).__name__, "retry_allowed": False}
                if isinstance(exc, v1.ContractError):
                    details["redacted_contract_diagnostic"] = v1._redacted_contract_diagnostic(call, exc)
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="call_failed" if received else "call_outcome_unknown", call_id=call["call_id"], details=details)
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_stopped", call_id=None, details={"reason": "call_failed", "call_id": call["call_id"]})
                raise v1.PilotStop(f"v3 stopped at {call['call_id']}") from exc
            v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="call_completed", call_id=call["call_id"], details={"actual_cost_usd": usage["cost_usd"], "metered_usage": usage, "receipt_sha256": receipt["receipt_sha256"]})
            results[call["call_id"]] = {"payload": copy.deepcopy(payload), "metered_usage": usage, "receipt_sha256": receipt["receipt_sha256"]}
            v1._assert_runtime_safety(opening_sentinels=sentinels, corpus_root=v1.CORPUS_ROOT, quarantine_root=v1.QUARANTINE_ROOT)
        charged = _charged_budget(execution, events, maximum_calls=_V3_CALL_COUNT, maximum_usd=_V3_MAXIMUM_RESERVATION_USD)
        if len(results) != _V3_CALL_COUNT:
            raise v1.PilotStop("v3 ended without all planned results")
        v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="model_calls_completed", call_id=None, details={"physical_model_calls": _V3_CALL_COUNT, "charged_usd": v1._decimal_text(charged["charged_usd"]), "canonical_effect": False, "email_effect": False})
        completion: dict[str, Any] = {"schema_version": V3_COMPLETION_SCHEMA_VERSION, "execution_plan_sha256": execution["plan_sha256"], "physical_model_calls": _V3_CALL_COUNT, "prior_charged_usd": v1._decimal_text(_V1_CHARGED_USD + _V2_CHARGED_USD), "v3_charged_usd": v1._decimal_text(charged["charged_usd"]), "cumulative_charged_usd": v1._decimal_text(_V1_CHARGED_USD + _V2_CHARGED_USD + charged["charged_usd"]), "canonical_effect": False, "email_effect": False, "automatic_action_allowed": False, "broker_used": False, "receipt_file_sha256": {call["call_id"]: v1._sha256_file(root / v1.RESPONSE_DIRECTORY_NAME / f"{call['call_id']}.json") for call in execution["calls"]}}
        completion["completion_sha256"] = v1._canonical_sha256(completion)
        v1._write_json_exclusive(root / V3_COMPLETION_NAME, completion)
        return completion


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(check_v3_readiness(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
