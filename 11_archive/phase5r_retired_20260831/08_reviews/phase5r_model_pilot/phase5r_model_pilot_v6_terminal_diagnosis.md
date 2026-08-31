# Phase 5R v6 terminal diagnosis (offline)

Status: terminal and preserved. This document is a separate diagnosis; it does
not alter v6's authorization receipt, execution plan, journal, receipts, or
cost records.

## Evidence bound

- Authorization file SHA-256: `5437307823aa66e0d8dda086793dd9b46bbcd1bc4dbe96210e0f7670b3fd88a8`
- Execution-plan file SHA-256: `4a2f6d01e009a0985adcce1dcdad8f62a8047a95d9374b828220419188c85a35`
- Execution-plan self-hash: `9dc50ecd15d8ff87dd7dfd143d6f30b8ebaaeac5050ed263f7ba77d6f7e5e87d`
- Journal SHA-256: `c6383703dacd3d64bbfd024a981c630dfb6d3a255103d9578d6b049e25ee394a`
- The journal chain validates. It records 11 reservations, 10 completed
  receipts, one `call_failed`, then one terminal `pilot_stopped` event.

The failed call is the eleventh reserved call, a `luna_assessment`. It passed
the provider input-token preflight and the pre-inference budget gate before its
reservation was written. Its failure event is `call_failed`, not
`call_outcome_unknown`, and has `failure_type: PilotStop`.

In the v6 executor, `call_failed` is written only after `provider.generate()`
has returned a `ProviderResult`. The production provider returns that object
only after a completed Responses result has an in-memory ID, its output text
has been parsed as one JSON object, and its usage receipt has been normalized.
Therefore the retained evidence rules out a failure before provider execution,
transport failure, and Structured-Output/JSON parsing failure.

The error occurred in local post-parse processing. `PilotStop` is used both by
the local contract/semantic validators and by post-parse metering, usage
reconciliation, metadata-redaction, and receipt-persistence safeguards. v6
intentionally retained neither the failed payload, provider response ID, nor
error text, and its old journal did not retain a phase code. Consequently the
evidence does **not** establish a particular schema field, validator mismatch,
or post-parse branch. It would be unsound to call this a specific contract
failure.

## Budget accounting

The 10 completed calls cost `$0.1178890`; the terminal reservation was
`$0.0580800`. Charged total: `$0.1759690` across 11 calls. From v6's approved
30-call, `$5.00` cap, the unspent ceiling is 19 calls and `$4.8240310`.

## Privacy-safe future diagnostic

The v6 descendant executor now records a finite `failure_phase` code only.
It separates a provider method that did not return from these post-parse local
steps: result type check, contract validation, metering validation, usage
reconciliation, provider-metadata redaction, and receipt persistence. It does
not retain response text, provider response IDs (or hashes), exception
messages, or credentials. A fixture regression test returns parsed,
schema-shaped data that fails the local confidence bound and verifies that only
`post_parse_contract_validation` is journaled.

The terminal v6 journal itself remains unchanged and cannot gain that new
field retroactively.
