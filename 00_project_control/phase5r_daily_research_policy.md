# Phase 5R Daily Research Policy

## Principle

Increase information frequency, not trading frequency. A daily conclusion must
combine current market state, official evidence, long-term fundamentals, and
the canonical local account before it can change a recommendation.

## Source Hierarchy

1. SEC submissions and filing documents.
2. SEC XBRL company facts.
3. Company investor-relations or other official government/exchange sources.
4. Public market data for price, volume, and session freshness.
5. Secondary sources only as context and never as the sole action trigger.

Social media and archived legacy project files are not active inputs.

## Refresh and Freshness Rules

- Held companies and active research candidates are scanned against SEC
  submissions on every scheduled refresh.
- Held-company XBRL fundamentals are refreshed with revenue, prior-year
  revenue, net income, margin, cash, assets, and liabilities when available.
- Quarterly metrics must represent 60–130 day reporting periods; cumulative
  year-to-date facts are rejected as quarter substitutes.
- B2 records both retrieval time and the actual `market_session_date`.
- A held ticker must match the expected U.S. market session and remain usable
  for scoring.
- If a held-company filing, fundamental, market, or account gate is incomplete,
  the system may still communicate a clear HOLD warning but cannot upgrade a
  new action proposal.

## Facts, Estimates, and Opinions

- SEC values and filing metadata are facts with source URLs.
- Local account value uses the canonical local state with public-price
  estimates, not broker account truth.
- Scores and trend labels are deterministic research rules, not facts.
- The email must state that it is research, not a buy/sell instruction.
- Every held-position add, trim, or exit review displayed in the email must
  include the exact whole-share review change, the post-review share count,
  the triggering rationale, and an explicit statement that it is not
  automatically executed.

## Long-Term Interpretation

- Daily price movement alone cannot create an ADD proposal.
- Revenue trend is a long-term evidence layer, not an automatic trade trigger.
- A new ADD proposal requires two different valid closes with the same action
  signature and complete evidence gates.
- Material official filings or contracting held-company revenue trends trigger
  research review, not automatic execution.

## Request Discipline

SEC requests are serialized at approximately five requests per second or less,
comfortably below the published 10 requests-per-second limit. The system uses
no SEC API key and never connects to a broker.
