# Phase 0E Canonical Copy Plan

Run timestamp: `2026-07-09T00:17:35-05:00`
Project root: `/Users/messssi/Desktop/equity`

## Scope

Phase 0E performs a controlled canonical migration copy only. Original files remain in place. No files are moved, renamed, deleted, or archived.

## Positive Copy Gates

- Phase 0C allowlist project and policy controls may be copied.
- Phase 0A/0B/0C/0D project-control reports may be copied into `00_project_control/audit_reports/`.
- Completed run logs may be copied into `00_project_control/run_logs/`.
- Verified Phase 5R-A manual-execution artifacts may be copied into the new canonical folders.
- Safe universe source files may be copied only when they are Phase 0C allowlisted and do not contain IOT/RBRK legacy ticker rows.

## Explicit Deferrals And Skips

- Legacy quarantine files are not copied.
- Real-position, trade-log, email/Gmail, weekly real-position, broker/order, and IOT/RBRK holding surfaces are not copied.
- Files requiring human decision or review are not copied.
- Phase 0C allowlisted workflow scripts from `05_scripts/` are deferred in Phase 0E because this phase copies only verified Phase 5R-A static/manual scripts and does not change imports or script paths.
- `01_universe/real_candidate_universe.csv` is skipped despite its Phase 0C allowlist entry because it contains IOT/RBRK ticker rows and Phase 0E is keeping legacy ticker context out of canonical Phase 5R source data.

## Planned Candidate Rows

Planned copy-map candidate rows before safety gates: `75`

## Required Non-Actions

- No deletion.
- No move.
- No rename.
- No old-folder archive.
- No Phase 5R-A logic modification.
- No Phase 5R-B creation.
- No `.env` read or copy.
- No broker/API/network execution.
- No order/trade code execution.
