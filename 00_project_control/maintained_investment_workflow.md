# Maintained investment research workflow

This workflow preserves the existing public collection cadence, broad market discovery, deterministic risk gates, and single canonical sender. It does not expand recommendation volume or enable trading. Company analysis, position plans, account facts, and actual performance are separate records with separate authority.

## Information flow and authority

1. Public market and official-source collection retains dated data, exact raw SEC responses, verified filing artifacts, and per-source news coverage. Collection success does not establish that new financial results were used.
2. Earnings reconciliation compares the latest known financial report/material earnings event with the selected financial period and archived selection receipt. A verified cached official inline-XBRL report can repair a lagging companyfacts response. Missing components stay unknown; an absent debt or capex fact is never converted to zero. The gate is recomputed from retained bytes when composing and validating publication.
3. A maintained company dossier records source-backed claims, supporting and contradictory evidence, business and per-share conclusions, valuation readiness, change reason, and next review. A completed business review can coexist with incomplete valuation. New material evidence, review deadlines, or invalid sources reopen the effective view while preserving its authored history.

   Verified substantive issuer headlines enter a durable review queue. The seven-day display window controls initial admission, not resolution: items remain pending through later feed failures or aging until an authored review acknowledges their exact content hash. Headline review does not imply full-document financial incorporation. Corrected content reopens review; unrelated dossier updates cannot clear it. Stored source receipts and review-version links make the transition traceable. Producer stages append under lock; publication only reads and validates.
4. A versioned position plan records the mandate, current research instruction, counterargument, observed account timestamp, next review, any original time exit, and dated draft validity. Reconciliation with observed holdings/orders precedes display. Unconfirmed absence, cancellation, expiry, or quantity changes remain unresolved. No daily rule output silently replaces the plan.
5. The canonical decision merges these layers. Current instructions use the maintained plan; the previous deterministic calculation remains labelled diagnostic background. Conflicting risk reviews are explicit reconciliation work. Missing or reopened prerequisites cannot clear new capital. Retained prices or quantities are historical proposals, never automatic renewal authority.
6. Text, HTML, current status, and the sender read this same decision contract. Publication rejects changed account inputs, plan state, financial selection, thesis evidence/deadline, or news state until recomposition. The immutable decision history records semantic changes and their plan/thesis versions; a new poll time alone is not a changed investment conclusion.
7. Outcome evaluation retains the original observation date and follows future exchange sessions without dropping missing sessions. It links new observations to their plan/thesis versions. Repeated snapshots are not independent trials. Actual portfolio performance uses a separate ledger of confirmed NAV, external flows, and reviewed intervals; planning cash is excluded.

## Daily and longer-horizon work

At the existing collection slots, refresh evidence, reconcile latest earnings, evaluate due company views and position plans, compose one current decision, and refresh outcome/operational coverage. Preserve unresolved states until new evidence resolves them. A successful refresh is an operational result, not proof that valuation research is complete or that an order filled.

Use the existing bounded discovery shortlist for research priorities. Prioritize held-company overdue/reopened reviews and specific valuation gaps before adding more recommendations. A company review should progress in explicit stages:

- Evidence received: preserve source identity, period and publication/collection times.
- Business assessed: state the supported conclusion and strongest countercase; document what would change it.
- Per-share economics assessed: reconcile dilution, cash-flow definition and debt scope.
- Valuation reviewed: use company-specific, source-backed scenarios with an explicit countercase and current price reference. A generic sensitivity grid remains research support.
- Maintained: set a next review and reopen on material evidence; append a superseding version with a reason instead of silently overwriting.

Weekly review should inspect overdue plans/dossiers, stale coverage, contradictory states, and matured outcomes. Monthly review should inspect reliability denominators, outcome coverage at each horizon, unresolved execution evidence and eligible actual-performance intervals. Do not claim an investment edge from a short or selected sample, and do not change thresholds automatically from early results.

## Price expectations, capital-loss paths and thesis review

Adopted by the owner on October 19, 2026, following discussion of Howard
Marks's *The Most Important Thing*. The objective is better decisions per unit
of research effort: make the disputed assumption explicit, investigate the
evidence that can change it, and preserve the original judgment for review.
These are analyst methods within the existing workflow. Capital eligibility
continues through the existing strategy and evidence contracts.

### 1. State what the price requires and where our view differs

For a held-company review or a decision-relevant active-company candidate,
select the one to three operating assumptions that explain most of the case.
Use the existing reviewed company model to ask what must hold at an explicitly
dated price. Hold the other assumptions fixed and name them. For an earnings
multiple model, required EPS = price / assumed multiple; for a cash-flow model,
solve a named growth, cash-margin or reinvestment condition under the stated
discount rate and terminal assumptions. Identify the model's exact hash and
horizon. An endpoint multiple calculation does not become a present-value DCF,
and a price-distance ratio does not become a probability-weighted return.

Record three distinct assessments in the existing dossier's `research_method`:

- **Price-implied conditions:** a conditional model result with its dated
  price, method, fixed assumptions and main unknowns. A single price cannot
  uniquely reveal the market's growth, margin, discount-rate and terminal
  expectations; show the conditionality instead of claiming a unique answer.
- **Observed consensus:** only a dated, retained external expectations sample
  with a source and stated coverage. Management guidance and our reverse
  valuation are not market consensus. Missing consensus remains unknown;
  it need not prevent a useful comparison against price-implied conditions.
- **Differentiated view:** the specific disagreement, supporting and
  contradictory claim references, what would falsify it, and the next evidence
  that discriminates between the explanations. A different opinion alone does
  not establish an edge. If no supported disagreement exists, say so.

Do not change model inputs to make the current price pass. A changed economic
assumption needs the existing source-bound company/model amendment process.

### 2. Trace how capital could be lost

Write one to three material causal paths, not a general list of risks: adverse
event -> business/financing effect -> impairment of per-share value. Attach
supporting claim IDs and an observable early warning. Separate temporary price
volatility from economic impairment and from an investor's inability to wait.
The latter must use the owner's actual horizon and liquidity constraints.

Name the one to three most fragile assumptions and what an adverse change
would do to the conclusion. Reuse the existing sensitivity/model outputs when
available; label uncalculated severity as unknown. Bear/base/bull cases are
conditional scenarios, not probabilities, a worst-loss bound or stop protection.

Use a few stable exposure tags with issuer-specific causal explanations to
identify common risks across companies, such as customer financing or the same
capital-spending cycle. The existing workflow evaluation groups these tags for
portfolio review. Include known fund overlap with a dated holdings source when
available; missing fund look-through stays explicit. Tag counts are not weights,
correlations or evidence of diversification and do not set position limits.

### 3. Revisit the original thesis without rewriting it

At a decisive operating disclosure, a recorded falsifier/review date, or a
material change of view, attach `retrospective` to the next ordinary dossier
version. Bind the exact earlier review ID and hash. Separate:

- **Decision process:** whether the original evidence, price comparison,
  countercase and loss paths supported the judgment at that time. If the
  original record lacks this method, leave process quality unresolved rather
  than reconstructing an excellent past thesis after seeing the outcome.
- **Business outcome:** which original conditions were supported or challenged
  by later reported facts, with citations in the new review. An event that has
  not occurred is `not_yet_observable`, including when the share price moved.
- **Price outcome:** the existing forward observation tied to the original
  thesis version and observation timestamp. Preserve missing periods, original
  no-action/negative cases and costs/dividend/corporate-action limitations.
- **Learning:** one specific analytical lesson or next test. No automatic
  threshold changes, strategy promotion or claim of skill from a short streak.

Where comparable positive per-share earnings/cash flows and matched prices
exist, an analyst may distinguish business change from multiple change using
P = per-share metric x multiple, with consistent periods and accounting scope.
Otherwise leave attribution unresolved. Benchmark-relative price changes alone
do not establish causal alpha, luck or actual portfolio returns.

### Work selection, delivery and effectiveness

Use the existing analyst cadence and priority order: urgent held risks first,
then the unresolved assumption most likely to change a candidate's decision.
Complete these blocks during the next substantive company review; do not
restamp every dossier to manufacture adoption statistics. An unchanged source
set without a useful new question does not warrant another research narrative.
Record the primary reason for waiting as price, evidence or unfinished research,
with the condition that would reopen work and the next useful evidence.

One authored record feeds the existing company detail and daily text/HTML;
show concise reasoning within that company case. Full methods and citations
stay in the dossier. The existing `workflow_evaluation.local` report owns
cross-company risk grouping, retrospective coverage and pending reviews. Do
not create a separate Marks report, duplicate watchlist or parallel journal.

Judge effectiveness at weekly/monthly review using distinct original thesis
versions and unchanged-method deduplication: coverage of useful price/risk
reasoning, unresolved decisive evidence, source-backed business follow-through,
and due original theses still awaiting review. Repeated daily snapshots and
copied method blocks are not new analytical cases or independent trials.
Check whether the new evidence changed the thesis, price judgment, risk
assessment or next research task; more filled fields is not proof of value.
Actual investment performance remains subject to the existing confirmed NAV,
flows and benchmark requirements.

Obtain an unknown method block with `update_thesis_review.py
--research-method-template`. For a later review, use
`--retrospective-template ORIGINAL_REVIEW_JSON` to bind the exact original.
Merge only completed or explicitly unknown assessments into the next ordinary
review, seal it with `thesis_evidence.seal_review`, and use the existing
`--input` check followed by `--apply` under the documented locks. A template
alone is not completed research. Newly authored reasoning carries its own
`authored_at`; unchanged reasoning retains its original provenance.

Historical dossier versions remain immutable and valid without these optional
fields. Missing or unresolved method fields cannot independently clear or block
capital; supplied fields must pass the same evidence-integrity discipline as
the dossier. Any amended company review still uses the existing writer,
model admission bindings and full no-send recomposition procedure; a research
annotation must not silently renew the original model or review deadline.
Its own authored timestamp governs prospective evaluation; an old financial
review timestamp cannot backdate newly written reasoning.

## Private records and operator updates

### Retaining an older official filing for a current review

The ordinary SEC artifact collector keeps its current selection and may also
retain an exact historical filing needed by an authored review. Use
`refresh_sec_filing_artifacts.py --refresh --include-source-id SOURCE_ID`
through the existing identified public-collection launcher. The source must
already exist in the official evidence ledger and match the immutable SEC
acceptance index or an admitted acceptance extension. This option cannot admit
an arbitrary URL or a different issuer, accession or filing date.

Up to eight explicit review-source requests are retained in the artifact
index. Later ordinary refreshes and checks revalidate and include them without
removing current filings or broadening the recency window. The normal fetch,
raw/normalized hashes and artifact validation still apply. Missing acceptance
proof, conflicting identities or altered request metadata fail closed; a
retained request alone is not a verified artifact or completed review. Do not
backdate collection or change a filing's source class to bypass provenance.

Private records are ignored by Git and must not enter source-control commits:

| Record | Purpose | Update path |
|---|---|---|
| `05_risk_and_positions/investment_plans.local.json` | Append-only plan versions and preserved original deadlines | `update_investment_plan.py --input <review.json>` previews; `--apply` appends under lock |
| `04_research/company_research/thesis_dossiers.local.json` | Source-bound company conclusions and counterevidence | `update_thesis_review.py --input <review.json>` validates; `--apply` appends under lock |
| `04_research/company_research/issuer_news_review_queue.local.jsonl` | Retained verified headlines, pending assessment and exact review acknowledgments | Producers append hashed event identities; explicit company review resolves assessed items |
| `03_source_data/equity_research/earnings_incorporation_status.local.json` | Latest report versus incorporated financial selection | Generated after filing retrieval; read-time validation recomputes facts |
| `02_filings/companyfacts_snapshots.local/` | Exact public responses and immutable financial selection revisions | Collector writes content-addressed artifacts |
| `00_project_control/run_logs/decision_history.local.jsonl` | Why current conclusions changed | Canonical composer appends semantic changes with chained hashes |
| `05_risk_and_positions/performance_observations.local.jsonl` | Actual NAV, flows, reviewed intervals and corrections | `create_workflow_evaluation.py --record <record.json>` previews; `--apply` appends |
| `08_reviews/current/workflow_evaluation.local.json` | Reliability, forward-outcome coverage, actual-return readiness | Refreshed after the durable current refresh record |

Plan and company updates must cite retained source hashes. Preview is default. An amended review supersedes a named prior version; old records stay available. Record actual broker fills in the existing manual execution/account process first. A research plan is not an execution ledger, and neither changes broker orders.

For a dated owner-requested review, promote accepted durable conclusions into these records when applicable. The one-off email appendix is a dated presentation; it is not the authoritative store for tomorrow's instructions. Existing owner-review and normal-send deduplication rules still apply.

## Operational reliability

The production runtime remains the separate Git-synchronized clone. The runtime lock serializes deployment and scheduled work. Only public collection may use an unchanged, fully clean deployment previously verified online within 24 hours during an explicit DNS/connectivity outage. Sender and sync-only remain strict; authentication, TLS, unknown errors, dirty evidence, or changed commit state block execution. See `macbook_github_macmini_workflow.md` for the exact receipt and fallback constraints.

The workflow evaluation report distinguishes on-time, late, missing, and eventually completed calendar cycles; it does not relabel them as exchange sessions. Current-run timing is recorded before status generation. Delivery-unknown states remain unresolved, with no automatic resend. Retained raw responses grow only when content changes; monitor local storage before expanding individual-name research.

## Limitations that remain deliberate

The current pipeline uses dated reference data, not a live brokerage or real-time order engine. Fresh price, available shares, reservations, and confirmed funds still require verification before a human acts. Scheduled deterministic processing can age/reopen a company view but cannot manufacture a new analyst conclusion. Historical portfolio returns remain unavailable until actual balances and flows reconcile. Unsupported exchange years and exceptional closures require calendar updates. None of these gaps should be hidden by increasing a confidence label or issuing more recommendations.
