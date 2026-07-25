# Phase 5R-D3 Catch-up Scheduler Policy

## Purpose

Phase 5R-D3 replaces the D2 single calendar trigger with a stateful check. The LaunchAgent runs the check at login/load and every 900 seconds while the user session is available. A check can invoke the active C7 weekly conviction pipeline only when the current weekly cycle is due and has no successful C6 delivery.

## Authoritative Boundary

Every check reads `00_project_control/active_decision_state.yaml` and requires:

- `current_workflow=weekly_conviction`
- `active_pipeline=phase5r_c7`
- `email_delivery_allowed_from=phase5r_c7_only`
- `broker_connection_allowed=no`
- `order_code_allowed=no`
- `archived_folders_allowed_as_input=no`
- `manual_execution_only=yes`

A missing, invalid, or conflicting state blocks C7. D3 does not read SMTP configuration, connect to a broker, create orders, or use archived holdings.

## Weekly Due Rule

- Cycle ID: ISO week, formatted `YYYY-Www` in system-local time.
- Due time: Thursday at 09:05 system-local time.
- Before the due time: record `not_due_yet` and exit.
- After the due time: inspect `07_automation/email_delivery/phase5r_c6_delivery_status.csv`.
- A `sent=yes` row in the same ISO cycle at or after the due time records `already_sent` and blocks C7.
- If due and unsent, acquire the D3 lock, re-read C6 status, and then consider one C7 invocation.

`StartInterval=900` schedules checks, not email sends. `RunAtLoad=true` provides the wake/login catch-up opportunity. `KeepAlive=false` prevents a continuously running process.

## Duplicate and Failure Controls

The lock at `00_project_control/run_logs/phase5r_d3_catchup.lock` uses a nonblocking OS file lock. It prevents concurrent due checks; the OS releases the lock if the process exits unexpectedly.

Before invoking C7, D3 durably records one attempt for the cycle in its local state. A prior attempt without a confirmed C6 success blocks automatic retry and records `catchup_failed`; manual review is required. This fail-closed rule avoids a duplicate when delivery may have succeeded but status recording was interrupted.

A successful catch-up requires all three conditions:

1. C7 returns zero.
2. Exactly one new C6 `sent=yes` row exists.
3. The new successful row qualifies for the current cycle.

Any other result is `catchup_failed`. Later checks still recognize an actual qualifying C6 success as `already_sent`.

## Logging

Each check appends one row to `00_project_control/run_logs/phase5r_d3_catchup_check_log.csv`. Child C7 output is discarded rather than copied into D3 logs. Standard launchd output and error use `/Users/messssi/Library/Logs/phase5r_d3_launchd_stdout.log` and `/Users/messssi/Library/Logs/phase5r_d3_launchd_stderr.log`; keeping these launchd-opened files outside the protected Desktop tree avoids `EX_CONFIG` before wrapper startup. No credential value or SMTP configuration content may be written to these artifacts.

## Activation Boundary

D3 generation and verification do not install or load the LaunchAgent and do not invoke C7. Only manual execution of the D3 installer may migrate the active scheduler. The installer uses a temporary inhibit so the required `RunAtLoad` check cannot invoke C7 during installation; the next periodic check performs any due catch-up.
