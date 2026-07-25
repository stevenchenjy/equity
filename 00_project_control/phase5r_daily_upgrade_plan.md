# Phase 5R Daily Decision Upgrade Plan

Date: 2026-07-23  
Status: implemented and operationally verified

## Outcome

Replace the weekly C7/D3 path with one daily, account-aware research workflow:

- gather public market and official-company evidence more often;
- create one decisive conclusion per day;
- keep portfolio actions deliberately infrequent;
- reduce routine human review;
- suppress low-value weekend email;
- enforce sender-level duplicate protection.

## Cadence

| ET schedule | Purpose | Email |
| --- | --- | --- |
| Weekdays 08:15, 12:30, 16:15, 17:45 | B2 market refresh, SEC filings and XBRL fundamentals, C9 account-aware refresh | Never |
| Weekdays 18:30 | Final refresh, reliability gates, decisive daily conclusion | Once if eligible |
| Weekends 12:00 | Public evidence refresh | Never |
| Weekends 18:30 | Final refresh and decision comparison | Only for a material filing, decision change, or account conflict |

All times use `America/New_York`. launchd polls every 900 seconds; the wrappers
decide whether a slot is due.

## Decision Architecture

1. Validate active workflow, local account, positions, and confirmed execution
   reconciliation.
2. Refresh public B2 prices and preserve the actual market-session date.
3. Scan SEC submissions and retrieve SEC XBRL company facts.
4. Recalculate C9 weights and current-position recommendations.
5. Require market freshness, held-company SEC coverage, and structured account
   consistency.
6. Produce a prominent conclusion such as `继续持有现有仓位｜今天不新增仓位`.
7. Apply a two-distinct-close stability requirement before a new ADD proposal
   can become an action-review candidate.
8. Let the sender decide eligibility again and claim the ET cycle before SMTP.

## Human Review Reduction

| State | Human review |
| --- | --- |
| HOLD / WATCH / NO NEW POSITION | No |
| New ADD proposal before two valid closes | No; remains pending evidence |
| Stable ADD / TRIM / EXIT research proposal | Yes |
| Account or execution-state conflict | Yes |
| New material official filing or material long-term deterioration | Yes |

No automatic portfolio action exists in any state.

## Cutover Sequence

Completed in this order:

1. Retained maintenance inhibit.
2. Retired C2/C3 direct legacy entry points.
3. Unloaded D1, D2, and D3.
4. Moved installed legacy plists to a recoverable retired directory.
5. Changed active state to `daily_decision / phase5r_daily`.
6. Installed `dailyrefresh` and `dailydecision` launchd agents.
7. Ran a complete public-data pipeline with `--no-send`.
8. Passed protected verification.
9. Cleared inhibit only for `phase5r_daily`.
10. Passed operational verification.

`operational_from=2026-07-24`, so activation cannot produce a late-night
catch-up email on 2026-07-23.

## External Basis

- SEC submissions and XBRL APIs provide official, continuously updated company
  data without API keys:
  https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC asks automated clients to remain within 10 requests per second:
  https://www.sec.gov/filergroup/announcements-old/new-rate-control-limits
- Investor.gov emphasizes long-horizon investing and warns that frequent
  trading is generally harmful to long-term returns:
  https://www.investor.gov/build-wealth-over-time-through-saving-and-investing
- FINRA recommends due diligence across company disclosures, competitors,
  revenue, and earnings rather than acting on isolated signals:
  https://www.finra.org/investors/insights/stock-investing-due-diligence
