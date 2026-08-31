# Phase 5R-D3G Failed-Cycle Recovery Policy

Generated: `2026-07-18T18:02:25-04:00`

## Bounded D3 behavior

D3 records one C7 attempt per weekly cycle. A failed attempt remains guarded, and later automatic checks do not immediately rerun C7. The guard may be released only by the explicit recovery command for the current cycle or by progression to a new weekly cycle.

A successful C6 delivery remains final for its cycle. Neither failure recovery nor a new scheduler check may bypass the delivery-status duplicate guard.

## Recovery command

`07_automation/scheduler/reset_phase5r_d3_failed_cycle_after_fix.sh`

The command accepts `--cycle-id YYYY-Www`; if omitted, it uses the current local ISO week. `--check-only` performs all recoverability checks without changing D3 state.

Before clearing a guard, the command must:

1. Validate the protected active-state boundary (`weekly_conviction`, `phase5r_c7`, manual execution, no broker/order permission).
2. Confirm D3 is loaded.
3. Confirm the C7 and C6 program files and local state/status inputs exist.
4. Refuse if a qualifying `sent=yes` C6 row exists for the target cycle.
5. Refuse any cycle other than the current cycle.
6. Require a current-cycle D3 attempt with outcome `catchup_failed`.
7. Refuse if that cycle already used its one manual recovery reset.
8. Run the C6 composer as a no-send validation.
9. Acquire the D3 lock and repeat the sent/history/state checks before the atomic state update.

The reset preserves the failed attempt inside `cycle_recovery_history`, removes only its active current-cycle attempt guard, and writes `00_project_control/run_logs/phase5r_d3g_recovery_log.csv`. It never runs C7, invokes the C6 sender, or sends email.

After a successful reset, the next D3 check may make one normal C7 attempt. If that attempt fails, the newly recorded failed guard blocks further retries because the cycle's recovery history already contains one reset. If delivery succeeds, the existing C6 status guard prevents another send.

## Verification boundary

D3G verification uses `--check-only`. It must not clear the live current-cycle failed state. Running the state-changing reset is a separate manual operational decision because the next D3 check may invoke live C7 delivery.

