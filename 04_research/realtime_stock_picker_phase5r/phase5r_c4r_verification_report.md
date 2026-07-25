# Phase 5R-C4R Verification Report

Generated: `2026-07-09T15:42:34-05:00`

## Required Checks

- **PASS** - current_positions.local.csv exists: exists=True.
- **PASS** - current_positions.local.csv is gitignored: gitignored=True.
- **PASS** - IOT and RBRK were read only from current local positions file: tickers=['IOT', 'RBRK'].
- **PASS** - archived legacy IOT/RBRK files were not read: archive_references=False.
- **PASS** - schema validation passed: rows=2, tickers=['IOT', 'RBRK'].
- **PASS** - concentration report created: position_rows=2, hard_cap_rows=2.
- **PASS** - position review queue created: rows=2, trim_review_rows=2.
- **PASS** - portfolio totals are correct: sleeve=47.34, cash=52.66.
- **PASS** - current local positions file remained read-only: unchanged=True.
- **PASS** - no broker libraries imported: violations=[].
- **PASS** - no order code created: violations=[].
- **PASS** - no email sent: email_imports=[], c2_unchanged=True, c3_unchanged=True.
- **PASS** - no scheduler installed or loaded: installed=False, loaded=False.
- **PASS** - SMTP config not modified: metadata_unchanged=True.
- **PASS** - Phase 5R-C5 was not created: paths=[].
- **PASS** - all required C4R files were created: missing=[].

## Portfolio State

- Account value assumption: `1000.00 USD`.
- Active stock sleeve: `47.34%` (`above_target`).
- Estimated cash reserve: `52.66%` (`at_or_above_target`).
- IOT concentration: `29.59%` (`above_hard_cap`).
- RBRK concentration: `17.75%` (`above_hard_cap`).
- Review label for both positions: `trim_review_due_to_concentration`.

## Boundary

These are weekly research-review labels, not sell orders. C4R did not read archived holdings, access a broker, send email, install a scheduler, modify SMTP configuration, or create Phase 5R-C5.
