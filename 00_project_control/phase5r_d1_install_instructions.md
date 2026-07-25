# Phase 5R-D1 Install Instructions

## Schedule

The launch agent is configured for Monday through Friday at `9:05 AM` in the Mac's local timezone. It runs the existing C3 pipeline once for each scheduled event.

Installation does not run the pipeline immediately because `RunAtLoad` is disabled. The installer also does not use `launchctl kickstart`.

## Install

From the project root:

```bash
./07_automation/scheduler/install_phase5r_d1_scheduler.sh
```

The installer validates the plist and Python dependency, copies the plist to `~/Library/LaunchAgents/com.steven.phase5r.dailybrief.plist`, and loads it into the current user's GUI launchd domain.

## Check Status

```bash
./07_automation/scheduler/check_phase5r_d1_scheduler_status.sh
```

## Uninstall

```bash
./07_automation/scheduler/uninstall_phase5r_d1_scheduler.sh
```

Uninstalling removes the user LaunchAgent plist but preserves scheduler stdout/stderr and project audit logs.

## Operational Notes

- Keep the Mac powered on and able to access the network near the scheduled time.
- A calendar event missed while the Mac sleeps may run once after wake according to macOS launchd behavior.
- The scheduler uses no cloud service and has no recipient, credential, broker, or execution configuration of its own.
- Review `00_project_control/run_logs/phase5r_d1_launchd_stdout.log` and `phase5r_d1_launchd_stderr.log` for launchd process output.
