# Phase 5R-B2 Full-Universe Data Policy

## Purpose

Phase 5R-B2 creates one read-only daily research dataset for the canonical Phase 5R universe. It supports an AI Investment Research Assistant workflow with low daily attention and manual execution only.

## Permitted Source and Scope

- Candidate membership comes only from `03_source_data/phase5r/phase5r_universe_seed.csv`.
- Current local ticker symbols may be appended to the public market snapshot for C9 position-price monitoring. They are not added to the candidate universe or B2 candidate scores.
- Public market data may be retrieved only through the Massive Stocks Basic end-of-day Custom Bars path after the QQQ, XLK, and SPY preflight succeeds. Massive is the sole active remote production source for B2; Yahoo/yfinance and every other public market-data source are prohibited as a fetch or fallback.
- The Massive request must explicitly use `adjusted=false`, preserving the unadjusted B2 close/range/volume basis.
- The required `MASSIVE_API_KEY` may be supplied only by the external process runtime. Its value must not be placed in this repository, a `.env` file, a launchd plist, source code, a report, a receipt, or a shell transcript.
- The refresh requests daily historical market data only. B2 itself does not create intraday alerts, a recurring scheduler, an every-15-minute scan, or email delivery.
- The `intraday_change_pct` field represents the latest completed-session change derived from the Massive end-of-day bars.

## Data Handling

- Provider-SLA decision: Massive identifies Stocks Basic as end-of-day data,
  and its official day-aggregate documentation says finalized daily datasets
  become available at approximately 11:00 ET on the following day. Production
  uses 11:15 ET as a conservative publication boundary. References:
  [Stocks pricing](https://massive.com/pricing?product=stocks) and
  [day aggregates](https://massive.com/docs/flat-files/stocks/day-aggregates).
- A bounded 2026-09-01 runtime diagnostic confirmed the contract mismatch:
  the prior session's grouped daily result was available while the same-day
  session was forbidden under the active Basic credential. No credential
  value or provider response body was retained.
- Massive Stocks Basic is limited to five API calls per minute. The adapter enforces a conservative minimum request interval and performs no automatic retry or pagination follow-up.
- The active production fetch is limited to the exact approved 29-ticker scope (27 canonical candidates plus held-only IOT and RBRK). Any scope change blocks before client construction and requires a separately reviewed update.
- The benchmark preflight runs before any full-universe retrieval.
- A successful preflight requires a current and prior close for QQQ, XLK, and SPY.
- A recognized Massive rate limit is recorded only as the finite code `massive_rate_limited`; response text, URLs, headers, and credentials are never persisted.
- On any failed required benchmark, B2 stops the remaining benchmark probes immediately, preserves the prior coherent output trio when available, and exits nonzero. It never performs an immediate, looped, or alternate-source retry.
- Massive Basic is gated by provider publication, not merely market close. The canonical latest-published session is the prior calendar day's market session at or after 11:15 ET, and the normalized session two calendar days back before 11:15 ET.
- Under the daily wrapper, a normal Massive fetch is attempted only at the bounded next-day publication slots 11:15, 11:45, 12:15, and 12:45 ET. These slots also run on Saturday so Friday's finalized close can be consumed. The 08:15 weekday refresh and the final daily-decision path use `--reuse-validated-snapshot` instead.
- The scheduler durably reserves each publication attempt before starting the child. A crash, timeout, provider failure, or later deterministic-step failure cannot repeat that attempt on an intervening 15-minute tick; only the next configured publication slot may retry. All later slots are reserved after the first fully passed refresh.
- Snapshot reuse makes no public-source request, rewrites none of the B2 snapshot/quality/candidate artifacts, and succeeds only when the entire prior trio is coherent and every covered ticker has the exact latest published market-session date. A reuse failure is nonzero and remains a freshness block for provider and email paths.
- During this one-way migration, an existing coherent trio labeled with the former local yfinance provenance may be read only to validate, preserve byte-for-byte after a Massive failure, or validate no-network reuse. It never authorizes a Yahoo/yfinance request, an alternate remote source, re-dating, a successful current refresh, or a substitution for Massive data.
- The full refresh requests a one-year daily history to calculate the latest close, prior close, latest volume, 20-session average volume, latest day range, and observed one-year range. The returned session-date sequence must exactly cover every expected U.S. market session in that window; gaps, duplicate session dates, or a truncated history reject the row.
- A completed download is not committed merely because the provider call returned. Before any B2 snapshot, quality, or candidate output is written, the response must have exact ticker coverage, valid core fields, coherent provenance, and the latest published market-session date for every covered ticker. A partial, empty, stale, or malformed row rejects the entire response with a finite non-sensitive code.
- Rejected full-universe responses never contribute partial live data. The existing B2 output trio remains byte-for-byte unchanged whether it is coherent, stale, or already invalid; downstream gates continue to reject it until a complete valid Massive batch replaces it. No fallback market value or signal is invented.
- Scoring independently compares each candidate row with the latest published market session and emits `insufficient_data` rather than an actionable-looking score for a preserved stale row.

## Scoring

The daily research score is:

`0.30 * trend_score + 0.25 * volume_score + 0.20 * catalyst_score + 0.15 * quality_score - 0.10 * risk_penalty`

Scores are research prioritization only. They are not investment advice, an order instruction, a broker signal, or a replacement for independent review.

## Safety Boundary

- No broker libraries, brokerage accounts, order placement, order routing, or execution automation.
- No credential or API-key value may be stored, printed, logged, hashed, persisted, or loaded from a repository file, `.env` file, or launchd plist. The exact external-runtime `MASSIVE_API_KEY` boundary is permitted solely for the active Massive adapter.
- No archived legacy files. For current-position price monitoring, B2 may read ticker symbols only from `05_risk_and_positions/current_positions.local.csv`; it must not use stored weights, notes, account values, or actions.
- Each generated ticket requires a human confirmation and explicitly prohibits broker connection and real-order capability.
- Phase 5R-C is outside this phase.
