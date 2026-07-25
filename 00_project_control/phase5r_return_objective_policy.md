# Phase 5R Long-Horizon Return Objective Policy

Date: 2026-07-25  
Status: active research objective; not a promise, annual quota, or execution
instruction

## Objective

Phase 5R will evaluate the portfolio research process against a **rolling
five-year annualized net total-return objective of 12%–15%**.

- Exact monthly compound equivalents: `0.9489%–1.1715%`.
- A `15%–20%` calendar-year return is an excellent-year outcome, not a result
  that must be repeated every year.
- Monthly returns may be reported, but `1.0%–1.2%` is not a monthly hurdle.
- The objective cannot override evidence, concentration, cash-reserve, market
  data, thesis-break, or manual-execution gates.
- No model, backtest, or report may describe the objective as guaranteed.

The SEC warns that investment gains are not guaranteed, and Investor.gov
explains that higher potential returns generally involve greater uncertainty
and loss risk. Diversification reduces concentration risk but does not eliminate
losses. See the [SEC investor guidance](https://www.sec.gov/investor/pubs/tenthingstoconsider.htm),
[Investor.gov risk definition](https://www.investor.gov/introduction-investing/investing-basics/glossary/risk),
and [FINRA diversification guidance](https://www.finra.org/investors/investing/investing-basics/asset-allocation-diversification).

This is a stretch objective, not a neutral market assumption. J.P. Morgan
Asset Management's
[2026 long-term assumptions](https://am.jpmorgan.com/us/en/asset-management/adv/about-us/media/press-releases/jp-morgan-releases-2026-long-term-capital-market-assumptions/)
projected `6.7%` for U.S. large-cap equities over 10–15 years. Vanguard's
[2026 outlook](https://corporate.vanguard.com/content/dam/corp/research/pdf/isg_vemo_2026.pdf.)
described roughly `4%–5%` annualized U.S. equity returns in its subdued case
and `6%–8%` in an AI-boom scenario. These forecasts are uncertain, but they make
the central point: 12%–15% should not be treated as a baseline that software can
promise. Any attempt to pursue it must expose the additional concentration,
drawdown, turnover, and forecast risk rather than hiding them in model
confidence.

## Measurement contract

The objective is measured, not inferred from model confidence:

- primary measure: rolling five-year time-weighted CAGR, net of modeled
  commissions, spread, slippage, and other implementation costs;
- secondary measures: calendar-year return, rolling 12/36/60-month return,
  maximum drawdown, downside deviation, volatility, Sortino ratio, turnover,
  concentration, cash weight, and recovery time;
- primary benchmark fixed in advance: `SPY` total return;
- factor-context comparators fixed in advance: `QQQ` and `XLK` total return;
- policy baseline: the deterministic C9 decisions without LLM influence;
- contributions and withdrawals are neutralized with time-weighted returns;
- tax effects are reported separately only when valid non-broker inputs exist;
- dividends, splits, delistings, and corporate actions must be point-in-time
  adjusted.

Benchmark selection cannot be changed after seeing results. S&P DJI's
[SPIVA U.S. Year-End 2025](https://www.spglobal.com/spdji/en/spiva/article/spiva-us/)
reported that most active large-cap U.S. funds underperformed the S&P 500,
which is a useful warning against treating an ambitious target as easy or
optimizing only a favorable backtest.

## Decision implications

The objective changes planning, not trading cadence:

- daily data collection and evidence review remain high frequency;
- position changes remain evidence- and risk-triggered, not calendar-triggered;
- a weak month does not create pressure to trade;
- an excellent month or year does not relax concentration or thesis controls;
- large cash allocations must be shown explicitly as return drag in feasibility
  analysis, but cash is never deployed automatically;
- model-generated price targets or expected returns are hypotheses, not facts;
- Python performs all return, scenario, and attribution calculations.

The committee must answer two distinct questions:

1. Does current primary evidence strengthen, preserve, weaken, or break the
   long-term thesis?
2. Is the proposed research classification proportionate to portfolio risk and
   the rolling return objective?

It may not answer the second question by fabricating a probability, target
price, or expected return that is absent from the deterministic packet.

## Evaluation before any advisory influence

Return evidence is evaluated only after factual and policy gates pass:

1. frozen point-in-time walk-forward replay, with no revised-fact, survivor,
   delisting, or future-price leakage;
2. an untouched holdout period and multiple market regimes;
3. realistic costs and turnover;
4. bootstrap confidence intervals and parameter sensitivity;
5. comparison with SPY, QQQ, XLK, and deterministic C9 on the same dates;
6. attribution separating allocation, selection, timing, cash, and costs;
7. explicit failure analysis for drawdowns and adverse regimes.

The 12%–15% objective is not a model-promotion shortcut. A model still fails if
it has unsupported claims, unsafe direction changes, weak calibration, citation
errors, or boundary violations—even if a historical return simulation is high.
Conversely, a short replay below 12% does not prove that a sound long-horizon
process has failed.

## Human workload

Routine daily HOLD/WATCH decisions do not require manual review after validation.
Human attention is reserved for:

- a proposed add, trim, or exit transition;
- a material thesis change;
- an evidence or model-policy exception;
- periodic performance/risk review, preferably quarterly rather than monthly;
- any future real-world action, which remains outside this repository.

This preserves a clear objective without turning normal market variance into
daily intervention.
