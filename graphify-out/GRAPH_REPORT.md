# Graph Report - equity  (2026-10-03)

## Corpus Check
- 323 files · ~302,306 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3578 nodes · 9325 edges · 181 communities (143 shown, 38 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 1763 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e7627539`
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
- workflow_health
- main
- Early Public Equity Lab
- ledger_row
- current_documents.md
- create_c5_weekly_conviction_memo.py
- score_candidates.py
- save_decision
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
- CandidateStabilityTests
- risk_profile_activation_20260914.md
- workflow_standards_audit_20260920.md
- score_candidates.py
- ResearchRiskLimitsTests
- test_owner_snapshot.py
- Equity Research 命名迁移验收
- Equity Research — Daily Decision Policy
- ResearchRiskLimitsTests
- build_current_research_baseline.py
- report_heading
- main
- score_candidates.py
- _run_identity
- main
- sec_acceptance_extensions.py
- Early Public Equity Research
- main
- create_long_horizon_research.py
- Equity Research — current document entrypoints
- test_sender_publication.py
- activate_daily_after_verification.sh
- check_daily_scheduler_status.sh
- clear_maintenance_inhibit.sh
- install_daily_schedulers.sh
- set_maintenance_inhibit.sh
- uninstall_daily_schedulers.sh
- next_thursday
- research_working_agreement.md
- main
- __init__.py
- SecAcceptanceReconciliationTests
- recommendation_notification_fingerprint
- Equity Research 命名与归档规则
- OwnerSnapshotTests
- RuntimePreflightAlertTests
- ResearchRiskLimitsTests
- workflow_health
- earnings_incorporation.py
- MaintainedThesisTests
- supplement_cached_latest_report
- IncorporationTests
- RecommendationNotificationTests
- RequestedCoverageTests
- Maintained investment research workflow
- delivery_meaning_key
- test_thesis_evidence.py
- _DocumentPeriod
- GraphDisplayNamesTests
- Workflow reliability and performance evidence
- main
- OwnerSnapshotTests
- cards
- Scoped blockers and recurring research work
- OwnerSnapshotTests
- MarketCoverageRecompositionTests
- .inputs
- main
- RuntimePreflightAlertTests
- long_horizon_research_policy.md
- issuer_news_continuity.md
- build_current_research_baseline.py
- Equity Research — Core Allocation Policy
- graphify reference: query, path, explain
- Source Policy
- main
- next_thursday
- Recurring analyst follow-through
- Pipeline audit and repair — September 28, 2026
- main
- score_candidates.py
- RecommendationNotificationTests
- objective_research_budget_20260928.md
- refresh_valuation_scenarios.py
- IncorporationTests
- test_refresh_cadence.py
- WorkQueueReportingTests
- sha256_file
- workflow_health
- LongHorizonDecisionDisciplineTests
- ResearchRiskLimitsTests
- Handler
- research_working_agreement.md
- Risk Policy
- write_acceptance_index
- MomentumStatusTests
- MomentumReviewStatusTests
- MomentumStatusTests
- ResearchRiskLimitsTests
- Equity Research — AI operating decision
- OwnerRefreshWindowsTests
- main
- connect_private.py
- _DocumentPeriod
- Equity Research 命名与归档规则
- test_manual_valuation_bootstrap.py
- Equity Research — SHADOW_LLM Evaluation Policy
- supplement_cached_latest_report
- feedback_blocker
- AGENTS.md
- FrozenRuntimeTests
- main
- IncorporationTests
- RuntimePreflightAlertTests
- test_momentum_price_coverage.py
- Data Source Policy
- Source Policy
- enable_llm_live_shadow.py
- graphify reference: query, path, explain
- check_llm_shadow_status.sh
- install_llm_shadow_scheduler.sh
- graphify reference: add a URL and watch a folder
- ShadowOutputLock
- anonymous_review_materials_status.md
- CodexCliProvider
- iso_now
- extraction-spec.md

## God Nodes (most connected - your core abstractions)
1. `canonical_sha256()` - 112 edges
2. `render_email()` - 73 edges
3. `read_json()` - 51 edges
4. `ExclusiveFileLock` - 47 edges
5. `main()` - 46 edges
6. `build_email_view()` - 41 edges
7. `iso_now()` - 40 edges
8. `now_et()` - 38 edges
9. `main()` - 38 edges
10. `_execute_unlocked()` - 38 edges

## Surprising Connections (you probably didn't know these)
- `verify_publication()` --calls--> `render_email()`  [INFERRED]
  10_dashboard/feedback.py → 09_scripts/equity_research/email_brief.py
- `atomic()` --calls--> `archive_before_replace()`  [INFERRED]
  10_dashboard/feedback.py → 09_scripts/equity_research/portfolio_archive.py
- `chart()` --calls--> `_validated_bars()`  [INFERRED]
  10_dashboard/server.py → 09_scripts/equity_research/tactical_review.py
- `main()` --calls--> `Store`  [INFERRED]
  10_dashboard/record_feedback.py → 10_dashboard/feedback.py
- `write_text()` --calls--> `archive_before_replace()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/portfolio_archive.py

## Import Cycles
- None detected.

## Communities (181 total, 38 thin omitted)

### Community 0 - "market_data_adapter.py"
Cohesion: 0.06
Nodes (47): feedback_blocker(), Path, Fail-closed publication barrier for unresolved owner-reported facts., append_plan(), apply_plan_context(), _bound_sources(), evaluate_plans(), _expired_at() (+39 more)

### Community 1 - "run_full_universe_market_data.py"
Cohesion: 0.22
Nodes (26): _canonical_sha256(), _declared_tickers(), _is_within(), load_valuation_input_bundle(), main(), _packet_as_of(), _parse_utc(), Any (+18 more)

### Community 2 - "AST"
Cohesion: 0.13
Nodes (55): canonical_sha256(), _append_ledger_event(), _archive_packet(), _archived_packet_index(), _atomic_private_json(), _atomic_private_text(), _contract_failure_code(), critic_route() (+47 more)

### Community 3 - "send_c6_weekly_email.py"
Cohesion: 0.05
Nodes (79): _allowed_classifications_by_ticker(), _artifact_map(), build_packet(), _compact_fact_provenance(), _date_from_period(), _decimal(), _decision_tickers(), _entities() (+71 more)

### Community 4 - "test_active_production.py"
Cohesion: 0.14
Nodes (39): acceptance_map(), main(), current_submission_entity_name(), _debt_fact(), _derived_fact(), _derived_provenance(), _duration_days(), duration_values() (+31 more)

### Community 5 - "score_b_candidates.py"
Cohesion: 0.05
Nodes (59): ExclusiveFileLock, Process lock using flock over a private, non-linked regular file., _append_execution_record(), assert_non_icloud_runtime_root(), _best_effort_failure_record(), _best_effort_preflight_alert(), _deployment_receipt_path(), _eligible_connectivity_failure() (+51 more)

### Community 6 - "ShadowProviderError"
Cohesion: 0.10
Nodes (29): build_report(), _cache_read(), _cache_write(), _digest(), DiscoveryClient, DiscoveryError, _empty(), _http_get() (+21 more)

### Community 7 - "main"
Cohesion: 0.20
Nodes (3): atomic_write_csv(), inline(), ResearchBacklogTests

### Community 8 - "ShadowLlmTests"
Cohesion: 0.11
Nodes (21): B2MarketRefreshFailureCommitTests, _candidate_row(), _CompleteCachedClient, _DuplicateSessionErrorClient, _FailingFullFetchClient, _market_row(), _PartialApprovedTickerClient, date (+13 more)

### Community 9 - "main"
Cohesion: 0.16
Nodes (7): Path, Persist one private atomic state containing history; fail without erasing it., refresh_capital_work_queue(), CapitalWorkQueueTests, decision(), plan(), write_valid_backlog()

### Community 10 - "PacketMarketObservationTests"
Cohesion: 0.17
Nodes (29): now_et(), append_delivery(), _attempt_identity(), build_message(), ConfigError, correction_eligibility(), _current_cycle_receipts(), cycle_is_blocked() (+21 more)

### Community 11 - "verify_daily_upgrade.py"
Cohesion: 0.07
Nodes (28): evaluate_archived(), Evaluate retained observations with their exact archived implementation.  Only e, build_tactical_review(), _day(), _integer(), _last_sessions(), load_tactical_review(), _money() (+20 more)

### Community 12 - "iso_now"
Cohesion: 0.12
Nodes (14): InlineFacts, parse_principal_facts(), project_relative_locator(), Any, datetime, HTMLParser, Path, ValueError (+6 more)

### Community 13 - "verify_c6_weekly_email_boundary.py"
Cohesion: 0.12
Nodes (23): canonical_url(), clean_title(), fetch_feed(), load_manifest(), NewsError, OfficialRedirect, parse_feed(), _PlainText (+15 more)

### Community 14 - "score_candidates.py"
Cohesion: 0.18
Nodes (12): compare_policies(), _decimal(), Holding, _number(), Compare capacities independently, never sum candidate share counts.  These are u, Apply explicit per-ticker price shocks simultaneously, keeping cash fixed.  Ever, RiskPolicy, simultaneous_stress() (+4 more)

### Community 15 - "ShadowMeasurementTests"
Cohesion: 0.16
Nodes (20): build_long_horizon_report(), fundamentals_candidate_queue(), hurdle_diagnostic(), number(), provenance(), Any, datetime, Path (+12 more)

### Community 16 - "llm_contract.py"
Cohesion: 0.15
Nodes (34): analyst_schema(), _assert_nonimperative(), build_blind_judge_target(), build_deterministic_baseline(), _calculation_index(), critic_schema(), deterministic_claim_capture(), _entity_tickers() (+26 more)

### Community 17 - "execution_common.py"
Cohesion: 0.13
Nodes (6): render_email(), action_fixture(), decision_fixture(), EmailArtifactBindingTests, EmailPresentationTests, PlanningEmailTests

### Community 18 - "verify_c5t_manual_action_boundary.py"
Cohesion: 0.11
Nodes (43): artifact_paths(), ArtifactError, atomic_write_bytes(), atomic_write_json(), build_chunks(), build_entry(), check_artifacts(), complete_cache_entry() (+35 more)

### Community 19 - "main"
Cohesion: 0.17
Nodes (24): Any, datetime, ValueError, current_inputs(), EvidenceFreshnessTests, receipt(), build_evidence_freshness_receipt(), EvidenceFreshnessError (+16 more)

### Community 20 - "account_common.py"
Cohesion: 0.10
Nodes (9): B2RefreshCadenceTests, _market_row(), ExitStack, Path, A failed child reserves its slot and waits for the next retry slot., The existing launchd job can refresh SEC evidence without B2 or email., The repair marker reuses local market data and cannot send email., The launchd probe maps only fixed status from the no-network B2 child. (+1 more)

### Community 21 - "PacketMarketObservationTests"
Cohesion: 0.15
Nodes (20): _aware(), _blockers(), build_capital_work_queue(), compact_summary(), _item_semantic(), _money(), _next_check(), _plan_needed() (+12 more)

### Community 22 - "compare_policies"
Cohesion: 0.17
Nodes (6): FailingProvider, fake_packet(), ShadowLlmTests, valid_analyst(), valid_critic(), valid_judge()

### Community 23 - "evaluate_shadow_llm_incremental_value.py"
Cohesion: 0.12
Nodes (34): action_review_display(), action_stability(), candidate_proposal_fingerprint(), candidate_stability(), execution_conflicts(), held_position_summary(), held_research_context(), is_action_transition() (+26 more)

### Community 24 - "applied_reconciliation_matches_current_state"
Cohesion: 0.20
Nodes (30): aggregate(), _atomic_private_snapshot_text(), _atomic_private_text(), _authority_checks(), _deduplicate_evidence(), _discover(), _evidence_keys(), load_automatic_bundle() (+22 more)

### Community 25 - "ResearchRiskLimitsTests"
Cohesion: 0.15
Nodes (38): _effective_acceptance_map(), Return the immutable index plus every validated append-only extension., admit_unindexed_current_records(), _audit_row(), build_extension_artifact(), _core_record(), extension_acceptance_records(), extension_artifact_path() (+30 more)

### Community 26 - "portfolio_construction.py"
Cohesion: 0.19
Nodes (33): _action_kind(), build_discovery_view(), build_email_view(), _comparison_weight(), _conflict_tasks(), _decimal(), email_subject(), _is_core() (+25 more)

### Community 27 - "next_thursday"
Cohesion: 0.11
Nodes (16): CanonicalWorkflowTests, OptionalActiveInputTests, registry_row(), _canonical_source_issues(), Check, collect_checks(), _deprecated_registry_issues(), _loaded() (+8 more)

### Community 28 - "verify_c2_email_delivery_boundary.py"
Cohesion: 0.12
Nodes (13): AcceptanceIndexError, build_acceptance_index(), make_acceptance_record(), ValueError, The SEC acceptance index failed its closed validation contract., validate_acceptance_index(), Regression coverage for the SEC acceptance precommit boundary., Run an offline refresh that must fail before any evidence commit. (+5 more)

### Community 29 - "HeldCorePositionTests"
Cohesion: 0.13
Nodes (18): classify_nonzero_exit(), cli_reported_token_usage(), CodexCliProvider, executable_sha256(), minimal_codex_environment(), Provider, ProviderResult, Any (+10 more)

### Community 30 - "shadow_llm_contract.py"
Cohesion: 0.10
Nodes (36): append_run_log(), as_float(), concentration_status(), dynamic_candidate_fit(), dynamic_position_fit(), is_core_allocation_ticker(), load_account_state(), load_active_inhibit() (+28 more)

### Community 34 - "ShadowLlmTests"
Cohesion: 0.15
Nodes (20): datetime, Independent official-news checks using the existing serialized scheduler.  No se, run_due_news_checks(), due_slots(), main(), market_snapshot_mode(), _market_step_passed(), _massive_auth_presence_probe_exit_code() (+12 more)

### Community 35 - "workflow_health"
Cohesion: 0.12
Nodes (21): chart(), current_snapshot(), digest(), email_version(), email_versions(), Handler, main(), number() (+13 more)

### Community 36 - "main"
Cohesion: 0.16
Nodes (10): MassiveB2AdapterResilienceTests, _payload(), The Basic delayed shape normalizes without leaking provider metadata., Ticker, adjustment, pagination, and malformed data each stop once., A provider 429 is one request and exposes neither URL detail nor key., Every new ticker is locally paced, while a failed request is never retried., Sanitized current Custom Bars shape, including optional metadata., The external-runtime key authorizes one request but never enters its URL/output. (+2 more)

### Community 37 - "Early Public Equity Lab"
Cohesion: 0.18
Nodes (20): acceptance_map(), load_acceptance_index(), load_immutable_acceptance_index(), _make_reconciliation_row(), normalize_acceptance_timestamp(), _normalize_generated_at(), Any, datetime (+12 more)

### Community 38 - "ledger_row"
Cohesion: 0.18
Nodes (8): fetch(), Path, CacheTests, ledger_row(), NormalizationTests, Path, SelectionAndValidationTests, write_ledger()

### Community 39 - "current_documents.md"
Cohesion: 0.12
Nodes (10): Cash-Deployment Decision, Equity Research — Core Allocation Policy, Separation, Maintained company research, effective 2026-09-24, 长期研究、倍增情景与证据边界, Explicit purpose, Position purpose and reassessment, Required reassessment (+2 more)

### Community 40 - "create_c5_weekly_conviction_memo.py"
Cohesion: 0.13
Nodes (31): csv_fields(), load_positions(), Path, write_text(), main(), append_c9b_log(), execution_cash(), intraday_range_pct() (+23 more)

### Community 41 - "score_candidates.py"
Cohesion: 0.20
Nodes (8): Fail closed before producing a range, not merely before order routing., valuation_input_issues(), duration(), facts(), FinancialPeriodIntegrityTests, fixture(), instant(), row()

### Community 42 - "save_decision"
Cohesion: 0.20
Nodes (5): CompactReviewTests, delivery_fixture(), owner_review_fixture(), OwnerReviewDeliveryTests, save_decision()

### Community 43 - "Owner-requested research reviews"
Cohesion: 0.14
Nodes (34): append_review(), _day(), _DocumentPeriod, evaluate_thesis(), evidence_context(), _inside(), material_filing_receipt(), Any (+26 more)

### Community 44 - "economic_packet"
Cohesion: 0.08
Nodes (49): actionNames, App(), AuditTrail(), blockerNames, blockerText(), errorNames, FeedbackForm(), formalErrors (+41 more)

### Community 46 - "ShadowLlmTests"
Cohesion: 0.08
Nodes (14): ActiveConfigError, load_active_config(), main(), Any, Path, ValueError, Raised when the active configuration is unsafe or incomplete., Validate an optional research overlay without accepting financial data. (+6 more)

### Community 47 - "test_refresh_cadence.py"
Cohesion: 0.19
Nodes (18): build_report(), main(), render(), append_record(), finite(), load_performance_records(), operational_summary(), Any (+10 more)

### Community 49 - "ShadowMeasurementTests"
Cohesion: 0.17
Nodes (16): ValuationResearchArchiveTests, archive_bytes(), _archive_snapshot(), compose_research_inputs(), generated_record(), _owned_directory(), _parse_snapshot(), _publish_private() (+8 more)

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
Cohesion: 0.14
Nodes (32): main(), append_chained(), _attempt_summary(), comparison_markdown(), evaluate(), failure_reason(), next_open_session(), number() (+24 more)

### Community 56 - "MarketRegimeTests"
Cohesion: 0.12
Nodes (16): Action-email presentation (v2, 2026-09-05), Boundaries, Current delivery and presentation rule (2026-09-26), Display naming, Duplicate Protection, Eligibility, Equity Research — Daily Delivery Policy, Explicit correction resend (+8 more)

### Community 57 - "OfficialNewsScheduleTests"
Cohesion: 0.32
Nodes (5): chained(), MomentumExperimentReviewTests, observations(), outcome(), payloads()

### Community 58 - "load_inhibit"
Cohesion: 0.14
Nodes (13): Action-first regular email (2026-09-29), Boundaries, Broker and order mechanics, Current email correction (2026-09-26), Delivery expectation, Durable follow-through for interactive reviews (2026-09-28), Email readability (2026-09-22 follow-up), Independent market discovery (2026-09-22 follow-up) (+5 more)

### Community 59 - "四项标准：工作流升级实施与验收"
Cohesion: 0.14
Nodes (12): Applied scheduling interpretation, Bounded observation on the installed collector, Endpoint and primary sources, REST collector timing evidence — September 28, 2026, Data Handling, Equity Research — Configured-Universe Data and Broad Discovery Policy, Independent broad-market discovery extension (September 22, 2026), Permitted Source and Scope (+4 more)

### Community 60 - "main"
Cohesion: 0.09
Nodes (21): dependencies, lucide-react, react, react-dom, devDependencies, tsx, @types/node, @types/react (+13 more)

### Community 61 - "create_long_horizon_research.py"
Cohesion: 0.25
Nodes (7): Active Workflow, Authority Order, Equity Research — Canonical Active-State Policy, Pipeline Requirement, Purpose, Safety Boundary, Stale-File Guard

### Community 63 - "risk_profile_activation_20260914.md"
Cohesion: 0.16
Nodes (22): clear_automation_alert(), iso_now(), Clear any prior terminal alert after a completed daily decision., active_delivery_window(), configured_delivery_windows(), delivery_window_by_id(), Any, datetime (+14 more)

### Community 64 - "workflow_standards_audit_20260920.md"
Cohesion: 0.29
Nodes (7): Canonical Inputs, Equity Research — Account-State Policy, Manual UI valuation bootstrap, Optional research-only risk limits, Privacy and Execution Boundary, Runtime State, Validation

### Community 65 - "score_candidates.py"
Cohesion: 0.29
Nodes (6): Admission requirements, Boundaries, Commit and recovery behavior, Equity Research — SEC Acceptance-Index Extension Policy v1, Immutable historical layer, Versioned artifacts and audit

### Community 66 - "ResearchRiskLimitsTests"
Cohesion: 0.18
Nodes (9): _official_follow_up(), Resolve only mechanically scoped facts with NEW later official provenance., build_automatic_evaluation(), deterministic_claim_check(), Conservative one-fact sign check, never a generic semantic truth judge.      Com, evaluation_bundle(), fact_packet(), net_loss_claim() (+1 more)

### Community 68 - "Equity Research 命名迁移验收"
Cohesion: 0.14
Nodes (13): write_csv(), archive_before_replace(), _archive_location(), _private_directory(), Path, Keep exact private predecessors when portfolio files are replaced.  The active f, Fail closed if a changed predecessor cannot be safely preserved., Cover direct owner edits as well as the writers hooked above. (+5 more)

### Community 69 - "Equity Research — Daily Decision Policy"
Cohesion: 0.33
Nodes (5): Action Inertia, Current-State Authority, Decision Priority, Equity Research — Daily Decision Policy, Required Presentation

### Community 70 - "ResearchRiskLimitsTests"
Cohesion: 0.33
Nodes (5): Boundaries, Current-State Authority, Equity Research — Manual Execution Policy, Purpose, State Contract

### Community 71 - "build_current_research_baseline.py"
Cohesion: 0.25
Nodes (7): Absolute-path audit, Bounded collection continuity during network failure, Equity Research — MacBook → GitHub → Mac mini workflow, Failure behavior, Normal authoring and deployment, Production boundary, Runtime operations

### Community 72 - "report_heading"
Cohesion: 0.23
Nodes (14): main(), build_review(), _cohort(), markdown(), datetime, Path, ValueError, Prepare an early manual-review packet without changing the frozen experiment. (+6 more)

### Community 73 - "main"
Cohesion: 0.23
Nodes (3): archive(), decision(), FollowthroughTests

### Community 74 - "score_candidates.py"
Cohesion: 0.12
Nodes (31): main(), append_csv_durable(), atomic_write_json(), atomic_write_text(), cycle_date(), easter_sunday(), expected_market_session(), is_us_market_session_date() (+23 more)

### Community 75 - "_run_identity"
Cohesion: 0.17
Nodes (15): active_document(), audit(), first_heading(), main(), Path, tracked_markdown(), atomic_write(), main() (+7 more)

### Community 76 - "main"
Cohesion: 0.18
Nodes (13): deployment_health(), jsonl_count(), main(), momentum_health(), momentum_review_health(), Any, datetime, Path (+5 more)

### Community 77 - "sec_acceptance_extensions.py"
Cohesion: 0.17
Nodes (13): atomic(), csv_bytes(), encoded(), Path, ValueError, Analyst work is a separate queue, never a deterministic refresh result., Local analyst admission; the browser cannot claim or complete a review., Verify the final visible publication, beyond hashes on stale content. (+5 more)

### Community 78 - "Early Public Equity Research"
Cohesion: 0.06
Nodes (72): report_heading(), api_key_from_environment(), _default_http_get(), _finite_number(), _http_failure_code(), MassiveB2Error, MassiveBasicEODClient, _NoRedirectHandler (+64 more)

### Community 79 - "main"
Cohesion: 0.16
Nodes (23): _append(), _hash(), merge_news_context(), Any, datetime, Path, Private source-bound issuer-news continuity; collectors never infer a view.  The, Merge retained identities and current verified observations, idempotently. (+15 more)

### Community 80 - "create_long_horizon_research.py"
Cohesion: 0.22
Nodes (10): AcceptanceReconciliationError, load_acceptance_reconciliation_log(), Fields that must remain fixed across an idempotent log retry., Load the append-only reconciliation log or fail closed on corruption., Append only newly observed, validated timestamp reconciliations.      The histor, A current SEC record cannot be reconciled to the immutable index., _reconciliation_identity(), write_acceptance_reconciliation_log() (+2 more)

### Community 81 - "Equity Research — current document entrypoints"
Cohesion: 0.11
Nodes (4): HeldCorePositionTests, RequestedCoverageTests, rows(), FeedbackTests

### Community 82 - "test_sender_publication.py"
Cohesion: 0.26
Nodes (19): _archive(), build_followthrough(), continuation_lines(), continuation_requires_reconciliation(), _displayed_actions(), _identity(), _positive(), Any (+11 more)

### Community 89 - "next_thursday"
Cohesion: 0.15
Nodes (12): compilerOptions, allowImportingTsExtensions, jsx, lib, module, moduleResolution, noEmit, skipLibCheck (+4 more)

### Community 90 - "research_working_agreement.md"
Cohesion: 0.33
Nodes (5): Account Total, Canonical Update, Cash, Equity Research — Account Reconciliation Policy, Preconditions

### Community 91 - "main"
Cohesion: 0.33
Nodes (5): Allowed Exact Actions, Current Positions, Equity Research — Action Threshold Policy, Maximum Entry and Trim Conditions, New Individual-Stock Eligibility

### Community 92 - "__init__.py"
Cohesion: 0.31
Nodes (15): main(), _accessions(), assess_company(), build_earnings_incorporation(), Any, datetime, Path, Hash-bound financial selection receipts and offline incorporation gate.  Collect (+7 more)

### Community 93 - "SecAcceptanceReconciliationTests"
Cohesion: 0.14
Nodes (12): WorkQueueReportingTests, cash_lines(), _money(), Any, datetime, Path, Read and present recurring work without granting decision authority., A prior success file cannot conceal a failed or stale scheduled step. (+4 more)

### Community 95 - "Equity Research 命名与归档规则"
Cohesion: 0.40
Nodes (5): Authoritative policy and boundaries, Current runtime outputs — read their generated timestamps, Dashboard implementation and remaining phases, Equity Research — current document entrypoints, Historical material — retained, not current instructions

### Community 96 - "OwnerSnapshotTests"
Cohesion: 0.14
Nodes (24): Read the rendered email body without markup, head or style content., visible_html_text(), WorkflowPublicationTests, _account_blockers(), apply_workflow_integrity(), current_news_context(), current_thesis_views(), incorporation_meaning() (+16 more)

### Community 97 - "RuntimePreflightAlertTests"
Cohesion: 0.33
Nodes (12): add_check(), append_verification_log(), file_digest_or_absent(), loaded(), main(), plist_checks(), pure_guard_tests(), Path (+4 more)

### Community 99 - "workflow_health"
Cohesion: 0.09
Nodes (17): cards(), core_tranche_line(), core_tranche_steps(), _current_tactical_drafts(), eligible_core_tranche(), _order_lines(), owner_check_window(), Any (+9 more)

### Community 100 - "earnings_incorporation.py"
Cohesion: 0.33
Nodes (5): Concentration and Sleeve Rules, Current-Weight Formula, Equity Research — Dynamic Weight Policy, Price Quality, Stored Percentage Boundary

### Community 101 - "MaintainedThesisTests"
Cohesion: 0.14
Nodes (7): fixture(), MaintainedThesisTests, material_fixture(), ValueError, The review cannot be used as a current maintained conclusion., seal_review(), ThesisValidationError

### Community 103 - "IncorporationTests"
Cohesion: 0.25
Nodes (7): External feasibility sources (checked September 27, 2026), Frozen experiment and limits, Momentum integration decision — 2026-09-27, Owner-approved first-cohort review timing — September 27 follow-up, Source-grounded integration choices, What runs without another chat, What was verified

### Community 104 - "RecommendationNotificationTests"
Cohesion: 0.33
Nodes (5): Boundary, Equity Research — Price Guidance Policy, Evidence, Order-Style Framework, Slippage Review Formula

### Community 105 - "RequestedCoverageTests"
Cohesion: 0.33
Nodes (5): Different challenges must remain separate, Documented practices and the limits of importing them, Evidence classification, Proposed workspace adaptations (our design, not Ross's rules), Ross Cameron primary-source audit

### Community 106 - "Maintained investment research workflow"
Cohesion: 0.29
Nodes (6): Daily and longer-horizon work, Information flow and authority, Limitations that remain deliberate, Maintained investment research workflow, Operational reliability, Private records and operator updates

### Community 107 - "delivery_meaning_key"
Cohesion: 0.19
Nodes (15): covered_by_last_delivery(), delivery_meaning_key(), delivery_notification_comparison(), latest_delivery_receipt(), Any, datetime, Path, Delivery-only comparison against what the owner actually received.  Research fin (+7 more)

### Community 109 - "_DocumentPeriod"
Cohesion: 0.33
Nodes (5): Active Boundary, Decision Implications, Equity Research — Long-Horizon Return Objective Policy, Measurement Contract, Objective

### Community 111 - "Workflow reliability and performance evidence"
Cohesion: 0.40
Nodes (4): Confirmed actual account observations, Operational measurement, Recommendation evaluation, Workflow reliability and performance evidence

### Community 112 - "main"
Cohesion: 0.27
Nodes (13): clamp(), main(), number(), price_unverified_research_row(), Keep owner-requested research visible without granting trade eligibility., requested_coverage_tickers(), requested_only_price_unverified(), selected_tickers() (+5 more)

### Community 113 - "OwnerSnapshotTests"
Cohesion: 0.10
Nodes (15): Boundaries, Decision, Equity Research — AI operating decision, Future evaluation boundary, Historical decision evidence — August 31 only, Immutable execution and admission, Interpreting progress, Introducing another experiment version (+7 more)

### Community 114 - "cards"
Cohesion: 0.15
Nodes (13): Equity Research Dashboard 分阶段搭建计划, Phase 0/1 完成记录与当时证据, Phase 0 定义数据和操作契约, Phase 1 查看和试填页面, Phase 2–3 实施记录, Phase 2 正式写入和完整重算, Phase 3 手机访问和日 K 线, Phase 4 根据使用反馈调整 (+5 more)

### Community 115 - "Scoped blockers and recurring research work"
Cohesion: 0.33
Nodes (5): Blocker scope, Bounded objective research, Cash and recurring work, Expired plans and reporting, Scoped blockers and recurring research work

### Community 116 - "OwnerSnapshotTests"
Cohesion: 0.25
Nodes (8): Equity Research Dashboard Phase 0 和 Phase 1 契约, Phase 1 的边界和后续接点, 数据入口和输出, 演示记录和状态流转, 用户可观察的结果, 表单字段和校验, 页面与状态规则, 验收证据

### Community 117 - "MarketCoverageRecompositionTests"
Cohesion: 0.35
Nodes (7): _bundle(), _input(), Path, _source(), ValuationInputBundleTests, _write_bundle(), _write_source()

### Community 118 - ".inputs"
Cohesion: 0.22
Nodes (8): Equity Research — Daily Research Policy, Facts, Estimates, and Opinions, Long-Term Interpretation, Principle, Refresh and Freshness Rules, Request Discipline, Source coverage and research completeness, Source Hierarchy

### Community 120 - "main"
Cohesion: 0.47
Nodes (3): compare(), CrossDayDeliveryTests, receipt()

### Community 121 - "RuntimePreflightAlertTests"
Cohesion: 0.24
Nodes (6): base(), flow(), nav(), review(), WorkflowEvaluationTests, performance_summary()

### Community 122 - "long_horizon_research_policy.md"
Cohesion: 0.16
Nodes (14): _jsonl(), main(), _number(), Path, display(), main(), missing_label(), render_report() (+6 more)

### Community 124 - "build_current_research_baseline.py"
Cohesion: 0.15
Nodes (3): PacketMarketObservationTests, Path, write_csv()

### Community 125 - "Equity Research — Core Allocation Policy"
Cohesion: 0.18
Nodes (15): _execute_frozen(), _execute_outcomes(), load_registry(), _module_imports(), Run an explicitly registered experiment from immutable, verified Git bytes.  Liv, Import-time dependencies; function-local imports stay outside the entry API., Validate all version bindings, stage a frozen run, then publish its append., run_frozen() (+7 more)

### Community 126 - "graphify reference: query, path, explain"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 127 - "Source Policy"
Cohesion: 0.25
Nodes (8): Current Safe Status Commands, Current Workflow, Equity Research, Long-horizon workflow upgrade (2026-09-20), Repository Paths, Safety Boundaries, What The System Can Do, What The System Cannot Do

### Community 131 - "Recurring analyst follow-through"
Cohesion: 0.22
Nodes (8): Authority, Dashboard request receipts, Durable completion receipt, Each run, Full no-send refresh after admission, Locking and publication, Recurring analyst follow-through, Writer paths and admission modes

### Community 132 - "Pipeline audit and repair — September 28, 2026"
Cohesion: 0.40
Nodes (4): Close the analytical follow-through gap, Pipeline audit and repair — September 28, 2026, Preserve the forward experiment across a software repair, Repaired contracts

### Community 133 - "main"
Cohesion: 0.22
Nodes (9): archive_validated_delivery(), _matches(), Path, Retain exact validated message inputs before a durable delivery claim.  Only dec, Remove only known dead-process temporary links to these exact bytes.      Unknow, Atomically publish immutable content-addressed files; fail before send.      Par, _recover_crashed_publish_links(), DeliveryArchiveTests (+1 more)

### Community 134 - "score_candidates.py"
Cohesion: 0.18
Nodes (5): bind_dashboard_link(), publication_id(), Path, Snapshot a private dashboard link; rendering never reads mutable config., PrivateRoutesTests

### Community 138 - "IncorporationTests"
Cohesion: 0.12
Nodes (17): JSON object with out-of-band raw-byte receipt (never inserted in facts)., SecPayload, acceptance_index_failure_reason(), approved_inline_tags(), classify_materiality(), company_fundamentals_required(), count_unindexed_acceptance_accessions(), load_ticker_map() (+9 more)

### Community 139 - "test_refresh_cadence.py"
Cohesion: 0.17
Nodes (10): append_audit(), as_float(), clamp(), main(), Path, read_csv(), score_row(), timestamp() (+2 more)

### Community 140 - "WorkQueueReportingTests"
Cohesion: 0.20
Nodes (3): DeliveryWindowTests, receipt(), stamp()

### Community 141 - "sha256_file"
Cohesion: 0.23
Nodes (20): append_jsonl(), classification(), evaluate(), forecast_origin(), jsonl(), linked_record(), main(), market_sessions() (+12 more)

### Community 142 - "workflow_health"
Cohesion: 0.47
Nodes (3): Keep operational completion, maintained views, and price readiness separate., workflow_health(), CurrentWorkflowStatusTests

### Community 143 - "LongHorizonDecisionDisciplineTests"
Cohesion: 0.25
Nodes (11): line_excerpt(), main(), number(), Any, Path, Match the packet clock's whole-second point-in-time precision., selected_band(), source() (+3 more)

### Community 145 - "Handler"
Cohesion: 0.27
Nodes (8): binding(), catalog(), main(), matching_summary(), Version-bound presentation notes; never a research or account input., source_hash(), validate_catalog(), PlanSummaryTests

### Community 146 - "research_working_agreement.md"
Cohesion: 0.16
Nodes (16): bool_value(), delivery_guard(), load_active_state(), load_inhibit(), notification_change_comparison(), Any, Hash recommendation meaning, excluding quotes, dates and raw filings., read_json() (+8 more)

### Community 147 - "Risk Policy"
Cohesion: 0.25
Nodes (7): Account Scope, Hard Rules, Portfolio Risk, Position Risk, Review Cadence, Risk Limits, Risk Policy

### Community 148 - "write_acceptance_index"
Cohesion: 0.42
Nodes (5): Bind an extension to exact immutable historical-index bytes., raw_file_sha256(), write_acceptance_index(), acceptance_record(), SecAcceptanceExtensionTests

### Community 149 - "MomentumStatusTests"
Cohesion: 0.29
Nodes (7): Equity Research 私人工作台, Tailscale 私人连接, 发布和服务, 日常使用, 日常登记与研究复审, 权威状态与后台, 验证和历史

### Community 152 - "ResearchRiskLimitsTests"
Cohesion: 0.15
Nodes (7): core_starter_decision(), individual_sizing_decision(), _passed_confidence(), Any, Size one staged broad-market core review without using stock valuation., Return the highest supported sizing tier and a feasible share count., ResearchRiskLimitsTests

### Community 153 - "Equity Research — AI operating decision"
Cohesion: 0.57
Nodes (3): actionable_fixture(), publication_fixture(), SenderPublicationTests

### Community 156 - "connect_private.py"
Cohesion: 0.13
Nodes (11): command(), main(), our_route(), Bind only the signed-in owner's Tailscale identity to HTTPS Serve.  Run after th, Allow a retry only when every existing route belongs to this app., cash(), dec(), Durable human feedback coordinator. Canonical CSV/JSON remain authoritative.  Th (+3 more)

### Community 157 - "_DocumentPeriod"
Cohesion: 0.31
Nodes (16): _append_history(), build_backlog(), complete_objective_data(), _history(), numeric(), datetime, Path, Bounded, offline SEC research completion; never analyst signoff or trading.  The (+8 more)

### Community 158 - "Equity Research 命名与归档规则"
Cohesion: 0.25
Nodes (6): Equity Research 改动验收入口, “5R”的来源与结论, Equity Research 命名与归档规则, 兼容边界, 文件与目录, 派生知识图谱显示名

### Community 160 - "Equity Research — SHADOW_LLM Evaluation Policy"
Cohesion: 0.25
Nodes (8): Calls and cost, Equity Research — SHADOW_LLM Evaluation Policy, Event-driven selection and replay, Evidence stages, Isolation and deterministic authority, Question being measured, Small evaluation architecture, Stop conditions

### Community 161 - "supplement_cached_latest_report"
Cohesion: 0.24
Nodes (8): inline_report_facts(), Any, datetime, Path, Conservative local inline-XBRL fallback when companyfacts lags a report.  Only a, supplement_cached_latest_report(), verified_artifact(), InlineFallbackTests

### Community 163 - "AGENTS.md"
Cohesion: 0.20
Nodes (8): Completion evidence for pipeline changes, File Conventions, graphify, Non-Negotiable Constraints, Owner-Requested Reviews and Email, Purpose, Research Standards, Script Safety

### Community 164 - "FrozenRuntimeTests"
Cohesion: 0.21
Nodes (4): FrozenRuntimeTests, Reproducibility regressions: immutable capture, closure, atomic append, replay., Bind real fixture bytes, so isolated frozen execution sees the same inputs., write_fixture()

### Community 165 - "main"
Cohesion: 0.23
Nodes (7): main(), number(), Any, Solve required revenue for explicit terminal-multiple/return sensitivities., reverse_expectations(), whole_share_diagnostics(), ReassessmentReportingTests

### Community 239 - "Data Source Policy"
Cohesion: 0.33
Nodes (5): Data Source Policy, Preferred Sources, Prohibited Sources And Data, Secondary Sources, Weak Evidence

### Community 241 - "Source Policy"
Cohesion: 0.33
Nodes (5): Citation Expectations, Source Policy, Strong Sources, Useful Secondary Sources, Weak Sources

### Community 242 - "enable_llm_live_shadow.py"
Cohesion: 0.33
Nodes (5): Approval, Market Quality, Research Completeness, Risk Controls, Trading Checklist

### Community 258 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 296 - "check_llm_shadow_status.sh"
Cohesion: 0.40
Nodes (4): Allowed, Brokerage Boundary, Human Responsibility, Prohibited

### Community 297 - "install_llm_shadow_scheduler.sh"
Cohesion: 0.40
Nodes (4): Approval Boundary, Manual Approval Policy, Out Of Scope, Required Before Approval

### Community 362 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 363 - "ShadowOutputLock"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 364 - "anonymous_review_materials_status.md"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

## Knowledge Gaps
- **319 isolated node(s):** `activate_daily_after_verification.sh script`, `check_daily_scheduler_status.sh script`, `check_shadow_llm_evaluation_scheduler.sh script`, `clear_maintenance_inhibit.sh script`, `install_daily_schedulers.sh script` (+314 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **38 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `canonical_sha256()` connect `AST` to `market_data_adapter.py`, `send_c6_weekly_email.py`, `main`, `main`, `IncorporationTests`, `verify_daily_upgrade.py`, `PacketMarketObservationTests`, `verify_c6_weekly_email_boundary.py`, `sha256_file`, `llm_contract.py`, `research_working_agreement.md`, `PacketMarketObservationTests`, `compare_policies`, `evaluate_shadow_llm_incremental_value.py`, `applied_reconciliation_matches_current_state`, `ResearchRiskLimitsTests`, `verify_c2_email_delivery_boundary.py`, `_DocumentPeriod`, `HeldCorePositionTests`, `main`, `Early Public Equity Lab`, `Owner-requested research reviews`, `portfolio_construction.py`, `test_refresh_cadence.py`, `AcceptanceReconciliationError`, `report_heading`, `score_candidates.py`, `main`, `test_sender_publication.py`, `__init__.py`, `OwnerSnapshotTests`, `MaintainedThesisTests`, `delivery_meaning_key`, `test_thesis_evidence.py`, `Equity Research — Core Allocation Policy`?**
  _High betweenness centrality (0.105) - this node is a cross-community bridge._
- **Why does `ExclusiveFileLock` connect `score_b_candidates.py` to `market_data_adapter.py`, `RuntimePreflightAlertTests`, `OwnerSnapshotTests`, `report_heading`, `main`, `score_candidates.py`, `IncorporationTests`, `PacketMarketObservationTests`, `verify_c6_weekly_email_boundary.py`, `Early Public Equity Research`, `main`, `test_refresh_cadence.py`, `research_working_agreement.md`, `_DocumentPeriod`, `AcceptanceReconciliationError`, `Equity Research — Core Allocation Policy`, `risk_profile_activation_20260914.md`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `main()` connect `evaluate_shadow_llm_incremental_value.py` to `market_data_adapter.py`, `AST`, `score_candidates.py`, `ShadowProviderError`, `main`, `PacketMarketObservationTests`, `verify_daily_upgrade.py`, `execution_common.py`, `research_working_agreement.md`, `portfolio_construction.py`, `shadow_llm_contract.py`, `ShadowLlmTests`, `risk_profile_activation_20260914.md`, `score_candidates.py`, `Early Public Equity Research`, `test_sender_publication.py`, `SecAcceptanceReconciliationTests`, `OwnerSnapshotTests`, `delivery_meaning_key`?**
  _High betweenness centrality (0.023) - this node is a cross-community bridge._
- **Are the 108 inferred relationships involving `canonical_sha256()` (e.g. with `evaluate_archived()` and `build_packet()`) actually correct?**
  _`canonical_sha256()` has 108 INFERRED edges - model-reasoned connections that need verification._
- **Are the 70 inferred relationships involving `render_email()` (e.g. with `main()` and `publication_id()`) actually correct?**
  _`render_email()` has 70 INFERRED edges - model-reasoned connections that need verification._
- **Are the 44 inferred relationships involving `read_json()` (e.g. with `load_active_config()` and `main()`) actually correct?**
  _`read_json()` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 40 inferred relationships involving `ExclusiveFileLock` (e.g. with `refresh_capital_work_queue()` and `run_frozen()`) actually correct?**
  _`ExclusiveFileLock` has 40 INFERRED edges - model-reasoned connections that need verification._