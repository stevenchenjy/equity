# Equity Research — current document entrypoints

Reviewed 2026-10-06 ET. This index locates maintained guidance and generated
outputs; it does not freeze balances, test counts, call counts, schedules, or
open-item counts. Verify the current branch, files, runtime timestamps and
relevant checks before relying on any linked claim.

## Authoritative policy and boundaries

- [Repository layout and path ownership](repository_layout.md): source/runtime/generated boundaries, archive recovery and retained compatibility paths.

- [Equity Research naming decision and migration plan](equity_naming_policy.md): fixed user-facing name and functional naming rules; display names are centralized; legacy technical identifiers remain compatible.
- [Owner-approved allocation policy](allocation_policy.md): October 6 replacement standard — broad core at least 30%, individual stocks up to 70%, zero cash target/reserve and no fixed single-stock cap; strategy-specific risk and execution controls remain.
- [Active production configuration](active_production_config.json): active paths and deterministic production controls.
- [Momentum integration decision](momentum_integration_20260927.md), [experimental parameters](../01_policies/momentum_experiment.json) and [position-purpose reassessment](position_purpose_reassessment.md): autonomous research without changing allocation, risk caps or trade authority.
- [SHADOW evaluation configuration](shadow_llm_config.json) and [policy](shadow_llm_evaluation_policy.md): evaluation allowance, routing, measurements, and future authority-review thresholds.
- [Research working agreement](research_working_agreement.md): routine autonomous work versus authority-changing choices.
- [Scoped blockers and recurring research work](workflow_followthrough_20260927.md): cash explanations, bounded objective completion and durable expired-plan reassessment; no allocation or risk-policy changes.
- [Discovery and research attention architecture](research_opportunity_architecture.md): durable first-seen opportunities, bounded official evidence, research assessments and the explicit experiment-to-research boundary; production capital contracts remain separate.
- [Account-state policy](account_state_policy.md), [action thresholds](action_threshold_policy.md), and [core-allocation policy](core_allocation_policy.md): deterministic account and portfolio constraints.
- [Delivery policy](daily_delivery_policy.md): notification eligibility is deterministic; SHADOW cannot alter it.
- [September 20 implementation and acceptance record](../11_archive/dated_reviews_20260923/workflow_implementation_20260920.md): completed changes, production verification, preserved evidence and remaining research gaps.
- [Long-horizon research policy](long_horizon_research_policy.md) and [executable sensitivity parameters](../01_policies/long_horizon_research_policy.json): fundamental candidate discovery, company-specific unresolved theses, source-bound observations, equity P/FCF sensitivities, and conditional 2×/3× hurdles. High confidence needs separately reviewed evidence; fixed size tiers are superseded by company-specific reviewed allocation, and arithmetic alone does not establish a company forecast.
- [Market-regime policy](../01_policies/market_regime_policy.json): bounded new-capital confirmation and research pacing; hard concentration caps, reserve, strategic targets and execution authority do not change.
- [Official-news source manifest](../01_policies/official_news_sources.json): approved issuer feeds, source domains, request bounds and freshness requirements; coverage is limited to configured sources.
- [Allowed active-input registry](allowed_active_inputs.csv): current machine-readable input paths, permitted readers, scope and freshness, including optional source-bound thesis assessments. Absence of an optional assessment cannot create an exit conclusion.

## Dashboard implementation and remaining phases

- [Dashboard phased build plan](dashboard_build_plan.md): Phase 0/1 delivered; Phase 2 formal feedback deployed; isolated acceptance and production no-send recomposition verified. Phase 3 charts/history ready; private HTTPS and real phone acceptance require Tailscale login.
- [Phase 0/1 contract](dashboard_phase01_contract.md): retained initial read-only and demo boundaries.
- [Dashboard application](../10_dashboard/README.md): shared formal forms, preview/apply receipts, incomplete-record completion, private service setup and operational recovery.

## Current runtime outputs — read their generated timestamps

These paths refer to `/Users/messssi/LocalRuntime/equity`, not cached reports
in the authoring clone. Missing local reports are not assumed complete.

- [Production status](/Users/messssi/LocalRuntime/equity/00_project_control/current_production_status.local.md).
- [Experimental momentum observations and forward evaluation](/Users/messssi/LocalRuntime/equity/08_reviews/momentum_experiment.local/report.md): private frozen cohorts, costs, missed/expired setups and explicitly unverified execution. Check current status for failures; a historical report is not a current signal.
- [Current daily research decision](/Users/messssi/LocalRuntime/equity/04_research/company_research/daily_decision.md).
- [Current research opportunities](/Users/messssi/LocalRuntime/equity/08_reviews/current/research_opportunities.local.md): original observations, research timing, separated evidence families, blockers and prospective measurement; no buy/sell authority.
- [Cash and recurring opportunity work](/Users/messssi/LocalRuntime/equity/08_reviews/capital_work_queue.local/report.md) and [prioritized research backlog](/Users/messssi/LocalRuntime/equity/08_reviews/current/research_backlog.local.md): check generated times and production health; pending work does not establish an eligible trade.
- [SHADOW measured results](/Users/messssi/LocalRuntime/equity/08_reviews/shadow_llm/reviews.local/evaluation.md) and [machine-readable results](/Users/messssi/LocalRuntime/equity/08_reviews/shadow_llm/reviews.local/evaluation.json).
- [Long-horizon company research and 2×/3× conditions](/Users/messssi/LocalRuntime/equity/08_reviews/current/long_horizon_research.local.md) and [source-bound JSON](/Users/messssi/LocalRuntime/equity/04_research/company_research/long_horizon_research.local.json): verify generation time, reference close and current holdings before use; authoring copies are not production evidence. No automatic action or forecast authority.
- [Market regime and research pacing](/Users/messssi/LocalRuntime/equity/08_reviews/current/market_regime.local.md) and [current regime receipt](/Users/messssi/LocalRuntime/equity/04_research/company_research/market_regime.local.json): use the current completed market session and distinct-close history.
- [Official-news health receipt](/Users/messssi/LocalRuntime/equity/03_source_data/equity_research/official_news_status.local.json) and [deduplicated official events](/Users/messssi/LocalRuntime/equity/03_source_data/equity_research/official_news_events.local.json): source coverage, freshness and unclassified announcements; a fetch failure is not proof that no announcement occurred.
- [Research questions and deterministic sensitivities](/Users/messssi/LocalRuntime/equity/08_reviews/current/research_questions.local.md): the earlier research companion; questions and conditional arithmetic, not established investment theses.
- [September 4 follow-through snapshot](/Users/messssi/LocalRuntime/equity/08_reviews/shadow_llm/reviews.local/system_followthrough_20260904.md): dated implementation/verification receipt; newer generated results take precedence.

- [Momentum experiment reproducibility](momentum_reproducibility.md): frozen experiment versions, source-bound replay and admission checks; historical observation batches do not promote candidates automatically.

## Historical material — retained, not current instructions

- [Dated project-control records](../11_archive/project_control_history/README.md): September 20 plan, September 28 repair and collector timing evidence; byte-preserved original context.
- [October 3 repository hygiene diagnosis](../11_archive/repository_hygiene_20261003/README.md): dated inventory and cleanup decisions; not a live status report.
- [Pre-October 6 manual risk reference](../11_archive/allocation_policy_before_20261006/README.md): preserved former generic limits, superseded by the owner-approved allocation contract.

- [September 4 documentation archive](../11_archive/phase5r_docs_superseded_20260904/README.md): pre-SHADOW proposal, August 31 verification/inventory, and obsolete duplicate Phase 0/1 skill packages.
- [August 31 retirement archive](../11_archive/phase5r_retired_20260831/README.md): prior implementation and experiments, never production inputs.
- Original local `system_reassessment_20260904.md` and `system_repair_20260904.md` remain unchanged so findings, failures, and the sequence of repairs remain auditable. They do not update themselves.

The general `01_policies/risk_policy.md` and `trading_checklist.md` summarize
current manual-planning requirements and link the authoritative allocation
contract. Their former generic limits are archived and do not restore old
single-name caps or mandatory reserves. Neither file establishes current
account truth. No archived command should be
run as an active workflow. Nothing in this cleanup grants model production
influence, broker access, trade execution, or new risk tolerance.

- [Capital decision and manual execution contract](capital_decision_contract.md) — common exact drafts, dependency routing and versioned strategy admission.
