# Equity Research — Account-State Policy

Account planning authority now follows [the October 9 owner-approved local-record policy](account_record_authority.md). When its private approval is active, use local cash, holdings and known order commitments for conditional manual plans. Do not request a fresh broker snapshot solely for age, completeness flags or estimated-cash labels; preserve those facts as execution checks. Actual arithmetic/order/feedback contradictions and company/strategy requirements remain effective.

## Canonical Inputs

- Shares, entry date, entry price, thesis, horizon, and invalidation context: `05_risk_and_positions/current_positions.local.csv`.
- Reported account-total reference, prior value, external cash, available cash, reserve, horizon, and allocation limits: gitignored `05_risk_and_positions/current_account_state.local.json`.
- Current prices and provenance: `03_source_data/equity_research/market_data_snapshot.csv`.
- Current public research evidence: controlled C5 packet fields; portfolio-fit fields from the old packet are not authoritative.

Generated portfolio calculations are in `05_risk_and_positions/generated/current/`.
Private prior versions are retained by hash in
`11_archive/portfolio_versions.local/`. Archives are audit evidence only and
cannot replace a missing or invalid current input. The daily refresh snapshots
current portfolio files at its boundary; managed writers save changed
predecessors before replacement. See `05_risk_and_positions/README.md` for
direct manual edits.

## Runtime State

No dollar amount, share count, or position weight in this policy is current
account truth. Runtime effective total is `cash_available + current shares *
canonical close`. The reported account-total field is a reconciliation
reference. Contribution-history fields remain provenance and can never become
the current calculation denominator.

## Validation

The account JSON must contain exactly the C9 fields, use finite non-negative
numbers, include a timezone-aware `last_updated`, keep reserved cash at or
below available cash, and make core/active/cash targets total 100%.
Contribution-history fields need not equal current equity after market movement,
cash flows, or fees and are never silently rewritten to force equality.

Current positions require positive shares. Each held ticker and SPY require exactly one canonical B2 row with a positive price, `data_quality_label=ok`, source, and timestamp.

Reported cash plus current holdings may differ from the last reported total because holdings are repriced while cash is manually maintained. C9 always exposes the difference and labels a material mismatch as a stale reported-total reference; sizing continues from cash plus current holdings. A missing or invalid cash/share input still fails closed.

If the local account file is absent, production fails closed. It never creates a dated example balance or silently invents a current account total.

## Effective research allocation and risk limits

Owner-approved reserve rule, 2026-09-27: there is no mandatory internal
cash reserve. The canonical account `cash_reserved` and configuration reserve
metadata are zero. No additional external reserve amount is recorded or added
to investment capital. This supersedes earlier reserve requirements; historical
snapshots retain their original values. Cash is still limited by actual funds,
order commitments, evidence and position limits. Allocation targets are
subject to the subsequent [October 6 allocation policy](allocation_policy.md):
30% broad-core minimum/baseline target, 70% aggregate stock target/maximum,
zero cash target and no fixed single-stock cap. A target is not a direction to
buy without evidence or a statement of current broker funds.

`account.research_risk_limits` supplies the effective research limits. Under
the October 6 policy, `active_stock_hard_cap_pct` is 70, while
`single_stock_default_cap_pct` and `single_stock_hard_cap_pct` are both `null`:
null explicitly disables a fixed name limit; it is never coerced to zero or
replaced by an archived cap. The configured core minimum and baseline target
are 30, individual-stock target is 70, and cash target is zero. A non-null
supported limit must be finite and internally consistent; an absent or invalid
required policy is not permission to invent a permissive fallback.

Private financial records retain their actual historical values and timestamps.
Effective policy overrides apply to research consumers without making those
records a fresh account observation. Controlled migration of policy metadata
must preserve cash, shares, orders, fills, source evidence and predecessor history.

Research weights, exact-action plans, cash plans, candidate sizing, research
questions and evidence packets use `load_research_account_state()`. Raw
financial validation, snapshots, confirmed-execution reconciliation and writers
continue to use `load_account_state()`. The overlay never changes cash, shares,
account timestamps, the NAV denominator, or account/snapshot hashes. Generated
weight/summary rows and the evidence packet expose the effective caps.

After a separately selected overlay is activated, rebuild all downstream
portfolio and decision artifacts together from the same dated cached inputs.
An old report does not become current simply because configuration changed.

## Manual UI valuation bootstrap

`update_manual_account.py --valuation-snapshot PATH` can record a complete,
explicitly observed manual cash/share snapshot before a newly held symbol has
canonical public prices. The local CSV must contain exactly `ticker`,
`last_price`, `valuation_basis`, `data_source` and `data_timestamp`; every
positive-share position must appear once, prices must be finite and positive,
the basis must be `manual_ui_observation`, and sourced timestamps must be
timezone-aware observations from the current local date. No broker connection
is made by the updater.

The marks value only the reported account-total reference. A private archived
copy and SHA-256 are bound into the existing owner snapshot receipt alongside
before/after account and position hashes. This does not write the canonical B2
snapshot, fabricate Massive provenance, or waive any downstream price gate.
After recording the actual holdings, refresh their public price-only coverage
and regenerate account-aware outputs from validated canonical prices. Run this
sequence under the existing runtime lock. A failed public refresh leaves the
new manual truth recorded and research eligibility blocked, not falsely current.

## Privacy and Execution Boundary

The account file is gitignored and local-user-readable only. C9 does not read SMTP credentials, archived position files, broker accounts, or transaction systems. Every output is research planning for manual confirmation.
