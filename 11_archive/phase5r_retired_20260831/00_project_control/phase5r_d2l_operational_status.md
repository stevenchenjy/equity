# Phase 5R-D2L Operational Status

Observed: `2026-07-09T16:57:12-05:00`

## Current State

| Control | Operational value |
| --- | --- |
| Active workflow | `weekly_conviction` |
| Active pipeline | `phase5r_c7` |
| Primary decision | `no_action_until_next_review` |
| Next review date | `2026-07-16` |
| D2 installed | `yes` |
| D2 loaded | `yes` |
| D1 installed | `no` |
| D1 loaded | `no` |
| C2/C3 daily workflows | `deprecated or parked` |

## Launchd Definition

The loaded job uses the installed plist that exactly matches the canonical D2 template. Its only program arguments are:

```text
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
/Users/messssi/Desktop/equity/09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py
```

The job has one weekly calendar trigger: Thursday at 09:05 local time. It has no interval trigger, no load-time execution, and no keep-alive behavior.

## Operating Boundary

The scheduler automates the weekly research-email pipeline only. Portfolio execution remains manual. The job has no broker, order, trade, daily, intraday, archived-input, or repeated-notification authority.

