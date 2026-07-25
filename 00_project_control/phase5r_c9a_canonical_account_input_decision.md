# Phase 5R-C9A Canonical Account Input Decision

## Decision

C9 will use an explicit, local account-state input and will recalculate every current position weight. Stored `position_pct` values will be historical/reference data only.

The proposed future account values are:

- Prior assumed account total: `1000 USD`.
- New external investable cash: `1500 USD`.
- Proposed account total: `2500 USD`.

These values are not activated by C9A. C9 must require a human-confirmed `current_account_state.local.json` before producing financial outputs.

## Proposed Sources of Truth

| Financial fact | Proposed canonical source | C9 rule |
| --- | --- | --- |
| Ticker, shares, entry date, entry price, thesis context | `05_risk_and_positions/current_positions.local.csv` | Read shares and entry data; do not accept stored `position_pct` as current truth. |
| Current market price | Latest canonical B2 market snapshot | Match one usable, fresh row per held ticker and retain timestamp/source provenance. Do not parse price from free-form position notes. |
| Account total, available cash, new external cash | Future `05_risk_and_positions/current_account_state.local.json` | Require explicit, human-confirmed numeric fields; do not infer the total from position notes or a phase fallback. |
| Current position market value | C9 calculation | `shares × current market price`. |
| Current position weight | C9 calculation | `position market value ÷ current account total × 100`. |
| Current active-stock sleeve | C9 calculation | Sum recalculated current position weights. |
| Current cash percentage | C9 calculation | `cash_available_usd ÷ current account total × 100`; reconcile against account total and holdings. |
| Current portfolio action | C9 decision generation | Generate dynamically from reconciled account state, current prices, policy thresholds, and current research. |

## Future Local Account-State Contract

The future local JSON should be gitignored and should minimally contain:

- `schema_version`
- `as_of`
- `account_total_usd`
- `cash_available_usd`
- `new_external_cash_usd`
- `currency`
- `human_confirmed_at`
- `notes`

Proposed activation values are `account_total_usd = 2500` and `new_external_cash_usd = 1500`. `cash_available_usd` must be confirmed or reconciled at C9 runtime; C9A does not invent it.

## Required C9 Validation

- Account fields must be finite, non-negative USD amounts with an `as_of` timestamp.
- Each active holding must have positive shares and exactly one usable canonical B2 price.
- Account total must be positive.
- Reconciliation must compare `cash_available_usd + sum(shares × price)` with `account_total_usd` and stop on a material mismatch.
- Every published weight must carry price timestamp, account-state timestamp, and calculation provenance.
- No script may fall back to `1000`, parse an account value from notes, or use stored `position_pct` for current concentration/action logic.

## Migration Boundary

This decision defines inputs and formulas only. No C9 account-state file, calculation implementation, scenario output, or recommendation was created in C9A.
