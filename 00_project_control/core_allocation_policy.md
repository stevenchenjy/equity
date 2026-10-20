# Equity Research — Core Allocation Policy

## Approved index core

On 2026-10-19 ET the owner approved both **SPY and QQQM** for the index-core
sleeve. Their combined market value counts toward the 30% minimum and baseline
target. SPY remains the broad-market benchmark; QQQM supplies a more concentrated
large-company growth tilt. ETF is a product structure, not automatic core
eligibility: this approval does not include every ETF, sector fund or leveraged
product. The compatibility identifier `broad_core` remains valid for this
approved index-core purpose.

The two funds do not have separate 30% requirements. Calculate:

`core_weight_pct = (SPY shares × SPY canonical close + QQQM shares × QQQM canonical close) / current validated account value × 100`

An unheld approved fund contributes zero. Use each fund's own validated price;
never substitute SPY's price or entry evidence for QQQM. Direct company holdings
are counted in the individual-stock sleeve, not added again to the core total.
Assess their economic overlap with both funds separately when evaluating
concentration, particularly QQQM's large technology and growth exposures.

Targets come from the validated current account state. Dollar amounts are
calculated from that state at runtime; this policy does not preserve a dated
account total or a fixed deployment amount. The active production configuration
defines the effective percentage targets and aggregate allocation controls.
The [owner allocation policy](allocation_policy.md) sets the combined index-core
minimum and baseline at 30%, individual stocks at up to 70%, zero cash
target/reserve, and no fixed single-stock cap. Core above its baseline is
permitted; it must not produce a ceiling-based trim. New stock sizing preserves
room for the combined core minimum. Whole-share rounding may cross above the
baseline target to meet the floor when the remaining evidence, cash and
aggregate checks pass; an already-above-floor combined core is not forced down
to 30%. Historical target fields never override this policy.

Approval does not prescribe equal fund weights, a separate QQQM cap, automatic
rebalancing or a sale of SPY. A proposed substitution must state both legs,
whole-share quantities, current price conditions, resulting combined core and
individual-stock weights, cash use, overlap and its investment rationale.
Projected sale proceeds are a scenario, not a recorded fill or verified funds.
No replacement purchase is assumed executed merely because a sale is proposed.

Targets are planning constraints, not automatic purchase instructions.

## Cash-Deployment Decision

1. `retain_cash_fallback`: selected whenever refreshed core evidence fails.
2. `core_starter_whole_share_review`: at most one whole share per review,
   bounded by the combined current core gap, deployable cash, range-position
   gate, and configured reserve. This existing starter path is not an automatic
   multi-leg rotation instruction.

An approved fund's starter requires its own market quality `ok`, technical-entry
score at least `5.0`, a 52-week-range percentile no higher than `95`, maintenance
inactive, valid current account state, post-allocation compliance, and independent
human confirmation. ETF valuation is labeled not applicable rather than missing
because the individual-company EV/revenue model is not the relevant
index-allocation test.

The individual-stock conviction score is not a core gate: its company earnings
and EV/revenue components are structurally not applicable to these index ETFs.
Core market/entry evidence and portfolio-allocation constraints are tested
directly instead. QQQM's approval does not waive its own liquidity, market-quality,
entry, overlap or whole-share checks and does not change tactical risk budgets.

While the C9 maintenance inhibit is active, the starter is `blocked_maintenance`.
Availability of cash alone never selects an ETF review.
