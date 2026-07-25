# Phase 5R Model Decision Authority Policy

## Status

The model layer is an evidence-grounded research classifier. It is not a trader,
sender, account controller, or source of truth. The deterministic Phase 5R
pipeline remains canonical while the registry is in `offline_fixture` or
`shadow` mode.

## Closed authority

- Permitted research classifications: `reject`, `watchlist`,
  `hold_existing`, `paper_trade_candidate`, `real_trade_candidate`,
  `trim_review`, `exit_review`, and `abstain`.
- `hold_existing`, `watchlist`, and `abstain` need no routine human review
  after the deterministic validator passes.
- Any action-changing research classification needs packet-local primary
  evidence, reconciled arithmetic, committee/critic agreement, and every
  deterministic C9 gate.
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

## Operational isolation

The model runner is a separate idempotent shadow process and is never placed in
the email-critical refresh/send call chain. It snapshots inputs briefly, releases
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

1. At least 200 point-in-time replay packets pass the evaluation manifest.
2. At least 50 material-transition cases are covered.
3. Thirty to sixty live market sessions complete in shadow mode.
4. Policy-boundary violations equal zero.
5. Unsupported-claim, citation, arithmetic, point-in-time, abstention,
   counterfactual, stability, and critic-catch thresholds all pass.
6. Promotion is recorded as a separate explicit state transition.

Promotion may allow validated model research language into a brief. It can never
enable an automatic trade, broker access, order code, or SMTP access.
