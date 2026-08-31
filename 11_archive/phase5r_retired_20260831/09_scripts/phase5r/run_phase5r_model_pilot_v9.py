#!/usr/bin/env python3
"""Fresh 30-output Phase 5R collection gated by the completed v8 qualification.

v9 reuses the already-tested v6 collection engine without resuming or
combining any earlier pilot.  The engine is rebound only to v9's separate plan
and quarantine paths for the duration of one process.  v8 is read-only proof
that the exact provider path qualified; it contributes no research receipt.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from phase5r_llm_provider import ModelProvider
import run_phase5r_model_pilot as v1
import run_phase5r_model_pilot_v6 as v6
import run_phase5r_model_pilot_v8_qualification as v8


V9_PLAN_PATH = (
    v1.ROOT
    / "08_reviews/phase5r_model_pilot/replacement_v9"
    / "phase5r_model_pilot_v9_plan.json"
)
V9_OUTPUT_ROOT = v1.QUARANTINE_ROOT / "v9"
V9_EXECUTION_PLAN_NAME = "phase5r_model_pilot_v9_execution_plan.json"
V9_AUTHORIZATION_NAME = "phase5r_model_pilot_v9_authorization.json"
V9_JOURNAL_NAME = "phase5r_model_pilot_v9_journal.jsonl"
V9_COMPLETION_NAME = "phase5r_model_pilot_v9_completion.json"


def _v8_completion() -> dict[str, Any]:
    plan = v8._load_v8_plan()
    completion_path = v8.V8_OUTPUT_ROOT / v8.V8_COMPLETION_NAME
    completion = v1._read_json_object(
        completion_path, label="v8 qualification completion"
    )
    claimed = completion.get("completion_sha256")
    unsigned = dict(completion)
    unsigned.pop("completion_sha256", None)
    if (
        claimed != v1._canonical_sha256(unsigned)
        or completion.get("schema_version")
        != "phase5r_model_pilot_v8_qualification_completion_v1"
        or completion.get("execution_plan_sha256")
        != "eb5e321e537e314be9b40cadc332890ca991d652a44e5dade5de19c6beb29ecf"
        or completion.get("passed") is not True
        or completion.get("physical_model_calls") != 3
        or completion.get("collection_authorized") is not False
        or completion.get("exact_model_cost_usd") != "0.00369"
        or plan.get("plan_sha256")
        != "d18bbe549274587fe99a5199a413fb4245a00a19eefdad5da6f87ac60da29a11"
    ):
        raise v1.PilotStop("v8 qualification completion is invalid")
    return completion


def _load_v9_plan(path: Path = V9_PLAN_PATH) -> dict[str, Any]:
    plan = v6._load_v6_plan(path)
    completion = _v8_completion()
    staged = plan.get("v8_qualification")
    if staged != {
        "action": "passed_then_preserve_read_only",
        "completion_sha256": completion["completion_sha256"],
        "execution_plan_sha256": completion["execution_plan_sha256"],
        "plan_sha256": "d18bbe549274587fe99a5199a413fb4245a00a19eefdad5da6f87ac60da29a11",
        "physical_model_calls": 3,
        "qualification_exact_cost_usd": "0.00369",
    }:
        raise v1.PilotStop("v9 qualification binding is invalid")
    if (
        plan.get("purpose")
        != "fresh independent complete 30-call shadow-only collection after "
        "passed v8 qualification; no v1-v7 receipt is read, reused, or combined"
    ):
        raise v1.PilotStop("v9 purpose binding is invalid")
    return plan


@contextmanager
def _v9_engine_bindings() -> Iterator[None]:
    """Temporarily bind the v6 engine to v9-only immutable paths."""

    names = {
        "V6_OUTPUT_ROOT": V9_OUTPUT_ROOT,
        "V6_EXECUTION_PLAN_NAME": V9_EXECUTION_PLAN_NAME,
        "V6_AUTHORIZATION_NAME": V9_AUTHORIZATION_NAME,
        "V6_JOURNAL_NAME": V9_JOURNAL_NAME,
    }
    original = {name: getattr(v6, name) for name in names}
    try:
        for name, value in names.items():
            setattr(v6, name, value)
        yield
    finally:
        for name, value in original.items():
            setattr(v6, name, value)


def check_v9_readiness(
    *, replacement_plan_path: Path = V9_PLAN_PATH,
    quarantine_root: Path = v1.QUARANTINE_ROOT,
) -> dict[str, Any]:
    """Run the v8 binding and full v9 collection readiness without a provider."""

    try:
        replacement = _load_v9_plan(replacement_plan_path)
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
    readiness = v6.check_v6_readiness(
        replacement_plan_path=replacement_plan_path,
        quarantine_root=quarantine_root,
    )
    if readiness.get("passed") is not True:
        return readiness
    return {
        **readiness,
        "status": "ready_for_explicit_v9_fresh_collection_execution",
        "v9_replacement_plan_sha256": replacement["plan_sha256"],
        "v8_qualification_passed": True,
        "v8_qualification_output_used_as_research": False,
        "new_collection_model_call_cap": 30,
        "new_collection_usd_cap": "5.00",
        "combined_training_budget_upper_bound_usd": "5.87120",
    }


def execute_model_pilot_v9(
    *,
    provider_factory: Callable[[], ModelProvider],
    explicit_user_authorization: bool,
    replacement_plan_path: Path = V9_PLAN_PATH,
    output_root: Path = V9_OUTPUT_ROOT,
    allow_test_provider: bool = False,
    test_quarantine_root: Path | None = None,
) -> dict[str, Any]:
    """Execute the new v9 collection; any started call remains terminal."""

    if explicit_user_authorization is not True:
        raise v1.PilotStop("v9 execution requires explicit user authorization")
    readiness = check_v9_readiness(
        replacement_plan_path=replacement_plan_path,
        quarantine_root=(
            test_quarantine_root if allow_test_provider else v1.QUARANTINE_ROOT
        ),
    )
    if readiness.get("passed") is not True:
        raise v1.PilotStop("v9 readiness is blocked")
    with _v9_engine_bindings():
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
    print(
        json.dumps(
            check_v9_readiness(), sort_keys=True, separators=(",", ":")
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
