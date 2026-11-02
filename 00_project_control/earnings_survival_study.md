# Prospective earnings-survival study

## Material Passport

| Field | Registered scope |
|---|---|
| Artifact | Preregistered observational code experiment; no participant study |
| Version | `earnings-survival-forward-v1-20261101` |
| Policy / implementation | `01_policies/earnings_survival.json` / `09_scripts/equity_research/earnings_survival.py` |
| Record namespace | `08_reviews/earnings_survival.local/` |
| Question | Does preserving a previously observed setup through an earnings release help select subsequent breakout opportunities? |
| Primary horizon | Five trading sessions; ten and fourteen sessions are separately labelled secondary observations |
| Authority | Research only; zero actionable shares, no capital admission, broker action or additional delivery authority |

Owner authorization: November 1, 2026. This study operationalizes a limited
earnings-survival hypothesis. It does not copy an influencer's complete method,
claim his performance, adopt a large-gap strategy, or establish that a company
with good earnings deserves investment. The unchanged current tactical capital
engine remains separate. Its observed prior-resistance target cannot supply
upside for a fresh breakout above that same resistance.

## Registered question and comparison

The treatment is a daily consolidation observed before an earnings event,
preserved through the release, followed by a separately observed qualifying
breakout. The baseline is the existing ordinary breakout definition without the
earnings-survival requirement, observed at the same capture clock and measured
from the same first-future-opening convention. Shared ticker/session signal
identities identify overlap; the same breakout is not counted twice as two
independent trades.

The primary descriptive comparison is five-session net price performance and
its matched ETF difference under the same cost convention. Report the baseline,
survival subset and exclusions together. This is an observational selection
study: issuer, sector, market regime and timing can differ between groups. A
favorable mean does not establish causal alpha, a reliable win probability or
incremental portfolio benefit.

## Prospective admission and frozen levels

At the first eligible pre-event capture, require an independently retained
calendar lead and source-valid completed daily history. The setup requires
SMA20 above SMA50, close above SMA20, close no higher than the prior nineteen
sessions' high, and a positive close above the observed five-session low.
Freeze support at that five-session low and resistance at the prior
nineteen-session high. The setup has not already broken out.

Retain the original event identity, fiscal-period label, schedule version,
calendar source, first detection, actual capture time, history/snapshot hashes,
frozen support/resistance, policy and implementation identity. Account/cash
context is a separate required observation for feasibility, not a market return
input; until it is captured, feasibility remains unavailable.
Admission must precede the calendar's conservative research deadline and the
subsequently established official release. A notice fetched later cannot prove
that the system enrolled it earlier. Existing historical winners cannot be
backfilled into this forward cohort.

Calendar estimates, schedule changes, uncertain identity, missing history and
elapsed events remain explicit dependencies or exclusions. A rescheduled event
does not silently replace the admitted event version or renew its setup.

## Official release and observation clocks

Nasdaq calendar dates are discovery estimates, not issuer confirmation or an
exact release clock. Its conservative attention deadline is not a release time.
An earnings call/webcast time and a later SEC acceptance time do not establish
when the results first became public.

The study's release-confirmation writer admits retained official issuer HTML,
with issuer host checked against the existing official-news manifest, a results
release title and matching fiscal-period evidence. Publication must be parsed
independently from supported `article:published_time` or JSON-LD
`datePublished` metadata with an explicit timezone. Preserve original bytes,
URL, content hash, parsed publication time and actual writer receipt time.
Do not substitute `dateModified`, a calendar estimate, a manually typed exact
time, a source fetch time or an unsupported article for publication proof.

The writer also requires the matching independently validated official-news
observed-event receipt. Its URL, ticker, title and parsed publication clock
corroborate the retained HTML. Calendar/source conflicts are not cleared by
typing a preferred release time. The supported check-then-apply entry is
`run_earnings_survival.py --root ROOT --confirm-release PROPOSAL`, followed by
the same command with `--apply` only after validation. The CLI owns the study
writer lock inside the maintained runtime-then-pipeline mutation discipline,
acquiring all three locks itself. Do not wrap that CLI in a parent process
already holding those locks.

The proposal schema is `equity_earnings_survival_release_v1`. Bind `event_id`,
`ticker`, `fiscal_period_label`, root-relative `document_path`,
`document_sha256`, official `url`, `official_news_event_id`, the literal
`fiscal_period_evidence` excerpt, `reviewer` and substantive `reasoning`.
The supported period evidence explicitly states the period ended/ending month
and year matching the calendar's `MMM/YYYY` label. Unsupported issuer wording
stays unavailable rather than being silently interpreted as a match.
An optional proposed `release_at` must exactly equal the independently parsed
metadata; omitting it avoids introducing a second clock. Issuers without the
required configured official source, a matching retained news receipt or
sufficient release metadata remain unavailable, even when an external website
appears to show their results.

Publication and local availability remain different. A later confirmation
cannot backdate an observation or entry. A future, missing, conflicting or
insufficiently precise clock leaves the event unavailable. Initial v1 requires
a supported before-market-open or after-market-close release and complete
subsequent regular sessions; an intraday release needs a separate convention.
Use the exchange calendar, timezone and actual close, including holidays and
shortened sessions, rather than fixed UTC offsets.

## Survival and breakout

After the release, use only complete post-release regular sessions available
at the actual capture clock. Every observed low must remain at or above frozen
support. A support breach fails the survival condition and stays in the cohort
history; a later rebound cannot erase it.

Within five trading sessions after the first post-release opening, require
the existing completed-close breakout: close above the rolling prior
nineteen-session high, close above the previous close, and volume at least
twice the prior nineteen-session mean. Also require close above the frozen
pre-event resistance. No fifteen-percent gap cutoff or discretionary "good
looking" chart exception is part of v1. Failure to break out in the window is
retained rather than rolled forward indefinitely.

The breakout is known only after its complete close. Its daily opening price
cannot be treated as an entry that the system could have made earlier that
day. The first future opening is a modeled benchmark. An actual later owner
window or delayed observation is a different clock and requires its own stock
and ETF source observations; missing observations cannot use that opening as
a proxy for the owner's action.

## Outcomes, feasibility and missingness

The primary horizon is five trading sessions. Ten- and fourteen-session
outcomes are secondary and do not extend the approved five-session live
tactical mandate. Freeze the same 10, 25 and 50 basis-point one-way cost
scenarios as the baseline, applied separately to entry and exit. These are
assumed sensitivities, not observed execution costs. Keep delayed
entry, missed observations, adverse paths and no-opportunity cases.

Use the existing matched SPY/QQQM protocol only when stock and ETF observations
share admissible entry/exit clocks, horizon, cost and applicable corporate-action
review. A daily-open ETF comparison cannot validate a delayed owner-window
entry. Missing benchmarks, splits, distributions or required reviews remain
unavailable; unadjusted price return is not total-return alpha.

Before economic qualification, assess whole-share, cash, name/aggregate capacity
and planned-loss feasibility against a separately captured account context under
unchanged current risk rules.
Positive modeled price performance cannot create cash or fractional shares.
These feasibility observations remain separate from the return denominator and
from actual fills; an infeasible observation stays visible. Stop-distance loss
is planned risk, not a maximum guaranteed loss. Neither a daily bar nor a last
sale establishes an intraday fill path, spread, slippage, NBBO or protective
order.

Report distinct denominators for pre-event detections, admitted setups,
release-confirmed events, surviving setups, qualified breakouts, priced outcomes,
matched ETF outcomes, feasibility-assessable observations and missing/excluded
cases. Report unique signals separately from overlapping horizons and cost
scenarios. Preserve the reason for each unavailable or rejected case; missing
does not mean zero return or no event.

The initial implementation records fixed-horizon unadjusted price/cost
sensitivities and same-session ETF sensitivities. It explicitly labels these
paths unreviewed, corporate-action review required and qualified strategy paths
zero. Where a valid capital/account context exists, a separate diagnostic may
show cash, five-percent name-headroom and event planned-loss whole-share
ceilings at a stated price reference. It retains actual quantity zero and does
not clear combined open risk, aggregate allocation, executable funds/orders or
the future entry price. Missing context remains unavailable. Portfolio capacity
and managed-stop paths remain unverified.
These dependencies must stay visible. A matched raw price path or a positive
planning ceiling does not satisfy the fuller benchmark, feasibility or
profitability review described above.

### Retained owner-window timing observations

The separate `timing_usability` projection links actual retained active-v3 owner
window and three-, five- and ten-minute delay observations. It requires the same
ticker, source session, original bars, price basis, dataset and implementation
identity as the study signal. A quote's trade and observation clocks must follow
the study's actual capture. Observations or delay anchors from before capture
cannot be borrowed; stale, outside-window or invalidated marks stay unavailable.
Every link retains its original record identity, clocks, expiry and actual delay.

Report matched and unmatched source signals, distinct setup/window counts,
nominal and delayed observation states, and closed-window missingness separately.
Three delay variants are not three independent setups. An elapsed window with no
admissible later observation is missed, rather than a daily-open substitute.
Where supported, a diagnostic recomputes the whole-share ceiling at the retained
quote using the original frozen account context; it does not establish current
execution funds. This reads the existing observer's retained evidence and adds
no collection schedule or request authority.

These links describe historical observation usability, not current entry cards,
human response or fills. Owner-window stop sequencing and matched window-return
paths remain unqualified. The five-session daily-opening price-path endpoint
stays separate; timing counts cannot be presented as a completed delayed-entry
performance comparison.

## Frozen versions and review

The policy, implementation, source receipts and first observation identify each
cohort. Retain immutable inputs and append-only history. A changed rule, source
adapter, cost, entry clock or outcome convention requires a new version; do not
reinterpret frozen v1/v2 momentum or swing observations with this study.
Historical repair/recovery and new prospective observations remain distinguishable.

The recovered generic swing route is separately identified as
`daily-swing-review-windows-v3-20261101`, with policy
`01_policies/swing_research_v3.json` and namespace
`08_reviews/swing_research_v3.local/`. The active adapter exposes its admitted
research context to this study; that shared dataset does not transfer historical
v3 enrollments into the earnings cohort or repair old v2 observations. Original
v1/v2 policies, source and ledgers remain retained under their original identities.

The active generic ETF comparison is also separately versioned as
`spy-qqqm-matched-paths-v2-20261101`, with
`01_policies/swing_benchmarks_v2.json`, `swing_benchmarks_v2.py` and
`08_reviews/swing_benchmarks_v2.local/`. Its active review entry is
`active_swing_benchmark_review.py`. Original benchmark v1 policy, implementation,
writer and history are retained; a new empty comparison cohort is not a reason
to rewrite that original registration. The earnings study's unreviewed raw ETF
sensitivities remain distinct from an economically reviewed generic benchmark
comparison.

The first completed five-session cohort permits a process review of source
integrity, clocks, missingness, feasibility and outcome calculations. It is not
automatic strategy adoption and has no required favorable return or invented
minimum sample-count threshold. Before any later capital proposal, review
unseen/forward evidence, dependence and adverse regimes, costs/delay, actual
portfolio constraints and the exact strategy contract. Explicit owner adoption
remains necessary to change capital behavior.

## Runtime and final artifacts

Research uses the existing bounded refresh/assessment workflow. It adds no
analyst slot, unattended broker access, sender, recipient or delivery purpose.
Read-only/API projections validate their own retained proof and do not mutate
study history. Invalid or stale proof withholds the affected study claim rather
than clearing the canonical capital gates.

Author and test in `/Users/messssi/Desktop/equity`. Production is
`/Users/messssi/LocalRuntime/equity`; Documents stores audit artifacts. Inspect
the actual study report and adjacent decision/dashboard views in an isolated
rehearsal before calling implementation complete. Source edits and passing
tests do not establish deployment, natural market-open observations, a completed
forward cohort, email delivery or a broker fill. Deployment and any no-send
recomposition follow the maintained runtime workflow only when separately
authorized.
