# Phase 5R-C8 Canonical Active-State Policy

## Purpose

Phase 5R has one canonical low-attention operating workflow:
`daily_decision / phase5r_daily`. Historical C1–C7, Phase 0, model-pilot,
replay, and shadow artifacts are isolated beneath
`11_archive/phase5r_retired_20260831/`. Their existence never authorizes them
as decision inputs, senders, providers, or schedulers.

## Authority Order

1. `00_project_control/active_decision_state.yaml`
2. `00_project_control/phase5r_c8_allowed_active_inputs.csv`
3. Current local account, positions, and execution-reconciliation state
4. Current B2 market and official SEC evidence
5. Current C9 deterministic portfolio/risk outputs
6. Current daily decision and brief
7. Daily delivery ledger

Historical reports cannot override this order. Archived folders are excluded
without reading their contents.

## Active Workflow

- Workflow: `daily_decision`
- Pipeline: `phase5r_daily`
- Primary decision: `daily_account_aware_decision`
- Analysis: multiple local refresh slots, with one final decision after
  18:30 ET
- Email: at most one weekday daily brief; weekend material-change only
- Authorized sender: `send_phase5r_daily_email.py`
- Execution: manual and outside the repository

The only standalone active launchd jobs are:

- `com.steven.phase5r.dailyrefresh`
- `com.steven.phase5r.dailydecision`

`dailybrief`, `weeklyconviction`, `weeklycatchup`, and `llmshadow` remain
unloaded and their installers are archived. The daily-refresh launcher reads
only the market-data credential; no model credential or provider path exists
in the active scheduler.

## Stale-File Guard

- C2/C3 direct daily delivery and C1 composition are retired.
- C5/C6/C7 weekly research, composition, and delivery are historical evidence
  only and cannot send.
- D1/D2/D3 schedulers are retired and unloaded.
- B2 human previews are context only; the daily pipeline reads source CSV/JSON
  evidence rather than old preview prose.
- `current_positions.local.csv` and `current_account_state.local.json` are the
  only current local portfolio sources.
- Model artifacts cannot influence the canonical decision or normal daily
  email. Restoring any provider code is a separately reviewed future project,
  not an active configuration switch.

## Pipeline Requirement

Every daily entrypoint validates `active_decision_state.yaml` and the
maintenance inhibit before reading decision-facing inputs or attempting
delivery. Missing or conflicting state blocks the run. The sender independently
checks the daily state, date, decision artifact, duplicate ledger, and manual
execution boundary before opening SMTP configuration.

## Safety Boundary

This policy authorizes no broker connection, broker-account read, order code,
automatic portfolio action, archived input, provider credential read, model
canonical influence, or trade. Weekly files may be retained or inspected for
audit, but must not be invoked by the canonical workflow.
