#!/bin/zsh
set -euo pipefail

# Replace only an idle dailydecision job. Loading the replacement must not run
# research or delivery: its first attempt remains owned by StartInterval.
project_root="/Users/messssi/LocalRuntime/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
job_label="com.steven.equity_research.dailydecision"
service_target="${launch_domain}/${job_label}"
runtime_wrapper="${project_root}/09_scripts/equity_research/run_runtime_scheduler.py"
template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
installed_plist="/Users/messssi/Library/LaunchAgents/${job_label}.plist"

[[ -x "${python_bin}" ]]
[[ -f "${runtime_wrapper}" ]]
[[ "$(/usr/bin/git -C "${project_root}" rev-parse --show-toplevel)" == "${project_root}" ]]
[[ "$(/usr/bin/git -C "${project_root}" branch --show-current)" == "main" ]]
[[ "$(/usr/bin/git -C "${project_root}" remote get-url origin)" == "https://github.com/stevenchenjy/equity.git" ]]

target_loaded=false
assert_target_idle() {
    local launch_state launch_status
    if launch_state="$(/bin/launchctl print "${service_target}" 2>&1)"; then
        target_loaded=true
        # Match only top-level service state, not a nested coalition's state.
        if ! /usr/bin/printf '%s\n' "${launch_state}" | /usr/bin/grep -Eq $'^\tstate = not running$' \
            || /usr/bin/printf '%s\n' "${launch_state}" | /usr/bin/grep -Eq $'^\tpid = [1-9][0-9]*$'; then
            /usr/bin/printf '%s\n' "installation_blocked=target_not_idle:${job_label}"
            return 1
        fi
    else
        launch_status=$?
        if [[ "${launch_status}" != 113 ]]; then
            /usr/bin/printf '%s\n' "installation_blocked=target_state_unknown:${job_label}:${launch_status}"
            return 1
        fi
        target_loaded=false
    fi
}

assert_target_idle
"${python_bin}" "${runtime_wrapper}" --job dailydecision --sync-only
"${python_bin}" "${runtime_wrapper}" --job dailydecision --safe-check
/usr/bin/plutil -lint "${template_plist}" >/dev/null
"${python_bin}" - "${template_plist}" "${runtime_wrapper}" <<'PY'
import plistlib
import sys
from pathlib import Path

template, wrapper = map(Path, sys.argv[1:])
payload = plistlib.loads(template.read_bytes())
expected = {
    "Label": "com.steven.equity_research.dailydecision",
    "ProgramArguments": [sys.executable, str(wrapper), "--job", "dailydecision"],
    "WorkingDirectory": str(wrapper.parents[2]),
    "RunAtLoad": False,
    "KeepAlive": False,
    "StartInterval": 900,
    "ProcessType": "Standard",
    "StandardOutPath": "/Users/messssi/Library/Logs/equity_research_dailydecision.out.log",
    "StandardErrorPath": "/Users/messssi/Library/Logs/equity_research_dailydecision.err.log",
    "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
}
if payload != expected:
    raise SystemExit("installation_blocked=unexpected_dailydecision_template")
PY

# Recheck after synchronization/preflight, immediately before any bootout.
assert_target_idle
if [[ "${target_loaded}" == true ]]; then
    /bin/launchctl bootout "${service_target}"
fi
/bin/mkdir -p "/Users/messssi/Library/LaunchAgents" "/Users/messssi/Library/Logs"
/bin/cp "${template_plist}" "${installed_plist}"
/bin/chmod 600 "${installed_plist}"
/usr/bin/cmp -s "${template_plist}" "${installed_plist}"
/bin/launchctl enable "${service_target}"
/bin/launchctl bootstrap "${launch_domain}" "${installed_plist}"
/usr/bin/printf '%s\n' \
    "dailydecision_installed=true" \
    "run_at_load=false" \
    "start_interval_seconds=900" \
    "sender_invoked=false" \
    "other_jobs_modified=false"
