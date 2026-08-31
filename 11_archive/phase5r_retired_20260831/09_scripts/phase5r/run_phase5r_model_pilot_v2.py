#!/usr/bin/env python3
"""Bounded replacement executor for the approved Phase 5R v2 pilot.

This module has no command that constructs a provider.  A caller must inject
an already-authenticated OpenAI Responses client and explicitly attest that the
interactive user authorized this one shadow-only run.  It never reads or
stores credentials, never sends email, and never changes canonical research or
trading state.
"""

from __future__ import annotations

import copy
import hashlib
import json
import secrets
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from phase5r_llm_provider import ModelProvider, OpenAIResponsesProvider, ProviderResult
import run_phase5r_model_pilot as v1


V2_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_replacement_plan_v2"
V2_EXECUTION_PLAN_SCHEMA_VERSION = "phase5r_model_pilot_execution_plan_v2"
V2_AUTHORIZATION_SCHEMA_VERSION = "phase5r_model_pilot_v2_authorization_v1"
V2_RECEIPT_SCHEMA_VERSION = "phase5r_model_pilot_v2_call_receipt_v1"
V2_COMPLETION_SCHEMA_VERSION = "phase5r_model_pilot_v2_completion_v1"
V2_BLIND_ASSIGNMENT_SCHEMA_VERSION = "phase5r_model_pilot_v2_blind_assignment_v1"

V2_PLAN_PATH = (
    v1.ROOT
    / "08_reviews"
    / "phase5r_model_pilot"
    / "replacement_v2"
    / "phase5r_model_pilot_v2_plan.json"
)
V1_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v1"
V2_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v2"
V2_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v2_execution_plan.json"
V2_AUTHORIZATION_NAME = "phase5r_model_pilot_v2_authorization.json"
V2_JOURNAL_NAME = "phase5r_model_pilot_v2_journal.jsonl"
V2_BLIND_ASSIGNMENT_NAME = ".phase5r_model_pilot_v2_blind_assignments.json"
V2_COMPLETION_NAME = "phase5r_model_pilot_v2_completion.json"

_V1_CHARGED_USD = Decimal("0.2044525")
_V1_CHARGED_CALLS = 4
_V2_CALL_COUNT = 26
_V2_MAXIMUM_RESERVATION_USD = Decimal("4.5302400")
_CUMULATIVE_CALL_CAP = 30
_CUMULATIVE_USD_CAP = Decimal("5")


def _load_v2_plan(path: Path = V2_PLAN_PATH) -> dict[str, Any]:
    """Validate the immutable replacement-plan authorization envelope."""

    plan = v1._read_json_object(path, label="replacement v2 pilot plan")
    claimed = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if (
        plan.get("schema_version") != V2_PLAN_SCHEMA_VERSION
        or v1._canonical_sha256(unsigned) != claimed
        or plan.get("status")
        != "ready_for_explicit_user_authorization_execution_prohibited"
        or plan.get("execution_prohibited") is not True
    ):
        raise v1.PilotStop("replacement v2 plan is not a sealed ready plan")
    boundaries = plan.get("execution_gates")
    validation = plan.get("local_validation")
    if (
        not isinstance(boundaries, list)
        or not isinstance(validation, dict)
        or validation.get("phase5r_suite") != "passed_361_tests_offline"
        or validation.get("pilot_contract_regression") != "passed"
        or validation.get("new_api_calls_made") is not False
        or validation.get("unrelated_baseline_blockers") != []
    ):
        raise v1.PilotStop("replacement v2 local validation is incomplete")
    return plan


def _validate_v1_state(source_v1: dict[str, Any]) -> dict[str, Any]:
    """Revalidate v1 without modifying its immutable plan, journal, or receipts."""

    plan_path = V1_OUTPUT_ROOT / v1.PLAN_NAME
    journal_path = V1_OUTPUT_ROOT / v1.JOURNAL_NAME
    plan = v1._read_json_object(plan_path, label="v1 pilot plan")
    unsigned = dict(plan)
    claimed_plan_sha256 = unsigned.pop("plan_sha256", None)
    if (
        v1._canonical_sha256(unsigned) != claimed_plan_sha256
        or source_v1.get("plan_sha256") != claimed_plan_sha256
        or source_v1.get("journal_file_sha256")
        != v1._sha256_file(journal_path)
        or source_v1.get("v1_action")
        != "preserve_immutable_no_resume_no_reset"
    ):
        raise v1.PilotStop("replacement v2 is not bound to immutable v1")
    events = v1._load_journal(journal_path, plan_sha256=plan["plan_sha256"])
    v1._assert_receipt_journal_coherence(
        output_root=V1_OUTPUT_ROOT,
        plan=plan,
        events=events,
    )
    charged = v1._charged_budget(plan, events)
    if (
        charged["used_model_calls"] != _V1_CHARGED_CALLS
        or charged["charged_usd"] != _V1_CHARGED_USD
        or len(events) != 14
        or (V1_OUTPUT_ROOT / v1.RESPONSE_DIRECTORY_NAME / "41103ccfe5365c841f39-terra-assessment.json").exists()
    ):
        raise v1.PilotStop("v1 charged state or terminal response set changed")
    return {
        "plan_sha256": plan["plan_sha256"],
        "journal_file_sha256": v1._sha256_file(journal_path),
        "charged_usd": v1._decimal_text(charged["charged_usd"]),
        "charged_model_calls": charged["used_model_calls"],
    }


def _selected_contexts(
    plan: dict[str, Any],
    contexts: list[v1.PacketContext],
) -> tuple[list[v1.PacketContext], list[v1.PacketContext]]:
    precommitted = plan.get("precommitted_packet_ids")
    if not isinstance(precommitted, dict):
        raise v1.PilotStop("replacement v2 packet selection is missing")
    analyst_ids = precommitted.get("analyst_pair_packets")
    committee_ids = precommitted.get("committee_and_critic_packets")
    if (
        not isinstance(analyst_ids, list)
        or not isinstance(committee_ids, list)
        or len(analyst_ids) != 8
        or len(committee_ids) != 5
        or any(not isinstance(value, str) for value in analyst_ids + committee_ids)
        or len(analyst_ids) != len(set(analyst_ids))
        or len(committee_ids) != len(set(committee_ids))
        or not set(committee_ids).issubset(analyst_ids)
    ):
        raise v1.PilotStop("replacement v2 packet selection is invalid")
    by_id = {context.packet_id: context for context in contexts}
    if not set(analyst_ids).issubset(by_id):
        raise v1.PilotStop("replacement v2 packets are not in frozen corpus")
    return (
        [by_id[packet_id] for packet_id in analyst_ids],
        [by_id[packet_id] for packet_id in committee_ids],
    )


def _v2_calls(
    analyst_contexts: list[v1.PacketContext],
    committee_contexts: list[v1.PacketContext],
    prices: dict[str, dict[str, Decimal]],
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for context in analyst_contexts:
        for stage in ("luna_assessment", "terra_assessment"):
            calls.append(
                {
                    "call_id": v1._call_id(context.packet_id, stage),
                    "packet_id": context.packet_id,
                    "ticker": context.ticker,
                    "stage": stage,
                    "role": v1.ROLE_BY_STAGE[stage],
                    "model": v1.MODEL_BY_STAGE[stage],
                    "reasoning_effort": v1.EFFORT_BY_STAGE[stage],
                    "dependencies": [],
                    "maximum_input_tokens": v1.MAXIMUM_INPUT_TOKENS,
                    "maximum_output_tokens": v1.MAXIMUM_OUTPUT_TOKENS,
                    "reservation_usd": v1._decimal_text(
                        v1._reservation_usd(v1.MODEL_BY_STAGE[stage], prices)
                    ),
                }
            )
    for index, context in enumerate(committee_contexts, start=1):
        assessment_dependencies = [
            v1._call_id(context.packet_id, "luna_assessment"),
            v1._call_id(context.packet_id, "terra_assessment"),
        ]
        committee_stage = "sol_committee"
        critic_stage = "sol_critic"
        calls.append(
            {
                "call_id": v1._call_id(context.packet_id, committee_stage),
                "packet_id": context.packet_id,
                "ticker": context.ticker,
                "stage": committee_stage,
                "role": v1.ROLE_BY_STAGE[committee_stage],
                "model": v1.MODEL_BY_STAGE[committee_stage],
                "reasoning_effort": v1.EFFORT_BY_STAGE[committee_stage],
                "dependencies": assessment_dependencies,
                "maximum_input_tokens": v1.MAXIMUM_INPUT_TOKENS,
                "maximum_output_tokens": v1.MAXIMUM_OUTPUT_TOKENS,
                "reservation_usd": v1._decimal_text(
                    v1._reservation_usd(
                        v1.MODEL_BY_STAGE[committee_stage], prices
                    )
                ),
            }
        )
        calls.append(
            {
                "call_id": v1._call_id(context.packet_id, critic_stage),
                "packet_id": context.packet_id,
                "ticker": context.ticker,
                "stage": critic_stage,
                "role": v1.ROLE_BY_STAGE[critic_stage],
                "model": v1.MODEL_BY_STAGE[critic_stage],
                "reasoning_effort": v1.EFFORT_BY_STAGE[critic_stage],
                "dependencies": [
                    *assessment_dependencies,
                    v1._call_id(context.packet_id, committee_stage),
                ],
                "control_probe_id": f"critic-control-{index:02d}",
                "control_expected": "unsupported" if index <= 3 else "supported",
                "maximum_input_tokens": v1.MAXIMUM_INPUT_TOKENS,
                "maximum_output_tokens": v1.MAXIMUM_OUTPUT_TOKENS,
                "reservation_usd": v1._decimal_text(
                    v1._reservation_usd(v1.MODEL_BY_STAGE[critic_stage], prices)
                ),
            }
        )
    reservations = sum(
        (v1._decimal(call["reservation_usd"], label="v2 reservation") for call in calls),
        Decimal(0),
    )
    if (
        len(calls) != _V2_CALL_COUNT
        or len({call["call_id"] for call in calls}) != _V2_CALL_COUNT
        or reservations != _V2_MAXIMUM_RESERVATION_USD
    ):
        raise v1.PilotStop("replacement v2 call layout or reservation changed")
    return calls


def _build_execution_plan(
    replacement: dict[str, Any],
    *,
    readiness: dict[str, Any],
    contexts: list[v1.PacketContext],
    policy: dict[str, Any],
    v1_state: dict[str, Any],
) -> dict[str, Any]:
    analyst_contexts, committee_contexts = _selected_contexts(replacement, contexts)
    calls = _v2_calls(analyst_contexts, committee_contexts, policy["prices"])
    cumulative = replacement.get("cumulative_budget")
    layout = replacement.get("v2_call_layout")
    if (
        not isinstance(cumulative, dict)
        or not isinstance(layout, dict)
        or cumulative.get("v1_charged_model_calls") != _V1_CHARGED_CALLS
        or v1._decimal(cumulative.get("v1_charged_usd"), label="v1 charge")
        != _V1_CHARGED_USD
        or cumulative.get("remaining_authorized_model_calls") != _V2_CALL_COUNT
        or v1._decimal(
            cumulative.get("remaining_authorized_usd"), label="remaining budget"
        )
        != _CUMULATIVE_USD_CAP - _V1_CHARGED_USD
        or layout.get("maximum_new_model_calls") != _V2_CALL_COUNT
        or v1._decimal(
            layout.get("maximum_new_reservation_usd"), label="v2 reservation"
        )
        != _V2_MAXIMUM_RESERVATION_USD
        or _V1_CHARGED_USD + _V2_MAXIMUM_RESERVATION_USD > _CUMULATIVE_USD_CAP
    ):
        raise v1.PilotStop("replacement v2 cumulative budget is invalid")
    execution_plan: dict[str, Any] = {
        "schema_version": V2_EXECUTION_PLAN_SCHEMA_VERSION,
        "replacement_plan_sha256": replacement["plan_sha256"],
        "source_v1": copy.deepcopy(v1_state),
        "strict_audit_sha256": readiness["strict_audit_sha256"],
        "policy_file_sha256": readiness["policy_file_sha256"],
        "opening_sentinel_sha256": v1._canonical_sha256(v1._sentinel_snapshot()),
        "packet_count": len(analyst_contexts),
        "committee_packet_ids": [context.packet_id for context in committee_contexts],
        "packet_input_bindings": {
            context.packet_id: {
                "assessment_view_sha256": v1._canonical_sha256(
                    context.assessment_view
                ),
                "audit_view_sha256": v1._canonical_sha256(context.audit_view),
            }
            for context in analyst_contexts
        },
        "calls": calls,
        "budget": {
            "v1_charged_model_calls": _V1_CHARGED_CALLS,
            "v1_charged_usd": v1._decimal_text(_V1_CHARGED_USD),
            "maximum_new_model_calls": _V2_CALL_COUNT,
            "maximum_new_reservation_usd": v1._decimal_text(
                _V2_MAXIMUM_RESERVATION_USD
            ),
            "cumulative_maximum_model_calls": _CUMULATIVE_CALL_CAP,
            "cumulative_maximum_usd": v1._decimal_text(_CUMULATIVE_USD_CAP),
            "maximum_input_tokens_per_call": v1.MAXIMUM_INPUT_TOKENS,
            "maximum_output_tokens_per_call": v1.MAXIMUM_OUTPUT_TOKENS,
            "maximum_request_envelope_bytes": v1.MAXIMUM_REQUEST_ENVELOPE_BYTES,
            "sdk_max_retries": 0,
            "batch_discount_assumed": False,
        },
        "boundaries": {
            "shadow_only": True,
            "canonical_effect": False,
            "email_effect": False,
            "automatic_action_allowed": False,
            "broker_used": False,
            "order_code_created": False,
            "provider": "openai_responses_injected_client",
            "store": False,
            "tools": [],
            "retry_count": 0,
        },
    }
    execution_plan["plan_sha256"] = v1._canonical_sha256(execution_plan)
    return execution_plan


def check_v2_readiness(
    *,
    replacement_plan_path: Path = V2_PLAN_PATH,
) -> dict[str, Any]:
    """Run v2's full local gate without a provider, network, or file writes."""

    replacement = _load_v2_plan(replacement_plan_path)
    v1_state = _validate_v1_state(replacement["source_v1"])
    readiness = v1.check_pilot_readiness()
    if readiness.get("passed") is not True:
        raise v1.PilotStop("strict pilot corpus or runtime readiness failed")
    policy, contexts, _unused_plan, _audit, _sentinels = v1._readiness_components()
    execution_plan = _build_execution_plan(
        replacement,
        readiness=readiness,
        contexts=contexts,
        policy=policy,
        v1_state=v1_state,
    )
    return {
        "passed": True,
        "provider_constructed": False,
        "network_used": False,
        "files_written": False,
        "model_calls": 0,
        "replacement_plan_sha256": replacement["plan_sha256"],
        "execution_plan_sha256": execution_plan["plan_sha256"],
        "strict_audit_sha256": readiness["strict_audit_sha256"],
        "policy_file_sha256": readiness["policy_file_sha256"],
        "new_model_calls": len(execution_plan["calls"]),
        "new_reserved_usd": execution_plan["budget"]["maximum_new_reservation_usd"],
        "cumulative_reserved_usd": v1._decimal_text(
            _V1_CHARGED_USD + _V2_MAXIMUM_RESERVATION_USD
        ),
        "canonical_effect": False,
        "email_effect": False,
        "automatic_action_allowed": False,
    }


def _write_or_validate(path: Path, payload: dict[str, Any], *, label: str) -> None:
    if path.exists():
        if v1._read_json_object(path, label=label) != payload:
            raise v1.PilotStop(f"existing {label} differs from sealed value")
        return
    v1._write_json_exclusive(path, payload)


def _authorization_receipt(execution_plan: dict[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": V2_AUTHORIZATION_SCHEMA_VERSION,
        "replacement_plan_sha256": execution_plan["replacement_plan_sha256"],
        "execution_plan_sha256": execution_plan["plan_sha256"],
        "authorization_source": "interactive_user_approval",
        "scope": {
            "maximum_new_model_calls": _V2_CALL_COUNT,
            "maximum_new_reservation_usd": v1._decimal_text(
                _V2_MAXIMUM_RESERVATION_USD
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


def _load_or_create_blind_assignments(
    output_root: Path,
    execution_plan: dict[str, Any],
) -> dict[str, dict[str, str]]:
    path = output_root / V2_BLIND_ASSIGNMENT_NAME
    if path.exists():
        payload = v1._read_json_object(path, label="v2 blind assignments")
        claimed = payload.get("assignment_sha256")
        unsigned = dict(payload)
        unsigned.pop("assignment_sha256", None)
        if (
            payload.get("schema_version") != V2_BLIND_ASSIGNMENT_SCHEMA_VERSION
            or payload.get("plan_sha256") != execution_plan["plan_sha256"]
            or payload.get("mapping_method") != "system_random_balanced_four_four"
            or v1._canonical_sha256(unsigned) != claimed
        ):
            raise v1.PilotStop("existing v2 blind assignments are invalid")
        rows = payload.get("rows")
    else:
        packet_ids = [
            call["packet_id"]
            for call in execution_plan["calls"]
            if call["stage"] == "luna_assessment"
        ]
        shuffled = list(packet_ids)
        secrets.SystemRandom().shuffle(shuffled)
        luna_as_a = set(shuffled[: len(shuffled) // 2])
        rows = {
            packet_id: (
                {"A": "luna_assessment", "B": "terra_assessment"}
                if packet_id in luna_as_a
                else {"A": "terra_assessment", "B": "luna_assessment"}
            )
            for packet_id in packet_ids
        }
        payload = {
            "schema_version": V2_BLIND_ASSIGNMENT_SCHEMA_VERSION,
            "plan_sha256": execution_plan["plan_sha256"],
            "mapping_method": "system_random_balanced_four_four",
            "rows": rows,
        }
        payload["assignment_sha256"] = v1._canonical_sha256(payload)
        v1._write_json_exclusive(path, payload)
    if (
        not isinstance(rows, dict)
        or len(rows) != 8
        or any(
            not isinstance(mapping, dict)
            or set(mapping) != {"A", "B"}
            or set(mapping.values())
            != {"luna_assessment", "terra_assessment"}
            for mapping in rows.values()
        )
    ):
        raise v1.PilotStop("v2 blind assignments are malformed")
    return copy.deepcopy(rows)


def _v2_charged_budget(
    execution_plan: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    calls = {call["call_id"]: call for call in execution_plan["calls"]}
    calls_used = 0
    charged = Decimal(0)
    for call_id, call in calls.items():
        reserved = v1._reserved_event(events, call_id)
        if reserved is None:
            continue
        calls_used += 1
        terminal = v1._terminal_event(events, call_id)
        if terminal is not None and terminal["event_kind"] == "call_completed":
            charged += v1._decimal(
                terminal["details"]["actual_cost_usd"], label="v2 completed cost"
            )
        else:
            charged += v1._decimal(call["reservation_usd"], label="v2 reservation")
    if (
        calls_used > _V2_CALL_COUNT
        or _V1_CHARGED_CALLS + calls_used > _CUMULATIVE_CALL_CAP
        or charged > _V2_MAXIMUM_RESERVATION_USD
        or _V1_CHARGED_USD + charged > _CUMULATIVE_USD_CAP
    ):
        raise v1.PilotStop("replacement v2 cumulative budget exceeded")
    return {"used_model_calls": calls_used, "charged_usd": charged}


def _redacted_provider_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Persist metering and boundary evidence but never a provider response ID."""

    redacted = copy.deepcopy(metadata)
    response_id = redacted.pop("provider_response_id", None)
    if isinstance(response_id, str) and response_id:
        redacted["provider_response_id_sha256"] = hashlib.sha256(
            response_id.encode("utf-8")
        ).hexdigest()
    else:
        raise v1.PilotStop("provider response ID is missing before redaction")
    return redacted


def _completed_output(
    output_root: Path, execution_plan: dict[str, Any]
) -> dict[str, Any] | None:
    path = output_root / V2_COMPLETION_NAME
    if not path.exists():
        return None
    completion = v1._read_json_object(path, label="v2 completion")
    claimed = completion.get("completion_sha256")
    unsigned = dict(completion)
    unsigned.pop("completion_sha256", None)
    receipt_hashes = completion.get("receipt_file_sha256")
    if (
        completion.get("schema_version") != V2_COMPLETION_SCHEMA_VERSION
        or completion.get("execution_plan_sha256") != execution_plan["plan_sha256"]
        or completion.get("physical_model_calls") != _V2_CALL_COUNT
        or completion.get("canonical_effect") is not False
        or completion.get("email_effect") is not False
        or completion.get("automatic_action_allowed") is not False
        or not isinstance(receipt_hashes, dict)
        or set(receipt_hashes) != {call["call_id"] for call in execution_plan["calls"]}
        or any(
            v1._sha256_file(
                output_root / v1.RESPONSE_DIRECTORY_NAME / f"{call_id}.json"
            )
            != digest
            for call_id, digest in receipt_hashes.items()
        )
        or v1._canonical_sha256(unsigned) != claimed
    ):
        raise v1.PilotStop("existing v2 completion is invalid")
    return completion


def execute_model_pilot_v2(
    *,
    provider_factory: Callable[[], ModelProvider],
    explicit_user_authorization: bool,
    replacement_plan_path: Path = V2_PLAN_PATH,
    output_root: Path = V2_OUTPUT_ROOT,
) -> dict[str, Any]:
    """Run the one approved v2 shadow pilot with no retry or side channels."""

    if not callable(provider_factory) or explicit_user_authorization is not True:
        raise v1.PilotStop("v2 execution requires explicit interactive user approval")
    readiness_report = check_v2_readiness(replacement_plan_path=replacement_plan_path)
    replacement = _load_v2_plan(replacement_plan_path)
    v1_state = _validate_v1_state(replacement["source_v1"])
    policy, contexts, _unused_plan, _audit, opening_sentinels = v1._readiness_components()
    execution_plan = _build_execution_plan(
        replacement,
        readiness={
            "strict_audit_sha256": readiness_report["strict_audit_sha256"],
            "policy_file_sha256": readiness_report["policy_file_sha256"],
        },
        contexts=contexts,
        policy=policy,
        v1_state=v1_state,
    )
    if output_root.expanduser().resolve() != V2_OUTPUT_ROOT.resolve():
        raise v1.PilotStop("v2 output root is pinned to its separate quarantine")
    with v1._pilot_lock(v1.QUARANTINE_ROOT):
        resolved_output = v1._validate_output_root(output_root, v1.QUARANTINE_ROOT)
        _write_or_validate(
            resolved_output / V2_EXECUTION_PLAN_NAME,
            execution_plan,
            label="v2 execution plan",
        )
        _write_or_validate(
            resolved_output / V2_AUTHORIZATION_NAME,
            _authorization_receipt(execution_plan),
            label="v2 authorization receipt",
        )
        completed = _completed_output(resolved_output, execution_plan)
        if completed is not None:
            return completed
        assignments = _load_or_create_blind_assignments(resolved_output, execution_plan)
        journal_path = resolved_output / V2_JOURNAL_NAME
        events = v1._load_journal(journal_path, plan_sha256=execution_plan["plan_sha256"])
        v1._assert_receipt_journal_coherence(
            output_root=resolved_output,
            plan=execution_plan,
            events=events,
        )
        if events:
            raise v1.PilotStop("v2 has durable journal state and cannot resume or retry")
        v1._append_event(
            journal_path,
            events,
            plan_sha256=execution_plan["plan_sha256"],
            event_kind="pilot_opened",
            call_id=None,
            details={
                "maximum_new_model_calls": _V2_CALL_COUNT,
                "maximum_new_reservation_usd": v1._decimal_text(
                    _V2_MAXIMUM_RESERVATION_USD
                ),
                "v1_charged_model_calls": _V1_CHARGED_CALLS,
                "v1_charged_usd": v1._decimal_text(_V1_CHARGED_USD),
                "provider": "openai_responses_api",
                "sdk_max_retries": 0,
                "email_effect": False,
                "canonical_effect": False,
            },
        )
        contexts_by_id = {context.packet_id: context for context in contexts}
        results: dict[str, dict[str, Any]] = {}
        for call in execution_plan["calls"]:
            context = contexts_by_id[call["packet_id"]]
            schema = v1._schema_for_stage(call["stage"])
            instructions = v1._instructions_for_stage(call["stage"])
            input_payload = v1._input_for_call(call, context, results, assignments)
            envelope_bytes = v1._request_envelope_bytes(
                call,
                schema=schema,
                instructions=instructions,
                input_payload=input_payload,
            )
            if envelope_bytes > v1.MAXIMUM_REQUEST_ENVELOPE_BYTES:
                raise v1.PilotStop("v2 request envelope exceeds its byte cap")
            v1._assert_runtime_safety(
                opening_sentinels=opening_sentinels,
                corpus_root=v1.CORPUS_ROOT,
                quarantine_root=v1.QUARANTINE_ROOT,
            )
            try:
                provider = provider_factory()
                v1._strict_provider(provider, allow_test_provider=False)
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
                    plan_sha256=execution_plan["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={
                        "reason": "provider_or_input_count_preflight_failed",
                        "call_id": call["call_id"],
                        "failure_type": type(exc).__name__,
                        "model_calls_charged": 0,
                    },
                )
                raise v1.PilotStop("v2 provider or input count preflight failed") from exc
            if (
                not isinstance(exact_input_tokens, int)
                or isinstance(exact_input_tokens, bool)
                or exact_input_tokens < 0
                or exact_input_tokens > call["maximum_input_tokens"]
            ):
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution_plan["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={
                        "reason": "exact_input_token_ceiling_exceeded",
                        "call_id": call["call_id"],
                        "model_calls_charged": 0,
                    },
                )
                raise v1.PilotStop("v2 exact input token count exceeds reservation")
            request_binding = {
                "call_id": call["call_id"],
                "packet_id": call["packet_id"],
                "stage": call["stage"],
                "role": call["role"],
                "model": call["model"],
                "reasoning_effort": call["reasoning_effort"],
                "schema_sha256": v1._canonical_sha256(schema),
                "instructions_sha256": v1._canonical_sha256(instructions),
                "input_sha256": v1._canonical_sha256(input_payload),
                "dependency_result_sha256s": {
                    dependency: v1._canonical_sha256(results[dependency]["payload"])
                    for dependency in call["dependencies"]
                },
                "request_envelope_bytes": envelope_bytes,
                "exact_input_tokens": exact_input_tokens,
                "store": False,
                "tools": [],
                "request_timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS,
                "sdk_max_retries": 0,
            }
            if call["stage"] in {"sol_committee", "sol_critic"}:
                request_binding["blind_mapping_sha256"] = v1._canonical_sha256(
                    v1._blind_mapping(call["packet_id"], assignments)
                )
            binding_sha256 = v1._canonical_sha256(request_binding)
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution_plan["plan_sha256"],
                event_kind="input_count_completed",
                call_id=call["call_id"],
                details={
                    "request_binding_sha256": binding_sha256,
                    "exact_input_tokens": exact_input_tokens,
                    "model_inference_started": False,
                },
            )
            v1._assert_runtime_safety(
                opening_sentinels=opening_sentinels,
                corpus_root=v1.CORPUS_ROOT,
                quarantine_root=v1.QUARANTINE_ROOT,
            )
            charged_before = _v2_charged_budget(execution_plan, events)
            reservation = v1._decimal(call["reservation_usd"], label="v2 reservation")
            if (
                charged_before["used_model_calls"] + 1 > _V2_CALL_COUNT
                or _V1_CHARGED_USD + charged_before["charged_usd"] + reservation
                > _CUMULATIVE_USD_CAP
            ):
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution_plan["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={
                        "reason": "pre_inference_cumulative_budget_gate_failed",
                        "call_id": call["call_id"],
                    },
                )
                raise v1.PilotStop("v2 pre-inference cumulative budget gate failed")
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution_plan["plan_sha256"],
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
                    instructions=instructions,
                    input_payload=copy.deepcopy(input_payload),
                )
                result_received = True
                if not isinstance(result, ProviderResult):
                    raise v1.PilotStop("v2 provider returned an invalid result")
                payload = v1._validate_stage_payload(
                    call, context, result.payload, results, assignments
                )
                metered_usage = v1._metered_usage(
                    call, result.metadata, policy["prices"], allow_test_provider=False
                )
                if metered_usage["total_input_tokens"] != exact_input_tokens:
                    raise v1.PilotStop("v2 provider usage differs from preflight count")
                receipt: dict[str, Any] = {
                    "schema_version": V2_RECEIPT_SCHEMA_VERSION,
                    "execution_plan_sha256": execution_plan["plan_sha256"],
                    "call_id": call["call_id"],
                    "request_binding_sha256": binding_sha256,
                    "payload": copy.deepcopy(payload),
                    "payload_sha256": v1._canonical_sha256(payload),
                    "provider_metadata": _redacted_provider_metadata(result.metadata),
                    "metered_usage": metered_usage,
                    "canonical_effect": False,
                    "email_effect": False,
                    "automatic_action_allowed": False,
                }
                receipt["receipt_sha256"] = v1._canonical_sha256(receipt)
                v1._write_json_exclusive(
                    resolved_output / v1.RESPONSE_DIRECTORY_NAME / f"{call['call_id']}.json",
                    receipt,
                )
            except Exception as exc:
                details: dict[str, Any] = {
                    "charged_reservation_usd": call["reservation_usd"],
                    "failure_type": type(exc).__name__,
                    "retry_allowed": False,
                }
                if isinstance(exc, v1.ContractError):
                    details["redacted_contract_diagnostic"] = v1._redacted_contract_diagnostic(call, exc)
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution_plan["plan_sha256"],
                    event_kind="call_failed" if result_received else "call_outcome_unknown",
                    call_id=call["call_id"],
                    details=details,
                )
                v1._append_event(
                    journal_path,
                    events,
                    plan_sha256=execution_plan["plan_sha256"],
                    event_kind="pilot_stopped",
                    call_id=None,
                    details={"reason": "call_failed", "call_id": call["call_id"]},
                )
                raise v1.PilotStop(f"v2 stopped at {call['call_id']}") from exc
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution_plan["plan_sha256"],
                event_kind="call_completed",
                call_id=call["call_id"],
                details={
                    "actual_cost_usd": metered_usage["cost_usd"],
                    "metered_usage": metered_usage,
                    "receipt_sha256": receipt["receipt_sha256"],
                },
            )
            results[call["call_id"]] = {
                "payload": copy.deepcopy(payload),
                "metered_usage": metered_usage,
                "receipt_sha256": receipt["receipt_sha256"],
            }
            v1._assert_runtime_safety(
                opening_sentinels=opening_sentinels,
                corpus_root=v1.CORPUS_ROOT,
                quarantine_root=v1.QUARANTINE_ROOT,
            )
        charged = _v2_charged_budget(execution_plan, events)
        if len(results) != _V2_CALL_COUNT:
            raise v1.PilotStop("v2 ended without all planned results")
        v1._append_event(
            journal_path,
            events,
            plan_sha256=execution_plan["plan_sha256"],
            event_kind="model_calls_completed",
            call_id=None,
            details={
                "physical_model_calls": _V2_CALL_COUNT,
                "charged_usd": v1._decimal_text(charged["charged_usd"]),
                "canonical_effect": False,
                "email_effect": False,
            },
        )
        completion: dict[str, Any] = {
            "schema_version": V2_COMPLETION_SCHEMA_VERSION,
            "execution_plan_sha256": execution_plan["plan_sha256"],
            "physical_model_calls": _V2_CALL_COUNT,
            "v1_charged_usd": v1._decimal_text(_V1_CHARGED_USD),
            "v2_charged_usd": v1._decimal_text(charged["charged_usd"]),
            "cumulative_charged_usd": v1._decimal_text(
                _V1_CHARGED_USD + charged["charged_usd"]
            ),
            "canonical_effect": False,
            "email_effect": False,
            "automatic_action_allowed": False,
            "broker_used": False,
            "receipt_file_sha256": {
                call["call_id"]: v1._sha256_file(
                    resolved_output
                    / v1.RESPONSE_DIRECTORY_NAME
                    / f"{call['call_id']}.json"
                )
                for call in execution_plan["calls"]
            },
        }
        completion["completion_sha256"] = v1._canonical_sha256(completion)
        v1._write_json_exclusive(resolved_output / V2_COMPLETION_NAME, completion)
        return completion


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    del args
    print(json.dumps(check_v2_readiness(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
