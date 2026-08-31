# Phase 5R-D3G Dynamic C6 Policy

Generated: `2026-07-18T18:02:25-04:00`

## Purpose

C6 composes a weekly research email from the current verified C5 and C5T outputs. It must not encode a previous week's ticker membership or eligible count as a permanent requirement.

## Canonical inputs

- `00_project_control/active_decision_state.yaml`
- `04_research/realtime_stock_picker_phase5r/phase5r_c5_weekly_conviction_scores.csv`
- `04_research/realtime_stock_picker_phase5r/phase5r_c5_position_review_recommendations.csv`
- `04_research/realtime_stock_picker_phase5r/phase5r_c5_new_candidate_recommendations.csv`
- `04_research/realtime_stock_picker_phase5r/phase5r_c5_company_research_packets.csv`
- `04_research/realtime_stock_picker_phase5r/phase5r_c5_weekly_conviction_memo.md`
- `05_risk_and_positions/current_positions.local.csv`
- current C5T action-plan, scenario-table, and next-review-trigger outputs

Archived or legacy holding data is not an allowed input.

## Validation rules

The only supported recommendation labels are:

- `eligible_buy_review`
- `wait_for_pullback`
- `hold_existing`
- `add_review`
- `trim_review`
- `exit_review`
- `reject`
- `watch_only`

C6 fails closed on an unsupported or missing label, a missing/duplicate ticker, a current position without a current C5 position recommendation, a mismatch between current score and recommendation labels, an unrecognized selected scenario, or an included ticker without a controlled C5 research packet.

Every controlled packet must retain human review and prohibit automatic action. It must provide current evidence references; eligibility is a research-review classification and never an execution instruction.

## Composition rules

- Current positions come from `current_positions.local.csv` and are presented concentration-first.
- Each current position uses its current C5 position label and reason; `trim_review` is not assumed.
- Candidate sections show no more than 2 `eligible_buy_review`, 3 `wait_for_pullback`, and 4 `watch_only` names.
- Rejects are summarized as a count. Other supported candidate labels are summarized without expanding the eligible section.
- Zero eligible candidates is stated explicitly.
- One or two eligible candidates are described as research-review candidates with no urgent trade language.
- The subject is `Weekly AI Equity Conviction Brief — {date} — {eligible_count} Eligible / {position_review_count} Position Reviews`.
- The primary scenario is read from the active decision state and must exist in the current C5T plan/scenario table.
- The next review date is the latest planned date found in current positions, C5T triggers, or the current C5/C5T narrative outputs; it is not hardcoded.

## Delivery boundary

C6 composition does not read SMTP configuration, send email, connect to a broker, or create orders. Delivery remains available only through the active `phase5r_c7` boundary and its existing C6 sender.

