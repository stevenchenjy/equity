from __future__ import annotations

import contextlib
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from _support import materialized
from phase5r_daily_common import canonical_sha256
from phase5r_llm_contract import ContractError, response_schema
from phase5r_llm_cost_aware_router import semantic_sha256
from phase5r_llm_shadow_router_gate import (
    CHALLENGER_PROMPT_VERSION,
    CHALLENGER_PROVIDER,
    PRIMARY_PROVIDER,
    SHADOW_ROUTER_ENVELOPE_SCHEMA_VERSION,
    plan_shadow_router_envelope,
    shadow_router_gate_receipt,
)
import run_phase5r_llm_shadow as shadow_runtime
import run_phase5r_llm_shadow_scheduler as shadow_scheduler


def _role_spec(
    role: str,
    *,
    registry: dict[str, object],
) -> dict[str, object]:
    if role == "challenger":
        provider = CHALLENGER_PROVIDER
        model = "claude-fable-5"
        reasoning_effort = "high"
        prompt_version = CHALLENGER_PROMPT_VERSION
    else:
        config = registry["roles"][role]
        provider = PRIMARY_PROVIDER
        model = config["model"]
        reasoning_effort = config["reasoning_effort"]
        prompt_version = config["prompt_version"]
    return {
        "role": role,
        "provider": provider,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "prompt_version": prompt_version,
        "response_schema_sha256": canonical_sha256(
            response_schema(role)
        ),
        "max_input_tokens": 2000,
        "max_output_tokens": 500,
        "max_usd": "0.50",
    }


def _envelope(
    packet: dict[str, object],
    registry: dict[str, object],
    *,
    material_change: bool = True,
) -> dict[str, object]:
    cycle = packet["cycle_date"]
    semantic_hash = semantic_sha256(
        {
            "packet_view": shadow_runtime._analyst_packet_view(
                packet
            )
        }
    )
    return {
        "schema_version": SHADOW_ROUTER_ENVELOPE_SCHEMA_VERSION,
        "policy": {
            "role_specs": [
                _role_spec(role, registry=registry)
                for role in (
                    "analyst",
                    "committee",
                    "critic",
                    "challenger",
                )
            ],
            "high_impact_classifications": [
                "paper_trade_candidate",
                "real_trade_candidate",
                "trim_review",
                "exit_review",
            ],
            "independent_challenger_required": False,
            "provider_fallback_allowed": False,
        },
        "ceilings": {
            "cycle_date": cycle,
            "max_requests_per_cycle": 4,
            "max_input_tokens_per_request": 3000,
            "max_output_tokens_per_request": 1000,
            "max_total_tokens_per_request": 4000,
            "max_usd_per_request": "1.00",
            "max_input_tokens_per_cycle": 10000,
            "max_output_tokens_per_cycle": 4000,
            "max_total_tokens_per_cycle": 14000,
            "max_usd_per_cycle": "4.00",
        },
        "usage": {
            "cycle_date": cycle,
            "used_requests": 0,
            "used_input_tokens": 0,
            "used_output_tokens": 0,
            "used_usd": "0",
        },
        "signals": {
            "cycle_date": cycle,
            "semantic_hash": semantic_hash,
            "evidence_sufficient": True,
            "material_evidence_changed": material_change,
            "classification_may_change": False,
            "decision_changed": False,
            "material_thesis_break": False,
            "disagreement": False,
            "previous_classification": "hold_existing",
            "proposed_classification": "hold_existing",
            "available_providers": [
                PRIMARY_PROVIDER,
                CHALLENGER_PROVIDER,
            ],
        },
    }


def _write_envelope(
    directory: str,
    payload: dict[str, object],
) -> Path:
    path = Path(directory) / "router-envelope.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class ShadowRouterGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.packet, _, _ = materialized("g01_stable_hold")
        self.registry = shadow_runtime.load_registry()

    def test_valid_material_plan_is_blocked_before_provider_execution(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            envelope_path = _write_envelope(
                directory,
                _envelope(self.packet, self.registry),
            )
            plan, envelope_sha256 = plan_shadow_router_envelope(
                envelope_path,
                semantic_payload={
                    "packet_view": shadow_runtime._analyst_packet_view(
                        self.packet
                    )
                },
                packet_cycle_date=self.packet["cycle_date"],
                registry=self.registry,
            )
        self.assertEqual(plan.status, "planned")
        self.assertEqual(
            tuple(call.role for call in plan.calls),
            ("analyst",),
        )
        receipt = shadow_router_gate_receipt(
            plan=plan,
            envelope_sha256=envelope_sha256,
            packet_id=self.packet["packet_id"],
            decision_fingerprint=self.packet[
                "decision_fingerprint"
            ],
            model_run_id="a" * 64,
        )
        gate = receipt["execution_gate"]
        self.assertEqual(gate["status"], "blocked")
        self.assertEqual(
            gate["reason"],
            "live_provider_execution_not_authorized",
        )
        self.assertTrue(gate["exact_role_executor_integrated"])
        self.assertTrue(gate["fixture_execution_available"])
        self.assertFalse(gate["live_provider_execution_authorized"])
        self.assertFalse(gate["provider_client_constructed"])
        self.assertFalse(gate["provider_attempt_started"])
        self.assertFalse(gate["provider_receipt_created"])
        self.assertEqual(gate["budget_charged_requests"], 0)
        unsigned = copy.deepcopy(receipt)
        receipt_sha256 = unsigned.pop("receipt_sha256")
        self.assertEqual(receipt_sha256, canonical_sha256(unsigned))

    def test_no_change_plan_is_a_durable_no_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            envelope_path = _write_envelope(
                directory,
                _envelope(
                    self.packet,
                    self.registry,
                    material_change=False,
                ),
            )
            receipt = shadow_runtime._run_explicit_router_gate(
                envelope_path=envelope_path,
                packet=self.packet,
                registry=self.registry,
                model_run_id="b" * 64,
                output_dir=Path(directory) / "outputs",
            )
            receipt_path = (
                Path(directory)
                / "outputs"
                / "phase5r_llm_shadow_router_gate.local.json"
            )
            persisted = json.loads(
                receipt_path.read_text(encoding="utf-8")
            )
        self.assertEqual(receipt["execution_gate"]["status"], "no_call")
        self.assertEqual(
            receipt["plan"]["reason"],
            "no_material_semantic_change",
        )
        self.assertEqual(persisted, receipt)
        self.assertFalse(
            persisted["boundaries"]["network_attempted"]
        )

    def test_stale_semantic_hash_fails_closed(self) -> None:
        payload = _envelope(self.packet, self.registry)
        payload["signals"]["semantic_hash"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            envelope_path = _write_envelope(directory, payload)
            with self.assertRaisesRegex(
                ContractError,
                "semantic hash",
            ):
                plan_shadow_router_envelope(
                    envelope_path,
                    semantic_payload={
                        "packet_view": (
                            shadow_runtime._analyst_packet_view(
                                self.packet
                            )
                        )
                    },
                    packet_cycle_date=self.packet["cycle_date"],
                    registry=self.registry,
                )

    def test_primary_model_drift_fails_closed(self) -> None:
        payload = _envelope(self.packet, self.registry)
        payload["policy"]["role_specs"][0]["model"] = "other-model"
        with tempfile.TemporaryDirectory() as directory:
            envelope_path = _write_envelope(directory, payload)
            with self.assertRaisesRegex(
                ContractError,
                "does not match the model registry",
            ):
                plan_shadow_router_envelope(
                    envelope_path,
                    semantic_payload={
                        "packet_view": (
                            shadow_runtime._analyst_packet_view(
                                self.packet
                            )
                        )
                    },
                    packet_cycle_date=self.packet["cycle_date"],
                    registry=self.registry,
                )

    def test_runner_explicit_envelope_never_constructs_provider(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            envelope_path = _write_envelope(
                directory,
                _envelope(self.packet, self.registry),
            )
            output_dir = Path(directory) / "outputs"
            with (
                mock.patch.object(
                    shadow_runtime,
                    "build_packet",
                    return_value=self.packet,
                ),
                mock.patch.object(
                    shadow_runtime,
                    "ExclusiveFileLock",
                    return_value=contextlib.nullcontext(),
                ),
                mock.patch.object(
                    shadow_runtime,
                    "FixtureProvider",
                    side_effect=AssertionError(
                        "provider must not be constructed"
                    ),
                ),
                mock.patch.object(
                    shadow_runtime,
                    "_verify_activation_for_transport",
                    side_effect=AssertionError(
                        "activation must follow the router gate"
                    ),
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_phase5r_llm_shadow.py",
                        "--fixture",
                        str(Path(directory) / "unused-fixture.json"),
                        "--router-envelope",
                        str(envelope_path),
                        "--output-dir",
                        str(output_dir),
                    ],
                ),
            ):
                exit_code = shadow_runtime.main()
        self.assertEqual(exit_code, 0)

    def test_scheduler_explicit_gate_precedes_activation_and_attempt(
        self,
    ) -> None:
        live_registry = copy.deepcopy(self.registry)
        live_registry["mode"] = "shadow"
        live_registry["live_shadow_enabled"] = True
        active = {
            "current_workflow": "daily_decision",
            "active_pipeline": "phase5r_daily",
            "email_delivery_allowed_from": "phase5r_daily_only",
            "broker_connection_allowed": "no",
            "order_code_allowed": "no",
            "manual_execution_only": "yes",
            "operational_from": "2026-01-01",
        }
        inhibit = {
            "active": False,
            "allowed_pipeline": "phase5r_daily",
        }
        router_result = subprocess.CompletedProcess(
            ["router-gate"],
            0,
            stdout=(
                "shadow_router_gate=blocked "
                "provider_invoked=false"
            ),
        )
        validation_modes: list[bool] = []

        def validate(*args, **kwargs):
            validation_modes.append(kwargs["verify_activation"])
            return "deferred"

        with (
            mock.patch.object(
                shadow_scheduler,
                "load_active_state",
                return_value=active,
            ),
            mock.patch.object(
                shadow_scheduler,
                "load_inhibit",
                return_value=inhibit,
            ),
            mock.patch.object(
                shadow_scheduler,
                "load_registry",
                return_value=live_registry,
            ),
            mock.patch.object(
                shadow_scheduler,
                "validate_runtime_boundary",
                side_effect=validate,
            ),
            mock.patch.object(
                shadow_scheduler,
                "now_et",
                return_value=datetime(
                    2026,
                    7,
                    27,
                    19,
                    0,
                    tzinfo=ZoneInfo("America/New_York"),
                ),
            ),
            mock.patch.object(
                shadow_scheduler,
                "_run_explicit_router_gate",
                return_value=router_result,
            ) as gate,
            mock.patch.object(
                shadow_scheduler,
                "read_json",
                side_effect=AssertionError(
                    "scheduler state must follow router gate"
                ),
            ),
            mock.patch.object(
                sys,
                "argv",
                [
                    "run_phase5r_llm_shadow_scheduler.py",
                    "--router-envelope",
                    "/tmp/explicit-router-envelope.json",
                ],
            ),
        ):
            exit_code = shadow_scheduler.main()
        self.assertEqual(exit_code, 0)
        self.assertEqual(validation_modes, [False])
        gate.assert_called_once_with(
            Path("/tmp/explicit-router-envelope.json"),
            check_mode=False,
        )


if __name__ == "__main__":
    unittest.main()
