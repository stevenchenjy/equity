# Phase 5R Rigorous Model and Decision API Upgrade Plan

Date: 2026-07-24  
Status: offline architecture implemented and fail-closed; real SEC replay
materialization, independently reviewed transition labels, provider replay, and
explicit external-inference activation remain pending

Target: improve decision robustness and decisiveness without automated trading

Implementation checkpoint (2026-07-25):

- per-ticker analyst/committee/critic contracts, deterministic adjudication,
  return-objective binding, replay corpus tooling, resumable provider
  collection, extended quality gates, dual-review finalization, and activation
  receipts are implemented;
- the integrated local suite is rerun after each combined change; the current
  final result is recorded in
  `00_project_control/phase5r_llm_upgrade_execution_report.md`;
- the live model scheduler remains intentionally unloaded and uninstalled;
- real qualification is still blocked on a 250-packet, 20-issuer SEC corpus,
  frozen independent annotations, the external-provider replay, and 30–60
  shadow sessions;
- the next external stage should be a 30-call quarantined smoke test, not an
  immediate full activation.

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

The portfolio research objective is a rolling five-year annualized net total
return of `12%–15%` (`0.9489%–1.1715%` exact monthly compound equivalent).
`15%–20%` describes an excellent calendar year, not a required annual result.
The target is never a monthly quota, guarantee, reason to increase turnover, or
override of evidence and risk gates. Its measurement contract is frozen in
`00_project_control/phase5r_return_objective_policy.md`.

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
 canonical daily       current sealed packet
 decision/email        + packet-hash identity
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
                             v
                  Adversarial Critic
                  independent prompt/request
                  (every replay/live-shadow packet)
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
implemented worker snapshots the newest locally available deterministic packet
under the pipeline lock and deduplicates by packet, role, prompt, schema, model,
and runtime-code hashes. It does **not** yet maintain a historical queue or
capture data while the Mac is off. Provider latency, quota, credential failure,
or outage therefore cannot delay or fail refresh, C9, or the daily email, but a
missed intraday state cannot be reconstructed after wake. An immutable spool or
always-on remote collector is a separate, not-yet-implemented work package.

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
| Optional independent challenger | Claude Fable 5, with Opus 5 as a lower-cost control, or successor | provider adapter | evaluation only |

Use strict Structured Outputs with a versioned JSON Schema. Do not let models
call web search, shell, email, filesystem, account, or execution tools. Retrieval
and computation occur before the request and are visible in the evidence packet.

### 3.2 Model registry

The implemented local, non-secret registry binds the provider, requested model
IDs, roles, reasoning settings, prompt/schema versions, activation mode,
successful-role reuse rule, live per-role attempt limit, and evaluation
thresholds. Before any future advisory activation, extend the registry/receipt
contract to bind the remaining production fields:

- allowed input classes;
- prohibited data classes;
- evaluation version and pass date;
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

The Batch API is attractive for the frozen replay because OpenAI documents a
50% discount, but its FAQ also states that Batch does not support Zero Data
Retention. Therefore Batch is acceptable only for already-public SEC/issuer
evidence plus sanitized portfolio bands; any future private or identifying
input must use a separately approved retention-compatible transport or remain
local. See
https://help.openai.com/en/articles/9197833-batch-api-faq%3F.gz.

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

Critic outcomes use the closed verdicts `approve`, `revise`, or `reject`, plus
a direction-safe downgrade classification for each reviewed ticker. The
deterministic adjudicator rolls the surviving ticker decisions up to the
portfolio headline.

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
- a schema, semantic, citation, evidence, or policy-invalid provider answer
  (terminal for that exact run and never retried into an apparent pass);
- a narrowly typed `RetryableProviderTransportError` after the affected role's
  two bounded live attempts;
- a declared replay call or cost budget is exceeded.

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

During replay and the initial live-shadow period, HOLD receives the same
independent critic pass as every other classification. A later cost-optimized
mode may omit the critic for an unchanged, hard-gate-valid HOLD only after that
event-gating policy passes its own replay and false-negative evaluation. HOLD
must still state the main risk and the condition that would change the
recommendation.

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

### 7.3 Frequency and current-state catch-up

Keep the current deterministic refresh cadence. Refresh performs no model call.
The implemented model worker runs separately after the daily decision window,
evaluates the newest locally available packet, and caches completed role
results by immutable run identity. Successful analyst, committee, and critic
receipts are reused independently, so retrying a narrowly typed
`RetryableProviderTransportError` (timeout or missing final response) does not
recall earlier successful roles. A schema,
semantic, citation, evidence, or policy-invalid answer is terminal for that
exact run and cannot be retried into an apparent pass. Each live role has at
most two attempts, and an ambiguous in-flight outcome is terminal rather than
recalled. A run is complete only after a hash-bound completion manifest commits
all required outputs. Interrupted partial publication can be repaired without
another provider call only when all required, valid role receipts already
exist; otherwise it fails closed.

There is no claim that launchd can collect data while the computer is powered
off or asleep. On wake, the local jobs can evaluate only the newest state that
can then be fetched. A future queue/spool should be considered only after live
shadow proves useful, and must be added without importing the provider into
refresh, C9, or sender code.

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

### WP3 — Separate receipt-backed shadow worker and audit trail

Do not add a synchronous model call to C9, daily refresh, the deterministic
decision pipeline, or the sender. The implemented worker is:

- `09_scripts/phase5r/run_phase5r_llm_shadow.py`;
- `09_scripts/phase5r/run_phase5r_llm_shadow_scheduler.py`;
- an immutable run identity keyed by packet, prompt, schema, model-registry,
  and runtime-code content, with a separate output lock, per-role durable
  attempt/result receipts, and an atomic completion manifest.

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
- model verdict, evidence, critic result, latency, local hashes, disagreement,
  and any available operator cost estimate are logged; the exploratory CLI does
  not claim provider-native token usage or billing;
- duplicate-email protections remain unchanged;
- refresh/C9/sender do not import or invoke the provider adapter;
- API failure, missing credential, or worker downtime cannot delay or fail the
  deterministic refresh or email;
- result publication and reuse for the same immutable model run are idempotent
  and cannot create duplicate email; no external exactly-once inference claim
  is made;
- a completed role is never recalled merely because a later role failed;
- semantically or contract-invalid output is terminal and cannot be repaired by
  retrying the model;
- partial output publication is completed only from a full set of valid
  existing role receipts or rejected, never mistaken for a completed run;
- the worker has no SMTP, broker, account-write, or order capability.

### WP4 — Replay evaluation and adversarial testing

Create:

- `09_scripts/phase5r/evaluate_phase5r_llm_decision.py`
- `08_reviews/phase5r_llm_eval_cases/`
- `00_project_control/phase5r_llm_evaluation_report.md`

Dataset:

- at least **250** immutable, time-isolated replay packets across at least
  **20 issuers**;
- at least **50** material-transition cases (proposed ADD/TRIM/EXIT or a
  transition that should correctly be rejected/abstained);
- held-position, candidate, no-change, missing-data, amendment, corporate-action,
  and contradictory-evidence cases;
- only evidence available at each historical `as_of` time;
- no revised facts or future prices leaked into the packet.

Corpus acquisition has two deliberately different stages:

1. **Source-materialization pilot (30 packets):** use a quarantined,
   representative sample to prove raw-primary reuse, filing-index and exhibit
   enumeration, XBRL reconciliation, point-in-time market coverage, hashes, and
   storage behavior. This is evidence/provenance QA only. It authorizes no
   provider call, does not count as the 250-packet qualification, and cannot
   unlock shadow or email influence.
2. **Qualification corpus (at least 250 packets and 20 issuers):** freeze the complete
   time-isolated cohort and its independent annotations, with at least 50
   genuinely material transitions plus retained no-change/rejected cases.
   Cohort design should target at least 20 issuers across forms, years, sectors,
   and market regimes; the current six-issuer ledger can exercise mechanics but
   is not representative decision-quality evidence. Provider replay begins
   only after this source and annotation freeze is complete.

Run the offline preflight before either stage:

```sh
python3 09_scripts/phase5r/inventory_phase5r_llm_replay_corpus.py
```

The inventory prints deterministic JSON only. It binds the ledger and SEC
acceptance-index SHA-256 values, freezes the selected cohort, reports
issuer/form/year/item distributions and accession-level primary/index/exhibit/
XBRL/market gaps, and estimates requests and storage. It performs no network
request, requests no authentication, writes no file, and does not create the
corpus root. Its readiness fields are planning evidence, never activation
evidence.

Provider evaluation is deliberately two-phase:

1. `collect` makes only the explicitly acknowledged, capped provider calls and
   writes immutable quarantined responses plus a non-passing review template;
2. two independent reviewers label the exact frozen claims and transition
   rationales; then a provider-free `finalize` command validates reviewer
   independence, rationale text, rubric/hash bindings, and publishes an
   activation-eligible report only if every gate passes.

A prompt, schema, model, output, packet, rubric, or runtime-code hash change
invalidates the review. Collection alone can never satisfy activation.

Every physical provider attempt is recorded in an immutable, hash-chained
ledger with its terminal classification. Schema, semantic, citation, evidence,
and policy-invalid answers terminate the logical item and cannot be retried
into a pass; only narrowly classified transport/process failures may consume a
bounded retry. The evaluation's global physical-call and operator-estimated
cost ceilings are frozen and remain cumulative across resumed collection
commands, while `--max-new-calls` limits only the current invocation. The gate
recomputes these counts and classifications rather than trusting summary
fields.

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

Performance comparison uses an advance-frozen `SPY` total-return benchmark,
`QQQ`/`XLK` factor context, and the deterministic C9 baseline. Report
time-weighted rolling CAGR, drawdown, downside risk, turnover, cash drag,
implementation costs, attribution, confidence intervals, and parameter
sensitivity. The 12%–15% long-horizon objective cannot compensate for a failed
factual, citation, calibration, or policy gate.

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

### WP6 — Controlled advisory activation (future, not implemented)

The implemented activation receipt can enable only
`exploratory_shadow_only` after WP4; it cannot affect the email or canonical
decision. Advisory activation may occur only after WP4 and WP5 pass and a
separate advisory receipt/transport is implemented. Its initial authority would
be limited to:

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
| Reproducible | Requested model ID plus exact local prompt/schema/packet/runtime hashes logged; provider-native resolved version/response ID required for future advisory |
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
direct Responses adapter is implemented with an externally supplied client;
activating it or adding a Batch execution path still requires a separate
external credential boundary, retention decision, and approval.

**No-go** for model-influenced production email until at least 250 replay
packets across at least 20 issuers, at least 50 material-transition cases,
30–60 live shadow sessions, all quality gates, and zero policy violations pass.

**Permanent no-go** for broker or order authority inside this repository.

Research basis:
`04_research/realtime_stock_picker_phase5r/phase5r_llm_decision_architecture_research.md`.
