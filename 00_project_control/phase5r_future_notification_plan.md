# Phase 5R Future Notification Plan

Date: 2026-07-28 ET
Status: planning only; current email behavior is unchanged

## Target operating model

Keep daily internal monitoring and evidence refresh, but eventually reduce
routine user-facing messages to:

1. **Material-event alerts** — send only when a new, verified SEC event,
   deterministic thesis break, account-state conflict, or other pre-registered
   material transition changes the decision fingerprint.
2. **Weekly summary** — one concise after-close summary covering unchanged
   holdings, watchlist changes, important evidence, unresolved risks, and the
   week's decisive recommendation.

## Boundaries

- No model output may trigger an alert or weekly email while model influence is
  disabled.
- B2/SEC/C9 deterministic gates remain authoritative.
- Missing, stale, or conflicting evidence suppresses action language and
  records the reason.
- Alerts and summaries must use the same durable pre-SMTP claim and
  `sent`/`delivery_unknown` duplicate guard as the current daily sender.
- A material alert already sent during the week is referenced, not repeated,
  in the weekly summary.
- The Mac-off/asleep limitation remains unless the workflow is separately
  migrated to an always-on environment.

## Future migration gate

Do not change the current daily production sender until a separate no-send
verification proves:

- daily internal refresh remains loaded;
- event detection is complete and deterministic;
- one weekly cycle identity is stable;
- catch-up and duplicate behavior pass;
- no historical weekly C1-C7/D1-D3 path regains authority; and
- the migration does not read or modify SMTP credentials during verification.
