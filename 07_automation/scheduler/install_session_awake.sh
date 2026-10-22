#!/bin/zsh
set -euo pipefail

# Install only the power guard. Do not bootstrap or invoke a delivery worker.
project_root="/Users/messssi/LocalRuntime/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
job_label="com.steven.equity_research.sessionawake"
template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
installed_plist="/Users/messssi/Library/LaunchAgents/${job_label}.plist"

[[ -x "${python_bin}" ]]
[[ -f "${project_root}/09_scripts/equity_research/session_awake.py" ]]
/usr/bin/plutil -lint "${template_plist}" >/dev/null
"${python_bin}" "${project_root}/09_scripts/equity_research/session_awake.py" --check
/bin/mkdir -p "/Users/messssi/Library/LaunchAgents" "/Users/messssi/Library/Logs"
if /bin/launchctl print "${launch_domain}/${job_label}" >/dev/null 2>&1; then
    /bin/launchctl bootout "${launch_domain}/${job_label}"
fi
/bin/cp "${template_plist}" "${installed_plist}"
/bin/chmod 600 "${installed_plist}"
/bin/launchctl enable "${launch_domain}/${job_label}"
/bin/launchctl bootstrap "${launch_domain}" "${installed_plist}"
/usr/bin/printf '%s\n' "session_awake_installed=true; sender_invoked=false; research_invoked=false"
