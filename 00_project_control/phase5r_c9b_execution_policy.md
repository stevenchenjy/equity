# Phase 5R-C9B Manual Execution Policy

## Purpose

`06_execution_records/manual_executions.local.csv` is the sole C9B manual execution-intake source. It is local, Git-ignored, and contains only facts entered or confirmed by the human owner. C9B never connects to a broker and never places, changes, or cancels an order.

## State Contract

- `pending_fill`: fill date, fill price, fees, cash values, and account total remain blank. Current positions and account state must remain byte-for-byte unchanged. No final post-execution recommendations are generated.
- `filled`: fill date, positive numeric fill price, explicit fees (including confirmed zero), and reconciled shares are required before account reconciliation can be applied.
- `partial_fill`: `shares` is changed to the actual whole shares filled, `shares_after` is recalculated, and notes must state that these are actual filled shares. Remaining unfilled quantity is handled outside this repository; C9B does not modify an order.
- `cancelled`: original positions and account state remain unchanged. Fill and reconciled-account fields remain blank.

An execution row is evidence, not an instruction. Every mutation of the canonical positions/account files requires a separate explicit `--apply` invocation after validation.

For a confirmed full fill, record only actual values with:

`python3 09_scripts/phase5r/validate_phase5r_c9b_execution_fill.py --execution-id C9B-IOT-PENDING-001 --record-status filled --fill-date YYYY-MM-DD --fill-price CONFIRMED_PRICE --fees CONFIRMED_FEES`

Then run reconciliation without `--apply` first to inspect the preview. Applying canonical state requires the separate explicit form:

`python3 09_scripts/phase5r/reconcile_phase5r_c9b_account_state.py --execution-id C9B-IOT-PENDING-001 --apply`

Placeholders must be replaced only with human-confirmed values. These commands record/reconcile an already-completed manual execution; they do not communicate with or control an order venue.

## Current Intake

The current record is `C9B-IOT-PENDING-001`: a user-reported pending sale of 3 IOT shares, from 8 shares to 5. The order type and submission timestamp are not known precisely, so they are not invented. The fill price and all post-fill financial values remain blank.

## Boundaries

- No broker libraries, credential reads, order endpoints, email sends, schedulers, or archived position files.
- The C9 maintenance inhibit remains active throughout validation and reconciliation.
- The local execution file is mode `0600` and must stay Git-ignored.
- SMTP configuration is outside the execution workflow and must not be read or modified.
