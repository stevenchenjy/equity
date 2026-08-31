#!/bin/zsh
set -euo pipefail

D3_LABEL="com.steven.phase5r.weeklycatchup"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
ACTIVE_STATE="${PROJECT_ROOT}/00_project_control/active_decision_state.yaml"
C6_COMPOSER="${PROJECT_ROOT}/09_scripts/phase5r/create_phase5r_c6_weekly_email_brief.py"
C6_STATUS="${PROJECT_ROOT}/07_automation/email_delivery/phase5r_c6_delivery_status.csv"
C7_PIPELINE="${PROJECT_ROOT}/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py"
D3_STATE="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_catchup_state.local.json"
D3_LOCK="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_catchup.lock"
RECOVERY_LOG="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3g_recovery_log.csv"
DOMAIN="gui/$(/usr/bin/id -u)"

TARGET_CYCLE=""
CHECK_ONLY="no"
while (( $# > 0 )); do
    case "$1" in
        --cycle-id)
            if (( $# < 2 )); then
                print -u2 "--cycle-id requires YYYY-Www"
                exit 2
            fi
            TARGET_CYCLE="$2"
            shift 2
            ;;
        --check-only)
            CHECK_ONLY="yes"
            shift
            ;;
        *)
            print -u2 "Unsupported argument: $1"
            exit 2
            ;;
    esac
done

CURRENT_CYCLE=$("${PYTHON_BIN}" - <<'PY'
from datetime import datetime
year, week, _ = datetime.now().astimezone().date().isocalendar()
print(f"{year}-W{week:02d}")
PY
)
if [[ -z "${TARGET_CYCLE}" ]]; then
    TARGET_CYCLE="${CURRENT_CYCLE}"
fi
if ! "${PYTHON_BIN}" - "${TARGET_CYCLE}" <<'PY'
import re
import sys
raise SystemExit(0 if re.fullmatch(r"20\d{2}-W(?:0[1-9]|[1-4]\d|5[0-3])", sys.argv[1]) else 1)
PY
then
    print -u2 "Cycle ID must use YYYY-Www"
    exit 2
fi

active_workflow=""
active_pipeline=""
d3_loaded="no"
successful_send_exists="unknown"
c6_validation="not_run"
failed_attempt_present="unknown"
recovery_count_before="0"
recovery_count_after="0"
attempt_guard_cleared="no"

function append_recovery_log {
    local result_state="$1"
    local result_reason="$2"
    local action_name="check_failed_cycle_recovery"
    if [[ "${CHECK_ONLY}" != "yes" ]]; then
        action_name="reset_failed_cycle_after_fix"
    fi
    "${PYTHON_BIN}" - "${RECOVERY_LOG}" "${action_name}" "${CHECK_ONLY}" "${TARGET_CYCLE}" "${CURRENT_CYCLE}" "${active_workflow}" "${active_pipeline}" "${d3_loaded}" "${successful_send_exists}" "${c6_validation}" "${failed_attempt_present}" "${recovery_count_before}" "${recovery_count_after}" "${attempt_guard_cleared}" "${result_state}" "${result_reason}" <<'PY'
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

(
    log_name,
    action_name,
    check_only,
    target_cycle,
    current_cycle,
    active_workflow,
    active_pipeline,
    d3_loaded,
    successful_send_exists,
    c6_validation,
    failed_attempt_present,
    recovery_count_before,
    recovery_count_after,
    attempt_guard_cleared,
    result_state,
    result_reason,
) = sys.argv[1:]
fields = [
    "timestamp",
    "phase",
    "action",
    "mode",
    "target_cycle",
    "current_cycle",
    "active_workflow",
    "active_pipeline",
    "d3_loaded",
    "successful_send_exists",
    "c6_validation",
    "failed_attempt_present",
    "recovery_count_before",
    "recovery_count_after",
    "attempt_guard_cleared",
    "c7_invoked",
    "email_sent",
    "status",
    "reason",
    "safety_notes",
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
            "phase": "phase5r_d3g",
            "action": action_name,
            "mode": "check_only" if check_only == "yes" else "reset",
            "target_cycle": target_cycle,
            "current_cycle": current_cycle,
            "active_workflow": active_workflow,
            "active_pipeline": active_pipeline,
            "d3_loaded": d3_loaded,
            "successful_send_exists": successful_send_exists,
            "c6_validation": c6_validation,
            "failed_attempt_present": failed_attempt_present,
            "recovery_count_before": recovery_count_before,
            "recovery_count_after": recovery_count_after,
            "attempt_guard_cleared": attempt_guard_cleared,
            "c7_invoked": "no",
            "email_sent": "no",
            "status": result_state,
            "reason": result_reason,
            "safety_notes": "manual_recovery_only=yes; c6_compose_validation_only=yes; successful_send_guard_preserved=yes",
        }
    )
PY
}

function refuse_reset {
    local refusal_reason="$1"
    append_recovery_log "refused" "${refusal_reason}"
    print -u2 "Phase 5R-D3G recovery refused: ${refusal_reason}"
    exit 3
}

for required_file in "${PYTHON_BIN}" "${ACTIVE_STATE}" "${C6_COMPOSER}" "${C6_STATUS}" "${C7_PIPELINE}" "${D3_STATE}"; do
    if [[ ! -e "${required_file}" ]]; then
        refuse_reset "required_input_missing"
    fi
done

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
) || refuse_reset "active_state_not_authorized"
active_workflow="${state_identity%%|*}"
active_pipeline="${state_identity#*|}"

if /bin/launchctl print "${DOMAIN}/${D3_LABEL}" >/dev/null 2>&1; then
    d3_loaded="yes"
else
    refuse_reset "d3_scheduler_not_loaded"
fi

successful_send_exists=$("${PYTHON_BIN}" - "${C6_STATUS}" "${TARGET_CYCLE}" <<'PY'
import csv
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

status_file = Path(sys.argv[1])
cycle_id = sys.argv[2]
year_text, week_text = cycle_id.split("-W")
year, week = int(year_text), int(week_text)
monday = date.fromisocalendar(year, week, 1)
due = datetime.combine(monday + timedelta(days=3), time(9, 5)).astimezone()
found = False
with status_file.open(newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        if row.get("sent", "").strip().lower() != "yes":
            continue
        raw = row.get("timestamp", "").strip().replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            raise SystemExit(2)
        if stamp.tzinfo is None:
            stamp = stamp.astimezone()
        stamp = stamp.astimezone()
        row_year, row_week, _ = stamp.date().isocalendar()
        if (row_year, row_week) == (year, week) and stamp >= due:
            found = True
            break
print("yes" if found else "no")
PY
) || refuse_reset "c6_delivery_status_invalid"
if [[ "${successful_send_exists}" == "yes" ]]; then
    refuse_reset "successful_c6_send_already_exists_for_cycle"
fi
if [[ "${TARGET_CYCLE}" != "${CURRENT_CYCLE}" ]]; then
    refuse_reset "only_current_cycle_can_be_reset"
fi

attempt_summary=$("${PYTHON_BIN}" - "${D3_STATE}" "${TARGET_CYCLE}" <<'PY'
import json
import sys
from pathlib import Path

state_file = Path(sys.argv[1])
cycle_id = sys.argv[2]
state = json.loads(state_file.read_text(encoding="utf-8"))
attempts = state.get("cycle_attempts", {})
history = state.get("cycle_recovery_history", [])
if not isinstance(attempts, dict) or not isinstance(history, list):
    raise SystemExit(1)
attempt = attempts.get(cycle_id)
failed = isinstance(attempt, dict) and attempt.get("outcome") == "catchup_failed"
recovery_count = sum(item.get("cycle_id") == cycle_id for item in history if isinstance(item, dict))
print(("yes" if failed else "no") + "|" + str(recovery_count))
PY
) || refuse_reset "d3_state_invalid"
failed_attempt_present="${attempt_summary%%|*}"
recovery_count_before="${attempt_summary#*|}"
recovery_count_after="${recovery_count_before}"
if [[ "${failed_attempt_present}" != "yes" ]]; then
    refuse_reset "current_cycle_has_no_failed_attempt_guard"
fi
if (( recovery_count_before >= 1 )); then
    refuse_reset "current_cycle_manual_retry_already_used"
fi

if "${PYTHON_BIN}" "${C6_COMPOSER}" >/dev/null 2>&1; then
    c6_validation="passed"
else
    c6_validation="failed"
    refuse_reset "c6_composer_validation_failed"
fi

if [[ "${CHECK_ONLY}" == "yes" ]]; then
    append_recovery_log "complete" "eligible_for_one_manual_recovery_reset"
    print "Phase 5R-D3G recovery check passed for ${TARGET_CYCLE}; guard was not cleared."
    print "C6 composition passed; C7 was not invoked and no email was sent."
    exit 0
fi

if ! "${PYTHON_BIN}" - "${D3_STATE}" "${D3_LOCK}" "${C6_STATUS}" "${TARGET_CYCLE}" <<'PY'
import csv
import fcntl
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

state_file = Path(sys.argv[1])
lock_file = Path(sys.argv[2])
status_file = Path(sys.argv[3])
cycle_id = sys.argv[4]
year_text, week_text = cycle_id.split("-W")
year, week = int(year_text), int(week_text)
monday = date.fromisocalendar(year, week, 1)
due = datetime.combine(monday + timedelta(days=3), time(9, 5)).astimezone()

lock_file.parent.mkdir(parents=True, exist_ok=True)
with lock_file.open("a+", encoding="utf-8") as lock_handle:
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit(2)
    with status_file.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("sent", "").strip().lower() != "yes":
                continue
            raw = row.get("timestamp", "").strip().replace("Z", "+00:00")
            stamp = datetime.fromisoformat(raw)
            if stamp.tzinfo is None:
                stamp = stamp.astimezone()
            stamp = stamp.astimezone()
            row_year, row_week, _ = stamp.date().isocalendar()
            if (row_year, row_week) == (year, week) and stamp >= due:
                raise SystemExit(3)
    state = json.loads(state_file.read_text(encoding="utf-8"))
    attempts = state.get("cycle_attempts", {})
    history = state.setdefault("cycle_recovery_history", [])
    if not isinstance(attempts, dict) or not isinstance(history, list):
        raise SystemExit(4)
    attempt = attempts.get(cycle_id)
    if not isinstance(attempt, dict) or attempt.get("outcome") != "catchup_failed":
        raise SystemExit(5)
    if any(item.get("cycle_id") == cycle_id for item in history if isinstance(item, dict)):
        raise SystemExit(6)
    history.append(
        {
            "cycle_id": cycle_id,
            "reset_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "reason": "composer_fix_validated_manual_retry_authorized",
            "cleared_attempt": attempt,
        }
    )
    del attempts[cycle_id]
    temporary = state_file.with_name(state_file.name + ".d3g.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, state_file)
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
PY
then
    refuse_reset "failed_attempt_guard_clear_was_refused"
fi

attempt_guard_cleared="yes"
recovery_count_after=$(( recovery_count_before + 1 ))
append_recovery_log "complete" "one_manual_retry_authorized_for_current_cycle"
print "Phase 5R-D3G cleared the failed-attempt guard for ${TARGET_CYCLE}."
print "C7 was not invoked and no email was sent; the next D3 check may retry once."
