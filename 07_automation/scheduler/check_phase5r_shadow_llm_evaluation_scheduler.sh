#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/LocalRuntime/equity"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"
job_label="com.steven.phase5r.shadoweval"
template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
installed_plist="${launch_agents_dir}/${job_label}.plist"
disabled_dump="$(/bin/launchctl print-disabled "${launch_domain}")"

if ! /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
    /usr/bin/printf '%s\n' "${job_label}=unloaded"
    exit 1
fi
if [[ ! -f "${installed_plist}" ]] || ! /usr/bin/cmp -s "${template_plist}" "${installed_plist}"; then
    /usr/bin/printf '%s\n' "${job_label}=loaded plist=missing_or_mismatch"
    exit 1
fi
if [[ "${disabled_dump}" == *"\"${job_label}\" => disabled"* ]]; then
    /usr/bin/printf '%s\n' "${job_label}=loaded disabled"
    exit 1
fi

/usr/bin/printf '%s\n' \
    "${job_label}=loaded enabled plist=installed_matches_template" \
    "shadow_evaluation_scheduler_status=passed production_influence=false"
