# Equity Research — current document entrypoints

Updated 2026-09-20 ET. This index identifies where to read current state; it
does not freeze balances, test counts, call counts, or open-item counts.

## Authoritative policy and boundaries

- [Equity Research naming decision and migration plan](equity_naming_policy.md): fixed user-facing name and functional naming rules; display names are centralized; legacy technical identifiers remain compatible.
- [Active production configuration](phase5r_active_production_config.json): active paths and deterministic production controls.
- [SHADOW evaluation configuration](phase5r_shadow_llm_config.json) and [policy](phase5r_shadow_llm_evaluation_policy.md): evaluation allowance, routing, measurements, and future authority-review thresholds.
- [Research working agreement](phase5r_research_working_agreement.md): routine autonomous work versus authority-changing choices.
- [Account-state policy](phase5r_c9_account_state_policy.md), [action thresholds](phase5r_c9_action_threshold_policy.md), and [core-allocation policy](phase5r_c9_core_allocation_policy.md): deterministic account and portfolio constraints.
- [Delivery policy](phase5r_daily_delivery_policy.md): notification eligibility is deterministic; SHADOW cannot alter it.
- [Four-standard workflow improvement plan](phase5r_workflow_improvement_plan_20260920.md): implementation scope and acceptance criteria; deployment and current operation must still be verified from runtime receipts.
- [September 20 implementation and acceptance record](../08_reviews/phase5r_workflow_implementation_20260920.md): completed changes, production verification, preserved evidence and remaining research gaps.
- [Long-horizon research policy](phase5r_long_horizon_research_policy.md) and [executable sensitivity parameters](../01_policies/phase5r_long_horizon_research_policy.json): fundamental candidate discovery, company-specific unresolved theses, source-bound observations, equity P/FCF sensitivities, and conditional 2×/3× hurdles. The high-conviction tier remains reserved; arithmetic alone does not establish a company forecast.
- [Market-regime policy](../01_policies/phase5r_market_regime_policy.json): bounded new-capital confirmation and research pacing; hard concentration caps, reserve, strategic targets and execution authority do not change.
- [Official-news source manifest](../01_policies/phase5r_official_news_sources.json): approved issuer feeds, source domains, request bounds and freshness requirements; coverage is limited to configured sources.
- [Allowed active-input registry](phase5r_c8_allowed_active_inputs.csv): current machine-readable input paths, permitted readers, scope and freshness, including optional source-bound thesis assessments. Absence of an optional assessment cannot create an exit conclusion.

## Current runtime outputs — read their generated timestamps

These paths refer to `/Users/messssi/LocalRuntime/equity`, not cached reports
in the authoring clone. Missing local reports are not assumed complete.

- [Production status](/Users/messssi/LocalRuntime/equity/00_project_control/phase5r_current_production_status.local.md).
- [Current daily research decision](/Users/messssi/LocalRuntime/equity/04_research/realtime_stock_picker_phase5r/phase5r_daily_decision.md).
- [SHADOW measured results](/Users/messssi/LocalRuntime/equity/08_reviews/phase5r_shadow_llm/reviews.local/evaluation.md) and [machine-readable results](/Users/messssi/LocalRuntime/equity/08_reviews/phase5r_shadow_llm/reviews.local/evaluation.json).
- [Long-horizon company research and 2×/3× conditions](/Users/messssi/LocalRuntime/equity/08_reviews/current/phase5r_long_horizon_research.local.md) and [source-bound JSON](/Users/messssi/LocalRuntime/equity/04_research/realtime_stock_picker_phase5r/phase5r_long_horizon_research.local.json): held-company research gaps, numerical review signals and explicit 3/5-year sensitivities; no automatic action or forecast authority.
- [Market regime and research pacing](/Users/messssi/LocalRuntime/equity/08_reviews/current/phase5r_market_regime.local.md) and [current regime receipt](/Users/messssi/LocalRuntime/equity/04_research/realtime_stock_picker_phase5r/phase5r_market_regime.local.json): use the current completed market session and distinct-close history.
- [Official-news health receipt](/Users/messssi/LocalRuntime/equity/03_source_data/phase5r/phase5r_official_news_status.local.json) and [deduplicated official events](/Users/messssi/LocalRuntime/equity/03_source_data/phase5r/phase5r_official_news_events.local.json): source coverage, freshness and unclassified announcements; a fetch failure is not proof that no announcement occurred.
- [Research questions and deterministic sensitivities](/Users/messssi/LocalRuntime/equity/08_reviews/current/phase5r_research_questions.local.md): the earlier research companion; questions and conditional arithmetic, not established investment theses.
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
