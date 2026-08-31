# Phase 5R-D3 Catch-up State Policy

## State Locations

- Template: `07_automation/scheduler/phase5r_d3_catchup_state.template.json`
- Documentation example: `07_automation/scheduler/phase5r_d3_catchup_state.local.json.example`
- Runtime local state: `00_project_control/run_logs/phase5r_d3_catchup_state.local.json`

The runtime file is machine-local operational state. The template and example contain no credentials.

## Authority

`active_decision_state.yaml` authorizes the workflow. The C6 delivery status CSV is authoritative for confirmed delivery. The D3 state file is an additional fail-closed attempt ledger and observability record; it cannot authorize email by itself.

## Required Fields

- `schema_version` identifies `phase5r_d3_catchup_state_v1`.
- `schedule` documents Thursday 09:05 local checks every 900 seconds.
- `cycle_attempts` maps an ISO cycle ID to one C7 attempt record.
- `last_check`, `last_cycle_id`, `last_decision`, and `last_reason` describe the latest ordinary check.
- `last_successful_cycle_id` records the latest observed confirmed cycle.
- `last_sent_rows_observed` records only a count, never message content or configuration.

## Update Rules

Immediately before C7 invocation, D3 atomically persists an `in_progress` attempt for the current cycle. After C7 returns, it updates that same entry with return code, send delta, completion time, and outcome. Atomic replacement prevents a partially written JSON file from becoming the normal committed state.

If the state file is missing, D3 creates it from safe defaults when a due invocation must be guarded. If it is invalid or cannot persist the attempt marker, D3 fails closed and does not invoke C7. A prior cycle attempt is never automatically erased or retried.

Routine observation updates are best-effort because the check log remains the audit trail. Verification-only and installer-inhibited checks do not mutate runtime state.

## Recovery

Do not edit or clear a cycle attempt merely to force another send. First compare the C6 delivery log, C7 status, and D3 check log. Any manual reset should be deliberate, preserve a backup, and occur only after confirming no delivery was made. D3 itself provides no reset command.
