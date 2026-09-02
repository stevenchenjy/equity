# Phase 5R Daily Delivery Policy

## Eligibility

The only authorized sender is `send_phase5r_daily_email.py`. It requires:

- `daily_decision / phase5r_daily / phase5r_daily_only`;
- maintenance inhibit cleared only for `phase5r_daily`;
- the ET date on or after `operational_from`;
- a current decision artifact with `send_recommended=true`;
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
- At most one correction attempt is allowed for each exact content-hash set. A
  durable `correction_send_claimed`, `correction_sent`, or
  `correction_delivery_unknown` row blocks that same correction content from
  ever being attempted again; a newly changed version remains eligible.
- Correction messages use the subject prefix `[Phase 5R 更正版]`.

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
