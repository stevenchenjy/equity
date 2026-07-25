# Phase 5R-C9A Account-State Audit Report

## Outcome

The audit found a complete stale-denominator chain from current position intake through the weekly email. C9A did not replace the financial logic; it isolated the chain behind an active D3 maintenance inhibit and documented the required migration.

## Main Finding

The proposed `2500 USD` account total is not represented by a canonical account-state input. The active workflow still uses the old state in three ways:

1. `current_positions.local.csv` stores `29.59%` for IOT and `17.75%` for RBRK and describes a `1000 USD` account.
2. C4/C4R trust those percentages, and C4R also hardcodes `ACCOUNT_VALUE_USD = 1000.0`.
3. C5, C5T, C6, and C7 inherit the resulting `47.34%` sleeve, concentration labels, scenarios, and email wording.

The stale dependency path is:

`stored position_pct / 1000 USD notes → C4/C4R → C5 portfolio fit and labels → C5T scenarios → C6 brief → C7 delivery → D3 catch-up`

## Required Regeneration Under C9

- C4 portfolio state and C4R concentration outputs.
- C5 research-queue portfolio context.
- C5 packet portfolio-fit, risk, and label fields.
- C5 weekly portfolio-fit scores and position/candidate recommendations.
- C5 weekly conviction memo.
- C5T scenario table, checklist, triggers, report, and manual action plan.
- C6 subject, text, HTML, metadata, preview, and composition report.
- C7 latest status and research reports produced from those files.

## Inputs That Can Mostly Remain

- The canonical B2 public market-data pipeline and latest market snapshot can remain the price-data foundation.
- Company primary-source evidence can remain when still fresh.
- Shares and entry data in `current_positions.local.csv` remain the holdings foundation.

Mixed C5 company packets must still be regenerated because their evidence fields are combined with hardcoded portfolio-fit scores, stale risk wording, and fixed labels.

## Canonical C9 Direction

C9 must calculate each current weight as:

`shares × current canonical B2 market price ÷ current account total`

Account total, available cash, and external cash must come from a future, human-confirmed `current_account_state.local.json`. Stored `position_pct`, free-form price/account notes, and a `1000` fallback must not participate in current calculations.

## Scheduler Safety

D3 remains loaded. The gitignored C9 maintenance file is active with `allowed_pipeline=none`. A D3 safe check recorded:

- `decision=maintenance_inhibit`
- `reason=phase5r_c9_migration`
- `c7_invoked=no`
- `send_delta=0`

D3's existing successful-cycle and once-per-cycle guards remain in the script unchanged and resume when a future approved clearance marks the C9 inhibit inactive.

## Boundary

C9A created plans, maps, reports, and the scheduler guard only. It did not create account-state data, calculate C9 weights, select a C9 portfolio action, run C7, call the sender, send email, alter positions, read SMTP configuration contents, connect to a broker, or create order code.
