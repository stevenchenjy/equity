# Phase 5R AI operating decision

Decision date: `2026-08-31`

## Decision

**Remove AI from the active production path and archive its implementation.**
The active scheduler, launcher, status generator, and delivery path contain no
model-provider route or model credential lookup. Historical pilots, replay
corpora, provider code, shadow runners, and reports are retained only beneath
`11_archive/phase5r_retired_20260831/` and in the immutable Git tag
`phase5r-pre-cleanup-20260831`.

This is the required evidence-backed remove decision in lieu of ten real
shadow observations. The deterministic research system is the sole production
authority.

## Evidence

- Real production shadow observations: `0/10`.
- Metered model cost: `$0.000000`.
- Production API authorization: absent; no credential was requested, exposed,
  or probed.
- Deterministic production refresh: passed on the current completed market
  session with `29/29` valid market rows, complete held-position SEC coverage,
  deterministic valuation, portfolio review, and recommendation tracking.
- Active model budget and call allowance: `$0` and `false`.
- Observed marginal decision benefit from AI: none can be established without
  real observations. Promotion would therefore be unsupported.

## Future evaluation boundary

A future model evaluation is a new project decision, not a dormant production
switch. It requires a separately reviewed restore from the archive or recovery
tag, new cost and security limits, focused tests, and explicit authorization
before any provider code may return to the active script tree.

## Boundaries

No broker or account connection, automatic action, order code, or trade
placement is permitted. The normal event-driven email remains deterministic;
No AI output exists in the active workflow and no AI output can make an email
or portfolio review eligible.
