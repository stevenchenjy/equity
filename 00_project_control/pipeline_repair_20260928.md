# Pipeline audit and repair — September 28, 2026

This change addresses observed data-flow and follow-through failures. It does
not change allocation targets, risk percentages, broker facts, trading authority
or the criteria for admitting company evidence. The owner explicitly requested
repair after the audit and allowed more research processing when it produces
useful output.

## Repaired contracts

- Source polling: an unchanged issuer announcement's `last_seen_at` no longer
  consumes the objective worker's budget again. Changed content, publication
  times, first observation, actual source bytes and freshness still matter.
- Schedule reporting: successful publication refreshes do not promise a later
  recovery-only retry. Reports distinguish routine windows, conditional retries
  and the time at which the schedule was observed.
- Capital accounting: the final projection follows the proposals that survived
  all final gates. The earlier baseline projection remains separate evidence;
  rejected candidates cannot remain embedded in projected cash or exposures.
- Order evidence: a verified current inventory and an unresolved historical
  sell reservation are different facts. Historical sells remain restricted to
  their named shares; an unknown inventory, uncertain buy commitments or
  contradictory observations still block globally. Structured observations
  survive into the decision and dated email presentation.
- Delivery evidence: exact validated decision/text/HTML bytes are archived
  privately before a send claim or SMTP. Conflicting or failed archives stop
  the send. The archive contains no SMTP configuration. Existing delivery
  deduplication and permission rules remain in force.
- SHADOW diagnostics: invalid archived evidence remains intact and identified.
  Valid runs can be reported separately, but incomplete history prevents
  readiness or promotion claims. Current status exposes this advisory failure
  independently of the canonical strategy.

Each repaired failure has a regression and relevant adverse counterexamples.
Release acceptance additionally requires a clean deployed commit, complete
no-send recomposition and inspection of current private facts and final output.
Passing software checks does not establish investment performance.

## Preserve the forward experiment across a software repair

The tactical order repair changes a frozen implementation dependency. New
observations therefore use `eod-breakout-v3-20260928`. Only the version changes;
thresholds, holding sessions, costs, selection hypotheses and authority remain
unchanged. Existing observations and recorded selections are never rewritten.

`momentum_implementation_archives.json` registers exact Git commits and source
hashes for older implementations. Their pending outcomes use their original
validators and execution model in an isolated temporary process. Missing or
unavailable data stays pending. The full proposed outcome append is validated
before durable history changes. Versions remain separate in every comparison.

A completed retained cohort can open its own historical manual review; it does
not complete or promote the active version. This preserves the owner's first
complete five-session review preference without relabelling old evidence as a
new implementation's result.

## Close the analytical follow-through gap

The deterministic worker gathers facts; it does not author company judgments.
The scheduled chat follow-up described in `analyst_followthrough.md` performs
that missing work and uses the existing validators to record supported inputs.
Its first rehearsal includes a source-bound same-purpose core-plan reassessment
and a debt-scope analysis. A sourced debt observation is not a completed
valuation, and a maintained plan is not a submitted broker order.

Private audit artifacts retain the actual source/runtime hashes, failed-before
tests, independent reviews, deployment receipts, raw-before snapshots and
no-send run results. Production is verified from those artifacts, not from this
document or a chat summary.
