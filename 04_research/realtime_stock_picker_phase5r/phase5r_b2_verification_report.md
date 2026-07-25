# Phase 5R-B2 Verification Report

Generated: `2026-07-09T13:22:37-05:00`

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
- **PASS** - IOT/RBRK absent: legacy=[].
- **PASS** - full universe data rows created: snapshot_rows=27, universe_rows=27.
- **PASS** - required market data columns exist: snapshot header checked.
- **PASS** - insufficient_data rows are preserved when data is missing: missing_core=[], insufficient=[].
- **PASS** - manual ticket constants are yes/no/no/no: ticket_rows=27.
- **PASS** - Phase 5R-C was not created: paths=[].

## Summary

- Canonical universe rows: `27`.
- Snapshot rows: `27`.
- Score rows: `27`.
- Manual ticket rows: `27`.
- Missing-core-data rows preserved: `0`.
- The B2 dataset is a single daily, read-only public-market-data refresh. It remains manual-execution-only.
