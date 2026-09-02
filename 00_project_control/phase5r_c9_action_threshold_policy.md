# Phase 5R-C9 Action Threshold Policy

## Current Positions

- If dynamic weight is above 8%, generate a whole-share `trim_specific_shares_review` scenario unless an independent thesis break requires `exit_review`.
- The trim count is the minimum whole-share reduction whose resulting current-price weight is at or below 8%; it is recalculated every run.
- If dynamic weight is at or below 8% and research remains adequate, use `hold`; do not produce a concentration-only trim.
- A current holding receives no add proposal unless the current deterministic
  evidence and every portfolio gate independently support it.

## Allowed Exact Actions

`hold`, `trim_specific_shares_review`, `add_specific_dollars_review`, `core_allocation_tranche_review`, `wait_for_pullback`, `watch_only`, `reject`, and `exit_review`.

Every portfolio-changing review must set:

- `human_confirmation_required=yes`
- `automatic_action_allowed=no`

Routine HOLD/WATCH rows set `human_confirmation_required=no` and still set
`automatic_action_allowed=no`.

## Maximum Entry and Trim Conditions

Maximum buy price is blank when no purchase review is selected. Conditional core plans use the latest quality-`ok` SPY reference price as a do-not-pay-above ceiling and also require a cleared maintenance state, valid current account state, compliant post-allocation weights, and a fresh human confirmation.

Trim conditions state the refreshed dynamic-weight threshold and current minimum whole-share scenario. Research evidence can still cause hold, trim, or exit review independently of concentration.

## New Individual-Stock Eligibility

An individual stock always requires a controlled packet, complete source-bound
valuation, passing portfolio fit, feasible whole-share sizing, and resulting
weights within caps. Evidence then maps to the highest supported tier:

- starter: score `7.0`, expected upside `10%`, reward/risk `1.25`, entry `5.5`, target `3%`;
- normal: score `7.5`, expected upside `15%`, reward/risk `2.0`, entry `6.0`, target `5%`;
- high conviction: score `8.25`, expected upside `25%`, reward/risk `2.5`, entry `6.5`, target `6%`.

All tiers require `medium_high` or `high` confidence except high conviction,
which requires `high`. A small-account one-share exception may overshoot the
tier target by at most two percentage points, but never the default
single-stock cap or active-sleeve hard cap.

Missing upside or reward-to-risk evidence is never invented. The candidate becomes `wait_for_more_evidence` or `watch_only`, not `eligible_buy_review`.
