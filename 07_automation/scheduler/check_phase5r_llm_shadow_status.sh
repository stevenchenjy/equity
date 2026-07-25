#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/Desktop/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"
job_label="com.steven.phase5r.llmshadow"
template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
installed_plist="${launch_agents_dir}/${job_label}.plist"
check_failed=0

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
"${python_bin}" "${project_root}/09_scripts/phase5r/run_phase5r_llm_shadow_scheduler.py" --safe-check
/usr/bin/printf '%s\n' "${job_label}=${loaded_state}; plist=${plist_state}"
if (( check_failed != 0 )); then
    /usr/bin/printf '%s\n' "llm_shadow_scheduler_status=failed"
    exit 1
fi
/usr/bin/printf '%s\n' "llm_shadow_scheduler_status=passed"
