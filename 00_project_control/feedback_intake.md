# Trade recording during research refresh

Trade preview, confirmation, duplicate detection and recovery use the short
`account_records.lock`. They do not acquire the runtime or daily research lock.
An accepted fill updates canonical cash, holdings, known orders and the existing
execution journal immediately. The original request ID remains the idempotency
key; a changed payload under that ID is rejected. A stale account version needs
a fresh preview. Multi-file transitions retain their prepared-write recovery and
external-change checks. Research failure never rolls back accepted facts.

The public research worker keeps the runtime and daily locks, but releases both
the account lock and its SQLite transaction before starting subprocess/network
work. It rereads durable records at completion, preserving later entries and
revisions. A successful current publication covers entries admitted during the
run too; superseded work is queued again, never reported as a failed trade save.

Research starts with a fingerprint of account, positions, orders, execution and
reconciliation records, pending-write barrier and manual observation receipt.
The composer checks that exact context before computation and under the short
publication lock before replacing decision, report, text/HTML and state. A new
fill cannot be disguised by attaching fresh hashes to older calculations. The
full refresh can retry account-dependent stages twice using current inputs;
public collection and objective-research quota are not restarted. Continuous
changes beyond that bound leave research pending for the durable worker.
The last stable account context is retained in
`00_project_control/run_logs/account_research_version.local.json`; a standalone
composer cannot adopt a changed account without recomposition.

The account transition also replaces the unsent text/HTML brief with a current
account-only pending notice, retaining the old bytes in the durable journal.
A composer cannot overwrite an applying/recovery-conflict transition.
The dashboard serves current committed cash and holdings throughout a refresh.
It withholds superseded research quantities and drafts until recomposition is
current. The temporary account-only view retains the independently validated
owner local-ledger authority; research refresh does not request a new broker
observation or claim one occurred. Email validates the same account fingerprint; final validation and its
durable send claim use the short shared account lock. The lock is released
before SMTP. A claim fixes the immutable as-of snapshot; a fill recorded after
that claim belongs to the next publication. Historical sent artifacts remain
unchanged. No additional email, broker connection or trade is authorized.

The existing 90-second quiet interval, bounded at three minutes from the oldest
queued entry, now batches research only. It never delays trade intake. Explicit
`record_feedback.py --apply --refresh` still attempts research immediately.
Legacy account writers and allocation migrations share the account lock; their
transaction and recovery checks remain effective. Deployment retains the
runtime/daily locks, and service replacement must preserve the durable journal.
