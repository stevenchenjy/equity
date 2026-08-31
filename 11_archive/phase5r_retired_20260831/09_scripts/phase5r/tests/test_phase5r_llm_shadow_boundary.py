from __future__ import annotations

import ast
import copy
import hashlib
import json
import smtplib
import socket
import sys
import tempfile
import unittest
import urllib.request
from datetime import datetime
from pathlib import Path
from unittest import mock

from _support import PROJECT_ROOT, digest_or_absent, materialized, rehash
import run_phase5r_llm_shadow as shadow_runtime
import run_phase5r_llm_shadow_scheduler as shadow_scheduler
from evaluate_phase5r_llm_decision import (
    _safe_output_dir,
    evaluate_manifest,
    write_report,
)
from enable_phase5r_llm_live_shadow import provider_replay_status
from phase5r_daily_common import EMAIL_CONFIG_PATH
from phase5r_llm_activation_receipt import RUNTIME_CODE_PATHS
from phase5r_llm_contract import ContractError, validate_packet
from phase5r_llm_provider import (
    FixtureProvider,
    ProviderError,
    RetryableProviderTransportError,
)
from run_phase5r_llm_shadow import (
    CachedBundleIntegrityError,
    ShadowRoleResultStore,
    ShadowOutputLock,
    _cached,
    _invocation_transport,
    _outcome_exit_code,
    _write_audit,
    apply_verified_close_stability,
    execute_shadow,
    load_registry,
    output_paths,
)
from run_phase5r_llm_shadow_scheduler import (
    validate_runtime_boundary,
    weekend_has_material_change,
)
from verify_phase5r_llm_provider_replay_gate import (
    MINIMUM_REAL_PACKETS,
    RUNTIME_EVALUATION_CODE_PATHS,
)
from verify_phase5r_llm_shadow_boundary import (
    CANONICAL_RUNTIME_FILES,
    canonical_model_reference_markers,
)


SCRIPT_DIR = PROJECT_ROOT / "09_scripts" / "phase5r"


class RecordingFixtureProvider:
    def __init__(
        self,
        responses: dict[str, dict[str, object]],
        *,
        fail_role: str = "",
    ) -> None:
        self.delegate = FixtureProvider(responses)
        self.fail_role = fail_role
        self.failed = False
        self.calls: list[str] = []

    def generate(self, **kwargs: object):
        role = str(kwargs["role"])
        self.calls.append(role)
        if role == self.fail_role and not self.failed:
            self.failed = True
            raise RetryableProviderTransportError(
                f"injected {role} failure"
            )
        return self.delegate.generate(**kwargs)


class InvalidAnalystProvider(RecordingFixtureProvider):
    def generate(self, **kwargs: object):
        result = super().generate(**kwargs)
        if kwargs["role"] == "analyst":
            result.payload["packet_id"] = "invalid-packet-id"
        return result


class TerminalProviderFailure:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls: list[str] = []

    def generate(self, **kwargs: object):
        role = str(kwargs["role"])
        self.calls.append(role)
        raise ProviderError(self.message)


class CodexMetadataFixtureProvider(RecordingFixtureProvider):
    def __init__(
        self,
        responses: dict[str, dict[str, object]],
        *,
        executable_sha256: str,
    ) -> None:
        super().__init__(responses)
        self.executable_sha256 = executable_sha256

    def generate(self, **kwargs: object):
        result = super().generate(**kwargs)
        result.metadata["transport"] = "codex_cli"
        result.metadata["executable_sha256"] = self.executable_sha256
        return result
SCAN_FILES = (
    SCRIPT_DIR / "phase5r_llm_contract.py",
    SCRIPT_DIR / "build_phase5r_decision_evidence_packet.py",
    SCRIPT_DIR / "phase5r_llm_provider.py",
    SCRIPT_DIR / "phase5r_llm_citation_reviews.py",
    SCRIPT_DIR / "run_phase5r_llm_shadow.py",
    SCRIPT_DIR / "evaluate_phase5r_llm_decision.py",
    SCRIPT_DIR / "run_phase5r_llm_shadow_scheduler.py",
    SCRIPT_DIR / "enable_phase5r_llm_live_shadow.py",
)
SENTINELS = (
    PROJECT_ROOT
    / "07_automation"
    / "email_delivery"
    / "phase5r_daily_delivery_ledger.csv",
    PROJECT_ROOT
    / "07_automation"
    / "email_delivery"
    / "phase5r_c2_delivery_status.csv",
    PROJECT_ROOT
    / "07_automation"
    / "email_delivery"
    / "phase5r_c6_delivery_status.csv",
    PROJECT_ROOT / "00_project_control" / "run_logs" / "phase5r_c7_run_log.csv",
    PROJECT_ROOT
    / "00_project_control"
    / "run_logs"
    / "phase5r_c7_weekly_pipeline_run_log.csv",
    PROJECT_ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_daily_decision.json",
    PROJECT_ROOT
    / "07_automation"
    / "email_briefs"
    / "phase5r_daily_email_brief.txt",
    PROJECT_ROOT
    / "07_automation"
    / "email_briefs"
    / "phase5r_daily_email_brief.html",
    PROJECT_ROOT / "05_risk_and_positions" / "current_positions.local.csv",
    PROJECT_ROOT / "05_risk_and_positions" / "current_account_state.local.json",
    PROJECT_ROOT / "06_execution_records" / "manual_executions.local.csv",
    PROJECT_ROOT
    / "06_execution_records"
    / "phase5r_c9b_pending_execution_report.csv",
    PROJECT_ROOT
    / "06_execution_records"
    / "phase5r_c9b_confirmed_execution_report.csv",
    PROJECT_ROOT
    / "06_execution_records"
    / "phase5r_c9b_reconciliation_report.csv",
    PROJECT_ROOT
    / "05_risk_and_positions"
    / "phase5r_c9_exact_action_plan.csv",
    PROJECT_ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_position_recommendations.csv",
    PROJECT_ROOT
    / "04_research"
    / "realtime_stock_picker_phase5r"
    / "phase5r_c9_new_candidate_recommendations.csv",
)


def smtp_stat() -> tuple[int, int, int, int] | str:
    try:
        metadata = EMAIL_CONFIG_PATH.stat()
    except FileNotFoundError:
        return "absent"
    return (
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


class BoundaryTests(unittest.TestCase):
    def test_weekend_shadow_suppresses_unchanged_decision(self) -> None:
        unchanged = {
            "cycle_date": "2026-07-25",
            "decision_changed": False,
            "human_review_required": False,
            "evidence_gate": {"new_material_event_count": 0},
            "material_events": [],
            "eligible_action_review_candidates": [],
        }
        self.assertFalse(
            weekend_has_material_change(
                current_cycle_date="2026-07-25",
                weekday=5,
                decision=unchanged,
            )
        )
        changed = dict(unchanged)
        changed["decision_changed"] = True
        self.assertTrue(
            weekend_has_material_change(
                current_cycle_date="2026-07-25",
                weekday=5,
                decision=changed,
            )
        )
        self.assertTrue(
            weekend_has_material_change(
                current_cycle_date="2026-07-24",
                weekday=4,
                decision={},
            )
        )

    def test_model_run_id_binds_exact_prompt_schema_and_code(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        registry = load_registry()
        baseline = shadow_runtime._run_id(packet, registry)
        with mock.patch.object(
            shadow_runtime,
            "ANALYST_INSTRUCTIONS",
            shadow_runtime.ANALYST_INSTRUCTIONS + "\nchanged",
        ):
            changed = shadow_runtime._run_id(packet, registry)
        self.assertNotEqual(baseline, changed)

    def test_model_run_id_binds_registry_and_expected_transport(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        registry = load_registry()
        fixture_run = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        shadow_registry = copy.deepcopy(registry)
        shadow_registry["mode"] = "shadow"
        shadow_registry["live_shadow_enabled"] = True
        live_run = shadow_runtime._run_id(
            packet,
            shadow_registry,
            expected_transport="codex_cli",
        )
        self.assertNotEqual(fixture_run, live_run)
        changed_provider = copy.deepcopy(shadow_registry)
        changed_provider["provider_executable_sha256"] = "f" * 64
        self.assertNotEqual(
            live_run,
            shadow_runtime._run_id(
                packet,
                changed_provider,
                expected_transport="codex_cli",
            ),
        )

    def test_role_receipt_crashes_reuse_every_completed_role(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        first_expected = {
            "analyst": ["analyst"],
            "committee": ["analyst", "committee"],
            "critic": ["analyst", "committee", "critic"],
        }
        resumed_expected = {
            "analyst": ["committee", "critic"],
            "committee": ["critic"],
            "critic": [],
        }
        with tempfile.TemporaryDirectory(
            prefix="phase5r-role-receipt-crash-"
        ) as directory:
            for target_role in ("analyst", "committee", "critic"):
                with self.subTest(target_role=target_role):
                    root = Path(directory) / target_role / "runs"
                    store = ShadowRoleResultStore(
                        root,
                        model_run_id=run_id,
                        run_binding=shadow_runtime._shadow_run_binding(
                            packet,
                            registry,
                            model_run_id=run_id,
                            expected_transport="fixture",
                        ),
                    )
                    first = RecordingFixtureProvider(responses)
                    original = store._persist_success
                    injected = {"raised": False}

                    def crash_after_receipt(**kwargs: object) -> None:
                        if (
                            not injected["raised"]
                            and kwargs["role"] == target_role
                        ):
                            injected["raised"] = True
                            raise RuntimeError(
                                f"injected {target_role} receipt crash"
                            )
                        original(**kwargs)

                    with mock.patch.object(
                        store,
                        "_persist_success",
                        side_effect=crash_after_receipt,
                    ):
                        with self.assertRaisesRegex(
                            RuntimeError,
                            f"{target_role} receipt crash",
                        ):
                            execute_shadow(
                                packet,
                                first,
                                registry,
                                distinct_valid_closes=0,
                                expected_transport="fixture",
                                role_store=store,
                            )
                    self.assertEqual(
                        first.calls,
                        first_expected[target_role],
                    )

                    resumed_provider = RecordingFixtureProvider(responses)
                    bundle = execute_shadow(
                        packet,
                        resumed_provider,
                        registry,
                        distinct_valid_closes=0,
                        expected_transport="fixture",
                        role_store=store,
                    )
                    self.assertEqual(
                        resumed_provider.calls,
                        resumed_expected[target_role],
                    )
                    self.assertEqual(bundle["outcome"], "validated")
                    self.assertEqual(
                        set(store.progress["successful_roles"]),
                        {"analyst", "committee", "critic"},
                    )

    def test_failed_committee_retries_only_committee_then_critic(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-role-failure-resume-"
        ) as directory:
            store = ShadowRoleResultStore(
                Path(directory) / "runs",
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            first = RecordingFixtureProvider(
                responses,
                fail_role="committee",
            )
            with self.assertRaises(ProviderError):
                execute_shadow(
                    packet,
                    first,
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                )
            self.assertEqual(first.calls, ["analyst", "committee"])
            resumed = RecordingFixtureProvider(responses)
            bundle = execute_shadow(
                packet,
                resumed,
                registry,
                distinct_valid_closes=0,
                expected_transport="fixture",
                role_store=store,
            )
            self.assertEqual(resumed.calls, ["committee", "critic"])
            self.assertEqual(bundle["outcome"], "validated")
            committee_events = [
                event["event_kind"]
                for event in store.progress["events"]
                if event["role"] == "committee"
            ]
            self.assertEqual(
                committee_events,
                [
                    "attempt_started",
                    "failure",
                    "attempt_started",
                    "success",
                ],
            )

    def test_semantic_invalid_role_is_terminal_without_second_call(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-role-semantic-cap-"
        ) as directory:
            store = ShadowRoleResultStore(
                Path(directory) / "runs",
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            provider = InvalidAnalystProvider(responses)
            with self.assertRaises(ContractError):
                execute_shadow(
                    packet,
                    provider,
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                )
            self.assertEqual(provider.calls, ["analyst"])
            valid_provider = RecordingFixtureProvider(responses)
            with self.assertRaisesRegex(
                ContractError,
                "semantic or policy failure is terminal",
            ):
                execute_shadow(
                    packet,
                    valid_provider,
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                )
            self.assertEqual(valid_provider.calls, [])
            self.assertEqual(
                [
                    event["event_kind"]
                    for event in store.progress["events"]
                    if event["role"] == "analyst"
                ],
                [
                    "attempt_started",
                    "failure",
                ],
            )
            terminal = store.progress["events"][-1]
            self.assertIs(terminal["retryable"], False)
            self.assertFalse(store.retry_authorized())

    def test_malformed_provider_outputs_are_terminal_without_second_call(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        terminal_messages = (
            "analyst model response was not valid JSON",
            "analyst model response exceeded size limit",
            "analyst model response must be one JSON object",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-role-terminal-provider-output-"
        ) as directory:
            for message in terminal_messages:
                with self.subTest(message=message):
                    store = ShadowRoleResultStore(
                        Path(directory)
                        / hashlib.sha256(
                            message.encode("utf-8")
                        ).hexdigest()
                        / "runs",
                        model_run_id=run_id,
                        run_binding=shadow_runtime._shadow_run_binding(
                            packet,
                            registry,
                            model_run_id=run_id,
                            expected_transport="fixture",
                        ),
                    )
                    invalid = TerminalProviderFailure(message)
                    with self.assertRaises(ProviderError):
                        execute_shadow(
                            packet,
                            invalid,
                            registry,
                            distinct_valid_closes=0,
                            expected_transport="fixture",
                            role_store=store,
                        )
                    self.assertEqual(invalid.calls, ["analyst"])
                    valid = RecordingFixtureProvider(responses)
                    with self.assertRaisesRegex(
                        ContractError,
                        "semantic or policy failure is terminal",
                    ):
                        execute_shadow(
                            packet,
                            valid,
                            registry,
                            distinct_valid_closes=0,
                            expected_transport="fixture",
                            role_store=store,
                        )
                    self.assertEqual(valid.calls, [])
                    terminal = store.progress["events"][-1]
                    self.assertEqual(
                        terminal["failure_type"],
                        "ProviderError",
                    )
                    self.assertIs(terminal["retryable"], False)

    def test_retryable_timeout_is_bounded_to_two_attempts(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-role-transport-cap-"
        ) as directory:
            store = ShadowRoleResultStore(
                Path(directory) / "runs",
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            for _ in range(2):
                provider = RecordingFixtureProvider(
                    responses,
                    fail_role="analyst",
                )
                with self.assertRaises(ProviderError):
                    execute_shadow(
                        packet,
                        provider,
                        registry,
                        distinct_valid_closes=0,
                        expected_transport="fixture",
                        role_store=store,
                    )
                self.assertEqual(provider.calls, ["analyst"])
            third = RecordingFixtureProvider(responses)
            with self.assertRaisesRegex(
                ProviderError,
                "attempt limit reached",
            ):
                execute_shadow(
                    packet,
                    third,
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                )
            self.assertEqual(third.calls, [])
            self.assertFalse(store.retry_authorized())
            timeout_failures = [
                event
                for event in store.progress["events"]
                if event["event_kind"] == "failure"
            ]
            self.assertEqual(len(timeout_failures), 2)
            self.assertTrue(
                all(
                    event["failure_type"]
                    == "RetryableProviderTransportError"
                    and event["retryable"] is True
                    for event in timeout_failures
                )
            )

    def test_unknown_post_call_outcome_is_terminal_without_recall(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-role-unknown-outcome-"
        ) as directory:
            store = ShadowRoleResultStore(
                Path(directory) / "runs",
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            first = RecordingFixtureProvider(responses)
            with mock.patch.object(
                store,
                "persist_receipt",
                side_effect=RuntimeError(
                    "injected post-call pre-receipt crash"
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "post-call pre-receipt crash",
                ):
                    execute_shadow(
                        packet,
                        first,
                        registry,
                        distinct_valid_closes=0,
                        expected_transport="fixture",
                        role_store=store,
                    )
            self.assertEqual(first.calls, ["analyst"])
            resumed = RecordingFixtureProvider(responses)
            with self.assertRaisesRegex(
                ContractError,
                "semantic or policy failure is terminal",
            ):
                execute_shadow(
                    packet,
                    resumed,
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                )
            self.assertEqual(resumed.calls, [])
            terminal = store.progress["events"][-1]
            self.assertEqual(terminal["event_kind"], "interrupted")
            self.assertIs(terminal["retryable"], False)

    def test_retry_failure_then_attempt_two_crash_recovers_without_third_call(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-retry-combined-crash-"
        ) as directory:
            for crash_point in ("before_receipt", "after_receipt"):
                with self.subTest(crash_point=crash_point):
                    paths = output_paths(Path(directory) / crash_point)
                    store = ShadowRoleResultStore(
                        paths.role_store_root,
                        model_run_id=run_id,
                        run_binding=shadow_runtime._shadow_run_binding(
                            packet,
                            registry,
                            model_run_id=run_id,
                            expected_transport="fixture",
                        ),
                    )
                    first = RecordingFixtureProvider(
                        responses,
                        fail_role="analyst",
                    )
                    with self.assertRaises(ProviderError) as first_error:
                        execute_shadow(
                            packet,
                            first,
                            registry,
                            distinct_valid_closes=0,
                            expected_transport="fixture",
                            role_store=store,
                        )
                    failure_bundle = shadow_runtime._failure_bundle(
                        packet,
                        registry,
                        first_error.exception,
                        expected_transport="fixture",
                        failure_retryable=True,
                    )
                    shadow_runtime.persist_bundle(
                        paths,
                        failure_bundle,
                        role_store=store,
                        completion_status=None,
                    )
                    second = RecordingFixtureProvider(responses)
                    if crash_point == "before_receipt":
                        patcher = mock.patch.object(
                            store,
                            "persist_receipt",
                            side_effect=RuntimeError(
                                "attempt two pre-receipt crash"
                            ),
                        )
                    else:
                        original_success = store._persist_success

                        def crash_after_receipt(**kwargs: object) -> None:
                            if kwargs["role"] == "analyst":
                                raise RuntimeError(
                                    "attempt two post-receipt crash"
                                )
                            original_success(**kwargs)

                        patcher = mock.patch.object(
                            store,
                            "_persist_success",
                            side_effect=crash_after_receipt,
                        )
                    with patcher:
                        with self.assertRaises(RuntimeError):
                            execute_shadow(
                                packet,
                                second,
                                registry,
                                distinct_valid_closes=0,
                                expected_transport="fixture",
                                role_store=store,
                            )
                    self.assertEqual(second.calls, ["analyst"])
                    self.assertFalse(
                        _cached(
                            paths,
                            run_id,
                            packet=packet,
                            registry=registry,
                            expected_transport="fixture",
                            role_store=store,
                        )
                    )
                    resumed = RecordingFixtureProvider(responses)
                    if crash_point == "before_receipt":
                        with self.assertRaises(ContractError) as terminal:
                            execute_shadow(
                                packet,
                                resumed,
                                registry,
                                distinct_valid_closes=0,
                                expected_transport="fixture",
                                role_store=store,
                            )
                        self.assertEqual(resumed.calls, [])
                        terminal_bundle = shadow_runtime._failure_bundle(
                            packet,
                            registry,
                            terminal.exception,
                            expected_transport="fixture",
                            failure_retryable=False,
                        )
                        shadow_runtime.persist_bundle(
                            paths,
                            terminal_bundle,
                            role_store=store,
                            completion_status="terminal_failure",
                        )
                    else:
                        recovered_bundle = execute_shadow(
                            packet,
                            resumed,
                            registry,
                            distinct_valid_closes=0,
                            expected_transport="fixture",
                            role_store=store,
                        )
                        self.assertEqual(
                            resumed.calls,
                            ["committee", "critic"],
                        )
                        recovered_bundle = (
                            apply_verified_close_stability(
                                packet,
                                recovered_bundle,
                            )
                        )
                        shadow_runtime.persist_bundle(
                            paths,
                            recovered_bundle,
                            role_store=store,
                            completion_status="complete",
                        )
                    analyst_starts = [
                        row
                        for row in store.progress["events"]
                        if row["role"] == "analyst"
                        and row["event_kind"] == "attempt_started"
                    ]
                    self.assertEqual(len(analyst_starts), 2)
                    self.assertTrue(
                        store.completion_manifest_path.is_file()
                    )

    def test_provider_factory_runs_only_after_attempt_intent(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-role-intent-order-"
        ) as directory:
            store = ShadowRoleResultStore(
                Path(directory) / "runs",
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            constructed = {"count": 0}

            def factory() -> RecordingFixtureProvider:
                constructed["count"] += 1
                self.assertEqual(
                    store.progress["events"][-1]["event_kind"],
                    "attempt_started",
                )
                self.assertEqual(
                    store.progress["events"][-1]["role"],
                    "analyst",
                )
                persisted = json.loads(
                    store.progress_path.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    persisted["events"][-1]["event_kind"],
                    "attempt_started",
                )
                return RecordingFixtureProvider(responses)

            bundle = execute_shadow(
                packet,
                shadow_runtime._LazyProvider(factory),
                registry,
                distinct_valid_closes=0,
                expected_transport="fixture",
                role_store=store,
            )
            self.assertEqual(bundle["outcome"], "validated")
            self.assertEqual(constructed["count"], 1)

    def test_malformed_same_run_failure_cache_never_recalls_provider(
        self,
    ) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-malformed-failure-cache-"
        ) as directory:
            paths = output_paths(Path(directory))
            paths.decision_json.write_text(
                json.dumps(
                    {
                        "model_run_id": run_id,
                        "outcome": (
                            "abstain_provider_or_contract_failure"
                        ),
                    }
                ),
                encoding="utf-8",
            )
            paths.decision_json.chmod(0o600)
            with (
                mock.patch.object(
                    shadow_runtime,
                    "load_registry",
                    return_value=registry,
                ),
                mock.patch.object(
                    shadow_runtime,
                    "build_packet",
                    return_value=packet,
                ),
                mock.patch.object(shadow_runtime, "ExclusiveFileLock"),
                mock.patch.object(
                    shadow_runtime,
                    "FixtureProvider",
                    side_effect=AssertionError("provider was recalled"),
                ) as provider_mock,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_phase5r_llm_shadow.py",
                        "--fixture",
                        str(Path(directory) / "unused-fixture.json"),
                        "--output-dir",
                        directory,
                    ],
                ),
            ):
                self.assertEqual(shadow_runtime.main(), 2)
            provider_mock.assert_not_called()

    def test_exact_failure_cache_requires_matching_role_failure(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-exact-failure-cache-"
        ) as directory:
            paths = output_paths(Path(directory))
            store = ShadowRoleResultStore(
                paths.role_store_root,
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            provider = RecordingFixtureProvider(
                responses,
                fail_role="analyst",
            )
            with self.assertRaises(ProviderError) as raised:
                execute_shadow(
                    packet,
                    provider,
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                )
            failure = shadow_runtime._failure_bundle(
                packet,
                registry,
                raised.exception,
                expected_transport="fixture",
                failure_retryable=True,
            )
            paths.decision_json.write_text(
                json.dumps(failure),
                encoding="utf-8",
            )
            paths.decision_json.chmod(0o600)
            self.assertFalse(
                _cached(
                    paths,
                    run_id,
                    packet=packet,
                    registry=registry,
                    expected_transport="fixture",
                    role_store=store,
                )
            )
            failure["failure_type"] = "ContractError"
            failure["adjudication"]["reasons"] = [
                "ContractError:fail_closed"
            ]
            paths.decision_json.write_text(
                json.dumps(failure),
                encoding="utf-8",
            )
            paths.decision_json.chmod(0o600)
            with self.assertRaises(CachedBundleIntegrityError):
                _cached(
                    paths,
                    run_id,
                    packet=packet,
                    registry=registry,
                    expected_transport="fixture",
                    role_store=store,
                )

    def test_fixture_is_rejected_by_active_shadow_registry(self) -> None:
        registry = load_registry()
        registry["mode"] = "shadow"
        registry["live_shadow_enabled"] = True
        with self.assertRaisesRegex(ContractError, "fixture execution"):
            _invocation_transport(
                registry,
                fixture_requested=True,
                live_shadow_requested=False,
            )

    def test_live_cache_requires_codex_metadata_and_fresh_receipt(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        offline_registry = load_registry()
        registry = copy.deepcopy(offline_registry)
        registry["mode"] = "shadow"
        registry["live_shadow_enabled"] = True
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="codex_cli",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-live-cache-test-"
        ) as directory:
            paths = output_paths(Path(directory))
            store = ShadowRoleResultStore(
                paths.role_store_root,
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="codex_cli",
                ),
            )
            payload = execute_shadow(
                packet,
                CodexMetadataFixtureProvider(
                    responses,
                    executable_sha256=registry[
                        "provider_executable_sha256"
                    ],
                ),
                registry,
                distinct_valid_closes=0,
                expected_transport="codex_cli",
                role_store=store,
            )
            payload = apply_verified_close_stability(packet, payload)
            shadow_runtime.persist_bundle(
                paths,
                payload,
                role_store=store,
                completion_status="complete",
            )
            self.assertFalse(
                _cached(
                    paths,
                    run_id,
                    packet=packet,
                    registry=registry,
                    expected_transport="codex_cli",
                    live_activation_verified=False,
                    role_store=store,
                )
            )
            self.assertTrue(
                _cached(
                    paths,
                    run_id,
                    packet=packet,
                    registry=registry,
                    expected_transport="codex_cli",
                    live_activation_verified=True,
                    role_store=store,
                )
            )
            tampered = copy.deepcopy(payload)
            tampered["provider_metadata"][0]["transport"] = "fixture"
            paths.decision_json.write_text(
                json.dumps(tampered),
                encoding="utf-8",
            )
            paths.decision_json.chmod(0o600)
            with self.assertRaises(CachedBundleIntegrityError):
                _cached(
                    paths,
                    run_id,
                    packet=packet,
                    registry=registry,
                    expected_transport="codex_cli",
                    live_activation_verified=True,
                    role_store=store,
                )

    def test_same_run_cache_tampering_fails_closed(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        mutations = {
            "role_output": lambda payload: payload["analyst"]["claims"][0].update(
                {"claim": "tampered cached role output"}
            ),
            "adjudication": lambda payload: payload["adjudication"].update(
                {"headline": "tampered cached adjudication"}
            ),
            "stability": lambda payload: payload["stability"].update(
                {"distinct_valid_closes": 999}
            ),
            "boundaries": lambda payload: payload["boundaries"].update(
                {"email_eligible": True}
            ),
        }
        with tempfile.TemporaryDirectory(
            prefix="phase5r-cache-integrity-test-"
        ) as directory:
            paths = output_paths(Path(directory))
            run_id = shadow_runtime._run_id(
                packet,
                registry,
                expected_transport="fixture",
            )
            store = ShadowRoleResultStore(
                paths.role_store_root,
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            valid = apply_verified_close_stability(
                packet,
                execute_shadow(
                    packet,
                    FixtureProvider(responses),
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                ),
            )
            shadow_runtime.persist_bundle(
                paths,
                valid,
                role_store=store,
                completion_status="complete",
            )
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    payload = copy.deepcopy(valid)
                    mutate(payload)
                    paths.decision_json.write_text(
                        json.dumps(payload),
                        encoding="utf-8",
                    )
                    paths.decision_json.chmod(0o600)
                    with self.assertRaises(CachedBundleIntegrityError):
                        _cached(
                            paths,
                            valid["model_run_id"],
                            packet=packet,
                            registry=registry,
                            expected_transport="fixture",
                            role_store=store,
                        )
                    paths.decision_json.write_bytes(
                        shadow_runtime._json_document_bytes(valid)
                    )
                    paths.decision_json.chmod(0o600)

    def test_cache_read_rejects_symlink_and_hardlink(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        valid = apply_verified_close_stability(
            packet,
            execute_shadow(
                packet,
                FixtureProvider(responses),
                registry,
                distinct_valid_closes=0,
                expected_transport="fixture",
            ),
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-cache-link-test-"
        ) as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text(json.dumps(valid), encoding="utf-8")
            source.chmod(0o600)
            for link_kind in ("symlink", "hardlink"):
                with self.subTest(link_kind=link_kind):
                    target_dir = root / link_kind
                    target_dir.mkdir()
                    paths = output_paths(target_dir)
                    run_id = shadow_runtime._run_id(
                        packet,
                        registry,
                        expected_transport="fixture",
                    )
                    store = ShadowRoleResultStore(
                        paths.role_store_root,
                        model_run_id=run_id,
                        run_binding=shadow_runtime._shadow_run_binding(
                            packet,
                            registry,
                            model_run_id=run_id,
                            expected_transport="fixture",
                        ),
                    )
                    completed_bundle = apply_verified_close_stability(
                        packet,
                        execute_shadow(
                            packet,
                            FixtureProvider(responses),
                            registry,
                            distinct_valid_closes=0,
                            expected_transport="fixture",
                            role_store=store,
                        ),
                    )
                    shadow_runtime.persist_bundle(
                        paths,
                        completed_bundle,
                        role_store=store,
                        completion_status="complete",
                    )
                    paths.decision_json.unlink()
                    if link_kind == "symlink":
                        paths.decision_json.symlink_to(source)
                    else:
                        paths.decision_json.hardlink_to(source)
                    with self.assertRaises(CachedBundleIntegrityError):
                        _cached(
                            paths,
                            valid["model_run_id"],
                            packet=packet,
                            registry=registry,
                            expected_transport="fixture",
                            role_store=store,
                        )

    def test_complete_role_receipts_finish_without_provider_recall(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-complete-receipts-"
        ) as directory:
            paths = output_paths(Path(directory))
            store = ShadowRoleResultStore(
                paths.role_store_root,
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            first = RecordingFixtureProvider(responses)
            execute_shadow(
                packet,
                first,
                registry,
                distinct_valid_closes=0,
                expected_transport="fixture",
                role_store=store,
            )
            self.assertEqual(
                first.calls,
                ["analyst", "committee", "critic"],
            )
            resumed = RecordingFixtureProvider(responses)
            bundle = execute_shadow(
                packet,
                resumed,
                registry,
                distinct_valid_closes=0,
                expected_transport="fixture",
                role_store=store,
            )
            self.assertEqual(resumed.calls, [])
            bundle = apply_verified_close_stability(packet, bundle)
            shadow_runtime.persist_bundle(
                paths,
                bundle,
                role_store=store,
                completion_status="complete",
            )
            self.assertTrue(store.completion_manifest_path.is_file())
            self.assertTrue(
                _cached(
                    paths,
                    run_id,
                    packet=packet,
                    registry=registry,
                    expected_transport="fixture",
                    role_store=store,
                )
            )

    def test_manifest_repairs_missing_outputs_without_provider_recall(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-manifest-repair-"
        ) as directory:
            paths = output_paths(Path(directory))
            store = ShadowRoleResultStore(
                paths.role_store_root,
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            bundle = apply_verified_close_stability(
                packet,
                execute_shadow(
                    packet,
                    RecordingFixtureProvider(responses),
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                ),
            )
            shadow_runtime.persist_bundle(
                paths,
                bundle,
                role_store=store,
                completion_status="complete",
            )
            expected = {
                paths.decision_json: paths.decision_json.read_bytes(),
                paths.decision_report: paths.decision_report.read_bytes(),
                paths.state: paths.state.read_bytes(),
            }
            manifest_before = store.completion_manifest_path.read_bytes()
            for path in (
                paths.decision_report,
                paths.state,
                paths.audit_log,
            ):
                path.unlink()
            with (
                mock.patch.object(
                    shadow_runtime,
                    "load_registry",
                    return_value=registry,
                ),
                mock.patch.object(
                    shadow_runtime,
                    "build_packet",
                    return_value=packet,
                ),
                mock.patch.object(shadow_runtime, "ExclusiveFileLock"),
                mock.patch.object(
                    shadow_runtime,
                    "FixtureProvider",
                    side_effect=AssertionError("provider was recalled"),
                ) as provider_mock,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_phase5r_llm_shadow.py",
                        "--fixture",
                        str(Path(directory) / "unused-fixture.json"),
                        "--output-dir",
                        directory,
                    ],
                ),
            ):
                self.assertEqual(shadow_runtime.main(), 0)
            provider_mock.assert_not_called()
            for path, content in expected.items():
                self.assertEqual(path.read_bytes(), content)
            self.assertTrue(paths.audit_log.is_file())
            self.assertEqual(
                store.completion_manifest_path.read_bytes(),
                manifest_before,
            )

    def test_manifest_tamper_fails_before_missing_output_repair(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-manifest-tamper-"
        ) as directory:
            paths = output_paths(Path(directory))
            store = ShadowRoleResultStore(
                paths.role_store_root,
                model_run_id=run_id,
                run_binding=shadow_runtime._shadow_run_binding(
                    packet,
                    registry,
                    model_run_id=run_id,
                    expected_transport="fixture",
                ),
            )
            bundle = apply_verified_close_stability(
                packet,
                execute_shadow(
                    packet,
                    RecordingFixtureProvider(responses),
                    registry,
                    distinct_valid_closes=0,
                    expected_transport="fixture",
                    role_store=store,
                ),
            )
            shadow_runtime.persist_bundle(
                paths,
                bundle,
                role_store=store,
                completion_status="complete",
            )
            manifest = json.loads(
                store.completion_manifest_path.read_text(
                    encoding="utf-8"
                )
            )
            manifest["artifacts"]["decision_json"]["sha256"] = "0" * 64
            store.completion_manifest_path.chmod(0o600)
            store.completion_manifest_path.write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            store.completion_manifest_path.chmod(0o400)
            paths.decision_json.unlink()
            with self.assertRaises(CachedBundleIntegrityError):
                _cached(
                    paths,
                    run_id,
                    packet=packet,
                    registry=registry,
                    expected_transport="fixture",
                    role_store=store,
                )
            self.assertFalse(paths.decision_json.exists())

    def test_candidate_publication_recovers_every_crash_boundary(
        self,
    ) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        run_id = shadow_runtime._run_id(
            packet,
            registry,
            expected_transport="fixture",
        )
        boundaries = (
            "candidate",
            "decision_json",
            "decision_report",
            "state",
            "audit",
            "manifest",
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-completion-crashes-"
        ) as directory:
            for boundary in boundaries:
                with self.subTest(boundary=boundary):
                    paths = output_paths(Path(directory) / boundary)
                    store = ShadowRoleResultStore(
                        paths.role_store_root,
                        model_run_id=run_id,
                        run_binding=shadow_runtime._shadow_run_binding(
                            packet,
                            registry,
                            model_run_id=run_id,
                            expected_transport="fixture",
                        ),
                    )
                    bundle = apply_verified_close_stability(
                        packet,
                        execute_shadow(
                            packet,
                            RecordingFixtureProvider(responses),
                            registry,
                            distinct_valid_closes=0,
                            expected_transport="fixture",
                            role_store=store,
                        ),
                    )
                    old_bundle = copy.deepcopy(bundle)
                    old_bundle["model_run_id"] = "old-run-id"
                    old_bundle["generated_at"] = (
                        "2026-07-24T18:00:00-04:00"
                    )
                    paths.decision_json.parent.mkdir(
                        parents=True,
                        exist_ok=True,
                    )
                    paths.decision_json.write_bytes(
                        shadow_runtime._json_document_bytes(old_bundle)
                    )
                    paths.decision_report.write_text(
                        shadow_runtime._report(old_bundle),
                        encoding="utf-8",
                    )
                    paths.state.write_bytes(
                        shadow_runtime._json_document_bytes(
                            shadow_runtime._state_payload(old_bundle)
                        )
                    )
                    paths.audit_log.write_text(
                        '{"legacy":"preserve-exactly"}\n',
                        encoding="utf-8",
                    )
                    for output in (
                        paths.decision_json,
                        paths.decision_report,
                        paths.state,
                        paths.audit_log,
                    ):
                        output.chmod(0o600)

                    stack = []
                    if boundary == "candidate":
                        stack.append(
                            mock.patch.object(
                                shadow_runtime,
                                "_publish_completion_candidate",
                                side_effect=RuntimeError(
                                    "crash after candidate"
                                ),
                            )
                        )
                    elif boundary in {
                        "decision_json",
                        "decision_report",
                        "state",
                    }:
                        original_output = (
                            shadow_runtime._write_or_validate_output
                        )

                        def crash_after_output(
                            *args: object,
                            **kwargs: object,
                        ) -> None:
                            original_output(*args, **kwargs)
                            target_paths = {
                                "decision_json": paths.decision_json,
                                "decision_report": paths.decision_report,
                                "state": paths.state,
                            }
                            if args[0] == target_paths[boundary]:
                                raise RuntimeError(
                                    f"crash after {boundary}"
                                )

                        stack.append(
                            mock.patch.object(
                                shadow_runtime,
                                "_write_or_validate_output",
                                side_effect=crash_after_output,
                            )
                        )
                    elif boundary == "audit":
                        original_audit = shadow_runtime._write_audit

                        def crash_after_audit(
                            *args: object,
                            **kwargs: object,
                        ) -> dict[str, str]:
                            result = original_audit(*args, **kwargs)
                            raise RuntimeError("crash after audit")

                        stack.append(
                            mock.patch.object(
                                shadow_runtime,
                                "_write_audit",
                                side_effect=crash_after_audit,
                            )
                        )
                    else:
                        original_private = (
                            shadow_runtime._write_or_validate_private_json
                        )

                        def crash_before_manifest(
                            path: Path,
                            payload: dict[str, object],
                        ) -> None:
                            if path == store.completion_manifest_path:
                                raise RuntimeError(
                                    "crash before manifest"
                                )
                            original_private(path, payload)

                        stack.append(
                            mock.patch.object(
                                shadow_runtime,
                                "_write_or_validate_private_json",
                                side_effect=crash_before_manifest,
                            )
                        )
                    with stack[0]:
                        with self.assertRaises(RuntimeError):
                            shadow_runtime.persist_bundle(
                                paths,
                                bundle,
                                role_store=store,
                                completion_status="complete",
                            )
                    self.assertTrue(store.candidate_path.is_file())
                    self.assertFalse(
                        store.completion_manifest_path.exists()
                    )
                    resumed = RecordingFixtureProvider(responses)
                    self.assertTrue(
                        _cached(
                            paths,
                            run_id,
                            packet=packet,
                            registry=registry,
                            expected_transport="fixture",
                            role_store=store,
                        )
                    )
                    self.assertEqual(resumed.calls, [])
                    self.assertTrue(
                        store.completion_manifest_path.is_file()
                    )
                    audit_bytes = paths.audit_log.read_bytes()
                    self.assertTrue(
                        audit_bytes.startswith(
                            b'{"legacy":"preserve-exactly"}\n'
                        )
                    )
                    audit_rows = [
                        json.loads(line)
                        for line in audit_bytes.decode("utf-8").splitlines()
                    ]
                    current_rows = [
                        row
                        for row in audit_rows
                        if row.get("model_run_id") == run_id
                    ]
                    self.assertEqual(len(current_rows), 1)

    def test_same_run_invalid_cache_never_recalls_provider(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        registry = load_registry()
        payload = apply_verified_close_stability(
            packet,
            execute_shadow(
                packet,
                FixtureProvider(responses),
                registry,
                distinct_valid_closes=0,
                expected_transport="fixture",
            ),
        )
        payload["boundaries"]["canonical_effect"] = True
        with tempfile.TemporaryDirectory(
            prefix="phase5r-cache-main-test-"
        ) as directory:
            paths = output_paths(Path(directory))
            paths.decision_json.write_text(
                json.dumps(payload),
                encoding="utf-8",
            )
            paths.decision_json.chmod(0o600)
            with (
                mock.patch.object(
                    shadow_runtime,
                    "load_registry",
                    return_value=registry,
                ),
                mock.patch.object(
                    shadow_runtime,
                    "build_packet",
                    return_value=packet,
                ),
                mock.patch.object(shadow_runtime, "ExclusiveFileLock"),
                mock.patch.object(
                    shadow_runtime,
                    "FixtureProvider",
                    side_effect=AssertionError("provider was recalled"),
                ) as provider_mock,
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "run_phase5r_llm_shadow.py",
                        "--fixture",
                        str(Path(directory) / "unused-fixture.json"),
                        "--output-dir",
                        directory,
                    ],
                ),
            ):
                self.assertEqual(shadow_runtime.main(), 2)
            provider_mock.assert_not_called()

    def test_activation_runtime_hashes_cover_all_live_control_code(
        self,
    ) -> None:
        expected = {
            "phase5r_daily_common.py",
            "phase5r_evidence_freshness.py",
            "phase5r_llm_cost_aware_router.py",
            "phase5r_llm_role_execution_ledger.py",
            "phase5r_llm_shadow_router_gate.py",
            "run_phase5r_llm_shadow_scheduler.py",
            "phase5r_llm_activation_receipt.py",
            "enable_phase5r_llm_live_shadow.py",
            "run_phase5r_llm_provider_replay_evaluation.py",
            "phase5r_llm_citation_reviews.py",
            "verify_phase5r_llm_shadow_boundary.py",
            "phase5r_sec_acceptance.py",
            "refresh_phase5r_sec_filing_artifacts.py",
            "run_phase5r_daily_refresh.py",
            "run_phase5r_daily_decision_pipeline.py",
            "run_phase5r_daily_refresh_scheduler.py",
            "run_phase5r_daily_scheduler.py",
            "send_phase5r_daily_email.py",
        }
        receipt_names = {path.name for path in RUNTIME_CODE_PATHS}
        replay_names = {
            path.name for path in RUNTIME_EVALUATION_CODE_PATHS
        }
        self.assertTrue(expected.issubset(receipt_names))
        self.assertTrue(
            set(CANONICAL_RUNTIME_FILES).issubset(receipt_names)
        )
        self.assertEqual(receipt_names, replay_names)

    def test_canonical_child_shadow_artifact_read_is_rejected(self) -> None:
        synthetic_child_source = (
            'payload = read_json(ROOT / "04_research" / '
            '"phase5r_llm_shadow_decision.json")'
        )
        markers = canonical_model_reference_markers(
            synthetic_child_source
        )
        self.assertIn("phase5r_llm", markers)
        self.assertIn(
            "create_phase5r_daily_decision_and_brief.py",
            CANONICAL_RUNTIME_FILES,
        )
        self.assertIn(
            "create_phase5r_c9_exact_action_plan.py",
            CANONICAL_RUNTIME_FILES,
        )

    def test_provider_failure_remains_retryable_for_scheduler(self) -> None:
        self.assertEqual(
            _outcome_exit_code(
                {
                    "outcome": "abstain_provider_or_contract_failure",
                    "failure_retryable": True,
                }
            ),
            2,
        )
        self.assertEqual(
            _outcome_exit_code(
                {
                    "outcome": "abstain_provider_or_contract_failure",
                    "failure_retryable": False,
                }
            ),
            0,
        )
        for completed_outcome in (
            "validated",
            "abstain_validation_failed",
        ):
            with self.subTest(completed_outcome=completed_outcome):
                self.assertEqual(
                    _outcome_exit_code({"outcome": completed_outcome}),
                    0,
                )

    def test_static_model_layer_has_no_email_broker_order_or_c7_calls(self) -> None:
        prohibited_import_tokens = (
            "smtplib",
            "imaplib",
            "alpaca",
            "ib_insync",
            "robin_stocks",
            "ccxt",
        )
        prohibited_calls = {
            "sendmail",
            "send_message",
            "place_order",
            "submit_order",
            "create_order",
            "get_account",
            "get_accounts",
            "execute_trade",
        }
        violations: list[str] = []
        for path in SCAN_FILES:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("run_phase5r_c7_weekly_conviction_pipeline", source)
            self.assertNotIn("run_phase5r_daily_refresh.py", source)
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(token in alias.name.lower() for token in prohibited_import_tokens):
                            violations.append(f"{path.name}:import:{alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if any(token in module.lower() for token in prohibited_import_tokens):
                        violations.append(f"{path.name}:from:{module}")
                elif isinstance(node, ast.Call):
                    name = (
                        node.func.attr
                        if isinstance(node.func, ast.Attribute)
                        else node.func.id
                        if isinstance(node.func, ast.Name)
                        else ""
                    )
                    if name in prohibited_calls:
                        violations.append(f"{path.name}:call:{name}")
        self.assertEqual(violations, [])

    def test_offline_evaluation_does_not_touch_operational_state(self) -> None:
        before = {str(path): digest_or_absent(path) for path in SENTINELS}
        smtp_before = smtp_stat()
        original_open = Path.open

        def guarded_open(path: Path, *args: object, **kwargs: object):
            if path.expanduser().resolve() == EMAIL_CONFIG_PATH.expanduser().resolve():
                raise AssertionError("SMTP configuration was opened")
            return original_open(path, *args, **kwargs)

        with tempfile.TemporaryDirectory(prefix="phase5r-eval-test-") as directory:
            with (
                mock.patch.object(Path, "open", guarded_open),
                mock.patch(
                    "phase5r_llm_provider.subprocess.run",
                    side_effect=AssertionError("Codex/process invoked"),
                ) as process_mock,
                mock.patch.object(
                    socket,
                    "create_connection",
                    side_effect=AssertionError("network invoked"),
                ) as network_mock,
                mock.patch.object(
                    urllib.request,
                    "urlopen",
                    side_effect=AssertionError("HTTP invoked"),
                ) as urlopen_mock,
                mock.patch.object(
                    smtplib,
                    "SMTP",
                    side_effect=AssertionError("email invoked"),
                ) as smtp_mock,
            ):
                report = evaluate_manifest()
                write_report(Path(directory), report)
            process_mock.assert_not_called()
            network_mock.assert_not_called()
            urlopen_mock.assert_not_called()
            smtp_mock.assert_not_called()
            self.assertEqual(
                {path.name for path in Path(directory).iterdir()},
                {
                    "phase5r_llm_evaluation_report.json",
                    "phase5r_llm_evaluation_report.md",
                },
            )
        after = {str(path): digest_or_absent(path) for path in SENTINELS}
        self.assertEqual(before, after)
        self.assertEqual(smtp_before, smtp_stat())

    def test_output_path_rejects_project_and_sensitive_targets(self) -> None:
        with self.assertRaisesRegex(ContractError, "outside the project"):
            _safe_output_dir(PROJECT_ROOT / "00_project_control")
        with self.assertRaises(ContractError):
            _safe_output_dir(Path("/tmp/phase5r-smtp-canary"))
        with self.assertRaisesRegex(ContractError, "outside the project"):
            output_paths(PROJECT_ROOT / "04_research")
        with self.assertRaisesRegex(ContractError, "sensitive path"):
            output_paths(Path("/tmp/phase5r-email_delivery-canary"))

    def test_sensitive_packet_canary_is_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        packet["entities"][0]["thesis"] = "SMTP_CANARY_DO_NOT_LEAK"
        with self.assertRaisesRegex(ContractError, "sensitive/local marker"):
            validate_packet(rehash(packet))

    def test_audit_append_refuses_symlink_target(self) -> None:
        bundle = {
            "generated_at": "2026-07-25T18:00:00-04:00",
            "model_run_id": "canary-run",
            "packet_id": "canary-packet",
            "decision_fingerprint": "canary-decision",
            "outcome": "validated",
            "adjudication": {
                "effective_classification": "hold_existing",
                "validation_passed": True,
            },
            "provider_metadata": [],
        }
        with tempfile.TemporaryDirectory(prefix="phase5r-audit-link-test-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.txt"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            link = root / "phase5r_llm_decision_audit.jsonl"
            link.symlink_to(canary)
            before = canary.read_bytes()
            with self.assertRaises(CachedBundleIntegrityError):
                _write_audit(link, bundle)
            self.assertEqual(canary.read_bytes(), before)

    def test_live_runner_exposes_no_close_count_override(self) -> None:
        source = (SCRIPT_DIR / "run_phase5r_llm_shadow.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--distinct-valid-closes", source)
        self.assertIn("verify_active_activation_receipt", source)
        self.assertIn(
            "live shadow activation receipt is missing or stale",
            source,
        )

    def test_shadow_output_lock_refuses_symlink(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-lock-link-test-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.lock"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            link = root / "phase5r_llm_shadow.lock"
            link.symlink_to(canary)
            with self.assertRaises(OSError):
                with ShadowOutputLock(link):
                    pass
            self.assertEqual(canary.read_text(encoding="utf-8"), "UNCHANGED\n")

    def test_scheduler_revalidates_runtime_boundary(self) -> None:
        active = {
            "current_workflow": "daily_decision",
            "active_pipeline": "phase5r_daily",
            "email_delivery_allowed_from": "phase5r_daily_only",
            "broker_connection_allowed": "no",
            "order_code_allowed": "no",
            "manual_execution_only": "yes",
        }
        inhibit = {"active": False, "allowed_pipeline": "phase5r_daily"}
        registry = load_registry()
        validate_runtime_boundary(active, inhibit, registry)
        active["active_pipeline"] = "phase5r_c7"
        with self.assertRaisesRegex(RuntimeError, "active.active_pipeline"):
            validate_runtime_boundary(active, inhibit, registry)

    def test_scheduler_skips_full_receipt_scan_before_time(self) -> None:
        active = {
            "current_workflow": "daily_decision",
            "active_pipeline": "phase5r_daily",
            "email_delivery_allowed_from": "phase5r_daily_only",
            "broker_connection_allowed": "no",
            "order_code_allowed": "no",
            "manual_execution_only": "yes",
            "operational_from": "2026-01-01",
        }
        inhibit = {"active": False, "allowed_pipeline": "phase5r_daily"}
        registry = copy.deepcopy(load_registry())
        registry["mode"] = "shadow"
        registry["live_shadow_enabled"] = True
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
                return_value=registry,
            ),
            mock.patch.object(
                shadow_scheduler,
                "now_et",
                return_value=datetime.fromisoformat(
                    "2026-07-24T17:59:00-04:00"
                ),
            ),
            mock.patch.object(
                shadow_scheduler,
                "verify_active_activation_receipt",
                side_effect=AssertionError(
                    "full receipt scan reached before shadow time"
                ),
            ) as receipt_mock,
            mock.patch.object(
                shadow_scheduler.subprocess,
                "run",
                side_effect=AssertionError("provider runner invoked"),
            ) as process_mock,
            mock.patch.object(
                shadow_scheduler.sys,
                "argv",
                ["run_phase5r_llm_shadow_scheduler.py"],
            ),
        ):
            self.assertEqual(shadow_scheduler.main(), 0)
        receipt_mock.assert_not_called()
        process_mock.assert_not_called()

    def test_scheduler_claims_before_launch_and_recovers_unknown_outcome(
        self,
    ) -> None:
        active = {
            "current_workflow": "daily_decision",
            "active_pipeline": "phase5r_daily",
            "email_delivery_allowed_from": "phase5r_daily_only",
            "broker_connection_allowed": "no",
            "order_code_allowed": "no",
            "manual_execution_only": "yes",
            "operational_from": "2026-01-01",
        }
        inhibit = {"active": False, "allowed_pipeline": "phase5r_daily"}
        registry = copy.deepcopy(load_registry())
        registry["mode"] = "shadow"
        registry["live_shadow_enabled"] = True
        current = datetime.fromisoformat(
            "2026-07-24T18:01:00-04:00"
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-scheduler-claim-"
        ) as directory:
            root = Path(directory)
            state_path = root / "scheduler-state.json"
            daily_path = root / "daily-decision.json"
            daily_path.write_text(
                json.dumps({"cycle_date": "2026-07-24"}),
                encoding="utf-8",
            )

            def boundary(
                *args: object,
                verify_activation: bool = True,
                **kwargs: object,
            ) -> str:
                return "verified" if verify_activation else "deferred"

            def crash_after_claim(*args: object, **kwargs: object):
                persisted = json.loads(
                    state_path.read_text(encoding="utf-8")
                )
                date_state = persisted["dates"]["2026-07-24"]
                self.assertEqual(date_state["attempts"], 1)
                self.assertEqual(
                    date_state["attempt_claims"][-1]["status"],
                    "launch_claimed",
                )
                raise RuntimeError("injected scheduler process uncertainty")

            common_patches = (
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
                    return_value=registry,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "now_et",
                    return_value=current,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "validate_runtime_boundary",
                    side_effect=boundary,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "STATE_PATH",
                    state_path,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "DAILY_DECISION_PATH",
                    daily_path,
                ),
                mock.patch.object(
                    shadow_scheduler.sys,
                    "argv",
                    ["run_phase5r_llm_shadow_scheduler.py"],
                ),
            )
            with (
                common_patches[0],
                common_patches[1],
                common_patches[2],
                common_patches[3],
                common_patches[4],
                common_patches[5],
                common_patches[6],
                common_patches[7],
                mock.patch.object(
                    shadow_scheduler.subprocess,
                    "run",
                    side_effect=crash_after_claim,
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "process uncertainty",
                ):
                    shadow_scheduler.main()
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            first_claim = persisted["dates"]["2026-07-24"][
                "attempt_claims"
            ][0]
            self.assertEqual(first_claim["status"], "launch_claimed")

            def second_launch(*args: object, **kwargs: object):
                claimed = json.loads(
                    state_path.read_text(encoding="utf-8")
                )["dates"]["2026-07-24"]
                self.assertEqual(claimed["attempts"], 2)
                self.assertEqual(
                    [row["status"] for row in claimed["attempt_claims"]],
                    ["outcome_unknown", "launch_claimed"],
                )
                return shadow_scheduler.subprocess.CompletedProcess(
                    args[0],
                    2,
                    stdout="terminal exact-run recovery",
                )

            # Patch objects cannot be reused after exit, so rebuild them.
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
                    return_value=registry,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "now_et",
                    return_value=current,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "validate_runtime_boundary",
                    side_effect=boundary,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "STATE_PATH",
                    state_path,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "DAILY_DECISION_PATH",
                    daily_path,
                ),
                mock.patch.object(
                    shadow_scheduler.sys,
                    "argv",
                    ["run_phase5r_llm_shadow_scheduler.py"],
                ),
                mock.patch.object(
                    shadow_scheduler.subprocess,
                    "run",
                    side_effect=second_launch,
                ) as second_process,
            ):
                self.assertEqual(shadow_scheduler.main(), 2)
            second_process.assert_called_once()
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [
                    row["status"]
                    for row in persisted["dates"]["2026-07-24"][
                        "attempt_claims"
                    ]
                ],
                ["outcome_unknown", "completed"],
            )

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
                    return_value=registry,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "now_et",
                    return_value=current,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "validate_runtime_boundary",
                    side_effect=boundary,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "STATE_PATH",
                    state_path,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "DAILY_DECISION_PATH",
                    daily_path,
                ),
                mock.patch.object(
                    shadow_scheduler.sys,
                    "argv",
                    ["run_phase5r_llm_shadow_scheduler.py"],
                ),
                mock.patch.object(
                    shadow_scheduler.subprocess,
                    "run",
                    side_effect=AssertionError("third launch occurred"),
                ) as third_process,
            ):
                self.assertEqual(shadow_scheduler.main(), 0)
            third_process.assert_not_called()

    def test_scheduler_finalizes_second_unknown_claim_before_cap_exit(
        self,
    ) -> None:
        active = {
            "current_workflow": "daily_decision",
            "active_pipeline": "phase5r_daily",
            "email_delivery_allowed_from": "phase5r_daily_only",
            "broker_connection_allowed": "no",
            "order_code_allowed": "no",
            "manual_execution_only": "yes",
            "operational_from": "2026-01-01",
        }
        inhibit = {"active": False, "allowed_pipeline": "phase5r_daily"}
        registry = copy.deepcopy(load_registry())
        registry["mode"] = "shadow"
        registry["live_shadow_enabled"] = True
        current = datetime.fromisoformat(
            "2026-07-24T18:01:00-04:00"
        )
        with tempfile.TemporaryDirectory(
            prefix="phase5r-scheduler-cap-recovery-"
        ) as directory:
            root = Path(directory)
            state_path = root / "scheduler-state.json"
            daily_path = root / "daily-decision.json"
            daily_path.write_text(
                json.dumps({"cycle_date": "2026-07-24"}),
                encoding="utf-8",
            )
            state_path.write_text(
                json.dumps(
                    {
                        "schema_version": (
                            shadow_scheduler
                            .SCHEDULER_STATE_SCHEMA_VERSION
                        ),
                        "dates": {
                            "2026-07-24": {
                                "attempts": 2,
                                "attempt_claims": [
                                    {
                                        "attempt_number": 1,
                                        "status": "completed",
                                    },
                                    {
                                        "attempt_number": 2,
                                        "status": "launch_claimed",
                                    },
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            boundary_calls: list[bool] = []

            def boundary(
                *args: object,
                verify_activation: bool = True,
                **kwargs: object,
            ) -> str:
                boundary_calls.append(verify_activation)
                return "verified" if verify_activation else "deferred"

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
                    return_value=registry,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "now_et",
                    return_value=current,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "validate_runtime_boundary",
                    side_effect=boundary,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "STATE_PATH",
                    state_path,
                ),
                mock.patch.object(
                    shadow_scheduler,
                    "DAILY_DECISION_PATH",
                    daily_path,
                ),
                mock.patch.object(
                    shadow_scheduler.sys,
                    "argv",
                    ["run_phase5r_llm_shadow_scheduler.py"],
                ),
                mock.patch.object(
                    shadow_scheduler.subprocess,
                    "run",
                    side_effect=AssertionError(
                        "provider relaunched after second unknown claim"
                    ),
                ) as process_mock,
            ):
                self.assertEqual(shadow_scheduler.main(), 0)
            process_mock.assert_not_called()
            self.assertEqual(boundary_calls, [False])
            persisted = json.loads(
                state_path.read_text(encoding="utf-8")
            )
            date_state = persisted["dates"]["2026-07-24"]
            self.assertEqual(date_state["attempts"], 2)
            self.assertEqual(
                date_state["attempt_claims"][1]["status"],
                "outcome_unknown",
            )
            self.assertIn(
                "recovered_at",
                date_state["attempt_claims"][1],
            )
            self.assertIn("last_unknown_outcome_at", date_state)

    def test_installer_preflights_before_bootstrap(self) -> None:
        source = (
            PROJECT_ROOT
            / "07_automation"
            / "scheduler"
            / "install_phase5r_llm_shadow_scheduler.sh"
        ).read_text(encoding="utf-8")
        self.assertLess(
            source.index("run_phase5r_llm_shadow_scheduler.py\" --safe-check"),
            source.index("/bin/launchctl bootstrap"),
        )
        self.assertLess(
            source.index("phase5r_llm_activation_receipt.py"),
            source.index("/bin/launchctl bootstrap"),
        )
        self.assertIn("cleanup_incomplete_install", source)

    def test_live_activation_is_blocked_until_replay_corpus_gate(self) -> None:
        result = provider_replay_status()
        self.assertIsNot(result.get("passed"), True)
        self.assertLess(
            int(result.get("packet_count", 0) or 0),
            MINIMUM_REAL_PACKETS,
        )
        self.assertLess(
            int(result.get("material_transition_count", 0) or 0),
            50,
        )


if __name__ == "__main__":
    unittest.main()
