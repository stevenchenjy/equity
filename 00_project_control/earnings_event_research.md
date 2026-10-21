# Independent earnings-event discovery and research

Approved implementation: October 21, 2026. Earnings research is a separate
attention route from the momentum shortlist. It does not adopt an investment
strategy, add a security to the canonical universe, change a valuation or risk
limit, or authorize execution.

## Discovery and coverage

The existing full refresh runs `refresh_earnings_events.py` before opportunity
intake. In its ordinary public-fetch mode it queries Nasdaq's public earnings
calendar for every weekday in a rolling 14-calendar-day horizon. The existing
no-send reuse mode verifies retained sources without HTTP. A deliberate public
refresh is also available from production:

```sh
python3 09_scripts/equity_research/refresh_earnings_events.py --refresh --root /Users/messssi/LocalRuntime/equity
```

This is an explicit bounded anonymous public request, not a paid service or a
broker connection. Each date gets one attempt per scan, with response-size and
timeout limits and no redirects/retries. Original responses, actual observation
times and immutable scan receipts are retained under
`03_source_data/equity_research/earnings_events.local/`; the append-only scan
index is `earnings_events.local.json`. The status receipt names failed dates and
quarantined rows. One failed date or malformed row cannot imply an empty market.
Stale, failed, conflicting and absent-on-rescan observations remain explicit.
Absence alone does not prove cancellation. History is never reset to repair an
inconsistency.

Coverage means all valid **returned calendar leads on queried dates**. It is
neither complete market coverage nor full fundamental research. Nasdaq returns
date/session estimates without issuer-confirmation or original-publication
timestamps. Preserve `exchange_calendar_estimate`; verify the issuer's notice
before relying on its exact release schedule. A webcast time is not the results
release time. Actual `event_at` stays unknown when the source cannot establish
it. Research deadlines conservatively use 16:00 ET for after-close leads and
00:00 ET for pre-market/unknown-time leads. These are attention cutoffs, never
invented exact release times or order expiries.

The actual local first detection establishes whether our process was early.
An old public notice fetched today cannot prove we assessed it yesterday.
Duplicate scans preserve first detection; schedule changes retain their versions
and need confirmation. Elapsed unreviewed events remain visible as missed work.

## Attention and objective work

Every verified lead may create a `catalyst` observation with trigger
`upcoming_earnings_calendar`, regardless of momentum rank, configured candidate
membership or existing issuer-news coverage. All detections are retained; a
bounded queue is not described as completed coverage. Imminent deadlines receive
attention before ordinary momentum and unchanged capital-escalation work, after
urgent held/adverse risk. Lower-priority attention can be deferred without
deleting original evidence. Existing research-capacity and public-SEC request
bounds remain effective, with deadline-aware access to the shared objective
budget. Capacity deferral and insufficient evidence remain visible.

Outside-universe objective work uses the existing research-only SEC dossier
path. It does not add canonical price/fundamental rows. A completed dossier is
not an analyst conclusion, event valuation, or conditional plan.

## Analyst review and advice

During recurring work, read the current event view alongside the backlog and
opportunity journal. After urgent held risk, prioritize events whose remaining
time permits useful research. Do not repeatedly collect unchanged dossiers while
allowing a near-term event to pass without a recorded outcome. When time or
evidence is insufficient, retain a precise no-entry/dependency conclusion.

Use the existing `update_research_assessment.py` check-then-apply writer under
the runtime/pipeline lock order in `analyst_followthrough.md`. An event-specific
proposal includes `earnings_event_review` with `event_id`, `expectations_case`,
`priced_in_assessment`, `valuation_case`, `downside_case`, `recheck_condition`
and retained `sources`. State unknown expectations or unavailable valuation
honestly. The review must bind the detected event's source and be recorded
before its conservative deadline; its next-review time cannot extend beyond
that deadline. Generic historical reviews do not complete a new earnings task.

The final projection distinguishes detection, waiting/capacity, research in
progress, reviewed without entry, eligible conditional plan, schedule conflict
and elapsed unreviewed work. A review can explicitly reject an entry or record
why research is still insufficient. Eligibility requires a current event case
and a complete positive draft from the existing canonical capital engine. The
calendar, assessment and display cannot create that draft. Outside-universe
canonical admission, company-specific thesis/valuation, price, allocation,
funding, event-loss and reward/risk requirements remain independent. The event
tactical planned-loss budget remains 0.25%, aggregate tactical planned risk 2%,
with existing 2:1 minimum plausible reward/risk and human-only execution.

## Publication and delivery

The final decision, separate email research section, dashboard event panel and
production status show the same source-bound event lifecycle. Research belongs
below the actionable BUY/SELL cards. Unreviewed detections never appear as order
instructions. The ordinary sender may recognize a newly completed, current
event-specific advice outcome under its existing meaningful-change policy;
bulk detections, refetch clocks and queue churn do not authorize filler email.
Delivery windows, deduplication, recipients and sending authority are unchanged.

After accepted research, release mutation locks and run the existing full
no-send launcher. Inspect actual final artifacts and dated source bindings;
do not infer delivery, pre-event review or investment performance from a passing
software test or a queued task.
