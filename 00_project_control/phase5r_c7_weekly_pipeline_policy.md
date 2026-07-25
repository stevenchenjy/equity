# Phase 5R-C7 Weekly Pipeline Policy

## Purpose

Phase 5R-C7 provides one manual command for the complete weekly conviction workflow. It validates current local positions, refreshes public market data, rebuilds weekly research and manual scenarios, composes the weekly brief, and invokes the C6 sender at most once.

## Commands

Default mode permits one weekly delivery:

```text
python3 09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py
```

Non-sending modes:

```text
python3 09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py --dry-run
python3 09_scripts/phase5r/run_phase5r_c7_weekly_conviction_pipeline.py --no-send
```

## Step Boundary

1. Validate `current_positions.local.csv` with the C4 validator.
2. Refresh C4R concentration artifacts consumed by C5.
3. Refresh B2 public market data.
4. Rebuild B2 scores and manual tickets.
5. Rebuild the C5 research queue, company packets, conviction scores, and memo.
6. Rebuild C5T scenarios and manual action plan.
7. Compose the C6 weekly email.
8. Invoke the C6 sender once according to the selected mode.

Every child step must return successfully before the next step begins. There are no automatic retries.

## Mode Rules

- Default: C6 sender runs once without mode flags; exactly one live-send row must be added.
- `--dry-run`: C6 sender runs once with `--dry-run`; no live-send row may be added.
- `--no-send`: C6 sender is skipped; no live-send row may be added.

## Safety Boundary

- Manual invocation only; no launchd installation or automatic scheduling.
- No daily delivery loop, repeated notification, or time-sensitive alert behavior.
- C7 does not read SMTP configuration or credentials; only the existing C6 sender owns that boundary.
- No broker access, portfolio-change capability, attachments, archived holding input, or Phase 5R-D2.
