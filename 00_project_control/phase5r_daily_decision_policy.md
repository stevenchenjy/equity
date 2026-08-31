# Phase 5R Daily Decision Policy

## Required Presentation

Every brief begins with one prominent, decisive conclusion. It must answer:

- what to do with current positions;
- whether any new position is justified;
- whether evidence is reliable enough;
- whether human review is actually required.

The language may be firm, but it remains research rather than a trading command.

## Decision Priority

1. Account conflict: `暂停新增动作｜先解决账户状态冲突`.
2. Data or evidence failure: `不采取新动作｜数据可靠性门槛未通过`.
3. Material long-term weakening: maintain the position pending focused research
   unless C9 independently produces an action-review candidate.
4. Stable C9 action transition: show the exact research proposal for human
   review.
5. Otherwise: `继续持有现有仓位｜今天不新增仓位`.

## Action Inertia

Daily analysis does not imply daily action.

- HOLD and WATCH never require confirmation.
- An ADD proposal must remain identical across two different valid closing
  sessions.
- TRIM and EXIT research proposals may escalate immediately when C9 identifies
  a concentration or invalidation condition.
- Every action proposal has `automatic_action_allowed=no`.

## Current-State Authority

This policy contains no dated position, share-count, recommendation, or
fundamental snapshot. The current decision is the validated
`04_research/realtime_stock_picker_phase5r/phase5r_daily_decision.json`
artifact generated from the current local account, current market session, and
current official evidence. Automatic action remains prohibited in every state.
