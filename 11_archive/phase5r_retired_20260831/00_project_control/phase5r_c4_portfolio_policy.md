# Phase 5R-C4 Portfolio Policy

## Private Local State

The optional file `05_risk_and_positions/current_positions.local.csv` is the canonical private portfolio-state input. It is ignored by Git and is not created or populated during C4. Templates and schema files contain illustrative or blank data only.

## Required Position Fields

- `ticker`
- `entry_date`
- `entry_price`
- `position_pct`
- `shares_optional`
- `thesis`
- `horizon_class`
- `planned_review_date`
- `max_loss_pct_of_account`
- `invalidation_rule`
- `current_action`
- `notes`

Active positions should include a numeric `position_pct` so concentration can be evaluated. `shares_optional` may remain blank. Watch-only ideas must use `position_pct=0` or leave it blank.

## Manual Decision Boundary

- Portfolio state is research context, not an instruction to transact.
- The system may identify buy, wait, hold, add-review, trim-review, exit-review, reject, or watch-only decisions.
- Every action requires independent human confirmation outside the project.
- No broker account, real-time account balance, order route, or execution system is read or used.
- Existing D1 scheduler artifacts remain parked and inactive.
