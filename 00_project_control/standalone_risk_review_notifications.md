# Standalone held-risk review notifications

Owner approval: November 8, 2026. The owner explicitly approved the independent,
human-review-only risk notification proposal from the reliability review. The
permission is recorded in `active_production_config.json` under
`notifications.risk_review_alerts`; its effective date is `2026-11-08` in Eastern
time. An absent permission object, disabled permission or future effective date
does not enable this route. Earlier delivery archives retain their original
schema, permission and rendering semantics.

## Approved scope

The existing installed sender may send a separately typed risk-review alert for
either of these independently validated conditions on positive recorded exposure:

- `approved_risk_condition_crossed`: a dated, admitted observation newly crosses
  an already-approved held risk condition applicable to the current position and
  maintained plan/version.
- `held_review_or_protection_unavailable`: required held review or protection
  becomes unavailable while exposure remains unresolved. Identify the missing,
  expired, contradictory or unverified input precisely; do not turn an unknown
  observation into a claimed numerical breach.

At the first authorized check, an already-active uncovered condition may be
reported once as an observed existing condition without claiming it newly began;
recurrence requires verified intervening recovery, and mere absence from a brief
does not establish recovery.

This route does not require a new entry, capital action or substantive analyst
priority change. It creates no loss percentage, concentration cap, valuation
override, trading instruction, maintained plan, broker protection or strategy
adoption. A closed position's old stop and an expired order remain historical.
Raw price movement, a refreshed timestamp, a repeated source receipt or an
unchanged unresolved state alone does not qualify again.

## Existing cadence, sender and recipient

Use only the existing short-assessment slots: 09:30, 11:00, 12:30, 14:00 and
15:30 ET on a verified exchange session. The existing fifteen-minute slot grace
ends at the earlier of slot time plus fifteen minutes and actual regular close.
It is not an additional fifteen minutes after a completed ten-minute worker.
The short worker's ten-minute budget, holiday/early-close calendar, admission
locks and no-catch-up behavior remain unchanged. No schedule is added.

The installed scheduled sender owns eligibility, rendering, durable claims,
transport and receipts. It uses the existing configured recipient; the new
permission has no recipient override. The research worker records useful
source-bound conclusions, completes its normal no-send publication obligations
and inspects outcomes. It must not invoke SMTP, the sender, owner-review or
correction modes to deliver this alert. Separate owner-approved extended-hours
and long-term-watch workflows retain their own existing authority.

## Required message and duplicate protection

Each alert identifies the ticker, applicable plan/version or its absence,
condition, dated observation and freshness limits, account/protection uncertainty,
precise responsible resolver and next existing review expectation. It clearly
requests human review and states that it creates or renews no order. A valid
observation for one holding must not imply validated prices or NAV for others.

Retain the exact source-bound decision, typed delivery purpose and immutable
text/HTML. Deduplicate the same ticker/plan/condition state against actual recent
delivery context, including a mandatory brief that already covered it. A mere
new source clock does not reopen an identical alert. A material intervening
state can establish a new episode, subject to the same validation and current
window. Keep pre-send claims and claimed/uncertain-send fences; no automatic
retry can resolve unknown transport acceptance. Prior-cycle legacy uncertainty
remains retained and is not marked resolved: only a later strictly verified
substantive advice delivery, not a status-only or risk-only message, can admit
an unrelated new purpose without retrying the old uncertain content; current-cycle
and risk-purpose unknown-send fences remain in force. At most one bundled
risk-review message per existing slot reports eligible changed holdings without
duplicating an already covered state.

This permission does not authorize a setup/test email, a Sunday replay, an
extra research schedule, or a message outside its actual permitted window.
Deployment, no-send previews, mocked SMTP behavior, an actual eligible send and
verified recipient delivery must be reported separately.
