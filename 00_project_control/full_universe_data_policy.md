# Phase 5R-B2 Configured-Universe Data and Broad Discovery Policy

## Purpose

Phase 5R-B2 creates one read-only daily research dataset for the canonical Phase 5R universe. It supports an AI Investment Research Assistant workflow with low daily attention and manual execution only.

"Full universe" in legacy B2 filenames means the configured 31 candidates plus
the current local held-only symbols. It does not mean the entire listed market. The separate
market-discovery extension below implements the owner's September 22 request
for independent broad screening, without changing B2's evidence contract.

## Permitted Source and Scope

- Candidate membership comes only from `03_source_data/equity_research/universe_seed.csv`.
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
- The production candidate set remains the exact approved 31 symbols. Added, missing, replaced or duplicate candidate symbols block before client construction, including no-network reuse. The September 24 held-position repair allows valid, unique ticker symbols from the current local positions file to extend price monitoring only; sold held-only symbols are no longer required. These rows receive the same complete Massive history, quality, freshness and atomic-trio checks, without admission to candidate scoring. Existing request pacing, no-retry behavior and bounded child runtime remain unchanged; an oversized or slow refresh fails visibly rather than loosening validation.
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

As of September 22, `catalyst_score` is neutral at 5 for every B2 row: a theme
label is not a verified event. The legacy trend field is a one-session measure;
the quality field is a manually assigned liquidity-tier proxy. This score
describes configured-watchlist monitoring, not a market-wide investment rank.

## Safety Boundary

- No broker libraries, brokerage accounts, order placement, order routing, or execution automation.
- No credential or API-key value may be stored, printed, logged, hashed, persisted, or loaded from a repository file, `.env` file, or launchd plist. The exact external-runtime `MASSIVE_API_KEY` boundary is permitted solely for the active Massive adapter.
- No archived legacy files. For current-position price monitoring, B2 may read ticker symbols only from `05_risk_and_positions/current_positions.local.csv`; it must not use stored weights, notes, account values, or actions.
- Each generated ticket requires a human confirmation and explicitly prohibits broker connection and real-order capability.
- Phase 5R-C is outside this phase.

## Tactical research extension (September 22, 2026)

After a complete validated batch, retain the last 20 daily OHLCV bars in an ignored local sidecar, bound by SHA-256 to the canonical snapshot. A failed batch preserves prior artifacts; old or mismatched history cannot authorize a tactical draft. QQQM and XLI are ETFs exempt from company XBRL valuation, not newly approved core allocations. The deterministic daily plan uses completed published data and cannot verify live entry triggers.

## Independent broad-market discovery extension (September 22, 2026)

The owner explicitly broadened discovery beyond their watchlist. For this
separate read-only layer, Massive Stocks Basic may additionally retrieve
`/v3/reference/tickers` (bounded, same-origin complete pagination) and
`/v2/aggs/grouped/locale/us/market/stocks/{date}` (all-market daily OHLCV).
Official references: [All Tickers](https://massive.com/docs/rest/stocks/tickers/all-tickers)
and [Daily Market Summary](https://massive.com/docs/rest/stocks/aggregates/daily-market-summary).
This is a reviewed exception to the B2 Custom Bars-only scope above, not
permission to alter B2's approved candidate set or use another market provider.

The extension screens active, exchange-listed US common stocks and ETFs, with
explicit exclusions and coverage counts. It excludes OTC, non-common-stock
security types, insufficient history, sub-$5 prices and less than $20 million
average daily dollar turnover. Liquidity thresholds are research assumptions,
not backtested optimal settings. Leveraged/inverse/option-related ETF name
filters are conservative heuristics; every remaining ETF still requires issuer
structure review before it becomes a researched setup. ADRs are outside the
initial CS/ETF reference-type scope and must be disclosed as a limitation.

Use `include_otc=false` and `adjusted=true` on grouped data. Split-adjusted
discovery returns are a separate basis from B2's unadjusted account prices;
never substitute discovery bars for canonical order-price evidence. Retain 21
published sessions and cache reference metadata. Rank stocks and ETFs separately
using measured strength/volume inputs, without watchlist, theme or held-status
bonuses. Portfolio fit and position sizing come after discovery. The heuristic
score is not an expected return, confirmed catalyst or validated trading edge.

Use only the existing external-runtime Authorization header. No keys in query
strings, files or diagnostics; no redirects; bounded response sizes, request
counts and timeouts; at least 13 seconds between requests and no immediate
retry. Run beneath the existing runtime lock. Bootstrap through the explicit
no-send discovery entrypoint, then incrementally refresh during existing EOD
publication slots. No new scheduler, subscription or email recipient is added.
Local-only refresh cycles make no discovery network requests.

Cache/output files live in ignored `market_discovery.local/`. Complete metadata
and published-session validation are required before claiming full configured
discovery coverage. Missing/stale/failed data must be reported, never masked by
the legacy watchlist. Discovery outputs feed a separate watch-only report with
zero cleared shares, not the canonical eligible-order list. Broad screening
does not imply fundamental or catalyst diligence on every listed company.
