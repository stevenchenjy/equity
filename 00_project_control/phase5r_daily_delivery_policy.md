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

- Weekdays: send after 18:30 ET only for a material decision/evidence change;
  also send the configured Friday summary. Suppress unchanged ordinary days.
- Weekends: send only for a new material official filing, a decision fingerprint
  change, or an account-state conflict.
- No late-night catch-up is allowed before the configured operational date.

## Refresh handoff and recovery

- Only the Keychain-backed `dailyrefresh` launcher may supply the Massive
  credential and SEC User-Agent identity.
- The `dailydecision` job never receives either credential. It consumes a
  persisted refresh handoff only when that handoff is for the current ET cycle,
  the currently completed market session, and has no hard or soft failures.
- Refresh-time decision composition never applies the 18:30 send clock. The
  scheduler owns that clock, so a fully passed 17:45 handoff remains eligible
  when `dailydecision` evaluates it after 18:30.
- Regular-session close import is attempted at bounded ET slots `17:45`,
  `18:15`, `18:45`, and `19:15`. A later attempt stops being necessary as soon
  as the current close and complete deterministic refresh pass.
- Waiting for a current refresh does not consume either of the two SMTP/send
  attempts. At 20:00 ET, an unresolved refresh becomes one terminal local
  automation alert rather than an unbounded retry loop.
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
