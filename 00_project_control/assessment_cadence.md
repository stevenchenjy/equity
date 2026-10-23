# Daily reviews, short assessments and delivery

Owner approval: October 21, 2026. The new delivery and short-assessment
contract takes effect October 22, Eastern Time. Deployment and future
execution are separate claims; consult the actual runtime receipts.

## Research cadence

Keep the substantive reviews at 08:45 and 13:45 ET on weekdays. They own the
longer company valuation, countercase, allocation and maintained-plan work.
Short assessments supplement this work at 09:30, 11:00, 12:30, 14:00 and
15:30 ET, a 90-minute cadence beginning at the regular market open. The
existing exchange-session and early-close calendar suppresses short checks
on holidays and after the actual close. A late wake does not replay a day's
missed assessments or renew an expired instruction.

Each short assessment has a ten-minute budget and selects one or two useful
items: urgent held risk, new official company evidence, approaching earnings,
changed account records, or a precise unfinished analytical task. Preserve
durable partial work and its next step. Unchanged inputs may support further
analysis of an unfinished case; they do not justify repeating a completed
narrative or the same unavailable external dependency at every wake.

The short worker uses nonblocking runtime/pipeline admission, durable slot
reservations and source-bound completion receipts. It does not wait an hour
behind another refresh, overlap an active assessment, refetch the full EOD
universe at every wake, send mail or execute trades. Bounded official-news
and earnings-calendar checks supply fresh public context. Their success is
not analyst completion. The October 22 owner-approved
[intraday observation and risk overlay](market_intraday_risk.md) additionally
collects all held symbols during a real admitted claim. It validates original
Nasdaq Last Sale responses, explicit current trade clocks, complete coverage
and a bound canonical prior close. These dated observations supplement the
completed-close decision; they never replace its price history or entry gates.
Missing, partial or expired marks cannot establish a current portfolio loss.

Accepted research still uses the existing writers and lock order. Release
mutation locks, run the full operator-safe no-send recomposition after an
accepted amendment, and inspect current final outputs. A failed or expired
claim retains its history. The deterministic capital engine remains the
only source of eligible quantities, prices and portfolio-changing drafts.

Public collection can change exact publication bindings even when its news
or calendar meaning is unchanged. A short claim reports this separately as
`publication_recomposition_required`; it cannot retire itself as unchanged
or complete a no-action result while those bindings are stale. For public-only
changes with unchanged account, market and analyst stores, release mutation
locks and use the claim-bound offline publication refresh:

```sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/messssi/LocalRuntime/equity/09_scripts/equity_research/run_short_publication.py --root /Users/messssi/LocalRuntime/equity --claim-id CLAIM_ID
```

This rebuilds the existing downstream incorporation, valuation, portfolio,
decision, risk and final publication closure without repeating SEC network
collection, objective research, escalation or experiments. It preserves the
ten-minute deadline and has a separate receipt; it is not a passed full research
refresh or completed company analysis. Every final gate and exact email binding
still passes. Changed account/market bytes, actual analyst amendments, corrupt
sources or rewritten collector history cannot use this route. The opportunity
journal is mixed: only append-only events passing the full existing source,
hash-chain, owner and timestamp validation count as collector observations.
Real analyst transitions still require accepted record receipts and the
full declared no-send refresh stage set, including the offline intraday risk
projection. Completion checks derive that required set from the deployed code,
not an older fixed stage count. An elapsed claim becomes durably expired on the next
claim/completion entry, including an out-of-window wake, without replay.

A truthful degraded, zero-order full publication can document the
remaining public-data failure for a no-action result; it is not a passing
research refresh or an accepted analytical amendment. Accepted amendments
retain their stricter completion requirements.

The local host also needs actual operating-day availability; see
[Local session availability](session_host_availability.md). An installed active
schedule is not proof that a sleeping host ran or that SMTP accepted a message.

## Two daily briefs

The normal morning (09:30–10:30 ET) and afternoon (14:30–15:05 ET) windows
each own one mandatory brief on a trading day, including a truthful no-action
conclusion. An unchanged recommendation does not suppress this checkpoint.
Existing polling and machine/SMTP availability mean this is a required
delivery attempt in the window, not an inbox-arrival guarantee.

When a current validated research handoff is unavailable, the required brief
uses a separately validated, current status-only artifact. It reports the
observed failed, pending or missing handoff without recycling old order
quantities or prices, relabelling stale research as passed, or bypassing any
investment gate. Original source receipts and unknown-send protection remain.
There is no late evening catch-up after a closed window.

The underlying `regular_delivery_mode=watch_or_action_change` and
`unchanged_daily_email=false` retain their original event-comparison meaning.
The separately adopted `mandatory_daily_briefs` purpose is what authorizes
an unchanged daily checkpoint; it does not falsify `send_recommended`.

## Extra action and priority alerts

The existing scheduled sender alone may send an extra alert while the exchange
is open. It requires either a material validated action change, including
withdrawal of a previously delivered recommendation, or a substantive
source-bound analyst research-priority change. A priority alert can state
which company should be researched first and why without implying that it is
eligible to buy. It identifies the evidence, remaining dependency and next
research step separately from order instructions.

The priority writer retains an ordered, bounded research judgment with actual
authorship time, sources and validity. It grants no allocation, model,
strategy-adoption or execution authority. Raw scores, watchlist movements,
calendar polling, source-arrival titles alone, clock changes and unreviewed
queue reshuffling do not independently authorize an alert. Intraday price polling,
a changed observation timestamp, a portfolio price-only decline or an observed
existing risk condition likewise requires the existing source-bound analytical
and delivery eligibility; none creates a new loss threshold or email rule.

Daily briefs and alerts have distinct durable purposes. Compare alert meaning
with exact archived delivery context, including claimed and uncertain sends;
do not search historical messages for an older convenient match. Identical
meaning stays quiet. A genuinely changed A-to-B-to-A sequence can be reported
without treating the new A as an old duplicate. A daily brief that covers the
same change prevents a redundant extra alert.

Preserve pre-SMTP durable claims, immutable bodies and all unknown-send fences.
A priority-only alert does not imply that omitted canonical drafts were sent,
filled or cancelled. Earlier delivered quantities and unresolved executions
remain in the existing follow-through and account reconciliation controls.
The owner-approved full-fill scenario remains explicitly hypothetical and
cannot supply actual funds or verified order outcomes.

## Boundaries and acceptance

The approved planning basis, combined SPY/QQQM core floor, aggregate stock
limit, absence of a fixed name cap, valuation thresholds, event/tactical risk
limits and human-only execution remain unchanged. No test mail or trade is
authorized by deployment verification.

Test unchanged mandatory checkpoints, changed priority without a trade, quiet
score-only churn, same-poll brief/alert deduplication, repeated alerts,
uncertain delivery, partial/unknown execution, source mutation, expired
plans, missing/failed refreshes, early closes, holidays, overlapping work and
late wakes. Inspect the actual deployed configuration, installed schedules,
no-send refresh and generated artifacts. Mocked SMTP tests establish code
behavior only; actual future execution and inbox receipt require their own
receipts.

## Operator entry points

The same-chat short heartbeat enters through the production Python runtime:

```sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/messssi/LocalRuntime/equity/09_scripts/equity_research/run_short_assessment.py --claim --refresh-public --root /Users/messssi/LocalRuntime/equity
```

`--check` is read-only. `--claim --refresh-public` performs the actual due,
calendar, active-claim and lock checks before any public request. Read its
returned receipt; a blocked or not-due claim is not completed analysis.

A completed claim uses `--complete --input PROPOSAL`. The deployed
`short_assessment.py` defines `equity_short_assessment_v1`, source-bound item
conclusions, actual accepted record identities, and explicit continuation.
Do not replace an unfinished result with a fabricated completed amendment.
Private transitions are retained under
`08_reviews/analyst_followthrough.local/short_assessments/<claim_id>/` and
current slot state under `00_project_control/run_logs/short_assessment.local.json`.

Substantive ordered-priority judgments use the separate admission CLI:

```sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 /Users/messssi/LocalRuntime/equity/09_scripts/equity_research/delivery_assessments.py --root /Users/messssi/LocalRuntime/equity --input PROPOSAL
```

Validate first, then add `--apply` while holding the documented mutation locks.
Read the current deployed schema before preparing a proposal. The writer
retains immutable inputs, sources, versions and history; its current view must
survive no-send recomposition. It cannot produce an order or allocate capital.

The normal fifteen-minute sender poll checks a due mandatory brief before an
intraday alert. A brief that already reports the current meaning covers that
meaning; a later poll does not send a second copy. A truthful status-only brief
contains no trading advice and does not erase the preceding verified advice.
Neither changing a delivery purpose nor a subsequent priority-only alert
clears an uncertain send or an unresolved earlier instruction.
