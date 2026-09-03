#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/LocalRuntime/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"
job_label="com.steven.phase5r.shadoweval"
template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
installed_plist="${launch_agents_dir}/${job_label}.plist"
event_runner="${project_root}/07_automation/scheduler/run_phase5r_shadow_llm_event.sh"
shadow_runner="${project_root}/09_scripts/phase5r/run_phase5r_shadow_llm_evaluation.py"

[[ -x "${python_bin}" ]]
[[ -x "${event_runner}" ]]
[[ -f "${shadow_runner}" ]]
[[ "$(/usr/bin/git -C "${project_root}" rev-parse --show-toplevel)" == "${project_root}" ]]

if /bin/launchctl print "${launch_domain}/com.steven.phase5r.llmshadow" >/dev/null 2>&1; then
    /usr/bin/printf '%s\n' "installation_blocked=retired_llmshadow_loaded"
    exit 1
fi
if [[ -f "${launch_agents_dir}/com.steven.phase5r.llmshadow.plist" ]]; then
    /usr/bin/printf '%s\n' "installation_blocked=retired_llmshadow_plist_present"
    exit 1
fi

"${python_bin}" "${shadow_runner}" --check
/usr/bin/plutil -lint "${template_plist}" >/dev/null
/bin/mkdir -p "${launch_agents_dir}" "/Users/messssi/Library/Logs"

if /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${launch_domain}/${job_label}"
fi
/bin/cp "${template_plist}" "${installed_plist}"
/bin/chmod 600 "${installed_plist}"
/bin/launchctl enable "${launch_domain}/${job_label}"
/bin/launchctl bootstrap "${launch_domain}" "${installed_plist}"

/usr/bin/printf '%s\n' \
    "shadow_evaluation_scheduler_installed=true" \
    "event_source=phase5r_llm_evidence_packet.json" \
    "production_scheduler_integration=false"
