# Phase 5R-C3 Daily Email Pipeline Policy

## Purpose

Phase 5R-C3 provides one manual command that refreshes the canonical Phase 5R research dataset, rebuilds the daily brief, and optionally delivers exactly one email. It does not create automatic scheduling.

## Ordered Workflow

1. Refresh the full canonical Phase 5R universe with the B2 public market-data runner.
2. Recalculate B2 signal scores.
3. Rebuild B2 manual-only tickets.
4. Compose the C1 local daily email brief.
5. Invoke the C2 sender once, according to the selected mode.

Each step must complete successfully before the next step starts. A failed B2, C1, or C2 step stops the pipeline and marks remaining steps as skipped.

## Modes

- Default: runs B2 and C1, then invokes C2 once in live-send mode.
- `--dry-run`: runs B2 and C1, then invokes C2 once with `--dry-run`; no live email is sent.
- `--no-send`: runs B2 and C1 and skips C2 delivery entirely.

## Safety Boundary

- One live email at most per default pipeline run.
- No recipient override, attachment, SMTP credential handling, or direct SMTP implementation in the C3 runner. Only the existing C2 sender may read the local SMTP configuration.
- No scheduler, repeated notification, intraday alert, every-15-minute scan, broker connection, order placement, or trade execution.
- No archived legacy input and no legacy holding data.
- Phase 5R-D is outside this phase.
