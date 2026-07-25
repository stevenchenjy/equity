#!/bin/zsh
set -euo pipefail

launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    installed_plist="${launch_agents_dir}/${job_label}.plist"
    if /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
        /bin/launchctl bootout "${launch_domain}/${job_label}"
    fi
    if [[ -f "${installed_plist}" ]]; then
        /bin/rm -f "${installed_plist}"
    fi
done

/usr/bin/printf '%s\n' "daily_schedulers_uninstalled=true"
