#!/bin/zsh
set -euo pipefail

D2_LABEL="com.steven.phase5r.weeklyconviction"
D3_LABEL="com.steven.phase5r.weeklycatchup"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
TEMPLATE_PATH="${PROJECT_ROOT}/07_automation/scheduler/${D3_LABEL}.plist.template"
WRAPPER_PATH="${PROJECT_ROOT}/09_scripts/phase5r/run_phase5r_d3_weekly_catchup.py"
C7_PATH="${PROJECT_ROOT}/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py"
STATE_PATH="${PROJECT_ROOT}/00_project_control/active_decision_state.yaml"
STATE_TEMPLATE="${PROJECT_ROOT}/07_automation/scheduler/phase5r_d3_catchup_state.template.json"
RUN_LOG_DIR="${PROJECT_ROOT}/00_project_control/run_logs"
CATCHUP_LOG="${RUN_LOG_DIR}/phase5r_d3_catchup_check_log.csv"
LOCAL_STATE="${RUN_LOG_DIR}/phase5r_d3_catchup_state.local.json"
INSTALL_INHIBIT="${RUN_LOG_DIR}/phase5r_d3_install_inhibit"
LAUNCHD_LOG_DIR="${HOME}/Library/Logs"
LAUNCHD_STDOUT="${LAUNCHD_LOG_DIR}/phase5r_d3_launchd_stdout.log"
LAUNCHD_STDERR="${LAUNCHD_LOG_DIR}/phase5r_d3_launchd_stderr.log"
LAUNCH_AGENTS_DIR="${HOME}/Library/LaunchAgents"
D2_TARGET="${LAUNCH_AGENTS_DIR}/${D2_LABEL}.plist"
D3_TARGET="${LAUNCH_AGENTS_DIR}/${D3_LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"
INHIBIT_CREATED="no"
INSTALL_MODE="install"

if [[ "${1:-}" == "--check-only" ]]; then
    INSTALL_MODE="check_only"
elif (( $# > 0 )); then
    print -u2 "Unsupported argument: $1"
    exit 2
fi

function install_failed {
    local exit_code=$?
    if (( exit_code != 0 )); then
        print -u2 "Phase 5R-D3 installation failed. C7 was not invoked by this installer."
        if [[ "${INHIBIT_CREATED}" == "yes" && -e "${INSTALL_INHIBIT}" ]]; then
            print -u2 "The D3 install inhibit remains in place to prevent an unsupervised catch-up run."
        fi
    fi
}
trap install_failed EXIT

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    print -u2 "Phase 5R-D3 requires macOS launchd."
    exit 1
fi

for required_path in "${PYTHON_BIN}" "${TEMPLATE_PATH}" "${WRAPPER_PATH}" "${C7_PATH}" "${STATE_PATH}" "${STATE_TEMPLATE}"; do
    if [[ ! -e "${required_path}" ]]; then
        print -u2 "Required scheduler path is missing: ${required_path}"
        exit 1
    fi
done

if ! "${PYTHON_BIN}" -c 'import json, pathlib, sys; state=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")); expected={"current_workflow":"weekly_conviction","active_pipeline":"phase5r_c7","email_delivery_allowed_from":"phase5r_c7_only","archived_folders_allowed_as_input":"no","broker_connection_allowed":"no","order_code_allowed":"no","manual_execution_only":"yes"}; sys.exit(0 if all(state.get(k)==v for k,v in expected.items()) else 1)' "${STATE_PATH}"; then
    print -u2 "Active decision state does not authorize the D3 C7 catch-up scheduler."
    exit 1
fi

/usr/bin/plutil -lint "${TEMPLATE_PATH}" >/dev/null
if [[ "${INSTALL_MODE}" == "check_only" ]]; then
    trap - EXIT
    print "Phase 5R-D3 installer safe check passed. No scheduler or inhibit state was changed."
    print "C7 was not invoked."
    exit 0
fi
/bin/mkdir -p "${LAUNCH_AGENTS_DIR}" "${RUN_LOG_DIR}" "${LAUNCHD_LOG_DIR}"
/usr/bin/touch "${CATCHUP_LOG}" "${LAUNCHD_STDOUT}" "${LAUNCHD_STDERR}"
if [[ ! -f "${LOCAL_STATE}" ]]; then
    /bin/cp "${STATE_TEMPLATE}" "${LOCAL_STATE}"
fi

initial_log_lines=$(/usr/bin/wc -l < "${CATCHUP_LOG}" | /usr/bin/tr -d ' ')
/usr/bin/touch "${INSTALL_INHIBIT}"
INHIBIT_CREATED="yes"

if /bin/launchctl print "${DOMAIN}/${D3_LABEL}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${DOMAIN}/${D3_LABEL}"
fi
if /bin/launchctl print "${DOMAIN}/${D2_LABEL}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${DOMAIN}/${D2_LABEL}"
fi
if [[ -f "${D2_TARGET}" ]]; then
    /bin/rm "${D2_TARGET}"
fi

/bin/cp "${TEMPLATE_PATH}" "${D3_TARGET}"
/bin/chmod 600 "${D3_TARGET}"
/bin/launchctl bootstrap "${DOMAIN}" "${D3_TARGET}"
/bin/launchctl enable "${DOMAIN}/${D3_LABEL}"

inhibit_observed="no"
first_new_line=$(( initial_log_lines + 1 ))
for _attempt in {1..300}; do
    if /usr/bin/tail -n +"${first_new_line}" "${CATCHUP_LOG}" 2>/dev/null | /usr/bin/grep -q ',verification_only,install_inhibit_active,'; then
        inhibit_observed="yes"
        break
    fi
    /bin/sleep 0.1
done

if [[ "${inhibit_observed}" != "yes" ]]; then
    print -u2 "D3 did not confirm its protected RunAtLoad check; install inhibit was retained."
    exit 1
fi

/bin/rm "${INSTALL_INHIBIT}"
INHIBIT_CREATED="no"
trap - EXIT
print "Installed and loaded ${D3_LABEL}."
print "D2 was unloaded and its installed LaunchAgent plist was removed; project D2 artifacts were preserved."
print "RunAtLoad performed an inhibited check only. C7 was not invoked during installation."
print "D3 will check every 900 seconds and catch up after Thursday 09:05 local time when due."
