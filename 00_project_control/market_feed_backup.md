# Validated full-universe market backup

Owner authority: October 19, 2026 request to implement and deploy a backup so
Massive publication delays do not consume an otherwise usable research session.
This changes data availability and provenance only. Capital, allocation,
valuation, risk, rotation quantities/prices/deadline, experimental status and
human-only execution remain unchanged. It authorizes no additional email.

## Admission and source basis

Massive Custom Bars with `adjusted=false` remains primary. Each complete primary
batch now retains its entire validated one-year OHLCV history, not merely the
20-bar tactical sidecar. An unavailable/invalid primary batch may use the
credential-free Nasdaq public historical endpoint for **new sessions only**.
This is the only newly adopted backup; other sources remain research comparisons.

Nasdaq historical series are not assumed to have Massive's adjustment basis.
The backup preserves every retained unadjusted historical bar. It requests the
last two retained sessions through the required completed session, requires
every expected date once in descending provider order, then compares both
overlapping closes. A difference greater than $0.005 rejects the batch. This
is half a displayed cent of quote precision, not an investment risk tolerance.
It detects an incompatible adjusted history or an unresolved price conflict;
it does not silently average conflicting prices or treat volume as identical
across feeds. Earlier OHLCV is never replaced by Nasdaq's historical values.
Only the new observed bars extend the retained series, which must then pass
the existing exact one-year session, numerical, OHLCV and coverage checks.

Every configured candidate and every current held-only ticker must pass. A
single missing, malformed, duplicate, stale or conflicting symbol rejects the
entire backup. No partial universe, alternative signal threshold, old date
relabelling or fabricated volume/range is admitted. The source label is
`massive_unadjusted_history_nasdaq_eod_extension`, which explicitly identifies
the composite provenance. Its published price remains EOD context, not a live
execution quote or a separately reconciled official closing-auction price.

## Retention, publication and recovery

`03_source_data/equity_research/market_feed.local/` retains content-addressed
full histories and original Nasdaq JSON responses. The original Massive
baseline is a labelled normalized provider observation, not claimed raw HTTP
bytes. `current.json` binds the selected immutable history and canonical CSV
hash. It and the feed policy participate in final publication fingerprints.
Backup reuse and market-gate composition revalidate source bindings. The
dashboard reads the same publication and displays the backup source separately
from dated action cards. Email provenance belongs in supporting information.

Publication stages snapshot, quality, candidate, history-sidecar and history
pointer bytes under the existing locks. Prior bytes and a prepared receipt
survive failure. A caught error rolls back only this batch's known bytes. The
next collector recovers a crashed prepared transaction only when every file
still matches its recorded before/after hash; an unexpected newer value stops
recovery instead of being overwritten. Failed response attempts remain retained.

An installation without a complete retained baseline cannot invent one from
Nasdaq's possibly adjusted historical series. Initial deployment must validate
a full Massive unadjusted baseline against the retained canonical snapshot
before activating the pointer. Normal successful Massive runs maintain it.
New held-only symbols require the same historical admission; a missing symbol
remains an exact dependency rather than expanding the candidate universe.

## Freshness and bounded operation

The required session is now the latest completed exchange session at the
existing 16:15 ET boundary, including overnight before 08:00. The old helper
name/publication argument remain compatibility identifiers; they no longer
grant a vendor-specific day of lag. Frozen experiment helpers remain archived.

The existing morning/afternoon collector slots, recovery opportunities and
email windows remain. Each slot attempts primary once, then at most one
complete backup batch. Nasdaq requests are sequential, at least one second
apart, eight-second timeouts, no redirect, retry, paging, authentication or
subscription. Existing process timeouts remain finite. Missing primary
credentials may reach the anonymous backup rather than stopping the launcher;
missing baseline or unavailable backup still fails closed. Independent broad
market discovery remains its separate Massive-based advisory worker.

The deployed collector has no email sender or broker path. A full refresh and
normal sender handoff are still required; backup availability does not establish
an attractive company or rotation. Retained experimental outcome coverage is
not replaced by the backup and remains separately reported.
