# Phase 5R-C5T Manual Action Policy

## Purpose

Phase 5R-C5T converts the weekly `trim_review` labels into comparable hold, wait, and trim-review scenarios. It is a decision aid for Steven and has no authority to change a portfolio.

## Planning Rules

- Read current positions only from `05_risk_and_positions/current_positions.local.csv`.
- Use the account-value assumption in the local notes when available; otherwise use `1000 USD`.
- Preserve C5 conviction scores and the C4 concentration limits as context.
- Show fractional-share estimates and a separate whole-share practical scenario.
- Treat taxes, transaction costs, lot selection, and account-specific restrictions as unknown human-review items.
- A scenario is not a recommendation to act. Waiting until the next scheduled review is always a valid choice.

## Boundaries

- Manual decision required for every scenario.
- No automatic portfolio action is allowed.
- No broker, account connection, email delivery, scheduler activation, credential access, or archived holding input.
- Phase 5R-C6 remains out of scope.

## Concentration References

- Single-stock default cap: `6%`.
- Single-stock hard cap: `8%`.
- Active stock sleeve target: `30%`.
- Cash reserve target: `10%`.
