#!/usr/bin/env python3
"""Explicitly transition the isolated model layer from fixtures to live shadow.

This transition does not install a scheduler, invoke a model, change a canonical
decision, or enable email/execution.  It exists so external inference can never
be activated accidentally by an ordinary refresh or install command.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from phase5r_daily_common import (
    ROOT,
    atomic_write_json,
    atomic_write_text,
    iso_now,
)
from phase5r_llm_activation_receipt import (
    ACTIVATION_RECEIPT_PATH,
    build_activation_receipt,
    verify_active_activation_receipt,
)
from phase5r_llm_provider import (
    CodexCliProvider,
    ProviderError,
    _sanitized_codex_environment,
)
from run_phase5r_llm_shadow import REGISTRY_PATH, load_registry
from verify_phase5r_llm_provider_replay_gate import (
    CORPUS_MANIFEST_PATH,
    PROVIDER_REPORT_PATH,
    verify_provider_replay_gate,
)


BOUNDARY_VERIFIER = (
    ROOT / "09_scripts" / "phase5r" / "verify_phase5r_llm_shadow_boundary.py"
)


def external_auth_status(
    executable: Path,
    expected_sha256: str,
) -> bool:
    try:
        provider = CodexCliProvider(
            executable,
            expected_sha256=expected_sha256,
        )
    except ProviderError:
        return False
    with tempfile.TemporaryDirectory(prefix="phase5r-auth-check-") as directory:
        try:
            provider.revalidate_executable()
        except ProviderError:
            return False
        completed = subprocess.run(
            [str(provider.executable), "login", "status"],
            cwd=directory,
            env=_sanitized_codex_environment(Path(directory)),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=15,
            check=False,
        )
    return completed.returncode == 0 and "logged in" in completed.stdout.lower()


def boundary_passes() -> bool:
    completed = subprocess.run(
        [sys.executable, str(BOUNDARY_VERIFIER)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
        check=False,
    )
    return completed.returncode == 0 and "llm_shadow_boundary=passed" in completed.stdout


def provider_replay_status(
    *,
    registry_path: Path = REGISTRY_PATH,
    corpus_manifest_path: Path = CORPUS_MANIFEST_PATH,
    provider_report_path: Path = PROVIDER_REPORT_PATH,
) -> dict[str, Any]:
    """Run the read-only provider quality gate against the evaluated registry."""

    return verify_provider_replay_gate(
        manifest_path=corpus_manifest_path,
        provider_report_path=provider_report_path,
        model_registry_path=registry_path,
    )


def _read_registry_snapshot(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("model registry must be a non-symlink regular file")
    raw = path.read_bytes()
    try:
        registry = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("model registry is unreadable") from exc
    if not isinstance(registry, dict):
        raise RuntimeError("model registry must be a JSON object")
    return registry, raw


def _existing_receipt_bytes(path: Path) -> bytes | None:
    if path.is_symlink():
        raise RuntimeError("activation receipt must not be a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError("activation receipt must be a regular file")
    return path.read_bytes()


def _restore_activation_files(
    *,
    registry_path: Path,
    registry_raw: bytes,
    receipt_path: Path,
    receipt_raw: bytes | None,
) -> None:
    atomic_write_text(registry_path, registry_raw.decode("utf-8"))
    if receipt_raw is None:
        if receipt_path.is_symlink():
            raise RuntimeError("cannot rollback a symlink activation receipt")
        receipt_path.unlink(missing_ok=True)
    else:
        atomic_write_text(receipt_path, receipt_raw.decode("utf-8"))


def activate_live_shadow(
    *,
    registry_path: Path = REGISTRY_PATH,
    receipt_path: Path = ACTIVATION_RECEIPT_PATH,
    corpus_manifest_path: Path = CORPUS_MANIFEST_PATH,
    provider_report_path: Path = PROVIDER_REPORT_PATH,
    boundary_checker: Callable[[], bool] = boundary_passes,
    auth_checker: Callable[[Path, str], bool] = external_auth_status,
    gate_verifier: Callable[..., dict[str, Any]] = verify_provider_replay_gate,
    receipt_verifier: Callable[..., dict[str, Any]] = (
        verify_active_activation_receipt
    ),
    json_writer: Callable[[Path, Any], None] = atomic_write_json,
) -> dict[str, Any]:
    """Activate live shadow transactionally after all read-only gates pass."""

    registry, original_registry_raw = _read_registry_snapshot(registry_path)
    original_receipt_raw = _existing_receipt_bytes(receipt_path)
    if (
        registry.get("mode") != "offline_fixture"
        or registry.get("live_shadow_enabled") is not False
    ):
        raise RuntimeError("live-shadow activation requires a disabled registry")

    initial_gate = gate_verifier(
        manifest_path=corpus_manifest_path,
        provider_report_path=provider_report_path,
        model_registry_path=registry_path,
    )
    if initial_gate.get("passed") is not True:
        raise RuntimeError("provider replay quality gate did not pass")
    if not boundary_checker():
        raise RuntimeError("offline shadow boundary verification did not pass")
    executable = Path(str(registry["provider_executable"]))
    if not auth_checker(
        executable,
        str(registry["provider_executable_sha256"]),
    ):
        raise RuntimeError("external Codex CLI authentication is not ready")

    # Authentication and boundary checks can take time.  Re-run the offline
    # provider gate immediately before mutation and require unchanged registry
    # bytes so the receipt binds the exact evaluated state.
    final_gate = gate_verifier(
        manifest_path=corpus_manifest_path,
        provider_report_path=provider_report_path,
        model_registry_path=registry_path,
    )
    if final_gate.get("passed") is not True:
        raise RuntimeError("provider replay quality gate changed before activation")
    current_registry, current_registry_raw = _read_registry_snapshot(registry_path)
    if (
        current_registry != registry
        or current_registry_raw != original_registry_raw
    ):
        raise RuntimeError("model registry changed during activation checks")
    receipt, target_registry = build_activation_receipt(
        evaluated_registry=registry,
        evaluated_registry_raw=original_registry_raw,
        corpus_manifest_path=corpus_manifest_path,
        provider_report_path=provider_report_path,
        activated_at=iso_now(),
        provider_gate_result=final_gate,
    )

    mutation_started = False
    try:
        mutation_started = True
        json_writer(registry_path, target_registry)
        json_writer(receipt_path, receipt)
        postcheck = receipt_verifier(
            registry_path=registry_path,
            receipt_path=receipt_path,
            corpus_manifest_path=corpus_manifest_path,
            provider_report_path=provider_report_path,
        )
        if postcheck.get("passed") is not True:
            raise RuntimeError("active activation receipt postcheck failed")
    except Exception:
        if mutation_started:
            _restore_activation_files(
                registry_path=registry_path,
                registry_raw=original_registry_raw,
                receipt_path=receipt_path,
                receipt_raw=original_receipt_raw,
            )
        raise
    return {
        "registry": target_registry,
        "receipt": receipt,
        "postcheck": postcheck,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--enable", action="store_true")
    parser.add_argument(
        "--acknowledge-external-inference",
        action="store_true",
        help="required with --enable; no provider credential is read or stored",
    )
    parser.add_argument(
        "--corpus-manifest",
        type=Path,
        default=CORPUS_MANIFEST_PATH,
    )
    parser.add_argument(
        "--provider-report",
        type=Path,
        default=PROVIDER_REPORT_PATH,
    )
    args = parser.parse_args()
    registry = load_registry()
    executable = Path(registry["provider_executable"])
    boundary_ready = boundary_passes()
    active_mode = (
        registry["mode"] == "shadow"
        and registry["live_shadow_enabled"] is True
    )
    if active_mode:
        replay_result = verify_active_activation_receipt(
            registry_path=REGISTRY_PATH,
            receipt_path=ACTIVATION_RECEIPT_PATH,
            corpus_manifest_path=args.corpus_manifest,
            provider_report_path=args.provider_report,
        )
    else:
        replay_result = provider_replay_status(
            registry_path=REGISTRY_PATH,
            corpus_manifest_path=args.corpus_manifest,
            provider_report_path=args.provider_report,
        )
    replay_ready = replay_result.get("passed") is True
    replay_cases = int(replay_result.get("packet_count", 0) or 0)
    transition_cases = int(
        replay_result.get("material_transition_count", 0) or 0
    )
    auth_ready = (
        external_auth_status(
            executable,
            registry["provider_executable_sha256"],
        )
        if boundary_ready and replay_ready
        else False
    )
    if args.check:
        print(
            f"live_shadow_enable_check={'passed' if auth_ready and boundary_ready and replay_ready else 'failed'} "
            f"external_auth_ready={str(auth_ready).lower()} "
            f"boundary_verification_passed={str(boundary_ready).lower()} "
            f"offline_replay_ready={str(replay_ready).lower()} "
            f"replay_cases={replay_cases} transition_cases={transition_cases} "
            f"currently_enabled={str(registry['live_shadow_enabled']).lower()} "
            "provider_invoked=false credential_read=false email_attempted=false"
        )
        return 0 if auth_ready and boundary_ready and replay_ready else 1
    if not args.acknowledge_external_inference:
        raise ValueError("--acknowledge-external-inference is required")
    if active_mode:
        if not replay_ready:
            raise RuntimeError("active activation receipt is invalid")
        print(
            "live_shadow_enabled=true already_enabled=true "
            "activation_receipt_verified=true scheduler_installed=false "
            "provider_invoked=false credential_read=false canonical_effect=false "
            "email_attempted=false broker_connected=false order_code_created=false"
        )
        return 0
    if not auth_ready:
        raise RuntimeError("external Codex CLI authentication is not ready")
    if not boundary_ready:
        raise RuntimeError("offline shadow boundary verification did not pass")
    if not replay_ready:
        raise RuntimeError(
            "offline replay corpus has not met the pre-shadow policy gate"
        )
    activate_live_shadow(
        registry_path=REGISTRY_PATH,
        receipt_path=ACTIVATION_RECEIPT_PATH,
        corpus_manifest_path=args.corpus_manifest,
        provider_report_path=args.provider_report,
    )
    print(
        "live_shadow_enabled=true activation_receipt_written=true "
        "activation_receipt_verified=true scheduler_installed=false "
        "provider_invoked=false credential_read=false canonical_effect=false "
        "email_attempted=false broker_connected=false order_code_created=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
