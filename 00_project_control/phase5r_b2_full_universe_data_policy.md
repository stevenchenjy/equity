# Phase 5R-B2 Full-Universe Data Policy

## Purpose

Phase 5R-B2 creates one read-only daily research dataset for the canonical Phase 5R universe. It supports an AI Investment Research Assistant workflow with low daily attention and manual execution only.

## Permitted Source and Scope

- Candidate membership comes only from `03_source_data/phase5r/phase5r_universe_seed.csv`.
- Current local ticker symbols may be appended to the public market snapshot for C9 position-price monitoring. They are not added to the candidate universe or B2 candidate scores.
- Public market data may be retrieved through `yfinance` after the QQQ, XLK, and SPY preflight succeeds.
- The refresh requests daily historical market data only. It does not create intraday alerts, a recurring scheduler, an every-15-minute scan, or email delivery.
- The `intraday_change_pct` field represents the latest available session change from the public source and may be delayed.

## Data Handling

- The benchmark preflight runs before any full-universe retrieval.
- A successful preflight requires a current and prior close for QQQ, XLK, and SPY.
- The full refresh requests a one-year daily history to calculate the latest close, prior close, latest volume, 20-session average volume, latest day range, and observed one-year range.
- Rows with incomplete data remain in the dataset with blank unavailable fields and `data_quality_label=insufficient_data`; no market value or signal is invented.

## Scoring

The daily research score is:

`0.30 * trend_score + 0.25 * volume_score + 0.20 * catalyst_score + 0.15 * quality_score - 0.10 * risk_penalty`

Scores are research prioritization only. They are not investment advice, an order instruction, a broker signal, or a replacement for independent review.

## Safety Boundary

- No broker libraries, brokerage accounts, order placement, order routing, or execution automation.
- No credentials, API keys, `.env` files, email sending, or email scheduling.
- No archived legacy files. For current-position price monitoring, B2 may read ticker symbols only from `05_risk_and_positions/current_positions.local.csv`; it must not use stored weights, notes, account values, or actions.
- Each generated ticket requires a human confirmation and explicitly prohibits broker connection and real-order capability.
- Phase 5R-C is outside this phase.
