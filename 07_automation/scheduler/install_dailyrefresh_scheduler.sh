#!/bin/zsh
set -euo pipefail

# Replace only an idle refresh job. Preserve RunAtLoad=true: bootstrap may run
# the refresh scheduler immediately, but never invokes or reloads the sender.
project_root="/Users/messssi/LocalRuntime/equity"
python_bin="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
launch_domain="gui/$(/usr/bin/id -u)"
job_label="com.steven.equity_research.dailyrefresh"
service_target="${launch_domain}/${job_label}"
runtime_wrapper="${project_root}/09_scripts/equity_research/run_runtime_scheduler.py"
template_plist="${project_root}/07_automation/scheduler/${job_label}.plist.template"
installed_plist="/Users/messssi/Library/LaunchAgents/${job_label}.plist"
launcher_template="${project_root}/07_automation/scheduler/dailyrefresh_launcher.py.template"
launcher_path="/Users/messssi/Library/Application Support/EquityResearch/bin/dailyrefresh_launcher.py"

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
        # Match only the service state, never a nested coalition's state.
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
"${python_bin}" "${runtime_wrapper}" --job dailyrefresh --sync-only
"${python_bin}" "${runtime_wrapper}" --job dailyrefresh --safe-check
/usr/bin/plutil -lint "${template_plist}" >/dev/null
"${python_bin}" - "${template_plist}" "${runtime_wrapper}" "${launcher_template}" "${launcher_path}" <<'PY'
import plistlib
import sys
from pathlib import Path

template, wrapper, launcher_template, launcher = map(Path, sys.argv[1:])
payload = plistlib.loads(template.read_bytes())
expected = {
    "Label": "com.steven.equity_research.dailyrefresh",
    "ProgramArguments": [str(launcher)],
    "WorkingDirectory": str(wrapper.parents[2]),
    "RunAtLoad": True,
    "KeepAlive": False,
    "StartInterval": 900,
    "ProcessType": "Standard",
    "StandardOutPath": "/Users/messssi/Library/Logs/equity_research_dailyrefresh.out.log",
    "StandardErrorPath": "/Users/messssi/Library/Logs/equity_research_dailyrefresh.err.log",
    "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
}
if payload != expected:
    raise SystemExit("installation_blocked=unexpected_dailyrefresh_template")
if launcher_template.is_symlink() or not launcher_template.is_file():
    raise SystemExit("installation_blocked=unsafe_launcher_template")
if launcher.is_symlink() or (launcher.exists() and not launcher.is_file()):
    raise SystemExit("installation_blocked=unsafe_installed_launcher")
PY

# Recheck after synchronization/preflight, immediately before replacing the job.
assert_target_idle
if [[ "${target_loaded}" == true ]]; then
    /bin/launchctl bootout "${service_target}"
fi
/bin/mkdir -p "/Users/messssi/Library/LaunchAgents" "/Users/messssi/Library/Logs" "${launcher_path:h}"
/bin/cp "${launcher_template}" "${launcher_path}"
/bin/chmod 700 "${launcher_path}"
/usr/bin/cmp -s "${launcher_template}" "${launcher_path}"
/bin/cp "${template_plist}" "${installed_plist}"
/bin/chmod 600 "${installed_plist}"
/usr/bin/cmp -s "${template_plist}" "${installed_plist}"
/bin/launchctl enable "${service_target}"
/bin/launchctl bootstrap "${launch_domain}" "${installed_plist}"
/usr/bin/printf '%s\n' \
    "dailyrefresh_installed=true" \
    "run_at_load=true" \
    "start_interval_seconds=900" \
    "bootstrap_refresh_may_run=true" \
    "sender_invoked=false" \
    "other_jobs_modified=false"
