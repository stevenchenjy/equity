# Phase 5R-B2 Full-Universe Data Policy

## Purpose

Phase 5R-B2 creates one read-only daily research dataset for the canonical Phase 5R universe. It supports an AI Investment Research Assistant workflow with low daily attention and manual execution only.

## Permitted Source and Scope

- Candidate membership comes only from `03_source_data/phase5r/phase5r_universe_seed.csv`.
- Current local ticker symbols may be appended to the public market snapshot for C9 position-price monitoring. They are not added to the candidate universe or B2 candidate scores.
- Public market data may be retrieved through `yfinance` after the QQQ, XLK, and SPY preflight succeeds.
- The refresh requests daily historical market data only. B2 itself does not create intraday alerts, a recurring scheduler, an every-15-minute scan, or email delivery.
- The `intraday_change_pct` field represents the latest available session change from the public source and may be delayed.

## Data Handling

- The benchmark preflight runs before any full-universe retrieval.
- A successful preflight requires a current and prior close for QQQ, XLK, and SPY.
- A recognized Yahoo/yfinance rate limit is recorded only as the finite code `yfinance_rate_limited`; response text, URLs, cookies, and credentials are never persisted.
- On any failed required benchmark, B2 stops the remaining benchmark probes immediately. On a rate limit, it records `yfinance_rate_limited`, preserves the prior coherent output trio when available, and exits nonzero. It never performs an immediate or looped retry.
- A local, ignored runtime circuit prevents additional same-day public-source requests before 17:45 ET. At or after that time, it permits at most one consumed post-close recovery attempt; a failure remains blocking and a success must still pass all existing freshness and quality gates.
- Under the existing daily wrapper, a normal public-source fetch is attempted only in the 17:45-or-later slot of a regular U.S. market-session day. Earlier weekday slots, weekends, and the final daily-decision refresh must use the bounded `--reuse-validated-snapshot` path instead.
- Snapshot reuse makes no public-source request, rewrites none of the B2 snapshot/quality/candidate artifacts, and succeeds only when the entire prior trio is coherent and every covered ticker has the exact latest completed market-session date. A reuse failure is nonzero and remains a freshness block for provider and email paths.
- The full refresh requests a one-year daily history to calculate the latest close, prior close, latest volume, 20-session average volume, latest day range, and observed one-year range.
- A completed download is not committed merely because the provider call returned. Before any B2 output is written or the rate-limit state is cleared, the response must have exact ticker coverage, valid core fields, coherent provenance, and the latest completed market-session date for every covered ticker. A partial, empty, stale, or malformed row rejects the entire response with a finite non-sensitive code.
- Rejected full-universe responses never contribute partial live data. B2 preserves a coherent prior trio byte-for-byte when available; otherwise it writes one explicit insufficient-data fallback. No market value or signal is invented.

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
