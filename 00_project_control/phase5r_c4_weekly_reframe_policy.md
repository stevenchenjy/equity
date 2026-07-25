# Phase 5R-C4 Weekly Conviction Reframe Policy

## Direction

Phase 5R-C4 reframes the project as a lower-attention AI Investment Research Assistant centered on weekly conviction research, explicit portfolio state, and manual decisions. It does not create daily trading pressure or automatic buying and selling.

## Weekly Workflow

1. Review current positions, thesis changes, invalidation risks, and concentration once per week.
2. Refresh the research universe and rank ideas for deeper work.
3. Produce zero to two new `eligible_buy_review` candidates per week by default.
4. Treat `wait_for_pullback`, `hold_existing`, and `watch_only` as valid outcomes.
5. Review portfolio-level rebalancing once per month.
6. Permit future event alerts only for major thesis or risk changes, never routine price noise.

## Decision Labels for Future Phases

- `eligible_buy_review`
- `wait_for_pullback`
- `hold_existing`
- `add_review`
- `trim_review`
- `exit_review`
- `reject`
- `watch_only`

Every label is a research decision for independent human review. No label authorizes an automated transaction.

## Parked Daily Capability

The D1 launchd template and management files remain preserved as evidence and optional future capability. They are inactive: the LaunchAgent is not installed or loaded, and the daily pipeline is not scheduled under the weekly workflow.
