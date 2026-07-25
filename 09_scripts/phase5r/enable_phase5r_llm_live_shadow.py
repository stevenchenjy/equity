#!/usr/bin/env python3
"""Explicitly transition the isolated model layer from fixtures to live shadow.

This transition does not install a scheduler, invoke a model, change a canonical
decision, or enable email/execution.  It exists so external inference can never
be activated accidentally by an ordinary refresh or install command.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from phase5r_daily_common import ROOT, atomic_write_json
from run_phase5r_llm_shadow import REGISTRY_PATH, load_registry


BOUNDARY_VERIFIER = (
    ROOT / "09_scripts" / "phase5r" / "verify_phase5r_llm_shadow_boundary.py"
)


def external_auth_status(executable: Path) -> bool:
    if not executable.exists():
        return False
    completed = subprocess.run(
        [str(executable), "login", "status"],
        cwd=ROOT,
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
    args = parser.parse_args()
    registry = load_registry()
    executable = Path(registry["provider_executable"])
    auth_ready = external_auth_status(executable)
    boundary_ready = boundary_passes()
    if args.check:
        print(
            f"live_shadow_enable_check={'passed' if auth_ready and boundary_ready else 'failed'} "
            f"external_auth_ready={str(auth_ready).lower()} "
            f"boundary_verification_passed={str(boundary_ready).lower()} "
            f"currently_enabled={str(registry['live_shadow_enabled']).lower()} "
            "provider_invoked=false credential_read=false email_attempted=false"
        )
        return 0 if auth_ready and boundary_ready else 1
    if not args.acknowledge_external_inference:
        raise ValueError("--acknowledge-external-inference is required")
    if not auth_ready:
        raise RuntimeError("external Codex CLI authentication is not ready")
    if not boundary_ready:
        raise RuntimeError("offline shadow boundary verification did not pass")
    updated = dict(registry)
    updated["mode"] = "shadow"
    updated["live_shadow_enabled"] = True
    updated["canonical_influence_enabled"] = False
    updated["automatic_action_allowed"] = False
    updated["email_eligible"] = False
    atomic_write_json(REGISTRY_PATH, updated)
    print(
        "live_shadow_enabled=true scheduler_installed=false "
        "provider_invoked=false credential_read=false canonical_effect=false "
        "email_attempted=false broker_connected=false order_code_created=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
