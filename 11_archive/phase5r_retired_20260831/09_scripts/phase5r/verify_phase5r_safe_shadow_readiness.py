#!/usr/bin/env python3
"""Read-only Phase 5R economical safe-shadow readiness audit.

The audit validates disabled-by-default paid dependencies, recomputes the
documented cost envelopes, exercises the injected Responses adapter with an
in-memory fake client, inventories the local replay corpus, and confirms the
canonical daily workflow.  It never constructs a real provider client, reads a
credential or SMTP configuration, sends email, writes files, connects to a
broker, creates an order, or changes canonical state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from inventory_phase5r_llm_replay_corpus import (
    inventory_replay_readiness,
)
from phase5r_daily_common import ROOT
from phase5r_llm_provider import OpenAIResponsesProvider
from phase5r_llm_role_execution_ledger import (
    cycle_execution_ledger_path,
)
from run_phase5r_model_pilot import check_pilot_readiness


SCHEMA_VERSION = "phase5r_safe_shadow_readiness_v1"
POLICY_PATH = (
    ROOT / "00_project_control" / "phase5r_paid_dependency_policy.json"
)
MODEL_REGISTRY_PATH = (
    ROOT / "00_project_control" / "phase5r_llm_model_registry.json"
)
MARKET_REGISTRY_PATH = (
    ROOT
    / "00_project_control"
    / "phase5r_market_data_provider_registry.json"
)
CANONICAL_VERIFIER = (
    ROOT
    / "09_scripts"
    / "phase5r"
    / "verify_phase5r_c8_active_state_guard.py"
)
SHADOW_LABEL = "com.steven.phase5r.llmshadow"
SHADOW_PLIST = (
    Path.home() / "Library" / "LaunchAgents" / f"{SHADOW_LABEL}.plist"
)
REQUIREMENTS_LOCK = (
    ROOT
    / "09_scripts"
    / "phase5r"
    / "phase5r_model_pilot_requirements.lock.txt"
)


class ReadinessError(RuntimeError):
    """The readiness input is malformed or a closed invariant failed."""


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ReadinessError(f"missing or unsafe JSON: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ReadinessError(f"JSON root must be an object: {path}")
    return payload


def _check(
    checks: list[dict[str, Any]],
    check_id: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append(
        {
            "check_id": check_id,
            "passed": bool(passed),
            "detail": detail,
        }
    )


def _decimal(value: object, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise ReadinessError(f"{label} must be an exact decimal string")
    try:
        parsed = Decimal(value)
    except Exception as exc:
        raise ReadinessError(f"{label} is not a decimal") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ReadinessError(f"{label} must be finite and non-negative")
    return parsed


def _model_call_cost(
    *,
    price: dict[str, Any],
    calls: int,
    input_tokens: int,
    output_tokens: int,
    batch_discount: Decimal,
) -> Decimal:
    million = Decimal(1_000_000)
    standard = Decimal(calls) * (
        Decimal(input_tokens) * _decimal(price["input"], label="input price")
        + Decimal(output_tokens)
        * _decimal(price["output"], label="output price")
    ) / million
    return standard * (Decimal("1") - batch_discount)


def _cost_policy_checks(
    policy: dict[str, Any],
    checks: list[dict[str, Any]],
) -> None:
    required = {
        "schema_version",
        "effective_date",
        "decision",
        "canonical_workflow",
        "canonical_pipeline",
        "canonical_model_influence_enabled",
        "email_model_influence_enabled",
        "automatic_action_allowed",
        "broker_connection_allowed",
        "order_code_allowed",
        "model_api",
        "licensed_market_data",
        "cross_provider_challenger",
        "sec_corpus",
        "sources",
    }
    _check(
        checks,
        "policy.closed_top_level",
        set(policy) == required
        and policy.get("schema_version")
        == "phase5r_paid_dependency_policy_v1",
        f"fields={len(policy)}",
    )
    _check(
        checks,
        "policy.canonical_daily_only",
        policy.get("canonical_workflow") == "daily_decision"
        and policy.get("canonical_pipeline") == "phase5r_daily",
        (
            f"workflow={policy.get('canonical_workflow')!r};"
            f"pipeline={policy.get('canonical_pipeline')!r}"
        ),
    )
    false_boundaries = (
        "canonical_model_influence_enabled",
        "email_model_influence_enabled",
        "automatic_action_allowed",
        "broker_connection_allowed",
        "order_code_allowed",
    )
    _check(
        checks,
        "policy.fail_closed_boundaries",
        all(policy.get(field) is False for field in false_boundaries),
        f"false_fields={','.join(false_boundaries)}",
    )

    model_api = policy["model_api"]
    prices = model_api["pricing_usd_per_million_tokens"]
    expected_prices = {
        "gpt-5.6-luna": ("1.00", "0.10", "6.00"),
        "gpt-5.6-terra": ("2.50", "0.25", "15.00"),
        "gpt-5.6-sol": ("5.00", "0.50", "30.00"),
    }
    price_ok = set(prices) == set(expected_prices)
    for model, expected in expected_prices.items():
        row = prices.get(model, {})
        price_ok = price_ok and (
            row.get("input"),
            row.get("cached_input"),
            row.get("output"),
        ) == expected and row.get("cache_write_multiplier") == "1.25"
    _check(
        checks,
        "policy.official_prices_pinned",
        price_ok,
        f"models={','.join(sorted(prices))}",
    )
    pilot = model_api["pilot"]
    runtime_lock_sha256 = (
        hashlib.sha256(REQUIREMENTS_LOCK.read_bytes()).hexdigest()
        if REQUIREMENTS_LOCK.is_file()
        and not REQUIREMENTS_LOCK.is_symlink()
        else ""
    )
    runtime_pinned = (
        pilot.get("python_runtime_version") == "3.11.15"
        and pilot.get("openai_sdk_package") == "openai"
        and pilot.get("openai_sdk_version") == "2.49.0"
        and pilot.get("requirements_lock_path")
        == "09_scripts/phase5r/phase5r_model_pilot_requirements.lock.txt"
        and pilot.get("requirements_lock_sha256")
        == runtime_lock_sha256
    )
    _check(
        checks,
        "policy.pilot_runtime_pinned",
        runtime_pinned,
        (
            f"python={pilot.get('python_runtime_version')!r};"
            f"sdk={pilot.get('openai_sdk_version')!r};"
            f"lock={runtime_lock_sha256}"
        ),
    )

    pilot_authorization = (
        pilot.get("authorized") is True
        and pilot.get("maximum_physical_calls") == 30
        and pilot.get("maximum_usd") == "5.00"
        and policy["sec_corpus"].get("network_acquisition_authorized")
        is True
        and policy["sec_corpus"].get("required_contact_string_present")
        is True
        and policy["sec_corpus"].get("storage_budget_authorized") is True
    )
    later_spend_disabled = (
        model_api["qualification"].get("authorized") is False
        and model_api["live_shadow"].get("authorized") is False
        and policy["licensed_market_data"].get("authorized") is False
        and policy["cross_provider_challenger"].get("authorized") is False
    )
    _check(
        checks,
        "policy.pilot_only_authorization",
        pilot_authorization and later_spend_disabled,
        (
            f"pilot={model_api['pilot'].get('authorized')!r};"
            f"calls={model_api['pilot'].get('maximum_physical_calls')!r};"
            f"usd={model_api['pilot'].get('maximum_usd')!r};"
            f"qualification={model_api['qualification'].get('authorized')!r};"
            f"live={model_api['live_shadow'].get('authorized')!r}"
        ),
    )
    _check(
        checks,
        "policy.minimum_cost_routing",
        model_api["routing"]
        == {
            "unchanged_or_insufficient_evidence": (
                "local_only_zero_model_calls"
            ),
            "analyst_baseline": "gpt-5.6-terra_medium",
            "low_cost_candidate": (
                "gpt-5.6-luna_medium_bounded_same_packet_eval_only"
            ),
            "committee": (
                "gpt-5.6-sol_high_only_if_classification_may_change"
            ),
            "critic": (
                "gpt-5.6-sol_high_only_for_high_impact_or_disagreement"
            ),
            "cross_provider_challenger": (
                "deferred_not_required_for_initial_shadow"
            ),
            "multi_agent": "disabled",
        },
        f"routing={model_api['routing']}",
    )

    pilot = model_api["pilot"]
    discount = _decimal(
        model_api["batch_discount_fraction"],
        label="batch discount",
    )
    pilot_input = int(pilot["maximum_input_tokens_per_call"])
    pilot_output = int(pilot["maximum_output_tokens_per_call"])
    pilot_standard_cost = sum(
        (
            _model_call_cost(
                price=prices[model],
                calls=10,
                input_tokens=pilot_input,
                output_tokens=pilot_output,
                batch_discount=Decimal("0"),
            )
            for model in (
                "gpt-5.6-luna",
                "gpt-5.6-terra",
                "gpt-5.6-sol",
            )
        ),
        Decimal("0"),
    )
    pilot_cache_write_worst = sum(
        (
            (
                Decimal(pilot_input)
                * _decimal(prices[model]["input"], label="input price")
                * _decimal(
                    prices[model]["cache_write_multiplier"],
                    label="cache-write multiplier",
                )
                + Decimal(pilot_output)
                * _decimal(prices[model]["output"], label="output price")
            )
            * Decimal(10)
            / Decimal(1_000_000)
            for model in (
                "gpt-5.6-luna",
                "gpt-5.6-terra",
                "gpt-5.6-sol",
            )
        ),
        Decimal("0"),
    )
    pilot_reserved = pilot_cache_write_worst * _decimal(
        pilot["billing_safety_multiplier"],
        label="billing safety multiplier",
    )
    qualification = model_api["qualification"]
    assumed_input = int(qualification["assumed_input_tokens_per_call"])
    assumed_output = int(qualification["assumed_output_tokens_per_call"])
    qualification_terra = _model_call_cost(
        price=prices["gpt-5.6-terra"],
        calls=250,
        input_tokens=assumed_input,
        output_tokens=assumed_output,
        batch_discount=discount,
    ) + _model_call_cost(
        price=prices["gpt-5.6-sol"],
        calls=100,
        input_tokens=assumed_input,
        output_tokens=assumed_output,
        batch_discount=discount,
    )
    qualification_luna = _model_call_cost(
        price=prices["gpt-5.6-luna"],
        calls=250,
        input_tokens=assumed_input,
        output_tokens=assumed_output,
        batch_discount=discount,
    ) + _model_call_cost(
        price=prices["gpt-5.6-sol"],
        calls=100,
        input_tokens=assumed_input,
        output_tokens=assumed_output,
        batch_discount=discount,
    )
    estimates_ok = (
        pilot_standard_cost
        == _decimal(
            pilot["estimated_standard_usd_without_cache_writes"],
            label="standard pilot estimate",
        )
        and pilot_cache_write_worst
        == _decimal(
            pilot["maximum_worst_case_usd_with_cache_writes"],
            label="cache-write pilot estimate",
        )
        and pilot_reserved
        == _decimal(
            pilot[
                "maximum_worst_case_usd_with_cache_writes_and_billing_safety"
            ],
            label="reserved pilot estimate",
        )
        and qualification_terra
        == _decimal(
            model_api["qualification"][
                "estimated_batch_usd_if_terra_analyst"
            ],
            label="Terra qualification estimate",
        )
        and qualification_luna
        == _decimal(
            model_api["qualification"][
                "estimated_batch_usd_if_luna_noninferior"
            ],
            label="Luna qualification estimate",
        )
        and pilot_reserved <= _decimal(
            pilot["maximum_usd"],
            label="pilot maximum USD",
        )
        and qualification_terra
        <= _decimal(
            model_api["qualification"]["maximum_usd"],
            label="qualification maximum USD",
        )
    )
    _check(
        checks,
        "policy.cost_estimates_recomputed",
        estimates_ok,
        (
            f"pilot_standard_usd={pilot_standard_cost};"
            f"pilot_cache_write_worst_usd={pilot_cache_write_worst};"
            f"pilot_reserved_usd={pilot_reserved};"
            f"qualification_terra_batch_usd={qualification_terra};"
            f"qualification_luna_batch_usd={qualification_luna}"
        ),
    )


def _adapter_check(checks: list[dict[str, Any]]) -> None:
    class Responses:
        def __init__(self) -> None:
            self.request: dict[str, Any] = {}

        def create(self, **kwargs: Any) -> dict[str, Any]:
            self.request = kwargs
            return {
                "id": "resp_local_readiness_fixture",
                "status": "completed",
                "model": "gpt-5.6-terra",
                "service_tier": "default",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"ok":true}',
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 5,
                    "total_tokens": 105,
                    "input_tokens_details": {
                        "cached_tokens": 20,
                        "cache_write_tokens": 10,
                    },
                },
            }

    class Client:
        def __init__(self) -> None:
            self.responses = Responses()

    client = Client()
    result = OpenAIResponsesProvider(
        client,
        max_output_tokens=100,
    ).generate(
        role="analyst",
        model="gpt-5.6-terra",
        reasoning_effort="medium",
        schema={
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        },
        instructions="Return the fixture schema.",
        input_payload={"local_fixture": True},
    )
    expected_usage = {
        "input_tokens": 90,
        "output_tokens": 5,
        "cached_input_tokens": 20,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 0,
    }
    request = client.responses.request
    passed = (
        result.metadata.get("transport") == "openai_responses_api"
        and result.metadata.get("usage") == expected_usage
        and request.get("tools") == []
        and request.get("store") is False
        and request.get("service_tier") == "default"
        and request.get("prompt_cache_options") == {"mode": "explicit"}
    )
    _check(
        checks,
        "adapter.responses_usage_and_cache_normalized",
        passed,
        (
            f"usage={result.metadata.get('usage')};"
            f"cache={request.get('prompt_cache_options')}"
        ),
    )


def _canonical_check(
    checks: list[dict[str, Any]],
    *,
    static_only: bool,
) -> None:
    command = [sys.executable, str(CANONICAL_VERIFIER), "--json"]
    if static_only:
        command.append("--static-only")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=30,
        check=False,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {}
    _check(
        checks,
        "canonical.daily_guard",
        completed.returncode == 0 and payload.get("passed") is True,
        (
            f"exit_code={completed.returncode};"
            f"workflow={payload.get('canonical_workflow')!r};"
            f"pipeline={payload.get('canonical_pipeline')!r}"
        ),
    )


def _shadow_job_status(
    checks: list[dict[str, Any]],
    *,
    static_only: bool,
) -> None:
    if static_only:
        _check(
            checks,
            "launchd.shadow_not_installed",
            not SHADOW_PLIST.exists(),
            f"plist_exists={SHADOW_PLIST.exists()};runtime=skipped",
        )
        return
    completed = subprocess.run(
        [
            "launchctl",
            "print",
            f"gui/{os.getuid()}/{SHADOW_LABEL}",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    _check(
        checks,
        "launchd.shadow_not_installed_or_loaded",
        completed.returncode != 0 and not SHADOW_PLIST.exists(),
        (
            f"loaded={completed.returncode == 0};"
            f"plist_exists={SHADOW_PLIST.exists()}"
        ),
    )


def audit(*, static_only: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    policy = _read_json(POLICY_PATH)
    _cost_policy_checks(policy, checks)

    registry = _read_json(MODEL_REGISTRY_PATH)
    registry_disabled = (
        registry.get("mode") == "offline_fixture"
        and registry.get("live_shadow_enabled") is False
        and registry.get("canonical_influence_enabled") is False
        and registry.get("email_eligible") is False
        and registry.get("automatic_action_allowed") is False
    )
    _check(
        checks,
        "registry.model_influence_disabled",
        registry_disabled,
        (
            f"mode={registry.get('mode')!r};"
            f"live={registry.get('live_shadow_enabled')!r};"
            f"canonical={registry.get('canonical_influence_enabled')!r}"
        ),
    )

    market = _read_json(MARKET_REGISTRY_PATH)
    market_disabled = (
        market.get("mode") == "offline_fixture"
        and market.get("action_grade_enabled") is False
        and market.get("canonical_influence_enabled") is False
        and market.get("network_enabled") is False
        and market.get("synthetic_fixture_only") is True
    )
    _check(
        checks,
        "registry.licensed_market_data_disabled",
        market_disabled,
        (
            f"mode={market.get('mode')!r};"
            f"action_grade={market.get('action_grade_enabled')!r};"
            f"network={market.get('network_enabled')!r}"
        ),
    )

    ledger_path = cycle_execution_ledger_path(
        date.fromisoformat("2026-07-27")
    )
    try:
        ledger_path.resolve(strict=False).relative_to(ROOT.resolve())
        outside_repository = False
    except ValueError:
        outside_repository = True
    _check(
        checks,
        "ledger.fixed_private_cycle_path",
        outside_repository
        and "Library/Application Support/Phase5R/llm_execution"
        in ledger_path.as_posix()
        and ledger_path.name == "phase5r-2026-07-27.ledger.json",
        f"path={ledger_path}",
    )

    _adapter_check(checks)
    _canonical_check(checks, static_only=static_only)
    _shadow_job_status(checks, static_only=static_only)

    inventory = inventory_replay_readiness(
        pilot_packet_count=int(
            policy["sec_corpus"]["pilot_target_packets"]
        ),
        target_packet_count=int(
            policy["sec_corpus"]["qualification_target_packets"]
        ),
    )
    inventory_pilot = inventory["stage_readiness"]["pilot"]
    frozen_pilot = check_pilot_readiness()
    _check(
        checks,
        "corpus.frozen_pilot_readiness",
        frozen_pilot.get("passed") is True
        and frozen_pilot.get("provider_constructed") is False
        and frozen_pilot.get("network_used") is False
        and frozen_pilot.get("files_written") is False,
        (
            f"passed={frozen_pilot.get('passed')!r};"
            f"packets={frozen_pilot.get('packet_count')!r};"
            f"provider_constructed="
            f"{frozen_pilot.get('provider_constructed')!r};"
            f"network_used={frozen_pilot.get('network_used')!r}"
        ),
    )
    qualification = inventory["stage_readiness"]["qualification"]
    _check(
        checks,
        "corpus.inventory_read_only",
        inventory["boundaries"].get("network_used") is False
        and inventory["boundaries"].get("files_written") is False
        and inventory["boundaries"].get("provider_api_used") is False,
        (
            f"inventory_pilot_complete="
            f"{inventory_pilot['locally_complete_packet_count']};"
            f"qualification_complete="
            f"{qualification['locally_complete_packet_count']};"
            f"issuers={qualification['selected_issuer_count']}"
        ),
    )

    safety_passed = all(row["passed"] for row in checks)
    external_blockers: list[str] = []
    sec = policy["sec_corpus"]
    if sec.get("required_contact_string_present") is not True:
        external_blockers.append("sec_contact_string")
    if sec.get("storage_budget_authorized") is not True:
        external_blockers.append("corpus_storage_budget")
    if frozen_pilot.get("passed") is not True:
        external_blockers.append("complete_frozen_pilot_corpus")
    if policy["model_api"]["pilot"].get("authorized") is not True:
        external_blockers.append("pilot_call_and_usd_authorization")
    external_blockers.append("external_provider_authentication")
    external_blockers.append("independent_transition_and_citation_reviews")

    return {
        "schema_version": SCHEMA_VERSION,
        "safety_controls_passed": safety_passed,
        "local_controls_ready": safety_passed,
        "live_shadow_launch_ready": (
            safety_passed and not external_blockers
        ),
        "checks": checks,
        "replay_status": {
            "pilot_ready": frozen_pilot.get("passed") is True,
            "pilot_complete_packets": frozen_pilot.get("packet_count", 0),
            "qualification_ready": qualification[
                "readiness_gate_passed"
            ],
            "qualification_complete_packets": qualification[
                "locally_complete_packet_count"
            ],
            "qualification_selected_issuers": qualification[
                "selected_issuer_count"
            ],
            "typical_storage_estimate_bytes": inventory[
                "storage_estimates"
            ]["qualification_typical_projected_total_bytes"],
            "authorized_storage_ceiling_bytes": policy["sec_corpus"][
                "maximum_local_storage_bytes"
            ],
        },
        "external_blockers": external_blockers,
        "boundaries": {
            "files_written": False,
            "network_used": False,
            "real_provider_client_constructed": False,
            "provider_invoked": False,
            "credential_read": False,
            "smtp_config_read": False,
            "email_attempted": False,
            "canonical_effect": False,
            "broker_connected": False,
            "broker_account_read": False,
            "order_code_created": False,
            "trade_placed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-launch-ready", action="store_true")
    args = parser.parse_args()
    try:
        result = audit(static_only=args.static_only)
    except (ReadinessError, OSError, ValueError) as exc:
        result = {
            "schema_version": SCHEMA_VERSION,
            "safety_controls_passed": False,
            "live_shadow_launch_ready": False,
            "error": type(exc).__name__,
            "boundaries": {
                "files_written": False,
                "provider_invoked": False,
                "credential_read": False,
                "email_attempted": False,
            },
        }
    if args.json:
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(
            "phase5r_safe_shadow_readiness="
            f"{'passed' if result.get('safety_controls_passed') else 'failed'} "
            "live_shadow_launch_ready="
            f"{str(result.get('live_shadow_launch_ready') is True).lower()} "
            "provider_invoked=false email_attempted=false"
        )
    if args.require_launch_ready:
        return 0 if result.get("live_shadow_launch_ready") is True else 1
    return 0 if result.get("safety_controls_passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
