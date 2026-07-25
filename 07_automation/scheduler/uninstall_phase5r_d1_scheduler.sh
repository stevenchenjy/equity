#!/bin/zsh
set -euo pipefail

LABEL="com.steven.phase5r.dailybrief"
TARGET_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"

if /bin/launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${DOMAIN}/${LABEL}"
fi

if [[ -f "${TARGET_PATH}" ]]; then
    /bin/rm "${TARGET_PATH}"
fi

print "Uninstalled ${LABEL}."
print "Project logs were preserved."
