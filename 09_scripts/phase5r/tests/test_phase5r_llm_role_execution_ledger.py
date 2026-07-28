from __future__ import annotations

import copy
import json
import socket
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_llm_cost_aware_router import (
    CycleCeilings,
    CycleUsage,
    RoleCallSpec,
    RouterPolicy,
    RoutingSignals,
    canonical_sha256,
    plan_inference,
    semantic_sha256,
)
from phase5r_llm_provider import ProviderResult
from phase5r_llm_role_execution_ledger import (
    DurableRoleExecutionLedger,
    ExecutionBudgetError,
    ExecutionLedgerError,
    ExecutionRecoveryRequired,
    ModelPrice,
    RoleExecutionRequest,
    cycle_execution_ledger_path,
    default_execution_ledger_root,
)


CYCLE_DATE = date(2026, 7, 24)


def _schema(role: str) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["role", "decision"],
        "properties": {
            "role": {"const": role},
            "decision": {"type": "string"},
        },
    }


def _policy() -> RouterPolicy:
    roles = []
    for index, role in enumerate(
        ("analyst", "committee", "critic", "challenger"),
        start=1,
    ):
        if role == "analyst":
            provider = "fixture-primary"
            model = "gpt-5.6-terra"
        elif role in {"committee", "critic"}:
            provider = "fixture-primary"
            model = "gpt-5.6-sol"
        else:
            provider = "fixture-challenger"
            model = "claude-fable-5"
        roles.append(
            RoleCallSpec(
                role=role,
                provider=provider,
                model=model,
                reasoning_effort="medium" if role == "analyst" else "high",
                prompt_version=f"fixture-{role}-v1",
                response_schema_sha256=canonical_sha256(_schema(role)),
                max_input_tokens=100 * index,
                max_output_tokens=50,
                max_usd=Decimal("0.50"),
            )
        )
    return RouterPolicy(role_specs=tuple(roles))


def _plan(*, roles: int):
    if roles == 1:
        signals = {
            "material_evidence_changed": True,
            "classification_may_change": False,
            "decision_changed": False,
            "material_thesis_break": False,
            "disagreement": False,
            "previous_classification": "hold_existing",
            "proposed_classification": "hold_existing",
        }
    elif roles == 2:
        signals = {
            "material_evidence_changed": True,
            "classification_may_change": True,
            "decision_changed": False,
            "material_thesis_break": False,
            "disagreement": False,
            "previous_classification": "hold_existing",
            "proposed_classification": "hold_existing",
        }
    elif roles == 4:
        signals = {
            "material_evidence_changed": True,
            "classification_may_change": True,
            "decision_changed": True,
            "material_thesis_break": True,
            "disagreement": True,
            "previous_classification": "hold_existing",
            "proposed_classification": "exit_review",
        }
    else:
        raise AssertionError("unsupported test role count")
    policy = _policy()
    return plan_inference(
        policy=policy,
        ceilings=CycleCeilings(
            cycle_date=CYCLE_DATE,
            max_requests_per_cycle=4,
            max_input_tokens_per_request=1000,
            max_output_tokens_per_request=500,
            max_total_tokens_per_request=1500,
            max_usd_per_request=Decimal("1"),
            max_input_tokens_per_cycle=4000,
            max_output_tokens_per_cycle=2000,
            max_total_tokens_per_cycle=6000,
            max_usd_per_cycle=Decimal("4"),
        ),
        usage=CycleUsage(
            cycle_date=CYCLE_DATE,
            used_requests=0,
            used_input_tokens=0,
            used_output_tokens=0,
            used_usd=Decimal("0"),
        ),
        signals=RoutingSignals(
            cycle_date=CYCLE_DATE,
            semantic_hash=semantic_sha256({"sealed": "evidence-v1"}),
            evidence_sufficient=True,
            available_providers=frozenset(
                spec.provider for spec in policy.role_specs
            ),
            **signals,
        ),
    )


def _prices(plan) -> tuple[ModelPrice, ...]:
    identities = {
        (call.provider, call.model)
        for call in plan.calls
    }
    return tuple(
        ModelPrice(
            provider=provider,
            model=model,
            input_usd_per_million=Decimal("2.50"),
            output_usd_per_million=Decimal("15"),
            cached_input_usd_per_million=Decimal("0.25"),
        )
        for provider, model in sorted(identities)
    )


def _request(role: str) -> RoleExecutionRequest:
    return RoleExecutionRequest(
        role=role,
        instructions=f"Return the exact {role} fixture contract.",
        schema=_schema(role),
        input_payload={"sealed_role_input": role},
    )


class _MeteredFixtureProvider:
    def __init__(
        self,
        role: str,
        *,
        input_tokens: int = 20,
        output_tokens: int = 10,
    ) -> None:
        self.role = role
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def generate(self, **kwargs):
        if kwargs["role"] != self.role:
            raise AssertionError("unexpected role")
        payload = {"role": self.role, "decision": "hold"}
        return ProviderResult(
            payload=payload,
            metadata={
                "transport": "fixture",
                "usage": {
                    "input_tokens": self.input_tokens,
                    "output_tokens": self.output_tokens,
                    "cached_input_tokens": 5,
                },
                "credential_read": False,
                "tools_enabled": False,
            },
        )


class RoleExecutionLedgerTests(unittest.TestCase):
    def test_default_cycle_ledger_path_is_fixed_and_outside_repository(
        self,
    ) -> None:
        user_home = Path("/Users/phase5r-test")
        self.assertEqual(
            default_execution_ledger_root(user_home=user_home),
            user_home
            / "Library"
            / "Application Support"
            / "Phase5R"
            / "llm_execution",
        )
        self.assertEqual(
            cycle_execution_ledger_path(
                CYCLE_DATE,
                user_home=user_home,
            ),
            user_home
            / "Library"
            / "Application Support"
            / "Phase5R"
            / "llm_execution"
            / "2026"
            / "phase5r-2026-07-24.ledger.json",
        )

    def test_reserves_before_provider_construction_and_charges_actual_usage(
        self,
    ) -> None:
        plan = _plan(roles=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution-ledger.json"
            ledger = DurableRoleExecutionLedger(
                path,
                plan=plan,
                prices=_prices(plan),
            )

            def factory():
                persisted = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(
                    persisted["events"][-1]["event_kind"],
                    "call_reserved",
                )
                self.assertFalse(
                    persisted["events"][-1]["details"][
                        "provider_constructed"
                    ]
                )
                return _MeteredFixtureProvider("analyst")

            call = plan.calls[0]
            payload, _ = ledger.execute_role_fixture(
                call=call,
                request=_request(call.role),
                dependency_results={},
                provider_factory=factory,
                validator=lambda row: self.assertEqual(
                    row["role"],
                    "analyst",
                ),
            )
            self.assertEqual(payload["decision"], "hold")
            snapshot = ledger.budget_snapshot()
            self.assertEqual(snapshot["used_requests"], 1)
            self.assertEqual(snapshot["used_input_tokens"], 20)
            self.assertEqual(snapshot["used_output_tokens"], 10)
            self.assertEqual(snapshot["used_total_tokens"], 30)
            self.assertEqual(snapshot["used_usd"], "0.00018875")
            receipt = path.with_name(
                "execution-ledger.analyst.receipt.json"
            )
            self.assertEqual(receipt.stat().st_mode & 0o077, 0)

    def test_executes_exact_four_role_route_with_dependency_hashes(
        self,
    ) -> None:
        plan = _plan(roles=4)
        with tempfile.TemporaryDirectory() as directory:
            ledger = DurableRoleExecutionLedger(
                Path(directory) / "ledger.json",
                plan=plan,
                prices=_prices(plan),
            )
            requests = {
                call.role: _request(call.role) for call in plan.calls
            }
            providers = {
                call.role: (
                    lambda role=call.role: _MeteredFixtureProvider(role)
                )
                for call in plan.calls
            }
            validators = {
                call.role: (
                    lambda payload, role=call.role: self.assertEqual(
                        payload["role"],
                        role,
                    )
                )
                for call in plan.calls
            }
            with mock.patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("network forbidden"),
            ):
                results = ledger.execute_plan_fixture(
                    requests=requests,
                    provider_factories=providers,
                    validators=validators,
                )
            self.assertEqual(
                tuple(results),
                ("analyst", "committee", "critic", "challenger"),
            )
            self.assertEqual(ledger.budget_snapshot()["used_requests"], 4)
            committee_receipt = json.loads(
                (
                    Path(directory) / "ledger.committee.receipt.json"
                ).read_text(encoding="utf-8")
            )
            dependency_rows = committee_receipt["request_binding"][
                "dependency_result_sha256s"
            ]
            self.assertEqual(dependency_rows[0][0], "analyst")
            self.assertEqual(
                dependency_rows[0][1],
                results["analyst"]["result_sha256"],
            )

    def test_unresolved_reservation_is_charged_and_never_called_again(
        self,
    ) -> None:
        plan = _plan(roles=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = DurableRoleExecutionLedger(
                path,
                plan=plan,
                prices=_prices(plan),
            )
            call = plan.calls[0]

            def interrupted_factory():
                raise KeyboardInterrupt()

            with self.assertRaises(KeyboardInterrupt):
                ledger.execute_role_fixture(
                    call=call,
                    request=_request(call.role),
                    dependency_results={},
                    provider_factory=interrupted_factory,
                    validator=lambda _: None,
                )
            second_factory = mock.Mock(
                side_effect=AssertionError("must not call provider again")
            )
            with self.assertRaisesRegex(
                ExecutionRecoveryRequired,
                "outcome is unknown",
            ):
                ledger.execute_role_fixture(
                    call=call,
                    request=_request(call.role),
                    dependency_results={},
                    provider_factory=second_factory,
                    validator=lambda _: None,
                )
            second_factory.assert_not_called()
            snapshot = ledger.budget_snapshot()
            self.assertEqual(snapshot["used_requests"], 1)
            self.assertEqual(
                snapshot["used_input_tokens"],
                call.max_input_tokens,
            )
            self.assertEqual(snapshot["used_usd"], "0.50")

    def test_over_budget_metadata_fails_and_keeps_worst_case_charge(
        self,
    ) -> None:
        plan = _plan(roles=1)
        with tempfile.TemporaryDirectory() as directory:
            ledger = DurableRoleExecutionLedger(
                Path(directory) / "ledger.json",
                plan=plan,
                prices=_prices(plan),
            )
            call = plan.calls[0]
            with self.assertRaises(ExecutionBudgetError):
                ledger.execute_role_fixture(
                    call=call,
                    request=_request(call.role),
                    dependency_results={},
                    provider_factory=lambda: _MeteredFixtureProvider(
                        call.role,
                        input_tokens=call.max_input_tokens + 1,
                    ),
                    validator=lambda _: None,
                )
            snapshot = ledger.budget_snapshot()
            self.assertEqual(
                snapshot["used_input_tokens"],
                call.max_input_tokens,
            )
            self.assertEqual(snapshot["used_usd"], "0.50")

    def test_exact_role_and_request_bindings_fail_closed(self) -> None:
        plan = _plan(roles=2)
        with tempfile.TemporaryDirectory() as directory:
            ledger = DurableRoleExecutionLedger(
                Path(directory) / "ledger.json",
                plan=plan,
                prices=_prices(plan),
            )
            with self.assertRaisesRegex(
                ExecutionLedgerError,
                "exact planned roles",
            ):
                ledger.execute_plan_fixture(
                    requests={"analyst": _request("analyst")},
                    provider_factories={
                        "analyst": lambda: _MeteredFixtureProvider("analyst")
                    },
                    validators={"analyst": lambda _: None},
                )
            stale = copy.deepcopy(_schema("analyst"))
            stale["properties"]["extra"] = {"type": "string"}
            with self.assertRaisesRegex(
                ExecutionLedgerError,
                "schema binding is stale",
            ):
                ledger.execute_role_fixture(
                    call=plan.calls[0],
                    request=RoleExecutionRequest(
                        role="analyst",
                        instructions="test",
                        schema=stale,
                        input_payload={},
                    ),
                    dependency_results={},
                    provider_factory=lambda: _MeteredFixtureProvider(
                        "analyst"
                    ),
                    validator=lambda _: None,
                )

    def test_tampered_ledger_is_rejected(self) -> None:
        plan = _plan(roles=1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            DurableRoleExecutionLedger(
                path,
                plan=plan,
                prices=_prices(plan),
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["events"][0]["details"]["opening_usage"]["requests"] = 9
            path.write_text(json.dumps(payload), encoding="utf-8")
            path.chmod(0o600)
            with self.assertRaisesRegex(
                ExecutionLedgerError,
                "hash or schema",
            ):
                DurableRoleExecutionLedger(
                    path,
                    plan=plan,
                    prices=_prices(plan),
                )

    def test_non_fixture_transport_is_never_accepted(self) -> None:
        plan = _plan(roles=1)

        class LiveLookingProvider(_MeteredFixtureProvider):
            def generate(self, **kwargs):
                result = super().generate(**kwargs)
                result.metadata["transport"] = "openai_responses_api"
                return result

        with tempfile.TemporaryDirectory() as directory:
            ledger = DurableRoleExecutionLedger(
                Path(directory) / "ledger.json",
                plan=plan,
                prices=_prices(plan),
            )
            call = plan.calls[0]
            with self.assertRaisesRegex(
                ExecutionLedgerError,
                "live provider transport is not enabled",
            ):
                ledger.execute_role_fixture(
                    call=call,
                    request=_request(call.role),
                    dependency_results={},
                    provider_factory=lambda: LiveLookingProvider(call.role),
                    validator=lambda _: None,
                )


if __name__ == "__main__":
    unittest.main()
