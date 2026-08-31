# Phase 5R Model/API Upgrade Research

Date: 2026-07-25  
Status: architecture decision made and core offline hardening implemented;
real corpus/data qualification remains blocked; no paid provider inference or
market-data subscription activated

## Research question

What model/API architecture can materially improve Phase 5R's long-horizon
equity decisions, allow the system to state clear buy/hold/trim/exit research
recommendations with less routine human review, and still fail closed when the
evidence, valuation, market data, or evaluation record is inadequate?

The target is not to find a model that sounds more confident. The target is to
measure whether a model adds decision value beyond deterministic C9 on
point-in-time evidence, without giving the model broker, order, SMTP, or
canonical-state authority.

## Method and evidence limits

This assessment combines:

- direct inspection of the active Phase 5R code and local artifacts;
- current official OpenAI API documentation;
- primary repositories and papers for open-source finance systems;
- public risk-management and backtest-overfitting guidance;
- adversarial tests for label leakage, evidence omission, valuation invention,
  correlated critics, temporal leakage, and false decisiveness.

Vendor documentation establishes API behavior, not investment performance.
Project repositories and arXiv papers establish that an architecture exists,
not that its reported returns will reproduce in Phase 5R. No source found
justifies delegating trading execution to an LLM.

## Decisive conclusion

Use a frontier reasoning model through the OpenAI Responses API as a
**leakage-free semantic research layer**, not as an autonomous trading agent:

1. `gpt-5.6-terra` with `reasoning.effort=medium` extracts source-bound facts,
   contradictions, missing decisive evidence, periods, units, and calculation
   references. It does not choose the final action class.
2. `gpt-5.6-sol` with `reasoning.effort=high` independently proposes exactly
   one classification from the implemented closed set: `reject`, `watchlist`,
   `hold_existing`, `paper_trade_candidate`, `real_trade_candidate`,
   `trim_review`, `exit_review`, or `abstain`.
3. The implemented separate Sol critic is proposal-aware and returns
   `approve`, `revise`, or `reject`; it tests critic mechanics but is neither
   blinded nor model-family independent. A proposal-free challenger contract,
   deterministic disagreement matrix, and injected Anthropic Messages adapter
   are now implemented offline. After Q2, a real cross-provider model must
   precommit on the same evidence hash without the Sol proposal and pass
   provider-specific schema, retention, and issuer-held-out tests.
4. Only after issuer-held-out qualification may a frozen challenger benchmark
   use `claude-fable-5` for maximum Anthropic capability, `claude-opus-5` as a
   lower-cost Anthropic control, or `gemini-3.1-pro-preview` as a preview-only
   alternative.
5. Deterministic Python recomputes every number. Evidence and valuation
   sufficiency, critic, and blinded-challenger checks determine
   `research_classification`; ticker-scoped freshness/finality,
   portfolio/risk, verified-close, and C9 permissions separately determine
   `action_review_classification`. A blocked action cannot erase a supported
   research conclusion, and a model cannot unlock action eligibility.
6. Only the validated research result may later appear automatically in the
   daily email. It is a research classification rather than an instruction;
   execution remains manual and outside the repository.

## Post-research implementation result

The local implementation now includes:

- a ticker-scoped SEC/market/valuation freshness receipt that does not expire
  durable filing evidence merely because it is old;
- explicit research/action dual-axis adjudication, including visible
  divergence when market, portfolio, close, freshness, or C9 blocks an
  otherwise supported research conclusion;
- a proposal-free cross-family challenger contract and exact disagreement
  matrix;
- a worst-case-reserving cost router, pre-provider shadow gate, and exact-role
  fixture executor with private hash-chained request/token/USD accounting,
  metered immutable receipts, and conservative unknown-outcome charging; live
  provider authority remains disabled;
- one issuer-grouped chronological development/holdout split plus three
  expanding out-of-time folds, each with seven-day purge/embargo and no
  issuer/packet/adjacent-transition leakage, with globally disjoint holdout
  issuers and cases;
- rolling 12/36/60-month performance evidence and a chronological monthly
  portfolio simulator with modeled costs, cash/exposure/turnover constraints,
  abstain/hold semantics, and exact terminal losses; and
- runtime-hash coverage for the new transitive routing and freshness code.

The integrated offline suite passes `341/341`. This is contract and safety
evidence, not proof of investment skill. No real model response, licensed
market receipt, populated valuation receipt, complete replay corpus, or real
paper-performance result exists yet.

This follows OpenAI's current guidance to use the Responses API for reasoning
workflows, define exact output schemas and tool boundaries, and compare changes
on representative evals. Strict Structured Outputs constrain JSON shape, but
they do not establish factuality or economic value:
[model guidance](https://developers.openai.com/api/docs/guides/latest-model),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
and [working with evals](https://developers.openai.com/api/docs/guides/evals).

The direct Responses API is the production target because it can provide a
provider-native response ID, resolved model metadata, status, and token usage.
The existing constrained Codex CLI bridge remains an offline/exploratory
fallback only because it cannot provide authoritative API billing and response
receipts. The proposed 30-call pilot, if explicitly authorized, must use the
direct Responses adapter.

Every direct model request is stateless and uses a strict JSON Schema,
`tools=[]`, `store=false`, no conversation/previous-response linkage, and no
background, search, retrieval, code-interpreter, function, or programmatic-tool
surface. OpenAI documents both the Responses Structured Outputs contract and
the fact that `store=false` is not by itself the same as account-level Zero Data
Retention:
[Responses/Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and [API data controls](https://developers.openai.com/api/docs/guides/your-data).

## Concrete role and authority flow

```text
point-in-time SEC + market + deterministic calculations + valuation + risk
                                  |
                    leakage-free sealed evidence view
                                  |
                 Terra analyst: claims and contradictions
                                  |
                  Sol proposer: research classification
                                  |
       proposal-aware critic: approve unchanged / revise / reject
                                  |
        deterministic citation/numeric/SEC/market/valuation/risk/C9 intersection
                                  |
              validated research artifact or fail-closed abstention
                                  |
                 optional daily-email text after full promotion
```

C9's answer and `allowed_classifications_by_ticker` map are absent from all
semantic formation stages. At final adjudication, the hidden deterministic map
may preserve or downgrade a proposal but may never upgrade it. The implemented
fallback is role-aware: prefer `hold_existing` for a held ticker; prefer
`watchlist`, then `reject`, for a candidate; otherwise use `abstain`. No model
can write canonical state, choose an executable quantity, send an email
directly, connect to an account, create an order, or execute.

## Primary-source provider comparison

| Model/provider | Why it is considered | Official context/output and structured-output facts | Standard list price | Decision |
| --- | --- | --- | --- | --- |
| OpenAI `gpt-5.6-terra` | lower-cost high-volume evidence extraction | OpenAI describes Terra as its balance of intelligence and cost; 1.05M context and 128K max output | `$2.50` input / `$15` output per MTok | selected analyst for physical pilot and qualification |
| OpenAI `gpt-5.6-sol` | harder synthesis and proportionality judgment | OpenAI's flagship 5.6 tier; Responses API reasoning and strict Structured Outputs | `$5` input / `$30` output per MTok | selected proposer; separate Sol critic is only a same-provider control |
| Anthropic `claude-fable-5` | highest available capability can test the hardest OpenAI failure cases | Anthropic's most capable widely released model; 1M context, 128K synchronous max output, and Claude API Structured Outputs | `$10` input / `$50` output per MTok | preferred maximum-rigor challenger after issuer-held-out qualification and exact-schema preflight |
| Anthropic `claude-opus-5` | lower-cost different-family control can expose correlated OpenAI errors | official ID `claude-opus-5`; 1M context, 128K synchronous max output, and Claude API Structured Outputs | `$5` input / `$25` output per MTok | lower-cost challenger after issuer-held-out qualification and exact-schema preflight |
| Google `gemini-3.1-pro-preview` | lower-cost alternative independent challenger | 1M context, 64K max output; Structured Outputs supported; explicitly a preview model | `$2/$12` per MTok at or below 200K input; `$4/$18` above 200K | challenger benchmark only; preview status blocks production selection |

Primary official sources:

- OpenAI:
  [GPT-5.6 model guidance](https://developers.openai.com/api/docs/guides/latest-model),
  [Terra model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
  and [GPT-5.6 release/pricing](https://openai.com/index/gpt-5-6/).
- Anthropic:
  [models overview](https://platform.claude.com/docs/en/about-claude/models/overview),
  [pricing](https://platform.claude.com/docs/en/about-claude/pricing), and
  [Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
- Google:
  [Gemini 3 guide](https://ai.google.dev/gemini-api/docs/gemini-3),
  [pricing](https://ai.google.dev/gemini-api/docs/pricing), and
  [Structured Outputs](https://ai.google.dev/gemini-api/docs/structured-output).

The providers' general reasoning and finance benchmarks are only model-selection
hypotheses. They do not answer whether a model has incremental Phase 5R
decision value, which is why the same frozen issuer-held-out evidence and
metrics are mandatory. All three providers support Structured Outputs, but
Anthropic and Google document schema subsets or limitations. Each adapter must
therefore preflight the exact frozen semantic contract using its provider-native
schema form; a limitation may block that provider but may never justify looser
decision semantics.

## Why the current system is not yet decision-robust

### Market evidence

The provider-neutral market contract, synthetic Massive-shaped adapter, and
per-ticker packet gate are complete locally. The synthetic registry
deliberately sets `action_grade_enabled=false` and cannot unlock a transition.
The active B2 path still uses public `yfinance` context and does not provide a
licensed, hash-bound, finality-aware action-grade receipt. A global boolean is
also insufficient: ticker A's clean bar must never unlock ticker B. A licensed
feed and 30 completed-session shadow remain absent.

### SEC evidence

The local SEC ledger is real and provenance-aware. The completed read-only D3
inventory found `609` distinct accessions and selected `325` candidates
(`300` target plus `25` padding) across six issuers. Selection metadata is
acceptance-complete for a 10-packet pilot and a 300-packet qualification
cohort, but locally complete packet count and corpus bytes are both `0`.

Across the `325` candidates, all lack local filing-index and raw-submission
snapshots, `318` lack a reusable primary filing, `204` have missing or
incomplete exhibit discovery, `73` lack XBRL reconciliation, and all `325`
lack market packets. Estimated qualification acquisition is `791–2,701`
requests, with the upper bound uncertain until exhibit discovery. Typical
projected storage is `1,119,510,052` bytes (about `1.12 GB`), versus a
deliberately conservative `72,938,946,560`-byte (`72.94 GB`) planning upper
bound. The current six issuers do not meet the `20+` issuer qualification
design, and acquisition has not been authorized. This inventory is planning
evidence, not a replay corpus or proof of generalization.

### Valuation

C9 leaves individual-candidate expected upside and reward-to-risk empty. The
model fixture can nevertheless self-report high `valuation_clarity_pct` without
market cap, diluted shares, net debt, FCF, or a reconciled valuation. That is a
contract bug, not a model-quality result.

A standalone local `valuation_evidence_v1` foundation now performs Decimal-only
market-cap, net-debt, enterprise-value, revenue/FCF, dilution, target/downside,
upside, and reward-to-risk calculations. It binds each input to source IDs,
period, unit, and availability time, separates observations from scenario
assumptions, rejects unknown/future/malformed inputs, and fails closed when
evidence is insufficient. Receipt validation is wired into packet validation
and deterministic adjudication. The active real packet nevertheless has
`"valuation_evidence": []` and no valuation-action-grade ticker, because no
real point-in-time ingestion supplies those inputs. The integration is
therefore locally complete but not populated with decision-grade evidence.

### Evaluation

The existing offline fixtures prove schema, citations, safety, retry, and
adjudication mechanics. They do not prove investment skill. The real promotion
test needs both material changes and genuine no-change/uncertain cases,
issuer-held-out and out-of-time splits, deployment-shaped multi-ticker
portfolios, pre-frozen gold evidence spans, and point-in-time performance.

### Label leakage

The semantic model previously received C9 recommendations and derived research
labels. A model could therefore look accurate by paraphrasing C9. The local
mechanics now use a two-stage boundary: the model first sees only evidence and
legitimate portfolio constraints; deterministic C9 permissions enter only
during final adjudication. Real-provider invariance still has to be measured.

## Actual implementation state

### Completed local mechanics

- closed analyst, proposer, critic, and deterministic-adjudication contracts;
- evidence-ID citation binding, strict schema validation, retries, physical
  call/cost ceilings, and canonical-influence protection;
- leakage-free semantic role views with C9 recommendation/action/eligibility/
  score fields and `allowed_classifications_by_ticker` removed;
- a direct Responses adapter that accepts an externally constructed client,
  does not read credentials, requests strict JSON, disables tools and storage,
  and records provider response/model/status/usage metadata;
- a provider-neutral market-data contract, Massive-shaped synthetic adapter,
  and per-ticker action-grade packet gate, with synthetic fixtures correctly
  prevented from becoming action grade;
- deterministic valuation receipt, sufficiency, integrity, packet validation,
  deterministic-adjudicator wiring, and fail-closed synthetic tests;
- hidden C9 per-ticker permission-map enforcement and role-aware fallback;
- the D3 read-only inventory over `609` distinct accessions, with `325`
  candidates selected for a 300-packet target plus padding;
- machine-enforced promotion minima of `250` replay packets, `20` distinct
  issuer CIKs, `50` material transitions, and `30` live-shadow sessions; the
  replay loader computes CIK diversity and fails closed;
- read-only next-session, TWR, external-flow, cash-drag, cost,
  split/dividend/delisting, SPY/QQQ/XLK/C9 alignment, drawdown, turnover, and
  block-bootstrap foundations with synthetic tests.

### Real-data, provider, and shadow blockers

- no paid OpenAI, Anthropic, or Google request has run, so there is no real
  response ID, resolved model, token bill, latency, refusal, or quality record;
- current market context is not a licensed ticker-scoped action-grade feed, and
  no 30-session market-data shadow exists;
- the active packet has zero valuation receipts; real diluted shares,
  cash/debt, FCF, and valuation scenarios are not ingested;
- D3 has `0` locally complete packets despite its completed selection
  inventory; corpus acquisition/materialization is blocked, and six issuers
  remain below the `20+` design minimum;
- full negative/no-change/uncertain labels, issuer-held-out and out-of-time
  splits, and sufficient adverse/corporate-action cases are not frozen;
- no immutable real paper NAV, external-flow, total-return benchmark, or
  corporate-action coverage ledger exists;
- no Claude/Gemini adapter, external credential, retention review, or spend
  authorization exists;
- no 30-call pilot, qualification replay, cross-provider critic benchmark, or
  30–60-session live shadow has occurred;
- canonical influence, email influence, broker access, order creation, and
  execution remain disabled.

## Open-source audit

| Project | Portable mechanism verified in primary source | Material limitation | Phase 5R decision |
| --- | --- | --- | --- |
| [Microsoft Qlib](https://github.com/microsoft/qlib) | Its [PIT design](https://github.com/microsoft/qlib/blob/main/docs/advanced/PIT.rst) separates reporting period, observation date, and revisions; its [rolling task generator](https://github.com/microsoft/qlib/blob/main/qlib/workflow/task/gen.py) truncates training by horizon/label delay; benchmarks report [20-seed mean/std](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md). | PIT support does not automatically fix news timing, universe survivorship, or every processor. Its [enhanced optimizer](https://github.com/microsoft/qlib/blob/main/qlib/contrib/strategy/optimizer/enhanced_indexing.py) removes the turnover constraint and retries after an initial failure. | Adopt the PIT/revision contract, purged chronological walk-forward, cost-aware evaluation, and portfolio-constraint mathematics. Reimplement constraints fail-closed; do not import execution authority. |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Typed [decision schemas](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/schemas.py), bounded role graph, deterministic market snapshots, and atomic/checkpointed decision records are useful workflow patterns. | Its [bull](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/researchers/bull_researcher.py) and [bear](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/researchers/bear_researcher.py) read shared debate history, so agreement is correlated rather than independent. Its [fundamental filter](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/dataflows/alpha_vantage_fundamentals.py) uses fiscal-period end rather than filing availability, and the [paper](https://arxiv.org/abs/2412.20138) evaluates a short 2024 window and a handful of large technology stocks. | Borrow typed state, exact enums, bounded rounds, logs, and tests. Do not treat shared-role debate or reported annualized returns as robustness evidence. |
| [OpenBB](https://docs.openbb.co/platform/developer_guide) | The standardization framework provides typed adapters and an `OBBject` with [provider and warning metadata](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/app/model/obbject.py). | When no provider is specified, OpenBB can select from a [configured priority](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/app/static/container.py). Standard financial-statement models such as [balance sheet](https://github.com/OpenBB-finance/OpenBB/blob/develop/openbb_platform/core/openbb_core/provider/standard_models/balance_sheet.py) have `period_ending` but no mandatory publication/acceptance timestamp. | Borrow the adapter/validation pattern, but pin the provider and version, retain raw request/response hashes, and apply Phase 5R PIT checks outside the adapter. No silent fallback. |
| [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) | Domain-specific sentiment tasks can be a separately scored specialist feature. | Its forecaster injects a current company profile into historical prompts, filters basics by fiscal period rather than availability, uses random news sampling, and constructs teacher explanations after supplying the realized label; the project [warns that random news can strongly bias results](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/fingpt/FinGPT_Forecaster/README.md). | Consider only after PIT repair, frozen corpus manifests, seeded construction, issuer/time holdouts, and probability calibration. Never final authority. |
| [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) | Separating deterministic calculations from LLM narrative and using specialized report contracts are sound boundaries. | The current [valuation engine](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/finrobot_equity/core/src/modules/valuation_engine.py) substitutes hard-coded net-debt, FCF, multiple, growth, WACC, and confidence assumptions when inputs are missing. Its [equity paper](https://arxiv.org/abs/2411.08804) primarily evaluates one generated report through expert and GPT-4 ratings, not point-in-time Buy/Sell outcomes. | Keep the calculation/narration separation; reject arbitrary valuation defaults, self-scored confidence, and end-to-end action authority. |
| [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | Transaction-cost environments and regime/turbulence guards are useful offline comparison ideas. | The repository identifies the classic stack as [education/research](https://github.com/AI4Finance-Foundation/FinRL/blob/master/README.md); its [preprocessor](https://github.com/AI4Finance-Foundation/FinRL/blob/master/finrl/meta/preprocessor/preprocessors.py) uses backward filling and drops tickers without complete histories, creating leakage and survivorship concerns. | Do not introduce RL in this upgrade. It increases objective/reward and execution risk before the PIT corpus and simulator are qualified. |
| [VectorBT](https://github.com/polakowo/vectorbt) | Fast parameter sweeps and explicit fees, slippage, partial fills, size granularity, shared cash, call sequence, and seed controls. | A vectorized engine does not repair PIT, universe, corporate-action, or delisting bias, and order timing can diverge from an event-driven simulator. | Optional differential calculator only after the canonical ledger exists. |

The synthesis is that open-source projects are useful as **design references and
independent test tools**, not as a turnkey “AI fund manager.” Importing a larger
agent framework would increase dependencies and tool authority before Phase 5R
has the data and evaluation needed to judge it.

### Evidence-backed architecture selected

The resulting architecture is a cost-aware, fail-closed cascade:

1. A deterministic materiality and sufficiency gate creates one immutable
   evidence bundle. Each fact binds event/period time, publication or SEC
   acceptance time, retrieval time, revision, provider, source ID, raw hash,
   and decision `as_of`; universe membership is point-in-time.
2. OpenBB-style typed adapters normalize transport only. The exact provider,
   endpoint, parameters, schema version, and raw response are pinned and
   receipted; no automatic provider substitution is permitted.
3. Terra extracts source-bound supporting and disconfirming claims. Sol proposes
   a closed research class only when the packet is sufficient.
4. A production challenger must be cross-family and blind: it receives the same
   evidence hash but neither Sol's proposal nor C9's answer, and precommits its
   own closed class. TradingAgents-style shared debate is retained only as a
   workflow/testing pattern, not counted as independent agreement.
5. Deterministic Python recomputes numbers and applies C9 plus cash, per-name
   and sector concentration, turnover, liquidity/capacity, drawdown/regime, and
   benchmark/factor-exposure constraints. Missing state, infeasibility, or an
   inaccurate solve produces abstention or a downgrade; constraints are never
   relaxed to obtain an answer.
6. Qualification calls every role on every frozen packet. After promotion,
   unchanged fresh HOLD/WATCH cases may terminate at the deterministic gate;
   Terra runs on material evidence, Sol only when the class could change, and
   the external challenger only for predeclared high-impact transitions or
   disagreement. Call/cost exhaustion is a safe failure, not a fallback.

No component is selected because it reported the highest historical return.
Phase 5R must use chronological purged walk-forward tests, issuer-held-out and
out-of-time sets, a point-in-time universe, next-session fills, costs,
corporate actions and delistings, multi-seed/confidence-interval reporting, and
explicit correction for repeated search. The
[Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)
and [Deflated Sharpe Ratio](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551)
are relevant promotion diagnostics. They cannot turn a backtest into a return
guarantee.

## Actual upgrade plan

### Gate 0 — Local contracts

Required before the quarantined paid pilot:

- leakage-free analyst/committee inputs;
- closed strict schemas and citation/calculation validation;
- no tools, stateless `store=false` provider request construction;
- provider call, cost, retry, response-ID, model, and token receipts.

Those transport/mechanics requirements now exist locally. The only Gate 0/Q1
blockers are explicit call/cost authorization, external authentication, and
freezing the ten sanitized public-evidence pilot packets.

The following are not needed to test transport, but are mandatory before Q2 can
claim decision qualification or any model output can influence email:

- per-ticker action-grade market receipts;
- real source-populated `valuation_evidence_v1` receipts in the active packet;
- the 250–300 packet full-label chronological corpus;
- the real point-in-time paper performance ledger.

The minimum-size gate is not merely prose: the model registry refuses
thresholds below `250` packets, `20` issuer CIKs, `50` material transitions,
and `30` live-shadow sessions. The replay loader counts distinct CIKs and fails
closed if packet or issuer diversity is below the configured minimum.

### Gate 1 — 30-call quarantined smoke test

Use public SEC/issuer evidence and sanitized portfolio bands only. Run ten
packets through the Terra analyst, Sol proposer, and a separately requested Sol
critic (`30` physical calls total). The Sol critic validates critic protocol
and transport only; it is not an independent-family benchmark. Record exact
response IDs, resolved models, token usage, latency, refusal and incomplete
status, schema validity, citations, and costs. Do not send email or change any
canonical decision.

Each retry consumes a physical-call slot; the ceiling never expands beyond
`30`. With a conservative per-request envelope of 20K billed input tokens and
8K billed output/reasoning tokens, current list prices imply:

- ten Terra requests: at most about `$1.70`;
- twenty Sol requests: at most about `$6.80`;
- total planning envelope: `$8.50`;
- requested operator hard cap: `$10.00` before tax.

The smoke test is operational validation, not a model-quality promotion test.

### Gate 2 — Qualification replay

Build a pre-frozen `250–300` packet corpus with at least `20` issuers and
issuer/form/year/regime diversity. Include amendments, dilution, offerings,
cyber/accounting/governance cases, failed theses, acquisitions, and delistings.
The packet/issuer floors are non-lowerable across registry, loader, annotation,
and inventory paths; issuer counts exclude reserve padding beyond the selected
qualification slice.
Blind-review at least `150` chronological probes so the final set contains at
least `50` independently confirmed material positives plus retained no-change,
uncertain, reject, watch, and abstain cases.
The corpus gate separately requires at least `50` adversarial-safety probes, so
the hard minimum is `100` combined material-transition/adversarial cases.

Use issuer-held-out and out-of-time holdouts. Do not tune on the final holdout.
For public, non-identifying replay only, OpenAI documents Batch as an async eval
surface with lower cost and separate rate limits:
[Batch API](https://developers.openai.com/api/docs/guides/batch).

At three role requests per packet, qualification requires `750–900` physical
requests. Under the deliberately conservative Gate 1 token envelope, the
synchronous list-price ceiling is approximately `$212.50–$255.00`. The
official Batch API's 50% discount would reduce the estimate to approximately
`$106.25–$127.50`, but Batch persists uploaded input/output files and therefore
requires a separate retention decision. It is not silently substituted for
stateless `store=false` requests.

### Gate 2C — Independent critic challenger

This gate is forbidden until the primary OpenAI configuration has passed Gate
2 on a frozen issuer-held-out set. Then, without tuning the holdout, run a
blinded independent-classifier contract—after each provider's exact-schema
preflight—on a fixed `50`-packet challenger subset. The challenger receives the
same evidence and analyst claims but never the Sol proposal, and precommits its
own source-bound closed research class:

- Claude Fable 5 estimate at 20K input/8K output: about `$0.60` per request or
  `$30.00` for 50;
- Claude Opus 5 estimate at 20K input/8K output: about `$0.30` per request or
  `$15.00` for 50;
- Gemini 3.1 Pro Preview estimate at or below 200K input: about `$0.136` per
  request or `$6.80` for 50;
- all three candidates, only if separately authorized: about `$51.80`.

Select neither model from vendor benchmarks. Compare unique error catches,
false rejects/downgrades by class, citation/calculation validity,
counterevidence recall, calibration, latency, and cost on the same packets.
Deterministic Python compares the independent proposal with Sol and may
preserve or reduce the effective research class, never upgrade it. Gemini's
preview status prevents production selection even if its research benchmark is
useful.

### Gate 3 — Decision-quality thresholds

Promotion requires all of:

- zero policy/boundary violations;
- action precision and false-decisive-rate confidence bounds;
- material, decisive, and counterevidence recall against pre-frozen gold spans;
- exact citation and calculation validity;
- risk-coverage/selective-abstention performance;
- label/ticker/order/tone/noise counterfactual stability;
- critic unique-catch benefit exceeding false rejects/downgrades;
- statistically credible improvement over C9-only and simple baselines.

Total accuracy alone is not a promotion metric.

### Gate 4 — Point-in-time economic evaluation

Measure proposals with next-session fills only, whole-share and small-account
constraints, cash drag, dividends, splits, delistings, spreads, slippage, and
commissions. Compare with SPY total return, QQQ/XLK context, C9-only, and
no-change baselines. Report TWR, rolling CAGR, drawdown, downside risk,
turnover, attribution, and issuer/regime-clustered intervals.

The `12%–15%` rolling annualized objective is a measurement aspiration, not a
label, daily/monthly quota, or guarantee. Correct for repeated strategy search
and selection bias; strong in-sample results alone are not authority. Relevant
background includes the literature on backtest overfitting and deflated Sharpe
ratios: [Bailey et al. working paper](https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf).

### Gate 5 — 30–60 completed-session live shadow

Run after each completed market session and on material SEC/issuer events.
Compare model, critic, and C9 without email influence. Require stable latency,
cost, data finality, corporate-action reconciliation, and no cross-ticker
unlocking.

### Gate 6 — Reduced-review advisory publication

Only after Gates 0–5, including Gate 2C, pass:

- a matching, current, fully validated artifact may automatically supply the
  decisive email headline and evidence section;
- normal HOLD/WATCH and fully agreed decisions do not require daily manual
  semantic review;
- ABSTAIN, model/critic disagreement, stale data, a new model/prompt/schema,
  corporate actions, large valuation shocks, and boundary failures route to
  exception review;
- any real buy/sell/trim/exit remains a manual action outside Phase 5R.

This reduces routine review while preserving review where the evidence says it
matters. NIST's AI RMF likewise emphasizes documented roles, measurement, and
lifecycle governance rather than treating human oversight as a single binary:
[NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework).

## Authority matrix

| Component | May interpret evidence | May propose buy/hold/trim/exit research class | May unlock class by itself | May publish after promotion | May execute |
| --- | ---: | ---: | ---: | ---: | ---: |
| Evidence analyst | yes | no | no | no | no |
| Decision committee | yes | yes | no | no | no |
| Proposal-aware critic | yes | approve unchanged, revise, or reject | no | no | no |
| Blinded external challenger (future) | yes | yes, without seeing Sol's proposal | no | no | no |
| Deterministic valuation/market/risk/C9 adjudicator | no | maps allowed result | no; only the full intersection may authorize an effective research class | authorizes artifact only; does not publish | no |
| Email renderer | no | no | no | yes, matching validated artifact only | no |
| Broker/order path | not present | not present | not present | not present | not present |

## External inputs still required

No secret should be pasted into chat, committed, logged, or placed in a
LaunchAgent.

1. A real SEC-compliant User-Agent contact string, such as project name plus a
   monitored email address, before the replay acquisition pilot.
2. Confirmation that an OpenAI project with GPT-5.6 Terra/Sol access and
   authentication already exists outside this repository.
3. Explicit authorization for exactly `30` physical Q1 requests, the
   20K-input/8K-output planning envelope, and a `$10.00` hard cap. Credential
   availability is not spend authorization.
4. Two independent reviewers plus an adjudicator for at least `150`
   chronological probes. Reducing routine operational review does not remove
   this one-time qualification-label requirement.
5. A licensed read-only market-data source (Massive is the current first
   candidate) and confirmation that the selected plan permits local raw-receipt
   and corporate-action research retention.
6. Explicit authorization for D3's SEC/network acquisition after the
   User-Agent is configured, plus an operator storage budget. Current planning
   is `791–2,701` requests, about `1.12 GB` typical, and a deliberately
   conservative `72.94 GB` upper bound.
7. After issuer-held-out Gate 2 only: a user choice among Claude Fable 5
   (maximum rigor), Claude Opus 5 (lower-cost Anthropic control), and Gemini
   3.1 Pro Preview (preview-only alternative), external provider authentication,
   data-region and retention review, and a separate challenger cost cap. No
   challenger credential is needed now.
8. Separate approval before using OpenAI Batch, because uploaded request and
   output files have separate object-storage and retention behavior from
   stateless `store=false` Responses calls.

OpenAI documents that `/v1/responses` data are not used for training and that
default abuse-monitoring retention may be up to 30 days; response application
state also depends on `store` and account controls. Phase 5R therefore uses
`store=false`, public evidence, and sanitized bands until stricter controls are
confirmed: [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data).

All cost figures in this report are planning ceilings based on public list
prices checked on `2026-07-25`. They exclude taxes, retries beyond the stated
physical-call ceiling, long-context/data-region multipliers, and later provider
price changes. Actual usage receipts and billing exports must be reconciled
before another cost authorization.

## What this research does not claim

- It does not claim that GPT-5.6, an open-source finance model, or a multi-agent
  debate will achieve the return objective.
- It does not claim that the current offline fixtures prove good decisions.
- It does not claim that a provider name makes data or output action-grade.
- It does not authorize a paid model call, email, broker connection, order, or
  canonical decision change.
