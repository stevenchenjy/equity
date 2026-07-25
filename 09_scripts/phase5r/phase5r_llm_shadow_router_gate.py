#!/usr/bin/env python3
"""Closed adapter from a local routing envelope to the Phase 5R planner.

This module validates explicit, operator-supplied routing inputs and invokes
the deterministic cost-aware planner.  It has no provider construction,
network, credential, email, canonical-decision, broker, order, or trade
capability.

An exact-role, durable budget executor now exists for offline fixtures.  Live
provider authority remains deliberately absent, so this gate still blocks
every planned external call until an explicit, cost-authorized live adapter
preserves that executor contract.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from phase5r_daily_common import canonical_sha256
from phase5r_llm_contract import ContractError, response_schema
from phase5r_llm_cost_aware_router import (
    CycleCeilings,
    CycleUsage,
    InferencePlan,
    RoleCallSpec,
    RouterError,
    RouterPolicy,
    RoutingSignals,
    plan_inference,
    semantic_sha256,
)
from phase5r_llm_role_execution_ledger import (
    LEDGER_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
)


SHADOW_ROUTER_ENVELOPE_SCHEMA_VERSION = (
    "phase5r_llm_shadow_router_envelope_v1"
)
SHADOW_ROUTER_GATE_RECEIPT_SCHEMA_VERSION = (
    "phase5r_llm_shadow_router_gate_receipt_v1"
)
MAX_ROUTER_ENVELOPE_BYTES = 256 * 1024
PRIMARY_PROVIDER = "codex_cli_external_auth"
CHALLENGER_PROVIDER = "anthropic_messages_injected_client"
CHALLENGER_PROMPT_VERSION = "phase5r_blinded_challenger_v1"


def _closed_object(
    value: object,
    *,
    label: str,
    fields: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ContractError(f"{label} fields do not match the closed contract")
    return value


def _one_line(value: object, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character in value for character in "\r\n")
    ):
        raise ContractError(f"{label} must be one non-empty trimmed line")
    return value


def _boolean(value: object, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractError(f"{label} must be boolean")
    return value


def _integer(
    value: object,
    *,
    label: str,
    minimum: int = 0,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
    ):
        raise ContractError(f"{label} must be an integer >= {minimum}")
    return value


def _decimal(
    value: object,
    *,
    label: str,
    positive: bool,
) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractError(f"{label} must be an exact decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ContractError(f"{label} is not a valid decimal") from exc
    if (
        not parsed.is_finite()
        or (parsed <= 0 if positive else parsed < 0)
    ):
        comparator = "> 0" if positive else ">= 0"
        raise ContractError(f"{label} must be finite and {comparator}")
    return parsed


def _cycle_date(value: object, *, label: str) -> date:
    text = _one_line(value, label=label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise ContractError(f"{label} must be YYYY-MM-DD") from exc
    if parsed.isoformat() != text:
        raise ContractError(f"{label} must use canonical YYYY-MM-DD")
    return parsed


def _read_envelope(path: Path) -> dict[str, Any]:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ContractError("router envelope requires O_NOFOLLOW support")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise ContractError("router envelope is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or metadata.st_size <= 0
            or metadata.st_size > MAX_ROUTER_ENVELOPE_BYTES
        ):
            raise ContractError(
                "router envelope must be one owned regular file"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            payload = json.load(handle)
    except ContractError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError("router envelope is not valid JSON") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise ContractError("router envelope must be one JSON object")
    return payload


def _role_spec(
    row: object,
    *,
    registry: Mapping[str, Any],
) -> RoleCallSpec:
    payload = _closed_object(
        row,
        label="router role spec",
        fields={
            "role",
            "provider",
            "model",
            "reasoning_effort",
            "prompt_version",
            "response_schema_sha256",
            "max_input_tokens",
            "max_output_tokens",
            "max_usd",
        },
    )
    role = _one_line(payload["role"], label="router role")
    provider = _one_line(
        payload["provider"],
        label=f"{role}.provider",
    )
    model = _one_line(payload["model"], label=f"{role}.model")
    reasoning_effort = _one_line(
        payload["reasoning_effort"],
        label=f"{role}.reasoning_effort",
    )
    prompt_version = _one_line(
        payload["prompt_version"],
        label=f"{role}.prompt_version",
    )
    schema_sha256 = _one_line(
        payload["response_schema_sha256"],
        label=f"{role}.response_schema_sha256",
    )
    if role not in {"analyst", "committee", "critic", "challenger"}:
        raise ContractError("router role is outside the closed role set")
    expected_schema_sha256 = canonical_sha256(response_schema(role))
    if schema_sha256 != expected_schema_sha256:
        raise ContractError(f"{role} router schema binding is stale")
    if role == "challenger":
        if (
            provider != CHALLENGER_PROVIDER
            or not model.startswith("claude-")
            or prompt_version != CHALLENGER_PROMPT_VERSION
        ):
            raise ContractError(
                "challenger router identity is not cross-family allowlisted"
            )
    else:
        registry_roles = registry.get("roles")
        if (
            not isinstance(registry_roles, dict)
            or not isinstance(registry_roles.get(role), dict)
        ):
            raise ContractError(f"registry role is missing: {role}")
        expected = registry_roles[role]
        if (
            provider != PRIMARY_PROVIDER
            or registry.get("provider") != PRIMARY_PROVIDER
            or model != expected.get("model")
            or reasoning_effort != expected.get("reasoning_effort")
            or prompt_version != expected.get("prompt_version")
        ):
            raise ContractError(
                f"{role} router identity does not match the model registry"
            )
    return RoleCallSpec(
        role=role,
        provider=provider,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt_version=prompt_version,
        response_schema_sha256=schema_sha256,
        max_input_tokens=_integer(
            payload["max_input_tokens"],
            label=f"{role}.max_input_tokens",
            minimum=1,
        ),
        max_output_tokens=_integer(
            payload["max_output_tokens"],
            label=f"{role}.max_output_tokens",
            minimum=1,
        ),
        max_usd=_decimal(
            payload["max_usd"],
            label=f"{role}.max_usd",
            positive=True,
        ),
    )


def _policy(
    payload: object,
    *,
    registry: Mapping[str, Any],
) -> RouterPolicy:
    row = _closed_object(
        payload,
        label="router policy",
        fields={
            "role_specs",
            "high_impact_classifications",
            "provider_fallback_allowed",
        },
    )
    role_rows = row["role_specs"]
    if not isinstance(role_rows, list):
        raise ContractError("router role_specs must be a list")
    high_impact = row["high_impact_classifications"]
    if (
        not isinstance(high_impact, list)
        or any(not isinstance(value, str) for value in high_impact)
        or len(set(high_impact)) != len(high_impact)
    ):
        raise ContractError(
            "router high-impact classifications must be unique strings"
        )
    return RouterPolicy(
        role_specs=tuple(
            _role_spec(role_row, registry=registry)
            for role_row in role_rows
        ),
        high_impact_classifications=frozenset(high_impact),
        provider_fallback_allowed=_boolean(
            row["provider_fallback_allowed"],
            label="provider_fallback_allowed",
        ),
    )


def _ceilings(payload: object) -> CycleCeilings:
    row = _closed_object(
        payload,
        label="router ceilings",
        fields={
            "cycle_date",
            "max_requests_per_cycle",
            "max_input_tokens_per_request",
            "max_output_tokens_per_request",
            "max_total_tokens_per_request",
            "max_usd_per_request",
            "max_input_tokens_per_cycle",
            "max_output_tokens_per_cycle",
            "max_total_tokens_per_cycle",
            "max_usd_per_cycle",
        },
    )
    return CycleCeilings(
        cycle_date=_cycle_date(
            row["cycle_date"],
            label="ceilings.cycle_date",
        ),
        max_requests_per_cycle=_integer(
            row["max_requests_per_cycle"],
            label="max_requests_per_cycle",
        ),
        max_input_tokens_per_request=_integer(
            row["max_input_tokens_per_request"],
            label="max_input_tokens_per_request",
            minimum=1,
        ),
        max_output_tokens_per_request=_integer(
            row["max_output_tokens_per_request"],
            label="max_output_tokens_per_request",
            minimum=1,
        ),
        max_total_tokens_per_request=_integer(
            row["max_total_tokens_per_request"],
            label="max_total_tokens_per_request",
            minimum=1,
        ),
        max_usd_per_request=_decimal(
            row["max_usd_per_request"],
            label="max_usd_per_request",
            positive=True,
        ),
        max_input_tokens_per_cycle=_integer(
            row["max_input_tokens_per_cycle"],
            label="max_input_tokens_per_cycle",
        ),
        max_output_tokens_per_cycle=_integer(
            row["max_output_tokens_per_cycle"],
            label="max_output_tokens_per_cycle",
        ),
        max_total_tokens_per_cycle=_integer(
            row["max_total_tokens_per_cycle"],
            label="max_total_tokens_per_cycle",
        ),
        max_usd_per_cycle=_decimal(
            row["max_usd_per_cycle"],
            label="max_usd_per_cycle",
            positive=False,
        ),
    )


def _usage(payload: object) -> CycleUsage:
    row = _closed_object(
        payload,
        label="router usage",
        fields={
            "cycle_date",
            "used_requests",
            "used_input_tokens",
            "used_output_tokens",
            "used_usd",
        },
    )
    return CycleUsage(
        cycle_date=_cycle_date(
            row["cycle_date"],
            label="usage.cycle_date",
        ),
        used_requests=_integer(
            row["used_requests"],
            label="used_requests",
        ),
        used_input_tokens=_integer(
            row["used_input_tokens"],
            label="used_input_tokens",
        ),
        used_output_tokens=_integer(
            row["used_output_tokens"],
            label="used_output_tokens",
        ),
        used_usd=_decimal(
            row["used_usd"],
            label="used_usd",
            positive=False,
        ),
    )


def _signals(
    payload: object,
    *,
    expected_semantic_hash: str,
) -> RoutingSignals:
    row = _closed_object(
        payload,
        label="router signals",
        fields={
            "cycle_date",
            "semantic_hash",
            "evidence_sufficient",
            "material_evidence_changed",
            "classification_may_change",
            "decision_changed",
            "material_thesis_break",
            "disagreement",
            "previous_classification",
            "proposed_classification",
            "available_providers",
        },
    )
    if row["semantic_hash"] != expected_semantic_hash:
        raise ContractError(
            "router semantic hash does not match the frozen packet view"
        )
    providers = row["available_providers"]
    if (
        not isinstance(providers, list)
        or any(
            not isinstance(provider, str)
            or not provider
            or provider != provider.strip()
            or any(character in provider for character in "\r\n")
            for provider in providers
        )
        or len(set(providers)) != len(providers)
    ):
        raise ContractError(
            "available providers must be unique one-line strings"
        )
    return RoutingSignals(
        cycle_date=_cycle_date(
            row["cycle_date"],
            label="signals.cycle_date",
        ),
        semantic_hash=expected_semantic_hash,
        evidence_sufficient=_boolean(
            row["evidence_sufficient"],
            label="evidence_sufficient",
        ),
        material_evidence_changed=_boolean(
            row["material_evidence_changed"],
            label="material_evidence_changed",
        ),
        classification_may_change=_boolean(
            row["classification_may_change"],
            label="classification_may_change",
        ),
        decision_changed=_boolean(
            row["decision_changed"],
            label="decision_changed",
        ),
        material_thesis_break=_boolean(
            row["material_thesis_break"],
            label="material_thesis_break",
        ),
        disagreement=_boolean(
            row["disagreement"],
            label="disagreement",
        ),
        previous_classification=row["previous_classification"],
        proposed_classification=row["proposed_classification"],
        available_providers=frozenset(providers),
        # Reuse claims are deliberately not accepted from an operator file.
        # Existing role receipts require runtime validation by the executor.
        reusable_results=(),
    )


def plan_shadow_router_envelope(
    path: Path,
    *,
    semantic_payload: Mapping[str, Any],
    packet_cycle_date: str,
    registry: Mapping[str, Any],
) -> tuple[InferencePlan, str]:
    """Validate one explicit envelope and return a local-only plan.

    The envelope semantic hash must bind the exact packet view supplied by the
    caller.  No provider object is constructed before, during, or after this
    function.
    """

    if not isinstance(path, Path):
        raise ContractError("router envelope path must be a pathlib.Path")
    expected_cycle_date = _cycle_date(
        packet_cycle_date,
        label="packet_cycle_date",
    )
    if not isinstance(semantic_payload, Mapping):
        raise ContractError("router semantic payload must be a mapping")
    envelope = _closed_object(
        _read_envelope(path),
        label="router envelope",
        fields={
            "schema_version",
            "policy",
            "ceilings",
            "usage",
            "signals",
        },
    )
    if (
        envelope["schema_version"]
        != SHADOW_ROUTER_ENVELOPE_SCHEMA_VERSION
    ):
        raise ContractError("router envelope schema version mismatch")
    expected_semantic_hash = semantic_sha256(semantic_payload)
    try:
        policy = _policy(envelope["policy"], registry=registry)
        ceilings = _ceilings(envelope["ceilings"])
        usage = _usage(envelope["usage"])
        signals = _signals(
            envelope["signals"],
            expected_semantic_hash=expected_semantic_hash,
        )
        if not (
            policy.provider_fallback_allowed is False
            and ceilings.cycle_date
            == usage.cycle_date
            == signals.cycle_date
            == expected_cycle_date
        ):
            raise ContractError(
                "router envelope cycle or fallback binding mismatch"
            )
        plan = plan_inference(
            policy=policy,
            ceilings=ceilings,
            usage=usage,
            signals=signals,
        )
    except RouterError as exc:
        raise ContractError(f"router envelope failed closed: {exc}") from exc
    return plan, canonical_sha256(envelope)


def shadow_router_gate_receipt(
    *,
    plan: InferencePlan,
    envelope_sha256: str,
    packet_id: str,
    decision_fingerprint: str,
    model_run_id: str,
) -> dict[str, Any]:
    """Bind a planner result to a non-provider execution gate receipt."""

    call_roles = tuple(call.role for call in plan.calls)
    if plan.calls:
        gate_status = "blocked"
        gate_reason = "live_provider_execution_not_authorized"
    elif plan.fail_closed:
        gate_status = "blocked"
        gate_reason = plan.reason
    else:
        gate_status = "no_call"
        gate_reason = plan.reason
    receipt = {
        "schema_version": SHADOW_ROUTER_GATE_RECEIPT_SCHEMA_VERSION,
        "packet_id": packet_id,
        "decision_fingerprint": decision_fingerprint,
        "model_run_id": model_run_id,
        "envelope_sha256": envelope_sha256,
        "plan": plan.to_dict(),
        "execution_gate": {
            "status": gate_status,
            "reason": gate_reason,
            "planned_call_roles": list(call_roles),
            "exact_role_executor_integrated": True,
            "fixture_execution_available": True,
            "live_provider_execution_authorized": False,
            "durable_execution_ledger_schema_version": (
                LEDGER_SCHEMA_VERSION
            ),
            "metered_role_receipt_schema_version": (
                RECEIPT_SCHEMA_VERSION
            ),
            "exact_planned_roles_enforced": True,
            "provider_fallback_allowed": False,
            "provider_client_constructed": False,
            "provider_attempt_started": False,
            "provider_receipt_created": False,
            "existing_role_receipt_schema_version": (
                "phase5r_llm_shadow_role_receipt_v1"
            ),
            "operator_reuse_claims_accepted": False,
            "budget_charged_requests": 0,
            "budget_charged_input_tokens": 0,
            "budget_charged_output_tokens": 0,
            "budget_charged_usd": "0",
        },
        "boundaries": {
            "network_attempted": False,
            "credential_read": False,
            "canonical_effect": False,
            "email_attempted": False,
            "smtp_config_read": False,
            "broker_connected": False,
            "broker_account_read": False,
            "order_code_created": False,
            "trade_placed": False,
            "automatic_action_allowed": False,
        },
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    return receipt


__all__ = [
    "CHALLENGER_PROMPT_VERSION",
    "CHALLENGER_PROVIDER",
    "PRIMARY_PROVIDER",
    "SHADOW_ROUTER_ENVELOPE_SCHEMA_VERSION",
    "SHADOW_ROUTER_GATE_RECEIPT_SCHEMA_VERSION",
    "plan_shadow_router_envelope",
    "shadow_router_gate_receipt",
]
