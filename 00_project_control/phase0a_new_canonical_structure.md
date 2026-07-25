# Phase 0A Canonical Project Structure Proposal

Run timestamp: `2026-07-08T22:59:44-05:00`

This is a proposal only. Phase 0A does not move files.

```text
/equity
  00_project_control/
    phase_register.csv
    audit_reports/
    run_logs/
    cleanup_maps/
  01_policies/
    brokerage_boundary.md
    data_source_policy.md
    manual_approval_policy.md
    risk_policy.md
    trading_checklist.md
  02_universe/
    raw_sources/
    candidate_universe.csv
    selected_candidates.csv
    rejected_candidates.csv
  03_source_data/
    sec_raw/
    filing_notes/
    market_data_manual/
    market_data_validated/
  04_research/
    company_memos/
    gpt_packets/
    filing_excerpts/
    peer_work/
    valuation_work/
    red_team/
    templates/
    sector_frameworks/
  05_risk_and_positions/
    calculators/
    paper_position_reviews/
    real_position_reviews/
    risk_calculation_outputs/
  06_execution_records/
    paper_trades/
    real_trades/
    trade_journal/
    execution_decisions/
  07_automation/
    sec_alerts/
    weekly_review_agent/
    email_drafts/
    email_preflight/
    send_gate_policies/
  08_reviews/
    current/
    weekly/
    monthly/
    phase_archive/
  09_scripts/
    core/
    data_ingestion/
    research_generation/
    risk/
    automation/
    phase_archive/
  10_tests/
    smoke/
    fixtures/
  11_archive/
    historical_phase_outputs/
    superseded_data/
    old_reports/
```

## Mapping Notes

- `00_rules/` should become `01_policies/`, preserving policy files as canonical controls.
- `01_universe/` should become `02_universe/`, split into raw sources, active candidate universe, selected candidates, and rejects.
- `02_filings/` should become `03_source_data/sec_raw` and `03_source_data/filing_notes`.
- `03_research/` should become `04_research/`, with historical phase workpapers archived under `11_archive/historical_phase_outputs` after approval.
- `04_data/` should be split by purpose: universe/source data, risk outputs, position reviews, automation logs, and historical phase data.
- `05_scripts/` should become `09_scripts/`, with reusable scripts separated from one-off phase scripts.
- `06_trading/` should become `06_execution_records/` and remain human-reviewed because it may contain real trade records.
- `07_reviews/` should become `08_reviews/`, separating `current/` snapshots from `phase_archive/` reports.
- `06_logs/` should remain audit/run-log only unless renamed into `00_project_control/run_logs/` in a later approved cleanup.

## Guardrails For Later Migration

- Do not move real-position, trade-log, email, SEC alert, or weekly review files until a human confirms sensitivity and current use.
- Do not add broker connectivity during cleanup.
- Do not create Phase 5R until Phase 0A is accepted and a migration plan is approved.
- Preserve historical phase evidence even when files are superseded.
