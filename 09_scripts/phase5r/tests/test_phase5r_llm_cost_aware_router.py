from __future__ import annotations

import hashlib
import socket
import subprocess
import unittest
import urllib.request
from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from unittest import mock

from _support import SCRIPT_DIR  # noqa: F401
from phase5r_llm_cost_aware_router import (
    CycleCeilings,
    CycleUsage,
    RoleCallSpec,
    RouterConfigurationError,
    RouterInputError,
    RouterPolicy,
    RoutingSignals,
    build_reusable_role_result,
    plan_inference,
    semantic_sha256,
)


FRIDAY = date(2026, 7, 24)
SATURDAY = date(2026, 7, 25)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _role(
    role: str,
    *,
    provider: str,
    model: str,
    max_input_tokens: int,
    max_output_tokens: int,
    max_usd: str,
) -> RoleCallSpec:
    return RoleCallSpec(
        role=role,
        provider=provider,
        model=model,
        reasoning_effort=(
            "medium" if role == "analyst" else "high"
        ),
        prompt_version=f"test-{role}-v1",
        response_schema_sha256=_digest(f"schema:{role}:v1"),
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_usd=Decimal(max_usd),
    )


def _policy(
    *,
    challenger_provider: str = "anthropic",
    analyst_input_tokens: int = 1000,
    committee_input_tokens: int = 1200,
) -> RouterPolicy:
    return RouterPolicy(
        role_specs=(
            _role(
                "analyst",
                provider="openai",
                model="gpt-5.6-terra",
                max_input_tokens=analyst_input_tokens,
                max_output_tokens=200,
                max_usd="0.10",
            ),
            _role(
                "committee",
                provider="openai",
                model="gpt-5.6-sol",
                max_input_tokens=committee_input_tokens,
                max_output_tokens=300,
                max_usd="0.20",
            ),
            _role(
                "critic",
                provider="openai",
                model="gpt-5.6-sol",
                max_input_tokens=1200,
                max_output_tokens=300,
                max_usd="0.20",
            ),
            _role(
                "challenger",
                provider=challenger_provider,
                model="claude-fable-5",
                max_input_tokens=1200,
                max_output_tokens=300,
                max_usd="0.30",
            ),
        ),
    )


def _ceilings(
    *,
    cycle_date: date = FRIDAY,
    max_requests: int = 4,
    request_input: int = 2000,
    request_output: int = 1000,
    request_total: int = 3000,
    request_usd: str = "0.50",
    cycle_input: int = 6000,
    cycle_output: int = 3000,
    cycle_total: int = 9000,
    cycle_usd: str = "1.00",
) -> CycleCeilings:
    return CycleCeilings(
        cycle_date=cycle_date,
        max_requests_per_cycle=max_requests,
        max_input_tokens_per_request=request_input,
        max_output_tokens_per_request=request_output,
        max_total_tokens_per_request=request_total,
        max_usd_per_request=Decimal(request_usd),
        max_input_tokens_per_cycle=cycle_input,
        max_output_tokens_per_cycle=cycle_output,
        max_total_tokens_per_cycle=cycle_total,
        max_usd_per_cycle=Decimal(cycle_usd),
    )


def _usage(
    *,
    cycle_date: date = FRIDAY,
    requests: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    usd: str = "0",
) -> CycleUsage:
    return CycleUsage(
        cycle_date=cycle_date,
        used_requests=requests,
        used_input_tokens=input_tokens,
        used_output_tokens=output_tokens,
        used_usd=Decimal(usd),
    )


def _signals(
    *,
    cycle_date: date = FRIDAY,
    semantic_label: str = "evidence-v1",
    evidence_sufficient: bool = True,
    material: bool = False,
    may_change: bool = False,
    decision_changed: bool = False,
    thesis_break: bool = False,
    disagreement: bool = False,
    previous: str | None = "hold_existing",
    proposed: str | None = "hold_existing",
    providers: frozenset[str] = frozenset(
        {"openai", "anthropic"}
    ),
    reusable_results=(),
) -> RoutingSignals:
    return RoutingSignals(
        cycle_date=cycle_date,
        semantic_hash=semantic_sha256(
            {"sealed_evidence": semantic_label}
        ),
        evidence_sufficient=evidence_sufficient,
        material_evidence_changed=material,
        classification_may_change=may_change,
        decision_changed=decision_changed,
        material_thesis_break=thesis_break,
        disagreement=disagreement,
        previous_classification=previous,
        proposed_classification=proposed,
        available_providers=providers,
        reusable_results=tuple(reusable_results),
    )


def _all_reusable(
    policy: RouterPolicy,
    semantic_hash: str,
) -> tuple:
    analyst_hash = _digest("result:analyst")
    committee_hash = _digest("result:committee")
    return (
        build_reusable_role_result(
            policy=policy,
            role="analyst",
            semantic_hash=semantic_hash,
            result_sha256=analyst_hash,
            dependency_results={},
        ),
        build_reusable_role_result(
            policy=policy,
            role="committee",
            semantic_hash=semantic_hash,
            result_sha256=committee_hash,
            dependency_results={"analyst": analyst_hash},
        ),
        build_reusable_role_result(
            policy=policy,
            role="critic",
            semantic_hash=semantic_hash,
            result_sha256=_digest("result:critic"),
            dependency_results={
                "analyst": analyst_hash,
                "committee": committee_hash,
            },
        ),
        build_reusable_role_result(
            policy=policy,
            role="challenger",
            semantic_hash=semantic_hash,
            result_sha256=_digest("result:challenger"),
            dependency_results={"analyst": analyst_hash},
        ),
    )


class CostAwareRouterTests(unittest.TestCase):
    def test_weekday_no_change_stays_local_without_provider(self) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(providers=frozenset()),
        )
        self.assertEqual(plan.status, "local_only")
        self.assertEqual(plan.reason, "no_material_semantic_change")
        self.assertEqual(plan.calls, ())
        self.assertEqual(plan.required_roles, ())
        self.assertFalse(plan.fail_closed)
        self.assertFalse(
            plan.to_dict()["boundaries"][
                "provider_client_constructed"
            ]
        )

    def test_weekend_no_change_is_suppressed_even_with_new_hash(
        self,
    ) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(cycle_date=SATURDAY),
            usage=_usage(cycle_date=SATURDAY),
            signals=_signals(
                cycle_date=SATURDAY,
                semantic_label="timestamp-only-new-hash",
                providers=frozenset(),
            ),
        )
        self.assertEqual(plan.status, "suppressed")
        self.assertEqual(
            plan.reason,
            "weekend_no_change_suppressed",
        )
        self.assertTrue(plan.weekend_suppressed)
        self.assertEqual(plan.calls, ())

    def test_weekend_material_change_routes_terra(self) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(cycle_date=SATURDAY),
            usage=_usage(cycle_date=SATURDAY),
            signals=_signals(
                cycle_date=SATURDAY,
                material=True,
            ),
        )
        self.assertEqual(plan.status, "planned")
        self.assertEqual(plan.required_roles, ("analyst",))
        self.assertEqual(
            [(call.role, call.model) for call in plan.calls],
            [("analyst", "gpt-5.6-terra")],
        )

    def test_material_evidence_gets_only_terra_pass(self) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(material=True),
        )
        self.assertEqual(plan.required_roles, ("analyst",))
        self.assertEqual(
            tuple(call.role for call in plan.calls),
            ("analyst",),
        )

    def test_possible_class_change_escalates_to_sol_proposal(
        self,
    ) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(material=True, may_change=True),
        )
        self.assertEqual(
            plan.required_roles,
            ("analyst", "committee"),
        )
        self.assertEqual(
            [(call.role, call.model) for call in plan.calls],
            [
                ("analyst", "gpt-5.6-terra"),
                ("committee", "gpt-5.6-sol"),
            ],
        )
        self.assertNotIn(
            "challenger",
            {call.role for call in plan.calls},
        )

    def test_high_impact_transition_gets_critic_and_blind_challenger(
        self,
    ) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(
                material=True,
                previous="hold_existing",
                proposed="real_trade_candidate",
            ),
        )
        self.assertTrue(plan.high_impact_transition)
        self.assertEqual(plan.required_roles, (
            "analyst",
            "committee",
            "critic",
            "challenger",
        ))
        self.assertEqual(
            [
                (call.role, call.provider, call.model)
                for call in plan.calls
            ],
            [
                ("analyst", "openai", "gpt-5.6-terra"),
                ("committee", "openai", "gpt-5.6-sol"),
                ("critic", "openai", "gpt-5.6-sol"),
                ("challenger", "anthropic", "claude-fable-5"),
            ],
        )
        challenger = plan.calls[-1]
        self.assertEqual(
            challenger.dependency_roles,
            ("analyst",),
        )
        self.assertFalse(challenger.provider_fallback_allowed)

    def test_disagreement_alone_requires_cross_family_challenger(
        self,
    ) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(disagreement=True),
        )
        self.assertFalse(plan.high_impact_transition)
        self.assertTrue(plan.disagreement)
        self.assertEqual(
            tuple(call.role for call in plan.calls),
            ("analyst", "committee", "critic", "challenger"),
        )

    def test_low_impact_transition_never_routes_challenger(
        self,
    ) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(
                previous="hold_existing",
                proposed="watchlist",
            ),
        )
        self.assertFalse(plan.high_impact_transition)
        self.assertEqual(
            tuple(call.role for call in plan.calls),
            ("analyst", "committee"),
        )

    def test_material_thesis_break_is_high_impact(self) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(thesis_break=True),
        )
        self.assertTrue(plan.high_impact_transition)
        self.assertEqual(
            tuple(call.role for call in plan.calls),
            ("analyst", "committee", "critic", "challenger"),
        )

    def test_insufficient_evidence_fails_closed_without_call(self) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(
                evidence_sufficient=False,
                material=True,
                may_change=True,
            ),
        )
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(
            plan.reason,
            "deterministic_evidence_insufficient",
        )
        self.assertTrue(plan.fail_closed)
        self.assertEqual(plan.calls, ())

    def test_exact_semantic_role_results_are_reused_at_budget_limit(
        self,
    ) -> None:
        policy = _policy()
        base = _signals(
            material=True,
            previous="hold_existing",
            proposed="real_trade_candidate",
        )
        signals = replace(
            base,
            reusable_results=_all_reusable(
                policy,
                base.semantic_hash,
            ),
        )
        plan = plan_inference(
            policy=policy,
            ceilings=_ceilings(),
            usage=_usage(
                requests=4,
                input_tokens=6000,
                output_tokens=3000,
                usd="1.00",
            ),
            signals=signals,
        )
        self.assertEqual(plan.status, "reused")
        self.assertEqual(plan.reason, "semantic_hash_reuse")
        self.assertEqual(plan.calls, ())
        self.assertEqual(plan.reused_roles, (
            "analyst",
            "committee",
            "critic",
            "challenger",
        ))
        self.assertEqual(plan.budget.reserved_requests, 0)

    def test_stale_semantic_hash_never_reuses(self) -> None:
        policy = _policy()
        stale_hash = semantic_sha256(
            {"sealed_evidence": "old"}
        )
        signals = _signals(
            material=True,
            previous="hold_existing",
            proposed="real_trade_candidate",
            reusable_results=_all_reusable(policy, stale_hash),
        )
        plan = plan_inference(
            policy=policy,
            ceilings=_ceilings(),
            usage=_usage(),
            signals=signals,
        )
        self.assertEqual(plan.reused_roles, ())
        self.assertEqual(len(plan.calls), 4)

    def test_downstream_cache_is_not_reused_without_upstream_result(
        self,
    ) -> None:
        policy = _policy()
        semantic_hash = _signals().semantic_hash
        committee = build_reusable_role_result(
            policy=policy,
            role="committee",
            semantic_hash=semantic_hash,
            result_sha256=_digest("result:committee"),
            dependency_results={
                "analyst": _digest("result:analyst")
            },
        )
        signals = _signals(
            material=True,
            previous="hold_existing",
            proposed="real_trade_candidate",
            reusable_results=(committee,),
        )
        plan = plan_inference(
            policy=policy,
            ceilings=_ceilings(),
            usage=_usage(),
            signals=signals,
        )
        self.assertEqual(plan.reused_roles, ())
        self.assertEqual(len(plan.calls), 4)

    def test_blind_challenger_cache_depends_only_on_analyst(self) -> None:
        policy = _policy()
        semantic_hash = _signals().semantic_hash
        analyst_hash = _digest("result:analyst")
        analyst = build_reusable_role_result(
            policy=policy,
            role="analyst",
            semantic_hash=semantic_hash,
            result_sha256=analyst_hash,
            dependency_results={},
        )
        challenger = build_reusable_role_result(
            policy=policy,
            role="challenger",
            semantic_hash=semantic_hash,
            result_sha256=_digest("result:challenger"),
            dependency_results={"analyst": analyst_hash},
        )
        signals = _signals(
            material=True,
            previous="hold_existing",
            proposed="real_trade_candidate",
            reusable_results=(analyst, challenger),
        )
        plan = plan_inference(
            policy=policy,
            ceilings=_ceilings(),
            usage=_usage(),
            signals=signals,
        )
        self.assertEqual(
            plan.reused_roles,
            ("analyst", "challenger"),
        )
        self.assertEqual(
            tuple(call.role for call in plan.calls),
            ("committee", "critic"),
        )

    def test_corrupt_current_reuse_binding_is_rejected(self) -> None:
        policy = _policy()
        signals = _signals(
            material=True,
            may_change=True,
        )
        analyst = build_reusable_role_result(
            policy=policy,
            role="analyst",
            semantic_hash=signals.semantic_hash,
            result_sha256=_digest("result:analyst"),
            dependency_results={},
        )
        corrupt = replace(
            analyst,
            role_binding_sha256=_digest("forged-binding"),
        )
        with self.assertRaisesRegex(
            RouterInputError,
            "binding is invalid",
        ):
            plan_inference(
                policy=policy,
                ceilings=_ceilings(),
                usage=_usage(),
                signals=replace(
                    signals,
                    reusable_results=(corrupt,),
                ),
            )

    def test_unavailable_challenger_never_falls_back(self) -> None:
        plan = plan_inference(
            policy=_policy(),
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(
                material=True,
                previous="hold_existing",
                proposed="exit_review",
                providers=frozenset({"openai", "google"}),
            ),
        )
        self.assertEqual(plan.status, "blocked")
        self.assertEqual(
            plan.reason,
            "provider_unavailable_no_fallback:anthropic",
        )
        self.assertTrue(plan.fail_closed)
        self.assertEqual(plan.calls, ())
        self.assertFalse(
            plan.to_dict()["boundaries"][
                "provider_fallback_allowed"
            ]
        )

    def test_budget_exhaustion_returns_no_partial_call_plan(self) -> None:
        scenarios = (
            (
                "cycle_requests",
                _ceilings(max_requests=3),
                _usage(),
            ),
            (
                "cycle_input_tokens",
                _ceilings(
                    cycle_input=4500,
                    cycle_total=7500,
                ),
                _usage(),
            ),
            (
                "cycle_output_tokens",
                _ceilings(
                    cycle_output=1000,
                    cycle_total=7000,
                ),
                _usage(),
            ),
            (
                "cycle_total_tokens",
                _ceilings(
                    cycle_input=5000,
                    cycle_output=3000,
                    cycle_total=5600,
                ),
                _usage(),
            ),
            (
                "cycle_usd",
                _ceilings(cycle_usd="0.79"),
                _usage(),
            ),
        )
        for expected, ceilings, usage in scenarios:
            with self.subTest(ceiling=expected):
                plan = plan_inference(
                    policy=_policy(),
                    ceilings=ceilings,
                    usage=usage,
                    signals=_signals(
                        material=True,
                        previous="hold_existing",
                        proposed="real_trade_candidate",
                    ),
                )
                self.assertEqual(plan.status, "blocked")
                self.assertEqual(
                    plan.reason,
                    f"budget_exhausted:{expected}",
                )
                self.assertTrue(plan.fail_closed)
                self.assertEqual(plan.calls, ())
                self.assertEqual(
                    plan.budget.reserved_requests,
                    4,
                )

    def test_per_request_ceiling_blocks_entire_plan(self) -> None:
        plan = plan_inference(
            policy=_policy(committee_input_tokens=1200),
            ceilings=_ceilings(
                request_input=1100,
                request_total=2100,
            ),
            usage=_usage(),
            signals=_signals(material=True, may_change=True),
        )
        self.assertEqual(
            plan.reason,
            "budget_exhausted:"
            "per_request_input_tokens:committee",
        )
        self.assertEqual(plan.calls, ())
        self.assertTrue(plan.fail_closed)

    def test_existing_usage_over_ceiling_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            RouterInputError,
            "already exceeds",
        ):
            plan_inference(
                policy=_policy(),
                ceilings=_ceilings(max_requests=3),
                usage=_usage(requests=4),
                signals=_signals(),
            )

    def test_cycle_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            RouterInputError,
            "cycles must match",
        ):
            plan_inference(
                policy=_policy(),
                ceilings=_ceilings(),
                usage=_usage(cycle_date=SATURDAY),
                signals=_signals(),
            )

    def test_policy_and_budget_are_immutable(self) -> None:
        policy = _policy()
        ceilings = _ceilings()
        with self.assertRaises(FrozenInstanceError):
            ceilings.max_requests_per_cycle = 99  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            policy.provider_fallback_allowed = True  # type: ignore[misc]
        with self.assertRaises(RouterConfigurationError):
            replace(policy, provider_fallback_allowed=True)
        with self.assertRaisesRegex(
            RouterConfigurationError,
            "different provider family",
        ):
            _policy(challenger_provider="openai")

    def test_plan_hash_is_deterministic_and_semantic_bound(self) -> None:
        policy = _policy()
        first = plan_inference(
            policy=policy,
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(material=True),
        )
        second = plan_inference(
            policy=policy,
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(material=True),
        )
        changed = plan_inference(
            policy=policy,
            ceilings=_ceilings(),
            usage=_usage(),
            signals=_signals(
                semantic_label="evidence-v2",
                material=True,
            ),
        )
        self.assertEqual(first.plan_sha256, second.plan_sha256)
        self.assertEqual(
            first.to_dict()["plan_sha256"],
            first.plan_sha256,
        )
        self.assertNotEqual(
            first.plan_sha256,
            changed.plan_sha256,
        )

    def test_planner_never_invokes_process_or_network(self) -> None:
        with (
            mock.patch.object(
                subprocess,
                "run",
                side_effect=AssertionError("process invoked"),
            ) as process_mock,
            mock.patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("network invoked"),
            ) as socket_mock,
            mock.patch.object(
                urllib.request,
                "urlopen",
                side_effect=AssertionError("HTTP invoked"),
            ) as http_mock,
        ):
            plan = plan_inference(
                policy=_policy(),
                ceilings=_ceilings(),
                usage=_usage(),
                signals=_signals(
                    material=True,
                    previous="hold_existing",
                    proposed="real_trade_candidate",
                ),
            )
        self.assertEqual(plan.status, "planned")
        process_mock.assert_not_called()
        socket_mock.assert_not_called()
        http_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
