#!/bin/zsh
set -euo pipefail

LABEL="com.steven.phase5r.weeklycatchup"
PROJECT_ROOT="/Users/messssi/Desktop/equity"
TARGET_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
INSTALL_INHIBIT="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3_install_inhibit"
D3F_VERIFICATION_INHIBIT="${PROJECT_ROOT}/00_project_control/run_logs/phase5r_d3f_verification_inhibit"
DOMAIN="gui/$(/usr/bin/id -u)"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    print -u2 "Phase 5R-D3 requires macOS launchd."
    exit 1
fi

if /bin/launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${DOMAIN}/${LABEL}"
fi
if [[ -f "${TARGET_PATH}" ]]; then
    /bin/rm "${TARGET_PATH}"
fi
if [[ -f "${INSTALL_INHIBIT}" ]]; then
    /bin/rm "${INSTALL_INHIBIT}"
fi
if [[ -f "${D3F_VERIFICATION_INHIBIT}" ]]; then
    /bin/rm "${D3F_VERIFICATION_INHIBIT}"
fi

print "Uninstalled ${LABEL}."
print "D3 logs, reports, templates, state, C7, and email configuration were preserved."
print "D2 was not reinstalled. C7 was not invoked."
