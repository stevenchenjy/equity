from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import materialized, rehash
from phase5r_daily_common import ExclusiveFileLock
from phase5r_llm_contract import (
    ContractError,
    validate_committee,
    validate_packet,
)
from phase5r_llm_provider import CodexCliProvider, FixtureProvider, ProviderError
from run_phase5r_llm_shadow import (
    ALLOWED_PROVIDER_EXECUTABLE,
    _verified_close_session,
    apply_verified_close_stability,
    execute_shadow,
    load_registry,
)


def _bind_responses_to_packet(
    packet: dict[str, object],
    responses: dict[str, dict[str, object]],
) -> None:
    packet_id = str(packet["packet_id"])
    for response in responses.values():
        response["packet_id"] = packet_id


class DecisionBoundaryRegressionTests(unittest.TestCase):
    def test_imperative_purchase_and_liquidate_synonyms_are_rejected(self) -> None:
        packet, responses, _ = materialized("g01_stable_hold")
        for advice in (
            "Purchase TST immediately.",
            "Liquidate the TST position.",
            "You should acquire TST today.",
            "Please dispose of TST.",
            "Close out the position now.",
        ):
            with self.subTest(advice=advice):
                committee = copy.deepcopy(responses["committee"])
                committee["decisive_advice"] = advice
                with self.assertRaisesRegex(ContractError, "imperative"):
                    validate_committee(packet, committee)

    def test_material_or_ticker_thesis_break_cannot_produce_buy_candidate(
        self,
    ) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        material_break = copy.deepcopy(responses["committee"])
        material_break["material_thesis_break"] = True
        with self.assertRaisesRegex(ContractError, "thesis break"):
            validate_committee(packet, material_break)

        broken_ticker = copy.deepcopy(responses["committee"])
        broken_ticker["ticker_decisions"][0]["thesis_direction"] = "broken"
        with self.assertRaisesRegex(ContractError, "broken ticker thesis"):
            validate_committee(packet, broken_ticker)

    def test_empty_canonical_close_session_never_grants_second_close(self) -> None:
        packet, responses, _ = materialized("g08_add_second_close")
        packet["gates"].update(
            {
                "deterministic_action_stability_distinct_closes": 2,
                "deterministic_transition_pending_tickers": [],
                "deterministic_transition_eligible_tickers": ["TST"],
                "verified_close_session": "",
            }
        )
        packet = rehash(packet)
        _bind_responses_to_packet(packet, responses)
        bundle = execute_shadow(
            packet,
            FixtureProvider(responses),
            load_registry(),
            distinct_valid_closes=0,
        )
        result = apply_verified_close_stability(packet, bundle)
        self.assertEqual(result["stability"]["distinct_valid_closes"], 0)
        self.assertEqual(
            result["adjudication"]["effective_classification"],
            "watchlist",
        )

    def test_invalid_canonical_close_sessions_fail_closed(self) -> None:
        packet, _, _ = materialized("g08_add_second_close")
        for session in ("2026-07-22", "not-a-date", 0, None):
            with self.subTest(session=session):
                candidate = copy.deepcopy(packet)
                candidate["gates"]["verified_close_session"] = session
                self.assertEqual(_verified_close_session(candidate), "")
                with self.assertRaisesRegex(
                    ContractError,
                    "verified close session",
                ):
                    validate_packet(rehash(candidate))


class PacketSanitizationRegressionTests(unittest.TestCase):
    def test_secret_prefix_and_camel_case_api_key_are_rejected(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        token_candidate = copy.deepcopy(packet)
        token_candidate["entities"][0]["thesis"] = (
            "sk-proj-CANARY0123456789abcdef"
        )
        with self.assertRaisesRegex(ContractError, "secret-like token"):
            validate_packet(rehash(token_candidate))

        key_candidate = copy.deepcopy(packet)
        key_candidate["entities"][0]["apiKey"] = "CANARY_VALUE"
        with self.assertRaisesRegex(ContractError, "forbidden field"):
            validate_packet(rehash(key_candidate))

        assignment_candidate = copy.deepcopy(packet)
        assignment_candidate["entities"][0]["thesis"] = (
            "apiKey=CANARY_VALUE"
        )
        with self.assertRaisesRegex(ContractError, "secret-like assignment"):
            validate_packet(rehash(assignment_candidate))

    def test_public_sec_dollar_figure_is_preserved_with_provenance(self) -> None:
        packet, _, _ = materialized("g01_stable_hold")
        source = packet["source_catalog"][0]
        self.assertEqual(source["source_type"], "sec_filing_text_chunk")
        self.assertEqual(source["authority"], "primary_official")
        excerpt = "The registrant reported revenue of $2,000.00 for the quarter."
        source["excerpt_text"] = excerpt
        source["content_sha256"] = hashlib.sha256(
            excerpt.encode("utf-8")
        ).hexdigest()
        packet = rehash(packet)
        self.assertIs(validate_packet(packet), packet)


class CanonicalLockRegressionTests(unittest.TestCase):
    def test_exclusive_lock_refuses_symlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-lock-symlink-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.lock"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            lock_path = root / "pipeline.lock"
            lock_path.symlink_to(canary)
            before = canary.read_bytes()
            with self.assertRaises((OSError, RuntimeError)):
                with ExclusiveFileLock(lock_path):
                    pass
            self.assertEqual(canary.read_bytes(), before)

    def test_exclusive_lock_refuses_hardlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-lock-hardlink-") as directory:
            root = Path(directory)
            canary = root / "canonical-canary.lock"
            canary.write_text("UNCHANGED\n", encoding="utf-8")
            lock_path = root / "pipeline.lock"
            os.link(canary, lock_path)
            before = canary.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "one link"):
                with ExclusiveFileLock(lock_path):
                    pass
            self.assertEqual(canary.read_bytes(), before)


class ProviderPinRegressionTests(unittest.TestCase):
    def test_provider_revalidates_executable_before_subprocess(self) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-provider-swap-") as directory:
            executable = Path(directory) / "codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            expected_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
            provider = CodexCliProvider(
                executable,
                expected_sha256=expected_hash,
            )
            executable.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
            with mock.patch(
                "phase5r_llm_provider.subprocess.run"
            ) as process_mock:
                with self.assertRaisesRegex(ProviderError, "hash mismatch"):
                    provider.generate(
                        role="analyst",
                        model="fixture-model",
                        reasoning_effort="medium",
                        schema={"type": "object"},
                        instructions="return one object",
                        input_payload={"packet": "safe"},
                    )
            process_mock.assert_not_called()

    def test_registry_pins_direct_native_codex_binary(self) -> None:
        registry = load_registry()
        executable = Path(registry["provider_executable"])
        self.assertEqual(executable, ALLOWED_PROVIDER_EXECUTABLE)
        self.assertNotEqual(executable, Path("/opt/homebrew/bin/codex"))
        provider = CodexCliProvider(
            executable,
            expected_sha256=registry["provider_executable_sha256"],
        )
        self.assertEqual(provider.executable, executable)


if __name__ == "__main__":
    unittest.main()
