# Prospective swing research during owner review windows

Owner request: October 27, 2026 overnight swing-strategy improvement. This adds
research and public observations, preserving numerical entry/quality/allocation/
risk limits, the approved live five-session tactical mandate, delivery rules,
human-only execution and experiment-adoption requirements.

## Signal, observation and execution clocks

Frozen `daily-swing-forward-v1-20261027` code, policy and observations remain
retained. The separate v2 uses `01_policies/swing_research_v2.json`,
`swing_research_v2.py` and `08_reviews/swing_research_v2.local/`. First detection,
source availability, first future opening benchmark, owner-window last sale,
modeled outcome and actual human execution are distinct. Never backdate entry.

A daily stock setup stays conditional through its named next exchange session's
09:45–10:45 and 14:45–15:20 Eastern owner windows, clipped at the actual close.
Older signals do not roll forward. Dated reference conditions may remain visible
after the open; expired quotes and expired setup levels are independently
suppressed. One last sale cannot prove rebound sequencing, an intraday path,
NBBO, spread, order or fill. Every experimental card retains zero actionable
shares. Growth thesis, catalyst, event risk, sizing and execution feasibility
remain analytical requirements. Stable ticker order is not a conviction ranking.

## Public observations without another analyst slot

`run_swing_observer.py` checks every 180 seconds, collecting only during the two
actual owner windows. It observes at most three already source-valid stock
setups; no candidates means no requests. Its 75-second worker takes runtime then
pipeline locks without waiting and defers to active short claims. It freezes
first detection before a new quote and fences older marks before an attempt.
Fresh complete held-scope marks are reused before another Nasdaq request.

Original HTTP/raw bytes, symbol, real-time flag, regular-session clock, no-future
clock, <=300-second age, <=120-second batch span, independently admitted current
prior close and latest-attempt proof remain mandatory. Failures never revive an
older success. Candidate observations are isolated under
`03_source_data/equity_research/swing_candidate_quotes.local/`. They do not
replace the complete held-risk scope, change EOD account/capital facts, invalidate
capital publication every three minutes, or authorize an email. API/browser
reads remain offline. The observer is no analyst review or completed analysis.

After normal tested source push and deployment, install only the new label:

```sh
/bin/sh /Users/messssi/LocalRuntime/equity/07_automation/scheduler/install_swing_observer.sh
```

Loaded configuration and an after-hours no-op are not natural market-open proof.
Host/login/service availability remains external; no administrative wake is
assumed. Two full reviews, two mandatory briefs and five short slots are unchanged.

## Focused outside-universe history and continuity

`swing_coverage.py` separates current broad screening, dated research leads,
current focused history and missing data. A failed latest broad attempt fences
older current-price claims. Dated ranks/first detections can preserve research
work, without establishing current momentum or an investment conclusion.

The advisory `swing_candidate_history` full-refresh stage can collect at most two
outside-universe common-stock histories per bounded attempt. Existing Massive
unadjusted Custom Bars and the Nasdaq new-session extension require exact raw
sources, two matching overlap closes, coherent OHLCV and the latest completed
session. `03_source_data/equity_research/swing_candidate_history.local/` is
separate from the canonical seed/snapshot/history pointer. Valid current caches
are revalidated and reused; pre-request reservations prevent repeated same-date
refetches. The child has 210 seconds inside the unchanged full-refresh budget.

Scheduled public full refreshes may collect. Operator full no-send reuse and
publication-only closure stay offline for this stage. The explicit standalone
`run_swing_candidate_history.py --root ROOT --collect` entry takes nonblocking
runtime/pipeline locks and respects active claims. A focused two-name recovery
does not establish current whole-market coverage. Mixed-fetch adjusted grouped
bars alone do not establish split-basis consistency; missing/bad history stays a
dependency rather than an invented signal.

## Qualification and adoption

First-opening benchmarks and actual timestamped owner-window observations are
separate cohorts. Missing window observations cannot use a daily-open proxy.
Retain skips, gaps, costs, delayed/failed observations and no-opportunity cases.
Source-bound corporate-action reviews bind exact ticker, observation/forward
window, original sources, timing, reasoning and limits before qualification.
Unsupported split/dividend adjustments stay unavailable. Reviewed fixed-horizon
price paths remain modeled, separate from actual fills or a managed stop strategy.

Compare identical horizons and costs with market benchmarks; overlapping paths
are not independent trades. Delay/spreads, owner response, events, whole shares,
portfolio capacity, drawdowns, adverse regimes and untouched holdout evidence
require review. A count, favorable mean or software pass cannot promote a
version. Exact strategy review and explicit owner adoption remain necessary.

### Separately versioned matched benchmarks

`01_policies/swing_benchmarks.json` and `swing_benchmarks.py` define a separate,
zero-capital SPY and QQQM comparison protocol. They do not change the frozen v1
or v2 signal definitions, original observations, or their implementation hashes.
Future-opening stock paths compare with the same entry session, exit session,
horizon and predeclared cost scenario. A daily opening price cannot stand in
for an owner-window or delayed entry. Such comparisons require original paired
stock and ETF last sales, with explicit clocks and the maximum permitted span.
Missing, delayed or mismatched observations remain visible dependencies.

The existing observer may make at most two supplemental ETF requests for new
source-valid stock entry observations, within its unchanged 75-second worker
budget. It makes no benchmark request when there is no new eligible entry or
insufficient remaining budget. Supplemental receipts are isolated under
`03_source_data/equity_research/swing_benchmark_quotes.local/`; they never replace
the held-risk batch or canonical account prices. The separate append-only
comparison history lives under `08_reviews/swing_benchmarks.local/`.

Raw unadjusted price comparisons and source-reviewed fixed-horizon modeled
paths remain distinct. Both legs require exact source coverage and applicable
corporate-action review before qualification. Neither is total-return alpha,
an actual fill, a managed stop-strategy return or sufficient adoption evidence.
The dashboard revalidates the comparison's own proof at read time, reports
unique outcome denominators separately from overlapping horizons and scenarios,
and withholds results whose source or protocol proof fails.

The separate `swing_benchmark_review.py --root ROOT --input PROPOSAL` path
validates a forward-window-only ETF corporate-action review; `--apply` appends
the accepted review under the existing runtime-then-pipeline lock discipline.
Its documented schema binds the exact immutable comparison, protocol, forward
bars and paired quote source. It requires retained issuer/SEC and independent
exchange evidence, authored reasoning, coverage and limitations after the exit
session. A distribution before entry cannot by itself invalidate this narrower
benchmark-path review. An unsupported split or distribution inside the evaluated
window remains a dependency. This review does not clear the original stock
signal history; the stock leg still needs its independent existing review.
Accepted research reviews require the normal full no-send recomposition, with
no additional delivery purpose or analyst slot.

At existing analyst reviews, inspect the handoff and outside research tasks
after urgent held risks and imminent events. Complete a sourced growth/company/
countercase/timing judgment through maintained writers, or retain its precise
dependency. A collected history, technical screen or refreshed clock alone is
neither completed investment analysis nor an eligible priority email.
