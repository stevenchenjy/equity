# Phase 5R-C9A Scheduler Maintenance Policy

## Active State

The C9 maintenance inhibit is active at:

`07_automation/scheduler/phase5r_c9_maintenance_inhibit.local.json`

Its C9A state is:

```json
{
  "active": true,
  "reason": "phase5r_c9_migration",
  "created_at": "2026-07-19T20:57:52-04:00",
  "allowed_pipeline": "none"
}
```

The local file is gitignored and permissioned for the local user only.

## D3 Behavior

D3 remains loaded and may continue its 15-minute checks. After validating the active workflow and reading delivery state, D3 reads the C9 inhibit before local attempt-state, successful-cycle, due-time, lock, or subprocess decisions.

When the inhibit is active:

- D3 records `decision=maintenance_inhibit`;
- the reason is `phase5r_c9_migration`;
- `c7_invoked=no`;
- sent-row before and after counts are equal;
- no cycle lock is acquired;
- no C7 or C6 sender subprocess is started;
- the D3 attempt state is not mutated.

If the inhibit file exists but is malformed, has a non-boolean `active`, lacks a reason, or allows anything other than `none` while active, D3 fails closed with `maintenance_inhibit`.

## Existing Cycle Guard

The existing successful-send, due-time, lock, and once-per-cycle attempt guards were not weakened or removed. While maintenance is active, the maintenance decision intentionally occurs before those execution gates. When the inhibit is later cleared, the pre-existing guards resume unchanged.

## Control Scripts

- `set_phase5r_c9_maintenance_inhibit.sh` atomically writes the active state with a fresh timestamp and `allowed_pipeline=none`.
- `clear_phase5r_c9_maintenance_inhibit.sh` atomically marks the file inactive; it does not delete the record.

The clear script must not be run during C9A.

## Clearance Gates

Clearance requires all of the following and an explicit human decision:

1. The future local account-state file exists and is human-confirmed.
2. C9 weight calculations use shares, canonical current price, and current account total only.
3. Account/holdings/cash reconciliation passes.
4. C4R, C5 portfolio-fit/action outputs, C5T scenarios, C6 email artifacts, and C7 status outputs are regenerated and verified.
5. No active output contains current claims derived from `1000`, `29.59%`, `17.75%`, or `47.34%`.
6. C9 verification proves one-cycle and one-send protections remain effective.
7. The active-decision state and active-input registry are updated for the C9 workflow.

Until every gate passes, `allowed_pipeline` remains `none`.
