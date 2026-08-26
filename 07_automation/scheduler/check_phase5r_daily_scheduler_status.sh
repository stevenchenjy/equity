#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/LocalRuntime/equity"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"
check_failed=0
disabled_dump="$(/bin/launchctl print-disabled "${launch_domain}")"

for legacy_suffix in dailybrief weeklyconviction weeklycatchup; do
    legacy_label="com.steven.phase5r.${legacy_suffix}"
    if /bin/launchctl print "${launch_domain}/${legacy_label}" >/dev/null 2>&1; then
        /usr/bin/printf '%s\n' "${legacy_label}=loaded_unexpected"
        check_failed=1
    else
        /usr/bin/printf '%s\n' "${legacy_label}=unloaded"
    fi
done

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
    installed_plist="${launch_agents_dir}/${job_label}.plist"
    if /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
        loaded_state="loaded"
    else
        loaded_state="unloaded"
        check_failed=1
    fi
    if [[ -f "${installed_plist}" ]] && /usr/bin/cmp -s "${template_plist}" "${installed_plist}"; then
        plist_state="installed_matches_template"
    else
        plist_state="missing_or_mismatch"
        check_failed=1
    fi
    if [[ "${disabled_dump}" == *"\"${job_label}\" => disabled"* ]]; then
        enabled_state="disabled"
        check_failed=1
    else
        enabled_state="enabled"
    fi
    /usr/bin/printf '%s\n' "${job_label}=${loaded_state}; ${enabled_state}; plist=${plist_state}"
done

if (( check_failed != 0 )); then
    /usr/bin/printf '%s\n' "daily_scheduler_status=failed"
    exit 1
fi
/usr/bin/printf '%s\n' "daily_scheduler_status=passed"
