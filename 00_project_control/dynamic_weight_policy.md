# Equity Research — Dynamic Weight Policy

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

The [October 6 owner allocation policy](allocation_policy.md) is authoritative:
broad core has a 30% minimum and baseline target, aggregate individual stocks
have a 70% target and maximum, and cash target/reserve are zero. Fixed default
and hard single-stock caps are disabled. Historical account-record percentages
and archived policy values must not become fallback active limits.

- A held stock has no allocation-cap breach merely because its own weight is
  large. Report its current weight, loss exposure and evidence separately;
  do not manufacture a name-cap trim or concentration-only score penalty.
- Combined individual-stock weight at or below 70% is within its aggregate
  target/cap. Above 70% remains an aggregate breach and blocks additions.
- Broad-core weight below 30% is an allocation shortfall to address through
  qualified research. At or above 30% satisfies the floor; being above the
  baseline target is not an automatic reduction condition.
- Strategy-specific tactical exposure and planned-loss budgets still apply.

Current positions are recalculated independently from validated account facts.
A combined sleeve within its effective cap cannot be described as above it.
Research may still recommend a reduction or exit for sourced business, valuation
or strategy-specific risk reasons; removal of a name cap is not a permanent hold.

## Price Quality

Held tickers are appended to the B2 public snapshot as price-monitoring rows only. They remain excluded from the B2 candidate universe. C9 stops if a held price is missing or not quality `ok`; it never falls back to free-form notes or old output files.
