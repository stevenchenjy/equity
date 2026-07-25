# Phase 5R-D2 Install Instructions

## Prepared Schedule

The prepared LaunchAgent runs C7 once each Thursday at 9:05 AM local time. It is not installed or loaded by Phase 5R-D2 generation.

## Preflight Status

```text
/Users/messssi/Desktop/equity/07_automation/scheduler/check_phase5r_d2_scheduler_status.sh
```

The status command reads project state and checks launchd registration. It does not run C7 or read SMTP configuration.

## Manual Install

Run only when weekly automatic delivery is intentionally approved:

```text
/Users/messssi/Desktop/equity/07_automation/scheduler/install_phase5r_d2_weekly_scheduler.sh
```

The installer validates the active workflow, the C7 path, the Python interpreter, and the plist before copying the template to:

`~/Library/LaunchAgents/com.steven.phase5r.weeklyconviction.plist`

It then bootstraps that LaunchAgent. Because `RunAtLoad=false`, installation does not intentionally invoke C7. The scheduled run uses C7 default mode and can send exactly one weekly email.

## Manual Uninstall

```text
/Users/messssi/Desktop/equity/07_automation/scheduler/uninstall_phase5r_d2_weekly_scheduler.sh
```

The uninstaller boots out only the D2 label and removes only its installed plist. Project templates, reports, and logs remain intact.

## Logs

- Standard output: `00_project_control/run_logs/phase5r_d2_launchd_stdout.log`
- Standard error: `00_project_control/run_logs/phase5r_d2_launchd_stderr.log`
- Setup verification: `00_project_control/run_logs/phase5r_d2_scheduler_setup_log.csv`

No SMTP secret or local delivery configuration is printed by the scheduler scripts.

