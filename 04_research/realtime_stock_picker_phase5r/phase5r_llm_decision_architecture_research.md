# Phase 5R LLM Decision Architecture Research

Date: 2026-07-24  
Mode: applied primary-source architecture and open-source dependency research

Decision: proceed to a gated shadow implementation; do not replace C9 with an
unconstrained model

Portfolio research objective: rolling five-year annualized net total return of
12%–15%. The exact monthly compound equivalent is 0.9489%–1.1715%; 15%–20% is
an excellent calendar-year range, not an annual quota or guarantee. Model
quality and portfolio returns remain separate evaluation axes.

## Executive conclusion

The optimal upgrade is a hybrid decision system:

1. retain SEC as the authoritative fundamental source;
2. replace `yfinance` as the sole action-grade price source with a licensed
   market-data API and use provider agreement as a quality gate;
3. add a model-based evidence analyst for filing language, guidance, competitive
   changes, and thesis deltas;
4. add a stronger model-based investment committee that proposes a decisive
   research action;
5. require an adversarial critic for any proposed ADD, TRIM, or EXIT transition;
6. leave arithmetic, portfolio limits, eligibility thresholds, duplicate-email
   protection, and final authorization in deterministic code; and
7. run every provider call in a separate asynchronous shadow worker, never
   synchronously inside refresh, C9, the deterministic decision pipeline, or the
   sender.

The model should receive more **read-only evidence**, not more operational
authority. It may propose one of:

- `paper_trade_candidate`
- `real_trade_candidate`
- `hold_existing`
- `trim_review`
- `exit_review`
- `watchlist`
- `reject`
- `abstain`

These are decisive research classifications. They are not buy/sell commands,
orders, or execution authorization.

The deterministic daily decision and email remain canonical and available when
the shadow worker is offline, delayed, uncredentialed, or rejected by a
validator. The implemented worker snapshots the newest local packet and
deduplicates by packet, model, prompt, schema, and runtime-code hashes; API
availability is not a dependency of the daily system. It does not yet keep an
immutable historical queue and cannot collect states while the Mac is off.

## Research question and method

**Research question:** What model-and-data architecture can materially improve
the factuality, semantic depth, numerical reliability, and action clarity of
Phase 5R's daily equity research decisions without creating an opaque or
automated trading system?

The assessment used:

- direct inspection of the active B2, SEC-evidence, C9, daily-composer, and
  sender paths;
- current official model/API documentation;
- official SEC, NIST, and FINRA guidance;
- peer-reviewed financial reasoning and financial-LLM benchmark research;
- an adversarial review of failure modes, including correlated model errors,
  source hallucination, numerical mistakes, temporal leakage, prompt injection,
  and unstable recommendations.

## Findings

### 1. The current limitation is architectural, not just model quality

B2 presently relies on `yfinance` for one-year daily market data. The SEC layer
uses official submissions and XBRL company facts, but extracts a relatively
narrow set of standardized numeric tags and lightweight form/item signals. C9
then applies deterministic weights and thresholds. This is safe and
reproducible, but it does not deeply interpret:

- changes in management guidance;
- risk-factor and accounting-policy changes;
- unit economics and operating leverage;
- competitive positioning;
- capital allocation and dilution;
- whether new evidence strengthens or invalidates the prior long-term thesis;
- contradictory evidence across filing text, tables, and prior statements.

A frontier model can improve those semantic tasks, but a model cannot repair
stale, incomplete, or weakly sourced inputs. Data provenance and deterministic
validation must be upgraded at the same time.

#### Provenance-first SEC prerequisite

SEC provenance must pass before the first live model/API request. The canonical
object is the raw official SEC artifact, not a parser's normalized text. For
each artifact, retain accession number, form, accepted timestamp, official URL,
retrieval time, and raw SHA-256. For each derivative, retain parser name/version,
normalized SHA-256, form item/heading, exact character span or page/bounding
box, and normalized-span hash. For each XBRL fact, retain concept, value, unit,
period, dimensions, accession, and its filing/table locator.

Every model claim must cite an immutable source ID resolving to those fields.
EdgarTools may produce the primary typed structure and `sec-parser` may
cross-check a sampled corpus, but both outputs remain derivatives of the raw SEC
record. Missing raw artifacts, unresolved spans, parser disagreement, or failed
XBRL reconciliation make the affected evidence ineligible and force
HOLD/ABSTAIN before a provider task is queued.

### 2. Financial numerical reasoning remains a known weak point

Peer-reviewed benchmarks consistently show that financial documents combine
text, tables, heterogeneous units, and multi-step calculations in ways that
remain difficult for language models:

- [FinQA](https://aclanthology.org/2021.emnlp-main.300/) established expert-built
  financial questions with executable reasoning programs and found a large
  gap between then-current models and expert performance.
- [ConvFinQA](https://aclanthology.org/2022.emnlp-main.421/) demonstrated the
  difficulty of long-range, multi-step conversational financial reasoning.
- [PIXIU](https://proceedings.neurips.cc/paper_files/paper/2023/hash/6a386d703b50f1cf1f61ab02a15967bb-Abstract-Datasets_and_Benchmarks.html)
  documented uneven strengths and weaknesses across financial tasks.
- [FinBen](https://proceedings.neurips.cc/paper_files/paper/2024/hash/adb1d9fa8be4576d28703b396b82ba1b-Abstract-Datasets_and_Benchmarks_Track.html)
  found that evaluated models were stronger at extraction and textual analysis
  than at advanced reasoning, forecasting, and other complex tasks.
- [FinanceReasoning](https://aclanthology.org/2025.acl-long.766/) found that even
  strong reasoning models still faced numerical-precision problems and that
  combining a reasoner with executable programs improved results.
- [SECQUE](https://aclanthology.org/2025.gem-1.16/) and
  [DocFinQA](https://aclanthology.org/2024.acl-short.42/) provide relevant
  real-world and long-context evaluation surfaces.

The design implication is decisive: the LLM should identify the calculation,
inputs, source spans, and intended formula; Python should perform and verify the
calculation. A prose answer from a model must never become the numeric source of
truth.

### 3. A model may help interpret information, but direct return prediction is
not a sufficient decision engine

Research reports both useful signals and material bias. For example,
[Lopez-Lira and Tang](https://arxiv.org/abs/2304.07619) report out-of-sample
return predictability from LLM interpretation of news headlines. Conversely,
[Chen et al.](https://doi.org/10.2139/ssrn.4941906) report trend extrapolation,
optimism, and miscalibrated intervals in LLM stock-return forecasts.

Therefore Phase 5R should use an LLM primarily to:

- interpret evidence;
- compare evidence with the prior thesis;
- surface contradictions;
- construct explicit bull/base/bear cases;
- propose a research action and conditions that would falsify it.

It should not use a model-generated next-day return or price target as the
decisive signal.

The return objective therefore belongs in portfolio constraints and
walk-forward measurement, not in provider self-scoring. Daily evidence may
change confidence, but weak monthly performance must not force a trade and a
strong year must not relax risk controls. The frozen measurement policy is
`00_project_control/phase5r_return_objective_policy.md`.

### 4. Recommended primary model and API

Use strict Structured Outputs through a narrow provider boundary. The first
implemented replay transport is a pinned, externally authenticated,
tool-disabled Codex CLI process because repository policy forbids reading API
credentials. A direct injected-client OpenAI Responses adapter is implemented
but disabled; live use and any Batch path still require an equally narrow
external credential boundary and explicit approval.

| Workload | Initial model | Setting | Reason |
| --- | --- | --- | --- |
| Filing and evidence extraction | `gpt-5.6-terra` | `reasoning.effort=medium` | Stronger cost/quality balance for repeatable structured extraction |
| Thesis update and action proposal | `gpt-5.6-sol` | `reasoning.effort=high` | Frontier model for the smaller set of high-value decisions |
| Proposal-aware critic | `gpt-5.6-sol` | separate stateless prompt, `high`; receives the committee proposal | Runs on every packet during evaluation/shadow so catch and false-downgrade rates are measurable; it is not a blinded or cross-family control |

As of 2026-07-24, OpenAI identifies GPT-5.6 Sol as the flagship model and Terra
as the intelligence/cost balance. Both support the Responses API, reasoning,
function calling, and Structured Outputs. The model family has a 1.05M-token
context window, but the implementation should still send compact, source-bound
evidence packets rather than entire uncontrolled archives. See the
[model guide](https://developers.openai.com/api/docs/guides/latest-model),
[model comparison](https://developers.openai.com/api/docs/models/compare),
[Responses API guidance](https://developers.openai.com/api/docs/guides/migrate-to-responses),
and [Structured Outputs guidance](https://developers.openai.com/api/docs/guides/structured-outputs).

Do not use `chat-latest` or an untracked convenience alias. Every run must
record the requested exact model ID, request settings, prompt version, schema
version, source-packet hash, timestamp, and local input/output hashes. A direct
Responses API transport must additionally record its provider-native response
ID, resolved model/version metadata, and token usage. The exploratory Codex CLI
bridge does not expose authoritative response IDs or billing usage; that known
provenance gap is one reason it cannot qualify advisory influence.

Keep a thin local `ModelProvider` interface. The implemented adapter pins and
rehashes the native Codex executable before every launch, runs in an ephemeral
read-only directory with model tools disabled and a minimal environment, and
records hashes rather than provider stdout/stderr content. A future official
OpenAI SDK adapter must provide equivalent success-status, refusal, incomplete,
schema, citation, numeric, and policy checks. Do not silently repair or retry a
semantically invalid finance answer into apparent validity.

The live-shadow implementation therefore persists intent before provider
construction, stores one immutable result receipt per role, and reuses every
successful role independently. Schema, semantic, citation, evidence, and
policy-invalid results terminate the exact run; only narrowly classified
transport/process failures may retry. A final hash-bound completion manifest,
not the mere presence of a decision file, is the completed-run authority.
Replay evaluation separately discloses every physical attempt and keeps its
global call and operator-estimated cost ceilings cumulative across resumes.

OpenAI documents that API inputs and outputs are not used for model training
unless the customer opts in. It also documents that default abuse-monitoring
logs may retain customer content for up to 30 days and that Zero Data Retention
requires approval. The implementation should therefore transmit only public
evidence and coarse portfolio percentages unless a stricter retention control
is confirmed:
[OpenAI API data controls](https://developers.openai.com/api/docs/guides/your-data).
For bulk replay, the [Batch API FAQ](https://help.openai.com/en/articles/9197833-batch-api-faq%3F.gz)
documents a 50% discount but explicitly excludes Batch from Zero Data
Retention. Batch is therefore appropriate only for public evidence and
sanitized portfolio bands, never private or identifying inputs.

### 5. Independent model option

Create a vendor-neutral critic interface, but do not make a second provider a
day-one dependency. During evaluation, compare the same frozen decision packet
with an independent model such as maximum-capability Claude Fable 5, with
Claude Opus 5 as a lower-cost control. Anthropic documents its current model IDs
as pinned snapshots, which is useful for reproducibility:
[Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
and [model ID/versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions).

Promote a cross-vendor critic only if the project eval shows that it catches
material errors missed by the primary analyst and its incremental value
justifies added cost, data governance, and outage complexity. Disagreement must
produce `abstain` or human review, never an arbitrary tie-break.

### 6. Recommended data API upgrade

Keep official SEC filing documents and SEC XBRL as the authoritative fundamental
record. SEC states that the Submissions API is typically updated in under a
second and XBRL APIs in under a minute; the APIs require no key:
[SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces).

For market data, evaluate Massive as the primary action-grade provider. Its
official documentation describes U.S. equity aggregates, trades, NBBO quotes,
corporate actions, reference identifiers, and data sourced through the SIPs:
[Massive Stocks REST API](https://massive.com/docs/rest/stocks). Use adjusted and
unadjusted bars explicitly and validate splits/dividends before comparing
historical prices.

Recommended source roles:

| Source | Role | Can be sole action trigger? |
| --- | --- | --- |
| SEC filing HTML/inline XBRL | Official facts and management disclosures | Yes, for a research review trigger |
| SEC Company Facts | Structured numeric cross-check | No; reconcile to official filing |
| Company IR | Official release, presentation, call transcript if hosted by issuer | Yes, when provenance is verified |
| Massive SIP-derived market data | Price, volume, session, corporate actions | Yes, after freshness and quality checks |
| `yfinance` | Temporary comparison/fallback | No for action-changing decisions |
| Secondary news/aggregators | Discovery and context | No |

### 7. Open-source component audit

This audit used the projects' primary repositories and license files, inspected
on 2026-07-24. Recent activity is useful maintenance evidence, not proof of
fitness or safety. No package was installed and no portfolio data was sent to a
third party.

#### Adopt

| Project | Primary-source activity and license | Narrow use in Phase 5R | Controls |
| --- | --- | --- | --- |
| [EdgarTools](https://github.com/dgunning/edgartools) | Active; repository pushed 2026-07-19 and reports v5.43.0; [MIT](https://github.com/dgunning/edgartools/blob/main/LICENSE.txt) | Typed SEC filings, sections, and XBRL behind the raw SEC archive | Do not enable agent/MCP surfaces; record parser version; raw SEC artifact remains canonical |
| [Docling](https://github.com/docling-project/docling) | Active; repository pushed 2026-07-24 and reports v2.115.0; [MIT](https://github.com/docling-project/docling/blob/main/LICENSE) | Issuer PDFs, image-heavy releases, and presentations | SEC HTML/iXBRL remains preferred; preserve page/bounding-box provenance and reconcile critical tables to raw/XBRL because document-table extraction can fail |
| [OpenAI Python SDK](https://github.com/openai/openai-python) | Active; repository pushed 2026-07-24 and reports v2.48.0; [Apache-2.0](https://github.com/openai/openai-python/blob/main/LICENSE) | Deferred direct Responses/Batch client | Repository policy currently forbids reading provider credentials; evaluate only behind a separately approved external credential boundary |
| [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) | Active; repository pushed 2026-07-24; [MIT](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/LICENSE) | Offline/CI replay and adversarial evaluation harness | Project deterministic scorers, frozen packets, and promotion policy remain authoritative |

#### Shadow-test or defer

| Project | License | Decision and reason |
| --- | --- | --- |
| [sec-parser](https://github.com/alphanome-ai/sec-parser) | [MIT](https://github.com/alphanome-ai/sec-parser/blob/main/LICENSE) | Shadow-test on a sampled parser-agreement corpus only; its repository was active through 2026-06-25, but a second parser is a cross-check, not another authority |
| [PydanticAI](https://github.com/pydantic/pydantic-ai) | [MIT](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE) | Defer. It is active and typed, but rapid release churn and agent/tool surfaces add unnecessary complexity to a non-agent shadow worker |
| [Instructor](https://github.com/567-labs/instructor) | [MIT](https://github.com/567-labs/instructor/blob/main/LICENSE) | Defer. Its structured-output convenience is useful, but automatic repair retries can conceal an initially invalid finance response; direct SDK plus fail-closed local validation is easier to audit |

#### Evaluation assets

| Asset | License evidence | Permitted planned reuse |
| --- | --- | --- |
| [FinQA](https://github.com/czyssrs/FinQA) and [ConvFinQA](https://github.com/czyssrs/ConvFinQA) | [MIT](https://github.com/czyssrs/FinQA/blob/main/LICENSE) and [MIT](https://github.com/czyssrs/ConvFinQA/blob/main/LICENSE) | Executable financial arithmetic and multi-step text/table fixtures |
| [TAT-QA](https://github.com/NExTplusplus/TAT-QA) | Repository code is [MIT](https://github.com/NExTplusplus/TAT-QA/blob/master/LICENSE); README identifies the dataset as CC BY 4.0 | Attributed table-and-text numerical cases after recording the dataset license |
| [FinReasoning](https://github.com/TongjiFinLab/FinReasoning) | [Apache-2.0](https://github.com/TongjiFinLab/FinReasoning/blob/main/LICENSE) code; dataset is CC BY-NC-SA 4.0 with third-party restrictions | Reuse the semantic-consistency, data-alignment, and deep-insight evaluation taxonomy; do not vendor the dataset without an asset-level review |
| [FinRAGBench-V](https://github.com/zhaosuifeng/FinRAGBench-V) | [Apache-2.0](https://github.com/zhaosuifeng/FinRAGBench-V/blob/main/LICENSE) | Optional visual/page-level citation tests |
| [FinanceRAG](https://github.com/linq-rag/FinanceRAG) | [MIT](https://github.com/linq-rag/FinanceRAG/blob/main/LICENSE); small/static repository | Reuse qrels and retrieval-evaluation conventions, not its activity as evidence of production readiness |

These public datasets supplement but do not replace project-specific,
time-isolated replay. A repository license does not automatically license every
bundled upstream dataset, PDF, or third-party artifact.

#### Avoid initially or do not vendor

| Project | License/status | Reason |
| --- | --- | --- |
| [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT), [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot), [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | [MIT](https://github.com/AI4Finance-Foundation/FinGPT/blob/master/LICENSE); [Apache-2.0](https://github.com/AI4Finance-Foundation/FinRobot/blob/master/LICENSE); [MIT](https://github.com/AI4Finance-Foundation/FinRL/blob/master/LICENSE) | Active projects, but autonomous agents, trading strategies, or reinforcement learning do not solve source-citation safety and conflict with this repository's non-execution boundary |
| [InvestorBench](https://github.com/felis33/INVESTOR-BENCH) | [MIT](https://github.com/felis33/INVESTOR-BENCH/blob/main/LICENSE); small repository | Historical trading returns do not establish factuality, temporal integrity, calibration, or policy safety |
| [PageIndex](https://github.com/VectifyAI/PageIndex) | [MIT](https://github.com/VectifyAI/PageIndex/blob/main/LICENSE); active | Its retrieval concepts may inform a bake-off, but self-reported FinanceBench results are not sufficient promotion evidence |
| [Haystack](https://github.com/deepset-ai/haystack) and [LlamaIndex](https://github.com/run-llama/llama_index) | [Apache-2.0](https://github.com/deepset-ai/haystack/blob/main/LICENSE); [MIT](https://github.com/run-llama/llama_index/blob/main/LICENSE) | Mature generic RAG/agent frameworks, but unnecessary orchestration and tool surfaces for a sealed-packet worker |
| [OpenBB](https://github.com/OpenBB-finance/OpenBB) | [AGPL-3.0](https://github.com/OpenBB-finance/OpenBB/blob/develop/LICENSE) | Broad data-platform scope and stronger copyleft boundary are unnecessary for the narrow provider/provenance problem |
| [LiteLLM](https://github.com/BerriAI/litellm) | [Mixed repository license file](https://github.com/BerriAI/litellm/blob/litellm_internal_staging/LICENSE): MIT outside listed enterprise files | A proxy is not needed for the initial provider. A [compromised PyPI release incident](https://github.com/BerriAI/litellm/issues/24518) and a [critical SQL-injection advisory](https://github.com/BerriAI/litellm/security/advisories/GHSA-r75f-5x8p-qvmc) increase the supply-chain/security case for the direct SDK |
| [FinBen](https://github.com/The-FinAI/FinBen) | README says MIT, but the repository has no reliably detected root license and bundles upstream datasets | Use taxonomy only; do not copy or vendor without asset-by-asset provenance and license review |
| [FinanceBench](https://github.com/patronus-ai/financebench) | No reliably detected repository license | Do not copy or vendor; a benchmark claim does not grant reuse rights |
| [EDGAR Crawler](https://github.com/lefterisloukas/edgar-crawler) | [GPL-3.0](https://github.com/lefterisloukas/edgar-crawler/blob/main/LICENSE); older project | Redundant with direct official SEC acquisition plus the selected permissive parser |

### 8. Separate shadow architecture and activation blocker

The original idea of making model calls “event-first” inside the refresh path is
rejected. Event-first remains the task-selection policy, but the call is made
only by a separate worker:

```text
deterministic refresh -> canonical C9/email (unchanged)
         |
         +-> newest sealed packet snapshot
                       |
                       v
             asynchronous shadow worker
                       |
             analyst / committee / critic
                       |
             local validators and audit
                       |
             non-canonical shadow artifact
```

The refresh process needs no provider credential and makes no external model
network request. The worker may run later against the newest locally available
packet. A provider outage, quota failure, refusal, incomplete output, validation
error, or computer shutdown cannot delay or fail deterministic refresh or
email. A shutdown can, however, lose an intraday state that was never fetched.
Even after a future promotion, email may consume only a previously completed,
validated artifact matching the current packet/session; otherwise it uses the
deterministic result.

The project `AGENTS.md` also creates a deliberate runtime blocker: it permits
explicit public-research network access but prohibits storing credentials in the
repository. A live provider test cannot be activated automatically by this
research or by code alone. The user must later:

1. keep provider authentication outside the repository (the selected first
   transport already delegates to the externally logged-in, pinned Codex CLI);
   and
2. explicitly authorize the capped outbound provider replay.

The implementation must not request, read, print, log, or persist that secret.
Until both steps occur, the project can complete schemas, fixtures, mock/replay,
provenance, worker, and offline evaluations, but real shadow model calls
remain blocked. The canonical deterministic daily workflow remains active.

### 9. Governance is part of model quality

NIST's AI RMF calls for scoped use, documented human-AI roles, testing,
validation, measurement, monitoring, and safe failure:
[NIST AI RMF Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/).
FINRA's 2026 GenAI report similarly emphasizes governance, testing, monitoring
prompts and outputs, recording model versions, and human-in-the-loop validation:
[FINRA GenAI report](https://www.finra.org/rules-guidance/guidance/reports/2026-finra-annual-regulatory-oversight-report/gen-ai).

For this project, safe failure means:

- invalid or unsupported model output becomes `abstain`;
- an API outage leaves the deterministic daily system operating in HOLD mode;
- a model or prompt change cannot enter production before replay evaluation;
- no model receives SMTP secrets, personal identity, broker credentials, or
  execution tools;
- no model can directly edit canonical account state or send email.

Promotion is not a subjective demonstration. It requires at least 250 immutable
time-isolated replay packets across at least 20 issuers, including at least 50
material-transition cases; 30–60 completed U.S. market sessions of separate
live shadow observation; every factual, numeric, citation, stability, and
boundary threshold in the project-control plan; and zero policy violations.
One policy violation is an automatic no-go regardless of average benchmark
score.

### 10. A source pilot is not qualification

The safest next corpus step is a 30-packet **source-materialization pilot**, not
a provider demonstration. It should expose exhibit discovery failures, missing
accession-level XBRL reconciliation, market-license or point-in-time gaps,
temporal leakage, cache-reuse defects, and realistic storage before hundreds of
public-source requests are made. No model/API call is needed for that pilot,
and a successful pilot does not establish decision quality.

Qualification is a separate frozen dataset of at least 250 time-isolated
packets across at least 20 issuers, with at least 50 independently reviewed
material transitions, explicit negative/no-change cases, and a predeclared
representative cohort distributed across filing forms, years, sectors, and
market regimes. The current ledger's six issuers can test mechanics but cannot
support a broad robustness claim. Only after the
qualification sources and annotations are frozen should capped provider replay
begin; the later provider smoke test must not be confused with the earlier
source pilot.

`inventory_phase5r_llm_replay_corpus.py` implements the local preflight for
both stages. It makes zero requests and writes no corpus file. Its deterministic
stdout report binds the evidence-ledger and SEC acceptance-index hashes, freezes
the selected accessions and distributions, itemizes missing primary,
filing-index, exhibit, XBRL, and market artifacts per accession, and gives
request/storage ranges. This closes the planning-information gap without
requiring an SEC User-Agent, provider authentication, or a market credential.

## Final recommendation

Proceed with a separate, asynchronous shadow-only hybrid upgrade. Keep
provenance-first raw SEC artifacts authoritative; evaluate EdgarTools behind
them and Docling only where PDF layout requires it. Use the implemented pinned
external CLI bridge for the first controlled provider replay, and evaluate the
official OpenAI Python SDK or Batch API only behind a separately approved
credential boundary. Inspect AI may later orchestrate evaluations while
deterministic project scorers remain authoritative. Use GPT-5.6 Terra for
structured evidence extraction and GPT-5.6 Sol for the thesis/action committee,
subject to project-specific model comparison. Add an independent critic, move
price quality to a licensed market-data provider, and keep deterministic C9
rules as the final policy gate.

Do not place any model/API request in refresh, C9, the deterministic decision
pipeline, or the sender. Do not promote the model layer until at least 250
time-isolated replay packets across at least 20 issuers, at least 50
material-transition cases, 30–60 live shadow sessions, all acceptance gates,
and zero policy violations pass.
Credential and provider-network activation remain a separate explicit user
action outside the repository.

## Limitations

- Vendor claims and model specifications change; model selection must be
  re-evaluated against the project dataset rather than accepted from general
  benchmarks.
- No public benchmark exactly matches this portfolio, its horizons, its source
  hierarchy, or its action labels.
- Historical replay can overstate quality if evidence timestamps or revised
  filings leak future information.
- A model can improve research quality without creating reliable excess
  returns. The two outcomes must be measured separately.

## AI disclosure

This report was produced with AI-assisted code inspection and web research.
External claims were limited to linked official documentation and primary
research papers. No model API was called on portfolio data, no email was sent,
and no broker or order system was accessed.
