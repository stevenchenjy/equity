#!/usr/bin/env python3
"""Run one isolated, noncanonical Phase 5R production shadow review.

The provider client is constructed only inside this dedicated runner, only
after the local freshness, frozen-handoff, contract, and cost-reservation
gates pass.  The OpenAI SDK receives authentication from the external runtime;
this file never reads, prints, hashes, stores, or forwards an API key.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from phase5r_llm_provider import OpenAIResponsesProvider, ProviderError
from phase5r_production_shadow_v1 import (
    MAX_OUTPUT_TOKENS,
    MODEL,
    PRODUCTION_SHADOW_SCHEMA_VERSION,
    REQUEST_TIMEOUT_SECONDS,
    SDK_MAX_RETRIES,
    check_current_readiness,
    current_cost_exposure,
    provider_attempt_capacity,
    run_production_shadow,
)


REQUIRED_OPENAI_SDK_VERSION = "2.49.0"


def _sdk_runtime_status() -> dict[str, Any]:
    """Inspect only the installed SDK package; never construct a client."""

    try:
        import openai
    except Exception:
        return {
            "available": False,
            "version": None,
            "reason": "openai_sdk_unavailable",
        }
    version = getattr(openai, "__version__", None)
    if version != REQUIRED_OPENAI_SDK_VERSION:
        return {
            "available": False,
            "version": version if isinstance(version, str) else None,
            "reason": "openai_sdk_version_mismatch",
        }
    return {"available": True, "version": version, "reason": None}


def external_runtime_provider_factory() -> OpenAIResponsesProvider:
    """Build one SDK client without touching credential values in repository code."""

    try:
        # No api_key argument is passed and no environment variable is read by
        # this repository code.  The externally authenticated SDK runtime owns
        # its normal credential resolution and any authentication failure.
        status = _sdk_runtime_status()
        if status["available"] is not True:
            raise ProviderError(str(status["reason"]))
        from openai import OpenAI

        client = OpenAI(max_retries=SDK_MAX_RETRIES, timeout=REQUEST_TIMEOUT_SECONDS)
        return OpenAIResponsesProvider(
            client,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            request_timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            billing_scope_attestation="unverified",
            retryable_exception_types=(),
            require_zero_client_retries=True,
        )
    except Exception as exc:
        # Preserve the boundary without exposing SDK, credential, or account
        # detail in an artifact or terminal output.
        raise ProviderError("external_authenticated_runtime_unavailable") from exc


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--run", action="store_true")
    mode.add_argument("--cost-exposure", action="store_true")
    args = parser.parse_args()
    if args.check:
        readiness = check_current_readiness()
        sdk = _sdk_runtime_status()
        capacity = provider_attempt_capacity()
        readiness["openai_sdk"] = sdk
        readiness["provider_attempt_capacity"] = capacity
        # Authentication remains deliberately unprobed until a fully frozen,
        # current, locally validated handoff has been cost-reserved.  A check
        # must never construct a client or trigger a provider request.
        readiness["authentication"] = "not_probed_without_provider_call"
        readiness["provider_constructed"] = False
        readiness["provider_called"] = False
        if readiness.get("ready") is True:
            if sdk["available"] is not True:
                readiness["ready"] = False
                readiness["reason"] = str(sdk["reason"])
            elif capacity["available"] is not True:
                readiness["ready"] = False
                readiness["reason"] = str(capacity["reason"])
        _print(readiness)
        return 0
    if args.cost_exposure:
        _print(
            {
                "schema_version": "phase5r_production_shadow_cost_exposure_v1",
                "cost_exposure": current_cost_exposure(),
                "canonical_effect": False,
                "provider_constructed": False,
                "provider_called": False,
            }
        )
        return 0
    # A package-metadata failure is detected before the core can freeze an
    # input or reserve the day.  This check never constructs an SDK client or
    # touches its credential resolution path.
    sdk = _sdk_runtime_status()
    if sdk["available"] is not True:
        _print(
            {
                "schema_version": PRODUCTION_SHADOW_SCHEMA_VERSION,
                "outcome": "blocked",
                "reason": str(sdk["reason"]),
                "canonical_effect": False,
                "provider_constructed": False,
                "provider_called": False,
                "email_attempted": False,
            }
        )
        return 0
    result = run_production_shadow(provider_factory=external_runtime_provider_factory)
    _print(result)
    # A gate block is a safe no-op for the post-refresh scheduler.  A terminal
    # runtime/contract/authentication failure is nonzero and never retried by
    # this runner on the same day because the reservation remains in the ledger.
    return 1 if result.get("outcome") == "terminal_failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
