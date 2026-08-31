# Phase 5R retired archive — 2026-08-31

This directory contains historical evidence removed from the active Phase 5R
workspace during the 2026-08-31 cleanup. Its contents are not production code,
are excluded by `.graphifyignore`, and must never be imported, executed,
scheduled, or used as a decision input.

## Contents

The archive preserves 520 previously tracked artifacts, including:

- Phase 0 inventories, migration records, reports, and logs;
- superseded Phase 5R B/B1 and C1–C7/D1–D3 workflows;
- historical email composers, senders, scheduler templates, and installers;
- model pilots v1–v10, replay/evaluation tooling, provider and shadow code,
  tests, policies, plans, and reports;
- obsolete market-fixture adapters and research simulations;
- completed C9A migration plans, dated C9/C9B verification snapshots, and
  one-off C9B setup/verification scripts;
- dated research outputs, previews, position templates, and review material.

Large ignored runtime evidence is stored outside both Git worktrees at
`/Users/messssi/LocalArchive/equity/phase5r_retired_20260831/` (693 files,
approximately 76 MiB). That external archive contains the authoring and runtime
copies of the model replay corpus, their distinct pilot quarantine records, and
13 stale ignored authoring reports/previews plus 9 stale ignored runtime
reports/previews.

## Recovery

The complete pre-cleanup repository tree is preserved byte-for-byte by the
annotated remote tag `phase5r-pre-cleanup-20260831`, pointing to commit
`5790e00040dcd07973f4366eaea480eff210c306`.

Restore historical material only on a separate branch or worktree. Any future
attempt to return archived code to active production requires a new review,
focused tests, updated policy, and explicit authorization.
