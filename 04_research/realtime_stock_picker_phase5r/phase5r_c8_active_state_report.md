# Phase 5R-C8 Active State Report

Generated: `2026-07-09T16:44:24-05:00`

## Authoritative State

- Current workflow: `weekly_conviction`.
- Active pipeline: `phase5r_c7`.
- Primary decision: `no_action_until_next_review`.
- Next review date: `2026-07-16`.
- Current position source: `05_risk_and_positions/current_positions.local.csv`.
- Email delivery boundary: `phase5r_c7_only`.

## Registry Summary

- Allowed active input rows: `43`.
- Deprecated or parked workflow rows: `8`.
- Stale-file guard checks: `15`.
- Archived folders are excluded without reading their contents.
- Historical daily files remain evidence only.

## Enforcement

C7 now validates the active state before reading other weekly inputs. A missing or conflicting state blocks pipeline execution.

## Boundary

The registry does not authorize scheduling, broker access, automatic portfolio action, standalone historical email workflows, archived inputs, or Phase 5R-D2.
