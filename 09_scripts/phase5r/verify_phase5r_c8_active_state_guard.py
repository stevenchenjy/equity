#!/usr/bin/env python3
"""Read-only verifier for the one canonical Phase 5R daily workflow.

The verifier never invokes a pipeline, sender, installer, scheduler kickstart,
provider, or broker surface.  It never opens SMTP configuration content.
Historical weekly files may exist, but no canonical runtime source, active
input registry row, launchd job, or state field may authorize them.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import plistlib
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
CONTROL_DIR = ROOT / "00_project_control"
SCHEDULER_DIR = ROOT / "07_automation" / "scheduler"
SCRIPT_DIR = ROOT / "09_scripts" / "phase5r"
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
LAUNCH_DOMAIN = f"gui/{os.getuid()}"
PRODUCTION_RUNTIME_ROOT = Path("/Users/messssi/LocalRuntime/equity")
PRODUCTION_RUNTIME_WRAPPER = (
    PRODUCTION_RUNTIME_ROOT
    / "09_scripts"
    / "phase5r"
    / "run_phase5r_runtime_scheduler.py"
)

STATE_PATH = CONTROL_DIR / "active_decision_state.yaml"
INHIBIT_PATH = (
    SCHEDULER_DIR / "phase5r_c9_maintenance_inhibit.local.json"
)
ALLOWED_PATH = CONTROL_DIR / "phase5r_c8_allowed_active_inputs.csv"
DEPRECATED_PATH = CONTROL_DIR / "phase5r_c8_deprecated_workflows.csv"
STALE_REPORT_PATH = (
    CONTROL_DIR / "phase5r_c8_stale_file_guard_report.csv"
)
POLICY_PATH = CONTROL_DIR / "phase5r_c8_active_state_policy.md"
MODEL_REGISTRY_PATH = (
    CONTROL_DIR / "phase5r_llm_model_registry.json"
)
SMTP_CONFIG_PATH = (
    ROOT
    / "07_automation"
    / "email_delivery"
    / "phase5r_email_config.local.json"
)

ACTIVE_JOBS = {
    "com.steven.phase5r.dailyrefresh": "dailyrefresh",
    "com.steven.phase5r.dailydecision": "dailydecision",
}
RETIRED_JOBS = (
    "com.steven.phase5r.dailybrief",
    "com.steven.phase5r.weeklyconviction",
    "com.steven.phase5r.weeklycatchup",
)
SHADOW_JOB = "com.steven.phase5r.llmshadow"
CANONICAL_RUNTIME_FILES = (
    "phase5r_daily_common.py",
    "run_phase5r_daily_refresh.py",
    "run_phase5r_daily_decision_pipeline.py",
    "run_phase5r_daily_refresh_scheduler.py",
    "run_phase5r_daily_scheduler.py",
    "run_phase5r_runtime_scheduler.py",
    "create_phase5r_daily_decision_and_brief.py",
    "send_phase5r_daily_email.py",
)
FORBIDDEN_CANONICAL_MARKERS = (
    "weekly_conviction",
    "weeklyconviction",
    "weeklycatchup",
    "phase5r_c1",
    "phase5r_c2",
    "phase5r_c3",
    "phase5r_c5",
    "phase5r_c6",
    "phase5r_c7",
    "send_phase5r_c",
)
EXPECTED_STATE = {
    "current_workflow": "daily_decision",
    "active_pipeline": "phase5r_daily",
    "primary_decision": "daily_account_aware_decision",
    "email_delivery_allowed_from": "phase5r_daily_only",
    "active_research_phase": "phase5r_daily",
    "active_action_planner": "phase5r_c9_account_aware",
    "active_email_brief": "phase5r_daily",
    "active_state_guard": "phase5r_daily",
    "d1_scheduler_status": "retired_unloaded",
    "d2_scheduler_status": "retired_unloaded",
    "d3_scheduler_status": "retired_unloaded",
    "archived_folders_allowed_as_input": "no",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
    "llm_shadow_canonical_influence": "disabled",
    "llm_shadow_scheduler_status": "legacy_standalone_not_installed",
    "production_shadow_status": "authorized_noncanonical_companion_pending_fresh_deterministic_refresh",
    "production_shadow_scheduler_status": "dailyrefresh_child_no_standalone_launchagent",
    "production_shadow_canonical_influence": "disabled",
    "production_shadow_email_status": "no_normal_llm_email_first_fully_valid_noncanonical_report_only",
}


@dataclass(frozen=True, slots=True)
class Check:
    check_id: str
    passed: bool
    detail: str


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _loaded(label: str) -> bool:
    return (
        subprocess.run(
            [
                "/bin/launchctl",
                "print",
                f"{LAUNCH_DOMAIN}/{label}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def _smtp_stat() -> tuple[int, int, int] | str:
    try:
        metadata = SMTP_CONFIG_PATH.stat()
    except FileNotFoundError:
        return "absent"
    return (
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _registry_paths(
    rows: list[dict[str, str]],
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    forbidden: list[str] = []
    for row in rows:
        path_spec = row.get("path_spec", "")
        path_kind = row.get("path_kind", "")
        if row.get("allowed_as_active_input") != "yes":
            forbidden.append(
                f"{row.get('registry_id', '')}:not_explicitly_allowed"
            )
        lowered = path_spec.lower()
        if (
            "11_archive" in lowered
            or any(
                marker in lowered
                for marker in (
                    "phase5r_c5",
                    "phase5r_c6",
                    "phase5r_c7",
                    "weekly",
                )
            )
        ):
            forbidden.append(
                f"{row.get('registry_id', '')}:{path_spec}"
            )
        if path_kind == "exact":
            if not (ROOT / path_spec).is_file():
                missing.append(path_spec)
        elif path_kind == "pattern":
            if not any(path.is_file() for path in ROOT.glob(path_spec)):
                missing.append(path_spec)
        else:
            forbidden.append(
                f"{row.get('registry_id', '')}:invalid_path_kind"
            )
    return missing, forbidden


def _deprecated_registry_issues(
    rows: list[dict[str, str]],
) -> list[str]:
    issues: list[str] = []
    required_ids = {f"DW-{index:03d}" for index in range(1, 12)}
    by_id = {row.get("workflow_id", ""): row for row in rows}
    if set(by_id) != required_ids:
        issues.append("closed_workflow_id_set_mismatch")
    for workflow_id, row in by_id.items():
        if (
            row.get("active_input_allowed") != "no"
            or row.get("email_send_allowed") != "no"
            or row.get("scheduler_allowed") != "no"
            or row.get("status")
            not in {
                "retired",
                "retired_unloaded",
                "archived_evidence_only",
                "context_only",
                "evidence_only",
            }
        ):
            issues.append(workflow_id)
    return issues


def _canonical_source_issues() -> list[str]:
    issues: list[str] = []
    for name in CANONICAL_RUNTIME_FILES:
        path = SCRIPT_DIR / name
        if not path.is_file():
            issues.append(f"{name}:missing")
            continue
        text = path.read_text(encoding="utf-8")
        try:
            compile(text, str(path), "exec")
        except SyntaxError:
            issues.append(f"{name}:syntax")
            continue
        lowered = text.lower()
        for marker in FORBIDDEN_CANONICAL_MARKERS:
            if marker in lowered:
                issues.append(f"{name}:{marker}")
    return sorted(issues)


def _plist_issues() -> list[str]:
    issues: list[str] = []
    for label, job_name in ACTIVE_JOBS.items():
        template = SCHEDULER_DIR / f"{label}.plist.template"
        installed = LAUNCH_AGENTS / f"{label}.plist"
        if not _loaded(label):
            issues.append(f"{label}:not_loaded")
        if (
            not template.is_file()
            or not installed.is_file()
            or template.read_bytes() != installed.read_bytes()
        ):
            issues.append(f"{label}:template_mismatch")
            continue
        with template.open("rb") as handle:
            payload = plistlib.load(handle)
        arguments = payload.get("ProgramArguments", [])
        if not (
            payload.get("Label") == label
            and payload.get("RunAtLoad") is True
            and payload.get("KeepAlive") is False
            and payload.get("StartInterval") == 900
            and "StartCalendarInterval" not in payload
            and payload.get("WorkingDirectory") == str(PRODUCTION_RUNTIME_ROOT)
            and arguments
            == [
                "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3",
                str(PRODUCTION_RUNTIME_WRAPPER),
                "--job",
                job_name,
            ]
        ):
            issues.append(f"{label}:invariants")
    for label in RETIRED_JOBS:
        if _loaded(label) or (
            LAUNCH_AGENTS / f"{label}.plist"
        ).exists():
            issues.append(f"{label}:retired_job_present")
    if _loaded(SHADOW_JOB) or (
        LAUNCH_AGENTS / f"{SHADOW_JOB}.plist"
    ).exists():
        issues.append(f"{SHADOW_JOB}:prematurely_active")
    return issues


def collect_checks(*, include_runtime: bool) -> list[Check]:
    checks: list[Check] = []
    state = _read_json(STATE_PATH)
    state_mismatches = [
        f"{key}={state.get(key)!r}"
        for key, expected in EXPECTED_STATE.items()
        if state.get(key) != expected
    ]
    checks.append(
        Check(
            "active_state.daily_only",
            not state_mismatches,
            "mismatches=" + (",".join(state_mismatches) or "none"),
        )
    )

    inhibit = _read_json(INHIBIT_PATH)
    inhibit_ok = (
        inhibit.get("active") is False
        and inhibit.get("allowed_pipeline") == "phase5r_daily"
    )
    checks.append(
        Check(
            "maintenance_inhibit.daily_only",
            inhibit_ok,
            (
                f"active={inhibit.get('active')!r};"
                f"allowed_pipeline={inhibit.get('allowed_pipeline')!r}"
            ),
        )
    )

    allowed_rows = _read_csv(ALLOWED_PATH)
    missing, forbidden = _registry_paths(allowed_rows)
    checks.append(
        Check(
            "active_input_registry.daily_only",
            bool(allowed_rows) and not missing and not forbidden,
            (
                f"rows={len(allowed_rows)};missing={missing};"
                f"forbidden={forbidden}"
            ),
        )
    )

    deprecated_rows = _read_csv(DEPRECATED_PATH)
    deprecated_issues = _deprecated_registry_issues(deprecated_rows)
    checks.append(
        Check(
            "deprecated_workflows.closed",
            not deprecated_issues,
            (
                f"rows={len(deprecated_rows)};"
                f"issues={deprecated_issues}"
            ),
        )
    )

    guard_rows = _read_csv(STALE_REPORT_PATH)
    weekly_allowed = [
        row.get("check_id", "")
        for row in guard_rows
        if (
            any(
                marker in row.get("path_or_pattern", "").lower()
                for marker in ("weekly", "phase5r_c5", "phase5r_c6", "phase5r_c7")
            )
            and row.get("active_input_allowed") != "no"
        )
    ]
    archive_excluded = any(
        row.get("guard_decision") == "exclude_all"
        and "11_archive" in row.get("path_or_pattern", "")
        and row.get("active_input_allowed") == "no"
        for row in guard_rows
    )
    checks.append(
        Check(
            "stale_guard.weekly_archive_closed",
            not weekly_allowed and archive_excluded,
            (
                f"weekly_allowed={weekly_allowed};"
                f"archive_excluded={archive_excluded}"
            ),
        )
    )

    source_issues = _canonical_source_issues()
    checks.append(
        Check(
            "canonical_source.no_weekly_dependency",
            not source_issues,
            f"issues={source_issues}",
        )
    )

    registry = _read_json(MODEL_REGISTRY_PATH)
    model_disabled = (
        registry.get("mode") == "offline_fixture"
        and registry.get("live_shadow_enabled") is False
        and registry.get("canonical_influence_enabled") is False
        and registry.get("email_eligible") is False
        and registry.get("automatic_action_allowed") is False
        and registry.get("broker_connection_allowed") is False
        and registry.get("order_code_allowed") is False
    )
    checks.append(
        Check(
            "model_influence.disabled",
            model_disabled,
            (
                f"mode={registry.get('mode')!r};"
                f"live={registry.get('live_shadow_enabled')!r}"
            ),
        )
    )

    required_files = (
        POLICY_PATH,
        STATE_PATH,
        INHIBIT_PATH,
        ALLOWED_PATH,
        DEPRECATED_PATH,
        STALE_REPORT_PATH,
    )
    missing_control = [
        str(path.relative_to(ROOT))
        for path in required_files
        if not path.is_file()
    ]
    checks.append(
        Check(
            "control_files.present",
            not missing_control,
            f"missing={missing_control}",
        )
    )

    if include_runtime:
        plist_issues = _plist_issues()
        checks.append(
            Check(
                "launchd.daily_only",
                not plist_issues,
                f"issues={plist_issues}",
            )
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="skip host launchd state and verify repository state only",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    smtp_before = _smtp_stat()
    checks = collect_checks(include_runtime=not args.static_only)
    smtp_after = _smtp_stat()
    checks.append(
        Check(
            "smtp_config.not_opened_or_modified",
            smtp_before == smtp_after,
            f"metadata_unchanged={smtp_before == smtp_after}",
        )
    )
    passed = all(check.passed for check in checks)
    payload = {
        "schema_version": "phase5r_canonical_workflow_check_v1",
        "passed": passed,
        "canonical_workflow": "daily_decision",
        "canonical_pipeline": "phase5r_daily",
        "checks": [asdict(check) for check in checks],
        "boundaries": {
            "pipeline_invoked": False,
            "sender_invoked": False,
            "email_attempted": False,
            "smtp_config_read": False,
            "provider_invoked": False,
            "broker_connected": False,
            "order_code_created": False,
            "canonical_effect": False,
            "files_written": False,
        },
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        failures = [
            check.check_id for check in checks if not check.passed
        ]
        print(
            "canonical_workflow_status="
            f"{'passed' if passed else 'failed'} "
            "workflow=daily_decision pipeline=phase5r_daily "
            f"checks={len(checks)} "
            f"failures={','.join(failures) or 'none'} "
            "weekly_active=false llm_active=false "
            "email_attempted=false smtp_config_read=false "
            "provider_invoked=false broker_connected=false "
            "order_code_created=false files_written=false"
        )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
