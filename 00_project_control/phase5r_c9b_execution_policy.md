# Phase 5R-C9B Manual Execution Policy

## Purpose

`06_execution_records/manual_executions.local.csv` is the sole C9B manual execution-intake source. It is local, Git-ignored, and contains only facts entered or confirmed by the human owner. C9B never connects to a broker and never places, changes, or cancels an order.

## State Contract

- `pending_fill`: fill date, fill price, fees, cash values, and account total remain blank. Current positions and account state must remain byte-for-byte unchanged. No final post-execution recommendations are generated.
- `filled`: fill date, positive numeric fill price, explicit fees (including confirmed zero), and reconciled shares are required before account reconciliation can be applied.
- `partial_fill`: `shares` is changed to the actual whole shares filled, `shares_after` is recalculated, and notes must state that these are actual filled shares. Remaining unfilled quantity is handled outside this repository; C9B does not modify an order.
- `cancelled`: original positions and account state remain unchanged. Fill and reconciled-account fields remain blank.

An execution row is evidence, not an instruction. Every mutation of the canonical positions/account files requires a separate explicit `--apply` invocation after validation.

For a confirmed full fill, record only actual values with an explicit execution
identifier:

`python3 09_scripts/phase5r/validate_phase5r_c9b_execution_fill.py --execution-id EXECUTION_ID --record-status filled --fill-date YYYY-MM-DD --fill-price CONFIRMED_PRICE --fees CONFIRMED_FEES`

Then run reconciliation without `--apply` first to inspect the preview. Applying canonical state requires the separate explicit form:

`python3 09_scripts/phase5r/reconcile_phase5r_c9b_account_state.py --execution-id EXECUTION_ID --apply`

Placeholders must be replaced only with human-confirmed values. These commands record/reconcile an already-completed manual execution; they do not communicate with or control an order venue.

## Current-State Authority

This policy contains no current execution identifier, ticker, share count, or
fill state. The private local execution ledger and the validated pending,
confirmed, and reconciliation reports are the only execution-state authority.
Historical one-off setup and verification material is archived.

## Boundaries

- No broker libraries, credential reads, order endpoints, email sends, schedulers, or archived position files.
- The C9 state must validate before processing; a cleared state may authorize
  only the canonical `phase5r_daily` workflow.
- The local execution file is mode `0600` and must stay Git-ignored.
- SMTP configuration is outside the execution workflow and must not be read or modified.
