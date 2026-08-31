# Phase 5R-C9 Verification Report

Generated: `2026-07-19T22:03:20-04:00`

## Result: `PASS`

| Check | Status | Detail |
| --- | --- | --- |
| account_state_exists | PASS | 05_risk_and_positions/current_account_state.local.json |
| account_state_gitignored | PASS | git check-ignore |
| account_state_private_mode | PASS | 0o600 |
| account_total_current_and_positive | PASS | 2500.00 |
| external_cash_confirmed | PASS | 1500.00 |
| cash_available_current_and_nonnegative | PASS | 2026.58 |
| d3_maintenance_inhibit_active | PASS | allowed_pipeline=none |
| required_account_outputs_exist | PASS | missing=0 |
| dynamic_weight_ticker_match | PASS | IOT,RBRK |
| weights_recalculated_from_shares_price_total | PASS | all current positions |
| weight_provenance_complete | PASS | B2 quality=ok and formula recorded |
| stale_denominator_not_current | PASS | all dynamic rows use current account total 2500.00 |
| iot_dynamic_concentration | PASS | weight=12.2624 |
| rbrk_dynamic_concentration | PASS | weight=6.3176 |
| combined_active_sleeve_dynamic | PASS | weight=18.5800 |
| active_sleeve_not_above_30 | PASS | within_target |
| cash_reconciliation_documented | PASS | difference=8.92 |
| iot_whole_share_scenario_dynamic | PASS | change=3; expected=3 |
| rbrk_dynamic_action | PASS | action=hold |
| manual_action_boundary | PASS | all exact actions require human confirmation |
| core_active_cash_separated | PASS | active_stock,cash,core_allocation |
| three_tranche_core_plan_conditional | PASS | three $500 tranches; maintenance blocked |
| no_incomplete_individual_purchase_review | PASS | eligible=0 |
| broad_market_core_separate | PASS | SPY core role present |
| no_broker_libraries_imported | PASS | none |
| no_order_code_created | PASS | none |
| no_email_sent_during_c9 | PASS | 2026-07-18T18:11:45-04:00 |
| c7_no_send_complete | PASS | run_id=phase5r_c7_20260719T213129-0400_no_send; rows=7; failed=0; delivery_skipped=True |

## Protected Inputs

- Current positions SHA-256: `d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c`.
- Account state SHA-256: `28a54007479003aec6535e2586b982a6ea1bdfdc47ac323f189f10d8077a02de`.
- Maintenance inhibit SHA-256: `f04f268c4fa4bc9c204779782565942d8c05833f56d20f724122b1f33877de93`.

## Boundary

C9 uses current shares, canonical B2 public prices, and the confirmed account total. Stored position percentages are emitted only as historical comparison values. No broker, order path, automatic action, archived holding input, credential read, or email send is part of C9.
