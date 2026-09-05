# Phase 5R — current document entrypoints

Updated 2026-09-04 ET. This index identifies where to read current state; it
does not freeze balances, test counts, call counts, or open-item counts.

## Authoritative policy and boundaries

- [Active production configuration](phase5r_active_production_config.json): active paths and deterministic production controls.
- [SHADOW evaluation configuration](phase5r_shadow_llm_config.json) and [policy](phase5r_shadow_llm_evaluation_policy.md): evaluation allowance, routing, measurements, and future authority-review thresholds.
- [Research working agreement](phase5r_research_working_agreement.md): routine autonomous work versus authority-changing choices.
- [Account-state policy](phase5r_c9_account_state_policy.md), [action thresholds](phase5r_c9_action_threshold_policy.md), and [core-allocation policy](phase5r_c9_core_allocation_policy.md): deterministic account and portfolio constraints.
- [Delivery policy](phase5r_daily_delivery_policy.md): notification eligibility is deterministic; SHADOW cannot alter it.

## Current runtime outputs — read their generated timestamps

These paths refer to `/Users/messssi/LocalRuntime/equity`, not cached reports
in the authoring clone. Missing local reports are not assumed complete.

- [Production status](/Users/messssi/LocalRuntime/equity/00_project_control/phase5r_current_production_status.local.md).
- [Current daily research decision](/Users/messssi/LocalRuntime/equity/04_research/realtime_stock_picker_phase5r/phase5r_daily_decision.md).
- [SHADOW measured results](/Users/messssi/LocalRuntime/equity/08_reviews/phase5r_shadow_llm/reviews.local/evaluation.md) and [machine-readable results](/Users/messssi/LocalRuntime/equity/08_reviews/phase5r_shadow_llm/reviews.local/evaluation.json).
- [Research questions and deterministic sensitivities](/Users/messssi/LocalRuntime/equity/08_reviews/current/phase5r_research_questions.local.md): questions and conditional arithmetic, not established investment theses.
- [Current follow-through report](/Users/messssi/LocalRuntime/equity/08_reviews/phase5r_shadow_llm/reviews.local/system_followthrough_20260904.md): dated implementation/verification receipt; newer generated results take precedence.

## Historical material — retained, not current instructions

- [September 4 documentation archive](../11_archive/phase5r_docs_superseded_20260904/README.md): pre-SHADOW proposal, August 31 verification/inventory, and obsolete duplicate Phase 0/1 skill packages.
- [August 31 retirement archive](../11_archive/phase5r_retired_20260831/README.md): prior implementation and experiments, never production inputs.
- Original local `system_reassessment_20260904.md` and `system_repair_20260904.md` remain unchanged so findings, failures, and the sequence of repairs remain auditable. They do not update themselves.

The general `01_policies/risk_policy.md` and `trading_checklist.md` are retained
manual-planning references. Do not confuse their historical examples with
current account truth or executable thresholds. No archived command should be
run as an active workflow. Nothing in this cleanup grants model production
influence, broker access, trade execution, or new risk tolerance.
