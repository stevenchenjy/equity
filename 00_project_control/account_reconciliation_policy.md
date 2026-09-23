# Phase 5R-C9B Account Reconciliation Policy

## Preconditions

Reconciliation can be applied only to one explicitly selected `filled` or `partial_fill` execution. The fill date, fill price, fees, share arithmetic, current canonical share count, active C9 maintenance inhibit, and public price quality must all validate. Pending or cancelled rows never mutate canonical state.

## Cash

For a sale, calculated cash after is `cash_before + actual_filled_shares * fill_price - fees`. For a purchase, it is `cash_before - actual_filled_shares * fill_price - fees`. A user-supplied `cash_after` must agree within one cent. If `cash_before` is blank, the validated canonical account cash is used and recorded as the source.

## Account Total

A supplied `account_total_after` is labeled `user_confirmed`. Otherwise C9B estimates account total as reconciled cash plus all post-execution holdings valued with quality-ok B2 public prices and labels it `estimated_public_prices`. The report records the difference between supplied/selected account total and that public-price estimate.

`prior_account_value` and `new_external_cash` retain their contribution-history meaning. After market movement or fees, their sum need not equal current account equity; they are not silently rewritten to force equality.

## Canonical Update

On explicit `--apply`, only the selected ticker's `shares_optional` field changes in `current_positions.local.csv`; entry date, entry price, historical `position_pct`, thesis, horizon, review date, invalidation rule, action text, and notes are preserved. `cash_available`, `account_total_value`, and `last_updated` change in the account state. Other positions, including RBRK unless separately reported, remain unchanged.

After the state update, C9 account-aware outputs and the C9B price-aware plan are regenerated. The reconciliation report stores before/after hashes and whether values were confirmed or estimated. Automatic order behavior, broker access, email delivery, and clearing the maintenance inhibit remain prohibited.
