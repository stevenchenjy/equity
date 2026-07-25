# Phase 0B Migration Plan

Run timestamp: `2026-07-08T23:11:29-05:00`  
Project root: `/Users/messssi/Desktop/equity`  
Scope: planning-only migration map after Phase 0A. No files were moved, copied, renamed, deleted, or executed.

## Summary

- Migration map rows: `375` current pre-Phase0B files.
- Phase 0A inventory rows covered: `365` / `365`.
- Human review queue rows: `213`.
- Phase 0A `NEEDS_HUMAN_REVIEW` rows: `93`.
- Duplicate groups planned: `5`.
- Broken/path reference rows planned: `27` total, `12` actual missing references.
- Active-script missing-reference blockers for Phase 5R: `0`.
- Migration-map rows currently blocking Phase 5R until review/approval: `82`.

## Proposed Action Counts

- ARCHIVE_AFTER_APPROVAL: 108
- COPY_TO_CANONICAL: 112
- DELETE_LATER_LOCAL_CACHE_ONLY: 51
- KEEP_IN_PLACE: 35
- NEEDS_HUMAN_REVIEW: 69

## Classification Counts In Migration Map

- ARCHIVE: 84
- DELETE_CANDIDATE: 51
- KEEP: 98
- MIGRATE: 49
- NEEDS_HUMAN_REVIEW: 93

## Sensitivity Counts

- HIGH: 90
- LOW: 220
- MEDIUM: 65

## Human Review Gate

Every file that touches real positions, trade logs, email drafts, SEC alerts, weekly reviews, or risk rules is routed into `phase0b_human_review_queue.csv`. Every Phase 0A `NEEDS_HUMAN_REVIEW` file is kept in the human-review queue; historical phase reports use `ARCHIVE_AFTER_APPROVAL` under the specific archive rule rather than deletion.

Phase 5R should stay blocked until the human queue rows with `blocks_phase5r=yes` are approved, overridden, or explicitly marked as out of scope.

## Duplicate Resolution

Duplicate handling is planning-only in `phase0b_duplicate_resolution_plan.csv`.

- Exact trade-log duplicates are not treated as interchangeable because paper trades, real trades, and trade journal files have different meanings.
- Same-basename rows are treated as naming conflicts, not automatic duplicate content.
- Local cache duplicates can be deleted only in a later approved cleanup phase.

## Broken Path Resolution

Broken/path references are planned in `phase0b_broken_path_resolution_plan.csv`.

- Old historical-report missing paths are marked as stale archive references.
- Active script missing references, if present, are marked `FIX_REFERENCE_ONLY` and block Phase 5R.
- Placeholder/glob references remain marked as template/pattern references and are not counted as broken paths.

## Active Entrypoints

`phase0b_active_entrypoint_register.csv` identifies the scripts that should remain runnable after migration. They were not executed in Phase 0B. The sensitive operational entrypoints require human review before Phase 5R can depend on them.

## Next Gate Before Phase 5R

1. Review `phase0b_human_review_queue.csv` and approve or override sensitive rows.
2. Resolve or explicitly waive Phase 5R blockers.
3. Decide duplicate group outcomes, especially trade-log semantic duplicates.
4. Repair active-script missing references if any appear in the broken path resolution plan.
5. Only after the human gate is complete, create a separate implementation phase for actual copying/moving/archiving.

## Non-Actions In Phase 0B

No broker API was used. No `.env` file was read. No order/trade code was executed. Phase 5R was not created.
