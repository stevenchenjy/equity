# REST collector timing evidence — September 28, 2026

This note records the evidence for replacing a late-morning scheduling
assumption with bounded requests for the actual expected prior session. It
does not change data entitlements, strategy thresholds, risk limits or trade
authority.

## Endpoint and primary sources

Production uses `market_data_adapter.MassiveBasicEODClient`:

`GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}`

Requests use `adjusted=false`, `sort=asc`, `limit=50000` and one year of history.
The adapter paces requests at least 13 seconds apart, sets a 10-second timeout,
does not retry or follow pagination, and validates normalized bars. The full
collector requires QQQ, XLK and SPY preflight followed by complete candidate
and held-symbol coverage before replacing canonical market outputs.

Primary documentation verified on September 28:

- [Custom Bars REST](https://massive.com/docs/rest/stocks/aggregates/custom-bars):
  Basic recency is end-of-day. The endpoint documentation does not specify an
  11:00 ET publication guarantee.
- [Day aggregate flat files](https://massive.com/docs/flat-files/stocks/day-aggregates):
  the documented 11:00 ET next-day update belongs to S3 daily files. Basic
  access to those files is not included.
- [Stocks plans](https://massive.com/stocks): Basic permits end-of-day data and
  five calls per minute; quotes, snapshots and WebSockets are not included.

The retired policy applied the flat-file timing to a different REST endpoint.
Its exact prior bytes and Git revision are preserved in
`11_archive/schedule_before_owner_windows_20260928/`. The prior grouped-endpoint
diagnostic remains historical evidence, but does not establish Custom Bars
availability in the morning.

## Bounded observation on the installed collector

The diagnostic used the installed production adapter and the existing external
launcher credential mechanism while holding the runtime and pipeline locks.
It made exactly two read-only requests, with the existing 13-second pacing.
No canonical artifact, decision, account, order or delivery history changed;
no provider payload, request header, request identifier or credential was
retained. No sender, model, broker or trading path was invoked.

| Response completed in Eastern time | Request | HTTP / provider status | Validated observation |
|---|---|---|---|
| 2026-09-28 20:35:32 | QQQ, 2025-09-29 through 2026-09-28 | 200 / DELAYED | 250 bars; latest 2026-09-25; exactly 2026-09-28 missing from expected 251-session sequence |
| 2026-09-28 20:35:45 | QQQ, 2025-09-26 through 2026-09-25 | 200 / OK | 251 bars; exact complete expected session sequence through 2026-09-25 |

The first request **fails freshness/completeness**, despite HTTP 200. The second
is a successful historical control using the same endpoint and credential.
Further benchmark requests were unnecessary once the current target failed.

This is one evening observation, not a timing SLA, morning verification,
full-universe production pass or investment-performance evidence. The
sanitized detailed observation and audit-only diagnostic are retained in the
owner's local schedule-upgrade audit folder, outside the public repository.

## Applied scheduling interpretation

The expected session is derived from the previous Eastern calendar day and
the existing U.S. market-session calendar. Availability is established only
by a complete accepted response. Morning slots are 08:00, 08:30, 09:00 and
09:45 ET; a passed morning refresh suppresses its remaining recovery attempts.
An independent 13:30 refresh with 14:00 recovery supports afternoon research
and plan reassessment. Morning availability will be measured by those real
runs; it is not already proved by this evening control.

No same-day-close evening email is enabled: the observed feed did not provide
that close. Missing expected bars stay blocked, unchanged older data are not
re-dated, and no live trigger is inferred. Email and analyst timing must fit
the owner's 09:45–10:45 and 14:45–15:20 attention windows without extending an
expired plan or DAY order. A fresh market batch does not clear missing broker
orders, fills, settled-funds or other independent evidence.
