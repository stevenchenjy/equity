# Momentum integration decision — 2026-09-27

## Owner-approved first-cohort review timing — September 27 follow-up

The owner selected manual review as soon as the first complete five-trading-session
forward cohort is available. `01_policies/momentum_experiment_review.json` records
this review timing separately from the frozen experiment. The daily refresh now
runs `create_momentum_experiment_review.py` after the study and links its private
packet from current production status. It does not require additional cohorts,
a minimum winning percentage, profitability or a minimum trade count merely to
open an owner review. Complete coverage, chronological observations and the
existing 10/25/50 bps one-way cost scenarios remain necessary for an honest
five-session comparison. Unfinished, missing or corrected observations remain
visible; they cannot be treated as completed outcomes.

Review availability does not establish an investment edge, change recommendation
eligibility or allocate capital. A batch with no selected breakout-plus-volume
names permits a review of coverage and missed opportunities but cannot establish
that strategy's performance. Current entry quotes, setup validity, account/order
facts and the existing risk checks still apply to any subsequent action plan.
No holding-period or experimental threshold changed, and the original ledger,
policy and implementation fingerprints remain intact.

For the v2 observations captured September 27 using the September 25 close,
the earliest modeled entry is September 28 and the fifth close is October 2.
The first existing Basic EOD publication slot able to evaluate that interval is
October 3 at 11:15 ET, plus collection and pipeline time, conditional on complete
valid data. The 33 overlapping ticker observations form one time cohort, not
33 independent trials. DDOG and SMCI met the frozen breakout-only condition;
none met breakout plus 2x daily volume. These are historical experimental
selections, not current buy recommendations.

The earlier sections below retain the original audit and promotion constraints.
The new minimum changes when an owner can review the evidence, not whether the
strategy has been validated for use with capital.

The production strategy remains the deterministic, fundamentals-led daily research workflow. This upgrade adds prospective position-purpose controls and an autonomous **experimental EOD research study**. It does not replace the strategy with Ross Cameron's intraday trading, change approved allocation or risk, purchase services, or enable orders. A successful software run is not evidence of profitable investing.

## What was verified

The authoring repository is `/Users/messssi/Desktop/equity`; scheduled execution uses `/Users/messssi/LocalRuntime/equity`. `/Users/messssi/Documents/equity` contains prior reviews and work products, not the scheduled application. Both clones began this audit clean at `b802b9068014a56f1008061adde2490a55e0565a`.

Code, active configuration, launchd state, execution logs and generated artifacts were examined independently. Refresh and decision jobs are installed, poll every 900 seconds, and have successful recent execution evidence. A successful September 27 refresh used September 25 completed daily bars. Polling does not mean intraday scans. The canonical 34-name evidence universe and separate broad-market discovery have different coverage; the new forward study is restricted to the former. Existing SEC evidence, issuer-news ingestion, maintained theses, plan continuity, whole-share sizing, regime-dependent confirmation pace, valuation gates and delivery suppression remain in place.

Actual cash is manually recorded and its planning basis is an estimate. Settled spendable funds, current orders and total tactical downside risk are not independently verified by this audit. Account type is a local cash-account assumption, not a new broker confirmation. No account read was performed. Existing held plans include due or unresolved reviews; this upgrade never assumes an old ticket filled or that a failed tactical position became a growth investment.

Allocation targets remain 40% broad core / 50% active / 10% cash, with the current 50% active and 15% single-name hard caps. The actual account-specific reserve remains unchanged; the active configuration's fallback is not permission to rewrite it. Existing tactical limits remain 0.5% ordinary risk, 0.25% event risk, 2% aggregate planned risk, 5% name size and a five-session maximum. Stops may gap and are not guaranteed loss limits. No short winning or losing streak changes these controls.

The separate AI shadow evaluator is installed but its latest observed run failed archived evidence-contract validation. It is outside canonical decision and email authority. Older prose saying it is not installed is stale. Its repair is outside this momentum change; evidence validation is not bypassed. Current portfolio evidence has one actual NAV observation and no usable return interval. Operational reliability and recommendation price paths do not establish actual investment performance.

## Source-grounded integration choices

The accompanying `ross_primary_research_20260927.md` and `ross_sources_20260927.json` preserve source dates, challenge differences and verification limits. Ross/Warrior are primary sources for their own described practices, not independent validation of a transferable edge.

| Principle | Decision and reason |
|---|---|
| Catalyst-driven selection | Retain official-news and filing research. The study records timestamped official announcements known at observation time, with direction unassessed. An announcement is never automatically positive; a positive catalyst needs a maintained evidence assessment. Missing news coverage is unverified. |
| Unusual relative volume | Add an explicitly named daily volume / prior-19-session mean feature and a frozen 2x experimental ablation. The current baseline ratio stays unchanged. Neither measure is live time-of-day RVOL; Ross's 5x examples use different contexts and denominators. |
| Strength and prior highs | Add an experimental close above all prior 19 highs with positive close-to-close strength. Prior highs do not bar this research candidate. Preserve the existing tactical observed-target gate until evidence supports a different executable exit model. |
| Float, price and liquidity | Record price and historical close-times-volume as trading characteristics. Float, spreads, depth and halts remain unverified. Shares outstanding are not substituted for free float. No $1–20, sub-20m float or +10% universal screens are imported. Business quality stays in the maintained fundamental thesis. |
| First pullback / bull flag / fast breakouts | Intraday detection deferred. One-/five-minute bars, live tape, Level 2 and timely attention were not verified. A daily breakout study is its own strategy hypothesis, not proof that a Ross pattern occurred. |
| Position sizing and deteriorating evidence | Keep approved caps and existing source-bound invalidation, concentration, plan-expiry and regime controls. No new capital is proposed by the experiment. Existing cautious activity in weak regimes remains; no automatic liquidation or loss-streak retuning is added. |
| Profit management | Compare a hypothetical full exit at 2R, observed-low failure and five-session exit in the experimental price model only. A 2R reference is not observed resistance, expected return, or executable protection. Ross's partial exits/tape discretion cannot be copied faithfully for tiny whole-share positions with daily data. |
| Explicit position purpose | Prospective plan writer checks source-bound reassessment when purpose, horizon or deadline changes, including replacement plan IDs. Failed and expired history remains. See `position_purpose_reassessment.md`. No historical plan is rewritten. |

Ross's 2017 $583.15 SureTrader account, 2024 Thinkorswim work and September 2025 $2,000 CMEG/DAS challenge are distinct. The 2025 challenge initially had 6x available leverage and later reset without it; none of that authorizes leverage here. Personal results, selected chart examples and the commercial toolkit's aggressive account-risk examples are not calibration data for our limits.

## What runs without another chat

The existing serialized daily refresh now invokes `create_momentum_experiment.py` after canonical research. It reads local validated evidence only, adds no provider calls, stores private frozen observations and later outcomes in `08_reviews/momentum_experiment.local/ledger.jsonl`, and produces `report.md`, `report.json` and status. The current production status links the experiment. Failures are advisory and visible; they cannot suppress valid existing account-risk reports, authorize a trade or change a recommendation/email fingerprint. Existing owner-review and change-only delivery policy remains unchanged. No extra automation, paid service, model call or email was added by this upgrade.

All covered names are retained, including no-setup, invalid-data, losing, expired, unfilled and missed positive paths. First observation per policy version / signal session / ticker is immutable; reruns display that frozen record. Policy and implementation fingerprints are frozen: changes under the same version fail closed. New versions remain separate cohorts. Older observations whose implementation no longer matches remain pending for replay with their preserved Git implementation; they are never silently evaluated with new rules. Inputs are checked for modification during reading. Account, execution, maintained thesis and plan history are never mutated by the experiment.

The September 27 operator restoration starts prospective cohort `eod-breakout-v2-20260927`. The approved workflow changes modified `investment_plans.py` and `daily_common.py`, both included in the experiment's whole-file implementation fingerprint, so the original version correctly refused to accept the changed implementation. The experiment algorithm and its imported helpers are unchanged; this version change preserves every hypothesis, threshold, cost assumption and authority setting. It is an implementation-provenance boundary, not performance-driven retuning. Original `eod-breakout-v1-20260927` observations retain their hashes and first-observation times; their matching implementation remains in Git commit `16e3842a5be2ecd00f663d77f363661122f9c076`. They remain separate and pending for replay with that implementation. New observations use their actual observation times, are never backdated, and must not be pooled with the original cohort as additional independent evidence.

No new intraday alert is actionable. All study quantities are zero. The owner confirmed a few brief checks during market hours on September 27; this supports conditional multi-day review but not continuous tape monitoring. A research candidate needs current quote, entry range, failure, calendar, cash/order reconciliation and achievable response time before any future human order draft. Evidence older than the applicable session remains blocked or expires, not retrospectively filled.

## Frozen experiment and limits

The 19-bar lookback uses existing validated 20-bar storage while excluding the signal bar. The 2x daily volume threshold and 0.25R maximum gap are predeclared exploratory choices, not learned optima or Ross rules. Five sessions matches the existing tactical maximum. The 2R profit reference is a hypothetical management convention. The first regular open strictly after actual observation is the earliest modeled entry: next-day Basic EOD availability cannot buy the already elapsed morning open.

The selection study compares frozen baseline eligibility and breakout cohorts on the **same** subsequent open-to-fifth-close path with the same costs. Differences describe selection cohorts, not causal incremental profit. Baseline conditional-limit intraday execution is unmodeled without suitable data. Supplemental breakout execution scenarios use bounded entry, gap-adjusted stop, stop-first treatment when daily high/low sequencing is ambiguous, and full exit at 2R or the fifth close. These scenarios cannot establish fills or portfolio capacity.

Use 10/25/50 basis points per side for spread/slippage/fee sensitivity and zero explicit commission as a stated online-equity assumption, not a verified cost for every transaction. Costs can be much worse for low-float illiquid stocks; no such strategy is authorized. No capital, leverage, tax, halt or dividend modeling is claimed. Missing/delisted names and missing forward bars stay unresolved rather than becoming flat returns or disappearing. Detected historical-bar corrections invalidate outcome interpretation. The study is a bounded covered-universe forward record, not a survivorship-free full-market historical backtest.

Preserve consecutive point-in-time forward records; do not backfill decisions from today's universe, latest filings or later prices. Before considering promotion, review baseline and added-opportunity cohorts separately, distinct nonoverlapping time cohorts, exposure/cost-matched portfolios, benchmark-relative returns, adverse regimes, drawdowns/tails, missingness, actionability latency, order/settlement feasibility, and sensitivity across predeclared costs. Overlapping names/dates are not independent samples. A later holdout must be kept unseen when choosing revised parameters. There is no automatic sample-count or winning-streak promotion rule. Any capital or risk change requires explicit owner approval; currently all strategy adaptations remain experimental.

## External feasibility sources (checked September 27, 2026)

[Massive's current Stocks plan page](https://www.massive.com/stocks) describes Basic as end-of-day with 5 calls/minute and no quotes or WebSockets. The observed collector/publication cadence, rather than higher-tier marketing capability, defines what this installation can verify. Basic may offer delayed historical minute aggregates, but no minute-data collection or intraday validator exists in the verified workflow.

[Chase cash-trading guidance, edited September 21, 2026](https://www.chase.com/personal/investments/learning-and-insights/article/how-to-avoid-cash-trading-violations) explains T+1 settlement and the risk of selling purchases funded by unsettled proceeds before payment completes. The [Self-Directed FAQ](https://www.chase.com/personal/investments/faqs/self-directed-investing) distinguishes own-money cash accounts from margin. These public pages do not verify this owner's account designation, settled balance or restrictions. Historical PDT numbers from Ross's articles were not adopted as current account rules.

Owner decisions still needed before an executable new adaptation: confirm broker/account/settled-cash constraints and, for any time-sensitive alert, achievable response timing within the brief-check availability; approve any future allocation or risk-limit changes; separately authorize paid data/services or live trading if ever desired. None is needed to let this zero-allocation research study accumulate observations.
