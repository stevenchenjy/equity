# Phase 5R-C9 Dynamic Weight Policy

## Current-Weight Formula

For every held ticker:

`current_weight_pct = current_shares × latest_canonical_B2_price ÷ account_total_value × 100`

The account denominator is `2500.00 USD` for the initial confirmed C9 state. After a validated C9B reconciliation is explicitly applied, the denominator is the updated current `account_total_value`. The formula and price provenance must be written with each dynamic weight.

## Stored Percentage Boundary

`position_pct` in `current_positions.local.csv` is historical/reference data only. C9 may emit it as `stored_historical_position_pct` and calculate a comparison difference, but no concentration status, score, label, target, share scenario, allocation, or email wording may depend on it.

## Concentration and Sleeve Rules

- Above `8%`: `above_hard_cap`.
- Above `6%` through `8%`: `above_default_cap`.
- At or below `6%`: `within_default_cap`.
- Combined active-stock sleeve at or below `20%`: `within_target`.
- Above `20%` through `30%`: `above_target_within_hard_cap`.
- Above `30%`: `above_hard_cap`.

Current positions are recalculated independently. A position at or below 8% cannot receive a concentration-only trim label. A combined sleeve at or below 30% cannot be described as above the hard cap.

## Price Quality

Held tickers are appended to the B2 public snapshot as price-monitoring rows only. They remain excluded from the B2 candidate universe. C9 stops if a held price is missing or not quality `ok`; it never falls back to free-form notes or old output files.
