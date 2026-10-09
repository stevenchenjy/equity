# Capital decision and manual execution contract

## Two-session capital deployment escalation

The October 8 owner instruction adds an escalation of research and capital-use
comparison. Two consecutive verified market sessions with no `ACTIONABLE_BUY`
or `ACTIONABLE_ADD`, uncommitted cash materially above the approved cash target,
and no account-wide integrity blocker activate it. The review materiality is
five percentage points of portfolio value above the approved target, configured
in `workflow.capital_deployment_escalation`; it changes no allocation or risk
limit. Repeated morning/afternoon refreshes count once per observed session.
Weekends and holidays do not count; missing session evidence stays unknown.
Any admitted buy/add in a session breaks its no-action classification, even if
a later draft expires. Validated historical final decisions may seed the ledger.

`daily_decision.json:capital_deployment_escalation` compares adding to an existing
quality holding, opening the strongest researched growth case, and a diversified
core/growth allocation. It ranks reviewed readiness and exact unsatisfied gates,
not past price performance. An unavailable route is explained. Existing admitted
eligibility, purpose, price, allocation and shared-cash owners still determine
every positive conditional draft. An above-floor core addition requires its own
approved sizing contract; the escalation does not invent one. Completed negative
economic assessments remain negative, rather than becoming unfinished research.

Retained cash has exact categorized evidence, valuation, price, risk, policy or
account gates and a named closest candidate where one can be compared. Account
integrity blockers suspend deployment escalation and are displayed explicitly;
ticker-only quarantine cannot suspend unrelated research. The closest candidate
is a readiness comparison, not approval or a claim of investment quality. Final
text/HTML and the dashboard consume the same summary.

Private state/report and bounded attempt receipts live under
`08_reviews/capital_escalation.local/`. A triggered full refresh immediately runs
one source-bound objective batch for priority candidates and recomposes valuation,
portfolio and final decisions, retaining unsuccessful stages and remaining gates.
Existing issuer/network limits and unchanged-evidence skips remain in force.
The analyst completes remaining reasoning through maintained writers; successful
collection does not prove that analysis occurred. Repeated refreshes cannot run
the same escalation batch again that session. No sender or broker is invoked.

The final capital decision is `daily_decision.json:capital_decision`, mirrored at
`08_reviews/current/capital_decision.local.json`. It is produced after canonical
eligibility, maintained thesis/plan reconciliation, portfolio sizing and observed
price-risk review. It is the common input to the action-first email and dashboard.
Renderers do not calculate a second recommendation. The engine does not connect
to a broker, handle credentials, submit orders or invoke a sender.
Adjacent dashboard widgets cannot restore old ceiling quantities or withheld
drafts. Historical plan levels remain available as historical evidence. Entry
validity ends at the earliest strategy/maintained-plan review or DAY close.

## Decision work versus execution

The system chooses the supported action, whole-share quantity, conditional price,
regular-session window, DAY expiry, risk, reassessment, concentration and cash.
The owner reads that complete draft and manually enters any real order in Chase.
A draft does not assert that an order has been submitted or filled. A later email's
owner-assumed completion scenario remains labelled and outside decision inputs.

Outcomes are ACTIONABLE_BUY, ACTIONABLE_ADD, HOLD, REDUCE_REVIEW, EXIT_REVIEW,
NO_ACTION and BLOCKED. Zero-share sizing is an explicit result. Failed observed
score/upside/reward-risk/whole-share conditions are NO_ACTION; unavailable evidence
is BLOCKED with an exact dependency. Current maintained exits may carry a complete
sell draft, independently of a failed new-capital market gate, when account shares,
orders and the dated source plan are sufficient. Sell proceeds never fund another
proposal until recorded as actual cash.

## Sizing and risk authority

The approved account record and active-production configuration remain authoritative.
Existing `portfolio_construction` computes canonical whole-share ceilings; the final
adapter cannot increase them. Existing `tactical_review` provides observed entry,
invalidation, target and loss budgets. Final proposals share remaining cash and risk,
and respect the current aggregate stock ceiling, broad-core floor and applicable
strategy-specific budgets. The [October 6 allocation policy](allocation_policy.md)
removes the fixed single-stock ceiling; legacy name-cap headroom cannot remain
a hidden sizing restriction. Account authority follows the owner-approved
[local-record policy](account_record_authority.md). With its private approval,
local shares, recorded order commitments and ledger cash supply conditional
planning quantities; observation age and completeness/cash labels are execution
checks rather than global research gates. Broker flags and dates remain unchanged.
Without that approval the verified-current-snapshot requirements still apply.

A tactical draft explicitly records a multi-day tactical purpose, observed price
invalidation, target and maximum five-session review/exit. Existing fundamental or
core holdings cannot be recast as tactical without a recorded reassessment. Frozen
momentum experiments are not signal admission inputs.

Broad-core investment rules do not prescribe a tactical price stop. For a permitted
core tranche, the contract therefore records `invalidation_price=null`, its economic
invalidation and the full unlevered principal exposure. `planned_total_loss` in that
risk model is the maximum principal exposed, not a promise of a small stopped loss.
Presentation must say this plainly. Do not invent a stop, valuation target or downside
floor to complete a form. Exact tactical price-risk and core exposure models remain
separate. Fees, spreads, gaps and execution availability remain explicit conditional
checks; estimated notional is not guaranteed execution cost or settled buying power.

## Research and automatic resolution

An official-evidence scan can complete with issuer quarantines. The collector
validates the shared immutable acceptance index and retained audit chain first,
then admits each issuer independently. `scan_status=partial` is usable only with
the explicit `global_integrity_passed`, empty `global_blockers`, admitted issuer
list and named `ticker_blockers` contract. It does not mean all companies passed.
Rejected submissions preserve their old selection/history without refreshing
their dates; successful issuers publish new receipts and continue objective work.
An admitted issuer's numerical gaps remain available to the objective worker.
Shared configuration, history corruption, lock or publication failures remain
global. The decision, packet, per-ticker stability and capital adapter preserve
the rejected company's blockers while evaluating unrelated companies normally.
Local-account arithmetic, known commitments and usable-funds execution checks remain independent; see the owner-approved account-record authority.

The artifact collector retains the latest original annual and quarterly report
of each periodic form as well as current event-window material. A later 8-K
cannot age the financial report out of the admission index. Preserving a report
does not claim that newer earnings have already been incorporated.

Recurring capital research uses actual recorded holdings to assess the core
floor. Satisfied core exposure stays in monitoring unless a specific new gap or
eligible case warrants work; below-floor core and held-risk reassessments retain
their priority. Monitoring does not create an add, trim or broker observation.

The existing full refresh already performs objective research, SEC acceptance
reconciliation, earnings incorporation, valuation recomposition and dependent
portfolio/decision stages. Its bounded workers now retain source/output hashes,
actual exit status and changed paths under `08_reviews/decision_resolution.local/`.
A successful stage is not proof that an investment case or canonical field completed.
The final queue classifies dependencies:

| Class | Responsibility |
|---|---|
| A | Existing bounded objective/admission/recomposition worker can resolve retained factual dependencies. It runs in the normal refresh. |
| B | New approved public data, publication or a reconciled primary source is required. Bounded public attempts continue; conflict stays unresolved. |
| C | Resolve an actual local-account contradiction or unbounded known commitment. In owner-local-ledger mode, age/completeness/estimated-cash labels are manual execution checks, not a request for a new broker snapshot. No unattended broker access. |
| D | Investment judgment or purpose reassessment requires source-bound analyst synthesis. The recurring Codex analyst performs that work and uses maintained writers. No positive conclusion is fabricated. |
| E | Reviewed strategy adoption, policy validity or actual execution conditions are required. No bypass. |

The analyst carries conclusions and valuation inputs into durable validated stores,
then performs the full no-send recompose. Opportunity support, a processed dossier,
new numerical field, reviewed thesis, complete valuation and actionable draft are
separate transitions. Negative, missed, failed, expired and unresolved work remains.
The bounded ten-item work priority is separate from decision coverage: all active
research opportunities receive a final outcome, including supported cases outside
the next work batch. This adds no research quota or canonical admission authority.
No production model API or service purchase is enabled by this change.

## Strategy lifecycle

`01_policies/production_strategies.json` identifies versioned policy adapters.
Existing owner-approved deterministic policies retain their prior authority; their
presence is not a performance-validation claim. The registry does not adopt Momentum
v4. An experimental definition must traverse mature evidence, source-bound strategy
review and explicit owner adoption of its exact hashed version before production
admission. Policy or definition changes invalidate that adoption; future signals from
an unchanged adopted version do not require another adoption approval. Individual
signals still pass current evidence, account, portfolio, risk and execution gates.
Adding a new strategy implementation remains a reviewed code/policy change; registry
metadata alone cannot implement a new entry method or invent a signal.

## Publication and verification

Contract content and source hashes are validated at publication consumers. Expired
or changed inputs suppress numerical actions on the dashboard and block delivery
validation until recomposed. Historical outputs remain historical. Software tests
prove calculation, isolation and presentation; investment evidence remains the
separately frozen forward/unseen strategy study. No profitability is inferred.

## Delivery and follow-up consistency

Email, text, Markdown and dashboard consume the admitted capital contract.
The notification baseline includes exact current drafts, held-position
conclusions and shared blockers; clock-only updates and unqualified research
churn do not count as new instructions. A new draft cannot quietly reuse an
older renderer's “up to” quantity.

The afternoon planning scenario reads only fully displayed, hash-bound text,
HTML and decision archives. It may illustrate completion of every exact prior
draft at its stated levels, but never writes holdings, fills, cash or order
status. A prior instruction requires a later complete owner-recorded account
snapshot and sourced complete order observation before additional capital
drafts. That reconciliation need is an account-state gate; hypothetical shares
and proceeds are never sizing inputs. Missing or truncated archived
instructions do not fall back to legacy proposals.
