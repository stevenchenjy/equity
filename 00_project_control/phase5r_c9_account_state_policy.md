# Phase 5R-C9 Account-State Policy

## Canonical Inputs

- Shares, entry date, entry price, thesis, horizon, and invalidation context: `05_risk_and_positions/current_positions.local.csv`.
- Reported account-total reference, prior value, external cash, available cash, reserve, horizon, and allocation limits: gitignored `05_risk_and_positions/current_account_state.local.json`.
- Current prices and provenance: `03_source_data/phase5r/phase5r_b2_market_data_snapshot.csv`.
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

## Privacy and Execution Boundary

The account file is gitignored and local-user-readable only. C9 does not read SMTP credentials, archived position files, broker accounts, or transaction systems. Every output is research planning for manual confirmation.
