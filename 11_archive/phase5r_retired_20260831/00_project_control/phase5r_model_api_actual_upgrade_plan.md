# Phase 5R Model/API Actual Upgrade Plan

Date: 2026-07-28
Objective: produce clear, source-grounded buy/hold/trim/exit research decisions
with exception-based review, while keeping all execution manual and outside the
repository

Economical dependency authority as of 2026-07-28:
`00_project_control/phase5r_paid_dependency_policy.json` and
`00_project_control/phase5r_economical_dependency_decision.md`. Where older
cost or dependency examples below differ, the 2026-07-28 closed policy wins.

## 2026-07-28 executable pilot update

The bounded pilot is authorized for OpenAI only, at most `30` physical
model-inference calls, and `$5.00`. Ten genuine SEC point-in-time packets pass
both the original corpus verifier and strict `10/10` inventory after
submissions, Company Facts, accession-level XBRL reconciliation, and attachment
discovery were added.

`09_scripts/phase5r/run_phase5r_model_pilot.py` is now the closed executable
runner. Its frozen request plan is:

- 10 Luna assessments;
- 10 Terra assessments on the identical analyst views;
- 5 randomly blinded Sol committee comparisons; and
- 5 Sol critic requests on a form- and issuer-diverse cohort.

Each inference has a separate non-inference exact input-token count request,
so a completed pilot uses `30` model-inference requests plus `30` token-count
requests. Inference requests are synchronous stateless Responses calls with
`service_tier=default`, `store=false`, `tools=[]`, a 120-second timeout, SDK
`max_retries=0`, at most 24,000 input tokens, and at most 3,800 output tokens.
The full cache-write-aware reservation plus a 10% billing contingency is
`$4.9368`; no Batch discount is assumed. Pricing must be reverified after
2026-08-04.

The executable environment is also frozen: Python `3.11.15`, OpenAI SDK
`2.49.0`, and the complete transitive dependency lock are bound into the plan.
The isolated runtime passed an offline real-SDK construction/boundary smoke
test without a credential, token count request, or inference request.

Actual result: `0/30` calls, zero input/cached/cache-write/output tokens, and
`$0.00/$5.00`, because no externally authenticated OpenAI client is available.
Citation accuracy, unsupported claims, model disagreement, and critic value
remain unmeasured without valid model outputs. The anonymous two-reviewer
protocol and immutable review-material generator are complete, but no review
claims were fabricated.

## Current decision

Proceed with a leakage-free three-role model layer plus deterministic
adjudication:

- evidence analyst: `gpt-5.6-terra`, medium reasoning, because it is the
  cost-balanced quality baseline; `gpt-5.6-luna` is evaluated on the same
  frozen pilot packets and may replace Terra only if it is non-inferior;
- committee/research proposer: `gpt-5.6-sol`, high reasoning, because the
  higher-cost frontier model is reserved for the smaller number of decisions
  that require synthesis and proportionality judgment;
- implemented critic protocol: a separate stateless, proposal-aware request
  whose exact verdict is `approve`, `revise`, or `reject`; it may preserve or
  reduce a proposal but never upgrade or authorize final output;
- cross-provider critic benchmark: `claude-fable-5` for the maximum-capability
  Anthropic arm, `claude-opus-5` as its lower-cost control, or
  `gemini-3.1-pro-preview` as a preview-only alternative, only after the OpenAI
  path has passed a frozen issuer-held-out qualification; no challenger is part
  of the first physical-call pilot or authorized for production;
- target transport: OpenAI Responses API with strict Structured Outputs,
  `store=false`, `tools=[]`, no conversation state, and provider-native
  receipts;
- SEC sufficiency, source/citation validity, the proposal-aware critic, and the
  blinded challenger govern whether a model research class survives. C9,
  market, valuation, portfolio, and risk rules separately govern whether that
  research class is eligible for action review; they cannot silently rewrite
  `exit_review` into `hold_existing`, and a model cannot unlock action
  eligibility by itself;
- buy/hold/trim/exit are user-facing research semantics mapped from the eight
  exact closed contract labels; they are not commands;
- no broker, account, order, trade, or automatic execution capability.

The full research basis is:
`04_research/realtime_stock_picker_phase5r/phase5r_model_api_upgrade_research_20260725.md`.

OpenAI describes Terra as the balanced intelligence/cost tier and Sol as the
flagship tier. Current list prices are `$2.50/$15.00` and `$5.00/$30.00` per
million input/output tokens, respectively:
[GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model),
[Terra model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
and [GPT-5.6 release and pricing](https://openai.com/index/gpt-5-6/).

## Status

| Work package | Status | Exit condition |
| --- | --- | --- |
| M0 safety/contract shell | Complete locally | closed schemas, citation binding, retries, receipts, cost/call ceilings, canonical influence false |
| M1 leakage-free semantic inputs | Complete locally | no C9 recommendation/action/eligibility/score reaches analyst, committee, or critic |
| M2 direct Responses API boundary | Adapter complete; live use disabled | externally constructed client, no credential read, strict JSON schema, no tools, `store=false`, response ID/model/usage receipts |
| M3 cost-aware inference routing | Planner, optional paid-challenger policy, pre-provider gate, exact-role fixture executor, fixed private cycle-ledger location, hash-chained request/token/USD ledger, GPT-5.6 cache-write/read normalization, and metered receipts complete locally; live provider authority disabled | explicit external authentication/cost authorization and physical smoke evidence |
| D1 per-ticker action-grade market contract | Provider-neutral contract, synthetic Massive adapter, and per-ticker packet gate complete locally; licensed feed absent | public data remains research/shadow-only; purchase a licensed feed only if model replay passes and a valuation-sensitive advisory transition requires action-grade data |
| D2 valuation evidence | Receipt validation and deterministic-adjudicator wiring complete; active packet contains zero real receipts | real source-bound shares/market cap/net debt/EV/FCF/dilution/target/downside receipts populate and pass the active packet |
| D3 full-label replay corpus | Minimum-size/diversity gates plus single-split and three-fold issuer/time purge/embargo receipts complete locally; real acquisition and labels blocked | 250–300 locally complete packets, 20+ issuers, 50+ material transitions, 50+ separate adversarial probes, material and no-change/uncertain labels, and real frozen multi-fold scores |
| D4 point-in-time performance | Rolling 12/36/60-month receipt and deterministic sequential paper simulator complete with synthetic tests; real ledger absent | real next-session paper ledger, calibrated costs/cash/corporate actions, benchmarks, drawdown/turnover/CI |
| D5 external blinded challenger | Closed contract, deterministic comparison, injected Anthropic Messages adapter, and offline fixtures complete; no credentials or calls | exact provider-specific schema preflight, frozen cross-family model/version, retention approval, issuer-held-out qualification, and explicit cost/call authorization |
| Q1 30-inference-call provider smoke | Executable, authorized, and corpus-ready; blocked only by external auth | 10 Luna + 10 Terra assessments, 5 blinded Sol committees, and 5 Sol critics; 30 separate non-inference token counts; all receipts valid; no canonical or email effect; `$4.9368` reservation within the `$5` cap |
| Q2 qualification replay | Blocked by corpus/auth | all decision-quality confidence-bound gates pass |
| Q2C cross-provider critic benchmark | Deferred and not required for initial shadow | buy only if the same-provider critic leaves measured correlated errors or inadequate unique catches |
| Q3 live shadow | Blocked by Q2/corpus/auth | 30–60 completed research-only market sessions without boundary/data-quality failure; public market context cannot unlock action-grade transitions |
| A1 advisory email influence | Disabled | explicit activation receipt after all Q gates |

## Concrete model architecture

### Stage 0 — Deterministic packet

Python constructs a sealed packet from point-in-time SEC/issuer evidence,
per-ticker market receipts, deterministic calculations, valuation receipts,
portfolio bands, and risk constraints. The packet contract already accepts and
validates valuation receipts, but the current active packet contains
`"valuation_evidence": []`. C9 recommendations, action labels, eligibility
flags, scores, and the deterministic
`allowed_classifications_by_ticker` map are excluded from all semantic model
views.

The point-in-time contract follows Qlib's distinction between the reporting
period, the date the information became observable, and later revisions. Every
action-grade fact must therefore carry `period_end` or `event_time`,
`published_at`/SEC `accepted_at`, `retrieved_at`, `revision_id`, `provider`,
`source_id`, `raw_hash`, and packet `as_of`; the investable-universe membership
must also be frozen as of the decision time. Historical replay may never
substitute the current/latest revision. Qlib documents the leakage mechanism in
its [PIT database design](https://github.com/microsoft/qlib/blob/main/docs/advanced/PIT.rst)
and truncates rolling training segments by horizon and label delay in its
[task generator](https://github.com/microsoft/qlib/blob/main/qlib/workflow/task/gen.py).

Data connectors may use OpenBB's typed provider/standard-model pattern, but the
provider must be explicitly pinned and its raw request and response retained by
hash. OpenBB otherwise selects from a configured provider priority when none is
specified, and its standard balance-sheet model exposes `period_ending` without
a mandatory publication/acceptance time. Provider normalization therefore does
not confer point-in-time or action-grade status:
[provider selection](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/app/static/container.py),
[typed result metadata](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/app/model/obbject.py),
and [balance-sheet schema](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/provider/standard_models/balance_sheet.py).

### Stage 1 — Terra evidence analyst

`gpt-5.6-terra` with `reasoning.effort=medium` receives only the sealed evidence
view and returns:

- atomic supporting and disconfirming claims tied to allowed source/span IDs;
- period, unit, and calculation references;
- missing decisive evidence and contradictions;
- thesis direction and uncertainty, but no final buy/hold/trim/exit class.

Terra cannot browse, fetch, calculate with a tool, or see provider secrets. Its
output is rejected unless it matches the closed analyst JSON Schema.

### Stage 2 — Sol research proposer

`gpt-5.6-sol` with `reasoning.effort=high` receives the same sealed evidence plus
the validated Terra claim set. It returns exactly one per-ticker research
classification:

- `reject`;
- `watchlist`;
- `hold_existing`;
- `paper_trade_candidate`;
- `real_trade_candidate`;
- `trim_review`;
- `exit_review`;
- `abstain`.

It must provide supporting and disconfirming claim IDs, scenario/invalidation
logic, confidence components, and the evidence that would change its class.
The class is a research proposal only.

### Stage 3 — Proposal-aware critic, then blinded challenger

The implemented first pilot uses a separate Sol request solely to validate
critic mechanics. That request receives the committee proposal from the start;
it is prompt-separated and proposal-aware, not a blinded precommitment. Its
closed verdict is `approve`, `revise`, or `reject`, with a safe
`downgrade_to` class. It can approve the proposal unchanged for deterministic
adjudication or reduce/reject it, but it cannot upgrade or authorize final
output. A same-provider Sol critic is **not** evidence of model-family
independence.

Only after Q2 passes on an issuer-held-out set may Phase 5R run a frozen
challenger benchmark using `claude-fable-5`, `claude-opus-5`, or
`gemini-3.1-pro-preview`. Unlike the current critic, the challenger receives
identical evidence and analyst claims but **not** the Sol proposal; it returns
its own source-bound closed research class. Deterministic Python compares the
two independent proposals and may preserve or downgrade, never upgrade. The
challenger gets no tools, no C9 answer, and no opportunity to tune the holdout.
Its exact frozen contract must pass a provider-specific Structured Outputs
preflight; provider JSON Schema subsets may differ, but semantics may not be
relaxed.

TradingAgents is useful evidence for typed role state, bounded debate rounds,
closed decision enums, and checkpointed hand-offs, but not for independence:
its [bull](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/researchers/bull_researcher.py)
and [bear](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/researchers/bear_researcher.py)
researchers read shared debate history. Phase 5R therefore treats role
specialization as workflow structure only. Independent disagreement requires a
different model family, the same frozen evidence hash, no access to the Sol
proposal, and a precommitted result before deterministic comparison.

### Stage 4 — Deterministic final authority

Python validates citations and recomputes every number, then produces two
explicit axes:

- `research_classification`: the source-bound thesis judgment after evidence,
  critic, confidence-sanity, and blinded-challenger checks;
- `action_review_classification` plus `action_review_status`: the deterministic
  C9/market/valuation/portfolio eligibility result.

The research axis is checked against:

- SEC/current-evidence sufficiency;
- source/citation and calculation validity;
- the critic `approve`/`revise`/`reject` result and any substantiated safe
  downgrade;
- structurally non-empty confidence; and
- the blinded challenger comparison when required.

The action-review axis then checks per-ticker market finality,
`valuation_evidence_v1`, portfolio/risk state, C9
`allowed_classifications_by_ticker`, two distinct closes, and deterministic
transition eligibility. If an action class is not allowed, the action-facing
compatibility label uses a role-aware safe fallback—`hold_existing` for a held
ticker, `watchlist` then `reject` for a candidate, otherwise `abstain`—while
retaining the research label and an explicit divergence reason. This avoids the
previous failure mode where a valid risk-reduction thesis could disappear
behind a C9 HOLD label.

The implemented adjudicator now enforces that separation directly. Stale
market state, inconsistent account/portfolio state, per-ticker freshness,
missing verified close, and C9 eligibility appear on
`action_review_reasons`; they do not erase a separately valid
`research_classification`. Missing source-bound valuation can still make the
research proposal itself unsupported through the committee's valuation
clarity and confidence sanity checks. That distinction prevents both false
certainty and the opposite error of hiding a well-supported thesis behind an
operational gate.

Neither axis can upgrade a failed model result. The C9 map remains hidden from
analyst, proposer, critic, and challenger semantic inputs.
No model output may directly change canonical state, render an email, connect
to a broker, create an order, or execute anything.

The final risk layer also requires a local portfolio-state receipt and enforces
cash, per-name and sector concentration, turnover, liquidity/capacity,
drawdown/regime, and benchmark/factor-exposure limits. If inputs are absent,
constraints conflict, or the optimizer is infeasible or inaccurate, the result
is `abstain` or the applicable safer class. Constraints are never silently
removed. This deliberately differs from Qlib's
[enhanced-indexing optimizer](https://github.com/microsoft/qlib/blob/main/qlib/contrib/strategy/optimizer/enhanced_indexing.py),
which retries without its turnover constraint after an initial solve failure.

### Stage 5 — Cost-aware operational cascade

Qualification replay invokes every frozen role on every selected packet so
that omission, disagreement, and failure rates are measurable. Promoted daily
operation is narrower:

1. deterministic freshness, materiality, PIT, valuation, and risk checks run
   first and cost no model call;
2. a genuinely unchanged, still-fresh HOLD/WATCH case reuses the last sealed
   thesis plus a deterministic no-change receipt;
3. a material packet calls Terra; Sol is called only if the validated evidence
   is sufficient and could change the research class;
4. the cross-family blinded challenger is reserved for candidate/add,
   trim/exit, material disagreement, or other predeclared high-impact cases,
   not routine no-change publication;
5. any role failure, cost/call-ceiling exhaustion, or provider mismatch ends in
   abstention or a safer class. There is no automatic model or data-provider
   fallback.

This cascade reduces routine inference and review without selecting activity
to hit a return target. No model, API, backtest, or multi-agent pattern can
guarantee the stated `12%–15%` annualized aspiration.

The deterministic router and its shadow preflight gate now bind the exact
analyst packet view, cycle date, model registry, provider, prompt, response
schema, token ceilings, USD ceilings, and routing signals before any provider
construction. A separate exact-role executor consumes only that frozen plan.
It writes a private hash-chained worst-case reservation before constructing a
fixture provider, executes exactly the planned one-, two-, or four-role set,
binds dependency result hashes, independently recomputes USD from reported
tokens and pinned prices, and persists a metered result receipt. Interrupted
unknown outcomes keep the worst-case charge and can never be silently retried.

The executor accepts fixture transport only. The operational shadow gate still
blocks every external call with
`live_provider_execution_not_authorized`; there is no fall-through to the
legacy fixed three-role executor. The fixed private per-cycle ledger location
and provider-native GPT-5.6 cache usage normalization are now implemented.
External authentication, cost authority, and physical provider evidence remain
required before live transport can be enabled.

## Provider comparison and qualification decision

| Candidate | Intended role | Official API facts used for planning | Cost at standard list price | Phase 5R decision |
| --- | --- | --- | --- | --- |
| `gpt-5.6-luna` | lower-cost analyst candidate | lowest-cost GPT-5.6 tier; Responses API, Structured Outputs, and Batch | `$1` input / `$6` output per MTok | frozen Batch comparison only; replace Terra only on non-inferiority |
| `gpt-5.6-terra` | high-volume evidence analyst | balanced 5.6 tier; Responses API reasoning and Structured Outputs | `$2.50` input / `$15` output per MTok | selected for Q1/Q2 |
| `gpt-5.6-sol` | committee/proposer and provisional same-provider critic | flagship 5.6 tier; higher reasoning capability | `$5` input / `$30` output per MTok | selected for Q1/Q2 |
| `claude-fable-5` | maximum-capability independent critic challenger | Anthropic's most capable widely released model; 1M context, 128K synchronous maximum output, and Claude API Structured Outputs | `$10` input / `$50` output per MTok | preferred maximum-rigor challenger after issuer-held-out Q2 and exact-schema preflight; never final authority |
| `claude-opus-5` | lower-cost independent critic control | official ID `claude-opus-5`; 1M context, 128K synchronous maximum output, and Claude API Structured Outputs | `$5` input / `$25` output per MTok | cost-performance challenger after issuer-held-out Q2 and exact-schema preflight; never final authority |
| `gemini-3.1-pro-preview` | alternative independent critic challenger | 1M context, 64K maximum output; Structured Outputs supported; model is still preview | `$2` input / `$12` output per MTok at or below 200K input, `$4/$18` above 200K | benchmark only after issuer-held-out Q2; preview status blocks production selection |

Anthropic's official
[model overview](https://platform.claude.com/docs/en/about-claude/models/overview),
[pricing](https://platform.claude.com/docs/en/about-claude/pricing), and
[Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
document Fable 5 and Opus 5, including Structured Outputs on the Claude API.
Anthropic still documents JSON Schema limitations, so official availability
does not replace an exact-contract preflight. Google's official
[Gemini 3 guide](https://ai.google.dev/gemini-api/docs/gemini-3),
[pricing](https://ai.google.dev/gemini-api/docs/pricing), and
[Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output)
document Gemini 3.1 Pro Preview. Provider claims and general benchmarks do not
substitute for the Phase 5R issuer-held-out test.

## Current truth: completed mechanics versus blockers

Completed locally:

- closed analyst, proposer, stricter proposal-aware critic, blinded challenger,
  deterministic comparison, and adjudication schemas;
- dual-axis output preserves `research_classification` independently from
  C9-limited `action_review_classification` and records every divergence;
- a proposal-free challenger input hash, exact disagreement matrix, and an
  injected tool-free Anthropic Messages adapter are implemented with offline
  fixtures; no client or credential is constructed by the repository;
- a transition with structurally empty overall, component, or per-ticker
  confidence now fails closed; the 1% structural floor is explicitly not an
  empirical calibration threshold;
- critic `revise`/`reject` now requires a failed check, a medium-or-higher
  issue, and a real safe downgrade;
- evidence-ID citation binding, fail-closed validation, retry/call/cost
  ceilings, and canonical-influence protections;
- leakage-free semantic views that exclude C9 recommendation, action,
  eligibility, score fields, and `allowed_classifications_by_ticker`;
- an externally constructed direct Responses API adapter with strict schema,
  no credential read, no tools, and provider-native receipt fields;
- a provider-neutral market-data contract, synthetic Massive-shaped adapter,
  and ticker-scoped packet gate; the synthetic registry deliberately cannot
  confer action grade;
- deterministic Decimal valuation and receipt-recomputation foundations with
  synthetic fail-closed tests, now wired into packet validation and the
  deterministic adjudicator;
- portfolio constraints now have exact fields, finite bounded percentages,
  ordered positive caps, targets summing to 100%, a bounded horizon, and an
  immutable manual-execution requirement;
- deterministic C9 per-ticker permission maps and role-aware fail-closed
  fallback, hidden from all semantic model roles;
- ticker-scoped hashed freshness receipts: a transition requires a complete
  SEC scan watermark no older than 48 hours, normal action review requires the
  expected completed market session and a valuation scenario no older than
  seven days, while durable SEC thesis evidence is not expired merely because
  a filing is old;
- research/action dual-axis enforcement now keeps stale market, portfolio,
  freshness, verified-close, and C9 failures on the action axis instead of
  silently erasing a valid research conclusion;
- deterministic cost-aware routing for zero-call no-change/weekend cases,
  Terra-only evidence changes, Sol escalation, and high-impact blinded
  challenges, plus a fail-closed shadow gate that runs before provider
  construction;
- exact planned-role fixture execution with provider construction after a
  durable reservation, hash-chained request/input/output/total-token/USD
  accounting, independently recomputed price, immutable role receipts,
  dependency binding, idempotent reuse, and conservative unknown-outcome
  charging;
- one frozen issuer-grouped chronological split with seven-day purge and
  seven-day embargo, no issuer/packet/adjacent-transition overlap, and a
  recomputable split hash, plus three expanding-window out-of-time folds whose
  holdout issuer and case sets are globally disjoint;
- a completed read-only D3 inventory over `609` distinct SEC accessions,
  selecting `325` candidates (`300` target plus `25` padding) across the six
  currently available issuers;
- machine-enforced promotion minima of `250` replay packets, `20` distinct CIKs,
  `50` material transitions, and `30` live-shadow sessions; the replay loader
  computes CIK diversity and fails closed below the registry threshold;
- provider qualification now reruns the strict manifest-to-ledger proof,
  including SEC/index, normalized-text, market-artifact hashes, and a
  ticker-to-single-CIK invariant; a synthetic fake-CIK/text corpus cannot reach
  provider scoring;
- read-only next-session/TWR/cost/cash/corporate-action/baseline/drawdown/
  turnover/bootstrap foundations with synthetic tests, including exact
  `-100%` terminal loss and 100% drawdown so failed securities are not silently
  excluded;
- immutable monthly performance rows, rolling 12/36/60-month CAGR,
  volatility/downside/Sortino/drawdown/recovery receipts, and a chronological
  long-only paper simulator with cash, exposure, per-name, position-count,
  turnover, cost/slippage, abstain/hold, and terminal-delisting guards.

Not completed or not authorized:

- no paid OpenAI, Anthropic, or Google inference has run;
- the exact-role executor is deliberately fixture-only; no fixed live
  cycle-ledger location, provider-native billing normalization, external
  credential authority, or physical-call authorization exists;
- no real provider response ID, resolved-model receipt, token bill, latency
  distribution, refusal distribution, or output-quality evidence exists;
- the active packet has zero valuation receipts, and no real ingestion path yet
  supplies point-in-time shares, debt, cash, FCF, or target/downside inputs;
- the local Massive adapter is synthetic-only and action grade is disabled; no
  licensed, ticker-scoped, finality-aware feed or 30-session shadow exists;
- D3 has `0` locally complete packets. The `325` selected candidates have
  missing filing index snapshots for all `325`, missing raw submissions for all
  `325`, missing market packets for all `325`, and incomplete exhibit discovery
  for `204`; the six-issuer inventory also misses the `20+` issuer design
  minimum;
- independent labels and real no-change/uncertain controls are not frozen;
  the three-fold algorithm and receipts pass synthetic tests, but no real
  corpus exists on which to freeze or score those folds;
- the real paper NAV/cash-flow/corporate-action/benchmark ledger does not
  exist;
- an injected Anthropic Messages adapter and proposal-free challenger contract
  exist locally, but no Claude/Gemini credential, schema preflight, cost
  authorization, or real challenger run exists;
- live shadow, email influence, broker access, order creation, and execution
  remain disabled.

## Work package details

### M1 — Leakage-free decision formation

The model forms its thesis before seeing C9's answer.

Required:

- strip deterministic recommendation, action, eligibility, and C9 score fields
  from all semantic inputs;
- retain only source evidence, reconciled calculations, legitimate portfolio
  constraints, and evidence-quality gates;
- apply C9 permissions only during final deterministic adjudication;
- run label-mutation invariance tests.

Acceptance:

- a changed hidden C9 label cannot change the semantic evidence view except for
  opaque packet identity;
- hidden C9 source/calculation IDs cannot be cited as model evidence;
- all existing safety and fixture tests still pass.

### M2 — Direct API receipt boundary

Required request settings:

- `/v1/responses`;
- strict `text.format` JSON Schema with `additionalProperties=false`;
- `tools=[]`;
- `store=false`;
- no `conversation`, `previous_response_id`, background mode, hosted tool,
  search, file retrieval, code interpreter, or programmatic tool calling;
- explicit model and reasoning effort;
- bounded output tokens;
- one stateless role request.

Required receipt:

- provider response ID;
- requested and resolved model;
- status;
- input/output hashes;
- input/output/total tokens;
- latency;
- prompt/schema/runtime hashes;
- physical attempt number and cumulative cost estimate.

The bounded pilot allows no retry of any inference request. A transport
timeout, connection failure, or unknown outcome consumes the full reservation,
is recorded durably, and stops the pilot. Refusal, incomplete, malformed,
schema-invalid, citation-invalid, semantic-invalid, or policy-invalid results
are likewise terminal.

OpenAI documents JSON Schema Structured Outputs in the Responses API and the
meaning of response storage/data controls:
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [API data controls](https://developers.openai.com/api/docs/guides/your-data).
`store=false` avoids stored Responses application state, while default
abuse-monitoring logs may retain content for up to 30 days and prompt-caching
or account controls have separate behavior. This is not account-level Zero Data
Retention without the relevant approval.

### Q1 physical-call and cost plan

The first paid pilot is capped at exactly `30` model-inference requests:

- `10` frozen public-evidence packets × one Luna analyst request;
- the same `10` packets × one Terra analyst request;
- `5` blinded Sol committee requests; and
- `5` Sol critic requests.

Before each inference, one exact `/responses/input_tokens` request measures the
same semantic input. Those `30` token-count requests do not generate model
output and are reported separately; the promise is therefore 30 physical
model-inference calls, not 30 total HTTP requests.

Every inference is attempted at most once. An ambiguous or failed outcome
retains its full durable reservation and stops the pilot. C9 and deterministic
validation do not consume provider calls.

The closed envelope is at most `24,000` input and `3,800` output tokens per
request. At pinned standard prices the no-cache-write maximum is `$3.978`; the
cache-write maximum is `$4.488`; and the hard reservation after a 10% billing
contingency is `$4.9368`. The operator hard cap is `$5.00`. No Batch discount,
cached-input saving, provider retry, or regional-price assumption is used.

Exact provider usage receipts determine the recorded standard cost. The
conservative reservation remains the budget authority and is never reclaimed
after an unknown outcome.

Q2 uses one analyst request for every one of 250 frozen packets and two Sol
requests only for 50 material transitions: at most `350` requests. Under the
same conservative token envelope and OpenAI's 50% Batch discount, the estimate
is `$38.25` with Terra or `$25.50` if Luna passes the non-inferiority gate.
The operator hard cap is `$45.00`. Batch is limited to public, sanitized replay
material:
[OpenAI Batch API](https://platform.openai.com/docs/api-reference/batch/object?api-mode=responses).

After issuer-held-out Q2 passes, a `50`-packet critic challenger benchmark
would cost, under the same 20K/8K envelope:

- Claude Fable 5: about `$30.00`;
- Claude Opus 5: about `$15.00`;
- Gemini 3.1 Pro Preview under the 200K-input tier: about `$6.80`;
- all three challengers, if separately authorized: about `$51.80`.

Those challenger estimates exclude taxes, retries, data-residency multipliers,
and provider price changes. No cross-provider spend is authorized by this
plan.

An illustrative **post-qualification operating ceiling** uses zero calls for
unchanged cycles, one Terra-or-Luna request for material evidence, and no more
than three same-provider requests for a material transition. Cross-provider
calls remain zero unless Q2 demonstrates a specific residual-error need.

The direct adapter disables implicit GPT-5.6 cache breakpoints because
stateless Phase 5R role requests are normally too far apart to reuse the
30-minute cache. Cache reads and writes are still normalized and priced from
actual provider receipts. API spend is an operating cost in net performance;
it is never justified by assuming the 12%–15% aspiration will be achieved.

### D1 — Action-grade market data

The provider-neutral `secondary_context`, `valuation_grade`, and
`action_grade` contract, a Massive-shaped synthetic adapter, and the
ticker-scoped packet gate are implemented locally. The committed registry
requires synthetic fixtures, keeps `action_grade_enabled=false`, and produces
an empty `action_grade_tickers` list; this is correct fail-closed behavior, not
a live-provider integration. `yfinance` remains secondary context and can
never unlock an action.

Action grade is per ticker and requires a licensed feed, identity/MIC/currency
checks, exact completed session, event/retrieval/finality timestamps, finite
OHLCV invariants, raw hashes and request receipts, pagination completeness, and
split/dividend reconciliation. A global boolean is insufficient. D1 exits only
after a licensed Massive or equivalent read-only feed produces real receipts
and the path completes a 30-session shadow without cross-ticker unlocking.

### D2 — Deterministic valuation

The model may interpret a valuation but may not create its inputs or numbers.

The standalone Decimal module and fail-closed synthetic tests now exist
locally. It produces source/period/unit-bound receipts, recomputable formulas,
SHA-256 receipt integrity, and separate observation versus scenario-assumption
types. Receipt validation is wired into the evidence-packet contract and
deterministic adjudicator. The active real packet nevertheless contains
`"valuation_evidence": []` and `valuation_action_grade_tickers=[]`, because no
real ingestion path supplies the required inputs. The model therefore cannot
unlock a valuation-dependent transition.

Minimum source-bound inputs:

- point-in-time price and diluted shares;
- cash, debt, net debt/net cash, market cap, and enterprise value;
- revenue and FCF with units and periods;
- dilution trend;
- deterministic base target and downside reference with disclosed method;
- recomputed expected upside and reward-to-risk.

Rules:

- missing diluted shares or net debt blocks sufficiency;
- no reconciled valuation calculation means
  `valuation_clarity_pct=0`;
- an insufficient ticker cannot become a buy/add/ordinary trim transition;
- no input is imputed by the LLM.

### D3 — Qualification corpus and labels

The read-only inventory is complete, but acquisition and materialization have
not run. It found `609` distinct ledger accessions and selected `325`
candidates (`300` target plus `25` padding) across ARM, AVGO, IOT, MU, PANW,
and RBRK. The 10-packet pilot and 300-packet qualification selections are
acceptance-complete as metadata, but locally complete packet count and corpus
bytes are both `0`.

For the `325` selected candidates, the inventory reports `325` missing filing
index snapshots, `318` missing primary filings (`7` reusable verified daily
primaries), `325` missing raw-submission snapshots, `204` with missing or
incomplete exhibit discovery, `73` missing XBRL reconciliation, and `325`
missing market packets. Qualification acquisition is estimated at `791–2,701`
requests; the upper bound remains uncertain because exact exhibit counts are
unknown. Typical projected storage is `1,119,510,052` bytes (about `1.12 GB`);
the deliberately conservative planning upper bound is `72,938,946,560` bytes
(about `72.94 GB`). No provider call or corpus acquisition is authorized.

The combined registry, corpus, and replay gates now machine-enforce at least
`250` packets, `20` distinct issuer CIKs, `50` material transitions, `50`
separate adversarial-safety probes (`100` combined cases), and `30`
live-shadow sessions. The loader rejects lowered caller/registry minima and
stale manifest declarations. Inventory readiness counts issuers only inside the
qualification slice, so an issuer found only in reserve padding cannot satisfy
the floor; the current six-issuer inventory cannot be mistaken for promotion
authority.

Freeze:

- 250–300 point-in-time packets;
- at least 20 issuers across sectors, maturity, forms, years, and regimes;
- 10-K/20-F, 10-Q, substantive 8-K/6-K, amendments, exhibits and XBRL;
- offerings/dilution, accounting, cyber, governance, mergers, ticker changes,
  acquired/delisted/failed-thesis cases;
- at least 150 chronological probes.
- at least 50 distinct adversarial-safety probes, separate from at least 50
  independently confirmed material transitions.

Two independent reviewers label all probes before adjudication. Retain positive,
no-change, uncertain, reject, watch, and abstain cases. Do not discard negatives
to reach a quota. The final reference set must contain at least 50 independently
confirmed material transitions.

### D4 — Decision and economic evaluation

Decision-quality gates:

- action precision lower confidence bound;
- false-decisive-rate upper confidence bound;
- material/decisive/counterevidence recall;
- exact-span citation precision;
- numerical and period/unit validity;
- risk-coverage/abstention curve;
- critic unique catches minus false rejects/downgrades;
- issuer/form/regime breakdowns;
- plausible counterfactual stability.

Economic evaluation:

- point-in-time decisions only;
- next-session fill, no same-close lookahead;
- whole-share and small-account effects;
- spreads, slippage, commissions, cash drag;
- splits, dividends, acquisitions and delistings;
- SPY total return, QQQ/XLK context, C9-only and no-change baselines;
- TWR, rolling CAGR, drawdown, downside risk, turnover, attribution, and
  issuer/regime-clustered intervals.

The local read-only foundation now covers next-session paper price selection,
explicit modeled costs, external-flow-neutralized TWR, cash drag, split,
dividend and delisting receipts, required SPY/QQQ/XLK/C9 alignment, drawdown,
turnover, and seeded block-bootstrap intervals using synthetic inputs. It has
no network, broker, execution, or file-write capability. A real frozen ledger,
corporate-action coverage manifest, benchmark total-return series, and
out-of-time decisions are still absent, so no return result is available.

The rolling 12%–15% annualized objective is measured, never used as a label,
quota, guarantee, or reason to force activity.

The newer monthly layer also validates consecutive source-bound ledger rows
and emits rolling 12-, 36-, and 60-month results plus full-period CAGR,
annualized volatility, downside deviation, Sortino, maximum drawdown,
underwater duration, and recovery. Objective status is `insufficient` until
60 months exist. A sequential simulator can produce those rows from
chronological paper decisions and market receipts while enforcing long-only
cash, gross exposure, per-name, position-count, turnover, modeled-cost, and
terminal-loss rules. Its current limitations—monthly bars, assumed costs,
no ordinary dividends/splits/taxes/partial fills, and no sector/factor/
liquidity constraints—remain explicit.

## Reduced-human-review operating model

After qualification:

- routine, fully agreed, current HOLD/WATCH decisions publish automatically;
- fully validated action-review conclusions may publish a clear decisive
  headline automatically;
- review is required only for disagreement, abstention, stale or inconsistent
  data, corporate action, model/prompt/schema change, large valuation shock,
  concentration conflict, or boundary failure;
- actual buy/sell/trim/exit execution remains a separate manual choice.

This removes routine semantic checking without pretending that model confidence
is execution authority.

## Verification snapshot

- Full integrated local suite: PASS, `369/369`, including the executable
  bounded pilot, durable audit journal, storage enforcement, exact token
  preflight, and anonymous-review generation.
  same-provider initial-shadow policy and explicit paid-challenger opt-in.
- Cost-router planner/gate, durable exact-role fixture execution and metering,
  three-fold issuer/time validation, freshness, research/action separation,
  runtime hash coverage, sequential simulator, and rolling-performance tests
  are included in that count.
- Persisted active packet remains packet
  `0125bf68a4d8f02e31e586752ff3b8427268c833d0c66293eac0cf73d20cb3af`
  with `7` entities, `81` sources, and `0` real valuation receipts.
- A read-only current packet build validated packet
  `6186f2d2238d3039e8c7956afd458f3935e41011c9e32566c41fef545541f05b`
  with `7/7` SEC-current and market-current ticker receipts, `0/7`
  valuation-current receipts, and no persisted/canonical/email effect.
- LLM shadow boundary: PASS with fixture transport; no provider, network,
  credential, email, SMTP, broker, order, or canonical effect.
- Provider replay gate: correctly blocked with `0` real qualified packets and
  no verifier side effects; it now reruns the strict manifest/ledger/SEC/market
  provenance verifier, and the synthetic fake-CIK/text corpus is rejected.
- Qualification inventory: correctly blocked at `250` selected target packets
  because only `6/20` issuers are present and `0/250` packets are locally
  complete.

## External inputs required

The SEC contact, SEC-network permission, 5 GB storage ceiling, OpenAI-only
30-inference-call limit, and `$5.00` cap have already been supplied and are not
outstanding.

1. Construct an authenticated OpenAI SDK client outside the repository with
   `max_retries=0`, the global standard API base, and no regional-processing
   billing multiplier; inject it into `OpenAIResponsesProvider` with the
   `global_standard_no_regional_processing` billing attestation. Never paste a
   key into chat, source files, logs, a LaunchAgent, or SMTP configuration.
2. Complete two independent copies of the generated anonymous review bundle
   and one adjudication receipt after real outputs exist. This review measures
   semantic citation accuracy, unsupported claims, disagreements, and critic
   value; it cannot activate canonical or email influence.

The present corpus occupies `37,968,013` of the authorized
`5,000,000,000` bytes. Qualification, live shadow, licensed data, a second
provider, model/email influence, and scheduler installation remain outside
this pilot and require separate future authorization.

A licensed market-data purchase is deliberately deferred. Public secondary
data is sufficient for noncanonical research shadow; valuation-sensitive
transitions continue to abstain until a later action-grade purchase gate is
met.

Until the authenticated client exists, continue only offline contract, fixture,
inventory, and verification work.
