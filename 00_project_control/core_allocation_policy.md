# Phase 5R-C9 Core Allocation Policy

## Separation

The broad-market core sleeve is separate from individual-stock research. SPY is an approved canonical broad-market benchmark and may be evaluated as a core candidate, not as a momentum stock.

Targets come from the validated current account state. Dollar amounts are
calculated from that state at runtime; this policy does not preserve a dated
account total or a fixed deployment amount. The active production configuration
currently defines the percentage targets and concentration caps.

Targets are planning constraints, not automatic purchase instructions.

## Cash-Deployment Decision

1. `retain_cash_fallback`: selected whenever refreshed core evidence fails.
2. `core_starter_whole_share_review`: at most one whole share per review,
   bounded by the current core gap, deployable cash, range-position gate, and
   configured reserve.

The starter requires SPY market quality `ok`, technical-entry score at least
`5.0`, a 52-week-range percentile no
higher than `95`, maintenance inactive, valid current account state,
post-allocation compliance, and independent human confirmation. ETF valuation
is labeled not applicable rather than missing because the individual-company
EV/revenue model is not the relevant core-allocation test.

The individual-stock conviction score is not a core gate: its company earnings
and EV/revenue components are structurally not applicable to a broad-market
ETF. Core market/entry evidence and portfolio-allocation constraints are tested
directly instead.

While the C9 maintenance inhibit is active, the starter is `blocked_maintenance`. Availability of cash alone never selects an ETF review.
