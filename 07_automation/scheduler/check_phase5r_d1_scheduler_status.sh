#!/bin/zsh
set -euo pipefail

LABEL="com.steven.phase5r.dailybrief"
TARGET_PATH="${HOME}/Library/LaunchAgents/${LABEL}.plist"
DOMAIN="gui/$(/usr/bin/id -u)"

if /bin/launchctl print "${DOMAIN}/${LABEL}" >/dev/null 2>&1; then
    /bin/launchctl print "${DOMAIN}/${LABEL}"
    print "Scheduler status: loaded."
    print "Installed plist: ${TARGET_PATH}"
    exit 0
fi

if [[ -f "${TARGET_PATH}" ]]; then
    print "Scheduler status: plist installed but agent not loaded."
else
    print "Scheduler status: not installed."
fi
exit 1
