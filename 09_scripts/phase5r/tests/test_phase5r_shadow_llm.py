from __future__ import annotations

import copy
import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _support import SCRIPT_DIR  # noqa: F401

from evaluate_phase5r_shadow_llm_incremental_value import (
    aggregate,
    load_automatic_bundle,
)
from phase5r_daily_common import canonical_sha256
from phase5r_shadow_llm_contract import (
    ANALYST_SCHEMA_VERSION,
    CRITIC_SCHEMA_VERSION,
    JUDGE_SCHEMA_VERSION,
    ShadowContractError,
    analyst_schema,
    build_blind_judge_target,
    critic_schema,
    judge_schema,
    load_packet,
    validate_analyst,
    validate_critic,
    validate_judge,
)
from phase5r_shadow_llm_provider import (
    CodexCliProvider,
    ShadowProviderError,
    classify_nonzero_exit,
    cli_reported_token_usage,
)
import run_phase5r_shadow_llm_evaluation as shadow_runner


def fake_packet() -> dict:
    return {
        "schema_version": "phase5r_llm_evidence_packet_v1",
        "packet_id": "a" * 64,
        "as_of_et": "2026-09-02T12:00:00-04:00",
        "cycle_date": "2026-09-01",
        "decision_fingerprint": "b" * 64,
        "entities": [
            {
                "ticker": "IOT",
                "role": "held",
                "thesis": "Enterprise adoption supports durable growth.",
                "holding_horizon": "medium_conviction",
                "invalidation_rule": "Demand weakens materially.",
            }
        ],
        "gates": {"prompt_injection_text_detected": False},
        "fundamental_observations": [],
        "filing_evidence": [],
        "research_context": [],
        "evidence_freshness": [],
        "calculations": [
            {"calculation_id": "calc:IOT:revenue", "ticker": "IOT"}
        ],
        "source_catalog": [
            {
                "source_id": "sec:IOT:quarterly",
                "ticker": "IOT",
                "source_type": "sec_filing_text_chunk",
                "authority": "primary_official",
                "accepted_at": "2026-08-29T12:00:00Z",
                "source_url": "https://www.sec.gov/example",
                "locator": "filing section",
                "content_sha256": "c" * 64,
                "excerpt_text": "Enterprise customer growth accelerated.",
            }
        ],
        "boundaries": {
            "research_only": True,
            "canonical_effect": False,
            "email_eligible": False,
            "automatic_action_allowed": False,
            "broker_connected": False,
            "order_code_available": False,
            "exact_account_dollars_included": False,
        },
    }


def valid_analyst(packet: dict | None = None, *, materiality: str = "high") -> dict:
    packet = packet or fake_packet()
    return {
        "schema_version": ANALYST_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "claims": [
            {
                "claim_id": "iot_growth",
                "ticker": "IOT",
                "category": "fundamental_trend",
                "direction": "positive",
                "materiality": materiality,
                "novelty": "new_evidence",
                "statement": "Enterprise customer growth accelerated.",
                "period": "latest reported quarter",
                "source_ids": ["sec:IOT:quarterly"],
                "calculation_ids": [],
                "uncertainty": "The filing excerpt does not establish durability.",
            }
        ],
        "ticker_reviews": [
            {
                "ticker": "IOT",
                "semantic_state": "strengthened",
                "confidence": "medium",
                "summary": "The filing supports a stronger demand signal.",
                "key_claim_ids": ["iot_growth"],
                "missing_evidence": ["Durability across later periods is unknown."],
            }
        ],
    }


def valid_critic(analyst: dict, packet: dict | None = None) -> dict:
    packet = packet or fake_packet()
    return {
        "schema_version": CRITIC_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "analyst_output_sha256": canonical_sha256(analyst),
        "claim_reviews": [
            {
                "claim_id": "iot_growth",
                "verdict": "supported",
                "reason": "The cited filing excerpt directly supports the scoped statement.",
                "source_ids": ["sec:IOT:quarterly"],
            }
        ],
        "omissions": [],
        "ticker_reviews": [
            {
                "ticker": "IOT",
                "decision": "accept",
                "reason_claim_ids": ["iot_growth"],
                "reason": "The bounded claim is supported by the cited filing.",
            }
        ],
    }


def valid_judge(
    analyst: dict, critic: dict | None, packet: dict | None = None
) -> dict:
    packet = packet or fake_packet()
    target, _ = build_blind_judge_target(analyst, critic)
    return {
        "schema_version": JUDGE_SCHEMA_VERSION,
        "packet_id": packet["packet_id"],
        "candidate_set_sha256": target["candidate_set_sha256"],
        "item_reviews": [
            {
                "blind_item_id": row["blind_item_id"],
                "support": "supported",
                "materiality": "material",
                "baseline_captured": "no",
                "reason": "The primary filing supports a material incremental issue.",
                "source_ids": row["source_ids"],
            }
            for row in target["candidates"]
        ],
        "missed_material_issues": [],
        "overall_confidence": "medium",
    }


class FailingProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, **kwargs):
        del kwargs
        self.calls += 1
        raise ShadowProviderError("simulated", failure_code="provider_error")


class ShadowLlmTests(unittest.TestCase):
    def test_evaluation_scheduler_is_event_driven_and_nonproduction(self) -> None:
        root = SCRIPT_DIR.parents[1]
        scheduler_dir = root / "07_automation" / "scheduler"
        template = scheduler_dir / "com.steven.phase5r.shadoweval.plist.template"
        with template.open("rb") as handle:
            payload = plistlib.load(handle)
        self.assertEqual(payload["Label"], "com.steven.phase5r.shadoweval")
        self.assertFalse(payload["RunAtLoad"])
        self.assertNotIn("StartInterval", payload)
        self.assertEqual(
            payload["WatchPaths"],
            [
                "/Users/messssi/LocalRuntime/equity/03_source_data/phase5r/"
                "phase5r_llm_evidence_packet.json"
            ],
        )
        self.assertEqual(
            payload["ProgramArguments"],
            [
                "/Users/messssi/LocalRuntime/equity/07_automation/scheduler/"
                "run_phase5r_shadow_llm_event.sh"
            ],
        )
        wrapper = (scheduler_dir / "run_phase5r_shadow_llm_event.sh").read_text(
            encoding="utf-8"
        )
        for prohibited in ("send_phase5r_daily_email", "smtp", "broker", "order"):
            self.assertNotIn(prohibited, wrapper.lower())

    def test_provider_schemas_use_only_portable_constraints(self) -> None:
        forbidden = {"minLength", "maxLength", "uniqueItems", "const"}

        def visit(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(analyst_schema())
        visit(critic_schema())
        visit(judge_schema())
        self.assertIn(
            "pattern",
            analyst_schema()["properties"]["claims"]["items"]["properties"][
                "claim_id"
            ],
        )

    def test_dynamic_schemas_bind_hashes_and_coverage(self) -> None:
        critic = critic_schema(
            packet_id="a" * 64,
            analyst_output_sha256="b" * 64,
            claim_ids=["claim_one", "claim_two"],
            entity_tickers=["IOT", "SPY"],
        )
        self.assertEqual(critic["properties"]["claim_reviews"]["minItems"], 2)
        judge = judge_schema(
            packet_id="a" * 64,
            candidate_set_sha256="c" * 64,
            blind_item_ids=["blind_one"],
            entity_tickers=["IOT"],
        )
        self.assertEqual(judge["properties"]["item_reviews"]["maxItems"], 1)

    def test_provider_failure_text_is_reduced_to_closed_codes(self) -> None:
        self.assertEqual(
            classify_nonzero_exit("The output schema is invalid"),
            "provider_schema_rejected",
        )
        self.assertEqual(
            classify_nonzero_exit("unrecognized feature in config"),
            "provider_config_error",
        )
        self.assertEqual(
            classify_nonzero_exit("opaque failure"), "provider_nonzero_exit"
        )

    def test_cli_usage_parser_requires_exact_completed_usage(self) -> None:
        stream = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 25,
                    "output_tokens": 10,
                    "reasoning_output_tokens": 4,
                },
            }
        )
        self.assertEqual(cli_reported_token_usage(stream)["total_tokens"], 110)
        with self.assertRaises(ShadowProviderError):
            cli_reported_token_usage("")

    def test_contract_accepts_source_bound_outputs(self) -> None:
        packet = fake_packet()
        analyst = valid_analyst(packet)
        critic = valid_critic(analyst, packet)
        target, _ = build_blind_judge_target(analyst, critic)
        judge = valid_judge(analyst, critic, packet)
        validate_analyst(packet, analyst)
        validate_critic(packet, analyst, critic)
        validate_judge(packet, target, judge)

    def test_blind_target_hides_self_grading_labels(self) -> None:
        analyst = valid_analyst()
        critic = valid_critic(analyst)
        target, mapping = build_blind_judge_target(analyst, critic)
        self.assertEqual(
            set(target["candidates"][0]),
            {
                "blind_item_id",
                "ticker",
                "statement",
                "period",
                "source_ids",
                "calculation_ids",
            },
        )
        self.assertNotIn("origin", target["candidates"][0])
        self.assertNotIn("materiality", target["candidates"][0])
        self.assertNotIn("novelty", target["candidates"][0])
        self.assertIn(target["candidates"][0]["blind_item_id"], mapping)

    def test_critic_routing_is_conditional(self) -> None:
        config = shadow_runner.load_config()
        analyst = valid_analyst(materiality="low")
        analyst["ticker_reviews"][0]["semantic_state"] = "strengthened"
        routed, reasons = shadow_runner.critic_route(analyst, config)
        self.assertFalse(routed)
        self.assertEqual(reasons, [])
        analyst["claims"][0]["materiality"] = "high"
        self.assertTrue(shadow_runner.critic_route(analyst, config)[0])

    def test_semantic_event_ignores_daily_market_and_account_churn(self) -> None:
        first = fake_packet()
        second = copy.deepcopy(first)
        second["as_of_et"] = "2026-09-03T12:00:00-04:00"
        second["cycle_date"] = "2026-09-02"
        second["decision_fingerprint"] = "d" * 64
        second["source_catalog"][0]["accepted_at"] = "2026-09-03T12:00:00Z"
        second["account_state"] = {"cash": 999}
        second["market_prices"] = {"IOT": 77}
        self.assertEqual(
            shadow_runner.semantic_event_fingerprint(first),
            shadow_runner.semantic_event_fingerprint(second),
        )
        second["source_catalog"][0]["content_sha256"] = "e" * 64
        self.assertNotEqual(
            shadow_runner.semantic_event_fingerprint(first),
            shadow_runner.semantic_event_fingerprint(second),
        )

    def test_legacy_semantic_view_prevents_automatic_duplicate(self) -> None:
        packet = fake_packet()
        semantic_view = shadow_runner.build_semantic_view(packet)
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "runs.local"
            run_dir = output_root / ("f" * 64)
            run_dir.mkdir(parents=True)
            (run_dir / "bundle.json").write_text(
                json.dumps(
                    {
                        "schema_version": "phase5r_shadow_bundle_v1",
                        "evaluation_class": "live_shadow",
                        "run_identity": {
                            "semantic_view_sha256": canonical_sha256(semantic_view)
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(
                shadow_runner._event_already_attempted(
                    output_root,
                    event_fingerprint=shadow_runner.semantic_event_fingerprint(packet),
                    evaluation_class="live_shadow",
                    evaluation_stage="bounded_autonomous_v1",
                    semantic_view_sha256=canonical_sha256(semantic_view),
                )
            )

    def test_contract_rejects_unknown_source_numeric_and_action_language(self) -> None:
        packet = fake_packet()
        unknown = valid_analyst(packet)
        unknown["claims"][0]["source_ids"] = ["sec:IOT:invented"]
        with self.assertRaises(ShadowContractError):
            validate_analyst(packet, unknown)
        numeric = valid_analyst(packet)
        numeric["claims"][0]["statement"] = "Revenue grew 30 percent."
        with self.assertRaises(ShadowContractError):
            validate_analyst(packet, numeric)
        action = valid_analyst(packet)
        action["claims"][0]["statement"] = "Investors should buy the stock."
        with self.assertRaises(ShadowContractError):
            validate_analyst(packet, action)

    def test_packet_loader_rejects_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "packet.json"
            target.write_text("{}", encoding="utf-8")
            linked = root / "linked.json"
            linked.symlink_to(target)
            with self.assertRaises(ShadowContractError):
                load_packet(linked)

    def test_fixture_run_is_blind_judged_and_excluded_from_metrics(self) -> None:
        packet = fake_packet()
        analyst = valid_analyst(packet)
        critic = valid_critic(analyst, packet)
        judge = valid_judge(analyst, critic, packet)
        provider = shadow_runner.FixtureProvider(
            {"analyst": analyst, "critic": critic, "judge": judge}
        )
        config = shadow_runner.load_config()
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "runs.local"
            with patch.object(shadow_runner, "load_packet", return_value=packet):
                bundle_path = shadow_runner.execute(
                    packet_path=Path(directory) / "unused.json",
                    output_root=output_root,
                    provider=provider,
                    transport="fixture",
                    evaluation_class="fixture_validation",
                    live=False,
                    config=config,
                )
            bundle = load_automatic_bundle(bundle_path)
            self.assertEqual(
                bundle["automatic_evaluation"]["semantic_value_status"],
                "incremental_material_value_observed",
            )
            self.assertFalse((bundle_path.parent / "review_template.json").exists())
            result = aggregate([bundle], config)
            self.assertEqual(result["metrics"]["automatically_judged_events"], 0)
            self.assertEqual(result["metrics"]["fixture_validation_events_excluded"], 1)
            self.assertFalse(result["decision"]["promotion_authorized"])

    def test_low_risk_fixture_skips_critic_but_keeps_blind_judge(self) -> None:
        packet = fake_packet()
        analyst = valid_analyst(packet, materiality="low")
        analyst["ticker_reviews"][0]["semantic_state"] = "strengthened"
        judge = valid_judge(analyst, None, packet)
        provider = shadow_runner.FixtureProvider(
            {"analyst": analyst, "judge": judge}
        )
        config = shadow_runner.load_config()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(shadow_runner, "load_packet", return_value=packet):
                bundle_path = shadow_runner.execute(
                    packet_path=Path(directory) / "unused.json",
                    output_root=Path(directory) / "runs.local",
                    provider=provider,
                    transport="fixture",
                    evaluation_class="fixture_validation",
                    live=False,
                    config=config,
                )
            bundle = load_automatic_bundle(bundle_path)
            self.assertIsNone(bundle["critic"])
            self.assertFalse(bundle["critic_routing"]["routed"])
            self.assertEqual(
                {row["role"] for row in bundle["provider_metadata"]},
                {"analyst", "judge"},
            )

    def test_no_human_review_is_required_to_aggregate(self) -> None:
        result = aggregate([], shadow_runner.load_config())
        self.assertEqual(
            result["decision"]["status"], "collecting_bounded_evaluation_evidence"
        )
        self.assertFalse(result["decision"]["promotion_authorized"])

    def test_failed_live_role_is_terminal_and_not_retried(self) -> None:
        packet = fake_packet()
        provider = FailingProvider()
        config = shadow_runner.load_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(shadow_runner, "load_packet", return_value=packet),
                patch.object(shadow_runner, "LEDGER_PATH", root / "calls.jsonl"),
                patch.object(shadow_runner, "LOCK_PATH", root / "calls.lock"),
            ):
                kwargs = {
                    "packet_path": root / "unused.json",
                    "output_root": root / "runs.local",
                    "provider": provider,
                    "transport": "codex_cli_external_auth",
                    "evaluation_class": "live_shadow",
                    "live": True,
                    "config": config,
                    "packet_archive_root": root / "packets.local",
                }
                with self.assertRaises(shadow_runner.ShadowRunError):
                    shadow_runner.execute(**kwargs)
                with self.assertRaises(shadow_runner.ShadowRunError):
                    shadow_runner.execute(**kwargs)
            self.assertEqual(provider.calls, 1)
            ledger = [
                json.loads(line)
                for line in (root / "calls.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual([row["event"] for row in ledger], ["started", "failed"])

    def test_full_run_capacity_fails_closed_before_provider_call(self) -> None:
        packet = fake_packet()
        provider = FailingProvider()
        config = copy.deepcopy(shadow_runner.load_config())
        config["limits"]["maximum_physical_live_calls_total"] = 2
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(shadow_runner, "load_packet", return_value=packet),
                patch.object(shadow_runner, "LEDGER_PATH", root / "calls.jsonl"),
                patch.object(shadow_runner, "LOCK_PATH", root / "calls.lock"),
            ):
                with self.assertRaises(shadow_runner.ShadowRunError):
                    shadow_runner.execute(
                        packet_path=root / "unused.json",
                        output_root=root / "runs.local",
                        provider=provider,
                        transport="codex_cli_external_auth",
                        evaluation_class="live_shadow",
                        live=True,
                        config=config,
                        packet_archive_root=root / "packets.local",
                    )
            self.assertEqual(provider.calls, 0)

    def test_new_stage_allowance_is_enforced_without_legacy_ledger(self) -> None:
        packet = fake_packet()
        provider = FailingProvider()
        config = copy.deepcopy(shadow_runner.load_config())
        config["limits"]["new_stage_physical_call_allowance"] = 2
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(shadow_runner, "load_packet", return_value=packet),
                patch.object(shadow_runner, "LEDGER_PATH", root / "calls.jsonl"),
                patch.object(shadow_runner, "LOCK_PATH", root / "calls.lock"),
            ):
                with self.assertRaises(shadow_runner.ShadowRunError):
                    shadow_runner.execute(
                        packet_path=root / "unused.json",
                        output_root=root / "runs.local",
                        provider=provider,
                        transport="codex_cli_external_auth",
                        evaluation_class="live_shadow",
                        live=True,
                        config=config,
                        packet_archive_root=root / "packets.local",
                    )
            self.assertEqual(provider.calls, 0)

    def test_production_entrypoints_do_not_reference_shadow_surface(self) -> None:
        production_files = (
            "run_phase5r_daily_refresh.py",
            "run_phase5r_daily_refresh_scheduler.py",
            "run_phase5r_runtime_scheduler.py",
            "create_phase5r_daily_decision_and_brief.py",
            "send_phase5r_daily_email.py",
        )
        prohibited = (
            "run_phase5r_shadow_llm_evaluation",
            "phase5r_shadow_llm_provider",
            "evaluate_phase5r_shadow_llm_incremental_value",
        )
        for name in production_files:
            source = (SCRIPT_DIR / name).read_text(encoding="utf-8")
            for token in prohibited:
                self.assertNotIn(token, source)

    def test_cli_provider_uses_json_usage_minimal_env_and_disabled_tools(self) -> None:
        packet = fake_packet()
        captured: dict = {}
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "codex"
            executable.write_text("placeholder", encoding="utf-8")
            executable.chmod(0o700)

            def fake_run(command, **kwargs):
                captured["command"] = command
                captured["kwargs"] = kwargs
                output_path = Path(command[command.index("--output-last-message") + 1])
                output_path.write_text('{"ok": true}', encoding="utf-8")
                stdout = json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {
                            "input_tokens": 10,
                            "cached_input_tokens": 0,
                            "output_tokens": 2,
                            "reasoning_output_tokens": 1,
                        },
                    }
                )
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            with (
                patch(
                    "phase5r_shadow_llm_provider.executable_sha256",
                    return_value="d" * 64,
                ),
                patch(
                    "phase5r_shadow_llm_provider.subprocess.run", side_effect=fake_run
                ),
            ):
                provider = CodexCliProvider(executable, expected_sha256="d" * 64)
                result = provider.generate(
                    role="analyst",
                    model="gpt-5.6-terra",
                    reasoning_effort="medium",
                    schema={"type": "object"},
                    instructions="Return a bounded result.",
                    input_payload={"semantic_view": packet},
                )
            self.assertEqual(result.payload, {"ok": True})
            self.assertEqual(result.metadata["authoritative_token_usage"]["total_tokens"], 12)
            self.assertIsNone(result.metadata["authoritative_billing_cost_usd"])
            self.assertIsNone(captured["kwargs"]["env"].get("OPENAI_API_KEY"))
            self.assertEqual(
                captured["kwargs"]["cwd"], Path(captured["kwargs"]["env"]["TMPDIR"])
            )
            self.assertIn("--json", captured["command"])
            self.assertIn("--ignore-user-config", captured["command"])
            self.assertIn("read-only", captured["command"])
            self.assertIn("--disable", captured["command"])
            self.assertFalse(result.metadata["credential_read_by_repository"])
            self.assertFalse(result.metadata["tools_enabled"])


if __name__ == "__main__":
    unittest.main()
