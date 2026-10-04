# Capital decision and manual execution contract

The final capital decision is `daily_decision.json:capital_decision`, mirrored at
`08_reviews/current/capital_decision.local.json`. It is produced after canonical
eligibility, maintained thesis/plan reconciliation, portfolio sizing and observed
price-risk review. It is the common input to the action-first email and dashboard.
Renderers do not calculate a second recommendation. The engine does not connect
to a broker, handle credentials, submit orders or invoke a sender.

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
and respect name and aggregate headroom. Current account evidence must include its
observation time, current complete orders and execution-funds confirmation. A stale
or estimated balance cannot acquire numerical capital authority through a renderer.

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
| C | Owner must record current account-wide holdings/orders/funds via the existing manual account mechanism. No unattended broker access. |
| D | Investment judgment or purpose reassessment requires source-bound analyst synthesis. The recurring Codex analyst performs that work and uses maintained writers. No positive conclusion is fabricated. |
| E | Reviewed strategy adoption, policy validity or actual execution conditions are required. No bypass. |

The analyst carries conclusions and valuation inputs into durable validated stores,
then performs the full no-send recompose. Opportunity support, a processed dossier,
new numerical field, reviewed thesis, complete valuation and actionable draft are
separate transitions. Negative, missed, failed, expired and unresolved work remains.
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
