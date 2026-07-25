# Phase 5R-D3 Migration from D2 Plan

## Decision

D3 supersedes D2 as the active weekly scheduler after the user manually runs the D3 installer. D2 remains installed and loaded until that explicit migration; D3 generation and verification do not change live scheduler state.

## D2 Problem

D2 has one Thursday 09:05 `StartCalendarInterval` trigger. It has no stateful catch-up decision, delivery-status guard, or periodic post-wake check. A run missed while the Mac or user session is unavailable is therefore not reliably recovered.

## D3 Fix

D3 replaces calendar-only execution with `RunAtLoad=true` and `StartInterval=900`. Each launch is only a check. The wrapper computes the weekly due time, reads the C6 successful-delivery record, uses a lock, persists a once-per-cycle attempt, and invokes C7 only when catch-up is due and safe.

## Manual Cutover

The D3 installer performs one controlled cutover:

- Temporarily inhibits D3 delivery during bootstrap.
- Boots out `com.steven.phase5r.weeklyconviction` if loaded.
- Removes the installed D2 LaunchAgent plist so it cannot return at a later login.
- Does not delete any D2 project artifact.
- Installs and bootstraps `com.steven.phase5r.weeklycatchup`.
- Confirms the RunAtLoad check was inhibited before enabling ordinary periodic eligibility.

There is no interval in which both D2 and D3 are intentionally active. The first uninhibited D3 interval occurs after installation, not inside the installer.

## Rollback Boundary

The D3 uninstaller removes only the installed D3 LaunchAgent and does not automatically reinstall D2. Re-enabling D2 would require a separate, explicit user decision. D1 remains parked and uninstalled throughout.
