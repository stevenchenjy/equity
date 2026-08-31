# Phase 5R Model Pilot Go/No-Go Report

Date: 2026-07-28 ET

## Decision

**NO-GO for provider inference — strict corpus quality now passes, but external
OpenAI authentication is absent.**

The user authorized public SEC acquisition with a declared contact, at most
`5,000,000,000` local bytes, and an OpenAI-only pilot capped at `30` physical
model-inference calls and `$5.00`. The SEC contact was passed only at runtime
and was not
added to the model-pilot policy, corpus metadata, runner logs, or review
materials. The same address already appears in older, unrelated email-delivery
artifacts.

## What completed

- The deterministic selector used the existing 609-accession ledger.
- Ten real-source point-in-time packet files were built across six issuers.
- The builder produced four real chronological transition probes and five
  synthetic adversarial safety probes.
- No source was skipped.
- The corpus contains 203 files and `37,968,013` bytes.
- Manifest SHA-256:
  `8207bb520c560f9f9ac7e3ae857a6457e39c3d38e548ee285f1b084254471c67`.
- The original corpus verifier passed all ten packets with zero integrity
  issues.
- The strict completion and independent inventory checks now both pass
  `10/10`.
- Six issuer submissions snapshots, four Company Facts snapshots, four
  accession-level XBRL reconciliations, six exhibit-discovery manifests, and
  five exact `EX-*` files are hash-bound locally.
- A new atomic-write storage guard enforces the 5 GB limit against the
  transient replacement high-water mark, not only final directory size.
- The dedicated executable runner is
  `09_scripts/phase5r/run_phase5r_model_pilot.py`; its CLI is check-only and
  cannot construct a provider.
- The frozen plan is 10 Luna assessments, 10 Terra assessments, 5 blinded Sol
  committees, and 5 Sol critics: exactly 30 model calls.
- Every request is exact-counted before inference, uses SDK `max_retries=0`,
  `service_tier=default`, a 24,000-input/3,800-output ceiling, no tools,
  `store=false`, and one durable pre-call reservation.
- An isolated Python 3.11.15 runtime with OpenAI SDK 2.49.0 is installed under
  `~/Library/Application Support/Phase5R/model_pilot_venv`; its complete
  dependency lock is hash-bound into the plan, and runtime/SDK versions must
  match before inference.
- One global quarantine, an exclusive process lock, receipt/journal
  coherence checks, and no-retry unknown-outcome accounting prevent duplicate
  paid calls.
- The same complete-call receipt/journal/token/cost validator runs before the
  first completion event, before final artifact publication, and on every
  resume; a self-consistent journal-cost tamper is rejected before publication.
- The full worst-case reservation is `$4.9368`, including cache-write pricing
  and a 10% billing contingency; pinned pricing expires on 2026-08-04 and
  must be reverified after that date.
- Current read-only readiness: PASS; corpus storage is `37,968,013` of
  `5,000,000,000` bytes, both daily jobs are loaded, and the shadow scheduler
  is absent and unloaded.
- The isolated runtime occupies about `32,964,608` bytes; corpus plus runtime
  occupy about `70,932,621` bytes, still far below the 5 GB ceiling.
- Full Phase 5R Python suite: `369/369` passed.

## Resolved data-quality stop

The first run correctly stopped when the stricter inventory found `0/10`.
The completion pass has resolved every pilot-cohort gap:

- `10/10` locally complete strict packets;
- all six pilot issuers have verified raw submissions snapshots;
- all four XBRL-relevant pilot issuers have verified Company Facts snapshots;
- all four XBRL pilot filings have exact-accession reconciliation; and
- all six exhibit-scoped pilot filings have complete, SEC-index-bound
  discovery manifests.

The correction also handles the observed SEC convention where exact-accession
Company Facts for late filings use the following `filed` calendar date. It
allows only a one-day offset for the exact accession and still rejects later
revisions, conflicting dates, empty matches, or facts absent from the primary
filing.

## Exact provider and evaluation result

| Measure | Result |
| --- | ---: |
| Physical model-inference attempts | `0 / 30` |
| Non-inference token-count requests | `0 / 30` |
| Input tokens | `0` |
| Cached input tokens | `0` |
| Cache-write tokens | `0` |
| Output tokens | `0` |
| Actual model cost | `$0.00 / $5.00` |
| Citation accuracy | Not measured; no model claims |
| Unsupported claims | Not measured; no model claims |
| Model disagreements | Not measured; no model outputs |
| Critic unique value | Not measured; critic was not called |

OpenAI authentication is not present in the process. No credential was read
from files, Keychain, SMTP configuration, or another application, so the
authorized provider pilot remains correctly unstarted.

## Safety evidence

- Canonical model influence: false
- Email model influence: false
- Shadow scheduler installed or loaded: no
- Second provider enabled: no
- SMTP configuration read or changed: no
- Email attempted: no
- Broker connected or account read: no
- Order code or execution created: no
- Daily internal monitoring changed: no

## Required external gate

Configure OpenAI authentication outside the repository and restart the bounded
pilot by injecting an `OpenAIResponsesProvider` whose externally created SDK
client has `max_retries=0` and the global standard API base, and set the
provider billing-scope attestation to
`global_standard_no_regional_processing`. Do not paste a key into chat, source
files, logs, a LaunchAgent, or any SMTP configuration. The runner will produce
exact per-call usage/cost receipts, a randomly blinded claim-review bundle,
five critic-review rows, and a sealed key. Independent review remains required
before any further authorization.

The current 30-call/$5 authorization remains entirely unused. Licensed data, a
second provider, canonical/email influence, and shadow-scheduler installation
remain disabled.
