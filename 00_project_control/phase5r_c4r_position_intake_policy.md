# Phase 5R-C4R Current Position Intake Policy

## Purpose

Phase 5R-C4R refreshes portfolio state from the private, Git-ignored file `05_risk_and_positions/current_positions.local.csv` for future weekly conviction research. It validates the minimum C4 schema and computes concentration from `position_pct` using an account-value assumption of `1000 USD`.

## Source Boundary

- The local current-positions file is the only position-data source.
- IOT and RBRK in that file are current local positions and are allowed inputs.
- Archived IOT/RBRK notes, holding files, reviews, logs, and risk calculations remain prohibited.
- No broker account, email system, SMTP configuration, scheduler, or cloud service is read or used.

## Privacy Boundary

Generated reports include only the information needed for validation, concentration, and weekly review routing. They do not copy thesis text, invalidation text, optional share counts, raw entry prices, or free-form notes from the private file.

## Concentration Rules

- `position_pct > 8`: `above_hard_cap` and `trim_review_due_to_concentration`.
- `position_pct > 6 and <= 8`: `above_default_cap`.
- `position_pct <= 6`: `within_default_cap`.
- Active stock sleeve above `30%`: `above_target`.
- Estimated cash below `10%`: `below_target`.
- Technology and AI-infrastructure exposure remain not evaluable because those classifications are not part of the minimum private position schema.

All review labels are weekly research prompts only. They are not sell orders and cannot execute transactions.
