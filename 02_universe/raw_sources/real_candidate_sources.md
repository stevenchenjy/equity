# Real Candidate Source Rules

Use this file when moving from system-test fixtures to a real research universe. Do not add a ticker unless the source path is clear and the idea is not based only on hype.

## Acceptable Source Types

- SEC EDGAR company search.
- Nasdaq IPO calendar or official exchange IPO pages.
- Company investor relations pages.
- Official earnings releases.
- FDA official pages for biotech.
- Reputable financial data pages for market cap and liquidity.
- Company 10-K, 10-Q, 8-K, S-1, and 424B filings.

## Blocked Source Types

- Social-media-only tickers.
- Forum hype.
- Influencer stock picks.
- Pump-and-dump style newsletters.
- OTC penny stock lists.
- Paid API output unless manually approved in a later phase.

## Entry Rules

- Use `MISSING` for unknown fields.
- Include source links for every row.
- Do not label anything as `real_trade_candidate`.
- Do not create buy/sell recommendations.
- Do not include OTC penny stock promotion.
