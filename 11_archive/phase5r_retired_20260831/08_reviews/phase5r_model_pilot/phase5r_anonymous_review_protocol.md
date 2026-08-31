# Phase 5R Anonymous Model-Pilot Review Protocol

Status: ready for use after the bounded provider pilot completes.

## Separation

Distribute only
`phase5r_model_pilot_anonymous_review.json`. Do not distribute the sealed blind
key, runtime A/B assignment file, plan, journal, or provider receipts until
both independent submissions have been completed and hash-frozen.

Each reviewer works from a separate copy and records a pseudonym, completion
time, independence attestation, and blind-key non-access attestation. Never
edit the immutable generated original.

## Required review

For every claim:

1. classify semantic support as `supports`, `partial`, `does_not_support`, or
   `not_assessable`;
2. mark whether the claim is unsupported;
3. validate period and unit; and
4. score every cited source separately as `accurate`, `partial`,
   `inaccurate`, or `uncertain`.

For every critic row, record valid catches, false positives, missed material
issues, whether a downgrade helped, and whether the critic added incremental
value.

## Adjudication gate

Do not deblind until both submissions are immutable. Reviewer disagreements
must be adjudicated without changing either original submission. Human
citation accuracy, unsupported-claim rate, and critic incremental value remain
`unmeasured` until both submissions and an adjudication receipt exist.

No review result can promote model output into canonical C9 decisions, email,
alerts, broker/account systems, orders, or execution.
