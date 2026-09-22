# Owner-requested research reviews

Recorded from the owner's explicit requests on 2026-09-14. These preferences
apply to interactive rechecks and their email delivery. They do not authorize
broker access, automatic trading, new recipients, or extra scheduled sends.
The owner's later risk-policy direction is recorded separately below; email
delivery authorization itself never changes risk limits.

## Risk-policy direction (2026-09-14 evening)

- The owner explicitly requested less defensive research and permitted
  relaxing configurable risk thresholds. Interpret this as reducing
  unnecessary restrictions, not lowering percentage caps and thereby making
  the system more restrictive.
- The inherited 30% active-stock cap and 6%/8% individual-stock caps are
  configurable planning choices, not Chase requirements or empirically
  demonstrated optimal allocations. Distinguish a policy blocker from
  missing evidence and from a negative investment thesis.
- Do not optimize thresholds to admit a ticker merely because it just rallied.
  Preserve verified evidence, cash/reserve checks and manual-only execution.
- On 2026-09-14 the owner directed the caps to the reasonably least restrictive
  setting in the context of asking for less defensiveness. The selected starting
  profile is the previously proposed moderate relaxation: active-stock hard cap
  50%, new/held individual-stock caps 15%. This interprets the request as lowering
  restriction strength, not lowering numerical caps. It is a preference choice,
  not an empirically optimized portfolio. The explicit research overlay is the
  authority; archived account-state caps remain historical financial-record
  bytes. Evidence-tier targets, cash reserve and manual-only boundaries remain.
- Review duplicate and indirect constraints, including theme-label-only fit
  deductions, integer-share rounding, and concentration-derived scores that
  can create an apparent thesis exit. Any change must have regression tests
  and distinguish concentration concerns from business evidence.
- The owner authorized installing suitable analytical skills. Installed
  methods can help audit assumptions; they are not evidence of superior
  returns and do not run inside the unattended deterministic scheduler.

## Delivery expectation

- Prefer email and concise text for research results. Do not proactively open
  HTML/web preview panels unless the owner asks to inspect one. A local email
  preview is not a hosted site and is not needed for email delivery.

- Frequency preference confirmed on 2026-09-14: regular research emails only
  when the watchlist or actionable recommendation changes, not a mandatory
  daily message. An unchanged weekly digest is not an exception to this
  preference. Operational failure alerts remain separate. Explicitly
  requested rechecks still receive one email under the rule below.
- “Redo the check”, “重新复核”, and equivalent requests mean complete a new
  review and email it once to the existing configured recipient. Do not ask
  again whether to email that review.
- A no-action conclusion still belongs in the requested review email. The
  normal scheduled report may remain suppressed as unchanged.
- Use `send_phase5r_daily_email.py --send-owner-review REQUEST_ID` with the
  validated, timestamped `owner_requested_research` payload bound to the actual
  canonical decision fingerprint. Read the daily delivery policy first.
- Give each real owner review a stable request ID. Do not mint a new ID merely
  to retry a sent or uncertain SMTP attempt. Preserve claims, sent records,
  uncertain-send protection and recipient configuration.
- Verify the rendered text and HTML contain the requested new instructions
  before sending. Report SMTP acceptance accurately, not guaranteed arrival
  in the inbox. On an uncertain send, investigate without blindly resending.

## Required review content

- Every daily report must explicitly distinguish: tonight/next-session orders,
  nonheld watchlist, and eligible buy/sell review plans. State zero new shares
  and no new order when appropriate; a watch candidate must not disappear
  simply because it is not yet eligible to buy. This content requirement is
  separate from email frequency, which remains governed by the delivery policy.
- Order a short interactive watchlist by a stated research priority. Explain
  what to observe and when to recheck. If quoting a price observation level,
  identify its dated source or analyst-selected basis and say whether it is
  only a review trigger, not a submitted order or automatic buy signal.
- Positive proposed share counts require complete evidence and portfolio
  checks, including tier-specific whole-share exceptions, single-stock caps,
  total active-stock allocation, confirmed cash and reserves. A hypothetical
  later quantity must be labelled separately from today's recommendation.
  Do not force a daily buy recommendation merely to provide a nonzero count.
- Lead with a clear analyst preference and its tradeoffs, not only “range
  research” or “pending human review”. Distinguish evidence, judgment and
  conditional order drafts. The owner makes all actual trades outside this
  system.
- Use verified, explicitly dated prices. Distinguish the new review's quotes
  from any older scheduled baseline, and never relabel yesterday's close as
  a live quote.
- Reconcile known share counts, estimated cash and actual account value.
  Never use a proposed funding range as deposited cash. If the ledger is not
  confirmed, show how the order quantity depends on actual account value;
  do not quietly relax a hard cap for integer-share rounding.
- For every held or specifically requested ticker state: hold/buy/sell/watch
  preference, shares added or reduced (including zero), price and its basis
  when applicable, order type, time in force, exact applicable session/date,
  conditions for cancel/review, and thesis/risk rationale. An observation
  level is not an actual resting order or a guaranteed support level.
- For nonheld names, explain research/evidence and position-size blockers,
  and define what would merit another review. Missing fair value is missing
  evidence, not a fabricated price or a confident bearish conclusion. ETF
  company valuation should be marked not applicable with an explanation.
- Include all holdings, tickers named by the owner, and previously material
  watch candidates in the interactive review's coverage check. A top-three
  automated shortlist must not silently exclude a specifically requested
  name. Do not claim the scheduled scanner has broader catalyst coverage
  than its actual implementation.
- Explain a missed move using the contemporaneous inputs and code path;
  do not claim foresight from a subsequent rally or guarantee future gains.

## Broker and order mechanics

- Broker: Chase app, as confirmed by the owner on 2026-09-14. Use current
  official Chase/J.P. Morgan Self-Directed documentation for supported order
  types, whole/fractional shares, expiration and session restrictions. Do not
  assume a GTD, OCO, or trailing-stop option exists because another broker
  offers it; the owner's actual ticket is authoritative.
- For short-lived research tied to the next regular session, prefer a DAY
  draft with an explicit date; do not extend it to GTC by default or across
  a major scheduled event without a reasoned review.
- Explain that a sell limit is a minimum acceptable execution price, not
  downside protection. A stop may slip and a stop-limit may fail to execute.
  No fill means the underlying exposure remains.
- Require a fresh quote, actual shares/cash and pending-order check before
  the owner submits a draft. Confirm cancellation/remaining quantity before
  replacement; never stack conflicting same-share sell orders.

## Boundaries

These preferences improve specificity and delivery. They do not certify an
incomplete valuation, promote a watchlist name to an eligible buy, change
whole-share or portfolio caps, connect to Chase, or submit any trade.


## One-year evaluation and tactical orders (2026-09-22)

The owner accepts a 40–50% portfolio drawdown and explicitly permits holding
periods of days or less than one week alongside longer holdings and planned
exits/re-entries. This is tolerance, not a loss target or a guaranteed floor.
The evaluation horizon is one year; an individual tactical trade has a separate
maximum five-session review/exit date. No assumption of positive weekly returns
is permitted. The owner asked to apply the four rules to existing regular emails:

1. State setup/catalyst, entry trigger and maximum price, invalidation, target,
   whole-share size, order type/session/expiration and exit/review date before
   entry. Separate core positions from tactical trades.
2. Planned risk is at most 0.5% of account value per ordinary tactical trade,
   0.25% for event exposure, and 2% across simultaneous tactical trades. Initial
   tactical exposure per name is at most 5%; size to the smallest cash, position
   and risk allowance. Gaps/slippage can exceed planned risk.
3. Require at least 2:1 plausible reward to planned loss for a fresh tactical
   entry, and reassess/exit in three to five sessions. An unsuccessful short
   trade cannot silently become a long-term holding. These rules are a research
   discipline, not a backtested profitable strategy.
4. Use explicit exit/re-entry triggers and maximum repurchase prices. Preserve
   a core holding when the business thesis remains intact rather than selling
   everything on a guessed pullback. Never chase or automatically average down.

The planning profile is 60% economic core, up to 30% tactical capacity and 10%
cash. In this codebase's different asset-type taxonomy it is represented as
40% broad ETFs, 50% individual stocks and 10% cash. The economic core includes
20 percentage points of individual stocks. This is a destination for staged
research, not an instruction to fully deploy cash or relax stock/ETF evidence
gates. The existing 50% aggregate-stock and 15% single-stock hard caps remain.
The precise cash reserve and current account values remain in ignored local
account records; the published configuration's reserve is a default only.

Use the owner's directed total Cash & Sweep assumption for scenario planning,
not an amount added on top of the displayed broker balance. This is an owner
assumption, not confirmed settled cash or a newly verified deposit. Preserve
cash_basis=ledger_estimate and source provenance in the audited local snapshot.
Exact holdings, share counts, costs, cash, order IDs and account values belong
only in ignored local files, never in the public source repository. Subsequent
fills must be reconciled before a scenario becomes an eligible order draft.

Regular delivery remains the existing after-13:30 ET watch/action-change mode:
check daily, email on a meaningful new/changed buy/sell/watch plan, and do not
send unchanged filler. Include material tactical price/quantity/invalidation or
order-status changes in notification comparisons. End-of-day inputs cannot
verify an intraday trigger, a fill, settled funds or an exhaustive event calendar.
Every positive hypothetical draft must list unresolved assumptions separately;
it is not today's cleared order quantity. Preserve full named coverage even
when a candidate is not in the ranking shortlist. No duplicate scheduler, new
recipient, live broker link or automated execution is authorized by this change.


## Email readability (2026-09-22 follow-up)

Use one language and one primary narrative per message. For interactive reviews,
set presentation=compact and provide at most six short sections, with a summary
first and one card per trade. Use short labelled lines for shares, entry trigger,
limit, stop, target, risk and expiry. Put sources in a small link row. Do not append
the full older automated report to an owner review; retain its date and eligibility
distinction in a short footer. Formatting-only corrections must explicitly retain
the original price date and conclusions. Scheduled reports keep the four rules
below the decisions rather than ahead of every trade. Preserve all material
conditions and unknowns; brevity must never turn a scenario into a cleared order.
