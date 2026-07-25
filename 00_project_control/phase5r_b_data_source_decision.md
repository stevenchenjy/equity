# Phase 5R-B Data Source Decision

Generated: `2026-07-09T11:40:59-05:00`

## Decision

- Selected data source: `manual_csv_fallback_missing`.
- yfinance available: `no`.
- Manual CSV fallback available: `no`.
- Fail-safe reason: `yfinance unavailable; manual fallback file not present; no market values invented`.

## Boundary

- Canonical input read: `03_source_data/phase5r/phase5r_universe_seed.csv`.
- Archived legacy folders were not read.
- IOT/RBRK legacy holding data was not used.
- No broker, credential, order, trade, or email system was used.
- If no public or manual market data is available, rows remain `insufficient_data`; prices are not invented.
