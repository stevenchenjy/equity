# Owner-requested research reviews

Recorded from the owner's explicit requests on 2026-09-14. These preferences
apply to interactive rechecks and their email delivery; they do not authorize
broker access, automatic trading, new recipients, extra scheduled sends, or a
change to portfolio risk limits.

## Delivery expectation

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
