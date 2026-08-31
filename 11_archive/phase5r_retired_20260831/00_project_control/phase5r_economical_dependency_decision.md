# Phase 5R Economical Dependency Decision

Effective: 2026-07-28 ET

## Decision

Use one canonical daily workflow and keep the model layer outside its critical
path. The cheapest credible architecture is not an LLM call on every refresh.
It is:

1. deterministic local B2/SEC/C9 gates at zero model cost;
2. no model request when evidence is insufficient or the semantic state did
   not materially change;
3. one OpenAI provider family for the initial qualification and shadow;
4. synchronous stateless Responses requests for the bounded pilot so each
   reservation and outcome can be reconciled immediately;
5. Terra as the initial evidence-analyst quality baseline;
6. Luna tested against Terra only as a lower-cost analyst candidate;
7. Sol used only when a classification may change or a high-impact proposal
   needs criticism; and
8. no paid cross-provider challenger or licensed market-data subscription
   until a measured gate justifies it.

The machine-readable authority is
`00_project_control/phase5r_paid_dependency_policy.json`. The user has
authorized only the bounded first pilot: at most 30 physical model calls and
$5 total, using one provider family after the strict corpus and external-auth
gates pass. The SEC acquisition and 5 GB local-storage ceiling are also
authorized. Qualification, live shadow, model influence, email influence,
licensed data, and any second provider remain disabled. The 2026-07-27 run
repaired the strict corpus to `10/10` but still stopped before inference
because external authentication is absent; actual provider calls, tokens, and
cost remain zero.

## Why Luna is a benchmark, not the automatic default

Luna is the least expensive GPT-5.6 tier, but local Python already performs the
cheap triage, arithmetic, freshness, and no-change work. Paying Luna to repeat
that work adds little. The remaining job is difficult financial-evidence
interpretation, so Terra is the quality baseline and Luna must demonstrate
non-inferiority on the frozen corpus before replacing it.

This is cheaper than routing every packet to Luna because unchanged and
insufficient-evidence cycles use zero calls. It also avoids assuming that a
lower per-token price produces a lower cost per correct decision.

## Current official price basis

Standard text prices per one million tokens:

| Model | Input | Cached input | Output | Intended Phase 5R use |
| --- | ---: | ---: | ---: | --- |
| GPT-5.6 Luna | $1.00 | $0.10 | $6.00 | bounded analyst challenger only |
| GPT-5.6 Terra | $2.50 | $0.25 | $15.00 | evidence-analyst baseline |
| GPT-5.6 Sol | $5.00 | $0.50 | $30.00 | sparse committee/critic |

OpenAI documents a 50% Batch discount with a 24-hour completion window, but the
bounded pilot does not use or assume that discount. GPT-5.6 cache writes cost
1.25 times uncached input, while cache reads receive the cached-input rate.
Because Phase 5R requests are stateless and normally separated by hours or
days, the direct Responses adapter uses explicit cache mode with no breakpoint
instead of paying for speculative implicit writes.

Sources:

- <https://developers.openai.com/api/docs/guides/latest-model>
- <https://developers.openai.com/api/docs/models/compare>
- <https://developers.openai.com/api/docs/guides/prompt-caching>
- <https://platform.openai.com/docs/api-reference/batch/object?api-mode=responses>
- <https://openai.com/api/pricing/>

## Minimum viable paid pilot

The first paid step is capped at 30 physical model-inference requests and
$5.00:

- 10 frozen packets with Luna analyst;
- the same 10 with Terra analyst;
- 5 blinded Sol committee requests; and
- 5 Sol critic requests.

Each inference is preceded by one non-inference exact input-token count
request, so the complete transport consists of 30 inference plus 30 token-count
requests. The closed ceiling is 24,000 input and 3,800 output tokens per
inference. Current standard prices yield a `$3.978` no-cache-write maximum and
a `$4.488` cache-write maximum. A 10% billing contingency reserves `$4.9368`,
below the `$5.00` hard cap. No Batch discount or cached-input saving is assumed.

The SDK has `max_retries=0`. Every inference is attempted once; transport
failures and unknown outcomes retain their full reservation and stop the run.

The pilot does not promote a model. It only proves transport, schema, metering,
cost, and whether Luna merits the larger analyst comparison.

## Future qualification cost envelope — not authorized

If the corpus reaches 250 packets across at least 20 issuers and contains at
least 50 reviewed material transitions:

- 250 Terra analyst Batch requests plus 100 sparse Sol committee/critic
  requests are estimated at $38.25;
- if Luna is non-inferior and replaces Terra for the analyst role, the same
  plan is estimated at $25.50.

The qualification hard cap is $45 and 350 physical calls. Neither figure is
authorized. Actual token receipts, not estimates, determine cost.

## Dependencies deliberately not purchased

### Licensed market data

Public secondary market data is enough for research and noncanonical shadow
comparison. It remains explicitly non-action-grade. A licensed ticker-scoped
feed is considered only after model replay quality passes and before any
valuation-sensitive model transition is allowed to influence advisory
language. Until then, affected transitions abstain or remain C9-only.

### Cross-provider challenger

A second paid model family is not required for the initial shadow. A
same-provider Sol critic is sufficient to measure the value of adversarial
review. A cross-provider challenger is considered only if the frozen holdout
shows residual correlated errors or inadequate unique critic catches. It never
receives final authority.

### Multi-agent API orchestration

Disabled. The roles are deterministic sequential requests with closed inputs.
Local preprocessing, exact role routing, and cached completed results are
cheaper and easier to audit than a provider-hosted multi-agent workflow.

## Remaining pilot gates

No model request can begin until:

- external authentication is configured outside the repository;
- the fixed private execution ledger and provider-native metering continue to
  pass at invocation time;
- the offline provider replay and boundary gates continue to pass; and
- model influence, email eligibility, broker access, and order capability
  remain false.

The SEC contact, 5 GB storage limit, 30-call limit, and $5 cap are already
authorized for this pilot. This run passed the contact string at runtime and
did not add it to the model-pilot policy, corpus metadata, model-pilot logs, or
review materials. The same address already exists in unrelated historical
email-delivery artifacts.
The strict point-in-time corpus requirement is now satisfied at `10/10`.
