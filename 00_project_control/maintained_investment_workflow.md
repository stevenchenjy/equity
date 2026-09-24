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

## Private records and operator updates

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
