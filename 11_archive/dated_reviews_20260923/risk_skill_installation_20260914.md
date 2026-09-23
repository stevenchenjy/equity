# Risk-analysis skill installation — 2026-09-14

The owner asked for helpful skills to reduce unnecessary defensiveness in the
research system. Two user-level skills were installed from
[wshobson/agents](https://github.com/wshobson/agents), pinned to commit
`4236bb91f8395b0435f1d8b8baf9e8e4c69a8620`:

- `backtesting-frameworks`: point-in-time inputs, transaction costs,
  out-of-sample evaluation and protection against selecting rules after a rally.
- `risk-metrics-calculation`: multiple risk measures, correlated stress,
  drawdown analysis and explicit assumptions instead of one allocation number.

Installation locations are under the owner's `~/.codex/skills/` directory,
not the production scheduler. Both packages contain only `SKILL.md` and a
Markdown reference file. The main agent read the instructions and reference
examples before adoption. No broker connection, trading library, credentials,
background process or automatic execution was installed.

Discovery observations: the Skills CLI reported approximately 15,000 installs
for backtesting-frameworks and 9,800 for risk-metrics-calculation; GitHub
reported 39,653 repository stars and MIT licensing at inspection. Popularity
is not verification of the methods or a guarantee of security/performance.

The examples are instructional, not validated production code. In particular,
their metric conventions, initial-equity treatment and sample backtest trade
counts require independent review before reuse. No example implementation was
copied into the production strategy.

## Application to this project

Use snapshot-based exposure and hypothetical stress diagnostics first. Label
them as such: they are neither historical backtests nor VaR/return forecasts.
Do not infer a distribution or annualized performance from a few daily closes.

A later strategy comparison needs point-in-time candidate/valuation history,
cash flows, transaction-cost assumptions and a reserved evaluation period.
Measure opportunity cost and turnover alongside drawdown. A larger allocation
is a user risk preference until evidence establishes a more specific claim;
no installation proves that it will outperform the inherited policy.

Source packages:
[backtesting-frameworks](https://github.com/wshobson/agents/tree/4236bb91f8395b0435f1d8b8baf9e8e4c69a8620/plugins/quantitative-trading/skills/backtesting-frameworks),
[risk-metrics-calculation](https://github.com/wshobson/agents/tree/4236bb91f8395b0435f1d8b8baf9e8e4c69a8620/plugins/quantitative-trading/skills/risk-metrics-calculation).
