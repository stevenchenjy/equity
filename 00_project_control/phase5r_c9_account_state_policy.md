# Phase 5R-C9 Account-State Policy

## Canonical Inputs

- Shares, entry date, entry price, thesis, horizon, and invalidation context: `05_risk_and_positions/current_positions.local.csv`.
- Account total, prior value, external cash, available cash, reserve, horizon, and allocation limits: gitignored `05_risk_and_positions/current_account_state.local.json`.
- Current prices and provenance: `03_source_data/phase5r/phase5r_b2_market_data_snapshot.csv`.
- Current public research evidence: controlled C5 packet fields; portfolio-fit fields from the old packet are not authoritative.

## Runtime State

No dollar amount, share count, or position weight in this policy is current
account truth. Runtime values come only from the validated local account and
position inputs above. Contribution-history fields may be retained for
provenance, but they can never become the current calculation denominator.

## Validation

The account JSON must contain exactly the C9 fields, use finite non-negative
numbers, include a timezone-aware `last_updated`, keep reserved cash at or
below available cash, and make core/active/cash targets total 100%.
Contribution-history fields need not equal current equity after market movement,
cash flows, or fees and are never silently rewritten to force equality.

Current positions require positive shares. Each held ticker and SPY require exactly one canonical B2 row with a positive price, `data_quality_label=ok`, source, and timestamp.

Reported cash plus current holdings may differ modestly from the confirmed total because holdings are repriced while cash is an estimate. C9 accepts and documents a difference no larger than the greater of `25 USD` or `1%` of account total. A larger difference stops the workflow for account-state refresh.

## Privacy and Execution Boundary

The account file is gitignored and local-user-readable only. C9 does not read SMTP credentials, archived position files, broker accounts, or transaction systems. Every output is research planning for manual confirmation.
