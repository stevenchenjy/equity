# Consecutive account-record intake

An accepted fill updates the canonical local account and execution journal
immediately under the existing runtime and pipeline locks. Its receipt remains
distinct from research completion. No broker or email action is performed.

The dashboard waits for a 90-second quiet interval after queued feedback before
starting its automatic full public-research refresh. Further entries within that
interval are saved normally and join the same research batch. The oldest queued
entry limits this coalescing interval to three minutes, so continued input cannot
defer research indefinitely. Queue times are durable across server restarts;
interrupted runs and prepared-write recovery bypass this delay.
The one-shot `record_feedback.py --apply --refresh` command also bypasses
the quiet interval and completes its explicit research attempt before exiting.

This is an intake scheduling change, not an investment threshold or a waiver of
coherent publication. A research job already running, including a scheduled
refresh, still holds the existing locks. A new form waits safely in that case,
shows elapsed waiting time, preserves its input and original request identity,
and continues automatically after release. Unknown network results retain the
same request for recovery; account or preview conflicts require a fresh preview.
Never retry by inventing another request ID or assume a reported trade was
executed by the system.

The worker rechecks intake after acquiring its locks, batches pending records,
and verifies the resulting decision and exact text/HTML against the current
account. Accepted account facts survive a failed research refresh.
