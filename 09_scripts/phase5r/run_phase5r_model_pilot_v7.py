"""Budget-limited v7 shadow pilot built from immutable v6 evidence.

This runner never resumes v6.  It uses the ten validated v6 analyst receipts
only in memory to complete five previously unattempted committee/critic pairs,
then runs nine previously unattempted source-locked diagnostic assessments.
The resulting 29 usable outputs are deliberately insufficient for the frozen
30-call review protocol, so completion is always a no-go with no review bundle.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from phase5r_llm_contract import ContractError
from phase5r_llm_provider import ModelProvider, ProviderResult
from phase5r_model_pilot_v6_contract import strict_schema_for_stage_v6
import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v6 as v6


V7_PLAN_PATH = (
    v1.ROOT
    / "08_reviews/phase5r_model_pilot/replacement_v7"
    / "phase5r_model_pilot_v7_plan.json"
)
V7_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v7"
V7_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v7_execution_plan.json"
V7_AUTHORIZATION_NAME = "phase5r_model_pilot_v7_authorization.json"
V7_COMPLETION_NAME = "phase5r_model_pilot_v7_completion.json"
V7_REPORT_NAME = "phase5r_model_pilot_v7_no_go_report.md"
V6_ROOT = v1.QUARANTINE_ROOT / "v6"
V6_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v6_execution_plan.json"
V6_AUTHORIZATION_NAME = "phase5r_model_pilot_v6_authorization.json"
V6_JOURNAL_NAME = "phase5r_model_pilot_v6_journal.jsonl"

V7_MAXIMUM_MODEL_CALLS = 19
V7_MAXIMUM_USD = Decimal("4.8240310")
V7_WORST_CASE_USD = Decimal("3.86232")


def _v7_plan(path: Path = V7_PLAN_PATH) -> dict[str, Any]:
    plan = v1._read_json_object(path, label="v7 replacement plan")
    claimed = plan.get("plan_sha256")
    unsigned = dict(plan)
    unsigned.pop("plan_sha256", None)
    if (
        plan.get("schema_version") != "phase5r_model_pilot_replacement_plan_v7"
        or plan.get("status") != "authorized_pending_sealed_execution_plan"
        or plan.get("execution_prohibited_without_explicit_runtime_authorization")
        is not False
        or claimed != v1._canonical_sha256(unsigned)
    ):
        raise v1.PilotStop("v7 replacement plan is invalid")
    authorization = plan.get("authorization")
    boundaries = plan.get("boundaries")
    remaining = plan.get("remaining_approved_budget")
    if (
        not isinstance(authorization, dict)
        or authorization.get("sdk_max_retries") != 0
        or authorization.get("physical_attempts_per_call") != 1
        or authorization.get("execution_requires_explicit_user_authorization")
        is not True
        or not isinstance(boundaries, dict)
        or any(
            boundaries.get(name) is not False
            for name in (
                "canonical_effect",
                "email_effect",
                "trading",
                "broker_or_account_access",
                "credential_storage",
                "scheduler_effect",
            )
        )
        or boundaries.get("shadow_only") is not True
        or boundaries.get("store") is not False
        or boundaries.get("tools") != []
        or not isinstance(remaining, dict)
        or remaining.get("maximum_new_model_calls") != V7_MAXIMUM_MODEL_CALLS
        or v1._decimal(remaining.get("maximum_new_usd"), label="v7 USD cap")
        != V7_MAXIMUM_USD
    ):
        raise v1.PilotStop("v7 replacement boundaries are invalid")
    return plan


def _v6_assignments(
    *, source_plan: dict[str, Any], contexts: list[v1.PacketContext]
) -> tuple[dict[str, dict[str, str]], str]:
    path = V6_ROOT / v1.BLIND_ASSIGNMENT_NAME
    payload = v1._read_json_object(path, label="v6 sealed blind assignments")
    claimed = payload.get("assignment_sha256")
    unsigned = dict(payload)
    unsigned.pop("assignment_sha256", None)
    rows = payload.get("rows")
    packet_ids = {context.packet_id for context in contexts}
    if (
        payload.get("schema_version") != v1.BLIND_ASSIGNMENT_SCHEMA_VERSION
        or payload.get("plan_sha256") != source_plan.get("plan_sha256")
        or payload.get("mapping_method") != "system_random_balanced_five_five"
        or claimed != v1._canonical_sha256(unsigned)
        or not isinstance(rows, dict)
        or set(rows) != packet_ids
    ):
        raise v1.PilotStop("v6 blind assignments are invalid")
    assignments = {
        packet_id: v1._blind_mapping(packet_id, {packet_id: rows[packet_id]})
        for packet_id in sorted(packet_ids)
    }
    if sum(row["A"] == "luna_assessment" for row in assignments.values()) != 5:
        raise v1.PilotStop("v6 blind assignments are not balanced")
    return assignments, v1._sha256_file(path)


def _v6_source_state(
    replacement: dict[str, Any], contexts: list[v1.PacketContext]
) -> dict[str, Any]:
    source = replacement.get("source_v6")
    if not isinstance(source, dict):
        raise v1.PilotStop("v7 source-v6 binding is missing")
    required_hashes = {
        V6_AUTHORIZATION_NAME: source.get("authorization_file_sha256"),
        V6_EXECUTION_PLAN_NAME: source.get("execution_plan_file_sha256"),
        V6_JOURNAL_NAME: source.get("journal_file_sha256"),
    }
    if any(
        not isinstance(expected, str)
        or v1._sha256_file(V6_ROOT / filename) != expected
        for filename, expected in required_hashes.items()
    ):
        raise v1.PilotStop("v6 immutable file binding changed")
    source_plan = v1._read_json_object(
        V6_ROOT / V6_EXECUTION_PLAN_NAME, label="v6 execution plan"
    )
    if source_plan.get("plan_sha256") != source.get("execution_plan_sha256"):
        raise v1.PilotStop("v6 execution plan self-hash changed")
    events = v1._load_journal(
        V6_ROOT / V6_JOURNAL_NAME, plan_sha256=source_plan["plan_sha256"]
    )
    if not events or events[-1].get("event_kind") != "pilot_stopped":
        raise v1.PilotStop("v6 is not terminal")
    calls = {call["call_id"]: call for call in source_plan["calls"]}
    completed_ids = [
        event["call_id"]
        for event in events
        if event.get("event_kind") == "call_completed"
    ]
    failed_ids = [
        event["call_id"]
        for event in events
        if event.get("event_kind") in {"call_failed", "call_outcome_unknown"}
    ]
    reserved_ids = [
        event["call_id"]
        for event in events
        if event.get("event_kind") == "call_reserved"
    ]
    if (
        len(completed_ids) != 10
        or len(failed_ids) != 1
        or len(reserved_ids) != 11
        or any(call_id not in calls for call_id in completed_ids + failed_ids)
    ):
        raise v1.PilotStop("v6 terminal call accounting is invalid")
    assignments, assignment_sha256 = _v6_assignments(
        source_plan=source_plan, contexts=contexts
    )
    contexts_by_id = {context.packet_id: context for context in contexts}
    results: dict[str, dict[str, Any]] = {}
    for call_id in completed_ids:
        call = calls[call_id]
        if call["stage"] not in {"luna_assessment", "terra_assessment"}:
            raise v1.PilotStop("v6 completed an unexpected stage")
        receipt = v1._validate_receipt(
            v1._receipt_path(V6_ROOT, call_id),
            call=call,
            plan_sha256=source_plan["plan_sha256"],
            prices=v1._readiness_components()[0]["prices"],
            allow_test_provider=False,
            allow_redacted_provider_response_id=True,
        )
        v1._validate_stage_payload(
            call,
            contexts_by_id[call["packet_id"]],
            receipt["payload"],
            {},
            assignments,
        )
        results[call_id] = v1._result_from_receipt(receipt)
    evaluation_packet_ids = sorted(
        {
            call["packet_id"]
            for call_id, call in calls.items()
            if call_id in results
        }
    )
    if len(evaluation_packet_ids) != 5 or any(
        v1._call_id(packet_id, stage) not in results
        for packet_id in evaluation_packet_ids
        for stage in ("luna_assessment", "terra_assessment")
    ):
        raise v1.PilotStop("v6 receipts do not form five complete analyst pairs")
    return {
        "plan": source_plan,
        "calls": calls,
        "results": results,
        "assignments": assignments,
        "blind_assignment_file_sha256": assignment_sha256,
        "evaluation_packet_ids": evaluation_packet_ids,
        "failed_ids": set(failed_ids),
        "terminal_ids": set(completed_ids + failed_ids),
    }


def _build_execution_plan(
    replacement: dict[str, Any],
    *,
    base_plan: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    selected = set(source["evaluation_packet_ids"])
    source_calls = source["calls"]

    def downstream_call(packet_id: str, stage: str, cohort_index: int) -> dict[str, Any]:
        existing = next(
            (
                call
                for call in source["plan"]["calls"]
                if call["packet_id"] == packet_id and call["stage"] == stage
            ),
            None,
        )
        if existing is not None:
            return copy.deepcopy(existing)
        template = next(
            call for call in source["plan"]["calls"] if call["stage"] == stage
        )
        assessment_dependencies = [
            v1._call_id(packet_id, "luna_assessment"),
            v1._call_id(packet_id, "terra_assessment"),
        ]
        call = {
            "call_id": v1._call_id(packet_id, stage),
            "packet_id": packet_id,
            "ticker": source_calls[assessment_dependencies[0]]["ticker"],
            "stage": stage,
            "role": template["role"],
            "model": template["model"],
            "reasoning_effort": template["reasoning_effort"],
            "dependencies": assessment_dependencies,
            "maximum_input_tokens": template["maximum_input_tokens"],
            "maximum_output_tokens": template["maximum_output_tokens"],
            "reservation_usd": template["reservation_usd"],
        }
        if stage == "sol_critic":
            call.update(
                {
                    "dependencies": [
                        *assessment_dependencies,
                        v1._call_id(packet_id, "sol_committee"),
                    ],
                    "control_probe_id": f"v7-critic-control-{cohort_index:02d}",
                    "control_expected": (
                        "unsupported" if cohort_index <= 3 else "supported"
                    ),
                }
            )
        return call

    ordered_selected = sorted(selected)
    committee_calls = [
        downstream_call(packet_id, "sol_committee", index)
        for index, packet_id in enumerate(ordered_selected, 1)
    ]
    critic_calls = [
        downstream_call(packet_id, "sol_critic", index)
        for index, packet_id in enumerate(ordered_selected, 1)
    ]
    diagnostics = [
        copy.deepcopy(call)
        for call in source["plan"]["calls"]
        if call["stage"] in {"luna_assessment", "terra_assessment"}
        and call["packet_id"] not in selected
        and call["call_id"] not in source["terminal_ids"]
    ]
    calls = committee_calls + critic_calls + diagnostics
    if (
        len(committee_calls) != 5
        or len(critic_calls) != 5
        or len(diagnostics) != 9
        or len(calls) != V7_MAXIMUM_MODEL_CALLS
        or len({call["call_id"] for call in calls}) != len(calls)
        or set(call["call_id"] for call in calls) & source["terminal_ids"]
    ):
        raise v1.PilotStop("v7 call layout would repeat or exceed v6 evidence")
    reservation = sum(
        (v1._decimal(call["reservation_usd"], label="v7 reservation") for call in calls),
        Decimal(0),
    )
    if reservation != V7_WORST_CASE_USD or reservation > V7_MAXIMUM_USD:
        raise v1.PilotStop("v7 reservation is outside remaining budget")
    execution: dict[str, Any] = {
        "schema_version": "phase5r_model_pilot_execution_plan_v7",
        "replacement_plan_sha256": replacement["plan_sha256"],
        "source_v6_execution_plan_sha256": source["plan"]["plan_sha256"],
        "source_v6_blind_assignment_file_sha256": source[
            "blind_assignment_file_sha256"
        ],
        "source_v6_evaluation_packet_ids": source["evaluation_packet_ids"],
        "calls": calls,
        "budget": {
            "maximum_physical_model_calls": V7_MAXIMUM_MODEL_CALLS,
            "maximum_usd": v1._decimal_text(V7_MAXIMUM_USD),
            "worst_case_reserved_usd": v1._decimal_text(reservation),
            "sdk_max_retries": 0,
            "maximum_output_tokens_per_call": v1.MAXIMUM_OUTPUT_TOKENS,
        },
        "boundaries": copy.deepcopy(replacement["boundaries"]),
        "contract": {
            "source_locked_analyst_stages": True,
            "strict_stage_schema_sha256": v6._schema_profile(),
            "failure_phase_codes_only": True,
        },
        "corpus_manifest": copy.deepcopy(base_plan["corpus_manifest"]),
        "strict_audit_sha256": base_plan["strict_audit_sha256"],
        "strict_completion_sha256": base_plan["strict_completion_sha256"],
        "policy_file_sha256": base_plan["policy_file_sha256"],
        "opening_sentinel_sha256": base_plan["opening_sentinel_sha256"],
        "evaluation_scope": "five_complete_v6_analyst_pairs_only",
        "review_materials": "prohibited_incomplete_frozen_30_call_protocol",
        "canonical_effect": False,
        "email_effect": False,
    }
    execution["plan_sha256"] = v1._canonical_sha256(execution)
    return execution


def check_v7_readiness(
    *, replacement_plan_path: Path = V7_PLAN_PATH
) -> dict[str, Any]:
    """Run v7's source, budget, and boundary checks with no provider."""

    try:
        replacement = _v7_plan(replacement_plan_path)
        policy, contexts, base_plan, _strict_audit, sentinels = (
            v1._readiness_components()
        )
        source = _v6_source_state(replacement, contexts)
        execution = _build_execution_plan(
            replacement, base_plan=base_plan, source=source
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
        "status": "ready_for_authorized_v7_shadow_execution",
        "planned_model_calls": len(execution["calls"]),
        "worst_case_reserved_usd": execution["budget"]["worst_case_reserved_usd"],
        "maximum_usd": execution["budget"]["maximum_usd"],
        "execution_plan_sha256": execution["plan_sha256"],
        "source_v6_receipts": len(source["results"]),
        "review_materials": execution["review_materials"],
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
        if v1._read_json_object(path, label=label) != payload:
            raise v1.PilotStop(f"{label} is not immutable")
        return
    v1._write_json_exclusive(path, payload)


def _authorization(execution: dict[str, Any]) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "schema_version": "phase5r_model_pilot_v7_authorization_v1",
        "execution_plan_sha256": execution["plan_sha256"],
        "replacement_plan_sha256": execution["replacement_plan_sha256"],
        "authorization_source": "explicit_user_authorization",
        "new_model_call_cap": V7_MAXIMUM_MODEL_CALLS,
        "new_usd_cap": v1._decimal_text(V7_MAXIMUM_USD),
        "sdk_max_retries": 0,
        "trading": False,
        "email_effect": False,
        "broker_or_account_access": False,
        "canonical_influence": False,
        "credential_storage": False,
    }
    receipt["authorization_sha256"] = v1._canonical_sha256(receipt)
    return receipt


def _assert_v7_execution_root(
    output_root: Path,
    *,
    quarantine_root: Path,
    allow_test_provider: bool,
) -> None:
    if not allow_test_provider and (
        output_root.expanduser().resolve() != V7_OUTPUT_ROOT.resolve()
        or quarantine_root.expanduser().resolve() != v1.QUARANTINE_ROOT.resolve()
    ):
        raise v1.PilotStop("v7 output root is pinned to its separate quarantine")
    if allow_test_provider:
        try:
            quarantine_root.expanduser().resolve().relative_to(v1.ROOT.resolve())
        except ValueError:
            return
        raise v1.PilotStop("v7 fixture quarantine must stay outside the repository")


def _v7_audit(
    *,
    output_root: Path,
    execution: dict[str, Any],
    events: list[dict[str, Any]],
    prices: dict[str, dict[str, Decimal]],
    allow_test_provider: bool,
) -> dict[str, Any]:
    calls = execution["calls"]
    if len(events) != 1 + 3 * len(calls):
        raise v1.PilotStop("v7 completed journal event count is invalid")
    opening = events[0]
    expected_opening = {
        "maximum_model_calls": V7_MAXIMUM_MODEL_CALLS,
        "maximum_usd": v1._decimal_text(V7_MAXIMUM_USD),
        "provider": "test_fixture" if allow_test_provider else "openai_responses_api",
        "sdk_max_retries": 0,
    }
    if (
        opening.get("event_kind") != "pilot_opened"
        or opening.get("call_id") is not None
        or opening.get("details") != expected_opening
    ):
        raise v1.PilotStop("v7 opening event is invalid")
    receipts: dict[str, dict[str, Any]] = {}
    cost = Decimal(0)
    for index, call in enumerate(calls):
        counted, reserved, completed = events[1 + index * 3 : 4 + index * 3]
        if (
            [counted.get("event_kind"), reserved.get("event_kind"), completed.get("event_kind")]
            != ["input_count_completed", "call_reserved", "call_completed"]
            or any(event.get("call_id") != call["call_id"] for event in (counted, reserved, completed))
        ):
            raise v1.PilotStop("v7 completed call journal order is invalid")
        receipt = v1._validate_receipt(
            v1._receipt_path(output_root, call["call_id"]),
            call=call,
            plan_sha256=execution["plan_sha256"],
            prices=prices,
            allow_test_provider=allow_test_provider,
            allow_redacted_provider_response_id=True,
        )
        binding = receipt["request_binding"]
        if (
            counted["details"].get("request_binding_sha256")
            != receipt["request_binding_sha256"]
            or counted["details"].get("exact_input_tokens")
            != binding.get("exact_input_tokens")
            or counted["details"].get("model_inference_started") is not False
            or reserved["details"].get("request_binding") != binding
            or reserved["details"].get("reservation_usd") != call["reservation_usd"]
            or completed["details"].get("receipt_sha256")
            != receipt["receipt_sha256"]
            or completed["details"].get("metered_usage")
            != receipt["metered_usage"]
        ):
            raise v1.PilotStop("v7 receipt/journal binding is invalid")
        cost += v1._decimal(receipt["metered_usage"]["cost_usd"], label="v7 cost")
        receipts[call["call_id"]] = receipt
    if cost > V7_MAXIMUM_USD:
        raise v1.PilotStop("v7 completed receipts exceed remaining USD cap")
    return {"receipts": receipts, "charged_usd": cost}


def _completion(
    *,
    output_root: Path,
    execution: dict[str, Any],
    events: list[dict[str, Any]],
    charged: Decimal,
) -> dict[str, Any]:
    receipt_hashes = {
        path.name: v1._sha256_file(path)
        for path in sorted((output_root / v1.RESPONSE_DIRECTORY_NAME).glob("*.json"))
    }
    completion: dict[str, Any] = {
        "schema_version": "phase5r_model_pilot_v7_completion_v1",
        "plan_sha256": execution["plan_sha256"],
        "state": "pilot_complete_no_go_incomplete_frozen_30_call_protocol",
        "go_no_go": "no_go_incomplete_30_output_protocol",
        "new_physical_model_calls": V7_MAXIMUM_MODEL_CALLS,
        "v6_charged_model_calls": 11,
        "cumulative_physical_model_calls": 30,
        "v7_exact_model_cost_usd": v1._decimal_text(charged),
        "v6_charged_cost_usd": "0.1759690",
        "cumulative_charged_cost_usd": v1._decimal_text(charged + Decimal("0.1759690")),
        "usable_provider_outputs": 29,
        "anonymous_review_materials": "not_generated_incomplete_frozen_30_call_protocol",
        "independent_review_complete": False,
        "promotion_eligible": False,
        "boundaries": {
            "canonical_effect": False,
            "email_effect": False,
            "trading": False,
            "broker_or_account_access": False,
            "scheduler_effect": False,
        },
        "journal": {"file_sha256": v1._sha256_file(output_root / v1.JOURNAL_NAME), "event_count": len(events)},
        "response_receipt_file_sha256": receipt_hashes,
    }
    completion["completion_sha256"] = v1._canonical_sha256(completion)
    return completion


def _report(completion: dict[str, Any]) -> bytes:
    return (
        "# Phase 5R v7 budget-limited shadow pilot\n\n"
        "Status: **NO-GO — the frozen 30-output review protocol is incomplete.**\n\n"
        f"v7 completed {completion['new_physical_model_calls']} new shadow-only "
        f"calls for `${completion['v7_exact_model_cost_usd']}`. Together with "
        "v6's terminal reservation, the original 30-call authorization is fully "
        "consumed but only 29 usable outputs exist.\n\n"
        "The v6 journal, plan, receipts, and cost record were read-only inputs. "
        "No response was retried; no email, trade, broker/account access, "
        "canonical change, credential storage, or scheduler change occurred.\n\n"
        "No anonymous review materials were generated: the frozen protocol forbids "
        "partial review rows or a partial-comparable evaluation. Independent human "
        "review remains unavailable until a separately authorized complete protocol "
        "exists.\n"
    ).encode("utf-8")


def execute_model_pilot_v7(
    *,
    provider_factory: Callable[[], ModelProvider],
    explicit_user_authorization: bool,
    replacement_plan_path: Path = V7_PLAN_PATH,
    output_root: Path = V7_OUTPUT_ROOT,
    allow_test_provider: bool = False,
    test_quarantine_root: Path | None = None,
) -> dict[str, Any]:
    """Execute exactly the sealed v7 calls, terminally stopping on any error."""

    if not callable(provider_factory) or explicit_user_authorization is not True:
        raise v1.PilotStop("v7 execution requires explicit user authorization")
    quarantine_root = test_quarantine_root if allow_test_provider else v1.QUARANTINE_ROOT
    if allow_test_provider and quarantine_root is None:
        raise v1.PilotStop("v7 fixture execution requires a fixture quarantine")
    assert quarantine_root is not None
    _assert_v7_execution_root(
        output_root, quarantine_root=quarantine_root, allow_test_provider=allow_test_provider
    )
    readiness = check_v7_readiness(replacement_plan_path=replacement_plan_path)
    if readiness.get("passed") is not True:
        raise v1.PilotStop("v7 readiness is blocked")
    replacement = _v7_plan(replacement_plan_path)
    policy, contexts, base_plan, _strict_audit, before_sentinels = v1._readiness_components()
    source = _v6_source_state(replacement, contexts)
    execution = _build_execution_plan(replacement, base_plan=base_plan, source=source)
    if readiness["execution_plan_sha256"] != execution["plan_sha256"]:
        raise v1.PilotStop("v7 sealed readiness plan changed before execution")
    with v1._pilot_lock(quarantine_root):
        root = v1._validate_output_root(output_root, quarantine_root)
        _write_or_validate(root / V7_EXECUTION_PLAN_NAME, execution, label="v7 execution plan")
        _write_or_validate(root / V7_AUTHORIZATION_NAME, _authorization(execution), label="v7 authorization")
        journal_path = root / v1.JOURNAL_NAME
        events = v1._load_journal(journal_path, plan_sha256=execution["plan_sha256"])
        completion_path = root / V7_COMPLETION_NAME
        if completion_path.exists():
            return v1._read_json_object(completion_path, label="v7 completion")
        if any(event["event_kind"] == "pilot_stopped" for event in events):
            raise v1.PilotStop("v7 has a durable stop event and cannot resume or retry")
        v1._assert_receipt_journal_coherence(output_root=root, plan=execution, events=events)
        v1._recover_or_stop_pending(
            output_root=root, plan=execution, events=events, prices=policy["prices"],
            allow_test_provider=allow_test_provider, allow_redacted_provider_response_id=True,
        )
        recovered_terminal = next(
            (
                event
                for event in events
                if event["event_kind"] in {"call_failed", "call_outcome_unknown"}
            ),
            None,
        )
        if recovered_terminal is not None:
            v1._append_event(
                journal_path,
                events,
                plan_sha256=execution["plan_sha256"],
                event_kind="pilot_stopped",
                call_id=None,
                details={
                    "reason": recovered_terminal["event_kind"],
                    "call_id": recovered_terminal["call_id"],
                },
            )
            raise v1.PilotStop("v7 prior provider outcome cannot be retried")
        if not events:
            v1._append_event(
                journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_opened", call_id=None,
                details={"maximum_model_calls": V7_MAXIMUM_MODEL_CALLS, "maximum_usd": v1._decimal_text(V7_MAXIMUM_USD), "provider": "test_fixture" if allow_test_provider else "openai_responses_api", "sdk_max_retries": 0},
            )
        contexts_by_id = {context.packet_id: context for context in contexts}
        results = copy.deepcopy(source["results"])
        for call in execution["calls"]:
            terminal = v1._terminal_event(events, call["call_id"])
            if terminal is not None:
                if terminal["event_kind"] != "call_completed":
                    raise v1.PilotStop("v7 call is terminal and cannot retry")
                receipt = v1._validate_receipt(v1._receipt_path(root, call["call_id"]), call=call, plan_sha256=execution["plan_sha256"], prices=policy["prices"], allow_test_provider=allow_test_provider, allow_redacted_provider_response_id=True)
                v1._validate_stage_payload(call, contexts_by_id[call["packet_id"]], receipt["payload"], results, source["assignments"])
                results[call["call_id"]] = v1._result_from_receipt(receipt)
                continue
            if v1._reserved_event(events, call["call_id"]) is not None:
                raise v1.PilotStop("v7 has an unrecovered reservation")
            if any(dependency not in results for dependency in call["dependencies"]):
                raise v1.PilotStop("v7 call dependency is incomplete")
            context = contexts_by_id[call["packet_id"]]
            schema = strict_schema_for_stage_v6(call["stage"])
            instructions = v6._instructions_for_call(call)
            input_payload = v6._input_for_call(call, context, results, source["assignments"])
            envelope_bytes = v1._request_envelope_bytes(call, schema=schema, instructions=instructions, input_payload=input_payload)
            if envelope_bytes > v1.MAXIMUM_REQUEST_ENVELOPE_BYTES:
                raise v1.PilotStop("v7 request envelope exceeds its byte cap")
            binding: dict[str, Any] = {"call_id": call["call_id"], "packet_id": call["packet_id"], "stage": call["stage"], "role": call["role"], "model": call["model"], "reasoning_effort": call["reasoning_effort"], "service_tier": "default", "request_timeout_seconds": v1.REQUEST_TIMEOUT_SECONDS, "billing_scope_attestation": "global_standard_no_regional_processing", "schema_sha256": v1._canonical_sha256(schema), "instructions_sha256": v1._canonical_sha256(instructions), "input_sha256": v1._canonical_sha256(input_payload), "dependency_result_sha256s": {dependency: v1._canonical_sha256(results[dependency]["payload"]) for dependency in call["dependencies"]}, "request_envelope_bytes": envelope_bytes, "store": False, "tools": [], "sdk_max_retries": 0}
            if call["stage"] in {"sol_committee", "sol_critic"}:
                binding["blind_mapping_sha256"] = v1._canonical_sha256(v1._blind_mapping(call["packet_id"], source["assignments"]))
            v1._enforce_runtime_safety(journal_path=journal_path, events=events, plan_sha256=execution["plan_sha256"], call_id=call["call_id"], opening_sentinels=before_sentinels, corpus_root=v1.CORPUS_ROOT, quarantine_root=quarantine_root)
            try:
                provider = provider_factory()
                v1._strict_provider(provider, allow_test_provider=allow_test_provider)
                exact_input_tokens = provider.count_input_tokens(role=call["role"], model=call["model"], reasoning_effort=call["reasoning_effort"], schema=copy.deepcopy(schema), instructions=instructions, input_payload=copy.deepcopy(input_payload))
            except Exception as exc:
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_stopped", call_id=None, details={"reason": "provider_or_input_count_preflight_failed", "call_id": call["call_id"], "failure_type": type(exc).__name__, "model_calls_charged": 0, "runtime_safety_issue": v1._runtime_safety_issue(opening_sentinels=before_sentinels, corpus_root=v1.CORPUS_ROOT, quarantine_root=quarantine_root)})
                raise v1.PilotStop("v7 provider or capability gate failed pre-inference") from exc
            if type(exact_input_tokens) is not int or not 0 <= exact_input_tokens <= call["maximum_input_tokens"]:
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
                raise v1.PilotStop("v7 exact input token count exceeds reservation")
            binding["exact_input_tokens"] = exact_input_tokens
            binding_sha256 = v1._canonical_sha256(binding)
            v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="input_count_completed", call_id=call["call_id"], details={"request_binding_sha256": binding_sha256, "exact_input_tokens": exact_input_tokens, "model_inference_started": False})
            charged = v1._charged_budget(execution, events)
            reservation = v1._decimal(call["reservation_usd"], label="v7 reservation")
            if charged["used_model_calls"] + 1 > V7_MAXIMUM_MODEL_CALLS or charged["charged_usd"] + reservation > V7_MAXIMUM_USD:
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
                raise v1.PilotStop("v7 pre-inference budget gate failed")
            v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="call_reserved", call_id=call["call_id"], details={"request_binding": binding, "request_binding_sha256": binding_sha256, "reservation_usd": call["reservation_usd"], "provider_constructed": True, "sdk_max_retries": 0, "maximum_physical_attempts": 1})
            result_received = False
            failure_phase = "provider_result_not_returned"
            try:
                result = provider.generate(role=call["role"], model=call["model"], reasoning_effort=call["reasoning_effort"], schema=copy.deepcopy(schema), instructions=instructions, input_payload=copy.deepcopy(input_payload))
                result_received = True
                failure_phase = "post_parse_provider_result_type_check"
                if not isinstance(result, ProviderResult):
                    raise v1.PilotStop("v7 provider returned an invalid result")
                failure_phase = "post_parse_contract_validation"
                payload = v6._validate_payload(call, context, result.payload, results, source["assignments"])
                failure_phase = "post_parse_metering_validation"
                metered = v1._metered_usage(call, result.metadata, policy["prices"], allow_test_provider=allow_test_provider)
                failure_phase = "post_parse_usage_reconciliation"
                if metered["total_input_tokens"] != exact_input_tokens:
                    raise v1.PilotStop("v7 provider usage differs from preflight")
                receipt: dict[str, Any] = {"schema_version": v1.RECEIPT_SCHEMA_VERSION, "plan_sha256": execution["plan_sha256"], "call_id": call["call_id"], "request_binding": binding, "request_binding_sha256": binding_sha256, "payload": copy.deepcopy(payload), "payload_sha256": v1._canonical_sha256(payload), "metered_usage": metered, "canonical_effect": False, "email_effect": False}
                failure_phase = "post_parse_provider_metadata_redaction"
                receipt["provider_metadata"] = v6._redacted_provider_metadata(result.metadata)
                failure_phase = "post_parse_receipt_persistence"
                receipt["receipt_sha256"] = v1._canonical_sha256(receipt)
                v1._write_json_exclusive(v1._receipt_path(root, call["call_id"]), receipt)
            except Exception as exc:
                details: dict[str, Any] = {"charged_reservation_usd": call["reservation_usd"], "failure_phase": failure_phase, "failure_type": type(exc).__name__, "retry_allowed": False, "runtime_safety_issue": v1._runtime_safety_issue(opening_sentinels=before_sentinels, corpus_root=v1.CORPUS_ROOT, quarantine_root=quarantine_root)}
                if isinstance(exc, ContractError):
                    details["redacted_contract_diagnostic"] = v1._redacted_contract_diagnostic(call, exc)
                event_kind = "call_failed" if result_received else "call_outcome_unknown"
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind=event_kind, call_id=call["call_id"], details=details)
                v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="pilot_stopped", call_id=None, details={"reason": event_kind, "call_id": call["call_id"]})
                raise v1.PilotStop(f"v7 stopped at {call['call_id']}") from exc
            v1._append_event(journal_path, events, plan_sha256=execution["plan_sha256"], event_kind="call_completed", call_id=call["call_id"], details={"actual_cost_usd": metered["cost_usd"], "metered_usage": metered, "receipt_sha256": receipt["receipt_sha256"], "recovered_after_interruption": False})
            results[call["call_id"]] = v1._result_from_receipt(receipt)
        audit = _v7_audit(output_root=root, execution=execution, events=events, prices=policy["prices"], allow_test_provider=allow_test_provider)
        completion = _completion(output_root=root, execution=execution, events=events, charged=audit["charged_usd"])
        _write_or_validate(root / V7_COMPLETION_NAME, completion, label="v7 completion")
        v1._write_bytes_exclusive(root / V7_REPORT_NAME, _report(completion))
        return completion
