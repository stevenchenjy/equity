# Equity Research — Action Threshold Policy

## Current Positions

The [October 6 owner allocation policy](allocation_policy.md) removes fixed
single-stock default and hard caps. All labels, score inputs, share arithmetic
and report wording must use that effective policy, never archived percentages.

- A large individual weight alone cannot generate `trim_specific_shares_review`
  or a concentration-only score penalty when the fixed name cap is disabled.
- A supported thesis break, adverse company evidence, aggregate stock breach
  or strategy-specific risk condition may still support a reduction/exit review.
- Whole-share reduction quantities must name the actual current condition that
  justifies them; never calculate shares needed to meet a removed name limit.
- If research supports holding and no applicable condition requires reduction,
  use `hold`. A maintained plan remains subject to its own evidence and deadline.
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

Trim conditions identify the applicable aggregate, strategy-specific or sourced investment condition and current whole-share scenario. There is no fixed single-name allocation threshold. Research evidence can still cause hold, trim, or exit review.

## New Individual-Stock Eligibility

An individual stock always requires a controlled packet, complete source-bound
valuation, passing portfolio fit, feasible whole-share sizing, and resulting
weights within the aggregate stock maximum while preserving the broad-core
minimum. Evidence eligibility retains these quality thresholds:

- starter: score `7.0`, expected upside `10%`, reward/risk `1.25`, entry `5.5`;
- normal: score `7.5`, expected upside `15%`, reward/risk `2.0`, entry `6.0`;
- high conviction: score `8.25`, expected upside `25%`, reward/risk `2.5`, entry `6.5`.

All tiers require `medium_high` or `high` confidence except high conviction,
which requires `high`. They are evidence classifications, not fixed size tiers.
The owner replaced the former 3%/5%/6% initial-size ceilings with company-specific
source-bound sizing. A growth proposal requires a current maintained plan that
states desired allocation, investment rationale, downside/countercase,
invalidation and retained sources in its validated `reviewed_allocation`.
Its source-bound entry ceiling and reassessment/invalidation levels remain
conditional review inputs, never assumed broker orders or guaranteed fills. Missing size justification leaves the proposed
size unresolved; it is not filled with an equal-weight default or the entire
remaining sleeve. The final whole-share amount remains bounded by that admitted
plan, aggregate stock room, the core-floor reservation, actual available cash
and any applicable strategy-specific budget. Rounding does not waive those
constraints. Core whole-share rounding can exceed its baseline target because
the core percentage is a floor; it cannot justify a forced reduction of an
existing core holding.

Missing upside or reward-to-risk evidence is never invented. The candidate becomes `wait_for_more_evidence` or `watch_only`, not `eligible_buy_review`.
