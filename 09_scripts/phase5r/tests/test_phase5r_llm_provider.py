from __future__ import annotations

import json
import socket
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from _support import PROJECT_ROOT, materialized
from phase5r_llm_provider import (
    CodexCliProvider,
    FixtureProvider,
    ProviderError,
)


class ProviderTests(unittest.TestCase):
    def test_fixture_provider_is_deep_copied_and_credential_free(self) -> None:
        _, responses, _ = materialized("g01_stable_hold")
        provider = FixtureProvider(responses)
        result = provider.generate(
            role="analyst",
            model="fixture-model",
            reasoning_effort="medium",
            schema={},
            instructions="fixture only",
            input_payload={"packet": "fixture"},
        )
        result.payload["claims"].clear()
        second = provider.generate(
            role="analyst",
            model="fixture-model",
            reasoning_effort="medium",
            schema={},
            instructions="fixture only",
            input_payload={"packet": "fixture"},
        )
        self.assertTrue(second.payload["claims"])
        self.assertFalse(second.metadata["credential_read"])
        self.assertFalse(second.metadata["tools_enabled"])

    def test_fixture_provider_never_invokes_process_or_network(self) -> None:
        _, responses, _ = materialized("g01_stable_hold")
        provider = FixtureProvider(responses)
        with (
            mock.patch(
                "phase5r_llm_provider.subprocess.run",
                side_effect=AssertionError("process invoked"),
            ) as process_mock,
            mock.patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("network invoked"),
            ) as network_mock,
        ):
            provider.generate(
                role="committee",
                model="fixture-model",
                reasoning_effort="high",
                schema={},
                instructions="fixture only",
                input_payload={"packet": "fixture"},
            )
        process_mock.assert_not_called()
        network_mock.assert_not_called()

    def test_missing_fixture_role_fails_closed(self) -> None:
        provider = FixtureProvider({})
        with self.assertRaisesRegex(ProviderError, "missing role"):
            provider.generate(
                role="critic",
                model="fixture-model",
                reasoning_effort="high",
                schema={},
                instructions="fixture only",
                input_payload={},
            )

    def test_synthetic_secret_canary_is_not_echoed(self) -> None:
        _, responses, _ = materialized("g01_stable_hold")
        result = FixtureProvider(responses).generate(
            role="analyst",
            model="fixture-model",
            reasoning_effort="medium",
            schema={},
            instructions="fixture only",
            input_payload={"private_test_value": "SMTP_CANARY_DO_NOT_LEAK"},
        )
        serialized = json.dumps(
            {"payload": result.payload, "metadata": result.metadata},
            sort_keys=True,
        )
        self.assertNotIn("SMTP_CANARY_DO_NOT_LEAK", serialized)

    def test_codex_bridge_cannot_be_inside_project(self) -> None:
        with self.assertRaisesRegex(ProviderError, "cannot live inside"):
            CodexCliProvider(PROJECT_ROOT / "AGENTS.md")


if __name__ == "__main__":
    unittest.main()
