# Phase 5R-C5 Deep Research Policy

## Purpose

Phase 5R-C5 converts the latest daily public-market signal set and the current private portfolio state into one weekly conviction review. It prioritizes thesis quality, holding horizon, valuation, filings, earnings, material company news, entry discipline, and portfolio fit.

## Weekly Boundary

- Current positions are read only from `05_risk_and_positions/current_positions.local.csv`.
- IOT and RBRK are current local positions in this phase. No archived holding record is an input.
- Current positions are reviewed before new candidates.
- The output may identify zero to two `eligible_buy_review` candidates in a week.
- Every label requires independent human review and has no transaction authority.
- The workflow does not send email, use a scheduler, access a broker, or automate portfolio changes.

## Portfolio Application

- A current position above the 8% hard cap cannot receive `add_review`.
- A hard-cap breach defaults to `trim_review` unless thesis evidence supports `exit_review`.
- With the active stock sleeve above 30%, new names normally remain `wait_for_pullback` or `watch_only`.
- Company quality and portfolio fit are scored separately. A strong business cannot erase a concentration breach.

## Cadence

The research queue is generated once for weekly review. Routine daily price movement does not create a new action. The next review date is one week after generation unless a material thesis or risk change warrants earlier human review.
