# Phase 5R-B1 Market Data Enablement Plan

Generated: `2026-07-09`

## Direction

Phase 5R-B1 supports the new AI Investment Research Assistant direction:

- Low-attention daily research workflow.
- Manual execution only.
- No day-trading rhythm.
- Email delivery is out of scope for this phase.

## Goal

Enable a usable read-only market data source before any email delivery work begins.

## Steps

1. Read only the canonical Phase 5R universe:
   `03_source_data/phase5r/phase5r_universe_seed.csv`
2. Confirm IOT/RBRK are absent.
3. Create a manual market data fallback template with required market fields.
4. Check whether `yfinance` is installed.
5. If `yfinance` is unavailable, write exact install instructions and do not fail the phase.
6. If `yfinance` is available, run a read-only smoke test on QQQ, XLK, and SPY only.
7. Do not fetch the full universe until a benchmark smoke test passes.
8. Generate a data-readiness report and verification report.

## Non-Actions

- No broker connection.
- No order placement or order code.
- No `.env` read.
- No API keys.
- No email sending or email workflow creation.
- No archived legacy files.
- No old IOT/RBRK holding data.
- No Phase 5R-C artifacts.

## Install Command

```bash
python3 -m pip install yfinance
```

After installing, rerun:

```bash
python3 09_scripts/phase5r/check_phase5r_b1_market_data_source.py
python3 09_scripts/phase5r/verify_phase5r_b1_data_enablement.py
```
