# Phase 5R-C9 Account-State Policy

## Canonical Inputs

- Shares, entry date, entry price, thesis, horizon, and invalidation context: `05_risk_and_positions/current_positions.local.csv`.
- Reported account-total reference, prior value, external cash, available cash, reserve, horizon, and allocation limits: gitignored `05_risk_and_positions/current_account_state.local.json`.
- Current prices and provenance: `03_source_data/equity_research/market_data_snapshot.csv`.
- Current public research evidence: controlled C5 packet fields; portfolio-fit fields from the old packet are not authoritative.

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

## Optional research-only risk limits

`account.research_risk_limits` in the active production configuration may
override exactly `active_stock_hard_cap_pct`, `single_stock_default_cap_pct`
and `single_stock_hard_cap_pct` for research consumers. It is optional and is
not activated merely by installing its supporting code. The three values must
be finite numeric percentages with `0 < default <= single hard <= active hard
<= 100`; the active hard cap cannot be below the recorded active target.

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
