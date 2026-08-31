#!/bin/zsh
set -euo pipefail

D2_LABEL="com.steven.phase5r.weeklyconviction"
D3_LABEL="com.steven.phase5r.weeklycatchup"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
STATE_PATH="${PROJECT_ROOT}/00_project_control/active_decision_state.yaml"
C6_STATUS="${PROJECT_ROOT}/07_automation/email_delivery/phase5r_c6_delivery_status.csv"
CATCHUP_LOG="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_catchup_check_log.csv"
LOCAL_STATE="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_catchup_state.local.json"
INSTALL_INHIBIT="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_install_inhibit"
D3F_VERIFICATION_INHIBIT="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3f_verification_inhibit"
C9_MAINTENANCE_INHIBIT="${PROJECT_ROOT}/07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json"
DOMAIN="gui/$(/usr/bin/id -u)"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    print -u2 "Phase 5R-D3 status requires macOS launchd."
    exit 1
fi

if [[ -x "${PYTHON_BIN}" ]]; then
    "${PYTHON_BIN}" - "${STATE_PATH}" "${C6_STATUS}" "${CATCHUP_LOG}" "${LOCAL_STATE}" "${INSTALL_INHIBIT}" "${D3F_VERIFICATION_INHIBIT}" "${C9_MAINTENANCE_INHIBIT}" <<'PY'
import csv
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

state_path, c6_path, catchup_path, local_state_file, install_inhibit_file, protected_file, c9_inhibit_file = map(Path, sys.argv[1:])
try:
    state = json.loads(state_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    state = {}
print("Active workflow: " + str(state.get("current_workflow", "unavailable")))
print("Active pipeline: " + str(state.get("active_pipeline", "unavailable")))

try:
    local_state = json.loads(local_state_file.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    local_state = {}
active_protections = [
    key
    for key in ("verification_flag_active", "install_inhibit", "protected_verification")
    if local_state.get(key) is True
]
if install_inhibit_file.exists():
    active_protections.append("install_inhibit_file")
if protected_file.exists():
    active_protections.append("phase5r_d3f_verification_inhibit")
if c9_inhibit_file.exists():
    try:
        c9_inhibit = json.loads(c9_inhibit_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        active_protections.append("phase5r_c9_maintenance_inhibit_invalid_fail_closed")
    else:
        if c9_inhibit.get("active") is True and c9_inhibit.get("allowed_pipeline") == "none":
            active_protections.append("phase5r_c9_maintenance_inhibit")
        elif c9_inhibit.get("active") is not False:
            active_protections.append("phase5r_c9_maintenance_inhibit_invalid_fail_closed")
print(
    "D3 protection state: "
    + ("blocked (" + ",".join(active_protections) + ")" if active_protections else "clear")
)

now = datetime.now().astimezone()
iso_year, iso_week, _ = now.date().isocalendar()
monday = date.fromisocalendar(iso_year, iso_week, 1)
due = datetime.combine(monday + timedelta(days=3), time(9, 5)).astimezone()
print("Current cycle due time: " + due.isoformat(timespec="seconds"))

successful = []
latest_send = None
try:
    with c6_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("mode") == "send":
                latest_send = row
            if row.get("sent", "").lower() == "yes":
                raw = row.get("timestamp", "").replace("Z", "+00:00")
                stamp = datetime.fromisoformat(raw)
                if stamp.tzinfo is None:
                    stamp = stamp.astimezone()
                successful.append(stamp.astimezone())
except (OSError, ValueError):
    pass

cycle_sent = any(
    stamp.date().isocalendar()[:2] == (iso_year, iso_week) and stamp >= due
    for stamp in successful
)
if cycle_sent or now >= due:
    next_monday = monday + timedelta(days=7)
    next_due = datetime.combine(next_monday + timedelta(days=3), time(9, 5)).astimezone()
else:
    next_due = due
print("Next nominal due time: " + next_due.isoformat(timespec="seconds"))
if now >= due and not cycle_sent:
    print("Catch-up status: past due and eligible, subject to lock and attempt guard.")
else:
    print("Catch-up status: current cycle is sent or not yet due.")

latest_decision = None
try:
    with catchup_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            latest_decision = row
except OSError:
    pass
if latest_decision:
    print(
        "Latest D3 decision: "
        + str(latest_decision.get("decision", "unknown"))
        + " at "
        + str(latest_decision.get("timestamp", "unknown"))
        + "; reason="
        + str(latest_decision.get("reason", "unknown"))
    )
    if latest_decision.get("decision") == "verification_only":
        print("Latest verification-only decision is historical; D3 protection state above determines whether the scheduler is currently blocked.")
else:
    print("Latest D3 decision: none recorded.")
if latest_send:
    print(
        "Latest C6 send status: sent="
        + str(latest_send.get("sent", "unknown"))
        + " at "
        + str(latest_send.get("timestamp", "unknown"))
    )
else:
    print("Latest C6 send status: none recorded.")
PY
else
    print "Active state and schedule: unavailable because configured Python is missing."
fi

if /bin/launchctl print "${DOMAIN}/${D2_LABEL}" >/dev/null 2>&1; then
    print "D2 scheduler: loaded."
else
    print "D2 scheduler: unloaded."
fi
if /bin/launchctl print "${DOMAIN}/${D3_LABEL}" >/dev/null 2>&1; then
    print "D3 scheduler: loaded."
else
    print "D3 scheduler: unloaded."
fi
print "Status check only: C7 was not invoked and email configuration was not read."
