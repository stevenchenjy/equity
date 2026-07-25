#!/usr/bin/env python3
"""Deterministic, side-effect-free inference routing for Phase 5R.

This module only plans provider calls.  It does not construct a provider
client, read credentials, use the network, persist state, send email, change a
canonical decision, or expose broker/order functionality.

The router is intentionally suitable for staged use:

1. deterministic local gates can stop with no call;
2. material evidence can request a Terra evidence pass;
3. a possible class change can add a Sol proposal;
4. a high-impact transition, thesis break, or disagreement can add the Sol
   critic and a proposal-blind cross-family challenger.

All limits are immutable inputs.  Calls are reserved at their configured
worst-case token and USD envelopes.  If one required call cannot fit, the
entire plan contains zero calls and fails closed.  Exact validated role results
can be reused only when their semantic, policy, role, and dependency bindings
match.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping


ROUTER_SCHEMA_VERSION = "phase5r_llm_cost_aware_router_v1"
PLAN_SCHEMA_VERSION = "phase5r_llm_inference_plan_v1"

ROLE_ORDER = ("analyst", "committee", "critic", "challenger")
ROLE_DEPENDENCIES = {
    "analyst": (),
    "committee": ("analyst",),
    "critic": ("analyst", "committee"),
    # Challenger is intentionally independent of committee and critic output.
    "challenger": ("analyst",),
}
HIGH_IMPACT_CLASSIFICATIONS = frozenset(
    {
        "paper_trade_candidate",
        "real_trade_candidate",
        "trim_review",
        "exit_review",
    }
)
ALLOWED_CLASSIFICATIONS = frozenset(
    {
        "reject",
        "watchlist",
        "hold_existing",
        "paper_trade_candidate",
        "real_trade_candidate",
        "trim_review",
        "exit_review",
        "abstain",
    }
)
REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh"})


class RouterError(ValueError):
    """Base class for deterministic router failures."""


class RouterConfigurationError(RouterError):
    """The immutable routing policy or ceilings are invalid."""


class RouterInputError(RouterError):
    """Cycle state, usage, or reuse evidence is malformed or inconsistent."""


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha256(value: object, label: str) -> str:
    if not _is_sha256(value):
        raise RouterConfigurationError(f"{label} must be a lowercase SHA-256")
    return str(value)


def _require_nonempty_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or any(character in value for character in "\r\n")
    ):
        raise RouterConfigurationError(
            f"{label} must be one non-empty trimmed line"
        )
    return value


def _require_int(
    value: object,
    label: str,
    *,
    minimum: int = 0,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
    ):
        raise RouterConfigurationError(
            f"{label} must be an integer >= {minimum}"
        )
    return value


def _require_decimal(
    value: object,
    label: str,
    *,
    positive: bool,
) -> Decimal:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or (value <= 0 if positive else value < 0)
    ):
        comparator = "> 0" if positive else ">= 0"
        raise RouterConfigurationError(
            f"{label} must be a finite Decimal {comparator}"
        )
    return value


def _canonical_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise RouterInputError(
                    "canonical payload keys must be strings"
                )
            normalized[key] = _canonical_value(item)
        return normalized
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, frozenset):
        normalized_items = [_canonical_value(item) for item in value]
        return sorted(
            normalized_items,
            key=lambda item: json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise RouterInputError(
            "canonical payload cannot contain non-finite floats"
        )
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise RouterInputError(
        f"canonical payload contains unsupported type: "
        f"{type(value).__name__}"
    )


def canonical_sha256(payload: Any) -> str:
    """Return a stable SHA-256 for JSON-compatible semantic content."""

    encoded = json.dumps(
        _canonical_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def semantic_sha256(payload: Mapping[str, Any]) -> str:
    """Hash one proposal-free semantic evidence view."""

    if not isinstance(payload, Mapping):
        raise RouterInputError("semantic payload must be a mapping")
    return canonical_sha256(payload)


@dataclass(frozen=True, slots=True)
class RoleCallSpec:
    """Pinned role, provider, model, semantic contract, and call envelope."""

    role: str
    provider: str
    model: str
    reasoning_effort: str
    prompt_version: str
    response_schema_sha256: str
    max_input_tokens: int
    max_output_tokens: int
    max_usd: Decimal

    def __post_init__(self) -> None:
        if self.role not in ROLE_ORDER:
            raise RouterConfigurationError(
                f"unsupported inference role: {self.role}"
            )
        _require_nonempty_text(self.provider, f"{self.role}.provider")
        _require_nonempty_text(self.model, f"{self.role}.model")
        if self.reasoning_effort not in REASONING_EFFORTS:
            raise RouterConfigurationError(
                f"{self.role}.reasoning_effort is unsupported"
            )
        _require_nonempty_text(
            self.prompt_version,
            f"{self.role}.prompt_version",
        )
        _require_sha256(
            self.response_schema_sha256,
            f"{self.role}.response_schema_sha256",
        )
        _require_int(
            self.max_input_tokens,
            f"{self.role}.max_input_tokens",
            minimum=1,
        )
        _require_int(
            self.max_output_tokens,
            f"{self.role}.max_output_tokens",
            minimum=1,
        )
        _require_decimal(
            self.max_usd,
            f"{self.role}.max_usd",
            positive=True,
        )

    @property
    def max_total_tokens(self) -> int:
        return self.max_input_tokens + self.max_output_tokens

    def semantic_binding(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "prompt_version": self.prompt_version,
            "response_schema_sha256": self.response_schema_sha256,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_usd": self.max_usd,
        }


@dataclass(frozen=True, slots=True)
class RouterPolicy:
    """Frozen model routing policy with no provider fallback surface."""

    role_specs: tuple[RoleCallSpec, ...]
    high_impact_classifications: frozenset[str] = (
        HIGH_IMPACT_CLASSIFICATIONS
    )
    provider_fallback_allowed: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.role_specs, tuple)
            or len(self.role_specs) != len(ROLE_ORDER)
        ):
            raise RouterConfigurationError(
                "router policy must define exactly four role specs"
            )
        roles = tuple(spec.role for spec in self.role_specs)
        if roles != ROLE_ORDER:
            raise RouterConfigurationError(
                "router role specs must use the closed role order"
            )
        if self.provider_fallback_allowed is not False:
            raise RouterConfigurationError(
                "provider fallback must remain disabled"
            )
        if (
            not isinstance(self.high_impact_classifications, frozenset)
            or not self.high_impact_classifications
            or not self.high_impact_classifications.issubset(
                ALLOWED_CLASSIFICATIONS
            )
        ):
            raise RouterConfigurationError(
                "high-impact classifications are invalid"
            )
        by_role = self.by_role
        if by_role["analyst"].model != "gpt-5.6-terra":
            raise RouterConfigurationError(
                "analyst role must remain pinned to gpt-5.6-terra"
            )
        for role in ("committee", "critic"):
            if by_role[role].model != "gpt-5.6-sol":
                raise RouterConfigurationError(
                    f"{role} role must remain pinned to gpt-5.6-sol"
                )
        primary_provider = by_role["analyst"].provider
        if any(
            by_role[role].provider != primary_provider
            for role in ("committee", "critic")
        ):
            raise RouterConfigurationError(
                "Terra and Sol roles must use one pinned primary provider"
            )
        if by_role["challenger"].provider == primary_provider:
            raise RouterConfigurationError(
                "challenger must use a different provider family"
            )

    @property
    def by_role(self) -> dict[str, RoleCallSpec]:
        return {spec.role: spec for spec in self.role_specs}

    @property
    def policy_sha256(self) -> str:
        return canonical_sha256(
            {
                "schema_version": ROUTER_SCHEMA_VERSION,
                "role_specs": [
                    spec.semantic_binding()
                    for spec in self.role_specs
                ],
                "high_impact_classifications": (
                    self.high_impact_classifications
                ),
                "provider_fallback_allowed": (
                    self.provider_fallback_allowed
                ),
            }
        )


@dataclass(frozen=True, slots=True)
class CycleCeilings:
    """Immutable per-request and per-cycle call, token, and USD ceilings."""

    cycle_date: date
    max_requests_per_cycle: int
    max_input_tokens_per_request: int
    max_output_tokens_per_request: int
    max_total_tokens_per_request: int
    max_usd_per_request: Decimal
    max_input_tokens_per_cycle: int
    max_output_tokens_per_cycle: int
    max_total_tokens_per_cycle: int
    max_usd_per_cycle: Decimal

    def __post_init__(self) -> None:
        if type(self.cycle_date) is not date:
            raise RouterConfigurationError(
                "cycle_date must be a date"
            )
        _require_int(
            self.max_requests_per_cycle,
            "max_requests_per_cycle",
        )
        for field_name in (
            "max_input_tokens_per_request",
            "max_output_tokens_per_request",
            "max_total_tokens_per_request",
        ):
            _require_int(
                getattr(self, field_name),
                field_name,
                minimum=1,
            )
        for field_name in (
            "max_input_tokens_per_cycle",
            "max_output_tokens_per_cycle",
            "max_total_tokens_per_cycle",
        ):
            _require_int(getattr(self, field_name), field_name)
        _require_decimal(
            self.max_usd_per_request,
            "max_usd_per_request",
            positive=True,
        )
        _require_decimal(
            self.max_usd_per_cycle,
            "max_usd_per_cycle",
            positive=False,
        )
        if not (
            max(
                self.max_input_tokens_per_request,
                self.max_output_tokens_per_request,
            )
            <= self.max_total_tokens_per_request
            <= (
                self.max_input_tokens_per_request
                + self.max_output_tokens_per_request
            )
        ):
            raise RouterConfigurationError(
                "per-request total-token ceiling is inconsistent"
            )
        if not (
            max(
                self.max_input_tokens_per_cycle,
                self.max_output_tokens_per_cycle,
            )
            <= self.max_total_tokens_per_cycle
            <= (
                self.max_input_tokens_per_cycle
                + self.max_output_tokens_per_cycle
            )
        ):
            raise RouterConfigurationError(
                "per-cycle total-token ceiling is inconsistent"
            )

    def binding(self) -> dict[str, Any]:
        return {
            "cycle_date": self.cycle_date,
            "max_requests_per_cycle": self.max_requests_per_cycle,
            "max_input_tokens_per_request": (
                self.max_input_tokens_per_request
            ),
            "max_output_tokens_per_request": (
                self.max_output_tokens_per_request
            ),
            "max_total_tokens_per_request": (
                self.max_total_tokens_per_request
            ),
            "max_usd_per_request": self.max_usd_per_request,
            "max_input_tokens_per_cycle": (
                self.max_input_tokens_per_cycle
            ),
            "max_output_tokens_per_cycle": (
                self.max_output_tokens_per_cycle
            ),
            "max_total_tokens_per_cycle": (
                self.max_total_tokens_per_cycle
            ),
            "max_usd_per_cycle": self.max_usd_per_cycle,
        }


@dataclass(frozen=True, slots=True)
class CycleUsage:
    """Cumulative, already-consumed worst-case budget for one cycle."""

    cycle_date: date
    used_requests: int
    used_input_tokens: int
    used_output_tokens: int
    used_usd: Decimal

    def __post_init__(self) -> None:
        if type(self.cycle_date) is not date:
            raise RouterInputError("usage cycle_date must be a date")
        for field_name in (
            "used_requests",
            "used_input_tokens",
            "used_output_tokens",
        ):
            try:
                _require_int(getattr(self, field_name), field_name)
            except RouterConfigurationError as exc:
                raise RouterInputError(str(exc)) from exc
        try:
            _require_decimal(
                self.used_usd,
                "used_usd",
                positive=False,
            )
        except RouterConfigurationError as exc:
            raise RouterInputError(str(exc)) from exc

    @property
    def used_total_tokens(self) -> int:
        return self.used_input_tokens + self.used_output_tokens


def _dependency_tuple(
    role: str,
    dependency_results: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    expected = ROLE_DEPENDENCIES[role]
    if set(dependency_results) != set(expected):
        raise RouterInputError(
            f"{role} reusable result dependencies must be exact"
        )
    rows: list[tuple[str, str]] = []
    for dependency in expected:
        digest = dependency_results[dependency]
        if not _is_sha256(digest):
            raise RouterInputError(
                f"{role} dependency result hash is invalid"
            )
        rows.append((dependency, digest))
    return tuple(rows)


def reusable_role_binding_sha256(
    *,
    policy_sha256: str,
    role: str,
    semantic_hash: str,
    dependency_results: Mapping[str, str],
) -> str:
    """Bind a validated role result to semantics, policy, and dependencies."""

    if role not in ROLE_ORDER:
        raise RouterInputError("reusable role is unsupported")
    if not _is_sha256(policy_sha256):
        raise RouterInputError("reusable policy hash is invalid")
    if not _is_sha256(semantic_hash):
        raise RouterInputError("reusable semantic hash is invalid")
    dependencies = _dependency_tuple(role, dependency_results)
    return canonical_sha256(
        {
            "schema_version": (
                "phase5r_llm_reusable_role_binding_v1"
            ),
            "policy_sha256": policy_sha256,
            "role": role,
            "semantic_hash": semantic_hash,
            "dependency_result_sha256s": dependencies,
        }
    )


@dataclass(frozen=True, slots=True)
class ReusableRoleResult:
    """Receipt summary for one already-validated semantic role result."""

    role: str
    semantic_hash: str
    policy_sha256: str
    dependency_result_sha256s: tuple[tuple[str, str], ...]
    result_sha256: str
    role_binding_sha256: str
    validated: bool

    def __post_init__(self) -> None:
        if self.role not in ROLE_ORDER:
            raise RouterInputError("reusable role is unsupported")
        for value, label in (
            (self.semantic_hash, "reusable semantic hash"),
            (self.policy_sha256, "reusable policy hash"),
            (self.result_sha256, "reusable result hash"),
            (self.role_binding_sha256, "reusable role binding"),
        ):
            if not _is_sha256(value):
                raise RouterInputError(f"{label} is invalid")
        if not isinstance(self.validated, bool):
            raise RouterInputError(
                "reusable validated flag must be boolean"
            )
        if not isinstance(self.dependency_result_sha256s, tuple):
            raise RouterInputError(
                "reusable dependencies must be an immutable tuple"
            )
        dependencies = dict(self.dependency_result_sha256s)
        if (
            len(dependencies)
            != len(self.dependency_result_sha256s)
        ):
            raise RouterInputError(
                "reusable dependencies contain duplicates"
            )
        expected = _dependency_tuple(self.role, dependencies)
        if expected != self.dependency_result_sha256s:
            raise RouterInputError(
                "reusable dependencies are out of order"
            )


def build_reusable_role_result(
    *,
    policy: RouterPolicy,
    role: str,
    semantic_hash: str,
    result_sha256: str,
    dependency_results: Mapping[str, str],
    validated: bool = True,
) -> ReusableRoleResult:
    """Build the immutable summary only after external semantic validation."""

    if role not in ROLE_ORDER:
        raise RouterInputError("reusable role is unsupported")
    if not _is_sha256(semantic_hash):
        raise RouterInputError("reusable semantic hash is invalid")
    if not _is_sha256(result_sha256):
        raise RouterInputError("reusable result hash is invalid")
    dependencies = _dependency_tuple(role, dependency_results)
    binding = reusable_role_binding_sha256(
        policy_sha256=policy.policy_sha256,
        role=role,
        semantic_hash=semantic_hash,
        dependency_results=dict(dependencies),
    )
    return ReusableRoleResult(
        role=role,
        semantic_hash=semantic_hash,
        policy_sha256=policy.policy_sha256,
        dependency_result_sha256s=dependencies,
        result_sha256=result_sha256,
        role_binding_sha256=binding,
        validated=validated,
    )


@dataclass(frozen=True, slots=True)
class RoutingSignals:
    """Deterministic state used to choose the minimum safe role sequence."""

    cycle_date: date
    semantic_hash: str
    evidence_sufficient: bool
    material_evidence_changed: bool
    classification_may_change: bool
    decision_changed: bool
    material_thesis_break: bool
    disagreement: bool
    previous_classification: str | None
    proposed_classification: str | None
    available_providers: frozenset[str]
    reusable_results: tuple[ReusableRoleResult, ...] = ()

    def __post_init__(self) -> None:
        if type(self.cycle_date) is not date:
            raise RouterInputError("signal cycle_date must be a date")
        if not _is_sha256(self.semantic_hash):
            raise RouterInputError("semantic hash is invalid")
        for field_name in (
            "evidence_sufficient",
            "material_evidence_changed",
            "classification_may_change",
            "decision_changed",
            "material_thesis_break",
            "disagreement",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise RouterInputError(
                    f"{field_name} must be boolean"
                )
        for field_name in (
            "previous_classification",
            "proposed_classification",
        ):
            value = getattr(self, field_name)
            if (
                value is not None
                and value not in ALLOWED_CLASSIFICATIONS
            ):
                raise RouterInputError(
                    f"{field_name} is outside the closed class set"
                )
        if not isinstance(self.available_providers, frozenset):
            raise RouterInputError(
                "available_providers must be an immutable frozenset"
            )
        for provider in self.available_providers:
            try:
                _require_nonempty_text(
                    provider,
                    "available provider",
                )
            except RouterConfigurationError as exc:
                raise RouterInputError(str(exc)) from exc
        if not isinstance(self.reusable_results, tuple):
            raise RouterInputError(
                "reusable_results must be an immutable tuple"
            )

    @property
    def classification_changed(self) -> bool:
        return (
            self.proposed_classification is not None
            and self.proposed_classification
            != self.previous_classification
        )


@dataclass(frozen=True, slots=True)
class PlannedRoleCall:
    """One exact, non-fallback provider call reservation."""

    role: str
    provider: str
    model: str
    reasoning_effort: str
    prompt_version: str
    response_schema_sha256: str
    semantic_hash: str
    dependency_roles: tuple[str, ...]
    max_input_tokens: int
    max_output_tokens: int
    max_usd: Decimal
    route_binding_sha256: str
    provider_fallback_allowed: bool = False

    @property
    def max_total_tokens(self) -> int:
        return self.max_input_tokens + self.max_output_tokens

    def binding(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "provider": self.provider,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "prompt_version": self.prompt_version,
            "response_schema_sha256": (
                self.response_schema_sha256
            ),
            "semantic_hash": self.semantic_hash,
            "dependency_roles": self.dependency_roles,
            "max_input_tokens": self.max_input_tokens,
            "max_output_tokens": self.max_output_tokens,
            "max_total_tokens": self.max_total_tokens,
            "max_usd": self.max_usd,
            "route_binding_sha256": self.route_binding_sha256,
            "provider_fallback_allowed": (
                self.provider_fallback_allowed
            ),
        }


@dataclass(frozen=True, slots=True)
class BudgetProjection:
    """Worst-case budget projection; negative remaining values show excess."""

    used_requests_before: int
    used_input_tokens_before: int
    used_output_tokens_before: int
    used_total_tokens_before: int
    used_usd_before: Decimal
    reserved_requests: int
    reserved_input_tokens: int
    reserved_output_tokens: int
    reserved_total_tokens: int
    reserved_usd: Decimal
    projected_requests: int
    projected_input_tokens: int
    projected_output_tokens: int
    projected_total_tokens: int
    projected_usd: Decimal
    remaining_requests: int
    remaining_input_tokens: int
    remaining_output_tokens: int
    remaining_total_tokens: int
    remaining_usd: Decimal
    within_ceiling: bool
    failed_ceiling: str

    def binding(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class InferencePlan:
    """Closed deterministic routing result with no executable authority."""

    cycle_date: date
    semantic_hash: str
    policy_sha256: str
    status: str
    reason: str
    required_roles: tuple[str, ...]
    reused_roles: tuple[str, ...]
    reused_result_sha256s: tuple[tuple[str, str], ...]
    calls: tuple[PlannedRoleCall, ...]
    high_impact_transition: bool
    disagreement: bool
    weekend_suppressed: bool
    fail_closed: bool
    budget: BudgetProjection

    def unsigned_payload(self) -> dict[str, Any]:
        return {
            "schema_version": PLAN_SCHEMA_VERSION,
            "cycle_date": self.cycle_date,
            "semantic_hash": self.semantic_hash,
            "policy_sha256": self.policy_sha256,
            "status": self.status,
            "reason": self.reason,
            "required_roles": self.required_roles,
            "reused_roles": self.reused_roles,
            "reused_result_sha256s": (
                self.reused_result_sha256s
            ),
            "calls": [call.binding() for call in self.calls],
            "high_impact_transition": (
                self.high_impact_transition
            ),
            "disagreement": self.disagreement,
            "weekend_suppressed": self.weekend_suppressed,
            "fail_closed": self.fail_closed,
            "budget": self.budget.binding(),
            "boundaries": {
                "local_planner_only": True,
                "network_attempted": False,
                "provider_client_constructed": False,
                "provider_fallback_allowed": False,
                "credential_read": False,
                "canonical_effect": False,
                "email_attempted": False,
                "broker_connected": False,
                "order_code_created": False,
                "trade_placed": False,
                "automatic_action_allowed": False,
            },
        }

    @property
    def plan_sha256(self) -> str:
        return canonical_sha256(self.unsigned_payload())

    def to_dict(self) -> dict[str, Any]:
        payload = _canonical_value(self.unsigned_payload())
        payload["plan_sha256"] = self.plan_sha256
        return payload


def _validate_cycle_state(
    ceilings: CycleCeilings,
    usage: CycleUsage,
    signals: RoutingSignals,
) -> None:
    if not (
        ceilings.cycle_date
        == usage.cycle_date
        == signals.cycle_date
    ):
        raise RouterInputError(
            "ceiling, usage, and signal cycles must match"
        )
    invalid = (
        usage.used_requests > ceilings.max_requests_per_cycle
        or usage.used_input_tokens
        > ceilings.max_input_tokens_per_cycle
        or usage.used_output_tokens
        > ceilings.max_output_tokens_per_cycle
        or usage.used_total_tokens
        > ceilings.max_total_tokens_per_cycle
        or usage.used_usd > ceilings.max_usd_per_cycle
    )
    if invalid:
        raise RouterInputError(
            "existing cycle usage already exceeds a frozen ceiling"
        )


def _high_impact_transition(
    policy: RouterPolicy,
    signals: RoutingSignals,
) -> bool:
    return bool(
        signals.material_thesis_break
        or (
            signals.classification_changed
            and signals.proposed_classification
            in policy.high_impact_classifications
        )
    )


def _has_material_change(
    policy: RouterPolicy,
    signals: RoutingSignals,
) -> bool:
    return bool(
        signals.material_evidence_changed
        or signals.classification_may_change
        or signals.decision_changed
        or signals.classification_changed
        or signals.material_thesis_break
        or signals.disagreement
        or _high_impact_transition(policy, signals)
    )


def _required_roles(
    policy: RouterPolicy,
    signals: RoutingSignals,
) -> tuple[str, ...]:
    high_impact = _high_impact_transition(policy, signals)
    if high_impact or signals.disagreement:
        return ROLE_ORDER
    if (
        signals.classification_may_change
        or signals.decision_changed
        or signals.classification_changed
    ):
        return ("analyst", "committee")
    if signals.material_evidence_changed:
        return ("analyst",)
    return ()


def _zero_projection(
    ceilings: CycleCeilings,
    usage: CycleUsage,
) -> BudgetProjection:
    return _budget_projection(
        ceilings,
        usage,
        (),
    )


def _budget_projection(
    ceilings: CycleCeilings,
    usage: CycleUsage,
    calls: tuple[PlannedRoleCall, ...],
) -> BudgetProjection:
    reserved_requests = len(calls)
    reserved_input = sum(call.max_input_tokens for call in calls)
    reserved_output = sum(
        call.max_output_tokens for call in calls
    )
    reserved_total = reserved_input + reserved_output
    reserved_usd = sum(
        (call.max_usd for call in calls),
        start=Decimal("0"),
    )
    projected_requests = usage.used_requests + reserved_requests
    projected_input = usage.used_input_tokens + reserved_input
    projected_output = usage.used_output_tokens + reserved_output
    projected_total = usage.used_total_tokens + reserved_total
    projected_usd = usage.used_usd + reserved_usd

    failed_ceiling = ""
    for call in calls:
        if (
            call.max_input_tokens
            > ceilings.max_input_tokens_per_request
        ):
            failed_ceiling = (
                f"per_request_input_tokens:{call.role}"
            )
            break
        if (
            call.max_output_tokens
            > ceilings.max_output_tokens_per_request
        ):
            failed_ceiling = (
                f"per_request_output_tokens:{call.role}"
            )
            break
        if (
            call.max_total_tokens
            > ceilings.max_total_tokens_per_request
        ):
            failed_ceiling = (
                f"per_request_total_tokens:{call.role}"
            )
            break
        if call.max_usd > ceilings.max_usd_per_request:
            failed_ceiling = f"per_request_usd:{call.role}"
            break
    if not failed_ceiling:
        cycle_checks = (
            (
                "cycle_requests",
                projected_requests,
                ceilings.max_requests_per_cycle,
            ),
            (
                "cycle_input_tokens",
                projected_input,
                ceilings.max_input_tokens_per_cycle,
            ),
            (
                "cycle_output_tokens",
                projected_output,
                ceilings.max_output_tokens_per_cycle,
            ),
            (
                "cycle_total_tokens",
                projected_total,
                ceilings.max_total_tokens_per_cycle,
            ),
            (
                "cycle_usd",
                projected_usd,
                ceilings.max_usd_per_cycle,
            ),
        )
        failed_ceiling = next(
            (
                name
                for name, projected, maximum in cycle_checks
                if projected > maximum
            ),
            "",
        )
    return BudgetProjection(
        used_requests_before=usage.used_requests,
        used_input_tokens_before=usage.used_input_tokens,
        used_output_tokens_before=usage.used_output_tokens,
        used_total_tokens_before=usage.used_total_tokens,
        used_usd_before=usage.used_usd,
        reserved_requests=reserved_requests,
        reserved_input_tokens=reserved_input,
        reserved_output_tokens=reserved_output,
        reserved_total_tokens=reserved_total,
        reserved_usd=reserved_usd,
        projected_requests=projected_requests,
        projected_input_tokens=projected_input,
        projected_output_tokens=projected_output,
        projected_total_tokens=projected_total,
        projected_usd=projected_usd,
        remaining_requests=(
            ceilings.max_requests_per_cycle
            - projected_requests
        ),
        remaining_input_tokens=(
            ceilings.max_input_tokens_per_cycle
            - projected_input
        ),
        remaining_output_tokens=(
            ceilings.max_output_tokens_per_cycle
            - projected_output
        ),
        remaining_total_tokens=(
            ceilings.max_total_tokens_per_cycle
            - projected_total
        ),
        remaining_usd=(
            ceilings.max_usd_per_cycle - projected_usd
        ),
        within_ceiling=not failed_ceiling,
        failed_ceiling=failed_ceiling,
    )


def _plan(
    *,
    policy: RouterPolicy,
    ceilings: CycleCeilings,
    usage: CycleUsage,
    signals: RoutingSignals,
    status: str,
    reason: str,
    required_roles: tuple[str, ...] = (),
    reused_results: tuple[ReusableRoleResult, ...] = (),
    calls: tuple[PlannedRoleCall, ...] = (),
    weekend_suppressed: bool = False,
    fail_closed: bool = False,
    budget: BudgetProjection | None = None,
) -> InferencePlan:
    return InferencePlan(
        cycle_date=signals.cycle_date,
        semantic_hash=signals.semantic_hash,
        policy_sha256=policy.policy_sha256,
        status=status,
        reason=reason,
        required_roles=required_roles,
        reused_roles=tuple(
            result.role for result in reused_results
        ),
        reused_result_sha256s=tuple(
            (result.role, result.result_sha256)
            for result in reused_results
        ),
        calls=calls,
        high_impact_transition=_high_impact_transition(
            policy,
            signals,
        ),
        disagreement=signals.disagreement,
        weekend_suppressed=weekend_suppressed,
        fail_closed=fail_closed,
        budget=(
            budget
            if budget is not None
            else _zero_projection(ceilings, usage)
        ),
    )


def _reusable_results(
    *,
    policy: RouterPolicy,
    signals: RoutingSignals,
    required_roles: tuple[str, ...],
) -> tuple[ReusableRoleResult, ...]:
    matching_by_role: dict[str, ReusableRoleResult] = {}
    for result in signals.reusable_results:
        if (
            result.semantic_hash != signals.semantic_hash
            or result.policy_sha256 != policy.policy_sha256
            or result.role not in required_roles
            or result.validated is not True
        ):
            continue
        if result.role in matching_by_role:
            raise RouterInputError(
                f"duplicate reusable result for role: {result.role}"
            )
        expected_binding = reusable_role_binding_sha256(
            policy_sha256=result.policy_sha256,
            role=result.role,
            semantic_hash=result.semantic_hash,
            dependency_results=dict(
                result.dependency_result_sha256s
            ),
        )
        if result.role_binding_sha256 != expected_binding:
            raise RouterInputError(
                f"reusable result binding is invalid: {result.role}"
            )
        matching_by_role[result.role] = result

    selected: list[ReusableRoleResult] = []
    selected_hashes: dict[str, str] = {}
    for role in required_roles:
        result = matching_by_role.get(role)
        if result is None:
            continue
        expected_dependencies = {
            dependency: selected_hashes[dependency]
            for dependency in ROLE_DEPENDENCIES[role]
            if dependency in selected_hashes
        }
        if set(expected_dependencies) != set(
            ROLE_DEPENDENCIES[role]
        ):
            continue
        if dict(result.dependency_result_sha256s) != (
            expected_dependencies
        ):
            raise RouterInputError(
                f"reusable dependency binding is stale: {role}"
            )
        selected.append(result)
        selected_hashes[role] = result.result_sha256
    return tuple(selected)


def _planned_call(
    *,
    policy: RouterPolicy,
    semantic_hash: str,
    role: str,
) -> PlannedRoleCall:
    spec = policy.by_role[role]
    route_binding = canonical_sha256(
        {
            "schema_version": (
                "phase5r_llm_planned_role_call_v1"
            ),
            "policy_sha256": policy.policy_sha256,
            "semantic_hash": semantic_hash,
            "role_spec": spec.semantic_binding(),
            "dependency_roles": ROLE_DEPENDENCIES[role],
            "provider_fallback_allowed": False,
        }
    )
    return PlannedRoleCall(
        role=role,
        provider=spec.provider,
        model=spec.model,
        reasoning_effort=spec.reasoning_effort,
        prompt_version=spec.prompt_version,
        response_schema_sha256=spec.response_schema_sha256,
        semantic_hash=semantic_hash,
        dependency_roles=ROLE_DEPENDENCIES[role],
        max_input_tokens=spec.max_input_tokens,
        max_output_tokens=spec.max_output_tokens,
        max_usd=spec.max_usd,
        route_binding_sha256=route_binding,
    )


def plan_inference(
    *,
    policy: RouterPolicy,
    ceilings: CycleCeilings,
    usage: CycleUsage,
    signals: RoutingSignals,
) -> InferencePlan:
    """Return the minimum safe call plan without performing any call.

    Budget and provider failures never yield a partial call plan.  The caller
    must persist an attempt intent and update immutable cumulative usage from
    actual receipts before invoking any planned role.
    """

    _validate_cycle_state(ceilings, usage, signals)

    if (
        signals.cycle_date.weekday() >= 5
        and not _has_material_change(policy, signals)
    ):
        return _plan(
            policy=policy,
            ceilings=ceilings,
            usage=usage,
            signals=signals,
            status="suppressed",
            reason="weekend_no_change_suppressed",
            weekend_suppressed=True,
        )

    if signals.evidence_sufficient is not True:
        return _plan(
            policy=policy,
            ceilings=ceilings,
            usage=usage,
            signals=signals,
            status="blocked",
            reason="deterministic_evidence_insufficient",
            fail_closed=True,
        )

    required_roles = _required_roles(policy, signals)
    if not required_roles:
        return _plan(
            policy=policy,
            ceilings=ceilings,
            usage=usage,
            signals=signals,
            status="local_only",
            reason="no_material_semantic_change",
        )

    reused = _reusable_results(
        policy=policy,
        signals=signals,
        required_roles=required_roles,
    )
    reused_roles = {result.role for result in reused}
    calls = tuple(
        _planned_call(
            policy=policy,
            semantic_hash=signals.semantic_hash,
            role=role,
        )
        for role in required_roles
        if role not in reused_roles
    )

    if not calls:
        return _plan(
            policy=policy,
            ceilings=ceilings,
            usage=usage,
            signals=signals,
            status="reused",
            reason="semantic_hash_reuse",
            required_roles=required_roles,
            reused_results=reused,
        )

    unavailable = tuple(
        sorted(
            {
                call.provider
                for call in calls
                if call.provider
                not in signals.available_providers
            }
        )
    )
    if unavailable:
        return _plan(
            policy=policy,
            ceilings=ceilings,
            usage=usage,
            signals=signals,
            status="blocked",
            reason=(
                "provider_unavailable_no_fallback:"
                + ",".join(unavailable)
            ),
            required_roles=required_roles,
            reused_results=reused,
            fail_closed=True,
        )

    budget = _budget_projection(ceilings, usage, calls)
    if not budget.within_ceiling:
        return _plan(
            policy=policy,
            ceilings=ceilings,
            usage=usage,
            signals=signals,
            status="blocked",
            reason=(
                "budget_exhausted:"
                f"{budget.failed_ceiling}"
            ),
            required_roles=required_roles,
            reused_results=reused,
            fail_closed=True,
            budget=budget,
        )

    return _plan(
        policy=policy,
        ceilings=ceilings,
        usage=usage,
        signals=signals,
        status="planned",
        reason=(
            "calls_planned_with_semantic_reuse"
            if reused
            else "calls_planned"
        ),
        required_roles=required_roles,
        reused_results=reused,
        calls=calls,
        budget=budget,
    )


__all__ = [
    "ALLOWED_CLASSIFICATIONS",
    "BudgetProjection",
    "CycleCeilings",
    "CycleUsage",
    "HIGH_IMPACT_CLASSIFICATIONS",
    "InferencePlan",
    "PLAN_SCHEMA_VERSION",
    "PlannedRoleCall",
    "ROLE_DEPENDENCIES",
    "ROLE_ORDER",
    "ROUTER_SCHEMA_VERSION",
    "ReusableRoleResult",
    "RoleCallSpec",
    "RouterConfigurationError",
    "RouterError",
    "RouterInputError",
    "RouterPolicy",
    "RoutingSignals",
    "build_reusable_role_result",
    "canonical_sha256",
    "plan_inference",
    "reusable_role_binding_sha256",
    "semantic_sha256",
]
