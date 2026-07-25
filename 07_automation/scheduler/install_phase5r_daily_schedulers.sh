#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/Desktop/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"

"${python_bin}" -c '
import json
from pathlib import Path
root = Path("/Users/messssi/Desktop/equity")
active = json.loads((root / "00_project_control/active_decision_state.yaml").read_text())
inhibit = json.loads((root / "07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json").read_text())
assert active["current_workflow"] == "daily_decision"
assert active["active_pipeline"] == "phase5r_daily"
assert inhibit["active"] is True
assert inhibit["allowed_pipeline"] == "none"
'

/bin/mkdir -p "${launch_agents_dir}" "/Users/messssi/Library/Logs"

for job_suffix in dailyrefresh dailydecision; do
    job_label="com.steven.phase5r.${job_suffix}"
    template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
    installed_plist="${launch_agents_dir}/${job_label}.plist"
    /usr/bin/plutil -lint "${template_plist}" >/dev/null
    if /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
        /bin/launchctl bootout "${launch_domain}/${job_label}"
    fi
    /bin/cp "${template_plist}" "${installed_plist}"
    /bin/chmod 600 "${installed_plist}"
    /bin/launchctl bootstrap "${launch_domain}" "${installed_plist}"
    /bin/launchctl enable "${launch_domain}/${job_label}"
done

"${python_bin}" "${project_root}/09_scripts/phase5r/run_phase5r_daily_refresh_scheduler.py" --safe-check
"${python_bin}" "${project_root}/09_scripts/phase5r/run_phase5r_daily_scheduler.py" --safe-check

/usr/bin/printf '%s\n' \
    "daily_schedulers_installed=true" \
    "maintenance_inhibit_retained=true" \
    "email_attempted=false"
