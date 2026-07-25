# Phase 5R Local Valuation and Performance Foundation

Date: 2026-07-25  
Status: deterministic valuation, packet/adjudicator integration, rolling
monthly measurement, and sequential paper simulation implemented; real
valuation ingestion and real point-in-time performance evidence remain open

## Scope and boundary

This foundation adds two offline, read-only calculation layers:

1. `phase5r_valuation_evidence_v1` creates provenance-bound valuation receipts.
2. `phase5r_point_in_time_performance` measures supplied paper walk-forward
   records.
3. `phase5r_sequential_portfolio_simulator` turns chronological, hash-bound
   paper decisions and market-period receipts into compatible monthly ledger
   rows.

Neither module fetches data, calls a model, sends email, connects to a broker,
reads an account, creates an executable instruction, or writes portfolio state.
All outputs are research measurements for human review.

No historical performance result is claimed by this implementation. The
repository still lacks the frozen real point-in-time ledger needed to evaluate
rolling five-year results.

## Valuation evidence v1

The valuation builder accepts only canonical inputs:

- current share price;
- current diluted shares;
- cash and equivalents;
- total debt;
- trailing revenue;
- trailing free cash flow;
- prior-period diluted shares;
- a separately labelled target-price scenario assumption;
- a separately labelled downside-price scenario assumption.

Every supplied input must contain:

- an exact Decimal-compatible value;
- the canonical unit;
- the reporting or scenario period;
- a UTC availability timestamp no later than the valuation as-of time;
- one or more source identifiers;
- either `observation` or `scenario_assumption`, according to the closed schema.

Binary floating-point inputs, unknown input names, missing provenance,
unit/kind mismatches, non-finite values, and future-available evidence are
rejected. Missing canonical inputs are not inferred or replaced.

The builder deterministically calculates, where the required inputs exist:

- market capitalization;
- net debt or net cash;
- enterprise value;
- EV/revenue;
- free-cash-flow margin and yield;
- EV/free cash flow when free cash flow is positive;
- diluted-share change;
- target upside;
- downside change;
- reward-to-risk.

Each calculation records its formula, input identifiers, source identifiers,
input periods, unit, and Decimal result. The complete receipt is protected by a
SHA-256 digest and can be fully recomputed by the validator.

`decision_sufficient=true` requires both:

- complete current valuation evidence, including dilution and free cash flow;
- sourced target/downside assumptions with target above the current price and
  downside below it.

When those conditions are absent,
`action_grade_valuation_permitted=false` and the explicit result is
`watch_or_abstain`. Negative free cash flow is preserved as negative evidence;
it is never rewritten into a positive multiple.

## Packet and adjudicator integration

The valuation contract is now wired into
`build_phase5r_decision_evidence_packet.py`, `phase5r_llm_contract.py`, and the
deterministic adjudicator:

- every packet contains a closed `valuation_evidence` array;
- each receipt is recomputed and checked for exact ticker, as-of timestamp,
  same-ticker source provenance, and deterministic projected calculations;
- duplicate ticker receipts, unknown sources, cross-ticker sources, future
  inputs, and mismatched calculations fail packet validation;
- `valuation_action_grade_tickers` must exactly equal the set of validated,
  decision-sufficient receipts whose guardrails permit action-grade valuation;
  and
- any proposed action transition other than a supported broken-thesis
  `exit_review` fails closed when its target ticker is absent from that set.

The active real packet currently contains `0` valuation receipts, and the
builder deliberately emits `valuation_evidence=[]` and
`valuation_action_grade_tickers=[]`. Therefore this integration adds no new
action authority today. Real, provenance-bound valuation inputs and scenario
assumptions have not been ingested.

## Point-in-time paper performance

The paper performance module supplies pure calculation interfaces for:

- selecting the first supplied session open strictly after a decision
  timestamp;
- explicit fixed-fee, spread, and slippage cost assumptions;
- external-flow-neutralized time-weighted returns;
- exact `-100%` terminal returns as portfolio ruin rather than an invalid row;
- cash drag against a fully invested counterfactual;
- split value preservation;
- dividend cash;
- explicit delisting recovery, including a no-lookahead availability check;
- maximum drawdown;
- one-way turnover using half the L1 weight change, including cash;
- same-period comparison with caller-supplied, period-aligned `SPY`, `QQQ`,
  `XLK`, and C9 baseline series;
- seeded circular-block-bootstrap TWR confidence intervals.

External flows are defined as occurring after a return subperiod closes. The
next subperiod opening NAV must reconcile exactly to the prior net closing NAV
plus that flow. Modeled costs are deducted before net TWR. Any discontinuity
fails closed instead of being silently absorbed into return.

Corporate actions are caller-supplied point-in-time evidence. In particular,
the delisting interface requires an explicit recovery value and verifies that
both the effective event and recovery evidence were available by the
evaluation as-of timestamp. This prevents a missing delisting from being
silently treated as a convenient surviving security.

The performance functions reject returns below `-100%`, but retain an exact
`-100%` final loss. Such a path produces net TWR of `-100%`, maximum drawdown
of `100%`, and remains eligible for bootstrap sampling. This closes a
survivorship-bias hole where bankrupt or zero-recovery securities could
previously disappear from measurement.

All comparison and confidence-interval outputs contain
`measurement_only=true`; performance comparison outputs additionally contain
`future_performance_claim=false`.

## Rolling monthly evidence and sequential simulation

The monthly ledger builder requires exact `YYYY-MM` period identity,
period-start/end UTC timestamps inside that calendar month, return no lower
than `-100%`, non-empty source bindings, and a deterministic row hash. The
rolling receipt rejects future availability, gaps, overlaps, reordered or
tampered rows, and policy-hash mismatch. It reports:

- rolling 12-, 36-, and 60-month TWR and annualized CAGR;
- full-period CAGR once at least 12 months exist;
- annualized volatility, downside deviation, and Sortino;
- maximum drawdown, underwater duration, and recovery; and
- an explicit five-year objective status only when 60 months exist.

The sequential simulator builds those rows from an immutable policy plus one
decision snapshot per consecutive month. Each decision must predate its
effective period and may be exactly `rebalance`, `hold`, or `abstain`.
Rebalances require explicit long-only target weights including cash and must
pass per-position, gross-exposure, cash-floor, position-count, and one-way
turnover limits. Fixed costs plus spread/slippage are deducted before period
return. Missing market receipts fail closed.

Market receipts bind ticker, period boundaries, availability time, source
IDs, prices, and terminal recovery. Delisting, bankruptcy, or liquidation can
produce an exact zero-recovery `-100%` loss; a terminal ticker cannot later
re-enter. Drift-induced constraint breaches are reported and cannot be carried
silently by a later hold/abstain decision.

This simulator is monthly, long-only, and price-based. It does not yet model
ordinary dividends, splits, taxes, partial fills, intramonth paths, sector/
factor/correlation/liquidity limits, or empirically calibrated costs. Those
are real-ledger requirements, not values the model may invent.

## Required real-ledger work before a result may be reported

The foundation does not make the repository evaluation-ready by itself. A
separate immutable ledger and coverage manifest must still provide:

- every decision's frozen information timestamp;
- the first eligible following market session and its primary-source price;
- portfolio NAV before and after modeled cost;
- contributions and withdrawals at explicit subperiod boundaries;
- dividends, splits, mergers, symbol changes, bankruptcies, acquisitions, and
  delistings, including zero recoveries when the source supports zero;
- total-return series for SPY, QQQ, and XLK on identical periods;
- the deterministic C9-only policy baseline on the same evidence timestamps;
- rejected candidates and non-survivors;
- an untouched out-of-time holdout and multiple market regimes;
- multiple frozen issuer-grouped chronological folds with purge/embargo, not
  only the current single-cohort split;
- a pre-registered cost grid and block-bootstrap configuration.

Only after that ledger passes point-in-time, corporate-action, baseline
alignment, and completeness checks should rolling CAGR, excess return,
drawdown, turnover, cash drag, or confidence intervals be described as
historical evidence. Even then, they are historical measurements, not a return
promise or authorization to act.

## Synthetic verification

The local unit tests cover:

- exact valuation arithmetic and source propagation;
- missing-share, missing-scenario, invalid-unit, wrong-kind, future-evidence,
  unknown-input, binary-float, and receipt-tampering failures;
- negative free cash flow without fabricated positive multiples;
- next-session paper fills;
- modeled transaction costs;
- TWR with an external contribution;
- NAV reconciliation failure;
- cash drag;
- splits, dividends, and delisting recovery;
- terminal `-100%` TWR, 100% drawdown, and bootstrap retention, while values
  below `-100%` fail closed;
- future delisting-outcome rejection;
- drawdown and turnover;
- required and aligned SPY/QQQ/XLK/C9 baselines;
- deterministic bootstrap output.
- consecutive monthly row and 12/36/60-month rolling evidence;
- rejection of row tampering, future data, calendar-label mismatch, and month
  gaps;
- insufficient status at 59 months and exact objective measurement at 60;
- chronological rebalance/hold/abstain simulation, constraint and turnover
  enforcement, modeled costs, forged availability rejection, missing-market
  failure, terminal loss, and terminal-ticker re-entry rejection.

These are synthetic contract tests. They demonstrate calculation and safety
behavior only; they do not demonstrate investment skill or realized return.

Final integrated verification: PASS — `341/341` tests with
`python3 -m unittest discover -s 09_scripts/phase5r/tests -p 'test_*.py'`,
completed 2026-07-25T10:08:39-04:00.
