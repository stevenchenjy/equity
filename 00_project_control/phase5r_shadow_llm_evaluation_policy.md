# Phase 5R SHADOW_LLM Evaluation Policy

Effective: `2026-09-02`

Measurement correction: `2026-09-04`. Historical commissioning, packets,
bundles, model verdicts and physical-call ledger remain unchanged. Corrected
derived reports are versioned separately; better software does not retroactively
give old runs calibration credit.

Status: evaluation authorized; production influence prohibited; any future
authority change requires measured incremental value and a separate explicit
decision.

## Question being measured

Does SHADOW_LLM consistently add unique, material research information beyond
the deterministic Phase 5R baseline, and is that value worth its measured call,
token, latency, and maintenance cost?

SHADOW_LLM is not an investment committee, a production decision engine, or a
trader. A valid evaluation result has no canonical or production effect.

## Isolation and deterministic authority

- Input is a sanitized, sealed `phase5r_llm_evidence_packet_v1`. Account dollars
  are excluded. Packet text is untrusted evidence, never instructions.
- Output exists only below the Git-ignored `08_reviews/phase5r_shadow_llm/`
  trees with owner-only permissions.
- Deterministic facts, valuation arithmetic, portfolio math, cash, position
  sizing, thresholds, action stability, and notification eligibility remain
  authoritative and cannot be changed by SHADOW_LLM.
- The model cannot browse, use tools, discover sources, read the repository,
  fill missing evidence, connect to a broker, read a broker account, create
  order code, place a trade, send an email, or trigger a production action.
- Provider, schema, citation, contract, critic, or judge failure terminates that
  exact run. There is no automatic retry or repair into a passing artifact.
- No production scheduler or production entrypoint may import or invoke the
  shadow surface. A separate evaluation-only scheduler is permitted, but the
  runner must still pass the event and allowance gates before any model call.
  The approved evaluation-only label is `com.steven.phase5r.shadoweval`; it
  watches only the noncanonical evidence-packet input and is not a production
  readiness or delivery dependency. The retired production-shadow label
  `com.steven.phase5r.llmshadow` remains prohibited.

## Small evaluation architecture

1. The `analyst` extracts bounded same-ticker, primary-source-cited claims and
   non-action thesis states.
2. Deterministic validators enforce packet/source/calculation binding, schema,
   ticker coverage, evidence sufficiency, and prohibited-action language.
3. The `critic` is conditional, not universal. It runs for non-mechanical
   high-materiality claims, new contradictions, or a weakened/mixed thesis
   state. Mechanically captured fact restatements alone do not justify an
   expensive critic. It may qualify/reject claims and add source-bound omissions.
4. A different configured model is the independent `judge` on every counted
   event. The judge sees deterministically ordered blind candidates, not their
   analyst/critic origin, the analyst's materiality or novelty label, or a critic
   verdict. It measures support, materiality, and whether the deterministic
   baseline already captured the issue, and may identify source-bound missed
   material issues.
5. The baseline includes the existing evidence, calculations, numerical signs,
   and structured research checklist, not just the short prose summary. Plain
   numerical restatements are baseline/explanatory value, not unique discovery.
   Two bounded hidden sign controls can share the judge call; they measure
   mechanically known errors and are excluded from incremental value.
6. The deterministic evaluator compares judge results with model labels and the
   baseline. Partial-versus-supported differences, including period qualifiers,
   are contested and excluded. Evidence-family identity removes repeated source
   claims across runs; updated evidence is reported separately from first value.
   This conservative grouping is a lower-bound proxy: it can merge distinct
   issues sharing one passage and is not a perfect semantic ontology.

The judge reduces self-grading but does not eliminate correlated model error.
Protection comes from model separation, blindness, deterministic binding,
disagreement exclusion, immutable point-in-time inputs, later official evidence
and outcome context, and optional reproducibly selected human spot checks.
Human spot checks use a fixed SHA-256 rule for ten percent of runs; they are not
required for routine measurement or stage continuation.

## Event-driven selection and replay

The runner hashes research-semantic inputs: entity/thesis membership, accepted
primary-source identities and content, filing and fundamental evidence, and the
stable deterministic research baseline. Daily price, account, and timestamp
churn is excluded from the separate v2 economic digest, including timestamps
embedded in primary-source row hashes. Raw provenance hashes remain intact.
`--auto-live` spends no call when that semantic event was already attempted;
historical sealed packets are reindexed in memory, not rewritten. Live and
replay cannot count the same economic event as two independent cases.

Every selected current-schema packet is privately archived. `--auto-replay`
chooses an unattempted economic event by a fixed salted SHA-256 ordering, with
the earliest sealed capture representing duplicate captures. Availability
timestamps must be aware and not later than the sealed packet clock. Manual case
picking is not required. Historical replay packets with a different schema are
not silently admitted; they need a deterministic migration before eligibility.
Fixtures test plumbing and count toward no evaluation metric.

Point-in-time recommendation snapshots and outcome records are linked as
secondary delayed context. Later official same-period, source-bound numerical
predicates may mechanically resolve claims; other narratives remain unresolved.
Short-horizon returns are not semantic ground truth and cannot validate an
unsupported claim. Missing later evidence is pending, not a positive score.

## Calls and cost

The original nine physical calls remain in the immutable hash-chained ledger.
They are commissioning history and are never erased or relabeled. The current
bounded stage adds 24 physical calls, for a lifetime ceiling of 33 and a ceiling
of three calls per logical run. The stage itself admits no more than six new
live events and two replay events. This covers all eight admitted events even
if every one routes through analyst+critic+judge; conditional critic use leaves
unused call capacity rather than authorizing extra events.

The provider records exact CLI-reported input, cached-input, output, reasoning,
and total token counters plus latency for each completed new-stage call. The
ChatGPT-managed Codex transport exposes no authoritative dollar charge, so
dollar cost remains `unavailable` and is never estimated or recorded as zero.
Physical calls and tokens are still exact observable cost measures.
Per-run bundles and the call ledger are immutable evidence. The aggregate
evaluation JSON and Markdown are derived current snapshots and may be replaced
atomically with private immutable measurement revisions retained.

Additional stop guards: 300,000 UTF-8 bytes per input envelope, 300,000
reported tokens per run, and 1,800,000 reported tokens in this same bounded
stage. A new event reserves a full run's token capacity and three physical-call
slots before invocation. Missing authoritative usage on any started stage call
blocks new inference. These are input/observed-usage guards, NOT a guaranteed
provider hard token limit or dollar ceiling: the transport can overshoot a token
threshold on one call before subsequent calls are stopped. No automatic retry.
The initial guards are based on the existing three events' 728,249 reported
tokens (approximately 242,750 per event), not assumed free billing. They do not
increase the original physical-call or event allowance.

## Evidence stages

Threshold values are machine-readable in
`phase5r_shadow_llm_config.json`.

Early continuation/usefulness uses explicitly named **model-reference estimates**
after deduplication, not an independently known issue universe. Common omissions
remain unobservable. Zero deterministic-control failures and complete sealed
baseline reassessment are required; usefulness also requires actual control
observations. Passing software tests does not satisfy those evidence checks.

- `continue evaluation`: at least 6 automatically judged events, 3 issuers, 6
  material reference issues, 2 incremental supported material items, at least
  0.60 precision and recall, at least 0.75 completion, no more than 0.20
  unsupported rate, and zero boundary violations.
- `useful`: at least 20 events, 8 issuers, 20 material reference issues, 5
  incremental supported material items, at least 0.75 precision, 0.80 recall,
  and 0.85 completion, no more than 0.10 unsupported rate, and zero boundary
  violations. Reaching this stage justifies continued shadow use, not authority.
- `future authority review`: retain the existing high bar of 250 replay packets,
  20 issuers, 50 material reference issues, 30–60 live semantic events, at least
  0.85 precision, 0.90 recall, 0.80 critic catch rate, no more than 0.10 critic
  false-veto rate and 0.05 unsupported rate, and zero boundary violations.

The high final threshold is for considering production influence, not for
deciding whether a small bounded evaluation is worth continuing. Passing it is
never automatic promotion. Broker access, order generation, execution, and
model override of deterministic gates remain prohibited in every future mode.
For final authority review, recall must use an independently established
reference denominator, not the judge's own missing-issue list. That corpus is
not currently established; independent recall is null, and final authority
review remains ineligible regardless of a high model-reference score.

## Stop conditions

Stop the bounded stage when its allowance is exhausted and continuation
evidence is not met, any boundary violation occurs, exact call accounting loses
integrity, the completion-rate floor fails after the bounded sample, or
incremental supported material value remains below the configured minimum.
Routine owner labeling is not a stop condition because it is not required.
