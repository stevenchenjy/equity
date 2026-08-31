# Phase 0C Reframe Plan

Run timestamp: `2026-07-08T23:22:04-05:00`  
Project root: `/Users/messssi/Desktop/equity`  
Scope: decision layer only. No files were moved, deleted, copied, renamed, imported, or executed.

## Reframe Decision

Phase 5R is a new realtime stock picker with manual execution only. Existing IOT/RBRK real-position monitoring, trade logs, weekly real-position outputs, email automation/preflight, and old execution workflows are legacy context and are excluded from Phase 5R dependencies.

## Decision Counts

- ALLOW_AFTER_REVIEW: 34
- ALLOW_FOR_PHASE5R: 8
- ARCHIVE_EVIDENCE_AFTER_APPROVAL: 141
- DELETE_LATER_LOCAL_CACHE_ONLY: 51
- EXCLUDE_FROM_PHASE5R: 64
- KEEP_POLICY_CONTROL: 6
- KEEP_PROJECT_CONTROL: 19
- LEGACY_QUARANTINE: 52

## Entrypoint Decisions

- exclude: 5
- legacy_only: 7
- needs_review: 2
- phase5r_core: 3
- phase5r_optional: 2

Core Phase 5R workflows:
- `05_scripts/screen_universe.py`: candidate_universe_screening
- `05_scripts/enrich_candidate_financials.py`: financial_enrichment
- `05_scripts/update_sec_filings.py`: sec_filing_ingestion

Optional safe workflows:
- `05_scripts/make_gpt_packet.py`: gpt_packet_generation
- `05_scripts/validate_manual_market_data.py`: manual_market_data_validation

Needs review before use:
- `05_scripts/make_weekly_report.py`: weekly_report_generation
- `05_scripts/risk_calculator.py`: risk_calculator_workflow

Legacy/excluded entrypoints:
- `05_scripts/run_phase2q_paper_risk_calculator.py`: paper_risk_calculator_workflow
- `05_scripts/validate_phase2q_manual_execution_inputs.py`: manual_execution_input_validation
- `05_scripts/validate_phase2o_manual_chart_review.py`: manual_chart_review_validation
- `05_scripts/normalize_phase3b_real_position_inputs.py`: real_position_input_normalization
- `05_scripts/create_phase3b_real_position_log.py`: real_position_log_creation
- `05_scripts/calculate_phase3b_real_risk.py`: real_position_risk_calculation
- `05_scripts/run_phase4a_weekly_real_position_review.py`: current_weekly_review_workflow
- `05_scripts/check_phase4a_sec_filing_alerts.py`: sec_filing_alert_workflow
- `05_scripts/create_phase4a_weekly_action_labels.py`: weekly_action_label_workflow
- `05_scripts/create_phase4b_weekly_email_draft.py`: email_draft_workflow
- `05_scripts/phase5a_email_automation_preflight.py`: email_automation_preflight
- `05_scripts/phase5b_email_preflight_validator.py`: email_preflight_validator

## Blocker Reduction

- Original Phase 0B blockers: `82`.
- Remaining true blockers after legacy quarantine: `0`.
- Optional reuse items requiring human review: `2`.
- Waived legacy/out-of-scope blockers: `69`.
- Cleared control/allowed blockers: `11`.

Original blockers tied to real positions, trade logs, email automation, weekly real-position outputs, historical evidence, or local cache can be waived for Phase 5R because those rows are explicitly out of scope. Policy controls are retained as guardrails rather than treated as blockers. Optional ALLOW_AFTER_REVIEW items are not in the minimum start set and must be reviewed only before reuse.

## Minimum Start Set

The minimum safe start set is listed in `phase0c_phase5r_dependency_allowlist.csv`. It contains policy/project controls, candidate/source files, and analysis-only workflows. Policy documents may mention broker/trade concepts as guardrails, but no allowlisted workflow may connect to a broker or place orders. It does not include broker connectivity, order execution, email automation, trade logs, or old IOT/RBRK holding data.

## Legacy Quarantine

Legacy/quarantine rows are listed in `phase0c_legacy_quarantine_plan.csv`. These rows should be preserved as evidence and not deleted in Phase 0C. IOT/RBRK legacy rows identified for exclusion/quarantine/archive: `46`.

## Manual Execution Boundary

Phase 5R may recommend or rank stocks, but execution must remain manual. No broker API, order placement, automated trade routing, email sending, or use of old real-position holding data is permitted by this gate.

## Next Gate

1. Review the dependency allowlist.
2. Keep legacy real-position, trade-log, and email workflows out of Phase 5R implementation.
3. Create Phase 5R only after accepting this reframe gate.
4. Build new Phase 5R code against allowlisted controls/workflows only.
