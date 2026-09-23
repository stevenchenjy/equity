# Phase 5R Long-Horizon Return Objective Policy

Updated: 2026-08-31

Status: active research objective; not a promise, quota, or execution instruction

## Objective

Phase 5R evaluates the research process against a rolling five-year annualized
net total-return objective of `12%–15%`.

- Exact monthly compound equivalents: `0.9489%–1.1715%`.
- A `15%–20%` calendar-year return is an excellent-year outcome, not a result
  that must be repeated every year.
- Monthly returns may be reported, but they are not monthly hurdles.
- The objective cannot override evidence, concentration, cash-reserve,
  freshness, thesis-break, or manual-execution gates.
- No report, simulation, or research classification may describe the objective
  as guaranteed.

The objective is deliberately ambitious. Higher potential returns carry
greater uncertainty and loss risk, while diversification reduces but does not
eliminate risk. The system must expose concentration, drawdown, turnover, cash
drag, implementation cost, and evidence gaps rather than treating the target as
a software-controlled outcome.

## Measurement Contract

The objective is measured only from valid point-in-time records:

- primary measure: rolling five-year time-weighted CAGR, net of documented
  commissions, spread, slippage, and other implementation costs;
- secondary measures: calendar-year and rolling 12/36/60-month return, maximum
  drawdown, downside deviation, volatility, Sortino ratio, turnover,
  concentration, cash weight, and recovery time;
- primary benchmark fixed in advance: `SPY` total return;
- context comparators fixed in advance: `QQQ` and `XLK` total return;
- policy baseline: deterministic C9 decisions on the same evidence dates;
- contributions and withdrawals neutralized with time-weighted returns; and
- dividends, splits, delistings, and other corporate actions adjusted without
  future information.

Benchmark selection cannot change after results are observed. Missing,
survivor-biased, revised, or future-dated evidence produces an explicit
insufficient-evidence result rather than an estimated performance claim.

## Decision Implications

- Daily evidence collection does not imply daily trading.
- A weak month does not create pressure to act.
- An excellent month or year does not relax risk controls.
- Cash drag is shown explicitly, but cash is never deployed automatically.
- Price targets and expected returns are sourced scenarios, not facts.
- Deterministic code performs return, scenario, and attribution calculations.
- Any add, trim, or exit remains a research proposal for human review.

## Active Boundary

The production system makes no model or provider calls. Historical replay,
simulation, and model-evaluation material is archived and cannot become a
current decision input. Current outcome tracking is limited to validated
point-in-time recommendation snapshots and their configured 1-, 5-, 20-, and
60-session measurements. A five-year result may not be claimed until a complete
five-year ledger passes the measurement contract above.

No return objective authorizes a broker connection, an automatic order, or a
real-world portfolio action.
