# Phase 5R-C9 Output Regeneration Plan

## Active C9 Sequence

1. Refresh the B2 snapshot, including current held tickers as price-only rows.
2. Validate or create the local account-state file.
3. Calculate dynamic weights and portfolio reconciliation.
4. Create exact current-position and whole-share action scenarios.
5. Create separate core/cash allocation approaches.
6. Recalculate C5 portfolio-fit scores and current/candidate recommendations.
7. Create the account-aware memo, allocation report, and C6-compatible weekly summary.
8. Verify the account and manual-execution boundary.
9. Compose C6 from C9 outputs.
10. Run C7 only as `--no-send`, then perform final C9 verification.

## Supersession

C9-named outputs supersede the old C4R/C5/C5T portfolio calculations for current decisions. Old files and logs remain historical and are not deleted or rewritten.

Public B2 data and fresh company evidence remain inputs. Old C5 packet portfolio-fit scores, fixed risk wording, and recommendation labels are ignored and regenerated into C9 outputs.

## Safety Gates

- D3 maintenance inhibit remains active with `allowed_pipeline=none`.
- C7 blocks send and dry-run modes while maintenance is active; only explicit `--no-send` verification is permitted.
- C6 composition reads C9 outputs and does not read SMTP configuration.
- The C6 sender is skipped in C7 no-send mode.
- No C10 files are created.
