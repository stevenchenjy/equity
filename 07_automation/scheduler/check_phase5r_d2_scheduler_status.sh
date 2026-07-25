#!/bin/zsh
set -euo pipefail

LABEL="com.steven.phase5r.weeklyconviction"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
STATE_PATH="${PROJECT_ROOT}/00_project_control/active_decision_state.yaml"
TARGET_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    print -u2 "Phase 5R-D2 requires macOS launchd."
    exit 1
fi

if [[ -f "${STATE_PATH}" && -x "${PYTHON_BIN}" ]]; then
    "${PYTHON_BIN}" -c 'import json, pathlib, sys; state=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")); print("Active workflow: " + str(state.get("current_workflow", "unknown"))); print("Active pipeline: " + str(state.get("active_pipeline", "unknown"))); print("Primary decision: " + str(state.get("primary_decision", "unknown"))); print("Next review date: " + str(state.get("next_review_date", "unknown")))' "${STATE_PATH}"
else
    print "Active state: unavailable."
fi

if /bin/launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    print "Scheduler status: loaded."
elif [[ -f "${TARGET_PATH}" ]]; then
    print "Scheduler status: plist installed but agent not loaded."
else
    print "Scheduler status: not installed."
fi

print "Prepared schedule: Thursday at 09:05 local time."
print "Prepared pipeline: phase5r_c7 only."
print "RunAtLoad=false; KeepAlive=false; no StartInterval."

