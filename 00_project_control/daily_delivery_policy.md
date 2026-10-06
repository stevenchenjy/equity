# Equity Research — Daily Delivery Policy

## Limited status continuity after source failure (2026-10-06)

A failed full refresh remains failed and keeps its existing bounded recovery
attempts. It no longer necessarily suppresses useful, current held-plan status
for the entire attention window. The narrowly admitted fallback applies only
when `official_evidence` is the sole non-advisory soft failure, every required
canonical stage passed, and the current window's exact required market close
was validated. All other soft failures, hard failures, missing/stale market
data and corrupt or changed artifacts still block this fallback.

The refresh may seal a `limited_status_handoff` over the newly composed decision,
text and HTML bytes. The ordinary scheduler and sender independently validate
its current cycle/window, complete stage identities, source-bound workflow and
capital contracts, failed evidence gate and retained evidence blocker. It must
contain no eligible new/action candidate, positive execution quantity or order
draft. Existing same-purpose HOLD/review context can remain visible; source,
account, order and funding blockers stay intact. Expired plans remain expired.
No previous successful decision, price, DAY draft or stale quantity is reused.

The email labels this a **Limited evidence update**, separate from the action
cards. It grants no new order authority and does not claim the research passed.
The sender rechecks the handoff before credentials and again before a durable
send claim. Existing meaningful-change filtering, one-message-per-window
deduplication, unknown-send fences and final clock checks still apply. This is
not an automatic resend or permission to send outside the owner's windows.

## Same-day continuation under the owner's full-fill assumption (2026-09-28)

For a later report on the same ET date, use the owner's explicitly approved
**fully filled planning assumption** only for precise prior instructions whose
successful SMTP receipt and exact decision JSON, text and HTML are archived and
hash-verified. Label every resulting share/cash figure as assumed. Displayed
order levels can support an illustrative cash calculation before unverified
fees, slippage, gaps and settlement; they are not observed fill prices or
buying power. A placed stop/limit is not evidence of a fill. Pending, partial,
unsubmitted, expired or unknown orders require reconciliation.

The follow-up carries the earlier plan forward and does not issue its quantity
again as an additional order. All portfolio-changing draft quantities, including
other tickers that share cash or risk capacity, remain withheld while they would
rely on unreconciled pre-execution records. Canonical strategy eligibility and
risk limits do not change. There is no validated engine for sizing new trades
against this hypothetical post-fill account. Existing protective purpose is
retained; this presentation rule does not cancel protection or renew a DAY
price/deadline. Changes or opposite recommendations explicitly require a review
of the actual remaining exposure.

Watch/no-action messages do not create assumed trades. Narrative owner reviews,
quantity ceilings without a complete structured draft, missing archives and
uncertain delivery do not provide invented quantities. A later status message or
partial correction cannot erase earlier unresolved instructions. Continuation
metadata itself never triggers an email; the existing meaningful-change rule,
attention windows and durable delivery fences still govern sending.

The actual account, positions, orders, execution reports and performance facts
remain separate and unchanged. A newly recorded complete owner account snapshot
may supersede the assumption within the same afternoon only when the existing
snapshot validator binds it to current positions/account/confirmed executions,
it was recorded after the prior delivery, cash is owner-recorded rather than a
planning estimate, and a later complete sourced order observation validates.
An arbitrary hash/comment change is insufficient. Such a snapshot supplies a
fresh actual-state basis without claiming which fill caused it; all existing
canonical evidence and risk checks still apply. No previous day's hypothetical
fill is silently carried into today's account.

## Owner attention windows (2026-09-28; first new cycle September 29)

This section supersedes the former single after-13:30 schedule and one-normal-
message-per-day rule. Exact prior policies/configuration are retained under
`11_archive/schedule_before_owner_windows_20260928/`; archived settings are not
active. Existing completed legacy calendar cycles and send receipts retain
all original meaning and are not relabelled as missed new windows.

The owner normally has time 09:45–10:45 and 14:45–15:20 ET. On exchange sessions:

- Morning delivery may begin at 09:30 and must pass its final preclaim clock
  check by 10:30. It requires a fully passed current-cycle refresh, or the
  narrowly validated limited-status handoff above, started at or after 08:00,
  with the exact required previous-session REST data validated.
- Afternoon delivery may begin at 14:30 and must pass the final clock check by
  15:05. It requires its own passed refresh or limited-status handoff started
  at or after 13:30; a morning handoff alone cannot satisfy this checkpoint.
- Each stable window can send at most one materially changed ordinary email.
  Unchanged evaluations consume no send-attempt budget and remain eligible for
  later meaningful analyst updates inside that same window. A quiet window
  closes quietly. Missing required research closes with a precise local alert;
  it never catches up as a late evening trade instruction.
- Existing 15-minute launchd polling means these are eligible windows, not
  guaranteed arrival times. SMTP acceptance is not inbox-arrival evidence.
- Cross-date comparison uses the latest verified durable delivery meaning.
  Ordinary windows do not bypass an unresolved send claim/unknown receipt in
  the current cycle. Old unscoped successful normal receipts keep their whole-
  day fence; no private ledger rewrite or reset is performed.
- No new scheduled night-before email is enabled. The actual REST evening test
  returned HTTP200 with the requested current-session bar missing. Earlier
  evidence can support research preparation, but cannot establish a fresh close
  or a next-session opening price. An explicitly requested evening review keeps
  its existing separate authorization and must bind the intended session,
  conditional entry/max price, invalidation, available shares/funds and expiry.
  Do not imply that a DAY draft was submitted or that overnight broker handling
  or an opening fill has been verified.

Research runs at 08:00 with bounded recovery at 08:30/09:00/09:45, and separately
at 13:30 with 14:00 recovery. Morning success retires only morning retries.
Weekends retain research/recomposition for historical experimental outcomes,
without automatic trading-session email. The Codex analyst follow-up runs at
08:45 and 13:45 weekdays. Material outcomes completed after a window carry
forward; unchanged filler and expired DAY instructions are never resent.

## Current delivery and presentation rule (2026-09-26)

This section supersedes earlier same-calendar-day coverage and long scheduled
email presentation requirements for the maintained workflow. The owner reported
repeated old-format automatic emails and requested a full fix.

- Preserve daily research, current plan states, eligibility and history.
  Compare notification meaning with the latest durable delivery receipt across
  dates, including an evening requested review covering the next session.
- Record `delivery_meaning_v1` in every new claim/sent/unknown receipt. Only the
  latest receipt is the comparison baseline; never skip over a changed risk
  message by finding an older matching one. Explicit requested reviews and
  authorized corrections retain their existing separate delivery rules.
- Unreviewed watch/screen ranking changes, quotes, rejected-entry diagnostics,
  and clock-only aging of an unchanged plan/order snapshot do not independently
  warrant another automatic email. They remain visible in local reports.
- Changed held or reviewed-company evidence, maintained plan versions, broker
  order facts, recorded shares/cash, eligible proposals, conflicts, and data/risk
  gates remain reportable. An unconfirmed outcome is retained, never marked
  completed by notification suppression. No suppressed message cancels a
  deadline, verifies a fill, or permits an expired order to be renewed.
- Legacy delivery receipts can be compared only using an archived decision
  whose exact bytes match the receipt's recorded SHA-256. Missing or invalid
  evidence does not suppress a message. Preserve original bodies and ledgers.
- Current automatic messages use the same six-card layout as compact requested
  reviews, with English summaries, dated references, held plans, order checks,
  cash provenance, research candidates and concise risk rules. Do not append
  the full diagnostic report or raw mixed-language thesis text. Label automatic
  status updates separately from fresh analyst reviews. Legacy historical
  schemas retain their renderer compatibility; production uses the maintained
  workflow path.
- Formatting repairs do not authorize a resend or a test message. Regression
  checks must use local previews and mocked SMTP.

## Eligibility

The only authorized sender is `send_daily_email.py`. It requires:

- `daily_decision / phase5r_daily / phase5r_daily_only`;
- maintenance inhibit cleared only for `phase5r_daily`;
- the ET date on or after `operational_from`;
- a current decision artifact with truthful notification-policy fields
  (`send_recommended=true` for ordinary/correction delivery; the explicit
  owner-review path below also accepts a truthfully suppressed decision);
- all broker/order boundaries set to false;
- no existing blocking delivery state for the ET cycle.

## Frequency

- The owner selected `regular_delivery_mode=watch_or_action_change` on
  2026-09-14: the then-current single-window emails sent only when the
  watchlist or action recommendations change. Unchanged Saturday/weekly
  reports do not send. Weekdays and weekends use the same change test.
- Meaningful changes include nonheld candidate membership, eligibility,
  blockers or review conditions; eligible proposed quantities/limits; held
  action quantities/targets; and recommendation changes caused by account
  conflicts, data gates or fundamental weakening. Sorted semantic snapshots
  and normalized numbers prevent ordering or formatting from creating alerts.
- Quote/date changes, research scores, raw filing arrivals and a new research
  fingerprint do not trigger email by themselves. The separate notification
  fingerprint leaves the canonical research identity unchanged.
- On migration, compare to the prior valid decision artifact when no prior
  notification fingerprint exists. With no valid baseline, seed quietly.
  Within one ET cycle, preserve the original comparison anchor so repeated
  pre-send composition does not consume an undelivered change. Normal daily
  durable deduplication now limits ordinary delivery to one message per stable
  attention window, while preserving unresolved-send protection across windows.
- Massive Basic publication and refresh timing stay unchanged. The legacy
  `weekly_summary_weekday=friday` remains available for historical policy
  validation but does not authorize an unchanged digest in the active mode.
- A missing mode means historical `legacy_material_or_weekly`: raw material
  events and the Saturday-published Friday-close summary retain their former
  policy truth only for legacy validation. An ordinary send must match the
  active mode; an explicit owner/correction review can validate its original
  historical policy without rewriting the decision's send fields.
- Explicit owner-requested reviews and operational failure alerts are
  independent of this regular research cadence.
- No catch-up is allowed before the configured operational date.

## Action-email presentation (v2, 2026-09-05)

`email_brief.py` renders the subject, plain text and HTML from one
deterministic decision snapshot. This changes presentation, not portfolio
decisions, eligibility, thresholds, stability, scheduling or recipients.

- Lead with a short status subject, one conclusion, the verified reference
  close and the generation time in ET. Then show what needs attention,
  recorded positions/cash, evidence and limitations, and the next research step.
- Account conflicts and failed data gates override all lower-level proposals.
  Do not display trade-like quantities or hypothetical post-action cash while
  blocked. A pending order is not a fill. Recent applied fills are a separate
  receipt, based on structured reconciliation rather than historical notes.
- Only already eligible proposals may show quantities, trigger reasons and
  adjacent limitations. Adds still need two different valid closes. HOLD and
  pending stability do not request transaction approval. Missing valuation
  remains missing; passing basic financial checks does not certify valuation.
- Use readable Chinese, ordinary currency/share formatting, a small semantic
  holdings table, inline styles, no scripts/assets/trackers and no attachments.
  Detailed screening, calculations and raw reasons stay in the local daily
  decision report. Official filing links are HTTPS SEC links; ingestion date
  is not presented as disclosure date.
- AI experiments do not supply the conclusion or notification eligibility.
  Do not imply that a deterministic $0 model route describes total SHADOW
  spending. No new LLM calls or costs are introduced by rendering.
- Before SMTP configuration access or a delivery claim, v2 text and HTML must
  exactly match a fresh render of the decision; unsupported versions fail
  closed. Legacy unversioned artifacts retain their existing validation path.
  A format change does not authorize a correction or test send.

### Visible watch candidates (2026-09-14)

Every rendered report includes the actual canonical nonheld `watch_candidates`
under a watch/new-position section, even when none are eligible. Already held
names (including SPY) stay in holdings, rather than being duplicated as new
positions. Display the reference price and its exact canonical session date;
missing prices stay unknown and failed market gates remain labelled unverified.

Blocked or incomplete names explicitly show zero suggested new shares and no
buy order, with readable evidence, valuation, portfolio, cash or stability
blockers and conditions for another review. Do not expose stale positive
quantities or invent entry prices. Only a plan already accepted by the shared
view's eligibility and global guards can display positive quantities and its
existing review-price limit. Account conflicts, failed data, estimated cash and
stability holds retain priority. Unknown blockers remain unresolved, rather than
being treated as a pass. The section describes only the actual shortlist and
does not claim full-market coverage or alter notification cadence.

### Owner snapshots and flexible research funding (2026-09-11)

An explicit owner snapshot can update shares and fee-inclusive cost basis
without inventing separate fill prices/fees or replaying past sales. The manual
updater retains before/after snapshots and hashes privately. Only an exact
match to the current account, positions and confirmed-execution ledger may
supersede the old fill's state anchor; new pending/unapplied fills still block.

`cash_basis=ledger_estimate` identifies arithmetic from the last recorded cash,
not a verified broker balance. Optional planning-capital endpoints describe
research scenarios only and never increase cash or replace the production
denominator. Email may continue research with those scenarios, while omitting
precise trade quantities that depend on the unverified balance. Real trading
still requires the owner to verify available funds outside this system.

A user-requested one-off research appendix may be bound to the current
decision fingerprint and rendered with explicit separation from deterministic
decisions. The composer never reads or carries it forward; it cannot change
eligibility, thresholds, sizing or SHADOW evidence. Only the existing sender
and its normal/correction or explicit owner-review deduplication rules may
deliver that email.

Design sources, consulted 2026-09-05: the
[SEC Plain English Handbook](https://www.sec.gov/pdf/handbook.pdf) supports
clear hierarchy and removal of jargon;
[GOV.UK email guidance](https://www.gov.uk/service-manual/design/sending-emails-and-text-messages)
supports short subjects, important information first and a clear next step;
[FINRA Rule 2210](https://www.finra.org/rules-guidance/rulebooks/finra-rules/2210)
supports balanced information and prominent material qualifications; and
[FINRA Notice 24-09](https://www.finra.org/rules-guidance/notices/24-09)
explains that AI use does not remove communication-content responsibilities.
These inform conservative design for personal research; they are not a claim
that this system is a regulated adviser or has obtained regulatory approval.

## Refresh handoff and recovery

- Only the existing Keychain-backed dailyrefresh launcher supplies market and
  SEC identities. Dailydecision consumes the current complete validated handoff
  or the explicitly limited, zero-order status handoff described above,
  and requires its window-specific refresh checkpoint before composing/sending.
- The required REST session is a calendar target, not a provider publication
  promise. Data must pass the existing complete one-year session, OHLCV, source,
  universe and atomic publication checks. A HTTP200 partial response fails.
- Failed morning fetches get only the configured later attempts. An afternoon
  refresh reuses a verified current close, or attempts recovery when that close
  remains unavailable. No stale fallback or new data subscription is admitted.
- Waiting for research and unchanged eligibility checks do not consume the two
  bounded failed-send attempts per window. Unknown SMTP outcomes remain blocked
  across both windows; no automatic retry can manufacture non-delivery.
- The final sender checks the clock again before claiming a send. A passed
  handoff does not authorize sending outside the owner's window. Recovery after
  a closed window may improve research but cannot reopen that expired window.
- Runtime preflight failures still use the configured final 15:05 alert gate.
  The deployed launchd configuration proves installation, not future execution;
  inspect current runtime receipts and exact delivery archives for confirmation.

## Duplicate Protection

### Same-day requested-review precedence (2026-09-23)

A requested review sent or durably claimed on the current ET calendar date
covers routine scheduled screening for that date. The normal sender checks
the actual ledger timestamp, not the review's possibly previous-day canonical
cycle, under the existing delivery lock and before reading SMTP configuration.
Routine watch/discovery changes alone do not produce a second report.

New official material events, account conflicts, failed data gates, fundamental
weakening, or validated action plans remain eligible for the normal notification
checks unless the exact canonical decision was already covered by a same-day
owner review. New owner-review claims, completed sends and uncertain sends
include an `owner_review_coverage_sha256` marker in the existing reason field.
It hashes the entire canonical decision, including timestamps, gates, account,
orders, action details and material events, excluding only the separate owner
research appendix. Matching coverage prevents a second email describing the
same risk or plan; any canonical change retains the normal critical-content
checks. Historical rows without the marker keep their conservative behavior.
Explicit owner reviews and authorized corrections retain their own request and
content deduplication rules. This does not roll forward analyst prices, change
decision eligibility, or suppress a future day's research.

Scheduled messages use six compact cards with a clear automatic-data-update
label. They do not claim to replace a separately researched stop or exit date.
Rejected mechanical tactical price scenarios and raw diagnostic codes remain
in the local canonical decision rather than being mailed as alternative plans.
Validated positive drafts retain their complete conditions and risk limits.
The historical sent message bodies and delivery hashes must be preserved before
re-rendering current artifacts after a presentation change.

The sender uses a process lock and a durable append-only delivery ledger.

Blocking states for the same ET date:

- `send_claimed`
- `sent`
- `delivery_unknown`

The sender sequence is:

1. active-state and date eligibility;
2. decision eligibility;
3. exclusive delivery lock;
4. second ledger check;
5. brief and configuration validation;
6. durable `send_claimed` row with flush/fsync;
7. SMTP attempt;
8. `sent` or `delivery_unknown`.

Any failure after the claim disables automatic retry. A crash after delivery
therefore favors a missed status confirmation over a duplicate email.

### Explicit correction resend

- The scheduler never invokes a correction resend; the automatic path remains
  limited to one ordinary email per stable attention window.
- `--resend-correction` is a manual, user-authorized recovery path for a
  materially corrected brief.
- It requires a prior successful normal delivery for the same cycle date and
  changed decision, text, or HTML content hashes.
- A correction may cover the current or immediately preceding ET cycle date.
  This supports a next-morning repair without presenting prior-cycle evidence
  as a new daily decision.
- An explicit correction may run before the ordinary attention-window clock;
  maintenance, operational-date, active-workflow, validation, deduplication,
  and delivery-boundary gates remain enforced.
- At most one correction attempt is allowed for each exact content-hash set. A
  durable `correction_send_claimed`, `correction_sent`, or
  `correction_delivery_unknown` row blocks that same correction content from
  ever being attempted again; a newly changed version remains eligible.
- Correction messages use the subject prefix `[Equity 更正版]`.

### Explicit owner-requested review (2026-09-14)

The owner requests an updated email whenever they ask to redo/recheck the
review (including `重新复核`). After completing that review, invoke the existing
sender with `--send-owner-review REQUEST_ID`. This is an explicit-request
delivery mode, never a scheduler command. A distinct ID must correspond to a
distinct real user request; retries keep the same ID.

- Bind `owner_requested_research` to the canonical `decision_fingerprint`,
  `mode=explicit_one_off_research`, and the same `request_id` supplied to the
  CLI. IDs use 8–128 ASCII letters/digits/`_.:-`, beginning with a letter/digit.
- `reviewed_at` must include a timezone, be on the current ET date, and be no
  more than six hours old or in the future. `market_as_of` is an ISO trading
  session date between the latest provider-published close and the latest
  completed close, inclusive, using existing holiday and publication helpers.
  A holiday weekend does not make the most recent valid close stale.
- The canonical decision may be for the current or immediately prior ET
  cycle. Its existing notification policy, `send_recommended` and
  `send_reason` are revalidated as generated and are never changed to make an
  explicit review eligible. No prior scheduled delivery or changed-content
  hash is required: a user can request another review of unchanged conditions.
- Preserve maintenance, operational-date, active-workflow and broker/order
  boundaries. Only the ordinary attention-window clock is waived. Require the versioned
  shared renderer and exact decision/text/HTML correspondence before opening
  SMTP configuration; revalidate after obtaining the delivery lock. Explicit
  review MIME bodies are rendered from that validated in-memory decision;
  ledger hashes retain its original parsed JSON bytes and rendered text/HTML.
  Later replacement of shared artifacts cannot change the content sent or
  the delivery evidence recorded.
- Before SMTP, write `owner_review_send_claimed`; then record
  `owner_review_sent` or `owner_review_delivery_unknown`. Each reason includes
  `owner_request_sha256=<SHA-256 of request_id>` using the existing ledger
  schema. Any of those states blocks reuse of that request ID across cycles
  and content changes, before credentials are read. Uncertain delivery is
  never retried automatically.
- Use subject prefix `[Equity 应请求复核]`. Lead with the dated requested
  review and source links, preserving its line breaks. Display the original
  deterministic holdings table later with its actual reference-close date;
  when the research date is newer, label that table as an old-close baseline.
- Public research source links use exact HTTPS host allowlists, including
  permitted company IR, SEC, Federal Reserve, Investor.gov/FINRA and
  Stock Analysis price-history sources, plus Chase/JPMorgan order guidance.
  A secondary price source is labelled
  as market reference, not as an official financial filing.

This mode supplies the requested email without manufacturing a scheduled
material event, changing the daily decision state or registering a trade.

The local SMTP configuration must be a single-link regular file owned by the
runtime user with no group or other permissions. The sender opens it with
`O_NOFOLLOW` only after eligibility and deduplication pass.

## Boundaries

- The refresh pipeline has no sender or SMTP configuration reference.
- C2 and C3 are permanently retired before configuration read or child
  invocation.
- C6/C7 and D1/D2/D3 are not authorized by the active state and are unloaded.
- Verification does not open SMTP configuration or invoke a sender.
- No email attachment, broker connection, account read, order code, or trade
  execution is permitted.

## Display naming

The public `01_policies/equity_display_names.json` controls the sender display name and ordinary/correction/owner-review subject prefixes. The legacy private `sender_name` remains a compatibility field. Naming does not affect delivery eligibility, recipient identity or ledger deduplication. See `equity_naming_policy.md`.
