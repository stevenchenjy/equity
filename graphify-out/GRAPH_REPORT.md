# Graph Report - equity  (2026-09-23)

## Corpus Check
- 195 files · ~201,576 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2099 nodes · 5280 edges · 112 communities (89 shown, 23 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 915 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `b97ff7bd`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- market_data_adapter.py
- run_full_universe_market_data.py
- AST
- send_c6_weekly_email.py
- test_active_production.py
- score_b_candidates.py
- ShadowProviderError
- main
- ShadowLlmTests
- main
- PacketMarketObservationTests
- verify_daily_upgrade.py
- iso_now
- verify_c6_weekly_email_boundary.py
- score_candidates.py
- ShadowMeasurementTests
- llm_contract.py
- execution_common.py
- verify_c5t_manual_action_boundary.py
- main
- account_common.py
- PacketMarketObservationTests
- compare_policies
- evaluate_shadow_llm_incremental_value.py
- applied_reconciliation_matches_current_state
- ResearchRiskLimitsTests
- portfolio_construction.py
- next_thursday
- verify_c2_email_delivery_boundary.py
- HeldCorePositionTests
- shadow_llm_contract.py
- check_shadow_llm_evaluation_scheduler.sh
- install_shadow_llm_evaluation_scheduler.sh
- run_shadow_llm_event.sh
- ShadowLlmTests
- Phase5R MacBook → GitHub → Mac mini workflow
- main
- Early Public Equity Lab
- Phase 5R AI operating decision
- Phase 5R — current document entrypoints
- create_c5_weekly_conviction_memo.py
- score_candidates.py
- Phase 5R risk-policy audit — 2026-09-14
- Owner-requested research reviews
- economic_packet
- portfolio_construction.py
- ShadowLlmTests
- test_refresh_cadence.py
- ShadowProviderError
- ShadowMeasurementTests
- ShadowMeasurementTests
- valuation_input_bundle.py
- Scoring
- main
- Phase 0C Reframe Plan
- AcceptanceReconciliationError
- MarketRegimeTests
- OfficialNewsScheduleTests
- load_inhibit
- 四项标准：工作流升级实施与验收
- main
- create_long_horizon_research.py
- Phase 5R SHADOW_LLM
- risk_profile_activation_20260914.md
- workflow_standards_audit_20260920.md
- score_candidates.py
- ResearchRiskLimitsTests
- test_owner_snapshot.py
- Equity Research 命名迁移验收
- Phase 5R-C9 Core Allocation Policy
- ResearchRiskLimitsTests
- build_current_research_baseline.py
- report_heading
- write_extension_admission_audit
- score_candidates.py
- _run_identity
- main
- Phase 5R AI operating decision
- Early Public Equity Research
- main
- create_long_horizon_research.py
- Equity Research — current document entrypoints
- Phase 5R-C9 Core Allocation Policy
- activate_daily_after_verification.sh
- check_daily_scheduler_status.sh
- clear_maintenance_inhibit.sh
- install_daily_schedulers.sh
- set_maintenance_inhibit.sh
- uninstall_daily_schedulers.sh
- next_thursday
- research_working_agreement.md
- __init__.py
- SecAcceptanceReconciliationTests
- recommendation_notification_fingerprint
- Equity Research 命名与归档规则
- graphify reference: query, path, explain
- Source Policy
- Phase 5R-C5 Verification Report
- Phase 5R-C2 Verification Report
- Phase 5R-D3G Research Verification Report
- Phase 5R-C9A Account-State and Stale-Denominator Audit Policy
- enable_llm_live_shadow.py
- Phase 5R-C9 Core Allocation Policy
- check_llm_shadow_status.sh
- install_llm_shadow_scheduler.sh
- Phase 5R Model Shadow Readiness — Research Summary
- ShadowOutputLock
- anonymous_review_materials_status.md
- CodexCliProvider
- iso_now
- Phase 5R v9 terminal diagnosis

## God Nodes (most connected - your core abstractions)
1. `render_email()` - 57 edges
2. `canonical_sha256()` - 53 edges
3. `_execute_unlocked()` - 38 edges
4. `main()` - 37 edges
5. `read_json()` - 37 edges
6. `build_email_view()` - 35 edges
7. `main()` - 35 edges
8. `RuntimeSyncError` - 33 edges
9. `iso_now()` - 32 edges
10. `ExclusiveFileLock` - 30 edges

## Surprising Connections (you probably didn't know these)
- `load_execution_rows()` --calls--> `csv_fields()`  [INFERRED]
  09_scripts/equity_research/execution_common.py → 09_scripts/equity_research/account_common.py
- `main()` --calls--> `write_text()`  [INFERRED]
  09_scripts/equity_research/create_price_aware_action_plan.py → 09_scripts/equity_research/account_common.py
- `main()` --calls--> `write_text()`  [INFERRED]
  09_scripts/equity_research/regenerate_portfolio_outputs.py → 09_scripts/equity_research/account_common.py
- `execution_conflicts()` --calls--> `load_account_state()`  [INFERRED]
  09_scripts/equity_research/create_daily_decision_and_brief.py → 09_scripts/equity_research/account_common.py
- `main()` --calls--> `load_account_state()`  [INFERRED]
  09_scripts/equity_research/create_price_aware_action_plan.py → 09_scripts/equity_research/account_common.py

## Import Cycles
- None detected.

## Communities (112 total, 23 thin omitted)

### Community 0 - "market_data_adapter.py"
Cohesion: 0.14
Nodes (19): AcceptanceIndexError, build_acceptance_index(), make_acceptance_record(), normalize_acceptance_timestamp(), _normalize_generated_at(), Any, ValueError, Return one timezone-aware ISO timestamp or fail closed. (+11 more)

### Community 1 - "run_full_universe_market_data.py"
Cohesion: 0.07
Nodes (45): InlineFacts, parse_principal_facts(), project_relative_locator(), Any, datetime, HTMLParser, Path, ValueError (+37 more)

### Community 2 - "AST"
Cohesion: 0.14
Nodes (51): canonical_sha256(), _append_ledger_event(), _archive_packet(), _archived_packet_index(), _atomic_private_json(), _atomic_private_text(), _contract_failure_code(), critic_route() (+43 more)

### Community 3 - "send_c6_weekly_email.py"
Cohesion: 0.08
Nodes (55): _allowed_classifications_by_ticker(), _artifact_map(), build_packet(), _compact_fact_provenance(), _date_from_period(), _decimal(), _decision_tickers(), _entities() (+47 more)

### Community 4 - "test_active_production.py"
Cohesion: 0.09
Nodes (54): acceptance_map(), fetch(), main(), Path, append_csv_durable(), log_daily_run(), classify_materiality(), company_fundamentals_required() (+46 more)

### Community 5 - "score_b_candidates.py"
Cohesion: 0.07
Nodes (45): ExclusiveFileLock, Process lock using flock over a private, non-linked regular file., _append_execution_record(), assert_non_icloud_runtime_root(), _best_effort_failure_record(), _exec_scheduler(), _git(), inspect_runtime_repository() (+37 more)

### Community 6 - "ShadowProviderError"
Cohesion: 0.10
Nodes (29): build_report(), _cache_read(), _cache_write(), _digest(), DiscoveryClient, DiscoveryError, _empty(), _http_get() (+21 more)

### Community 7 - "main"
Cohesion: 0.16
Nodes (21): easter_sunday(), expected_market_session(), is_us_market_session_date(), last_completed_market_session(), last_weekday(), nth_weekday(), observed(), date (+13 more)

### Community 8 - "ShadowLlmTests"
Cohesion: 0.11
Nodes (21): B2MarketRefreshFailureCommitTests, _candidate_row(), _CompleteCachedClient, _DuplicateSessionErrorClient, _FailingFullFetchClient, _market_row(), _PartialApprovedTickerClient, date (+13 more)

### Community 9 - "main"
Cohesion: 0.15
Nodes (20): build_tactical_review(), _day(), _integer(), _last_sessions(), load_tactical_review(), _money(), _number(), _positive() (+12 more)

### Community 10 - "PacketMarketObservationTests"
Cohesion: 0.11
Nodes (38): Path, append_delivery(), build_message(), ConfigError, correction_eligibility(), cycle_is_blocked(), delivery_policy(), load_config() (+30 more)

### Community 11 - "verify_daily_upgrade.py"
Cohesion: 0.12
Nodes (33): atomic_write_json(), bool_value(), clear_automation_alert(), cycle_date(), delivery_guard(), iso_now(), load_active_state(), load_inhibit() (+25 more)

### Community 12 - "iso_now"
Cohesion: 0.13
Nodes (19): line_excerpt(), main(), number(), Any, Path, Fail closed before producing a range, not merely before order routing., Match the packet clock's whole-second point-in-time precision., selected_band() (+11 more)

### Community 13 - "verify_c6_weekly_email_boundary.py"
Cohesion: 0.12
Nodes (23): canonical_url(), clean_title(), fetch_feed(), load_manifest(), NewsError, OfficialRedirect, parse_feed(), _PlainText (+15 more)

### Community 14 - "score_candidates.py"
Cohesion: 0.12
Nodes (12): LongHorizonDecisionDisciplineTests, RiskPolicyDiagnosticTests, compare_policies(), _decimal(), Holding, _number(), Compare capacities independently, never sum candidate share counts.  These are u, Apply explicit per-ticker price shocks simultaneously, keeping cash fixed.  Ever (+4 more)

### Community 15 - "ShadowMeasurementTests"
Cohesion: 0.11
Nodes (20): Any, datetime, fundamental(), LongHorizonResearchTests, RequestedCoverageTests, build_long_horizon_report(), fundamentals_candidate_queue(), hurdle_diagnostic() (+12 more)

### Community 16 - "llm_contract.py"
Cohesion: 0.21
Nodes (29): analyst_schema(), _assert_nonimperative(), _calculation_index(), critic_schema(), deterministic_claim_capture(), _entity_tickers(), _enum(), _identifier() (+21 more)

### Community 17 - "execution_common.py"
Cohesion: 0.13
Nodes (6): action_fixture(), decision_fixture(), EmailArtifactBindingTests, EmailPresentationTests, PlanningEmailTests, render_email()

### Community 18 - "verify_c5t_manual_action_boundary.py"
Cohesion: 0.11
Nodes (43): artifact_paths(), ArtifactError, atomic_write_bytes(), atomic_write_json(), build_chunks(), build_entry(), check_artifacts(), complete_cache_entry() (+35 more)

### Community 19 - "main"
Cohesion: 0.17
Nodes (24): Any, datetime, ValueError, current_inputs(), EvidenceFreshnessTests, receipt(), build_evidence_freshness_receipt(), EvidenceFreshnessError (+16 more)

### Community 20 - "account_common.py"
Cohesion: 0.11
Nodes (7): B2RefreshCadenceTests, ExitStack, Path, A failed child reserves its slot and waits for the next retry slot., The existing launchd job can refresh SEC evidence without B2 or email., The repair marker reuses local market data and cannot send email., The launchd probe maps only fixed status from the no-network B2 child.

### Community 21 - "PacketMarketObservationTests"
Cohesion: 0.16
Nodes (24): complete_inputs(), item(), ValuationEvidenceV1Tests, build_valuation_evidence_v1(), _calculation_receipt(), _InputSpec, _normalize_input(), _parse_decimal() (+16 more)

### Community 22 - "compare_policies"
Cohesion: 0.14
Nodes (9): build_automatic_evaluation(), build_blind_judge_target(), Create a deterministic candidate set without origin or model labels., fake_packet(), ShadowLlmTests, valid_analyst(), valid_critic(), valid_judge() (+1 more)

### Community 23 - "evaluate_shadow_llm_incremental_value.py"
Cohesion: 0.15
Nodes (30): action_review_display(), action_stability(), candidate_proposal_fingerprint(), candidate_stability(), execution_conflicts(), held_position_summary(), held_research_context(), is_action_transition() (+22 more)

### Community 24 - "applied_reconciliation_matches_current_state"
Cohesion: 0.18
Nodes (32): aggregate(), _atomic_private_snapshot_text(), _atomic_private_text(), _authority_checks(), _deduplicate_evidence(), _discover(), _evidence_keys(), load_automatic_bundle() (+24 more)

### Community 25 - "ResearchRiskLimitsTests"
Cohesion: 0.29
Nodes (16): atomic_write_csv(), append_jsonl(), classification(), evaluate(), forecast_origin(), jsonl(), main(), number() (+8 more)

### Community 26 - "portfolio_construction.py"
Cohesion: 0.23
Nodes (28): Any, _action_kind(), build_discovery_view(), build_email_view(), _comparison_weight(), _conflict_tasks(), _decimal(), email_subject() (+20 more)

### Community 27 - "next_thursday"
Cohesion: 0.11
Nodes (16): CanonicalWorkflowTests, OptionalActiveInputTests, registry_row(), _canonical_source_issues(), Check, collect_checks(), _deprecated_registry_issues(), _loaded() (+8 more)

### Community 28 - "verify_c2_email_delivery_boundary.py"
Cohesion: 0.07
Nodes (18): ActiveConfigError, load_active_config(), main(), Any, Path, ValueError, Raised when the active configuration is unsafe or incomplete., Validate an optional research overlay without accepting financial data. (+10 more)

### Community 29 - "HeldCorePositionTests"
Cohesion: 0.11
Nodes (21): classify_nonzero_exit(), cli_reported_token_usage(), CodexCliProvider, executable_sha256(), FixtureProvider, minimal_codex_environment(), Provider, ProviderResult (+13 more)

### Community 30 - "shadow_llm_contract.py"
Cohesion: 0.18
Nodes (22): append_run_log(), as_float(), concentration_status(), dynamic_candidate_fit(), dynamic_position_fit(), load_account_state(), load_active_inhibit(), load_market_rows() (+14 more)

### Community 34 - "ShadowLlmTests"
Cohesion: 0.15
Nodes (20): datetime, Independent official-news checks using the existing serialized scheduler.  No se, run_due_news_checks(), due_slots(), main(), market_snapshot_mode(), _market_step_passed(), _massive_auth_presence_probe_exit_code() (+12 more)

### Community 36 - "main"
Cohesion: 0.16
Nodes (10): MassiveB2AdapterResilienceTests, _payload(), The Basic delayed shape normalizes without leaking provider metadata., Ticker, adjustment, pagination, and malformed data each stop once., A provider 429 is one request and exposes neither URL detail nor key., Every new ticker is locally paced, while a failed request is never retried., Sanitized current Custom Bars shape, including optional metadata., The external-runtime key authorizes one request but never enters its URL/output. (+2 more)

### Community 37 - "Early Public Equity Lab"
Cohesion: 0.25
Nodes (8): Current Safe Status Commands, Current Workflow, Equity Research, Long-horizon workflow upgrade (2026-09-20), Repository Paths, Safety Boundaries, What The System Can Do, What The System Cannot Do

### Community 38 - "Phase 5R AI operating decision"
Cohesion: 0.20
Nodes (6): CacheTests, ledger_row(), NormalizationTests, Path, SelectionAndValidationTests, write_ledger()

### Community 39 - "Phase 5R — current document entrypoints"
Cohesion: 0.29
Nodes (4): Automatic event modes, Evaluation, Phase 5R SHADOW_LLM, Safe preflight

### Community 40 - "create_c5_weekly_conviction_memo.py"
Cohesion: 0.20
Nodes (17): main(), append_c9b_log(), execution_cash(), intraday_range_pct(), load_execution_rows(), optional_float(), parse_iso(), Path (+9 more)

### Community 41 - "score_candidates.py"
Cohesion: 0.17
Nodes (31): _effective_acceptance_map(), Return the immutable index plus every validated append-only extension., admit_unindexed_current_records(), _audit_row(), build_extension_artifact(), _core_record(), extension_acceptance_records(), _extension_number() (+23 more)

### Community 42 - "Phase 5R risk-policy audit — 2026-09-14"
Cohesion: 0.23
Nodes (5): CompactReviewTests, delivery_fixture(), owner_review_fixture(), OwnerReviewDeliveryTests, save_decision()

### Community 43 - "Owner-requested research reviews"
Cohesion: 0.40
Nodes (9): append_audit(), as_float(), clamp(), main(), Path, read_csv(), score_row(), timestamp() (+1 more)

### Community 44 - "economic_packet"
Cohesion: 0.14
Nodes (3): NamingCompatibilityTests, Display migration must preserve research meaning and delivery identity., OwnerSnapshotTests

### Community 46 - "ShadowLlmTests"
Cohesion: 0.24
Nodes (9): build_deterministic_baseline(), deterministic_claim_check(), _finite_number(), Decimal, Give the judge the facts/calculations already available without an LLM.      The, Conservative one-fact sign check, never a generic semantic truth judge.      Com, fact_packet(), net_loss_claim() (+1 more)

### Community 47 - "test_refresh_cadence.py"
Cohesion: 0.25
Nodes (15): csv_fields(), load_positions(), Path, write_csv(), write_text(), sha256(), main(), parse_args() (+7 more)

### Community 48 - "ShadowProviderError"
Cohesion: 0.16
Nodes (3): PacketMarketObservationTests, Path, write_csv()

### Community 49 - "ShadowMeasurementTests"
Cohesion: 0.18
Nodes (12): is_core_allocation_ticker(), Return whether a ticker is the policy-approved broad-market core., confirmed_thesis_break(), held_recommendation_label(), load_thesis_reviews(), main(), date, Optional analyst assessments; absence never turns a score into a sale. (+4 more)

### Community 50 - "ShadowMeasurementTests"
Cohesion: 0.21
Nodes (5): build_regime(), number(), Any, Use a single complete public close; repeated intraday runs add no votes., MarketRegimeTests

### Community 51 - "valuation_input_bundle.py"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 53 - "main"
Cohesion: 0.19
Nodes (3): decision_fixture(), discovery_fixture(), DiscoveryReportingTests

### Community 54 - "Phase 0C Reframe Plan"
Cohesion: 0.26
Nodes (6): applied_reconciliation_current_state_status(), applied_reconciliation_matches_current_state(), Classify whether a current C9 state remains consistent with one fill.      C9B r, Return the closed accepted subset of reconciliation-state statuses., C9BAccountSnapshotRefreshTests, _reconciliation()

### Community 55 - "AcceptanceReconciliationError"
Cohesion: 0.13
Nodes (25): acceptance_index_failure_reason(), Map acceptance validation failures to closed, non-sensitive status codes., acceptance_map(), AcceptanceReconciliationError, load_acceptance_index(), load_acceptance_reconciliation_log(), load_immutable_acceptance_index(), _make_reconciliation_row() (+17 more)

### Community 56 - "MarketRegimeTests"
Cohesion: 0.17
Nodes (12): Action-email presentation (v2, 2026-09-05), Boundaries, Display naming, Duplicate Protection, Eligibility, Explicit correction resend, Explicit owner-requested review (2026-09-14), Frequency (+4 more)

### Community 57 - "OfficialNewsScheduleTests"
Cohesion: 0.24
Nodes (13): Validate extension hashes, chain continuity, and audit bindings., _validate_runtime_evidence_chain(), extension_artifact_path(), load_extension_audit(), Path, Bind an extension to exact immutable historical-index bytes., Write exactly one new extension version; existing versions never change., Append any missing artifact-bound admission entries, never rewrites. (+5 more)

### Community 58 - "load_inhibit"
Cohesion: 0.20
Nodes (9): Boundaries, Broker and order mechanics, Delivery expectation, Email readability (2026-09-22 follow-up), Independent market discovery (2026-09-22 follow-up), One-year evaluation and tactical orders (2026-09-22), Owner-requested research reviews, Required review content (+1 more)

### Community 59 - "四项标准：工作流升级实施与验收"
Cohesion: 0.22
Nodes (8): Data Handling, Independent broad-market discovery extension (September 22, 2026), Permitted Source and Scope, Phase 5R-B2 Configured-Universe Data and Broad Discovery Policy, Purpose, Safety Boundary, Scoring, Tactical research extension (September 22, 2026)

### Community 60 - "main"
Cohesion: 0.22
Nodes (8): Facts, Estimates, and Opinions, Long-Term Interpretation, Phase 5R Daily Research Policy, Principle, Refresh and Freshness Rules, Request Discipline, Source coverage and research completeness, Source Hierarchy

### Community 61 - "create_long_horizon_research.py"
Cohesion: 0.25
Nodes (7): Active Workflow, Authority Order, Phase 5R-C8 Canonical Active-State Policy, Pipeline Requirement, Purpose, Safety Boundary, Stale-File Guard

### Community 64 - "workflow_standards_audit_20260920.md"
Cohesion: 0.29
Nodes (6): Canonical Inputs, Optional research-only risk limits, Phase 5R-C9 Account-State Policy, Privacy and Execution Boundary, Runtime State, Validation

### Community 65 - "score_candidates.py"
Cohesion: 0.29
Nodes (6): Admission requirements, Boundaries, Commit and recovery behavior, Immutable historical layer, Phase 5R SEC Acceptance-Index Extension Policy v1, Versioned artifacts and audit

### Community 66 - "ResearchRiskLimitsTests"
Cohesion: 0.52
Nodes (6): clamp(), main(), number(), Keep owner-requested research visible without granting trade eligibility., requested_coverage_tickers(), selected_tickers()

### Community 67 - "test_owner_snapshot.py"
Cohesion: 0.23
Nodes (7): main(), number(), Any, Solve required revenue for explicit terminal-multiple/return sensitivities., reverse_expectations(), whole_share_diagnostics(), ReassessmentReportingTests

### Community 69 - "Phase 5R-C9 Core Allocation Policy"
Cohesion: 0.33
Nodes (5): Action Inertia, Current-State Authority, Decision Priority, Phase 5R Daily Decision Policy, Required Presentation

### Community 70 - "ResearchRiskLimitsTests"
Cohesion: 0.33
Nodes (5): Boundaries, Current-State Authority, Phase 5R-C9B Manual Execution Policy, Purpose, State Contract

### Community 71 - "build_current_research_baseline.py"
Cohesion: 0.29
Nodes (6): Absolute-path audit, Failure behavior, Normal authoring and deployment, Phase5R MacBook → GitHub → Mac mini workflow, Production boundary, Runtime operations

### Community 72 - "report_heading"
Cohesion: 0.33
Nodes (5): Allowed Exact Actions, Current Positions, Maximum Entry and Trim Conditions, New Individual-Stock Eligibility, Phase 5R-C9 Action Threshold Policy

### Community 73 - "write_extension_admission_audit"
Cohesion: 0.33
Nodes (5): Concentration and Sleeve Rules, Current-Weight Formula, Phase 5R-C9 Dynamic Weight Policy, Price Quality, Stored Percentage Boundary

### Community 74 - "score_candidates.py"
Cohesion: 0.33
Nodes (5): Account Total, Canonical Update, Cash, Phase 5R-C9B Account Reconciliation Policy, Preconditions

### Community 75 - "_run_identity"
Cohesion: 0.33
Nodes (5): Boundary, Evidence, Order-Style Framework, Phase 5R-C9B Price Guidance Policy, Slippage Review Formula

### Community 76 - "main"
Cohesion: 0.33
Nodes (5): Active Boundary, Decision Implications, Measurement Contract, Objective, Phase 5R Long-Horizon Return Objective Policy

### Community 77 - "Phase 5R AI operating decision"
Cohesion: 0.40
Nodes (5): Boundaries, Decision, Future evaluation boundary, Historical decision evidence — August 31 only, Phase 5R AI operating decision

### Community 78 - "Early Public Equity Research"
Cohesion: 0.06
Nodes (71): main(), latest_published_market_session(), Return the newest close available under the Basic EOD publication SLA.      Mass, Any, date, HTTPRedirectHandler, RuntimeError, append_audit() (+63 more)

### Community 79 - "main"
Cohesion: 0.19
Nodes (12): _jsonl(), main(), _number(), Path, display(), main(), missing_label(), render_report() (+4 more)

### Community 81 - "Equity Research — current document entrypoints"
Cohesion: 0.18
Nodes (6): Authoritative policy and boundaries, Current runtime outputs — read their generated timestamps, Equity Research — current document entrypoints, Historical material — retained, not current instructions, 长期研究、倍增情景与证据边界, 四项投资工作流标准：实施计划与验收

### Community 82 - "Phase 5R-C9 Core Allocation Policy"
Cohesion: 0.50
Nodes (3): Cash-Deployment Decision, Phase 5R-C9 Core Allocation Policy, Separation

### Community 94 - "recommendation_notification_fingerprint"
Cohesion: 0.20
Nodes (4): notification_change_comparison(), Hash recommendation meaning, excluding quotes, dates and raw filings., recommendation_notification_fingerprint(), IndependentDiscoveryIntegrationTests

### Community 95 - "Equity Research 命名与归档规则"
Cohesion: 0.40
Nodes (4): “5R”的来源与结论, Equity Research 命名与归档规则, 兼容边界, 文件与目录

### Community 126 - "graphify reference: query, path, explain"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 127 - "Source Policy"
Cohesion: 0.25
Nodes (8): Calls and cost, Event-driven selection and replay, Evidence stages, Isolation and deterministic authority, Phase 5R SHADOW_LLM Evaluation Policy, Question being measured, Small evaluation architecture, Stop conditions

### Community 147 - "Phase 5R-C5 Verification Report"
Cohesion: 0.29
Nodes (7): Account Scope, Hard Rules, Portfolio Risk, Position Risk, Review Cadence, Risk Limits, Risk Policy

### Community 163 - "Phase 5R-C2 Verification Report"
Cohesion: 0.22
Nodes (7): File Conventions, graphify, Non-Negotiable Constraints, Owner-Requested Reviews and Email, Purpose, Research Standards, Script Safety

### Community 239 - "Phase 5R-D3G Research Verification Report"
Cohesion: 0.33
Nodes (5): Data Source Policy, Preferred Sources, Prohibited Sources And Data, Secondary Sources, Weak Evidence

### Community 241 - "Phase 5R-C9A Account-State and Stale-Denominator Audit Policy"
Cohesion: 0.33
Nodes (5): Citation Expectations, Source Policy, Strong Sources, Useful Secondary Sources, Weak Sources

### Community 242 - "enable_llm_live_shadow.py"
Cohesion: 0.33
Nodes (5): Approval, Market Quality, Research Completeness, Risk Controls, Trading Checklist

### Community 258 - "Phase 5R-C9 Core Allocation Policy"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 296 - "check_llm_shadow_status.sh"
Cohesion: 0.40
Nodes (4): Allowed, Brokerage Boundary, Human Responsibility, Prohibited

### Community 297 - "install_llm_shadow_scheduler.sh"
Cohesion: 0.40
Nodes (4): Approval Boundary, Manual Approval Policy, Out Of Scope, Required Before Approval

### Community 362 - "Phase 5R Model Shadow Readiness — Research Summary"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 363 - "ShadowOutputLock"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 364 - "anonymous_review_materials_status.md"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

## Knowledge Gaps
- **194 isolated node(s):** `activate_daily_after_verification.sh script`, `check_daily_scheduler_status.sh script`, `check_shadow_llm_evaluation_scheduler.sh script`, `clear_maintenance_inhibit.sh script`, `install_daily_schedulers.sh script` (+189 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **23 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `canonical_sha256()` connect `AST` to `market_data_adapter.py`, `test_owner_snapshot.py`, `send_c6_weekly_email.py`, `test_active_production.py`, `main`, `score_candidates.py`, `verify_daily_upgrade.py`, `verify_c6_weekly_email_boundary.py`, `portfolio_construction.py`, `llm_contract.py`, `AcceptanceReconciliationError`, `compare_policies`, `evaluate_shadow_llm_incremental_value.py`, `applied_reconciliation_matches_current_state`, `ResearchRiskLimitsTests`, `HeldCorePositionTests`, `recommendation_notification_fingerprint`?**
  _High betweenness centrality (0.062) - this node is a cross-community bridge._
- **Why does `main()` connect `evaluate_shadow_llm_incremental_value.py` to `AST`, `test_active_production.py`, `ShadowProviderError`, `main`, `main`, `verify_daily_upgrade.py`, `Early Public Equity Research`, `main`, `ShadowMeasurementTests`, `execution_common.py`, `portfolio_construction.py`, `verify_c2_email_delivery_boundary.py`, `recommendation_notification_fingerprint`?**
  _High betweenness centrality (0.058) - this node is a cross-community bridge._
- **Why does `render_email()` connect `execution_common.py` to `PacketMarketObservationTests`, `Phase 5R risk-policy audit — 2026-09-14`, `score_candidates.py`, `create_long_horizon_research.py`, `main`, `evaluate_shadow_llm_incremental_value.py`, `portfolio_construction.py`?**
  _High betweenness centrality (0.055) - this node is a cross-community bridge._
- **Are the 50 inferred relationships involving `render_email()` (e.g. with `main()` and `build_message()`) actually correct?**
  _`render_email()` has 50 INFERRED edges - model-reasoned connections that need verification._
- **Are the 49 inferred relationships involving `canonical_sha256()` (e.g. with `build_packet()` and `_fundamental_observations()`) actually correct?**
  _`canonical_sha256()` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `_execute_unlocked()` (e.g. with `canonical_sha256()` and `iso_now()`) actually correct?**
  _`_execute_unlocked()` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 22 inferred relationships involving `main()` (e.g. with `is_core_allocation_ticker()` and `load_active_config()`) actually correct?**
  _`main()` has 22 INFERRED edges - model-reasoned connections that need verification._