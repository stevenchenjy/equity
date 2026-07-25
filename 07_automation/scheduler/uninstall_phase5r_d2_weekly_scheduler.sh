#!/bin/zsh
set -euo pipefail

LABEL="com.steven.phase5r.weeklyconviction"
TARGET_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"

if [[ "$(/usr/bin/uname -s)" != "Darwin" ]]; then
    print -u2 "Phase 5R-D2 requires macOS launchd."
    exit 1
fi

if /bin/launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${DOMAIN}/${LABEL}"
fi

if [[ -f "${TARGET_PATH}" ]]; then
    /bin/rm "${TARGET_PATH}"
fi

print "Uninstalled ${LABEL}."
print "D2 templates, reports, and logs were preserved."
print "The C7 pipeline was not invoked."

