# Phase 5R-C9 Dynamic Weight Policy

## Current-Weight Formula

For every held ticker:

`current_weight_pct = current_shares × latest_canonical_B2_price ÷ account_total_value × 100`

The denominator is always the validated current `account_total_value`. The
formula, account timestamp, and price provenance must be written with each
dynamic weight. No historical account value or policy example may substitute
for the current local state.

## Stored Percentage Boundary

`position_pct` in `current_positions.local.csv` is historical/reference data only. C9 may emit it as `stored_historical_position_pct` and calculate a comparison difference, but no concentration status, score, label, target, share scenario, allocation, or email wording may depend on it.

## Concentration and Sleeve Rules

The active research overlay was set on 2026-09-14 to a 50% active-stock
hard cap and 15% default/hard single-stock caps. Use effective configured
values throughout these comparisons; the local financial record's inherited
30%/6%/8% fields are not the current research limits.

- Above `15%`: `above_hard_cap`.
- Above default through hard: `above_default_cap` (empty band while both are 15%).
- At or below `15%`: `within_default_cap`.
- Combined active-stock sleeve at or below `20%`: `within_target`.
- Above `20%` through `50%`: `above_target_within_hard_cap`.
- Above `50%`: `above_hard_cap`.

Current positions are recalculated independently. A position at or below the
effective single-stock hard cap cannot receive a concentration-only trim label.
A combined sleeve within its effective cap cannot be described as above it.

## Price Quality

Held tickers are appended to the B2 public snapshot as price-monitoring rows only. They remain excluded from the B2 candidate universe. C9 stops if a held price is missing or not quality `ok`; it never falls back to free-form notes or old output files.
