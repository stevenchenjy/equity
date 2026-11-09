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
The pending notice retains the independently validated owner local-ledger authority. Email validates the same account fingerprint; final validation and its
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


## Manual account-record CLI

Use `09_scripts/equity_research/record_feedback.py` to preview and apply verified owner-reported account events. Preview and confirmation validate the account version, plan reference, preview hash and request identity. An uncertain save retains its original request ID for recovery.

## Historical plan sources after account changes

Managed account writers preserve changed predecessor bytes, but preservation
alone does not register a historical plan's source resolution. After an account
update, verify the complete plan ledger against its sources before treating a
recomposed decision as current. An older plan may have bound one of the mutable
current account, position or order paths. A legitimate update can therefore
produce `plan_source_hash_mismatch` even though its exact predecessor was saved.

For each affected record, use the explicit
[historical source recovery procedure](position_purpose_reassessment.md#exact-historical-source-recovery)
to register the exact retained bytes and original plan/source identity, then
recompose. Keep the accepted current account facts and original plan history;
do not restore older account values or infer a fill, renewed deadline or new
trade authority. Once registered, that historical source remains resolved
through later account updates. Missing or mismatched retained bytes remain a
blocker requiring investigation. New plan proposals must bind their own direct
retained sources, rather than relying on an earlier record's resolution.

## Saved pending records and historical reconciliation

A saved pending receipt is a completed intake, not a running request and not an
applied financial transition. Research completion does not change that financial
status. Reviewing a pending record
uses its latest acknowledged record identity and revision. A deliberately changed
revision uses a new request UUID; recovery of an uncertain unchanged save keeps
the original UUID and payload.

Ordinary browser and CLI submissions retain the backdated-fill guard. When the
owner explicitly identifies an omitted historical fill and a correction to a
previously applied fill date, the operator-only historical-reconciliation path
can preview and apply that exact source-bound batch through the same durable
prepare/recover journal. It is not an HTTP bypass or a new account observation.
It requires active owner-local-ledger authority, exact account/input versions,
the pending record and revision, the referenced applied execution, and retained
owner instruction bytes. A stale input or changed reference rejects the batch.

The batch retains original request/event bytes and before/after projections,
records the corrected effective date separately, and applies the omitted fill's
current-ledger delta exactly once. Reconciliation cash balances are explicitly
current ledger values, not reconstructed balances on the historical fill date.
It does not assert broker inventory, settled funds or order-list completeness,
write a synthetic full-account observation, change investment gates, or send mail.
