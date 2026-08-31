#!/bin/zsh
set -euo pipefail

LABEL="com.steven.phase5r.weeklyconviction"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
TEMPLATE_PATH="${PROJECT_ROOT}/07_automation/scheduler/${LABEL}.plist.template"
PIPELINE_PATH="${PROJECT_ROOT}/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py"
STATE_PATH="${PROJECT_ROOT}/00_project_control/active_decision_state.yaml"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PATH="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"
LOG_DIR="${PROJECT_ROOT}/00_project_control/run_logs"

function install_failed {
    local exit_code=$?
    if (( exit_code != 0 )); then
        print -u2 "Phase 5R-D2 installation failed. The C7 pipeline was not started by this script."
    fi
}
trap install_failed EXIT

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    print -u2 "Phase 5R-D2 requires macOS launchd."
    exit 1
fi

for required_path in "${PYTHON_BIN}" "${TEMPLATE_PATH}" "${PIPELINE_PATH}" "${STATE_PATH}"; do
    if [[ ! -e "${required_path}" ]]; then
        print -u2 "Required scheduler path is missing: ${required_path}"
        exit 1
    fi
done

if ! "${PYTHON_BIN}" -c 'import json, pathlib, sys; state=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")); expected={"current_workflow":"weekly_conviction","active_pipeline":"phase5r_c7","daily_pipeline_status":"parked","d1_scheduler_status":"parked_uninstalled","email_delivery_allowed_from":"phase5r_c7_only","archived_folders_allowed_as_input":"no","broker_connection_allowed":"no","order_code_allowed":"no","manual_execution_only":"yes"}; sys.exit(0 if all(state.get(k)==v for k,v in expected.items()) else 1)' "${STATE_PATH}"; then
    print -u2 "Active decision state does not authorize the prepared C7 weekly scheduler."
    exit 1
fi

if ! "${PYTHON_BIN}" -c "import yfinance" >/dev/null 2>&1; then
    print -u2 "The configured Python interpreter cannot import yfinance."
    exit 1
fi

/usr/bin/plutil -lint "${TEMPLATE_PATH}" >/dev/null
/bin/mkdir -p "${LAUNCH_AGENTS_DIR}" "${LOG_DIR}"
/usr/bin/touch "${LOG_DIR}/phase5r_d2_launchd_stdout.log" "${LOG_DIR}/phase5r_d2_launchd_stderr.log"

if /bin/launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${DOMAIN}/${LABEL}"
fi

/bin/cp "${TEMPLATE_PATH}" "${TARGET_PATH}"
/bin/chmod 600 "${TARGET_PATH}"
/bin/launchctl bootstrap "${DOMAIN}" "${TARGET_PATH}"
/bin/launchctl enable "${DOMAIN}/${LABEL}"

trap - EXIT
print "Installed ${LABEL}."
print "Schedule: Thursday at 09:05 local time."
print "RunAtLoad and KeepAlive are disabled; this installer did not invoke C7."
