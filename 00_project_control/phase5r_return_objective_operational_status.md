# Phase 5R Return Objective Operational Status

Date: 2026-07-25  
Status: objective and rolling-measurement contract recorded; real performance
history and feasibility gap remain open

## Current feasibility

The latest local C9 allocation snapshot shows approximately `12.78%` invested
and the rest in cash/reserve. This report uses percentages only and does not
read a broker.

Illustrative arithmetic:

- if cash contributed `0%`, a 12.78% invested sleeve would need approximately
  `93.93%–117.41%` in one year to produce a 12%–15% whole-portfolio return;
- at the existing policy target of 80% core-plus-active equity and 20% cash,
  the invested sleeve would still need approximately `15.00%–18.75%` if cash
  contributed `0%`.

Those are feasibility illustrations, not forecasts. They show that the return
objective cannot be solved by a better email or LLM alone. Allocation, cash
yield, risk, implementation cost, and market returns dominate the arithmetic.

## Operational decision

- No allocation, position, cash-reserve, or execution state was changed.
- The existing optional broad-market core review remains conditional and
  manual; it was not selected or executed by this upgrade.
- The 12%–15% objective is embedded in the sealed LLM packet as a five-year
  constraint, with `monthly_or_annual_quota=false`,
  `return_guarantee=false`, and `risk_gates_override_allowed=false`.
- Daily evidence frequency remains high, while position changes remain tied to
  evidence and risk rather than monthly performance.
- The local monthly ledger and sequential paper simulator can now calculate
  rolling 12/36/60-month evidence, drawdown and downside risk from supplied
  point-in-time records. They contain no real history today; fewer than
  60 months explicitly returns insufficient evidence.

## Missing evidence

The repository does not yet have a sufficiently long, contribution-adjusted
portfolio NAV history to measure rolling five-year CAGR. Before making a
performance claim it needs:

- a local, non-broker time-weighted return ledger;
- external cash-flow records;
- total-return benchmark series with corporate actions;
- execution-cost assumptions;
- point-in-time walk-forward decision history;
- a real sequential ledger including failed/delisted names and calibrated
  costs, rather than only synthetic simulator fixtures;
- drawdown, turnover, attribution, and confidence-interval reporting.

Until those exist, the return objective is a planning and evaluation target,
not evidence that the strategy can or will achieve 12%–15%.
