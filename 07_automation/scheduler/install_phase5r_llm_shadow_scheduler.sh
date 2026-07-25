#!/bin/zsh
set -euo pipefail

project_root="/Users/messssi/Desktop/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
launch_agents_dir="/Users/messssi/Library/LaunchAgents"
job_label="com.steven.phase5r.llmshadow"
template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
installed_plist="${launch_agents_dir}/${job_label}.plist"

"${python_bin}" -c '
import json
from pathlib import Path
root = Path("/Users/messssi/Desktop/equity")
active = json.loads((root / "00_project_control/active_decision_state.yaml").read_text())
inhibit = json.loads((root / "07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json").read_text())
registry = json.loads((root / "00_project_control/phase5r_llm_model_registry.json").read_text())
assert active["current_workflow"] == "daily_decision"
assert active["active_pipeline"] == "phase5r_daily"
assert active["broker_connection_allowed"] == "no"
assert active["order_code_allowed"] == "no"
assert active["manual_execution_only"] == "yes"
assert inhibit["active"] is False
assert inhibit["allowed_pipeline"] == "phase5r_daily"
assert registry["mode"] == "shadow"
assert registry["live_shadow_enabled"] is True
assert registry["canonical_influence_enabled"] is False
assert registry["provider_credentials_read_by_repository"] is False
assert registry["tools_enabled"] is False
'

/usr/bin/plutil -lint "${template_plist}" >/dev/null
/bin/mkdir -p "${launch_agents_dir}" "/Users/messssi/Library/Logs"
if /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${launch_domain}/${job_label}"
fi
/bin/cp "${template_plist}" "${installed_plist}"
/bin/chmod 600 "${installed_plist}"
/bin/launchctl bootstrap "${launch_domain}" "${installed_plist}"
/bin/launchctl enable "${launch_domain}/${job_label}"
"${python_bin}" "${project_root}/09_scripts/phase5r/run_phase5r_llm_shadow_scheduler.py" --safe-check

/usr/bin/printf '%s\n' \
    "llm_shadow_scheduler_installed=true" \
    "canonical_effect=false" \
    "email_attempted=false"
