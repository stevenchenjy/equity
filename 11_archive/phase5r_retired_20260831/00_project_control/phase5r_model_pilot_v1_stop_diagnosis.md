# Phase 5R pilot v1 stop diagnosis

Date: 2026-08-01 ET

## Finding

Pilot v1 stopped at `41103ccfe5365c841f39-terra-assessment` after three
completed model calls. The immutable journal records `failure_type` as
`ContractError`, `retry_allowed` as `false`, and a terminal `pilot_stopped`
event. The protected-state receipt remained unchanged.

The v1 quarantine contains exactly three response receipts. It contains no
receipt, response body, provider response ID, validation message, or redacted
diagnostic for the fourth call. The journal and its three receipts remain
unchanged by this investigation.

## What the evidence proves

- The provider returned a `ProviderResult` before the failure. A transport,
  response-status, missing-output, or JSON-parsing failure would have been
  classified as `ProviderError`, not `ContractError`.
- The failure occurred in the post-parse assessment-validation path:
  closed JSON Schema validation, analyst validation, or a subsequent
  assessment safety assertion.
- The static request schema is not categorically incompatible: Luna and Terra
  completed one prior assessment each with the same schema and validator path.

## What cannot be determined

No evidence identifies the exact failing field or validator rule. It would be
unsafe to infer whether it was a missing field, enum/const/type mismatch,
packet/as-of binding, citation binding, ticker coverage, or a safety check.
The fourth payload was intentionally discarded before a receipt was written;
`store=false` also precludes relying on remote retention. No provider lookup
was attempted for this diagnosis.

## Safe remediation

Do not relax the schema, citation requirements, numeric checks, action
boundaries, or terminal no-retry rule. The minimal correction is diagnostic
only: future pilot code records a finite, redacted validation code alongside a
post-parse `ContractError`. It stores no payload, exception text, provider
response ID, credential, source excerpt, or account information.

The new regression uses an offline fourth Terra assessment with a deliberately
mismatched `as_of_et`. It proves the terminal stop behavior, redacted
`analyst_as_of_et_mismatch` code, absence of a failed-response receipt, and
absence of the mismatched timestamp from the journal. It does not claim that
the unavailable v1 response had that particular mismatch.

## Status

`reject` for resuming or resetting pilot v1. The separate v2 replacement plan
is non-executing and requires explicit approval before any provider call.

## Local validation caveat

The pilot regression, provider, contract, and shadow-boundary test modules
pass. The full local Phase 5R suite currently has two unrelated baseline
failures, so v2 remains a draft: current evidence freshness is later than a
historical test receipt as-of, and the safe-shadow readiness test expects a
frozen-corpus blocker that the current static audit still reports. Neither
file is part of this remediation and neither was changed here.
