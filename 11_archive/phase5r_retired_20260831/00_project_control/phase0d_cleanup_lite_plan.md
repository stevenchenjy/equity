# Phase 0D Cleanup-Lite Plan

Run timestamp: `2026-07-08T23:36:24-05:00`
Project root: `/Users/messssi/Desktop/equity`

## Scope

Phase 0D performs minimal safe cleanup only. It may delete `.DS_Store` files, `.pyc` files inside `__pycache__`, and remove empty `__pycache__` directories after those cache files are removed. It may create missing canonical folders only. No project files are moved, renamed, copied, imported, or executed.

## Cache Targets Identified Before Deletion

- `.DS_Store` files: `5`
- `.pyc` files inside `__pycache__`: `46`
- `__pycache__` directories: `2`

## Canonical Folders To Ensure

- `00_project_control/`
- `01_policies/`
- `02_universe/`
- `03_source_data/`
- `04_research/`
- `05_risk_and_positions/`
- `06_execution_records/`
- `07_automation/`
- `08_reviews/`
- `09_scripts/`
- `10_tests/`
- `11_archive/`

## Preservation Rules

- Preserve all Phase 0A/0B/0C reports and run logs.
- Preserve all Phase 5R-A files.
- Preserve all legacy quarantine evidence from `phase0c_legacy_quarantine_plan.csv`.
- Preserve real-position files, trade logs, email workflow files, weekly review files, and risk-rule files.
- Do not delete CSV, Markdown, Python source, TXT, JSON, HTML, or report files.
- Do not create Phase 5R-B.

## Actions Authorized In This Phase

1. Delete only the cache/noise targets listed above.
2. Remove `__pycache__` directories only after allowed cache files are removed and the directories are empty.
3. Create missing canonical folders only; do not move files into them.
