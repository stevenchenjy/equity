# Phase 5R-D2 Verification Report

Generated: `2026-07-09T16:51:59-05:00`

## Required Checks

- **PASS** - active_decision_state.yaml was read: workflow=weekly_conviction; pipeline=phase5r_c7.
- **PASS** - active workflow is weekly_conviction: source=active_decision_state.yaml.
- **PASS** - C7 is marked as the active pipeline: active_pipeline=phase5r_c7.
- **PASS** - C2/C3/D1 remain deprecated or parked: D1 installed=False; loaded=False.
- **PASS** - plist template was created: label=com.steven.phase5r.weeklyconviction.
- **PASS** - install script was created: manual bootstrap only.
- **PASS** - uninstall script was created: preserves project artifacts.
- **PASS** - status script was created: read-only status check.
- **PASS** - scheduler points only to C7 weekly pipeline: ProgramArguments=['/Library/Frameworks/Python.framework/Versions/3.13/bin/python3', '/Users/messssi/Desktop/equity/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py'].
- **PASS** - scheduler excludes C2/C3/D1 references: old_refs=[].
- **PASS** - scheduler has weekly timing only: StartCalendarInterval={'Weekday': 5, 'Hour': 9, 'Minute': 5}.
- **PASS** - scheduler has no StartInterval: StartInterval absent.
- **PASS** - scheduler has RunAtLoad=false: RunAtLoad=False.
- **PASS** - scheduler has KeepAlive=false: KeepAlive=False.
- **PASS** - scheduler log paths are absolute: stdout/stderr paths match policy.
- **PASS** - scheduler was not installed: installed=False.
- **PASS** - scheduler was not loaded: loaded=False.
- **PASS** - C7 pipeline was not executed: C7 run log hash unchanged.
- **PASS** - no email was sent: successful_send_rows=2.
- **PASS** - no broker libraries imported: broker_imports=[].
- **PASS** - no order code created: order_calls=[].
- **PASS** - no archived legacy input used: archive_refs=[].
- **PASS** - SMTP config was not modified: metadata unchanged; config content not read.
- **PASS** - no SMTP secret value appears in artifacts: secret_markers=[].
- **PASS** - installer has no immediate-run action: forbidden_actions=[].
- **PASS** - Phase 5R-E was not created: paths=[].
- **PASS** - all static D2 outputs exist: missing=[].
- **PASS** - all declared D2 inputs exist: missing=[].

## Schedule

- Label: `com.steven.phase5r.weeklyconviction`.
- Schedule: Thursday at 09:05 local time.
- Pipeline: `phase5r_c7` only.
- Installation status: not installed.
- Load status: not loaded.

## Boundary

D2 prepared scheduler artifacts only. It did not run C7, send email, install or load launchd, access a broker, create transaction code, read archived inputs, modify SMTP configuration, expose an SMTP secret value, or create Phase 5R-E.
