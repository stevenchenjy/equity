# Phase 5R Model Decision Authority Policy

## Status

The model layer is an evidence-grounded research classifier. It is not a trader,
sender, account controller, or source of truth. The deterministic Phase 5R
pipeline remains canonical while the registry is in `offline_fixture` or
`shadow` mode.

The active research objective is a rolling five-year annualized net total
return of 12%–15%; 15%–20% is an excellent-year range, not an annual or monthly
quota. This objective is not a guarantee and cannot relax any authority,
evidence, concentration, or manual-execution boundary. See
`00_project_control/phase5r_return_objective_policy.md`.

## Closed authority

- Permitted research classifications: `reject`, `watchlist`,
  `hold_existing`, `paper_trade_candidate`, `real_trade_candidate`,
  `trim_review`, `exit_review`, and `abstain`.
- `hold_existing`, `watchlist`, and `abstain` need no routine human review
  after the deterministic validator passes.
- Any action-changing research classification needs packet-local primary
  evidence matched to the same ticker, reconciled arithmetic,
  analyst/committee/critic agreement, resolved contradictions, sufficient
  official coverage, and every deterministic C9 gate.
- A model or critic can downgrade a classification. It cannot override a failed
  data, provenance, account-state, concentration, stability, or policy gate.
- A `real_trade_candidate` label is research only. Every real trade remains a
  separate human action outside this repository.

## Absolute prohibitions

- No live trading, broker connection, account API, order code, order sizing, or
  automatic execution.
- No email or SMTP access from the model layer.
- No API key, password, identity, email address, or exact account-dollar value
  in a model request, artifact, log, or configuration.
- No model tools, browsing, shell, filesystem mutation, source discovery, or
  free-form citations.
- No imperative buy or sell command.

## Evidence and provenance

Every material claim must cite an immutable `source_id` included in the frozen
packet. A source record carries its official URL or accession, accepted or
observed time, byte/content SHA-256, parser identity, and a deterministic
section, span, or market-session locator. SEC raw artifacts remain canonical;
parsed text and model prose are derivatives.

Numbers are recomputed in Python with explicit unit and period checks. Unknown
sources, future facts, incompatible periods or units, missing spans, hash
mismatches, unsupported claims, prompt-injection text, or parser disagreement
force `abstain`.

Any numeric model text must cite a packet calculation ID. Any
medium/high-materiality claim, prominent supporting fact, disconfirming fact,
or long-term action transition must cite a same-ticker primary source. A
model-declared thesis break can bypass per-ticker action-grade market and
valuation gates only for an `exit_review` supported by high-materiality,
medium/long-term, same-ticker primary evidence and an approving critic. Every
other deterministic gate remains mandatory.

## Operational isolation

The model runner is a separate shadow process and is never placed in the
email-critical refresh/send call chain. Its receipt-backed result publication
is idempotent, while the external provider is not claimed to offer exactly-once
inference. An ambiguous in-flight outcome therefore terminates the exact run
instead of authorizing a recall. The runner snapshots inputs briefly, releases
the pipeline lock, performs inference outside the lock, and writes only model
shadow/audit artifacts. A timeout, missing provider, malformed response, or
failed validation cannot change the canonical decision, brief, scheduler,
delivery ledger, positions, account state, or pipeline exit status.

The repository never reads provider credentials. Any future live inference must
use an explicitly approved external managed bridge whose authentication remains
outside the repository, or a separately approved narrow policy amendment.

## Promotion gate

Canonical advisory influence remains disabled until all of the following are
machine-verifiably true:

1. At least 250 point-in-time replay packets across at least 20 issuers pass
   the evaluation manifest.
2. At least 50 material-transition cases are covered.
3. Thirty to sixty live market sessions complete in shadow mode.
4. Policy-boundary violations equal zero.
5. Unsupported-claim, citation, arithmetic, point-in-time, abstention,
   counterfactual, stability, and critic-catch thresholds all pass.
6. A hash-bound activation receipt ties the exact corpus, annotations, rubric,
   provider artifacts, model/prompt/schema registry, and target shadow registry
   together.
7. Promotion is recorded as a separate explicit state transition.

Promotion may allow validated model research language into a brief. It can never
enable an automatic trade, broker access, order code, or SMTP access.
