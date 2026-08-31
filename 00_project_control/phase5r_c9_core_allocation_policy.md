# Phase 5R-C9 Core Allocation Policy

## Separation

The broad-market core sleeve is separate from individual-stock research. SPY is an approved canonical broad-market benchmark and may be evaluated as a core candidate, not as a momentum stock.

Targets come from the validated current account state. Dollar amounts are
calculated from that state at runtime; this policy does not preserve a dated
account total or a fixed deployment amount. The active production configuration
currently defines the percentage targets and concentration caps.

Targets are planning constraints, not automatic purchase instructions.

## Cash-Deployment Approaches

1. `no_deployment_until_next_review`
2. `three_tranche_core_plan`: three independently confirmed reviews sized from
   the current account state
3. `partial_core_plus_cash_reserve`: a partial core review while retaining at
   least the current configured cash reserve

Each purchase tranche requires SPY market quality `ok`, maintenance inactive, current account state valid, post-allocation compliance, a refreshed maximum-entry condition, and independent human confirmation.

While the C9 maintenance inhibit is active, all purchase tranches are `blocked_maintenance`. Availability of cash alone never selects an ETF purchase.
