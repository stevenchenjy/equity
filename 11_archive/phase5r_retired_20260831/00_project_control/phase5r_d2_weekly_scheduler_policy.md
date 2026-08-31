# Phase 5R-D2 Weekly Scheduler Policy

## Purpose

Phase 5R-D2 prepares a local macOS launchd job for the active C7 weekly conviction pipeline. D2 creates scheduler artifacts and instructions only; installation and loading remain separate manual actions.

## Authoritative State

- Current workflow: `weekly_conviction`.
- Active pipeline: `phase5r_c7`.
- Primary decision: `no_action_until_next_review`.
- Manual execution only: `yes`.
- Archived folders allowed as inputs: `no`.
- D1 daily scheduler: `parked_uninstalled`.

The source of truth is `00_project_control/active_decision_state.yaml`. C7 validates that state before reading its other active inputs.

## Schedule

- Frequency: once weekly.
- Day: Thursday (`Weekday=5` in launchd).
- Time: 9:05 AM local time.
- `RunAtLoad`: false.
- `KeepAlive`: false.
- `StartInterval`: prohibited.

The active state has no `next_review_day` or schedule override, so D2 uses the requested Thursday 09:05 default. The next review date, `2026-07-16`, falls on Thursday.

## Execution Boundary

The launchd template may invoke only:

`/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/messssi/Desktop/equity/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py`

C7 may produce one weekly brief and delegate at most one email delivery. D2 cannot place orders, access a broker, read archived holdings, run daily workflows, or create repeated notifications.

## Activation Boundary

- D2 generation does not copy a plist into `~/Library/LaunchAgents`.
- D2 generation does not call `launchctl bootstrap`, `load`, `start`, or `kickstart`.
- Installation occurs only when Steven manually executes the install script.
- Uninstallation preserves templates, reports, and logs.
- D1, C2, and C3 remain inactive historical capabilities.

