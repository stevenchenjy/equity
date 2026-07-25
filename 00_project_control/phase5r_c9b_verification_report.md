# Phase 5R-C9B Verification Report

Generated: `2026-07-20T23:17:01-04:00`

## Result: `PASS`

| Check | Status | Detail |
| --- | --- | --- |
| execution_file_exists_and_gitignored | PASS | local file exists; private mode 0o600; git check-ignore passed |
| execution_id_unique | PASS | C9B-IOT-PENDING-001 appears exactly once in 1 preserved row |
| confirmed_execution_identity | PASS | ticker=IOT; side=sell; status=filled |
| confirmed_fill_quantity | PASS | filled shares=3; shares before=8; shares after=5 |
| confirmed_fill_values | PASS | fill date=2026-07-20; fill price=37.7000; fees=0.00 |
| gross_proceeds | PASS | 3 x 37.70 = 113.10 USD |
| net_proceeds | PASS | 113.10 - 0.00 = 113.10 USD |
| no_fill_value_invented | PASS | fill date, price, quantity, and fees came from the user-confirmed execution |
| confirmed_report_valid | PASS | validation_status=valid_filled; reconciliation_eligible=yes; canonical_state_applied=no |
| reconciliation_preview_valid | PASS | reconciliation_status=validated_preview_not_applied |
| preview_cash_after | PASS | 2026.58 + 113.10 = 2139.68 USD |
| preview_account_total_after | PASS | 2489.22 USD using quality=ok public reference prices |
| preview_iot_weight | PASS | 5 shares x 38.32 / 2489.22 = 7.6972% |
| preview_rbrk_weight | PASS | 2 shares x 78.97 / 2489.22 = 6.3450% |
| current_positions_unchanged | PASS | SHA-256 remained d2941bd90ecb4318a8d6501ddf77ea576606b47c3e746712a813b3bb2f5ede6c |
| current_account_state_unchanged | PASS | SHA-256 remained 28a54007479003aec6535e2586b982a6ea1bdfdc47ac323f189f10d8077a02de |
| canonical_apply_not_run | PASS | canonical_state_applied=no; positions_modified=no; account_state_modified=no |
| maintenance_inhibit_active | PASS | active=true; allowed_pipeline=none |
| no_email_sent | PASS | C6 and C2 delivery-status files remained unchanged during this run |
| no_broker_or_order_api | PASS | validator and preview reconciler use local files only |
| smtp_configuration_unchanged | PASS | size and modification time unchanged; SMTP config content was not read |
| archived_legacy_positions_unused | PASS | inputs were canonical/local C9B files and the canonical B2 snapshot only |
| separate_apply_readiness | PASS | preview checks pass; a later explicit --apply remains separately required |

## Current State

The IOT execution is `filled`; 3 shares at $37.70 with $0.00 fees produce $113.10 gross and net proceeds. Reconciliation is a validated preview only, and canonical-state application remains `no`.

## Boundary

C9B recorded a human-confirmed fill and generated a local preview. It did not connect to a broker, place or modify an order, infer a fill value, send email, clear the maintenance inhibit, read archived positions, or apply canonical state.
