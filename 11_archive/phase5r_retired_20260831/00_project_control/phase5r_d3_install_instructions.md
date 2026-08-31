# Phase 5R-D3 Install Instructions

## Prepared Scheduler

D3 is prepared but not installed or loaded by generation or verification. It checks on load/login and every 900 seconds while the Mac user session is available. The wrapper sends nothing before Thursday 09:05 local time and sends nothing after a qualifying C6 success for the cycle.

## Preflight Status

Run:

```text
/Users/messssi/Desktop/equity/07_automation/scheduler/check_phase5r_d3_catchup_status.sh
```

The status script shows active workflow/pipeline, D2 and D3 load state, the next nominal due time, catch-up eligibility, the latest D3 decision, and the latest C6 send result. It does not run C7 or read SMTP configuration.

## Manual Migration Install

Run only when ready to replace D2:

```text
/Users/messssi/Desktop/equity/07_automation/scheduler/install_phase5r_d3_catchup_scheduler.sh
```

The installer validates the active state, Python path, C7 path, wrapper, state template, and plist. It then:

1. Creates a temporary D3 install inhibit.
2. Boots out D3 if an older loaded copy exists.
3. Boots out D2 if loaded and removes only D2's installed LaunchAgent plist.
4. Preserves every D2 project template, script, report, and log.
5. Installs D3 at `~/Library/LaunchAgents/com.steven.phase5r.weeklycatchup.plist`.
6. Bootstraps D3 only as a result of this manual command.
7. Waits for the `RunAtLoad` wrapper check to confirm `install_inhibit_active`.
8. Removes the inhibit, leaving the next 900-second check eligible to catch up.

The installer does not invoke C7. If the protected RunAtLoad check is not confirmed, installation fails and retains the inhibit so no unsupervised C7 run can start.

To validate installer prerequisites without changing launchd or inhibit state, run:

```text
/Users/messssi/Desktop/equity/07_automation/scheduler/install_phase5r_d3_catchup_scheduler.sh --check-only
```

## Manual Uninstall

Run:

```text
/Users/messssi/Desktop/equity/07_automation/scheduler/uninstall_phase5r_d3_catchup_scheduler.sh
```

This boots out D3 and removes its installed plist. It preserves logs, reports, templates, runtime state, C7, and email configuration. It does not reinstall D2.

## Operational Logs

- Check audit: `00_project_control/run_logs/phase5r_d3_catchup_check_log.csv`
- Launchd stdout: `/Users/messssi/Library/Logs/phase5r_d3_launchd_stdout.log`
- Launchd stderr: `/Users/messssi/Library/Logs/phase5r_d3_launchd_stderr.log`
- Runtime state: `00_project_control/run_logs/phase5r_d3_catchup_state.local.json`

No status or installation command prints SMTP configuration or credentials.
