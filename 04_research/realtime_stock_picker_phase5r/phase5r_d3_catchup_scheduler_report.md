# Phase 5R-D3 Catch-up Scheduler Report

## Outcome

Phase 5R-D3 prepares a stateful weekly catch-up scheduler for the active C7 conviction pipeline. It closes the missed-launchd-run gap by checking at user-session load and every 900 seconds while awake.

## Decision Flow

1. Validate the active weekly C7 workflow and safety flags.
2. Compute the ISO weekly cycle and Thursday 09:05 local due time.
3. Read successful C6 delivery rows.
4. Skip when not due or already sent.
5. When due and unsent, acquire a nonblocking file lock and re-check C6.
6. Persist a once-per-cycle attempt before invoking C7.
7. Accept success only for C7 return zero plus exactly one qualifying new C6 send row.

## Scheduler Shape

- Label: `com.steven.phase5r.weeklycatchup`
- `RunAtLoad=true`
- `KeepAlive=false`
- `StartInterval=900`
- No `StartCalendarInterval`
- Absolute Python, wrapper, working-directory, stdout, and stderr paths

The interval is check-only. Confirmed C6 delivery, the attempt ledger, and the lock prevent repeated automatic email behavior.

## Migration State

At D3 preparation time, D2 is the installed and loaded scheduler and D3 is neither installed nor loaded. The manual D3 installer is responsible for the cutover. It preserves D2 project artifacts and prevents C7 from running during bootstrap with a temporary install inhibit.

## Safety Boundary

D3 does not read SMTP configuration, import broker libraries, access broker accounts, create order code, run daily email workflows, use archived holding inputs, or create Phase 5R-E. Manual trade execution remains the only allowed execution mode.
