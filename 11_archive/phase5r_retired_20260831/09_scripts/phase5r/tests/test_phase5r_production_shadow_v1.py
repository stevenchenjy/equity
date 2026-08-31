from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import phase5r_production_shadow_email_gate as email_gate
import phase5r_production_shadow_v1 as shadow
from phase5r_llm_provider import ProviderError, ProviderResult
from phase5r_daily_common import canonical_sha256
from phase5r_evidence_freshness import build_evidence_freshness_receipt
import run_phase5r_daily_refresh as daily_refresh
import run_phase5r_daily_refresh_scheduler as refresh_scheduler
import run_phase5r_production_shadow as shadow_runner
import verify_phase5r_production_shadow_readiness as readiness_verifier


TRADING_DAY = "2026-08-04"


def _source() -> tuple[dict[str, object], str]:
    excerpt = "Acme reported revenue from its cloud segment."
    return (
        {
            "source_id": "sec-aaa-1",
            "ticker": "AAA",
            "excerpt_text": excerpt,
            "content_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "authority": "primary_official",
            "source_type": "sec_filing_text_chunk",
            "accepted_at": "2026-08-04T20:00:00+00:00",
            "locator": {"char_start": 0},
        },
        excerpt,
    )


def _packet() -> tuple[dict[str, object], bytes]:
    source, _ = _source()
    freshness = build_evidence_freshness_receipt(
        ticker="AAA",
        as_of_utc="2026-08-04T20:20:00Z",
        sec_scan={
            "status_artifact_sha256": "1" * 64,
            "completed_through_utc": "2026-08-04T20:00:00Z",
            "ticker_scanned": True,
            "complete": True,
        },
        market={
            "observed_at_utc": "2026-08-04T20:15:00Z",
            "market_session_date": TRADING_DAY,
            "expected_market_session_date": TRADING_DAY,
            "complete_close": True,
        },
        valuation={
            "valuation_receipt_sha256": "",
            "receipt_as_of_utc": "",
            "market_input_at_utc": "",
            "market_session_date": "",
            "expected_market_session_date": TRADING_DAY,
            "scenario_refreshed_at_utc": "",
            "complete": False,
        },
        durable_sec_source_ids=[],
    )
    packet: dict[str, object] = {
        "packet_id": "a" * 64,
        "cycle_date": TRADING_DAY,
        "as_of_et": "2026-08-04T16:20:00-04:00",
        "decision_fingerprint": "b" * 64,
        "entities": [{"ticker": "AAA", "role": "held"}],
        "source_catalog": [source],
        "gates": {
            "allowed_classifications_by_ticker": {
                "AAA": ["hold_existing", "abstain"]
            },
            "valuation_action_grade_tickers": [],
        },
        "evidence_freshness": [freshness],
    }
    raw = (json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    return packet, raw


def _payload(*, literal_anchor: bool = True) -> dict[str, object]:
    anchor = "Acme reported revenue" if literal_anchor else "not in the excerpt"
    return {
        "agreement_status": "agree",
        "valuation_conclusion": "abstain",
        "summary_claim_ids": ["claim-a"],
        "claims": [
            {
                "claim_id": "claim-a",
                "ticker": "AAA",
                "claim": "Acme reported revenue.",
                "materiality": "low",
                "source_ids": ["sec-aaa-1"],
            }
        ],
        "citation_assessments": [
            {
                "claim_id": "claim-a",
                "semantic_support": "supported",
                "citation_accuracy": "accurate",
                "period_unit_valid": True,
                "notes": "literal_anchor_and_source_match",
            }
        ],
        "citation_anchors": [
            {
                "claim_id": "claim-a",
                "source_id": "sec-aaa-1",
                "anchor_text": anchor,
            }
        ],
        "positive_findings": [
            {
                "finding": "Acme reported revenue.",
                "source_ids": ["sec-aaa-1"],
            }
        ],
        "negative_findings": [],
        "missing_or_contradictory_evidence": ["valuation_evidence_absent"],
        "contradictory_claim_pairs": [],
        "overclaim_findings": [],
        "confidence_calibration": {
            "confidence_pct": 40,
            "calibration": "low",
            "claim_ids": ["claim-a"],
        },
        "proposed_classification_adjustment": {
            "ticker": "AAA",
            "classification": "hold_existing",
            "claim_ids": ["claim-a"],
        },
        "holding_period_considerations": ["maintain_long_term_research_horizon"],
        "next_review_conditions": ["new_official_filing"],
    }


class RecordingProvider:
    def __init__(
        self, payload: dict[str, object], *, input_sha256_override: str | None = None
    ) -> None:
        self.payload = payload
        self.input_sha256_override = input_sha256_override
        self.calls: list[dict[str, object]] = []

    def generate(self, **kwargs: object) -> ProviderResult:
        self.calls.append(kwargs)
        return ProviderResult(
            payload=self.payload,
            metadata={
                "transport": "openai_responses_api",
                "model": shadow.MODEL,
                "resolved_model": shadow.MODEL,
                "reasoning_effort": shadow.REASONING_EFFORT,
                "tools_enabled": False,
                "store": False,
                "latency_ms": 1,
                "input_sha256": self.input_sha256_override
                or canonical_sha256(kwargs["input_payload"]),
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 100,
                    "cached_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )


class ProductionShadowTests(unittest.TestCase):
    def _runtime(self, root: Path):
        packet, raw = _packet()
        approved = root / "approved_packet.json"
        decision_state = root / "decision_state.json"
        refresh_state = root / "refresh_state.json"
        approved.write_bytes(raw)
        decision_state.write_text("{}\n", encoding="utf-8")
        refresh_state.write_text("{}\n", encoding="utf-8")
        state_sha256 = hashlib.sha256(b"{}\n").hexdigest()
        output = root / "output"
        control = root / "control"
        return (
            packet,
            raw,
            [
                patch.object(shadow, "PRODUCTION_ROOT", output),
                patch.object(shadow, "HANDOFF_ROOT", output / "handoffs"),
                patch.object(shadow, "VALIDATION_ROOT", output / "validations"),
                patch.object(shadow, "REPORT_ROOT", output / "reports"),
                patch.object(shadow, "LEDGER_ROOT", output / "ledger"),
                patch.object(shadow, "CONTROL_ROOT", control),
                patch.object(shadow, "OWNER_APPROVAL_ROOT", control / "approvals"),
                patch.object(shadow, "RUNTIME_AUTHORIZATION_ROOT", control / "runtime"),
                patch.object(shadow, "LOCK_PATH", control / "lock"),
                patch.object(shadow, "LEDGER_PATH", output / "ledger" / "ledger.jsonl"),
                patch.object(shadow, "OBSERVATION_STATE_PATH", control / "observation.json"),
                patch.object(shadow, "APPROVED_PACKET_PATH", approved),
                patch.object(shadow, "DAILY_DECISION_STATE_PATH", decision_state),
                patch.object(shadow, "DAILY_REFRESH_STATE_PATH", refresh_state),
                patch.object(shadow, "cycle_date", return_value=TRADING_DAY),
                patch.object(shadow, "iso_now", return_value="2026-08-04T17:00:00-04:00"),
                patch.object(shadow, "_load_current_approved_packet", return_value=(packet, raw)),
                patch.object(shadow, "_current_decision_context", return_value=({}, {})),
                patch.object(
                    shadow,
                    "_current_decision_snapshot_context",
                    return_value=({}, {}, state_sha256, state_sha256),
                ),
                patch.object(
                    shadow,
                    "_validate_freshness",
                    return_value="hold_no_new_position",
                ),
            ],
            output,
            control,
        )

    def test_shadow_schema_is_closed_and_required_names_are_unique(self) -> None:
        schema = shadow.shadow_output_schema()
        required = schema["required"]
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(len(required), len(set(required)))
        self.assertEqual(set(required), set(schema["properties"]))
        self.assertIn("valuation_conclusion", required)

    def test_missing_valuation_is_explicitly_nonactionable_but_not_a_shadow_freshness_failure(self) -> None:
        packet, _ = _packet()
        packet["gates"].update(  # type: ignore[index]
            {
                "market_data_current": True,
                "sec_held_coverage_complete": True,
                "fundamental_held_coverage_complete": True,
                "filing_artifact_provenance_complete": True,
                "sec_acceptance_provenance_complete": True,
                "account_state_consistent": True,
                "point_in_time_safe": True,
                "prompt_injection_text_detected": False,
                "verified_close_session": TRADING_DAY,
            }
        )
        decision_code = shadow._validate_freshness(
            packet=packet,
            refresh={
                "outcome": "passed",
                "decision_created": True,
                "completed_at": "2026-08-04T16:20:01-04:00",
            },
            decision_state={
                "cycle_date": TRADING_DAY,
                "decision_code": "hold_no_new_position",
            },
            trading_day=TRADING_DAY,
        )
        scope = shadow._shadow_valuation_scope(packet)
        self.assertEqual(decision_code, "hold_no_new_position")
        self.assertEqual(scope["valuation_status"], "unavailable")
        self.assertFalse(scope["valuation_actionable"])
        self.assertEqual(scope["valuation_conclusion_required"], "abstain")

    def test_unavailable_valuation_requires_disclosure_and_abstention(self) -> None:
        packet, _ = _packet()
        source = packet["source_catalog"][0]  # type: ignore[index]
        projection, _, _ = shadow._make_projection(
            packet=packet,
            decision_code="hold_no_new_position",
            selected_sources=[source],
            omitted_tickers=[],
        )
        missing = _payload()
        missing["missing_or_contradictory_evidence"] = []
        with self.assertRaisesRegex(
            shadow.ProductionShadowError,
            "unavailable valuation must be disclosed",
        ):
            shadow._validate_model_payload(missing, projection=projection)
        prohibited = _payload()
        prohibited["claims"][0]["claim"] = "Acme has a fair value above its price."
        with self.assertRaisesRegex(
            shadow.ProductionShadowError,
            "prohibited valuation conclusion",
        ):
            shadow._validate_model_payload(prohibited, projection=projection)

    def test_one_injected_call_writes_only_noncanonical_bound_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, output, control = self._runtime(root)
            provider = RecordingProvider(_payload())
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)
                state = json.loads((control / "observation.json").read_text(encoding="utf-8"))
                ledger = (output / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                report = json.loads(
                    next((output / "reports").glob("*/production_shadow_result.json")).read_text(
                        encoding="utf-8"
                    )
                )
                rendered = next(
                    (output / "reports").glob("*/production_shadow_daily_report.md")
                ).read_text(encoding="utf-8")

        self.assertEqual(result["outcome"], "completed")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0]["model"], shadow.MODEL)
        self.assertEqual(provider.calls[0]["reasoning_effort"], "medium")
        self.assertEqual(provider.calls[0]["role"], "analyst")
        self.assertFalse(result["canonical_effect"])
        self.assertFalse(report["canonical_effect"])
        self.assertEqual(report["validation"]["future_v2_citation_binding_status"], "completed")
        self.assertEqual(report["validation"]["assertion_span_procedure_status"], "completed")
        self.assertIn("## Summary", rendered)
        self.assertIn("## Claims, citations, and literal anchors", rendered)
        self.assertIn("## Overclaim findings", rendered)
        self.assertIn("## Confidence calibration", rendered)
        self.assertIn("`sec-aaa-1`", rendered)
        self.assertEqual(len(ledger), 2)
        self.assertTrue(state["active"])
        self.assertFalse(state["email_delivery_permitted"])

    def test_same_trading_day_never_retries_after_completed_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, output, _ = self._runtime(root)
            provider = RecordingProvider(_payload())
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                first = shadow.run_production_shadow(provider_factory=lambda: provider)
                second = shadow.run_production_shadow(provider_factory=lambda: provider)
                handoff_count = len(list((output / "handoffs").iterdir()))

        self.assertEqual(first["outcome"], "completed")
        self.assertEqual(second["outcome"], "blocked")
        self.assertEqual(second["reason"], "provider_attempt_already_reserved_today")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(handoff_count, 1)

    def test_post_construction_tampering_prevents_the_only_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, output, control = self._runtime(root)
            provider = RecordingProvider(_payload())
            from contextlib import ExitStack

            def tampering_factory() -> RecordingProvider:
                authorization = next((control / "runtime").glob("*.json"))
                value = json.loads(authorization.read_text(encoding="utf-8"))
                value["monthly_cost_cap_usd"] = "999.000000"
                authorization.write_text(
                    json.dumps(value, sort_keys=True) + "\n", encoding="utf-8"
                )
                return provider

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=tampering_factory)
                ledger_rows = [
                    json.loads(line)
                    for line in (output / "ledger" / "ledger.jsonl").read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertFalse(result["provider_invoked"])
        self.assertEqual(provider.calls, [])
        self.assertEqual(
            [row["event_type"] for row in ledger_rows],
            ["reservation", "terminal_failure"],
        )

    def test_malformed_literal_anchor_is_terminal_and_reservation_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, output, control = self._runtime(root)
            provider = RecordingProvider(_payload(literal_anchor=False))
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)
                ledger_rows = [json.loads(line) for line in (output / "ledger" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()]
                state = json.loads((control / "observation.json").read_text(encoding="utf-8"))
                exposure = shadow.current_cost_exposure()

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual([row["event_type"] for row in ledger_rows], ["reservation", "terminal_failure"])
        self.assertTrue(state["active"])
        self.assertFalse(state["email_delivery_permitted"])
        self.assertEqual(ledger_rows[-1]["latency_ms"], 1)
        self.assertEqual(ledger_rows[-1]["metered_cost_status"], "known")
        self.assertEqual(ledger_rows[-1]["validation_status"], "terminal_failure")
        self.assertEqual(ledger_rows[-1]["citation_quality"], "not_accepted")
        self.assertIsNone(ledger_rows[-1]["llm_challenge"])
        self.assertEqual(exposure["daily_metered_usd"], "0.001400")

    def test_unbound_human_finding_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            payload = _payload()
            payload["positive_findings"] = [
                {"finding": "An uncited extra assertion.", "source_ids": ["sec-aaa-1"]}
            ]
            provider = RecordingProvider(payload)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])
        self.assertEqual(len(provider.calls), 1)

    def test_sensitive_model_output_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            payload = _payload()
            payload["claims"][0]["claim"] = "Contact analyst@example.com for details."
            provider = RecordingProvider(payload)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])
        self.assertEqual(len(provider.calls), 1)

    def test_generic_key_shaped_model_output_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            payload = _payload()
            payload["claims"][0]["claim"] = "Acme reported sk-" + "a" * 16
            provider = RecordingProvider(payload)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])
        self.assertEqual(len(provider.calls), 1)

    def test_sensitive_selected_excerpt_blocks_before_provider_factory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, _, patches, _, _ = self._runtime(root)
            source = packet["source_catalog"][0]
            sensitive_excerpt = "sk-" + "a" * 16
            source["excerpt_text"] = sensitive_excerpt
            source["content_sha256"] = hashlib.sha256(
                sensitive_excerpt.encode("utf-8")
            ).hexdigest()
            raw = (
                json.dumps(packet, ensure_ascii=False, sort_keys=True) + "\n"
            ).encode("utf-8")
            factory_called = False

            def factory():
                nonlocal factory_called
                factory_called = True
                raise AssertionError("provider factory must not run")

            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                stack.enter_context(
                    patch.object(
                        shadow, "_load_current_approved_packet", return_value=(packet, raw)
                    )
                )
                result = shadow.run_production_shadow(provider_factory=factory)

        self.assertEqual(result["outcome"], "blocked")
        self.assertEqual(result["reason"], "approved_evidence_packet_privacy_failed")
        self.assertFalse(factory_called)

    def test_model_input_privacy_scans_omitted_ticker_and_mapping_keys(self) -> None:
        projection = {
            "deterministic_decision_code": "hold_existing",
            "decision_fingerprint": "b" * 64,
            "allowed_classifications_by_ticker": {"AAA": ["hold_existing"]},
            "valuation_scope": {
                "valuation_status": "unavailable",
                "valuation_actionable": False,
                "valuation_conclusion_required": "abstain",
            },
            "source_selection": {"selected_source_ids": ["sec-aaa-1"]},
            "source_catalog": [
                {
                    "source_id": "sec-aaa-1",
                    "ticker": "AAA",
                    "content_sha256": "a" * 64,
                    "excerpt_text": "Acme reported revenue.",
                }
            ],
        }
        with self.assertRaisesRegex(
            shadow.ProductionShadowError, "provider_input_privacy_failed"
        ):
            shadow._model_input(
                projection=projection, omitted_tickers=["sk-" + "a" * 16]
            )

    def test_provider_input_receipt_mismatch_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, output, _ = self._runtime(root)
            provider = RecordingProvider(_payload(), input_sha256_override="0" * 64)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)
                ledger_rows = [
                    json.loads(line)
                    for line in (output / "ledger" / "ledger.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])
        self.assertEqual(result["reason"], "production_shadow_internal_validation_failed")
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(ledger_rows[-1]["metered_cost_status"], "known")

    def test_provider_exception_text_is_not_written_to_failure_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, output, _ = self._runtime(root)
            synthetic_sensitive_text = "sk-" + "a" * 16
            from contextlib import ExitStack

            def factory():
                raise ProviderError(
                    synthetic_sensitive_text, failure_code="api_authentication"
                )

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=factory)
                receipt = next((output / "reports").glob("*/production_shadow_result.json"))
                report_text = receipt.read_text(encoding="utf-8")

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertEqual(result["reason"], "api_authentication")
        self.assertNotIn(synthetic_sensitive_text, report_text)

    def test_scheduler_never_reflects_raw_shadow_child_output(self) -> None:
        raw = "Traceback: sk-" + "a" * 16
        process = refresh_scheduler.subprocess.CompletedProcess(
            ["shadow"], 1, stdout=raw, stderr="ignored"
        )
        self.assertEqual(
            refresh_scheduler._safe_shadow_child_status(process),
            "unparseable_or_oversize_child_result",
        )

    def test_refresh_children_are_not_captured_or_persisted_as_summaries(self) -> None:
        completed = daily_refresh.subprocess.CompletedProcess(["child"], 1)
        with patch.object(daily_refresh.subprocess, "run", return_value=completed) as run:
            result = daily_refresh.run_step("fixture", "fixture.py", False)
        self.assertEqual(result["result_code"], "child_nonzero_exit")
        self.assertNotIn("safe_summary", result)
        _, kwargs = run.call_args
        self.assertEqual(kwargs["stdout"], daily_refresh.subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], daily_refresh.subprocess.DEVNULL)

    def test_exact_runtime_auth_presence_probe_is_mute_and_boolean_only(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch.dict(
            os.environ,
            {
                refresh_scheduler.AUTH_PRESENCE_PROBE_ENV: "1",
                "OPENAI_API_KEY": "test-presence-only-not-a-real-key",
            },
            clear=True,
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                present = refresh_scheduler.main()
        with patch.dict(
            os.environ,
            {refresh_scheduler.AUTH_PRESENCE_PROBE_ENV: "1"},
            clear=True,
        ):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                absent = refresh_scheduler.main()
        self.assertEqual(present, refresh_scheduler.AUTH_PRESENCE_PRESENT_EXIT)
        self.assertEqual(absent, refresh_scheduler.AUTH_PRESENCE_ABSENT_EXIT)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_degraded_refresh_state_cannot_start_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refresh_state = root / "refresh.json"
            scheduler_state = root / "scheduler.json"
            refresh_state.write_text(
                json.dumps(
                    {
                        "schema_version": "phase5r_daily_refresh_state_v1",
                        "started_at": "2026-08-04T16:15:01-04:00",
                        "completed_at": "2026-08-04T16:15:02-04:00",
                        "outcome": "degraded_decision_created",
                        "decision_created": True,
                        "hard_failures": ["portfolio_outputs"],
                        "soft_failures": [],
                    }
                ),
                encoding="utf-8",
            )
            scheduler_state.write_text(
                json.dumps(
                    {"schema_version": "phase5r_daily_scheduler_state_v1", "dates": {}}
                ),
                encoding="utf-8",
            )
            refresh = refresh_scheduler.subprocess.CompletedProcess(
                ["refresh"], 0
            )
            with (
                patch.object(refresh_scheduler, "DAILY_REFRESH_STATE_PATH", refresh_state),
                patch.object(refresh_scheduler, "DAILY_SCHEDULER_STATE_PATH", scheduler_state),
                patch.object(
                    refresh_scheduler,
                    "load_active_state",
                    return_value={"operational_from": "2026-01-01"},
                ),
                patch.object(refresh_scheduler, "load_inhibit", return_value={"active": False}),
                patch.object(refresh_scheduler, "cycle_date", return_value=TRADING_DAY),
                patch.object(
                    refresh_scheduler,
                    "now_et",
                    return_value=refresh_scheduler.datetime.fromisoformat(
                        "2026-08-04T16:16:00-04:00"
                    ),
                ),
                patch.object(
                    refresh_scheduler,
                    "iso_now",
                    side_effect=[
                        "2026-08-04T16:15:00-04:00",
                        "2026-08-04T16:16:00-04:00",
                        "2026-08-04T16:16:01-04:00",
                    ],
                ),
                patch.object(refresh_scheduler.sys, "argv", ["scheduler"]),
                patch.object(refresh_scheduler.subprocess, "run", return_value=refresh) as run,
            ):
                with redirect_stdout(io.StringIO()):
                    result = refresh_scheduler.main()
                gate = refresh_scheduler._refresh_state_allows_shadow(
                    refresh_returncode=0,
                    refresh_started_at="2026-08-04T16:15:00-04:00",
                )

        self.assertEqual(result, 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(gate, "not_started_refresh_state_not_passed")

    def test_current_fully_passed_refresh_state_allows_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            refresh_state = Path(directory) / "refresh.json"
            refresh_state.write_text(
                json.dumps(
                    {
                        "schema_version": "phase5r_daily_refresh_state_v1",
                        "started_at": "2026-08-04T16:15:01-04:00",
                        "completed_at": "2026-08-04T16:15:02-04:00",
                        "outcome": "passed",
                        "decision_created": True,
                        "hard_failures": [],
                        "soft_failures": [],
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(
                refresh_scheduler, "DAILY_REFRESH_STATE_PATH", refresh_state
            ):
                gate = refresh_scheduler._refresh_state_allows_shadow(
                    refresh_returncode=0,
                    refresh_started_at="2026-08-04T16:15:00-04:00",
                )

        self.assertEqual(gate, "passed")

    def test_action_language_model_output_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            payload = _payload()
            payload["claims"][0]["claim"] = "Buy AAA now."
            provider = RecordingProvider(payload)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])

    def test_position_modification_language_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            payload = _payload()
            payload["claims"][0]["claim"] = "Add to AAA."
            provider = RecordingProvider(payload)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])

    def test_citation_assessment_failure_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            payload = _payload()
            payload["citation_assessments"][0]["semantic_support"] = "partial"
            provider = RecordingProvider(payload)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])

    def test_classification_outside_ticker_allowlist_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            payload = _payload()
            payload["proposed_classification_adjustment"]["classification"] = "real_trade_candidate"
            provider = RecordingProvider(payload)
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                result = shadow.run_production_shadow(provider_factory=lambda: provider)

        self.assertEqual(result["outcome"], "terminal_failure")
        self.assertTrue(result["provider_invoked"])

    def test_blocked_freshness_never_constructs_provider(self) -> None:
        constructed = False

        def factory():
            nonlocal constructed
            constructed = True
            raise AssertionError("provider should not be constructed")

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(shadow, "LOCK_PATH", Path(directory) / "lock"),
                patch.object(
                    shadow,
                    "_create_frozen_handoff",
                    side_effect=shadow.ProductionShadowBlocked("daily_refresh_not_fully_passed"),
                ),
            ):
                result = shadow.run_production_shadow(provider_factory=factory)

        self.assertEqual(result["outcome"], "blocked")
        self.assertFalse(constructed)

    def test_provider_attempt_capacity_is_advisory_and_blocks_reserved_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, _, _ = self._runtime(root)
            provider = RecordingProvider(_payload())
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                completed = shadow.run_production_shadow(provider_factory=lambda: provider)
                capacity = shadow.provider_attempt_capacity()

        self.assertEqual(completed["outcome"], "completed")
        self.assertFalse(capacity["available"])
        self.assertEqual(capacity["reason"], "provider_attempt_already_reserved_today")

    def test_runner_blocks_missing_sdk_before_core_reservation_path(self) -> None:
        captured = io.StringIO()
        with (
            patch.object(
                shadow_runner,
                "_sdk_runtime_status",
                return_value={
                    "available": False,
                    "version": None,
                    "reason": "openai_sdk_unavailable",
                },
            ),
            patch.object(
                shadow_runner,
                "run_production_shadow",
                side_effect=AssertionError("core should not run"),
            ),
            patch("sys.argv", ["shadow-runner", "--run"]),
            redirect_stdout(captured),
        ):
            exit_code = shadow_runner.main()

        result = json.loads(captured.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["outcome"], "blocked")
        self.assertFalse(result["provider_constructed"])

    def test_readiness_accounts_for_unavailable_reservation_capacity(self) -> None:
        with (
            patch.object(shadow, "check_current_readiness", return_value={"ready": True}),
            patch.object(
                readiness_verifier,
                "_sdk_runtime_status",
                return_value={"available": True, "version": "2.49.0", "reason": None},
            ),
            patch.object(
                shadow,
                "provider_attempt_capacity",
                return_value={"available": False, "reason": "provider_attempt_already_reserved_today"},
            ),
        ):
            result = readiness_verifier.verify_readiness()

        self.assertFalse(result["ready_for_one_provider_attempt"])
        self.assertEqual(
            result["current_readiness_reason"], "provider_attempt_already_reserved_today"
        )

    def test_email_gate_suppresses_only_active_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            ledger = Path(directory) / "ledger.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": email_gate.OBSERVATION_SCHEMA_VERSION,
                        "active": True,
                        "email_delivery_permitted": False,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(email_gate, "OBSERVATION_STATE_PATH", path),
                patch.object(email_gate, "LEDGER_PATH", ledger),
            ):
                self.assertTrue(email_gate.observation_email_suppressed())
            path.write_text(
                json.dumps(
                    {
                        "schema_version": email_gate.OBSERVATION_SCHEMA_VERSION,
                        "active": False,
                        "email_delivery_permitted": True,
                        "completed_review_count": email_gate.TARGET_COMPLETED_REVIEWS,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(email_gate, "OBSERVATION_STATE_PATH", path),
                patch.object(email_gate, "LEDGER_PATH", ledger),
            ):
                self.assertFalse(email_gate.observation_email_suppressed())

    def test_email_gate_fails_closed_for_corrupt_state_or_reserved_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state.json"
            ledger = root / "ledger.jsonl"
            state.write_text("not-json", encoding="utf-8")
            with (
                patch.object(email_gate, "OBSERVATION_STATE_PATH", state),
                patch.object(email_gate, "LEDGER_PATH", ledger),
            ):
                self.assertTrue(email_gate.observation_email_suppressed())

            state.unlink()
            event = {
                "event_type": "reservation",
                "recorded_at_et": "2026-08-04T17:00:00-04:00",
                "run_id": "20260804-170000-aaaaaaaaaaaa",
                "trading_day": TRADING_DAY,
                "reservation_usd": "0.500000",
                "provider_invoked": False,
                "provider_completed": False,
                "canonical_effect": False,
                "human_usefulness_status": "awaiting_human_assessment",
                "schema_version": "phase5r_production_shadow_ledger_event_v1",
                "previous_event_sha256": "",
            }
            event["event_sha256"] = canonical_sha256(event)
            ledger.write_text(json.dumps(event, sort_keys=True) + "\n", encoding="utf-8")
            with (
                patch.object(email_gate, "OBSERVATION_STATE_PATH", state),
                patch.object(email_gate, "LEDGER_PATH", ledger),
            ):
                self.assertTrue(email_gate.observation_email_suppressed())

    def test_human_usefulness_is_appended_once_without_mutating_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, _, patches, output, _ = self._runtime(root)
            provider = RecordingProvider(_payload())
            from contextlib import ExitStack

            with ExitStack() as stack:
                for patcher in patches:
                    stack.enter_context(patcher)
                completed = shadow.run_production_shadow(provider_factory=lambda: provider)
                with self.assertRaises(shadow.ProductionShadowError):
                    shadow.record_human_usefulness(
                        run_id=completed["run_id"],
                        usefulness="useful",
                        assessment_code="not_actionable_for_human_review",
                    )
                assessment = shadow.record_human_usefulness(
                    run_id=completed["run_id"],
                    usefulness="useful",
                    assessment_code="materially_improved_review",
                )
                with self.assertRaises(shadow.ProductionShadowBlocked):
                    shadow.record_human_usefulness(
                        run_id=completed["run_id"],
                        usefulness="useful",
                        assessment_code="materially_improved_review",
                    )
                ledger_rows = [
                    json.loads(line)
                    for line in (output / "ledger" / "ledger.jsonl").read_text(
                        encoding="utf-8"
                    ).splitlines()
                ]

        self.assertEqual(assessment["outcome"], "human_usefulness_recorded")
        self.assertEqual(ledger_rows[-1]["event_type"], "human_assessment")
        self.assertEqual(ledger_rows[-1]["human_usefulness_status"], "useful")

    def test_static_readiness_verifier_has_no_historical_or_execution_boundary_violation(self) -> None:
        result = readiness_verifier.verify_readiness()
        self.assertTrue(result["static_boundary_passed"])
        self.assertFalse(result["provider_constructed"])
        self.assertFalse(result["provider_called"])


if __name__ == "__main__":
    unittest.main()
