# Held-position risk visibility

The November 8, 2026 reliability repair adds a dated observation for every
positive holding in the current local record. It does not change loss limits,
strategy approval, capital eligibility or manual execution. The separate
November 8 owner approval for [standalone held-risk review notifications](standalone_risk_review_notifications.md)
adds one explicit notification purpose using these validated observations.

`held_position_risk.py` reads the current position inventory, average basis,
individually checked canonical closes and quality rows, order inventory and
validated maintained-plan context. It remains independent of new-buy valuation
and another ticker's missing price. A shared provenance or account-integrity
failure remains explicit; it cannot authorize an order or reviewed HOLD.

The daily composer writes `daily_decision.held_position_risk`, the current
`04_research/company_research/held_position_risk.local.json`, and small immutable
observations in `05_risk_and_positions/generated/held_risk_observations.local/`.
An unchanged observation does not create another history object. Publication
rebuilds the projection from the exact bound inputs before accepting it.
The history is evidence, never an account or trade input.

States distinguish reviewed HOLD, reduction/exit review, crossed risk reference,
expired plan, required review and unavailable recommendation. Expired references
are observations only and never renewed orders. Only the latest evaluated plan
for the current inventory supplies structured thresholds; a closed prior
position's stop is not reused. A due review is not described as expired.

Recorded-basis return is `(dated close / recorded average basis - 1)`.
The displayed unrealized amount uses recorded quantity and excludes cash flows,
realized trades, dividends and costs. Basis can contain wash-sale adjustments.
Neither field is account performance, acquisition-fill return or peak drawdown.
Legacy CSV loss fields do not create a new approved percentage-loss rule.

Open risks name the analyst/public-data/account-record resolver and the next
existing review-window deadline. That deadline is a service expectation, not
proof that work completed. Order contradictions require exact actual filled,
cancelled and remaining quantities; no fill is inferred from price or expiry.
Current broker protection remains unverified unless supported by current evidence.

Normal decision emails lead with holding risk. Research alerts can carry the
same dated context without gaining order authority. The separately approved
risk-review route can qualify without an action/priority change, but only under
its explicit permission, existing short-slot windows, configured recipient and
duplicate/uncertain-send controls. The optional intraday batch still requires complete admitted coverage;
this repair isolates **canonical-close** observations and does not weaken that
intraday validator. No portfolio aggregate is inferred from partial coverage.
