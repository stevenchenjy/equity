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

## Historical decision evidence — August 31 only

These figures describe the retired workflow at the date of that decision.
They are not the call count, spend, reliability, or value of the subsequently
authorized SHADOW_LLM stage. Use the runtime evaluation report and hash-chained
call ledger for current stage measurements; unavailable dollar billing is not
zero.

- Real production shadow observations: `0/10`.
- Metered model cost: `$0.000000`.
- Production API authorization: absent; no credential was requested, exposed,
  or probed.
- Deterministic production refresh: passed on the current completed market
  session with `29/29` valid market rows, complete held-position SEC coverage,
  deterministic valuation, portfolio review, and recommendation tracking.
- Production model budget and call allowance at that decision: `$0` and `false`.
- Observed marginal decision benefit from AI: none can be established without
  real observations. Promotion would therefore be unsupported.

## Future evaluation boundary

On `2026-09-02`, a new noncanonical `SHADOW_LLM` evaluation was explicitly
authorized under
[`phase5r_shadow_llm_evaluation_policy.md`](phase5r_shadow_llm_evaluation_policy.md).
This is a separate evaluation surface, not a restoration of the archived model
workflow or a dormant production switch. Production model status, budget, call
allowance, scheduler path, canonical authority, and delivery path remain
unchanged. Promotion is contingent on independently measured incremental
semantic value and a later, separate explicit authorization.

The evaluation is now event-driven: an analyst is scored by a different blind
judge, with a critic routed only for material or risky result types. Routine
semantic measurement requires no per-run owner labels. A dedicated evaluation-
only scheduler is permitted, but production scheduler integration remains
prohibited. The original commissioning failures and physical calls remain
preserved and counted.

## Boundaries

No broker or account connection, automatic action, order code, or trade
placement is permitted. The normal event-driven email remains deterministic;
No AI output exists in the active production workflow and no AI output can
make an email or portfolio review eligible. SHADOW_LLM artifacts are
noncanonical evaluation evidence only.
