#!/usr/bin/env python3
"""Fresh v10 Phase 5R collection with a critic-only 5,000-token cap.

v10 preserves the v6 source-locked contract and every non-critic 3,800-token
limit.  It is a new complete collection, not a retry or continuation of v9.
The one deliberate change responds to v9's privacy-safe ``response_incomplete``
terminal category: ``sol_critic`` alone receives a sealed 5,000-token limit.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterator

from phase5r_llm_provider import ModelProvider
import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v6 as v6
import run_phase5r_model_pilot_v9 as v9


V10_PLAN_PATH = (
    v1.ROOT
    / "08_reviews/phase5r_model_pilot/replacement_v10"
    / "phase5r_model_pilot_v10_plan.json"
)
V10_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v10"
V10_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v10_execution_plan.json"
V10_AUTHORIZATION_NAME = "phase5r_model_pilot_v10_authorization.json"
V10_JOURNAL_NAME = "phase5r_model_pilot_v10_journal.jsonl"
V10_COMPLETION_NAME = "phase5r_model_pilot_v10_completion.json"
V10_MAXIMUM_USD = Decimal("5.1348")
V10_OUTPUT_CAP_BY_STAGE = {
    "luna_assessment": 3_800,
    "terra_assessment": 3_800,
    "sol_committee": 3_800,
    "sol_critic": 5_000,
}
_BASE_BUILD_EXECUTION_PLAN = v6._build_execution_plan


def _v9_terminal() -> dict[str, Any]:
    source_plan = v9._load_v9_plan()
    journal_path = v9.V9_OUTPUT_ROOT / v9.V9_JOURNAL_NAME
    events = v1._load_journal(
        journal_path, plan_sha256="e4a7e371240b894210cd8e6e3c2ee398a922b3b823b35e1f86adc804a64fd48e"
    )
    terminal = next(
        (
            event
            for event in events
            if event["event_kind"] == "call_outcome_unknown"
        ),
        None,
    )
    if (
        source_plan.get("plan_sha256")
        != "882628b10d2d19b44f5952b599252b5db7522eddab9fb83ced26fda698dbae22"
        or not events
        or events[-1].get("event_kind") != "pilot_stopped"
        or not isinstance(terminal, dict)
        or terminal.get("details")
        != {
            "charged_reservation_usd": "0.2904",
            "failure_phase": "provider_result_not_returned",
            "failure_type": "ProviderError",
            "provider_failure_code": "response_incomplete",
            "retry_allowed": False,
            "runtime_safety_issue": None,
        }
    ):
        raise v1.PilotStop("v9 terminal evidence is invalid")
    return {
        "journal_file_sha256": v1._sha256_file(journal_path),
        "terminal_call_id": terminal["call_id"],
    }


def _load_v10_plan(path: Path = V10_PLAN_PATH) -> dict[str, Any]:
    plan = v6._load_v6_plan(path)
    terminal = _v9_terminal()
    if (
        plan.get("purpose")
        != "fresh independent complete 30-call shadow-only collection with only "
        "sol_critic output cap raised to 5000 after v9 response_incomplete"
        or plan.get("v9_terminal")
        != {
            "action": "preserve_immutable_no_resume_no_retry",
            "journal_file_sha256": terminal["journal_file_sha256"],
            "plan_sha256": "882628b10d2d19b44f5952b599252b5db7522eddab9fb83ced26fda698dbae22",
            "failure_phase": "provider_result_not_returned",
            "failure_type": "ProviderError",
            "provider_failure_code": "response_incomplete",
            "terminal_diagnosis_sha256": "11fc5547b4778ad446788fc30a69d9618d3148365ff40d2c7a51f16a805b316d",
        }
        or plan.get("v10_profile")
        != {
            "all_other_stage_maximum_output_tokens": 3_800,
            "critic_only_maximum_output_tokens": 5_000,
            "execution_requires_explicit_user_approval": True,
            "new_independent_model_call_cap": 30,
            "new_independent_usd_cap": "5.1348",
            "physical_attempts_per_call": 1,
            "sdk_max_retries": 0,
        }
    ):
        raise v1.PilotStop("v10 plan binding is invalid")
    return plan


def _reservation_usd(model: str, maximum_output_tokens: int) -> Decimal:
    price = v1.EXPECTED_PRICES[model]
    maximum_input = (
        Decimal(v1.MAXIMUM_INPUT_TOKENS)
        * price["input"]
        * price["cache_write_multiplier"]
        / Decimal(1_000_000)
    )
    maximum_output = (
        Decimal(maximum_output_tokens)
        * price["output"]
        / Decimal(1_000_000)
    )
    return (maximum_input + maximum_output) * v1.BILLING_SAFETY_MULTIPLIER


def _build_execution_plan_v10(
    replacement: dict[str, Any],
    *,
    base_plan: dict[str, Any],
    predecessor_journals: dict[str, str],
) -> dict[str, Any]:
    execution = _BASE_BUILD_EXECUTION_PLAN(
        replacement,
        base_plan=base_plan,
        predecessor_journals=predecessor_journals,
    )
    total_reservation = Decimal(0)
    for call in execution["calls"]:
        maximum_output_tokens = V10_OUTPUT_CAP_BY_STAGE.get(call["stage"])
        if maximum_output_tokens is None:
            raise v1.PilotStop("v10 call stage is invalid")
        call["maximum_output_tokens"] = maximum_output_tokens
        reservation = _reservation_usd(call["model"], maximum_output_tokens)
        call["reservation_usd"] = v1._decimal_text(reservation)
        total_reservation += reservation
    if total_reservation != V10_MAXIMUM_USD:
        raise v1.PilotStop("v10 reservation does not match its cap")
    execution["budget"] = {
        "maximum_physical_model_calls": 30,
        "maximum_usd": v1._decimal_text(V10_MAXIMUM_USD),
        "worst_case_reserved_usd": v1._decimal_text(total_reservation),
        "maximum_input_tokens_per_call": v1.MAXIMUM_INPUT_TOKENS,
        "maximum_output_tokens_per_call": 5_000,
        "maximum_output_tokens_by_stage": copy.deepcopy(
            V10_OUTPUT_CAP_BY_STAGE
        ),
        "maximum_request_envelope_bytes": v1.MAXIMUM_REQUEST_ENVELOPE_BYTES,
        "sdk_max_retries": 0,
    }
    execution["authorization"] = {
        "source": "interactive_user_approval_v10_critic_5000",
        "new_independent_model_call_cap": 30,
        "new_independent_usd_cap": v1._decimal_text(V10_MAXIMUM_USD),
        "sdk_max_retries": 0,
        "physical_attempts_per_call": 1,
    }
    execution["contract"]["maximum_output_tokens_by_stage"] = copy.deepcopy(
        V10_OUTPUT_CAP_BY_STAGE
    )
    execution["contract"]["v9_response_incomplete_remediation"] = (
        "sol_critic_only_5000"
    )
    execution["plan_sha256"] = v1._canonical_sha256(
        {key: value for key, value in execution.items() if key != "plan_sha256"}
    )
    return execution


@contextmanager
def _v10_engine_bindings() -> Iterator[None]:
    names = {
        "V6_OUTPUT_ROOT": V10_OUTPUT_ROOT,
        "V6_EXECUTION_PLAN_NAME": V10_EXECUTION_PLAN_NAME,
        "V6_AUTHORIZATION_NAME": V10_AUTHORIZATION_NAME,
        "V6_JOURNAL_NAME": V10_JOURNAL_NAME,
        "_build_execution_plan": _build_execution_plan_v10,
    }
    original = {name: getattr(v6, name) for name in names}
    try:
        for name, value in names.items():
            setattr(v6, name, value)
        yield
    finally:
        for name, value in original.items():
            setattr(v6, name, value)


def check_v10_readiness(
    *,
    replacement_plan_path: Path = V10_PLAN_PATH,
    quarantine_root: Path = v1.QUARANTINE_ROOT,
) -> dict[str, Any]:
    """Validate the v9 stop binding and v10 sealed plan without a provider."""

    try:
        replacement = _load_v10_plan(replacement_plan_path)
        with _v10_engine_bindings():
            readiness = v6.check_v6_readiness(
                replacement_plan_path=replacement_plan_path,
                quarantine_root=quarantine_root,
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
    if readiness.get("passed") is not True:
        return readiness
    return {
        **readiness,
        "status": "ready_for_explicit_v10_execution",
        "v10_replacement_plan_sha256": replacement["plan_sha256"],
        "v9_receipts_used_as_research": False,
        "critic_maximum_output_tokens": 5_000,
        "all_other_stage_maximum_output_tokens": 3_800,
        "new_collection_usd_cap": v1._decimal_text(V10_MAXIMUM_USD),
        "cumulative_training_upper_bound_usd": "6.081993",
    }


def execute_model_pilot_v10(
    *,
    provider_factory: Callable[[], ModelProvider],
    explicit_user_authorization: bool,
    replacement_plan_path: Path = V10_PLAN_PATH,
    output_root: Path = V10_OUTPUT_ROOT,
    allow_test_provider: bool = False,
    test_quarantine_root: Path | None = None,
) -> dict[str, Any]:
    """Run v10; a started call still terminates the fresh collection."""

    if explicit_user_authorization is not True:
        raise v1.PilotStop("v10 execution requires explicit user authorization")
    readiness = check_v10_readiness(
        replacement_plan_path=replacement_plan_path,
        quarantine_root=(
            test_quarantine_root if allow_test_provider else v1.QUARANTINE_ROOT
        ),
    )
    if readiness.get("passed") is not True:
        raise v1.PilotStop("v10 readiness is blocked")
    with _v10_engine_bindings():
        return v6.execute_model_pilot_v6(
            provider_factory=provider_factory,
            explicit_user_authorization=True,
            replacement_plan_path=replacement_plan_path,
            output_root=output_root,
            allow_test_provider=allow_test_provider,
            test_quarantine_root=test_quarantine_root,
        )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(check_v10_readiness(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
