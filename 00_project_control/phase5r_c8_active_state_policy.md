# Phase 5R-C8 Active State Policy

## Purpose

Phase 5R-C8 separates the currently authoritative weekly workflow from historical evidence and parked tools. Active scripts must resolve their workflow state and permitted inputs from the C8 registries before making a decision-facing update.

## Authority Order

1. `00_project_control/active_decision_state.yaml`
2. `00_project_control/phase5r_c8_allowed_active_inputs.csv`
3. Current C4/C4R portfolio state
4. Current B2 public market data
5. Current C5 conviction research
6. Current C5T manual action planning
7. Current C6 weekly brief outputs
8. Current C7 pipeline status and logs

Historical reports may explain provenance but cannot override this order.

## Active Workflow

- Workflow: `weekly_conviction`.
- Pipeline: `phase5r_c7`.
- Primary decision: `no_action_until_next_review`.
- Next review: `2026-07-16`.
- Email delivery: C7 only, through the C6 delivery component.
- Execution: independent manual decisions only.

## Stale-File Guard

- Archived folders and archived IOT/RBRK records are never active inputs.
- `current_positions.local.csv` is the only current-position source for IOT and RBRK.
- C2, C3, and C1 daily delivery artifacts are deprecated or parked.
- D1 remains parked and uninstalled.
- Old daily watchlists are evidence only.
- C6 delivery remains a component of C7 and is not the active standalone pipeline.

## Pipeline Requirement

The C7 runner must read and validate `active_decision_state.yaml` before reading current positions, market data, delivery status, or any other decision input. A missing, malformed, or conflicting state blocks the run.

## Safety Boundary

No scheduler activation, broker connection, automatic portfolio action, archived input, credential handling change, file deletion, file movement, or Phase 5R-D2 is authorized by C8.
