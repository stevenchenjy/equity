#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/LocalRuntime/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"
runtime_wrapper="${project_root}/09_scripts/phase5r/run_phase5r_runtime_scheduler.py"

[[ -x "${python_bin}" ]]
[[ -f "${runtime_wrapper}" ]]
[[ "$(/usr/bin/git -C "${project_root}" rev-parse --show-toplevel)" == "${project_root}" ]]
[[ "$(/usr/bin/git -C "${project_root}" branch --show-current)" == "main" ]]
[[ "$(/usr/bin/git -C "${project_root}" remote get-url origin)" == "https://github.com/stevenchenjy/equity.git" ]]

for legacy_suffix in dailybrief weeklyconviction weeklycatchup; do
    legacy_label="com.steven.phase5r.${legacy_suffix}"
    if /bin/launchctl print "${launch_domain}/${legacy_label}" >/dev/null 2>&1; then
        /usr/bin/printf '%s\n' "installation_blocked=legacy_scheduler_loaded:${legacy_label}"
        exit 1
    fi
done

/bin/mkdir -p "${launch_agents_dir}" "/Users/messssi/Library/Logs"

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
    /usr/bin/plutil -lint "${template_plist}" >/dev/null
done

"${python_bin}" "${runtime_wrapper}" --job dailyrefresh --sync-only
"${python_bin}" "${runtime_wrapper}" --job dailyrefresh --safe-check
"${python_bin}" "${runtime_wrapper}" --job dailydecision --safe-check

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    if /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
        /bin/launchctl bootout "${launch_domain}/${job_label}"
    fi
done

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
    installed_plist="${launch_agents_dir}/${job_label}.plist"
    /bin/cp "${template_plist}" "${installed_plist}"
    /bin/chmod 600 "${installed_plist}"
    /bin/launchctl enable "${launch_domain}/${job_label}"
done

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    installed_plist="${launch_agents_dir}/${job_label}.plist"
    /bin/launchctl bootstrap "${launch_domain}" "${installed_plist}"
done

/usr/bin/printf '%s\n' \
    "daily_schedulers_installed=true" \
    "runtime_root=${project_root}" \
    "launch_domain=${launch_domain}"
