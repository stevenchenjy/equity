# Manual Approval Policy

This repo may support research and planning, but it does not authorize or execute real trades.

## Approval Boundary

- Every real trade requires human approval outside this repo.
- Approval must happen after the memo, red-team note, risk calculation, and checklist are complete.
- A script output, AI response, watchlist label, or trade plan is not approval.
- Approval records should avoid sensitive information. Do not store broker logins, account passwords, bank data, card data, API keys, session cookies, or private tokens.

## Required Before Approval

- Completed company memo.
- Completed red-team note or bear-case review.
- Completed risk calculation.
- Confirmed cash-account fit.
- Limit-order plan.
- Stop price, target price, invalidation point, holding period plan, and exit rule.
- Source links from primary or reliable sources.

## Out Of Scope

- Live order placement by Codex or scripts.
- Brokerage API connections.
- Automatic trading.
- Margin, options, short selling, and OTC penny stocks.
