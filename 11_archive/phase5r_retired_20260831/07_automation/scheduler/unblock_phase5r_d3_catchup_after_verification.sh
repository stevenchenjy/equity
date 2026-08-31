#!/bin/zsh
set -euo pipefail

D2_LABEL="com.steven.phase5r.weeklyconviction"
D3_LABEL="com.steven.phase5r.weeklycatchup"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
ACTIVE_STATE="${PROJECT_ROOT}/00_project_control/active_decision_state.yaml"
C7_PIPELINE="${PROJECT_ROOT}/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py"
D3_WRAPPER="${PROJECT_ROOT}/09_scripts/phase5r/run_phase5r_d3_weekly_catchup.py"
LOCAL_STATE="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_catchup_state.local.json"
ALTERNATE_LOCAL_STATE="${PROJECT_ROOT}/07_automation/scheduler/phase5r_d3_catchup_state.local.json"
INSTALL_INHIBIT="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_install_inhibit"
D3F_VERIFICATION_INHIBIT="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3f_verification_inhibit"
D3F_LOG="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3f_hotfix_log.csv"
SMTP_CONFIG="${PROJECT_ROOT}/07_automation/email_delivery/phase5r_email_config.local.json"
D3_INSTALLED_PLIST="${HOME}/Library/LaunchAgents/${D3_LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"

RUN_MODE="unblock"
PRESERVE_VERIFICATION_HOLD="no"
for argument in "$@"; do
    case "${argument}" in
        --check-only)
            RUN_MODE="check_only"
            ;;
        --preserve-verification-hold)
            PRESERVE_VERIFICATION_HOLD="yes"
            ;;
        *)
            print -u2 "Unsupported argument: ${argument}"
            exit 2
            ;;
    esac
done

active_workflow=""
active_pipeline=""
d2_loaded="unknown"
d3_loaded="unknown"
d3_plist_present="no"
c7_present="no"
install_inhibit_before="no"
install_inhibit_after="no"
state_flags_before=""
state_flags_after=""

function append_d3f_log {
    local result_state="$1"
    local action_name="$2"
    local detail_notes="$3"
    "${PYTHON_BIN}" - "${D3F_LOG}" "${action_name}" "${RUN_MODE}" "${active_workflow}" "${active_pipeline}" "${d2_loaded}" "${d3_loaded}" "${d3_plist_present}" "${c7_present}" "${install_inhibit_before}" "${install_inhibit_after}" "${state_flags_before}" "${state_flags_after}" "${PRESERVE_VERIFICATION_HOLD}" "${result_state}" "${detail_notes}" <<'PY'
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    log_name,
    action_name,
    run_mode,
    active_workflow,
    active_pipeline,
    d2_loaded,
    d3_loaded,
    d3_plist_present,
    c7_present,
    install_inhibit_before,
    install_inhibit_after,
    state_flags_before,
    state_flags_after,
    hold_preserved,
    result_state,
    detail_notes,
) = sys.argv[1:]
fields = [
    "timestamp",
    "phase",
    "action",
    "mode",
    "active_workflow",
    "active_pipeline",
    "d2_loaded",
    "d3_loaded",
    "d3_plist_present",
    "c7_present",
    "install_inhibit_before",
    "install_inhibit_after",
    "state_flags_before",
    "state_flags_after",
    "verification_hold_preserved",
    "c7_invoked",
    "email_sent",
    "smtp_config_modified",
    "status",
    "notes",
]
log_file = Path(log_name)
log_file.parent.mkdir(parents=True, exist_ok=True)
exists = log_file.exists() and log_file.stat().st_size > 0
with log_file.open("a", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fields)
    if not exists:
        writer.writeheader()
    writer.writerow(
        {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "phase": "phase5r_d3f",
            "action": action_name,
            "mode": run_mode,
            "active_workflow": active_workflow,
            "active_pipeline": active_pipeline,
            "d2_loaded": d2_loaded,
            "d3_loaded": d3_loaded,
            "d3_plist_present": d3_plist_present,
            "c7_present": c7_present,
            "install_inhibit_before": install_inhibit_before,
            "install_inhibit_after": install_inhibit_after,
            "state_flags_before": state_flags_before,
            "state_flags_after": state_flags_after,
            "verification_hold_preserved": hold_preserved,
            "c7_invoked": "no",
            "email_sent": "no",
            "smtp_config_modified": "no",
            "status": result_state,
            "notes": detail_notes,
        }
    )
PY
}

function fail_unblock {
    local failure_reason="$1"
    append_d3f_log "failed" "unblock_preflight" "${failure_reason}"
    print -u2 "Phase 5R-D3F unblock failed: ${failure_reason}"
    exit 1
}

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    fail_unblock "macos_launchd_required"
fi
for required_file in "${PYTHON_BIN}" "${ACTIVE_STATE}" "${C7_PIPELINE}" "${D3_WRAPPER}" "${LOCAL_STATE}"; do
    if [[ ! -e "${required_file}" ]]; then
        fail_unblock "required_file_missing"
    fi
done
c7_present="yes"

state_identity=$("${PYTHON_BIN}" - "${ACTIVE_STATE}" <<'PY'
import json
import pathlib
import sys

state_file = pathlib.Path(sys.argv[1])
state = json.loads(state_file.read_text(encoding="utf-8"))
expected = {
    "current_workflow": "weekly_conviction",
    "active_pipeline": "phase5r_c7",
    "email_delivery_allowed_from": "phase5r_c7_only",
    "broker_connection_allowed": "no",
    "order_code_allowed": "no",
    "manual_execution_only": "yes",
}
if not isinstance(state, dict) or any(state.get(key) != value for key, value in expected.items()):
    raise SystemExit(1)
print(str(state.get("current_workflow", "")) + "|" + str(state.get("active_pipeline", "")))
PY
) || fail_unblock "active_state_not_authorized"
active_workflow="${state_identity%%|*}"
active_pipeline="${state_identity#*|}"

if /bin/launchctl print "${DOMAIN}/${D2_LABEL}" >/dev/null 2>&1; then
    d2_loaded="yes"
    fail_unblock "d2_must_be_unloaded"
else
    d2_loaded="no"
fi
if /bin/launchctl print "${DOMAIN}/${D3_LABEL}" >/dev/null 2>&1; then
    d3_loaded="yes"
else
    d3_loaded="no"
    fail_unblock "d3_must_be_loaded"
fi

if [[ -f "${D3_INSTALLED_PLIST}" ]]; then
    d3_plist_present="yes"
else
    fail_unblock "d3_installed_plist_missing"
fi
if ! "${PYTHON_BIN}" - "${D3_INSTALLED_PLIST}" "${PYTHON_BIN}" "${D3_WRAPPER}" <<'PY'
import plistlib
import sys
from pathlib import Path

installed_file, python_name, wrapper_name = sys.argv[1:]
with Path(installed_file).open("rb") as handle:
    config = plistlib.load(handle)
expected = [python_name, wrapper_name]
raise SystemExit(0 if config.get("ProgramArguments") == expected else 1)
PY
then
    fail_unblock "d3_plist_program_arguments_invalid"
fi

if [[ -e "${INSTALL_INHIBIT}" ]]; then
    install_inhibit_before="yes"
fi
smtp_metadata_before=$(/usr/bin/stat -f '%z:%m:%c' "${SMTP_CONFIG}" 2>/dev/null || print "absent")

state_operation="inspect"
if [[ "${RUN_MODE}" == "unblock" ]]; then
    state_operation="clear"
fi
state_change=$("${PYTHON_BIN}" - "${state_operation}" "${LOCAL_STATE}" "${ALTERNATE_LOCAL_STATE}" <<'PY'
import json
import os
import sys
from pathlib import Path

operation = sys.argv[1]
state_files = [Path(item) for item in sys.argv[2:] if Path(item).exists()]
if not state_files:
    raise SystemExit(1)
flag_names = ("verification_flag_active", "install_inhibit", "protected_verification")
before = set()
after = set()
for state_file in state_files:
    state = json.loads(state_file.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != "phase5r_d3_catchup_state_v1":
        raise SystemExit(1)
    before.update(key for key in flag_names if state.get(key) is True)
    if operation == "clear":
        for key in flag_names:
            state.pop(key, None)
        temporary = state_file.with_name(state_file.name + ".d3f.tmp")
        temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, state_file)
    after.update(key for key in flag_names if state.get(key) is True)
print(";".join(sorted(before)) + "|" + ";".join(sorted(after)))
PY
) || fail_unblock "d3_local_state_invalid"
state_flags_before="${state_change%%|*}"
state_flags_after="${state_change#*|}"

if [[ "${RUN_MODE}" == "unblock" ]]; then
    if [[ -e "${INSTALL_INHIBIT}" ]]; then
        /bin/rm "${INSTALL_INHIBIT}"
    fi
    if [[ "${PRESERVE_VERIFICATION_HOLD}" != "yes" && -e "${D3F_VERIFICATION_INHIBIT}" ]]; then
        /bin/rm "${D3F_VERIFICATION_INHIBIT}"
    fi
fi
if [[ -e "${INSTALL_INHIBIT}" ]]; then
    install_inhibit_after="yes"
fi

smtp_metadata_after=$(/usr/bin/stat -f '%z:%m:%c' "${SMTP_CONFIG}" 2>/dev/null || print "absent")
if [[ "${smtp_metadata_before}" != "${smtp_metadata_after}" ]]; then
    fail_unblock "smtp_config_metadata_changed"
fi
if ! /bin/launchctl print "${DOMAIN}/${D3_LABEL}" >/dev/null 2>&1; then
    fail_unblock "d3_not_loaded_after_unblock"
fi
if /bin/launchctl print "${DOMAIN}/${D2_LABEL}" >/dev/null 2>&1; then
    fail_unblock "d2_loaded_during_unblock"
fi

if [[ "${RUN_MODE}" == "check_only" ]]; then
    append_d3f_log "complete" "safe_unblock_check" "preconditions_validated; no_protection_state_changed"
    print "Phase 5R-D3F safe check passed. No inhibit or state flag was changed; C7 was not invoked."
else
    append_d3f_log "complete" "clear_verification_inhibit" "legacy_protection_cleared; c7_not_invoked; email_not_sent"
    print "Phase 5R-D3F unblock completed. D3 remains loaded and D2 remains unloaded."
    print "C7 was not invoked and no email was sent by this command."
fi
