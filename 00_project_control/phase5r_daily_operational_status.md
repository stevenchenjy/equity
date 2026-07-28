# Phase 5R Daily Operational Status

Generated: 2026-07-27 ET

## Active state

- Workflow: `daily_decision`
- Pipeline: `phase5r_daily`
- Email source: `phase5r_daily_only`
- Time zone: `America/New_York`
- Maintenance inhibit: cleared only for `phase5r_daily`
- Broker connection, account read, order code, and automatic execution:
  prohibited
- Execution: manual outside the repository
- Model registry: `offline_fixture`
- Model canonical/email influence: disabled

The read-only canonical guard passes. It confirms that weekly C1–C7 and
schedulers D1–D3 cannot be active inputs or regain delivery authority.

## Scheduler state

- `com.steven.phase5r.dailyrefresh`: loaded; installed plist matches template
- `com.steven.phase5r.dailydecision`: loaded; installed plist matches template
- `com.steven.phase5r.dailybrief`: unloaded
- `com.steven.phase5r.weeklyconviction`: unloaded
- `com.steven.phase5r.weeklycatchup`: unloaded
- `com.steven.phase5r.llmshadow`: unloaded and not installed

The two daily LaunchAgents use `RunAtLoad=true`, `KeepAlive=false`, and
`StartInterval=900`. The refresh wrapper checks weekday slots at 08:15, 12:30,
16:15, and 17:45 ET and one weekend slot at 12:00. The decision wrapper checks
after 18:30 ET, caps automatic attempts at two, and records completion by
cycle date.

LaunchAgents do not run while the Mac is powered off or fully asleep. A later
wake can cover due slots for the current date; it does not guarantee
reconstruction of a prior day's missed state.

## Latest completed daily cycle

- Generated: `2026-07-27T19:01:56-04:00`
- Market snapshot rows: `29`
- Scored candidate rows: `27`
- IOT and RBRK close session: `2026-07-27`
- Held-position SEC and fundamental gates: passed
- New material SEC events: `0`
- Decision: `继续持有现有仓位｜今天不新增仓位`
- Human review required: no
- Weekday send recommended: yes

The ordinary production scheduler sent one email for the July 27 cycle. This
was not caused by upgrade verification. The delivery ledger contains a durable
pre-SMTP claim followed by `sent`. A prior `delivery_unknown` remains a blocking
status and was not retried, preserving the no-duplicate policy.

## Upgrade verification

- Canonical daily guard: PASS
- Daily scheduler status: PASS
- Full Phase 5R Python suite: PASS, `350/350`
- Safe-shadow controls: PASS
- Live shadow launch ready: no
- Model/provider invoked during verification: no
- Email attempted during verification: no
- SMTP configuration read during verification: no
- Broker/account/order/trade action: no

The model layer remains outside the daily critical path. Missing or stale model
artifacts cannot delay, change, or send the canonical daily decision.
