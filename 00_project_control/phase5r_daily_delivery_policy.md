# Phase 5R Daily Delivery Policy

## Eligibility

The only authorized sender is `send_phase5r_daily_email.py`. It requires:

- `daily_decision / phase5r_daily / phase5r_daily_only`;
- maintenance inhibit cleared only for `phase5r_daily`;
- the ET date on or after `operational_from`;
- a current decision artifact with truthful notification-policy fields
  (`send_recommended=true` for ordinary/correction delivery; the explicit
  owner-review path below also accepts a truthfully suppressed decision);
- all broker/order boundaries set to false;
- no existing blocking delivery state for the ET cycle.

## Frequency

- Send after 13:30 ET only for a material decision/evidence change. Suppress
  unchanged ordinary cycles.
- Massive Basic publishes a finalized close on the following calendar day.
  The configured Friday-close weekly summary is therefore sent on Saturday,
  after that close is published.
- Other weekend cycles send only for a new material official filing, a
  decision fingerprint change, or an account-state conflict.
- No catch-up is allowed before the configured operational date.

## Action-email presentation (v2, 2026-09-05)

`phase5r_email_brief.py` renders the subject, plain text and HTML from one
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

- Only the Keychain-backed `dailyrefresh` launcher may supply the Massive
  credential and SEC User-Agent identity.
- The `dailydecision` job never receives either credential. It consumes a
  persisted refresh handoff only when that handoff is for the current ET cycle,
  the latest market session published under the Basic EOD SLA, and has no hard
  or soft failures. Market close alone does not satisfy this publication gate.
- Refresh-time decision composition never applies the 13:30 send clock. The
  scheduler owns that clock, so a fully passed 12:45 handoff remains eligible
  when `dailydecision` evaluates it after 13:30.
- The latest published close is attempted at bounded ET slots `11:15`, `11:45`,
  `12:15`, and `12:45`, including Saturday so the Friday close can be consumed.
  A later attempt stops being necessary as soon as the latest published close
  and complete deterministic refresh pass.
- Waiting for a current refresh does not consume either of the two SMTP/send
  attempts. At 15:30 ET, an unresolved refresh becomes one terminal local
  automation alert rather than an unbounded retry loop.
- That refresh-deadline terminal may clear automatically only after a fully
  passed handoff for the same ET cycle appears. Delivery-unknown and exhausted
  SMTP-attempt terminals never auto-clear, preserving duplicate protection.
- A degraded decision may be retained as fail-closed research evidence, but it
  never counts as scheduler success and never authorizes email.

## Duplicate Protection

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
  limited to one email per ET cycle date.
- `--resend-correction` is a manual, user-authorized recovery path for a
  materially corrected brief.
- It requires a prior successful normal delivery for the same cycle date and
  changed decision, text, or HTML content hashes.
- A correction may cover the current or immediately preceding ET cycle date.
  This supports a next-morning repair without presenting prior-cycle evidence
  as a new daily decision.
- An explicit correction may run before the ordinary 13:30 ET scheduler gate;
  maintenance, operational-date, active-workflow, validation, deduplication,
  and delivery-boundary gates remain enforced.
- At most one correction attempt is allowed for each exact content-hash set. A
  durable `correction_send_claimed`, `correction_sent`, or
  `correction_delivery_unknown` row blocks that same correction content from
  ever being attempted again; a newly changed version remains eligible.
- Correction messages use the subject prefix `[Phase 5R 更正版]`.

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
  boundaries. Only the ordinary 13:30 clock is waived. Require the versioned
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
- Use subject prefix `[Phase 5R 应请求复核]`. Lead with the dated requested
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
