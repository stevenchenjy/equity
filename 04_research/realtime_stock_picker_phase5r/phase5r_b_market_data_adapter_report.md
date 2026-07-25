# Phase 5R-B Market Data Adapter Report

Generated: `2026-07-09T11:40:59-05:00`

## Adapter Summary

- Universe rows processed: `27`.
- Selected data source: `manual_csv_fallback_missing`.
- yfinance available: `no`.
- Manual CSV fallback available: `no`.
- Data quality counts: `{'insufficient_data': 27}`.
- Fail-safe note: `yfinance unavailable; manual fallback file not present; no market values invented`.

## Safety Boundary

- Read-only market data only.
- Manual execution only.
- No archived legacy input.
- No IOT/RBRK holding data.
- No broker imports, broker accounts, orders, email, credentials, or environment files.
