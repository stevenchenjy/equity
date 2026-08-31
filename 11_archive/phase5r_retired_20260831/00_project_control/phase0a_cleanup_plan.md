# Phase 0A Cleanup Plan

Run timestamp: `2026-07-08T22:59:44-05:00`  
Scope: baseline files under `/Users/messssi/Desktop/equity` captured before Phase 0A report writes.

## Executive Summary

- Baseline files inventoried: `365`.
- Exact duplicate content groups: `3`.
- Same-basename duplicate candidate groups: `2`.
- Broken/missing project path references found by heuristic scan: `12` actual missing, plus `15` placeholder/glob references not counted as broken.
- Phase 5R files found: `0`.
- `.env`-style files read: `0`.

## Classification Counts

- KEEP: 88
- MIGRATE: 49
- ARCHIVE: 84
- DELETE_CANDIDATE: 51
- NEEDS_HUMAN_REVIEW: 93

## Operational Touchpoints

- real_positions: 44
- risk_rules: 99
- email_drafts: 32
- sec_alerts: 16
- weekly_reviews: 57
- trade_logs: 36

Files touching real positions, risk rules, email drafts, SEC alerts, weekly reviews, and trade logs are listed separately in `phase0a_real_position_file_map.csv`. Anything involving real positions, trade logs, email sending, recipients, SEC alerts, or weekly operational reviews should be manually confirmed before any migration.

## Duplicate And Redundancy Findings

- Exact hash duplicates are listed in `phase0a_duplicate_file_report.csv` with `duplicate_type=EXACT_SHA256`.
- Same-basename candidates are listed with `duplicate_type=SAME_BASENAME`; these are not always true duplicates, but they are useful cleanup review targets.
- Generated files such as `.DS_Store` and `__pycache__/*.pyc` are classified as `DELETE_CANDIDATE`, but no deletion should occur in Phase 0A.

## Broken Path Findings

- Missing project path references are listed in `phase0a_broken_path_report.csv`; glob/template references are marked separately and are not counted as broken paths.
- The scan inspected readable project text files only and skipped `.env`-style files and git internals.
- Any missing path in a historical phase report may simply reflect a stale plan; missing paths in scripts should be fixed before reuse.

## Outdated Phase Files And Old Reports

- phase2b: 1 historical artifact(s).
- phase2c: 2 historical artifact(s).
- phase2e: 23 historical artifact(s).
- phase2e1: 25 historical artifact(s).
- phase2f: 15 historical artifact(s).
- phase2g: 11 historical artifact(s).
- phase2h: 12 historical artifact(s).
- phase2i: 10 historical artifact(s).
- phase2j: 16 historical artifact(s).
- phase2k: 15 historical artifact(s).
- phase2l: 14 historical artifact(s).
- phase2m: 9 historical artifact(s).
- phase2n: 9 historical artifact(s).
- phase2o: 4 historical artifact(s).
- phase2p: 2 historical artifact(s).
- phase2q: 11 historical artifact(s).
- phase2r: 8 historical artifact(s).

Historical phase reports under `07_reviews/phase*.md` and phase-specific workpapers under `03_research/*phase*` should be preserved as evidence but moved to an archive only after human approval.

## Potentially Unused Or One-Off Scripts

- `05_scripts/audit_phase3a_real_position_structure.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.
- `05_scripts/audit_phase3c_agent_restructure.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/calculate_phase3b_real_risk.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 8.
- `05_scripts/check_phase4a_sec_filing_alerts.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.
- `05_scripts/collect_phase2k_peer_data.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 4.
- `05_scripts/create_phase2h_manual_review_worksheets.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/create_phase2j_scenario_peer_workpapers.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/create_phase2l_valuation_earnings_workpapers.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/create_phase2m_research_decision_review.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/create_phase2n_paper_plan_drafts.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/create_phase2o_paper_execution_readiness.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/create_phase2p_paper_execution_log_setup.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/create_phase2q_execution_decision_gate.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.
- `05_scripts/create_phase2r_paper_execution_log.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/create_phase3b_real_position_log.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.
- `05_scripts/create_phase4a_weekly_action_labels.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.
- `05_scripts/create_phase4b_weekly_email_draft.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/extract_phase2f_filing_excerpts.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/normalize_phase2q_filled_inputs.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/normalize_phase3b_real_position_inputs.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.
- `05_scripts/phase5a_email_automation_preflight.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/phase5b_email_preflight_validator.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/rescore_phase2e1_candidates.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.
- `05_scripts/run_phase2q_paper_risk_calculator.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 8.
- `05_scripts/run_phase4a_weekly_real_position_review.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/score_phase2e_candidates.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/score_phase2f_memos.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/score_phase2k_peer_data_quality.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 5.
- `05_scripts/synthesize_phase2i_human_notes.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 4.
- `05_scripts/validate_manual_market_data.py`: generated-workflow utility; confirm whether it remains an active entry point; inbound text references found: 6.
- `05_scripts/validate_phase2o_manual_chart_review.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 6.
- `05_scripts/validate_phase2q_manual_execution_inputs.py`: phase-specific script; review for migration or archival before reuse; inbound text references found: 7.

Scripts with no inbound text references may still be valid manual entry points. Treat this section as a review queue, not a deletion list.

## Inconsistent Naming To Resolve

- `07_reviews/phase0_audit_report.md` uses `phase0` while the current audit uses `phase0a`; keep the distinction explicit in a phase register.
- Mixed latest/current naming exists in `07_reviews/latest_*` alongside phase-numbered reports; canonical structure should separate current snapshots from historical reports.
- Phase suffixes mix granular forms such as `phase2e`, `phase2e1`, and `phase2q_*_after_filled_inputs`; a phase register should define accepted suffixes and rerun labels.
- `04_data/screening_results.csv` and `04_data/phase2b_candidate_screening_results.csv` appear semantically overlapping; review before choosing a canonical screening output.
- `01_universe/universe.csv`, `01_universe/real_candidate_universe.csv`, and `01_universe/phase2c_selected_candidates.csv` should be reconciled into raw, selected, and active universe tiers.
- Runtime areas are split between `06_trading` and the newly requested `06_logs`; canonical structure should separate execution records from audit/run logs.

## Recommended Cleanup Sequence

1. Freeze Phase 0A reports as the audit baseline.
2. Create a phase register mapping every `phase*` artifact to owner, status, and canonical destination.
3. Review all `NEEDS_HUMAN_REVIEW` files, especially real positions, trade logs, email drafts, SEC alert workflows, weekly reviews, and risk rules.
4. Approve a migration map from `MIGRATE` files to the canonical structure.
5. Archive historical phase outputs after approval; do not delete evidence files.
6. Delete only confirmed local noise such as `.DS_Store` and `__pycache__` in a later cleanup phase.
7. Keep Phase 5R uncreated until this audit is accepted.

## Non-Actions In Phase 0A

No files were moved or deleted. No broker connection was made. No trade/order code was executed. No `.env` file content was read.
