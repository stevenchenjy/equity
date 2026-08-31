# Phase 5R-D3G Root-Cause Report

Generated: `2026-07-18T18:02:25-04:00`

## Incident

The current weekly cycle (`2026-W29`) did not produce a delivery. Two C7 live-mode attempts completed steps 1 through 11, but step 12 (`C6 weekly email composition`) returned nonzero. Step 13 was therefore skipped, and the C6 delivery status recorded no new successful send.

D3 correctly recorded the cycle outcome as `catchup_failed` with `send_delta=0`. Later 15-minute checks failed closed with `prior_c7_attempt_without_success_requires_manual_review` instead of rapidly retrying or risking a duplicate.

## Root cause

The C6 composer treated the prior week's recommendation outcome as an invariant. It required exact prior ticker memberships for `wait_for_pullback` and `watch_only` and required the eligible count to remain zero. C5 is a weekly research process, so valid changes to the current recommendation labels caused C6 to raise `C6 candidate labels do not match the verified C5 outcome`.

This was a composition-policy defect, not a launchd, C7 orchestration, SMTP, or delivery-guard defect.

## Correction

The composer now reads the current C5 position and candidate recommendation rows, validates each label against the supported label set, validates current-position coverage, and requires a controlled research packet for every included ticker. Position labels, candidate groupings, counts, selected scenario, and planned review date are derived from current canonical inputs.

The D3 failed-cycle state remains bounded. A new manual recovery command can clear only the current cycle's failed-attempt guard after confirming no qualifying successful send exists, D3 is loaded, and C6 composition passes. It never invokes C7 or the sender.

## Current disposition

- D3 scheduler: loaded.
- D2 scheduler: unloaded.
- Current failed-cycle guard: retained during D3G verification.
- C6 composition: passing with the current C5/C5T inputs.
- C7 verification: completed in `--no-send` mode with step 12 passing and step 13 skipped.
- Successful C6 sends for `2026-W29`: none.
- Live email sent during D3G: no.

