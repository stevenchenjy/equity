from __future__ import annotations

import json
import hashlib
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _support import PROJECT_ROOT, materialized
from phase5r_llm_provider import (
    CodexCliProvider,
    FixtureProvider,
    OpenAIResponsesProvider,
    ProviderError,
    RetryableProviderTransportError,
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
            CodexCliProvider(
                PROJECT_ROOT / "AGENTS.md",
                expected_sha256="0" * 64,
            )

    def test_codex_bridge_disables_tools_and_strips_sensitive_environment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="phase5r-provider-test-") as directory:
            executable = Path(directory) / "codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            expected_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
            provider = CodexCliProvider(
                executable,
                expected_sha256=expected_hash,
            )

            def completed(command: list[str], **kwargs: object):
                output_path = Path(command[command.index("--output-last-message") + 1])
                output_path.write_text('{"ok": true}', encoding="utf-8")
                environment = kwargs["env"]
                self.assertNotIn("OPENAI_API_KEY", environment)
                self.assertNotIn("SMTP_PASSWORD", environment)
                self.assertNotIn("BROKER_TOKEN", environment)
                for feature in (
                    "shell_tool",
                    "unified_exec",
                    "apps",
                    "browser_use",
                    "computer_use",
                    "plugins",
                ):
                    index = command.index(feature)
                    self.assertEqual(command[index - 1], "--disable")
                self.assertIn("--ignore-user-config", command)
                self.assertIn("--ignore-rules", command)
                return subprocess.CompletedProcess(command, 0, "", "")

            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "OPENAI_API_KEY": "CANARY_API_SECRET",
                        "SMTP_PASSWORD": "CANARY_SMTP_SECRET",
                        "BROKER_TOKEN": "CANARY_BROKER_SECRET",
                        "LANG": "en_US.UTF-8",
                    },
                    clear=False,
                ),
                mock.patch(
                    "phase5r_llm_provider.subprocess.run",
                    side_effect=completed,
                ),
            ):
                result = provider.generate(
                    role="analyst",
                    model="fixture-model",
                    reasoning_effort="medium",
                    schema={"type": "object"},
                    instructions="return one object",
                    input_payload={"packet": "safe"},
                )
            self.assertEqual(result.payload, {"ok": True})
            self.assertEqual(result.metadata["environment_policy"], "minimal_allowlist")
            self.assertIn("shell_tool", result.metadata["tool_features_disabled"])

    def test_only_timeout_and_missing_final_response_are_retryable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix="phase5r-provider-taxonomy-"
        ) as directory:
            executable = Path(directory) / "codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            provider = CodexCliProvider(
                executable,
                expected_sha256=hashlib.sha256(
                    executable.read_bytes()
                ).hexdigest(),
                max_output_bytes=8,
            )

            def invoke() -> None:
                provider.generate(
                    role="analyst",
                    model="fixture-model",
                    reasoning_effort="medium",
                    schema={"type": "object"},
                    instructions="return one object",
                    input_payload={"packet": "safe"},
                )

            terminal_outputs = {
                "oversize": "x" * 9,
                "malformed_json": "{bad",
                "non_object": "[]",
            }
            for label, output in terminal_outputs.items():
                with self.subTest(label=label):

                    def completed(
                        command: list[str],
                        **kwargs: object,
                    ) -> subprocess.CompletedProcess[str]:
                        output_path = Path(
                            command[
                                command.index(
                                    "--output-last-message"
                                )
                                + 1
                            ]
                        )
                        output_path.write_text(
                            output,
                            encoding="utf-8",
                        )
                        return subprocess.CompletedProcess(
                            command,
                            0,
                            "",
                            "",
                        )

                    with mock.patch(
                        "phase5r_llm_provider.subprocess.run",
                        side_effect=completed,
                    ):
                        with self.assertRaises(
                            ProviderError
                        ) as raised:
                            invoke()
                    self.assertNotIsInstance(
                        raised.exception,
                        RetryableProviderTransportError,
                    )

            with mock.patch(
                "phase5r_llm_provider.subprocess.run",
                side_effect=subprocess.TimeoutExpired(
                    ["codex"],
                    1,
                ),
            ):
                with self.assertRaises(
                    RetryableProviderTransportError
                ):
                    invoke()

            with mock.patch(
                "phase5r_llm_provider.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["codex"],
                    0,
                    "",
                    "",
                ),
            ):
                with self.assertRaises(
                    RetryableProviderTransportError
                ):
                    invoke()

    def test_responses_adapter_is_strict_stateless_tool_free_and_receipted(
        self,
    ) -> None:
        class Responses:
            def __init__(self) -> None:
                self.request: dict[str, object] = {}

            def create(self, **kwargs: object) -> object:
                self.request = kwargs
                return type(
                    "Response",
                    (),
                    {
                        "id": "resp_fixture_5r",
                        "status": "completed",
                        "model": "gpt-5.6-sol-2026-07-01",
                        "output": [
                            {
                                "type": "message",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": '{"ok":true}',
                                    }
                                ],
                            }
                        ],
                        "usage": {
                            "input_tokens": 120,
                            "output_tokens": 8,
                            "total_tokens": 128,
                            "input_tokens_details": {
                                "cached_tokens": 20,
                                "cache_write_tokens": 10,
                            },
                        },
                    },
                )()

        class Client:
            def __init__(self) -> None:
                self.responses = Responses()

        client = Client()
        provider = OpenAIResponsesProvider(client, max_output_tokens=1024)
        result = provider.generate(
            role="committee",
            model="gpt-5.6-sol",
            reasoning_effort="high",
            schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
                "required": ["ok"],
                "additionalProperties": False,
            },
            instructions="Return the closed result.",
            input_payload={"evidence": "fixture"},
        )

        self.assertEqual(result.payload, {"ok": True})
        request = client.responses.request
        self.assertEqual(request["tools"], [])
        self.assertIs(request["store"], False)
        self.assertEqual(
            request["prompt_cache_options"],
            {"mode": "explicit"},
        )
        self.assertEqual(request["reasoning"], {"effort": "high"})
        self.assertEqual(request["max_output_tokens"], 1024)
        output_format = request["text"]["format"]  # type: ignore[index]
        self.assertEqual(output_format["type"], "json_schema")
        self.assertIs(output_format["strict"], True)
        self.assertEqual(
            result.metadata["provider_response_id"],
            "resp_fixture_5r",
        )
        self.assertEqual(
            result.metadata["resolved_model"],
            "gpt-5.6-sol-2026-07-01",
        )
        self.assertEqual(
            result.metadata["usage"],
            {
                "input_tokens": 110,
                "output_tokens": 8,
                "cached_input_tokens": 20,
                "cache_creation_input_tokens": 10,
                "cache_read_input_tokens": 0,
            },
        )
        self.assertFalse(result.metadata["credential_read"])
        self.assertFalse(result.metadata["tools_enabled"])

    def test_responses_adapter_rejects_inconsistent_native_usage(
        self,
    ) -> None:
        class Responses:
            def create(self, **kwargs: object) -> object:
                del kwargs
                return {
                    "id": "resp_bad_usage",
                    "status": "completed",
                    "model": "gpt-5.6-terra",
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": '{"ok":true}',
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 2,
                        "total_tokens": 12,
                        "input_tokens_details": {
                            "cached_tokens": 8,
                            "cache_write_tokens": 4,
                        },
                    },
                }

        class Client:
            responses = Responses()

        with self.assertRaises(ProviderError):
            OpenAIResponsesProvider(Client()).generate(
                role="analyst",
                model="gpt-5.6-terra",
                reasoning_effort="medium",
                schema={"type": "object"},
                instructions="Return one object.",
                input_payload={"packet": "fixture"},
            )

    def test_responses_adapter_failure_taxonomy_is_fail_closed(self) -> None:
        class Responses:
            def __init__(self, response: object) -> None:
                self.response = response

            def create(self, **kwargs: object) -> object:
                del kwargs
                return self.response

        class Client:
            def __init__(self, response: object) -> None:
                self.responses = Responses(response)

        def invoke(response: object) -> None:
            OpenAIResponsesProvider(Client(response)).generate(
                role="analyst",
                model="gpt-5.6-terra",
                reasoning_effort="medium",
                schema={"type": "object"},
                instructions="Return one object.",
                input_payload={"packet": "fixture"},
            )

        incomplete = {
            "id": "resp_incomplete",
            "status": "incomplete",
            "model": "gpt-5.6-terra",
            "output": [],
        }
        with self.assertRaises(ProviderError) as incomplete_error:
            invoke(incomplete)
        self.assertNotIsInstance(
            incomplete_error.exception,
            RetryableProviderTransportError,
        )

        refusal = {
            "id": "resp_refusal",
            "status": "completed",
            "model": "gpt-5.6-terra",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "refusal", "refusal": "fixture refusal"}
                    ],
                }
            ],
        }
        with self.assertRaises(ProviderError) as refusal_error:
            invoke(refusal)
        self.assertNotIsInstance(
            refusal_error.exception,
            RetryableProviderTransportError,
        )

        missing_final = {
            "id": "resp_empty",
            "status": "completed",
            "model": "gpt-5.6-terra",
            "output": [],
        }
        with self.assertRaises(RetryableProviderTransportError):
            invoke(missing_final)

        malformed = {
            "id": "resp_malformed",
            "status": "completed",
            "model": "gpt-5.6-terra",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": "{bad"}
                    ],
                }
            ],
        }
        with self.assertRaises(ProviderError) as malformed_error:
            invoke(malformed)
        self.assertNotIsInstance(
            malformed_error.exception,
            RetryableProviderTransportError,
        )


if __name__ == "__main__":
    unittest.main()
