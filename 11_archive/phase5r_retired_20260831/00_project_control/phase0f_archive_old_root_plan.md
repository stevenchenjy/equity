# Phase 0F Archive Old Root Plan

Run timestamp: `2026-07-09T00:28:23-05:00`
Project root: `/Users/messssi/Desktop/equity`
Archive destination: `11_archive/legacy_pre_5r_root_20260709`

## Preflight Result

- Phase 0E verification report exists and contains no FAIL markers.
- Phase 0E created-canonical-file destinations exist.
- Phase 5R-A canonical files exist under the new canonical folders.
- No Phase 5R-A canonical file depends on the old root folders as its only location.

## Folders To Archive

- `00_rules/` -> `11_archive/legacy_pre_5r_root_20260709/00_rules/`
- `01_universe/` -> `11_archive/legacy_pre_5r_root_20260709/01_universe/`
- `02_filings/` -> `11_archive/legacy_pre_5r_root_20260709/02_filings/`
- `03_research/` -> `11_archive/legacy_pre_5r_root_20260709/03_research/`
- `04_data/` -> `11_archive/legacy_pre_5r_root_20260709/04_data/`
- `05_scripts/` -> `11_archive/legacy_pre_5r_root_20260709/05_scripts/`
- `06_logs/` -> `11_archive/legacy_pre_5r_root_20260709/06_logs/`
- `06_trading/` -> `11_archive/legacy_pre_5r_root_20260709/06_trading/`
- `07_reviews/` -> `11_archive/legacy_pre_5r_root_20260709/07_reviews/`
- `tests/` -> archive as an additional Phase 0C legacy-quarantine root folder needed for clean visible root structure.

## Preserved In Root

- `00_project_control`
- `01_policies`
- `02_universe`
- `03_source_data`
- `04_research`
- `05_risk_and_positions`
- `06_execution_records`
- `07_automation`
- `08_reviews`
- `09_scripts`
- `10_tests`
- `11_archive`
- `AGENTS.md`
- `README.md`
- `skills`

Hidden SCM entries `.git/` and `.gitignore` are left untouched.

## Method

- Create archive destination folder.
- Move approved old root folders with same-filesystem rename operations only.
- Do not delete files, copy files, modify file contents, run project scripts, read `.env` files, or execute broker/API/order/trade/email code.
- Build manifest rows from path metadata and checksums; `.env`-like files are counted but not read for checksums.
