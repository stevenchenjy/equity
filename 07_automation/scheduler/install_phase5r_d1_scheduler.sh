#!/bin/zsh
set -euo pipefail

LABEL="com.steven.phase5r.dailybrief"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
TEMPLATE_PATH="${PROJECT_ROOT}/07_automation/scheduler/${LABEL}.plist.template"
PIPELINE_PATH="${PROJECT_ROOT}/09_scripts/phase5r/run_phase5r_c3_daily_email_pipeline.py"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
TARGET_PATH="${LAUNCH_AGENTS_DIR}/${LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"
LOG_DIR="${PROJECT_ROOT}/00_project_control/run_logs"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    print -u2 "Phase 5R-D1 requires macOS launchd."
    exit 1
fi

for required_path in "${PYTHON_BIN}" "${TEMPLATE_PATH}" "${PIPELINE_PATH}"; do
    if [[ ! -e "${required_path}" ]]; then
        print -u2 "Required scheduler path is missing: ${required_path}"
        exit 1
    fi
done

if ! "${PYTHON_BIN}" -c "import yfinance" >/dev/null 2>&1; then
    print -u2 "The configured Python interpreter cannot import yfinance."
    exit 1
fi

/usr/bin/plutil -lint "${TEMPLATE_PATH}" >/dev/null
/bin/mkdir -p "${LAUNCH_AGENTS_DIR}" "${LOG_DIR}"
/usr/bin/touch "${LOG_DIR}/phase5r_d1_launchd_stdout.log" "${LOG_DIR}/phase5r_d1_launchd_stderr.log"

if /bin/launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${DOMAIN}/${LABEL}"
fi

/bin/cp "${TEMPLATE_PATH}" "${TARGET_PATH}"
/bin/chmod 600 "${TARGET_PATH}"
/bin/launchctl bootstrap "${DOMAIN}" "${TARGET_PATH}"
/bin/launchctl enable "${DOMAIN}/${LABEL}"

print "Installed ${LABEL}."
print "Schedule: Monday-Friday at 09:05 local time."
print "RunAtLoad is disabled; no pipeline run was triggered by installation."
