# Phase 5R-D3F Catch-up Scheduler Hotfix Plan

## Confirmed Failure State

The live D3 LaunchAgent was installed and registered, D2 was unloaded and its installed plist was absent, and the legacy `phase5r_d3_install_inhibit` file remained present. The D3 local state contained no cycle attempt or active verification flag. The visible `verification_flag_active` reason was a historical one-shot verification log entry, not a persistent state flag.

Two defects were confirmed:

1. `install_phase5r_d3_catchup_scheduler.sh` assigned the zsh read-only special parameter `status` inside its exit trap.
2. launchd returned `78: EX_CONFIG` before starting the wrapper because its standard-output and standard-error paths were under the protected Desktop tree. A temporary inhibited diagnostic LaunchAgent succeeded when those paths were placed under `~/Library/Logs`.

## Hotfix Changes

1. Rename the exit-trap variable from `status` to `exit_code` and statically reject assignments to `status`, `path`, `UID`, `EUID`, or `RANDOM` in D3 shell scripts.
2. Move only launchd stdout/stderr to `/Users/messssi/Library/Logs`; keep the wrapper, working directory, C6 status, D3 audit log, lock, and local state in the project.
3. Increase the installer protected-RunAtLoad confirmation window from 10 to 30 seconds.
4. Add explicit wrapper safe-check support and a D3F verification-inhibit file that is independent of the legacy install inhibit.
5. Treat any true `verification_flag_active`, `install_inhibit`, or `protected_verification` local-state flag as a fail-closed protection.
6. Add an explicit unblock script that validates the active workflow, active pipeline, D2/D3 launchd state, installed plist, C7 path, and local state before clearing legacy protection.
7. Make the status script distinguish historical `verification_only` decisions from current persistent protection state.

## Verification and Cutover Sequence

1. Keep the legacy install inhibit present while patching and reloading D3.
2. Confirm the repaired LaunchAgent executes the wrapper and records `install_inhibit_active`, with unchanged C6 and C7 logs.
3. Create the temporary D3F verification inhibit.
4. Run syntax, plist, shell-variable, pipeline-reference, locking, cycle-guard, and live launchd checks.
5. Exercise the unblock script in check-only mode and then clear legacy protection while preserving the D3F verification inhibit.
6. Confirm C6, C7, SMTP metadata, broker/order boundaries, and Phase 5R-E remain unchanged.
7. End verification, then explicitly remove the temporary D3F hold through the unblock script. The unblock command itself never invokes C7 or sends email.

## Final Intended State

- D2: unloaded and not installed.
- D3: installed and loaded.
- D3 program: the Phase 5R-D3 wrapper only.
- Persistent verification/install protection: clear.
- Current cycle duplicate controls: C6 sent-row check, nonblocking lock, and durable once-per-cycle attempt ledger.
- Catch-up: eligible on the next D3 interval when Thursday 09:05 local time has passed and the cycle has no qualifying successful C6 send.
