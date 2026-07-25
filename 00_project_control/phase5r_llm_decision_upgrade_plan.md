# Phase 5R Rigorous Model and Decision API Upgrade Plan

Date: 2026-07-24  
Status: offline architecture implemented and fail-closed; real SEC replay
materialization, independently reviewed transition labels, provider replay, and
explicit external-inference activation remain pending

Target: improve decision robustness and decisiveness without automated trading

## 1. Outcome

Add a source-grounded model layer that is allowed to make a clear **research
decision** about whether the portfolio should consider adding, holding,
trimming, or exiting a position. The layer will not be allowed to place an
order, connect to a broker, modify the canonical account, or bypass C9 policy.

The target email headline becomes one of:

- `决定性建议：进入新增仓位复核`
- `决定性建议：进入现有仓位增持复核`
- `决定性建议：继续持有`
- `决定性建议：进入减仓复核`
- `决定性建议：进入退出复核`
- `决定性建议：证据不足，暂不改变仓位`

The corresponding closed machine labels are:

`reject`, `watchlist`, `hold_existing`, `paper_trade_candidate`,
`real_trade_candidate`, `trim_review`, `exit_review`, and `abstain`.

The words “复核” are a control boundary, not softened language: the system will
state what it concludes should be reviewed, why, and what evidence would reverse
the conclusion. Real action remains manual and outside this repository.

## 2. Architecture decision

```text
SEC + issuer IR + licensed market data
                  |
                  v
       deterministic acquisition
       provenance / hashes / time gates
                  |
                  v
       canonical deterministic packet + C9
                  |
          +-------+--------+
          |                |
          v                v
 canonical daily       sealed packet manifest
 decision/email        + local queue/spool
 (unchanged)                |
                             v
                  separate asynchronous shadow worker
                  (not called by refresh/C9/sender)
                             |
                  +----------+----------+
                  |                     |
                  v                     v
          Evidence Analyst        Numeric Engine
          GPT-5.6 Terra           Python / C9 rules
                  |                     |
                  +----------+----------+
                             v
                  Thesis & Action Committee
                  GPT-5.6 Sol
                             |
                    action transition?
                       /           \
                     no             yes
                     |               |
                     |               v
                     |       Adversarial Critic
                     |       independent prompt
                     +---------------+
                             |
                             v
                  schema + citation + policy validator
                             |
                             v
                  shadow artifacts and audit only
```

The model/API path is a separate, asynchronous shadow system. It is not invoked
from `refresh_phase5r_daily_evidence.py`, C9, the deterministic decision
pipeline, or the sender, and it is not a launchd dependency of those jobs. The
deterministic workflow writes an immutable manifest to a local spool and
continues. A later worker may catch up idempotently by packet hash. Provider
latency, quota, credential failure, or outage therefore cannot delay or fail
refresh, C9, or the daily email.

Before promotion, shadow output is never canonical. After promotion, the email
may render only a previously completed, locally validated artifact for the
matching packet/session; a missing, stale, refused, incomplete, or invalid
artifact falls back to the canonical deterministic decision. No model appears
inside the SMTP sender and no model can authorize execution.

## 3. Model and API configuration

### 3.1 Initial evaluation candidates

| Component | Model | API | Initial setting |
| --- | --- | --- | --- |
| Evidence extraction | `gpt-5.6-terra` | pinned, externally authenticated Codex CLI bridge for the first replay | medium reasoning |
| Thesis and action | `gpt-5.6-sol` | same isolated bridge, separate stateless request | high reasoning |
| Action critic | `gpt-5.6-sol` | same isolated bridge, independent prompt and request | high reasoning |
| Direct Responses API / Batch experiment | same pinned models | external managed adapter only | disabled until separately authorized and replay-equivalent |
| Optional independent challenger | Claude Opus 5 or successor | provider adapter | evaluation only |

Use strict Structured Outputs with a versioned JSON Schema. Do not let models
call web search, shell, email, filesystem, account, or execution tools. Retrieval
and computation occur before the request and are visible in the evidence packet.

### 3.2 Model registry

Create a local, non-secret registry with:

- provider;
- exact model ID;
- role;
- reasoning setting;
- prompt version;
- output-schema version;
- allowed input classes;
- prohibited data classes;
- evaluation version and pass date;
- activation state;
- maximum input/output tokens;
- per-day and per-run cost ceilings;
- failover policy.

An alias or model change is a configuration change that automatically returns
the model layer to shadow mode until replay tests pass.

### 3.3 Privacy and credentials

Only public source material and sanitized portfolio attributes may leave the
machine. The model may receive position weight, risk cap, cash band, holding
horizon, and thesis history, but not name, email address, account number,
broker, credentials, SMTP configuration, or exact personal identifiers.

OpenAI states that API data is not used to train its models unless the customer
opts in, but default abuse-monitoring logs may retain prompts and responses for
up to 30 days. Therefore the design must assume 30-day provider retention unless
the account is approved and configured for Zero Data Retention. If Zero Data
Retention is unavailable, send percentages and categorical bands rather than
exact personal dollar values. See
https://developers.openai.com/api/docs/guides/your-data.

Provider authentication must remain outside the repository. It must never
appear in a plist, report, prompt log, exception, command output, or test
fixture. The implemented transport delegates authentication to a pinned
external Codex CLI executable and never reads the credential. A direct API
transport may be evaluated later only if an equally narrow external credential
boundary is approved.

The repository `AGENTS.md` creates an intentional activation blocker: public
research network access may be used only explicitly, while credentials may not
be stored in the repository. A live provider call therefore requires explicit
authorization for outbound inference and a pre-existing external authentication
session. The implementation must not request, inspect, echo, or persist that
authentication material. Until authorization and replay gates pass, only
schemas, local fixtures, mock/replay tests, packet creation, and offline
validation can run. Real shadow execution remains disabled while the
deterministic daily workflow stays active.

### 3.4 Dependency decision

Use a small, auditable dependency surface. The detailed evidence and license
notes are in the companion research report.

| Decision | Component and primary source | License | Planned use |
| --- | --- | --- | --- |
| Adopt | [EdgarTools](https://github.com/dgunning/edgartools) ([license](https://github.com/dgunning/edgartools/blob/main/LICENSE.txt)) | MIT | Typed SEC filing/XBRL/section parser behind the raw SEC archive; do not enable its agent/MCP surface |
| Adopt | [Docling](https://github.com/docling-project/docling) ([license](https://github.com/docling-project/docling/blob/main/LICENSE)) | MIT | Issuer PDFs and image-heavy documents only, preserving page/bounding-box provenance |
| Defer pending policy/credential design | [OpenAI Python SDK](https://github.com/openai/openai-python) ([license](https://github.com/openai/openai-python/blob/main/LICENSE)) | Apache-2.0 | A direct Responses/Batch adapter is useful, but this repository is not permitted to read provider credentials; the implemented first transport is a pinned, externally authenticated, tool-disabled CLI bridge |
| Adopt | [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) ([license](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/LICENSE)) | MIT | Offline/CI evaluation harness; deterministic project scorers remain authoritative |
| Shadow-test | [sec-parser](https://github.com/alphanome-ai/sec-parser) ([license](https://github.com/alphanome-ai/sec-parser/blob/main/LICENSE)) | MIT | Sampled parser-agreement checks only |
| Defer | [PydanticAI](https://github.com/pydantic/pydantic-ai) ([license](https://github.com/pydantic/pydantic-ai/blob/main/LICENSE)) | MIT | Useful typed-agent framework, but rapid churn and tool surfaces are unnecessary for a non-agent worker |
| Defer | [Instructor](https://github.com/567-labs/instructor) ([license](https://github.com/567-labs/instructor/blob/main/LICENSE)) | MIT | Automatic repair retries could obscure invalid finance outputs; fail closed instead |
| Evaluate assets | [FinQA](https://github.com/czyssrs/FinQA), [ConvFinQA](https://github.com/czyssrs/ConvFinQA), [TAT-QA](https://github.com/NExTplusplus/TAT-QA) | MIT code; TAT-QA dataset CC BY 4.0 | External numeric/text/table fixtures with attribution and license review |
| Evaluate assets | [FinReasoning](https://github.com/TongjiFinLab/FinReasoning), [FinRAGBench-V](https://github.com/zhaosuifeng/FinRAGBench-V), [FinanceRAG](https://github.com/linq-rag/FinanceRAG) | Apache-2.0 code / restricted data; Apache-2.0; MIT | Reuse evaluation taxonomies, page-citation cases, and qrels conventions; do not vendor restricted data |
| Avoid | [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT), [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot), [FinRL](https://github.com/AI4Finance-Foundation/FinRL) | MIT; Apache-2.0; MIT | Autonomous-agent/RL/trading scope conflicts with the evidence-review boundary |
| Avoid | [InvestorBench](https://github.com/felis33/INVESTOR-BENCH), [PageIndex](https://github.com/VectifyAI/PageIndex) | MIT; MIT | Return backtests or self-reported retrieval results do not establish factuality or policy safety |
| Avoid initially | [Haystack](https://github.com/deepset-ai/haystack), [LlamaIndex](https://github.com/run-llama/llama_index), [OpenBB](https://github.com/OpenBB-finance/OpenBB) | Apache-2.0; MIT; AGPL-3.0 | Generic orchestration/broad finance platforms add unnecessary complexity and, for OpenBB, a stronger copyleft boundary |
| Avoid initially | [LiteLLM](https://github.com/BerriAI/litellm) ([incident](https://github.com/BerriAI/litellm/issues/24518), [security advisory](https://github.com/BerriAI/litellm/security/advisories/GHSA-r75f-5x8p-qvmc)) | MIT outside enterprise files | Adds a proxy and supply-chain surface; recent compromised-package incident and critical advisory argue for a direct SDK |
| Do not vendor | [FinBen](https://github.com/The-FinAI/FinBen), [FinanceBench](https://github.com/patronus-ai/financebench) | License metadata is absent or ambiguous at repository level | Taxonomy/reference only until every asset has a documented reusable license |
| Avoid | [EDGAR Crawler](https://github.com/lefterisloukas/edgar-crawler) | GPL-3.0 | Older crawler is unnecessary when official SEC acquisition and a permissive parser are already available |

## 4. Evidence packet contract

### 4.1 Provenance-first SEC prerequisite

No model/API work package is eligible to make a live request until the SEC
provenance layer passes its own acceptance tests. The raw official SEC artifact,
not a parser's normalized output, is canonical. Store:

- accession number, form, accepted timestamp, official URL, retrieval time, and
  raw-artifact SHA-256;
- parser name/version and normalized-artifact SHA-256;
- form item/section/heading plus exact character span, or page and bounding box;
- normalized excerpt hash linked back to the raw artifact;
- for every XBRL fact: concept, value, unit, period, dimensions, accession, and
  the filing/table locator used for reconciliation.

Every model-visible claim receives an immutable source ID that resolves to those
fields. Parser output is a derivative aid, never the authority. EdgarTools is
the primary structured parser; `sec-parser` may cross-check a sampled corpus.
Disagreement, a missing raw artifact, an unresolved span, or a failed XBRL
reconciliation makes the affected evidence ineligible and forces
HOLD/ABSTAIN—before any provider request is queued.

Every model run consumes one immutable packet with:

- `packet_id`, `as_of_et`, `market_session_date`, and `sha256`;
- workflow and pipeline identity;
- ticker, issuer, CIK, and verified identifiers;
- current research label and prior thesis;
- sanitized current weight, applicable caps, and portfolio conflicts;
- market features from the primary provider and comparison provider;
- corporate-action adjustments;
- new SEC filings, accession numbers, form/item, accepted time, and source URL;
- filing text excerpts with exact source spans;
- reconciled XBRL facts with units, periods, filing accession, and formulas;
- issuer-IR documents with provenance;
- prior claims and whether new evidence supports, weakens, contradicts, or does
  not address each claim;
- explicitly missing evidence;
- deterministic C9 score inputs and eligibility results;
- a closed list of permitted action labels.

The packet must exclude:

- unverified scraped text;
- archived legacy project files;
- SMTP or API secrets;
- broker/account credentials;
- live order or execution interfaces;
- model-generated facts from earlier runs unless clearly marked as prior
  hypotheses and re-grounded to source evidence.

## 5. Model roles

### 5.1 Evidence Analyst

The evidence analyst extracts and classifies claims; it does not choose the
portfolio action. Required output:

- material facts;
- source citation for every fact;
- direct source span or table/field locator;
- fact/estimate/opinion classification;
- unit and period;
- management claim versus independently reported fact;
- thesis impact: `supports`, `weakens`, `contradicts`, `neutral`, or `unknown`;
- identified missing evidence;
- calculations requested from the deterministic numeric engine;
- confidence and abstention reason.

Unsupported claims are rejected by the validator.

### 5.2 Thesis and Action Committee

The committee receives only validated evidence plus deterministic calculations.
It must produce:

- a one-sentence decisive recommendation;
- exactly one allowed action label;
- long-horizon thesis state;
- the three strongest supporting facts;
- the three strongest disconfirming facts or risks;
- bull/base/bear cases;
- valuation and portfolio-fit interpretation;
- action conditions;
- invalidation conditions;
- confidence decomposed into evidence coverage, thesis clarity, valuation
  clarity, and portfolio fit;
- what would change the decision;
- an explicit `abstain` result when evidence is insufficient.

The committee is not allowed to invent a price target, expected upside, or
reward-to-risk value. Those values must come from a versioned deterministic
calculation or remain missing.

### 5.3 Adversarial Critic

The critic is mandatory for `paper_trade_candidate`,
`real_trade_candidate`, `trim_review`, and `exit_review`. During the initial
replay and live-shadow evaluation it runs on every packet so its incremental
catch rate and false-downgrade rate can be measured. It receives the sealed
packet's cited evidence plus a separately marked set of uncited packet-local
sources and reconciled calculations, so it can detect omitted counterevidence.
It receives no uncontrolled archive context, tools, or hidden reasoning. It
must test:

- the strongest alternative explanation;
- contradicting primary-source evidence;
- time-period and unit mistakes;
- stale or revised evidence;
- extrapolation from short-term price moves;
- valuation sensitivity;
- concentration and liquidity;
- prompt injection or issuer promotional language;
- whether the conclusion overstates the evidence.

Critic outcomes:

- `confirm`;
- `confirm_with_lower_confidence`;
- `return_to_hold`;
- `abstain`;
- `human_material_review`.

The critic cannot upgrade a recommendation.

## 6. Deterministic decision authority

### 6.1 Hard gates

Any failed hard gate blocks an action-changing recommendation:

- stale or missing primary market session;
- unresolved split/dividend adjustment;
- held-position price disagreement above the tested tolerance;
- missing SEC coverage for a held issuer;
- unreconciled XBRL value or unit/period mismatch;
- unsupported material claim;
- invalid JSON/schema;
- account-state conflict;
- model/packet/prompt version not in the active registry;
- analyst/critic disagreement;
- API error after one bounded retry;
- daily cost cap exceeded.

The result is `abstain` or the existing deterministic HOLD, never a fallback
action proposal.

### 6.2 Action rules

#### New position or add review

Require all existing C9 eligibility rules:

- controlled research packet;
- C9 score at least 7.5;
- confidence at least `medium_high`;
- deterministic expected upside at least 15%;
- deterministic reward-to-risk at least 2.0;
- entry discipline and portfolio fit pass;
- post-action position and theme weights within caps;
- model committee proposes the same action;
- critic confirms;
- same action signature on two distinct valid market closes;
- no newly arrived contradictory official evidence.

#### Trim review

May be produced from:

- the existing deterministic concentration rule; or
- a validated deterioration in fundamentals, valuation asymmetry, or portfolio
  fit that the committee proposes and the critic confirms.

It remains a whole-share scenario for human review and cannot execute.

#### Exit review

May be produced immediately when a new official filing supplies a material,
source-cited thesis break. It does not require two closes because delay may
hide a material risk, but it does require:

- primary-source evidence;
- deterministic numeric reconciliation where applicable;
- committee proposal;
- critic confirmation or `human_material_review`;
- prominent uncertainty and invalidation conditions.

#### Hold

HOLD requires no critic when all hard gates pass and there is no action
transition. It must still state the main risk and the condition that would
change the recommendation.

## 7. Data-flow upgrade

### 7.1 Market data

Add a provider interface:

- primary: Massive U.S. equity aggregate bars and corporate actions;
- comparison: current `yfinance` feed during transition;
- action-grade record: primary price plus provider agreement and corporate
  action reconciliation;
- if the primary source is unavailable, refresh may continue for observation,
  but no new action proposal can be promoted.

Do not increase trade frequency because intraday data is available. Intraday
price and volume are context; closing-session evidence and long-term thesis
remain the action basis.

### 7.2 SEC and issuer evidence

Extend the current SEC layer to:

- download and hash official filing HTML/inline XBRL;
- extract relevant 10-K, 10-Q, 8-K, and applicable exhibit sections;
- preserve accession, accepted timestamp, form/item, and source locator;
- reconcile company facts to the filing rather than treating XBRL as sufficient
  on its own;
- capture official issuer earnings releases and presentations only from a
  verified issuer-domain allowlist;
- treat earnings-call transcripts as secondary unless issuer-hosted.

### 7.3 Frequency and asynchronous queueing

Keep the current deterministic refresh cadence. Refresh performs no model call.
It may seal a packet and append an idempotent local queue item:

- no new material evidence: do not enqueue a full filing-analysis task;
- new filing or source change: enqueue one evidence-analysis task keyed by
  document hash;
- final daily decision: enqueue committee work only for held positions,
  material events, and the highest-ranked eligible candidates;
- weekend: enqueue only after a material evidence or decision-state change;
- critic: enqueue only for a proposed action transition.

The separate shadow worker consumes tasks later, caches by immutable hashes, and
may safely catch up after the computer was off. Queue creation is local and
non-blocking; no credential or external network is needed in refresh. This
raises analysis depth without turning every refresh into a costly, unstable
re-decision or making email availability depend on an API.

## 8. Implementation work packages

### WP0 — Freeze contracts and authority

Create:

- `01_policies/phase5r_llm_decision_authority_policy.md`
- `00_project_control/phase5r_llm_model_registry.json`
- `00_project_control/phase5r_llm_evaluation_policy.md`

Acceptance:

- permitted labels and prohibited authority are explicit;
- no broker, order, SMTP, or canonical-account write tool is exposed;
- every failure path resolves to HOLD/ABSTAIN.

### WP1 — Market and evidence provenance

Implemented:

- `09_scripts/phase5r/refresh_phase5r_daily_evidence.py`
- `09_scripts/phase5r/build_phase5r_decision_evidence_packet.py`
- `09_scripts/phase5r/phase5r_sec_acceptance.py`

Pending external data-provider selection:

- add a narrow read-only licensed market-data adapter only after the user
  selects and provisions a provider outside the repository;
- until then B2 `yfinance` observations are secondary context and
  `market_data_action_grade=false`, so market-dependent action transitions fail
  closed.

Acceptance:

- exact SEC accession/acceptance provenance and raw artifact hashes pass;
- a future licensed primary market-data path works in read-only mode before
  `market_data_action_grade` may become true;
- provider agreement and corporate actions are checked;
- raw SEC filing text is hashed and source-located before parser output is used;
- SEC accession/accepted time/raw hash/parser version/span or page/bbox and XBRL
  provenance fields satisfy Section 4.1;
- unresolved parser disagreement fails closed before queueing;
- rerunning the same source packet produces the same packet hash.

### WP2 — Structured model layer

Implemented:

- `09_scripts/phase5r/phase5r_llm_contract.py`
- `09_scripts/phase5r/phase5r_llm_provider.py`
- `09_scripts/phase5r/run_phase5r_llm_shadow.py`, containing the versioned
  analyst, committee, critic, validator, and adjudication sequence;
- `09_scripts/phase5r/evaluate_phase5r_llm_decision.py` and versioned fixtures.

Acceptance:

- 100% schema-valid outputs on the acceptance set;
- all facts resolve to a packet source locator;
- arithmetic is executed and checked by Python;
- direct official SDK calls explicitly reject refused, incomplete, non-success,
  or locally invalid responses;
- model output cannot alter canonical state or send email;
- request/response logs contain no secret or personal identifier.

### WP3 — Separate idempotent shadow worker and audit trail

Do not add a synchronous model call to C9, daily refresh, the deterministic
decision pipeline, or the sender. The implemented worker is:

- `09_scripts/phase5r/run_phase5r_llm_shadow.py`;
- `09_scripts/phase5r/run_phase5r_llm_shadow_scheduler.py`;
- an immutable run identity keyed by packet, prompt, schema, and model-registry
  content, with a separate output lock and completed-run cache.

The worker takes a short locked snapshot of canonical inputs, releases the
pipeline lock, then performs inference. It does not queue a provider request
from refresh or email code. Consequently a powered-off Mac cannot capture
events while it is off; after wake the deterministic jobs and shadow worker can
evaluate the newest available state, but they cannot reconstruct an intraday
snapshot that was never collected. A continuously available remote collector is
a separate future deployment decision, not an implied capability of launchd.

Create parallel, non-canonical outputs:

- `04_research/realtime_stock_picker_phase5r/phase5r_llm_shadow_decision.json`
- `04_research/realtime_stock_picker_phase5r/phase5r_llm_shadow_decision.md`
- `03_source_data/phase5r/phase5r_llm_decision_audit.jsonl`

Acceptance:

- canonical decision and email remain unchanged;
- model verdict, evidence, critic result, cost, and disagreement are logged;
- duplicate-email protections remain unchanged;
- refresh/C9/sender do not import or invoke the provider adapter;
- API failure, missing credential, or worker downtime cannot delay or fail the
  deterministic refresh or email;
- replaying the same immutable model run is idempotent and cannot create
  duplicate email;
- the worker has no SMTP, broker, account-write, or order capability.

### WP4 — Replay evaluation and adversarial testing

Create:

- `09_scripts/phase5r/evaluate_phase5r_llm_decision.py`
- `08_reviews/phase5r_llm_eval_cases/`
- `00_project_control/phase5r_llm_evaluation_report.md`

Dataset:

- at least **200** immutable, time-isolated replay packets;
- at least **50** material-transition cases (proposed ADD/TRIM/EXIT or a
  transition that should correctly be rejected/abstained);
- held-position, candidate, no-change, missing-data, amendment, corporate-action,
  and contradictory-evidence cases;
- only evidence available at each historical `as_of` time;
- no revised facts or future prices leaked into the packet.

Use FinQA/ConvFinQA/TAT-QA-style executable arithmetic and table tests,
FinReasoning's semantic-consistency/data-alignment/deep-insight dimensions, and
FinRAGBench-V/FinanceRAG-style source/page/qrels checks as supplemental fixtures.
Project-specific replay packets remain the promotion authority. Do not vendor a
dataset until its exact asset license and attribution obligations are recorded.

Minimum promotion gates:

- schema validity: 100%;
- source-locator validity: 100%;
- material factual citation precision: at least 98%;
- deterministic numeric reconciliation: 100%;
- unsupported material claims: 0 on the acceptance set;
- action-label repeatability across controlled reruns: at least 95%;
- missing/contradictory evidence correctly yields HOLD/ABSTAIN: at least 95%;
- material thesis-break recall: at least 90%;
- action-changing false positives caused solely by short-term price movement: 0;
- authority-boundary violations: 0;
- secret/PII leakage: 0.

Any policy violation is an automatic no-go, regardless of aggregate score.

Do not optimize only for historical returns. Separately report:

- factual accuracy;
- calibration;
- action stability;
- decision timeliness;
- false action-transition rate;
- counter-evidence coverage;
- cost and latency;
- hypothetical forward returns with transaction costs, clearly labeled as
  research and never used as the sole promotion criterion.

### WP5 — Live shadow period

Run for **30–60 completed U.S. market sessions**. Thirty sessions is the
earliest possible promotion review; continue toward 60 if transition coverage,
drift, market-regime coverage, or provider reliability is insufficient. The
combined acceptance evidence must still contain at least 50 material-transition
cases, supplied by time-isolated replay when live markets do not produce enough.

Review only exceptions:

- action disagreement;
- unsupported citation;
- high-confidence model error;
- unexpected model drift;
- action transition;
- material held-position event.

Routine HOLD cases require no human review. This reduces manual workload without
removing human control from material portfolio changes.

Promotion requires zero policy violations throughout replay and live shadow:
no unsupported authority, secret/PII disclosure, broker/order behavior, direct
email action, canonical-state mutation, or synchronous dependency of the
deterministic workflow on the model provider.

### WP6 — Controlled activation

Activation may occur only after WP4 and WP5 pass. Initial authority:

- a previously completed, validated model headline and rationale may appear in
  the daily email only when its packet/session identity matches;
- deterministic C9 still decides whether an action label is eligible;
- ADD/TRIM/EXIT labels still require human confirmation;
- no automatic action, broker access, or order artifact is created.

Rollback is one configuration change:

- set model layer to `shadow` or `disabled`;
- deterministic daily workflow and sender continue unchanged;
- preserve packets and audit records for diagnosis.

## 9. Verification matrix

| Requirement | Verification |
| --- | --- |
| Clear decision | Exactly one closed-enum headline/action |
| Deep long-term analysis | Thesis delta, counter-evidence, bull/base/bear, invalidation |
| Reliable facts | Primary-source locators and packet hashes |
| Reliable numbers | Python calculation and reconciliation |
| Low manual burden | Human review only on exceptions and material transitions |
| No excess trading | Existing C9 thresholds and two-close ADD stability |
| No duplicate emails | Existing sender claim/ledger remains final authority |
| Safe outage | Model failure resolves to HOLD/ABSTAIN |
| No refresh coupling | Provider adapter is absent from refresh/C9/sender imports and call graph |
| Reproducible | Exact model/prompt/schema/packet versions logged |
| No execution | No broker/order/tool access; human action outside repo |

## 10. Explicit non-goals

This upgrade will not:

- connect to a broker or read a broker account;
- create order-routing or trade-execution code;
- let a model send an email directly;
- use a model-generated price target as fact;
- use secondary news as a sole action trigger;
- change position limits without a separate policy change;
- increase portfolio turnover merely because analysis runs daily;
- create a new execution phase.

## 11. Go/no-go decision

**Go** for the completed offline contracts, provenance, role isolation,
fixtures, corpus builder, replay verifier, provider-replay runner/gate, and
shadow-only architecture. Materializing the real corpus requires an explicit
SEC-compliant contact User-Agent. External provider replay remains **blocked**
until the user explicitly authorizes the fixed call and cost budgets. The
currently selected bridge uses authentication already owned by the external
Codex CLI; this repository neither requests nor reads a provider secret. A
future direct API/Batch adapter would require a separate external credential
design and approval.

**No-go** for model-influenced production email until at least 200 replay
packets, at least 50 material-transition cases, 30–60 live shadow sessions, all
quality gates, and zero policy violations pass.

**Permanent no-go** for broker or order authority inside this repository.

Research basis:
`04_research/realtime_stock_picker_phase5r/phase5r_llm_decision_architecture_research.md`.
