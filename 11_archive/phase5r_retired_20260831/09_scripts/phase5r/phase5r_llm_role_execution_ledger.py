#!/usr/bin/env python3
"""Durable, exact-plan execution ledger for Phase 5R shadow inference.

The cost-aware router deliberately has no execution authority.  This module
closes the next local safety gap by binding an immutable router plan to:

* one exact role sequence and its dependency result hashes;
* a durable reservation written before provider construction;
* provider-reported token usage and independently recomputed model cost;
* private, hash-bound result receipts; and
* conservative crash accounting that never silently releases a reservation.

Only the fixture transport is enabled.  No repository entry point enables a
live provider, reads credentials, or uses the network.  A later live adapter
must preserve this ledger contract and add explicit operator cost authority.
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from phase5r_daily_common import ROOT, iso_now
from phase5r_llm_cost_aware_router import (
    InferencePlan,
    PlannedRoleCall,
    canonical_sha256,
)
from phase5r_llm_provider import ModelProvider, ProviderResult


LEDGER_SCHEMA_VERSION = "phase5r_llm_execution_ledger_v1"
RECEIPT_SCHEMA_VERSION = "phase5r_llm_metered_role_receipt_v1"
MAX_LEDGER_BYTES = 4 * 1024 * 1024
DEFAULT_LEDGER_RELATIVE_ROOT = (
    Path("Library")
    / "Application Support"
    / "Phase5R"
    / "llm_execution"
)
ALLOWED_EVENT_KINDS = frozenset(
    {
        "cycle_opened",
        "call_reserved",
        "call_completed",
        "call_failed",
        "call_outcome_unknown",
    }
)


class ExecutionLedgerError(RuntimeError):
    """The execution ledger or a metered result failed closed."""


class ExecutionBudgetError(ExecutionLedgerError):
    """A reservation or reported provider charge exceeds a frozen ceiling."""


class ExecutionRecoveryRequired(ExecutionLedgerError):
    """A prior provider outcome is unknown and cannot be called again."""


class PayloadValidator(Protocol):
    def __call__(self, payload: dict[str, Any]) -> None:
        ...


def default_execution_ledger_root(
    *,
    user_home: Path | None = None,
) -> Path:
    """Return the one private, non-repository runtime-ledger root.

    The path is computed but not created.  Tests and explicit external
    launchers may inject ``user_home``; production callers must not select an
    arbitrary per-run location because that would bypass cumulative cycle
    accounting.
    """

    home_path = Path.home() if user_home is None else user_home
    if not isinstance(home_path, Path) or not home_path.is_absolute():
        raise ExecutionLedgerError("ledger user home must be absolute")
    root = home_path / DEFAULT_LEDGER_RELATIVE_ROOT
    try:
        root.resolve(strict=False).relative_to(ROOT.resolve())
    except ValueError:
        return root
    raise ExecutionLedgerError(
        "execution ledger root must remain outside the repository"
    )


def cycle_execution_ledger_path(
    cycle_date: date,
    *,
    user_home: Path | None = None,
) -> Path:
    """Bind one calendar cycle to one non-bypassable ledger filename."""

    if type(cycle_date) is not date:
        raise ExecutionLedgerError("ledger cycle date must be a date")
    root = default_execution_ledger_root(user_home=user_home)
    return (
        root
        / f"{cycle_date.year:04d}"
        / f"phase5r-{cycle_date.isoformat()}.ledger.json"
    )


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Pinned provider/model token prices in exact USD per million tokens."""

    provider: str
    model: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    cached_input_usd_per_million: Decimal = Decimal("0")
    cache_write_usd_per_million: Decimal = Decimal("0")
    cache_read_usd_per_million: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for label in ("provider", "model"):
            value = getattr(self, label)
            if (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or any(character in value for character in "\r\n")
            ):
                raise ExecutionLedgerError(
                    f"price {label} must be one non-empty trimmed line"
                )
        for label in (
            "input_usd_per_million",
            "output_usd_per_million",
            "cached_input_usd_per_million",
            "cache_write_usd_per_million",
            "cache_read_usd_per_million",
        ):
            value = getattr(self, label)
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value < 0
            ):
                raise ExecutionLedgerError(
                    f"price {label} must be a finite non-negative Decimal"
                )

    def binding(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "input_usd_per_million": _decimal_text(
                self.input_usd_per_million
            ),
            "output_usd_per_million": _decimal_text(
                self.output_usd_per_million
            ),
            "cached_input_usd_per_million": _decimal_text(
                self.cached_input_usd_per_million
            ),
            "cache_write_usd_per_million": _decimal_text(
                self.cache_write_usd_per_million
            ),
            "cache_read_usd_per_million": _decimal_text(
                self.cache_read_usd_per_million
            ),
        }


@dataclass(frozen=True, slots=True)
class RoleExecutionRequest:
    """Sealed semantic request supplied to one exact planned role."""

    role: str
    instructions: str
    schema: dict[str, Any]
    input_payload: dict[str, Any]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.role, str)
            or not self.role
            or not isinstance(self.instructions, str)
            or not self.instructions
            or not isinstance(self.schema, dict)
            or not isinstance(self.input_payload, dict)
        ):
            raise ExecutionLedgerError(
                "role execution request is not a closed semantic request"
            )


@dataclass(frozen=True, slots=True)
class MeteredUsage:
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    cost_usd: Decimal

    @property
    def total_input_tokens(self) -> int:
        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.output_tokens

    def binding(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "cache_creation_input_tokens": (
                self.cache_creation_input_tokens
            ),
            "cache_read_input_tokens": self.cache_read_input_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": _decimal_text(self.cost_usd),
        }


def _decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ExecutionLedgerError("non-finite decimal is forbidden")
    return format(value, "f")


def _parse_decimal(value: object, *, label: str) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ExecutionLedgerError(f"{label} must be an exact decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ExecutionLedgerError(f"{label} is invalid") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ExecutionLedgerError(f"{label} must be finite and non-negative")
    return parsed


def _token_count(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutionLedgerError(f"{label} must be a non-negative integer")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_mode & 0o077
    ):
        raise ExecutionLedgerError(
            "execution ledger directory must be private and owned"
        )


def _read_private_json(path: Path, *, label: str) -> dict[str, Any]:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ExecutionLedgerError("O_NOFOLLOW is required")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        )
    except OSError as exc:
        raise ExecutionLedgerError(f"{label} is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
            or metadata.st_size <= 0
            or metadata.st_size > MAX_LEDGER_BYTES
        ):
            raise ExecutionLedgerError(
                f"{label} must be one private owned regular file"
            )
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = -1
            payload = json.load(handle)
    except ExecutionLedgerError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionLedgerError(f"{label} is invalid JSON") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if not isinstance(payload, dict):
        raise ExecutionLedgerError(f"{label} must be one JSON object")
    return payload


def _atomic_private_json(path: Path, payload: Mapping[str, Any]) -> None:
    _private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            descriptor = -1
            json.dump(
                payload,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


class _ExclusiveLedgerLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor = -1

    def __enter__(self) -> "_ExclusiveLedgerLock":
        _private_directory(self.path.parent)
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        self.descriptor = os.open(self.path, flags, 0o600)
        metadata = os.fstat(self.descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
            or metadata.st_mode & 0o077
        ):
            os.close(self.descriptor)
            self.descriptor = -1
            raise ExecutionLedgerError(
                "execution ledger lock must be private and owned"
            )
        fcntl.flock(self.descriptor, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_: object) -> None:
        if self.descriptor >= 0:
            fcntl.flock(self.descriptor, fcntl.LOCK_UN)
            os.close(self.descriptor)
            self.descriptor = -1


def _derived_ceiling(plan: InferencePlan) -> dict[str, Any]:
    budget = plan.budget
    return {
        "max_requests": budget.projected_requests + budget.remaining_requests,
        "max_input_tokens": (
            budget.projected_input_tokens + budget.remaining_input_tokens
        ),
        "max_output_tokens": (
            budget.projected_output_tokens + budget.remaining_output_tokens
        ),
        "max_total_tokens": (
            budget.projected_total_tokens + budget.remaining_total_tokens
        ),
        "max_usd": _decimal_text(
            budget.projected_usd + budget.remaining_usd
        ),
    }


def _opening_usage(plan: InferencePlan) -> dict[str, Any]:
    budget = plan.budget
    return {
        "requests": budget.used_requests_before,
        "input_tokens": budget.used_input_tokens_before,
        "output_tokens": budget.used_output_tokens_before,
        "total_tokens": budget.used_total_tokens_before,
        "usd": _decimal_text(budget.used_usd_before),
    }


def _reservation(call: PlannedRoleCall) -> dict[str, Any]:
    return {
        "requests": 1,
        "input_tokens": call.max_input_tokens,
        "output_tokens": call.max_output_tokens,
        "total_tokens": call.max_total_tokens,
        "usd": _decimal_text(call.max_usd),
    }


def _price_map(
    prices: tuple[ModelPrice, ...],
) -> dict[tuple[str, str], ModelPrice]:
    rows: dict[tuple[str, str], ModelPrice] = {}
    for price in prices:
        key = (price.provider, price.model)
        if key in rows:
            raise ExecutionLedgerError(
                "duplicate provider/model price entry"
            )
        rows[key] = price
    return rows


def _validate_plan(plan: InferencePlan) -> None:
    if (
        not isinstance(plan, InferencePlan)
        or plan.status != "planned"
        or plan.fail_closed
        or not plan.calls
        or plan.budget.within_ceiling is not True
        or plan.budget.failed_ceiling
    ):
        raise ExecutionLedgerError(
            "only one non-empty, within-budget planned route is executable"
        )
    call_roles = tuple(call.role for call in plan.calls)
    if len(set(call_roles)) != len(call_roles):
        raise ExecutionLedgerError("planned role calls contain duplicates")
    available = set(plan.reused_roles)
    for call in plan.calls:
        if set(call.dependency_roles) - available:
            raise ExecutionLedgerError(
                f"{call.role} planned dependencies are not available"
            )
        available.add(call.role)
    if set(plan.required_roles) != available:
        raise ExecutionLedgerError(
            "planned and reused roles do not complete the required role set"
        )


class DurableRoleExecutionLedger:
    """Private append-only accounting for one immutable inference plan."""

    def __init__(
        self,
        path: Path,
        *,
        plan: InferencePlan,
        prices: tuple[ModelPrice, ...],
    ) -> None:
        _validate_plan(plan)
        if not isinstance(path, Path) or not path.is_absolute():
            raise ExecutionLedgerError(
                "execution ledger path must be absolute"
            )
        self.path = path
        self.lock_path = path.with_name(f".{path.name}.lock")
        self.plan = plan
        self.prices = prices
        self.price_by_identity = _price_map(prices)
        for call in plan.calls:
            if (call.provider, call.model) not in self.price_by_identity:
                raise ExecutionLedgerError(
                    f"missing pinned price for {call.provider}/{call.model}"
                )
        self.header = {
            "plan_sha256": plan.plan_sha256,
            "cycle_date": plan.cycle_date.isoformat(),
            "semantic_hash": plan.semantic_hash,
            "policy_sha256": plan.policy_sha256,
            "call_bindings": [
                _json_binding(call.binding()) for call in plan.calls
            ],
            "reused_result_sha256s": [
                list(row) for row in plan.reused_result_sha256s
            ],
            "opening_usage": _opening_usage(plan),
            "cycle_ceiling": _derived_ceiling(plan),
            "prices": [
                price.binding()
                for price in sorted(
                    prices,
                    key=lambda row: (row.provider, row.model),
                )
            ],
            "fixture_transport_only": True,
            "provider_fallback_allowed": False,
        }
        self.header["header_sha256"] = canonical_sha256(self.header)
        with _ExclusiveLedgerLock(self.lock_path):
            if self.path.exists():
                state = self._load_validate_locked()
                if state["header"] != self.header:
                    raise ExecutionLedgerError(
                        "existing ledger binding differs from the plan"
                    )
            else:
                state = {
                    "schema_version": LEDGER_SCHEMA_VERSION,
                    "header": copy.deepcopy(self.header),
                    "events": [],
                }
                self._append_event_locked(
                    state,
                    kind="cycle_opened",
                    role="",
                    call_binding_sha256="",
                    details={
                        "opening_usage": copy.deepcopy(
                            self.header["opening_usage"]
                        ),
                        "cycle_ceiling": copy.deepcopy(
                            self.header["cycle_ceiling"]
                        ),
                    },
                )

    def _save_locked(self, state: dict[str, Any]) -> None:
        unsigned = copy.deepcopy(state)
        unsigned.pop("ledger_sha256", None)
        state["ledger_sha256"] = canonical_sha256(unsigned)
        _atomic_private_json(self.path, state)

    def _load_validate_locked(self) -> dict[str, Any]:
        state = _read_private_json(self.path, label="execution ledger")
        if set(state) != {
            "schema_version",
            "header",
            "events",
            "ledger_sha256",
        }:
            raise ExecutionLedgerError("execution ledger fields are invalid")
        unsigned = copy.deepcopy(state)
        claimed_hash = unsigned.pop("ledger_sha256")
        if (
            state["schema_version"] != LEDGER_SCHEMA_VERSION
            or not isinstance(state["header"], dict)
            or not isinstance(state["events"], list)
            or canonical_sha256(unsigned) != claimed_hash
        ):
            raise ExecutionLedgerError(
                "execution ledger hash or schema is invalid"
            )
        header = copy.deepcopy(state["header"])
        header_hash = header.pop("header_sha256", "")
        if canonical_sha256(header) != header_hash:
            raise ExecutionLedgerError(
                "execution ledger header hash is invalid"
            )
        previous = ""
        reservations: dict[str, dict[str, Any]] = {}
        terminals: set[str] = set()
        for index, event in enumerate(state["events"], start=1):
            if (
                not isinstance(event, dict)
                or set(event)
                != {
                    "event_index",
                    "event_kind",
                    "role",
                    "call_binding_sha256",
                    "recorded_at",
                    "details",
                    "previous_event_sha256",
                    "event_sha256",
                }
                or event["event_index"] != index
                or event["event_kind"] not in ALLOWED_EVENT_KINDS
                or event["previous_event_sha256"] != previous
                or not isinstance(event["details"], dict)
            ):
                raise ExecutionLedgerError(
                    "execution ledger event chain is invalid"
                )
            unsigned_event = copy.deepcopy(event)
            event_hash = unsigned_event.pop("event_sha256")
            if canonical_sha256(unsigned_event) != event_hash:
                raise ExecutionLedgerError(
                    "execution ledger event hash is invalid"
                )
            previous = event_hash
            kind = event["event_kind"]
            role = event["role"]
            binding = event["call_binding_sha256"]
            if kind == "cycle_opened":
                if index != 1 or role or binding:
                    raise ExecutionLedgerError(
                        "execution ledger opening event is invalid"
                    )
                continue
            if (
                not isinstance(role, str)
                or not role
                or not _is_sha256(binding)
            ):
                raise ExecutionLedgerError(
                    "execution ledger role event identity is invalid"
                )
            if kind == "call_reserved":
                if binding in reservations:
                    raise ExecutionLedgerError(
                        "execution call was reserved more than once"
                    )
                reservations[binding] = event
            elif binding not in reservations or binding in terminals:
                raise ExecutionLedgerError(
                    "execution terminal event has no unique reservation"
                )
            else:
                terminals.add(binding)
        if not state["events"] or state["events"][0]["event_kind"] != "cycle_opened":
            raise ExecutionLedgerError(
                "execution ledger opening event is missing"
            )
        self._assert_budget_locked(state)
        return state

    def _append_event_locked(
        self,
        state: dict[str, Any],
        *,
        kind: str,
        role: str,
        call_binding_sha256: str,
        details: dict[str, Any],
    ) -> None:
        previous = (
            state["events"][-1]["event_sha256"]
            if state["events"]
            else ""
        )
        event = {
            "event_index": len(state["events"]) + 1,
            "event_kind": kind,
            "role": role,
            "call_binding_sha256": call_binding_sha256,
            "recorded_at": iso_now(),
            "details": copy.deepcopy(details),
            "previous_event_sha256": previous,
        }
        event["event_sha256"] = canonical_sha256(event)
        state["events"].append(event)
        self._assert_budget_locked(state)
        self._save_locked(state)

    def _events_by_binding(
        self,
        state: dict[str, Any],
        binding_sha256: str,
    ) -> list[dict[str, Any]]:
        return [
            event
            for event in state["events"]
            if event["call_binding_sha256"] == binding_sha256
        ]

    def _usage_locked(self, state: dict[str, Any]) -> dict[str, Any]:
        opening = self.header["opening_usage"]
        usage = {
            "requests": int(opening["requests"]),
            "input_tokens": int(opening["input_tokens"]),
            "output_tokens": int(opening["output_tokens"]),
            "total_tokens": int(opening["total_tokens"]),
            "usd": _parse_decimal(opening["usd"], label="opening usd"),
        }
        by_binding: dict[str, list[dict[str, Any]]] = {}
        for event in state["events"]:
            binding = event["call_binding_sha256"]
            if binding:
                by_binding.setdefault(binding, []).append(event)
        for events in by_binding.values():
            reservation = events[0]["details"]["reservation"]
            terminal = events[-1]
            charged = (
                terminal["details"]["charged_usage"]
                if terminal["event_kind"] == "call_completed"
                else reservation
            )
            usage["requests"] += int(charged["requests"])
            usage["input_tokens"] += int(charged["input_tokens"])
            usage["output_tokens"] += int(charged["output_tokens"])
            usage["total_tokens"] += int(charged["total_tokens"])
            usage["usd"] += _parse_decimal(
                charged["usd"],
                label="charged usd",
            )
        return usage

    def _assert_budget_locked(self, state: dict[str, Any]) -> None:
        usage = self._usage_locked(state)
        ceiling = self.header["cycle_ceiling"]
        checks = (
            ("requests", usage["requests"], int(ceiling["max_requests"])),
            (
                "input_tokens",
                usage["input_tokens"],
                int(ceiling["max_input_tokens"]),
            ),
            (
                "output_tokens",
                usage["output_tokens"],
                int(ceiling["max_output_tokens"]),
            ),
            (
                "total_tokens",
                usage["total_tokens"],
                int(ceiling["max_total_tokens"]),
            ),
            (
                "usd",
                usage["usd"],
                _parse_decimal(ceiling["max_usd"], label="ceiling usd"),
            ),
        )
        failed = next(
            (label for label, used, maximum in checks if used > maximum),
            "",
        )
        if failed:
            raise ExecutionBudgetError(
                f"execution ledger exceeds frozen {failed} ceiling"
            )

    def budget_snapshot(self) -> dict[str, Any]:
        with _ExclusiveLedgerLock(self.lock_path):
            state = self._load_validate_locked()
            usage = self._usage_locked(state)
            return {
                "plan_sha256": self.plan.plan_sha256,
                "used_requests": usage["requests"],
                "used_input_tokens": usage["input_tokens"],
                "used_output_tokens": usage["output_tokens"],
                "used_total_tokens": usage["total_tokens"],
                "used_usd": _decimal_text(usage["usd"]),
                "cycle_ceiling": copy.deepcopy(
                    self.header["cycle_ceiling"]
                ),
                "ledger_sha256": state["ledger_sha256"],
            }

    def _result_path(self, role: str) -> Path:
        return self.path.with_name(f"{self.path.stem}.{role}.receipt.json")

    def _request_binding(
        self,
        call: PlannedRoleCall,
        request: RoleExecutionRequest,
        dependency_results: Mapping[str, str],
    ) -> dict[str, Any]:
        if request.role != call.role:
            raise ExecutionLedgerError("request role differs from planned role")
        if canonical_sha256(request.schema) != call.response_schema_sha256:
            raise ExecutionLedgerError(
                f"{call.role} response schema binding is stale"
            )
        if tuple(dependency_results) != call.dependency_roles:
            raise ExecutionLedgerError(
                f"{call.role} dependency result order is not exact"
            )
        for digest in dependency_results.values():
            if not _is_sha256(digest):
                raise ExecutionLedgerError(
                    f"{call.role} dependency result hash is invalid"
                )
        binding = {
            "plan_sha256": self.plan.plan_sha256,
            "call": _json_binding(call.binding()),
            "dependency_result_sha256s": [
                [role, dependency_results[role]]
                for role in call.dependency_roles
            ],
            "instructions_sha256": hashlib.sha256(
                request.instructions.encode("utf-8")
            ).hexdigest(),
            "schema_sha256": canonical_sha256(request.schema),
            "input_sha256": canonical_sha256(request.input_payload),
        }
        binding["request_binding_sha256"] = canonical_sha256(binding)
        return binding

    def _metered_usage(
        self,
        call: PlannedRoleCall,
        metadata: Mapping[str, Any],
    ) -> MeteredUsage:
        if metadata.get("transport") != "fixture":
            raise ExecutionLedgerError(
                "live provider transport is not enabled by this executor"
            )
        usage = metadata.get("usage")
        if not isinstance(usage, dict):
            raise ExecutionLedgerError(
                "fixture provider metadata requires metered usage"
            )
        allowed = {
            "input_tokens",
            "output_tokens",
            "cached_input_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        }
        if set(usage) - allowed or not {
            "input_tokens",
            "output_tokens",
        }.issubset(usage):
            raise ExecutionLedgerError(
                "provider usage fields do not match the metering contract"
            )
        input_tokens = _token_count(
            usage["input_tokens"],
            label="provider input_tokens",
        )
        output_tokens = _token_count(
            usage["output_tokens"],
            label="provider output_tokens",
        )
        cached = _token_count(
            usage.get("cached_input_tokens", 0),
            label="provider cached_input_tokens",
        )
        cache_creation = _token_count(
            usage.get("cache_creation_input_tokens", 0),
            label="provider cache_creation_input_tokens",
        )
        cache_read = _token_count(
            usage.get("cache_read_input_tokens", 0),
            label="provider cache_read_input_tokens",
        )
        if cached > input_tokens:
            raise ExecutionLedgerError(
                "cached input tokens cannot exceed base input tokens"
            )
        price = self.price_by_identity[(call.provider, call.model)]
        million = Decimal(1_000_000)
        cost = (
            Decimal(input_tokens - cached)
            * price.input_usd_per_million
            + Decimal(cached)
            * price.cached_input_usd_per_million
            + Decimal(cache_creation)
            * price.cache_write_usd_per_million
            + Decimal(cache_read)
            * price.cache_read_usd_per_million
            + Decimal(output_tokens)
            * price.output_usd_per_million
        ) / million
        metered = MeteredUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached,
            cache_creation_input_tokens=cache_creation,
            cache_read_input_tokens=cache_read,
            cost_usd=cost,
        )
        if (
            metered.total_input_tokens > call.max_input_tokens
            or metered.output_tokens > call.max_output_tokens
            or metered.total_tokens > call.max_total_tokens
            or metered.cost_usd > call.max_usd
        ):
            raise ExecutionBudgetError(
                f"{call.role} actual metered usage exceeds its reservation"
            )
        return metered

    def _validate_receipt_locked(
        self,
        path: Path,
        *,
        binding: dict[str, Any],
        validator: PayloadValidator,
    ) -> tuple[dict[str, Any], dict[str, Any], MeteredUsage, str]:
        receipt = _read_private_json(path, label="metered role receipt")
        unsigned = copy.deepcopy(receipt)
        claimed_hash = unsigned.pop("receipt_sha256", "")
        if (
            set(receipt)
            != {
                "schema_version",
                "plan_sha256",
                "role",
                "request_binding",
                "request_binding_sha256",
                "payload",
                "payload_sha256",
                "provider_metadata",
                "metered_usage",
                "fixture_transport_only",
                "receipt_sha256",
            }
            or receipt["schema_version"] != RECEIPT_SCHEMA_VERSION
            or receipt["plan_sha256"] != self.plan.plan_sha256
            or receipt["role"] != binding["call"]["role"]
            or receipt["request_binding"] != binding
            or receipt["request_binding_sha256"]
            != binding["request_binding_sha256"]
            or not isinstance(receipt["payload"], dict)
            or receipt["payload_sha256"]
            != canonical_sha256(receipt["payload"])
            or not isinstance(receipt["provider_metadata"], dict)
            or receipt["fixture_transport_only"] is not True
            or canonical_sha256(unsigned) != claimed_hash
        ):
            raise ExecutionLedgerError(
                "metered role receipt binding is invalid"
            )
        validator(receipt["payload"])
        call = next(
            row
            for row in self.plan.calls
            if row.role == receipt["role"]
        )
        metered = self._metered_usage(
            call,
            receipt["provider_metadata"],
        )
        if receipt["metered_usage"] != metered.binding():
            raise ExecutionLedgerError(
                "metered role receipt usage was not recomputed exactly"
            )
        return (
            copy.deepcopy(receipt["payload"]),
            copy.deepcopy(receipt["provider_metadata"]),
            metered,
            _sha256_file(path),
        )

    def execute_role_fixture(
        self,
        *,
        call: PlannedRoleCall,
        request: RoleExecutionRequest,
        dependency_results: Mapping[str, str],
        provider_factory: Callable[[], ModelProvider],
        validator: PayloadValidator,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute one exact role; persist intent before provider construction."""

        if call not in self.plan.calls:
            raise ExecutionLedgerError("role call is not in the frozen plan")
        sealed_request = RoleExecutionRequest(
            role=request.role,
            instructions=request.instructions,
            schema=copy.deepcopy(request.schema),
            input_payload=copy.deepcopy(request.input_payload),
        )
        binding = self._request_binding(
            call,
            sealed_request,
            dict(dependency_results),
        )
        binding_sha256 = binding["request_binding_sha256"]
        receipt_path = self._result_path(call.role)
        with _ExclusiveLedgerLock(self.lock_path):
            state = self._load_validate_locked()
            matching = self._events_by_binding(state, binding_sha256)
            if matching:
                terminal = matching[-1]
                if terminal["event_kind"] == "call_completed":
                    payload, metadata, _, receipt_file_sha256 = (
                        self._validate_receipt_locked(
                            receipt_path,
                            binding=binding,
                            validator=validator,
                        )
                    )
                    if (
                        terminal["details"]["receipt_file_sha256"]
                        != receipt_file_sha256
                    ):
                        raise ExecutionLedgerError(
                            "completed receipt file hash is invalid"
                        )
                    return payload, metadata
                if terminal["event_kind"] == "call_reserved":
                    if receipt_path.exists():
                        payload, metadata, metered, receipt_file_sha256 = (
                            self._validate_receipt_locked(
                                receipt_path,
                                binding=binding,
                                validator=validator,
                            )
                        )
                        self._append_event_locked(
                            state,
                            kind="call_completed",
                            role=call.role,
                            call_binding_sha256=binding_sha256,
                            details={
                                "charged_usage": {
                                    "requests": 1,
                                    "input_tokens": (
                                        metered.total_input_tokens
                                    ),
                                    "output_tokens": metered.output_tokens,
                                    "total_tokens": metered.total_tokens,
                                    "usd": _decimal_text(
                                        metered.cost_usd
                                    ),
                                },
                                "result_sha256": canonical_sha256(payload),
                                "receipt_file_sha256": (
                                    receipt_file_sha256
                                ),
                                "recovered_after_interruption": True,
                            },
                        )
                        return payload, metadata
                    self._append_event_locked(
                        state,
                        kind="call_outcome_unknown",
                        role=call.role,
                        call_binding_sha256=binding_sha256,
                        details={
                            "charged_usage": _reservation(call),
                            "reason": (
                                "durable_reservation_without_result_receipt"
                            ),
                        },
                    )
                    raise ExecutionRecoveryRequired(
                        f"{call.role} prior provider outcome is unknown; "
                        "worst-case reservation remains charged"
                    )
                raise ExecutionRecoveryRequired(
                    f"{call.role} prior execution is terminal and not reusable"
                )
            if any(
                event["role"] == call.role
                and event["event_kind"] != "cycle_opened"
                for event in state["events"]
            ):
                raise ExecutionLedgerError(
                    f"{call.role} was already attempted under another binding"
                )
            self._append_event_locked(
                state,
                kind="call_reserved",
                role=call.role,
                call_binding_sha256=binding_sha256,
                details={
                    "request_binding": copy.deepcopy(binding),
                    "reservation": _reservation(call),
                    "provider_constructed": False,
                    "fixture_transport_only": True,
                },
            )
            try:
                provider = provider_factory()
                result = provider.generate(
                    role=call.role,
                    model=call.model,
                    reasoning_effort=call.reasoning_effort,
                    schema=copy.deepcopy(sealed_request.schema),
                    instructions=sealed_request.instructions,
                    input_payload=copy.deepcopy(
                        sealed_request.input_payload
                    ),
                )
                if not isinstance(result, ProviderResult):
                    raise ExecutionLedgerError(
                        "provider returned an invalid result object"
                    )
                validator(result.payload)
                metered = self._metered_usage(call, result.metadata)
                receipt = {
                    "schema_version": RECEIPT_SCHEMA_VERSION,
                    "plan_sha256": self.plan.plan_sha256,
                    "role": call.role,
                    "request_binding": copy.deepcopy(binding),
                    "request_binding_sha256": binding_sha256,
                    "payload": copy.deepcopy(result.payload),
                    "payload_sha256": canonical_sha256(result.payload),
                    "provider_metadata": copy.deepcopy(result.metadata),
                    "metered_usage": metered.binding(),
                    "fixture_transport_only": True,
                }
                receipt["receipt_sha256"] = canonical_sha256(receipt)
                _atomic_private_json(receipt_path, receipt)
                receipt_file_sha256 = _sha256_file(receipt_path)
            except Exception as error:
                self._append_event_locked(
                    state,
                    kind="call_failed",
                    role=call.role,
                    call_binding_sha256=binding_sha256,
                    details={
                        "charged_usage": _reservation(call),
                        "failure_type": type(error).__name__,
                        "retryable": False,
                    },
                )
                raise
            self._append_event_locked(
                state,
                kind="call_completed",
                role=call.role,
                call_binding_sha256=binding_sha256,
                details={
                    "charged_usage": {
                        "requests": 1,
                        "input_tokens": metered.total_input_tokens,
                        "output_tokens": metered.output_tokens,
                        "total_tokens": metered.total_tokens,
                        "usd": _decimal_text(metered.cost_usd),
                    },
                    "result_sha256": canonical_sha256(result.payload),
                    "receipt_file_sha256": receipt_file_sha256,
                    "recovered_after_interruption": False,
                },
            )
            return copy.deepcopy(result.payload), copy.deepcopy(result.metadata)

    def execute_plan_fixture(
        self,
        *,
        requests: Mapping[str, RoleExecutionRequest],
        provider_factories: Mapping[str, Callable[[], ModelProvider]],
        validators: Mapping[str, PayloadValidator],
    ) -> dict[str, dict[str, Any]]:
        """Execute exactly the router-planned roles, never an implicit role."""

        expected_roles = tuple(call.role for call in self.plan.calls)
        if (
            set(requests) != set(expected_roles)
            or set(provider_factories) != set(expected_roles)
            or set(validators) != set(expected_roles)
        ):
            raise ExecutionLedgerError(
                "fixture executor inputs must match exact planned roles"
            )
        result_hashes = dict(self.plan.reused_result_sha256s)
        results: dict[str, dict[str, Any]] = {}
        for call in self.plan.calls:
            dependencies = {
                role: result_hashes[role]
                for role in call.dependency_roles
            }
            payload, metadata = self.execute_role_fixture(
                call=call,
                request=requests[call.role],
                dependency_results=dependencies,
                provider_factory=provider_factories[call.role],
                validator=validators[call.role],
            )
            result_hashes[call.role] = canonical_sha256(payload)
            results[call.role] = {
                "payload": payload,
                "provider_metadata": metadata,
                "result_sha256": result_hashes[call.role],
            }
        return results


def _json_binding(value: Any) -> Any:
    """Convert router Decimal/tuple bindings into canonical JSON values."""

    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, Mapping):
        return {key: _json_binding(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_binding(item) for item in value]
    return value


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "DurableRoleExecutionLedger",
    "ExecutionBudgetError",
    "ExecutionLedgerError",
    "ExecutionRecoveryRequired",
    "LEDGER_SCHEMA_VERSION",
    "MeteredUsage",
    "ModelPrice",
    "DEFAULT_LEDGER_RELATIVE_ROOT",
    "cycle_execution_ledger_path",
    "default_execution_ledger_root",
    "RECEIPT_SCHEMA_VERSION",
    "RoleExecutionRequest",
]
