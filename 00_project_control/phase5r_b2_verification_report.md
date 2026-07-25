# Phase 5R-B2 Verification Report

Generated: `2026-07-25T04:34:16-04:00`

## Required Checks

- **PASS** - Phase 5R-B2 files were created: missing=[].
- **PASS** - benchmark smoke test ran before full universe fetch: smoke_index=0, fetch_index=1.
- **PASS** - yfinance is used only for public market data: imports=['run_phase5r_b2_full_universe_market_data.py'].
- **PASS** - no broker libraries imported: violations=[].
- **PASS** - no order code created: violations=[].
- **PASS** - no .env read: violations=[].
- **PASS** - no API keys used: no environment or credential access found.
- **PASS** - no email code created: violations=[].
- **PASS** - no archived legacy data used: archive_inputs=[].
- **PASS** - canonical universe remains 27 unique research tickers: universe_rows=27, unique=27.
- **PASS** - all ticker-keyed outputs are unique: duplicates={}.
- **PASS** - snapshot contains universe plus current held price-monitoring rows: snapshot_rows=29, expected=29, held_only=['IOT', 'RBRK'].
- **PASS** - quality report matches snapshot ticker coverage: quality_rows=29, expected=29.
- **PASS** - candidate, score, and ticket rows remain universe-only: candidate=27, scores=27, tickets=27.
- **PASS** - current IOT/RBRK rows are held-only price monitoring: price_rows=['IOT', 'RBRK'], held=['IOT', 'RBRK'], candidate_rows=[].
- **PASS** - active 17-column market data schema is exact: snapshot header checked.
- **PASS** - insufficient_data rows are preserved when data is missing: missing_core=[], insufficient=[].
- **PASS** - manual ticket constants are yes/no/no/no: ticket_rows=27.

## Summary

- Canonical universe rows: `27`.
- Held-only price-monitoring rows: `2` (IOT, RBRK).
- Snapshot rows: `29`.
- Candidate rows: `27`.
- Score rows: `27`.
- Manual ticket rows: `27`.
- Missing-core-data candidate rows preserved: `0`.
- The B2 dataset is a single daily, read-only public-market-data refresh. Held-only rows monitor existing positions but are never admitted to candidate scores or tickets. It remains manual-execution-only.
