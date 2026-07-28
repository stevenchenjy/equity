# Phase 5R Model Pilot Go/No-Go Report

Date: 2026-07-27 ET

## Decision

**NO-GO for provider inference — strict corpus quality now passes, but external
OpenAI authentication is absent.**

The user authorized public SEC acquisition with a declared contact, at most
`5,000,000,000` local bytes, and an OpenAI-only pilot capped at `30` physical
calls and `$5.00`. The SEC contact was passed only at runtime and was not
committed or copied into reports.

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
- Full Phase 5R Python suite: `360/360` passed.

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
| Physical provider attempts | `0 / 30` |
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
pilot. Do not paste a key into chat, source files, logs, a LaunchAgent, or any
SMTP configuration. After quarantined outputs exist, independent reviewers can
complete the claim-hash-bound citation/transition review.

The current 30-call/$5 authorization remains entirely unused. Licensed data, a
second provider, canonical/email influence, and shadow-scheduler installation
remain disabled.
