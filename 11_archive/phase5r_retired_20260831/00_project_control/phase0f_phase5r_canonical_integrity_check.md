# Phase 0F Phase 5R Canonical Integrity Check

Run timestamp: `2026-07-09T00:28:23-05:00`

## Checks

- **PASS** - Phase 5R-A canonical files still exist: missing=[]
- **PASS** - Canonical Phase 5R data/tickets do not contain IOT/RBRK tickers: violations=[]
- **PASS** - Manual ticket constants remain yes/no/no/no: violations=[]
- **PASS** - Legacy IOT/RBRK source locations are archived, not root canonical inputs: root_legacy_paths=[], archived_examples=['11_archive/legacy_pre_5r_root_20260709/01_universe/real_candidate_universe.csv', '11_archive/legacy_pre_5r_root_20260709/04_data/phase5r_universe_seed.csv']

## Boundary

Phase 0F moved old roots into archive only. It did not modify Phase 5R-A logic, did not run project scripts, and did not use archived IOT/RBRK legacy data as canonical Phase 5R input.
