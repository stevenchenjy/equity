# Phase 5R-B Data Adapter Policy

Generated: `2026-07-09`

## Purpose

Phase 5R-B adds a read-only market data adapter to the Phase 5R manual stock picker. It may attach public market data to the canonical Phase 5R universe, but it must not automate execution.

## Allowed Inputs

- `03_source_data/phase5r/phase5r_universe_seed.csv`
- Optional manual fallback CSV at `03_source_data/phase5r/phase5r_b_manual_market_data_fallback.csv` if a human creates it later
- Public market data through a market-data-only library such as `yfinance`, if the library is available

## Forbidden Inputs

- `11_archive/legacy_pre_5r_root_20260709/`
- Old IOT/RBRK holding data
- Real-position files
- Trade logs
- Broker account data
- Email or Gmail workflow files
- `.env` files or credential stores

## Adapter Boundary

- The adapter is read-only.
- It may fetch or accept market data only.
- It must not import broker libraries.
- It must not read credentials or API keys.
- It must not place, route, stage, or simulate orders.
- It must not send email.
- It must not create Phase 5R-C artifacts.

## Fallback Rule

If `yfinance` is unavailable or fails, Phase 5R-B must fail safely into manual CSV fallback mode. If no manual fallback CSV exists, it must create market rows with `data_quality_label=insufficient_data` and must not invent prices, volume, or signals.

## Manual Execution Boundary

All Phase 5R-B trade tickets are manual review artifacts. Required constants:

- `manual_confirmation_required=yes`
- `broker_connection_allowed=no`
- `real_order_allowed_by_script=no`
- `old_holding_data_used=no`
