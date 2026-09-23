# Phase 5R-C9B Price Guidance Policy

## Evidence

C9B uses the canonical B2 public snapshot for the reference price, timestamp, daily high-low range, volume, average volume, relative volume, and dollar volume. Public prices may be delayed and are not broker quotes. A fill price is never inferred from these values.

## Slippage Review Formula

The daily high-low range as a percentage of reference price is the volatility proxy. Dollar volume is the liquidity proxy. The maximum-slippage review value is deterministic:

- at least $5 billion dollar volume and range no more than 2%: 0.15%;
- at least $1 billion otherwise: 0.25%;
- range at least 5%: 10% of the daily range, bounded to 0.50%-1.00%;
- range at least 3%: 10% of the daily range, bounded to 0.40%-0.75%;
- otherwise: 0.30%.

This is a review tolerance, not an execution guarantee. A reference sell floor is `reference_price * (1 - maximum_slippage_pct / 100)`. A reference buy ceiling is `reference_price * (1 + maximum_slippage_pct / 100)`. These derived levels are human-review references only.

## Order-Style Framework

Market-at-open is not the default. Sell reviews prefer `limit_review`, `staged_limit_review`, `wait_for_market_open_review`, or `no_action`. A security with an already-submitted order receives `no_action` from C9B until the fill or cancellation is confirmed; C9B does not recommend modifying that order. Limit orders may not execute, may fill only partially, or may miss a fast market.

Guidance expires at the earlier of the next market-data refresh, a material company/market event, or the stated validity window. A stale/invalid public price, a breached portfolio rule, a thesis change, or an execution state change cancels the guidance.

## Boundary

Every price, slippage percentage, order style, share count, and resulting weight remains a manual-review reference. `human_confirmation_required=yes` and `automatic_action_allowed=no` are mandatory.
