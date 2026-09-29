# Graph Report - equity  (2026-09-28)

## Corpus Check
- 290 files · ~280,022 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3188 nodes · 8362 edges · 159 communities (120 shown, 39 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 1585 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8330c5e4`
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
- RequestedCoverageTests
- main
- RuntimePreflightAlertTests
- long_horizon_research_policy.md
- issuer_news_continuity.md
- build_current_research_baseline.py
- main
- graphify reference: query, path, explain
- Source Policy
- main
- main
- next_thursday
- Recurring analyst follow-through
- Pipeline audit and repair — September 28, 2026
- main
- MomentumReviewStatusTests
- MomentumStatusTests
- objective_research_budget_20260928.md
- workflow_health
- test_shadow_archive_isolation.py
- HeldCorePositionTests
- WorkQueueReportingTests
- OwnerSnapshotTests
- NamingCompatibilityTests
- Equity Research — SHADOW_LLM
- research_working_agreement.md
- Risk Policy
- AGENTS.md
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
1. `canonical_sha256()` - 107 edges
2. `render_email()` - 68 edges
3. `read_json()` - 51 edges
4. `main()` - 45 edges
5. `ExclusiveFileLock` - 45 edges
6. `iso_now()` - 40 edges
7. `build_email_view()` - 39 edges
8. `now_et()` - 38 edges
9. `main()` - 38 edges
10. `_execute_unlocked()` - 38 edges

## Surprising Connections (you probably didn't know these)
- `load_execution_rows()` --calls--> `csv_fields()`  [INFERRED]
  09_scripts/equity_research/execution_common.py → 09_scripts/equity_research/account_common.py
- `write_csv()` --calls--> `archive_before_replace()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/portfolio_archive.py
- `write_text()` --calls--> `archive_before_replace()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/portfolio_archive.py
- `main()` --calls--> `write_text()`  [INFERRED]
  09_scripts/equity_research/create_price_aware_action_plan.py → 09_scripts/equity_research/account_common.py
- `main()` --calls--> `write_text()`  [INFERRED]
  09_scripts/equity_research/regenerate_portfolio_outputs.py → 09_scripts/equity_research/account_common.py

## Import Cycles
- None detected.

## Communities (159 total, 39 thin omitted)

### Community 0 - "market_data_adapter.py"
Cohesion: 0.06
Nodes (44): append_plan(), apply_plan_context(), _bound_sources(), evaluate_plans(), _expired_at(), _finish_scopes(), load_plan_context(), _observed_orders() (+36 more)

### Community 1 - "run_full_universe_market_data.py"
Cohesion: 0.21
Nodes (27): _canonical_sha256(), _declared_tickers(), _is_within(), load_valuation_input_bundle(), main(), _packet_as_of(), _parse_utc(), Any (+19 more)

### Community 2 - "AST"
Cohesion: 0.13
Nodes (55): canonical_sha256(), _append_ledger_event(), _archive_packet(), _archived_packet_index(), _atomic_private_json(), _atomic_private_text(), _contract_failure_code(), critic_route() (+47 more)

### Community 3 - "send_c6_weekly_email.py"
Cohesion: 0.05
Nodes (81): _allowed_classifications_by_ticker(), _artifact_map(), build_packet(), _compact_fact_provenance(), _date_from_period(), _decimal(), _decision_tickers(), _effective_acceptance_map() (+73 more)

### Community 4 - "test_active_production.py"
Cohesion: 0.10
Nodes (50): acceptance_index_failure_reason(), approved_inline_tags(), classify_materiality(), company_fundamentals_required(), count_unindexed_acceptance_accessions(), current_submission_entity_name(), _debt_fact(), _derived_fact() (+42 more)

### Community 5 - "score_b_candidates.py"
Cohesion: 0.05
Nodes (59): ExclusiveFileLock, Process lock using flock over a private, non-linked regular file., _append_execution_record(), assert_non_icloud_runtime_root(), _best_effort_failure_record(), _best_effort_preflight_alert(), _deployment_receipt_path(), _eligible_connectivity_failure() (+51 more)

### Community 6 - "ShadowProviderError"
Cohesion: 0.10
Nodes (29): build_report(), _cache_read(), _cache_write(), _digest(), DiscoveryClient, DiscoveryError, _empty(), _http_get() (+21 more)

### Community 7 - "main"
Cohesion: 0.06
Nodes (46): main(), atomic_write_csv(), _accessions(), assess_company(), build_earnings_incorporation(), Any, datetime, Path (+38 more)

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
Cohesion: 0.09
Nodes (25): build_tactical_review(), _day(), _integer(), _last_sessions(), load_tactical_review(), _money(), _number(), _positive() (+17 more)

### Community 12 - "iso_now"
Cohesion: 0.13
Nodes (19): line_excerpt(), main(), number(), Any, Path, Fail closed before producing a range, not merely before order routing., Match the packet clock's whole-second point-in-time precision., selected_band() (+11 more)

### Community 13 - "verify_c6_weekly_email_boundary.py"
Cohesion: 0.12
Nodes (23): canonical_url(), clean_title(), fetch_feed(), load_manifest(), NewsError, OfficialRedirect, parse_feed(), _PlainText (+15 more)

### Community 14 - "score_candidates.py"
Cohesion: 0.13
Nodes (12): IndependentDiscoveryIntegrationTests, RiskPolicyDiagnosticTests, compare_policies(), _decimal(), Holding, _number(), Compare capacities independently, never sum candidate share counts.  These are u, Apply explicit per-ticker price shocks simultaneously, keeping cash fixed.  Ever (+4 more)

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
Cohesion: 0.08
Nodes (39): recent_filings(), acceptance_map(), AcceptanceIndexError, build_acceptance_index(), load_acceptance_index(), load_acceptance_reconciliation_log(), make_acceptance_record(), _make_reconciliation_row() (+31 more)

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
Cohesion: 0.10
Nodes (27): acceptance_map(), fetch(), main(), Path, _jsonl(), main(), _number(), Path (+19 more)

### Community 26 - "portfolio_construction.py"
Cohesion: 0.20
Nodes (32): _action_kind(), build_discovery_view(), build_email_view(), _comparison_weight(), _conflict_tasks(), _decimal(), email_subject(), _is_core() (+24 more)

### Community 27 - "next_thursday"
Cohesion: 0.11
Nodes (16): CanonicalWorkflowTests, OptionalActiveInputTests, registry_row(), _canonical_source_issues(), Check, collect_checks(), _deprecated_registry_issues(), _loaded() (+8 more)

### Community 28 - "verify_c2_email_delivery_boundary.py"
Cohesion: 0.15
Nodes (20): _aware(), _blockers(), build_capital_work_queue(), compact_summary(), _item_semantic(), _money(), _next_check(), _plan_needed() (+12 more)

### Community 29 - "HeldCorePositionTests"
Cohesion: 0.13
Nodes (18): classify_nonzero_exit(), cli_reported_token_usage(), CodexCliProvider, executable_sha256(), minimal_codex_environment(), Provider, ProviderResult, Any (+10 more)

### Community 30 - "shadow_llm_contract.py"
Cohesion: 0.13
Nodes (31): append_run_log(), as_float(), concentration_status(), dynamic_position_fit(), is_core_allocation_ticker(), load_account_state(), load_active_inhibit(), load_market_rows() (+23 more)

### Community 34 - "ShadowLlmTests"
Cohesion: 0.15
Nodes (20): datetime, Independent official-news checks using the existing serialized scheduler.  No se, run_due_news_checks(), due_slots(), main(), market_snapshot_mode(), _market_step_passed(), _massive_auth_presence_probe_exit_code() (+12 more)

### Community 35 - "workflow_health"
Cohesion: 0.18
Nodes (13): deployment_health(), jsonl_count(), main(), momentum_health(), momentum_review_health(), Any, datetime, Path (+5 more)

### Community 36 - "main"
Cohesion: 0.16
Nodes (10): MassiveB2AdapterResilienceTests, _payload(), The Basic delayed shape normalizes without leaking provider metadata., Ticker, adjustment, pagination, and malformed data each stop once., A provider 429 is one request and exposes neither URL detail nor key., Every new ticker is locally paced, while a failed request is never retried., Sanitized current Custom Bars shape, including optional metadata., The external-runtime key authorizes one request but never enters its URL/output. (+2 more)

### Community 37 - "Early Public Equity Lab"
Cohesion: 0.25
Nodes (8): Current Safe Status Commands, Current Workflow, Equity Research, Long-horizon workflow upgrade (2026-09-20), Repository Paths, Safety Boundaries, What The System Can Do, What The System Cannot Do

### Community 38 - "ledger_row"
Cohesion: 0.20
Nodes (6): CacheTests, ledger_row(), NormalizationTests, Path, SelectionAndValidationTests, write_ledger()

### Community 39 - "current_documents.md"
Cohesion: 0.20
Nodes (4): Equity Research 改动验收入口, Maintained company research, effective 2026-09-24, 长期研究、倍增情景与证据边界, 四项投资工作流标准：实施计划与验收

### Community 40 - "create_c5_weekly_conviction_memo.py"
Cohesion: 0.22
Nodes (15): main(), execution_cash(), intraday_range_pct(), load_execution_rows(), optional_float(), parse_iso(), select_execution(), slippage_review_pct() (+7 more)

### Community 41 - "score_candidates.py"
Cohesion: 0.12
Nodes (14): InlineFacts, parse_principal_facts(), project_relative_locator(), Any, datetime, HTMLParser, Path, ValueError (+6 more)

### Community 42 - "save_decision"
Cohesion: 0.21
Nodes (5): CompactReviewTests, delivery_fixture(), owner_review_fixture(), OwnerReviewDeliveryTests, save_decision()

### Community 43 - "Owner-requested research reviews"
Cohesion: 0.15
Nodes (38): append_review(), apply_issuer_news_review(), _day(), evaluate_thesis(), evidence_context(), _inside(), material_filing_receipt(), Any (+30 more)

### Community 46 - "ShadowLlmTests"
Cohesion: 0.08
Nodes (14): ActiveConfigError, load_active_config(), main(), Any, Path, ValueError, Raised when the active configuration is unsafe or incomplete., Validate an optional research overlay without accepting financial data. (+6 more)

### Community 47 - "test_refresh_cadence.py"
Cohesion: 0.06
Nodes (52): main(), number(), Any, Solve required revenue for explicit terminal-multiple/return sensitivities., reverse_expectations(), whole_share_diagnostics(), build_report(), main() (+44 more)

### Community 48 - "ShadowProviderError"
Cohesion: 0.14
Nodes (12): WorkQueueReportingTests, cash_lines(), _money(), Any, datetime, Path, Read and present recurring work without granting decision authority., A prior success file cannot conceal a failed or stale scheduled step. (+4 more)

### Community 49 - "ShadowMeasurementTests"
Cohesion: 0.17
Nodes (15): ValuationResearchArchiveTests, archive_bytes(), _archive_snapshot(), compose_research_inputs(), generated_record(), _owned_directory(), _publish_private(), Any (+7 more)

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
Nodes (30): main(), append_chained(), _attempt_summary(), comparison_markdown(), evaluate(), failure_reason(), next_open_session(), number() (+22 more)

### Community 56 - "MarketRegimeTests"
Cohesion: 0.12
Nodes (16): Action-email presentation (v2, 2026-09-05), Boundaries, Current delivery and presentation rule (2026-09-26), Display naming, Duplicate Protection, Eligibility, Equity Research — Daily Delivery Policy, Explicit correction resend (+8 more)

### Community 57 - "OfficialNewsScheduleTests"
Cohesion: 0.32
Nodes (5): chained(), MomentumExperimentReviewTests, observations(), outcome(), payloads()

### Community 58 - "load_inhibit"
Cohesion: 0.15
Nodes (12): Boundaries, Broker and order mechanics, Current email correction (2026-09-26), Delivery expectation, Durable follow-through for interactive reviews (2026-09-28), Email readability (2026-09-22 follow-up), Independent market discovery (2026-09-22 follow-up), Later-email continuity preference (2026-09-28) (+4 more)

### Community 59 - "四项标准：工作流升级实施与验收"
Cohesion: 0.14
Nodes (12): Applied scheduling interpretation, Bounded observation on the installed collector, Endpoint and primary sources, REST collector timing evidence — September 28, 2026, Data Handling, Equity Research — Configured-Universe Data and Broad Discovery Policy, Independent broad-market discovery extension (September 22, 2026), Permitted Source and Scope (+4 more)

### Community 60 - "main"
Cohesion: 0.29
Nodes (6): AcceptanceReconciliationError, load_immutable_acceptance_index(), Load the historical index only when the retained artifact exists.      The times, A current SEC record cannot be reconciled to the immutable index., acceptance_record(), SecAcceptanceReconciliationTests

### Community 61 - "create_long_horizon_research.py"
Cohesion: 0.25
Nodes (7): Active Workflow, Authority Order, Equity Research — Canonical Active-State Policy, Pipeline Requirement, Purpose, Safety Boundary, Stale-File Guard

### Community 63 - "risk_profile_activation_20260914.md"
Cohesion: 0.20
Nodes (17): active_delivery_window(), configured_delivery_windows(), delivery_window_by_id(), Any, datetime, Stable owner-attention windows; clocks never confer trading eligibility., Return explicit windows, retaining one-window legacy configuration reads., delivery_status_is_unknown() (+9 more)

### Community 64 - "workflow_standards_audit_20260920.md"
Cohesion: 0.25
Nodes (7): Canonical Inputs, Equity Research — Account-State Policy, Manual UI valuation bootstrap, Optional research-only risk limits, Privacy and Execution Boundary, Runtime State, Validation

### Community 65 - "score_candidates.py"
Cohesion: 0.29
Nodes (6): Admission requirements, Boundaries, Commit and recovery behavior, Equity Research — SEC Acceptance-Index Extension Policy v1, Immutable historical layer, Versioned artifacts and audit

### Community 66 - "ResearchRiskLimitsTests"
Cohesion: 0.18
Nodes (9): _official_follow_up(), Resolve only mechanically scoped facts with NEW later official provenance., build_automatic_evaluation(), deterministic_claim_check(), Conservative one-fact sign check, never a generic semantic truth judge.      Com, evaluation_bundle(), fact_packet(), net_loss_claim() (+1 more)

### Community 67 - "test_owner_snapshot.py"
Cohesion: 0.16
Nodes (7): Any, ResearchRiskLimitsTests, core_starter_decision(), individual_sizing_decision(), _passed_confidence(), Size one staged broad-market core review without using stock valuation., Return the highest supported sizing tier and a feasible share count.

### Community 68 - "Equity Research 命名迁移验收"
Cohesion: 0.08
Nodes (15): archive_before_replace(), _archive_location(), _private_directory(), Path, Keep exact private predecessors when portfolio files are replaced.  The active f, Fail closed if a changed predecessor cannot be safely preserved., Cover direct owner edits as well as the writers hooked above., Save a byte-exact current revision once, without changing the source. (+7 more)

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

### Community 74 - "score_candidates.py"
Cohesion: 0.12
Nodes (37): append_csv_durable(), bool_value(), cycle_date(), delivery_guard(), easter_sunday(), expected_market_session(), is_us_market_session_date(), last_completed_market_session() (+29 more)

### Community 75 - "_run_identity"
Cohesion: 0.17
Nodes (15): active_document(), audit(), first_heading(), main(), Path, tracked_markdown(), atomic_write(), main() (+7 more)

### Community 76 - "main"
Cohesion: 0.25
Nodes (3): evaluate_archived(), Evaluate retained observations with their exact archived implementation.  Only e, ArchivedMomentumTests

### Community 77 - "sec_acceptance_extensions.py"
Cohesion: 0.14
Nodes (40): admit_unindexed_current_records(), _audit_row(), build_extension_artifact(), _core_record(), extension_acceptance_records(), extension_artifact_path(), _extension_number(), extension_set_sha256() (+32 more)

### Community 78 - "Early Public Equity Research"
Cohesion: 0.06
Nodes (71): Any, date, HTTPRedirectHandler, RuntimeError, append_audit(), append_csv(), csv_header(), empty_market_row() (+63 more)

### Community 79 - "main"
Cohesion: 0.19
Nodes (17): _append(), _hash(), merge_news_context(), Any, datetime, Path, Private source-bound issuer-news continuity; collectors never infer a view.  The, Merge retained identities and current verified observations, idempotently. (+9 more)

### Community 81 - "Equity Research — current document entrypoints"
Cohesion: 0.20
Nodes (18): csv_fields(), load_positions(), Path, write_csv(), write_text(), append_c9b_log(), Path, sha256() (+10 more)

### Community 82 - "test_sender_publication.py"
Cohesion: 0.57
Nodes (3): actionable_fixture(), publication_fixture(), SenderPublicationTests

### Community 89 - "next_thursday"
Cohesion: 0.33
Nodes (6): Path, brand_name(), desktop_alert_script(), load_display_names(), Shared presentation names; no strategy, delivery or protocol authority., subject_prefix()

### Community 90 - "research_working_agreement.md"
Cohesion: 0.33
Nodes (5): Account Total, Canonical Update, Cash, Equity Research — Account Reconciliation Policy, Preconditions

### Community 91 - "main"
Cohesion: 0.33
Nodes (5): Allowed Exact Actions, Current Positions, Equity Research — Action Threshold Policy, Maximum Entry and Trim Conditions, New Individual-Stock Eligibility

### Community 92 - "__init__.py"
Cohesion: 0.30
Nodes (9): append_audit(), as_float(), clamp(), main(), Path, read_csv(), score_row(), timestamp() (+1 more)

### Community 95 - "Equity Research 命名与归档规则"
Cohesion: 0.50
Nodes (4): Authoritative policy and boundaries, Current runtime outputs — read their generated timestamps, Equity Research — current document entrypoints, Historical material — retained, not current instructions

### Community 96 - "OwnerSnapshotTests"
Cohesion: 0.18
Nodes (22): WorkflowPublicationTests, _account_blockers(), apply_workflow_integrity(), current_news_context(), current_thesis_views(), incorporation_meaning(), news_meaning(), Any (+14 more)

### Community 97 - "RuntimePreflightAlertTests"
Cohesion: 0.33
Nodes (12): add_check(), append_verification_log(), file_digest_or_absent(), loaded(), main(), plist_checks(), pure_guard_tests(), Path (+4 more)

### Community 99 - "workflow_health"
Cohesion: 0.08
Nodes (28): _archive(), build_followthrough(), continuation_lines(), continuation_requires_reconciliation(), _displayed_actions(), _identity(), _positive(), Any (+20 more)

### Community 100 - "earnings_incorporation.py"
Cohesion: 0.33
Nodes (5): Concentration and Sleeve Rules, Current-Weight Formula, Equity Research — Dynamic Weight Policy, Price Quality, Stored Percentage Boundary

### Community 101 - "MaintainedThesisTests"
Cohesion: 0.14
Nodes (7): fixture(), MaintainedThesisTests, material_fixture(), ValueError, The review cannot be used as a current maintained conclusion., seal_review(), ThesisValidationError

### Community 103 - "IncorporationTests"
Cohesion: 0.29
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
Cohesion: 0.31
Nodes (7): _bundle(), _input(), Path, _source(), ValuationInputBundleTests, _write_bundle(), _write_source()

### Community 113 - "OwnerSnapshotTests"
Cohesion: 0.40
Nodes (5): “5R”的来源与结论, Equity Research 命名与归档规则, 兼容边界, 文件与目录, 派生知识图谱显示名

### Community 114 - "cards"
Cohesion: 0.50
Nodes (3): Explicit purpose, Position purpose and reassessment, Required reassessment

### Community 115 - "Scoped blockers and recurring research work"
Cohesion: 0.33
Nodes (5): Blocker scope, Bounded objective research, Cash and recurring work, Expired plans and reporting, Scoped blockers and recurring research work

### Community 117 - "MarketCoverageRecompositionTests"
Cohesion: 0.50
Nodes (3): Cash-Deployment Decision, Equity Research — Core Allocation Policy, Separation

### Community 118 - ".inputs"
Cohesion: 0.22
Nodes (8): Equity Research — Daily Research Policy, Facts, Estimates, and Opinions, Long-Term Interpretation, Principle, Refresh and Freshness Rules, Request Discipline, Source coverage and research completeness, Source Hierarchy

### Community 120 - "main"
Cohesion: 0.47
Nodes (3): compare(), CrossDayDeliveryTests, receipt()

### Community 124 - "build_current_research_baseline.py"
Cohesion: 0.24
Nodes (14): dynamic_candidate_fit(), clamp(), main(), number(), price_unverified_research_row(), Keep owner-requested research visible without granting trade eligibility., requested_coverage_tickers(), requested_only_price_unverified() (+6 more)

### Community 126 - "graphify reference: query, path, explain"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 127 - "Source Policy"
Cohesion: 0.25
Nodes (8): Calls and cost, Equity Research — SHADOW_LLM Evaluation Policy, Event-driven selection and replay, Evidence stages, Isolation and deterministic authority, Question being measured, Small evaluation architecture, Stop conditions

### Community 128 - "main"
Cohesion: 0.40
Nodes (5): Boundaries, Decision, Equity Research — AI operating decision, Future evaluation boundary, Historical decision evidence — August 31 only

### Community 131 - "Recurring analyst follow-through"
Cohesion: 0.25
Nodes (7): Authority, Durable completion receipt, Each run, Full no-send refresh after admission, Locking and publication, Recurring analyst follow-through, Writer paths and admission modes

### Community 132 - "Pipeline audit and repair — September 28, 2026"
Cohesion: 0.40
Nodes (4): Close the analytical follow-through gap, Pipeline audit and repair — September 28, 2026, Preserve the forward experiment across a software repair, Repaired contracts

### Community 133 - "main"
Cohesion: 0.22
Nodes (9): archive_validated_delivery(), _matches(), Path, Retain exact validated message inputs before a durable delivery claim.  Only dec, Remove only known dead-process temporary links to these exact bytes.      Unknow, Atomically publish immutable content-addressed files; fail before send.      Par, _recover_crashed_publish_links(), DeliveryArchiveTests (+1 more)

### Community 137 - "workflow_health"
Cohesion: 0.47
Nodes (3): Keep operational completion, maintained views, and price readiness separate., workflow_health(), CurrentWorkflowStatusTests

### Community 140 - "WorkQueueReportingTests"
Cohesion: 0.20
Nodes (3): DeliveryWindowTests, receipt(), stamp()

### Community 143 - "Equity Research — SHADOW_LLM"
Cohesion: 0.50
Nodes (4): Automatic event modes, Equity Research — SHADOW_LLM, Evaluation, Safe preflight

### Community 147 - "Risk Policy"
Cohesion: 0.25
Nodes (7): Account Scope, Hard Rules, Portfolio Risk, Position Risk, Review Cadence, Risk Limits, Risk Policy

### Community 163 - "AGENTS.md"
Cohesion: 0.20
Nodes (8): Completion evidence for pipeline changes, File Conventions, graphify, Non-Negotiable Constraints, Owner-Requested Reviews and Email, Purpose, Research Standards, Script Safety

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
- **245 isolated node(s):** `activate_daily_after_verification.sh script`, `check_daily_scheduler_status.sh script`, `check_shadow_llm_evaluation_scheduler.sh script`, `clear_maintenance_inhibit.sh script`, `install_daily_schedulers.sh script` (+240 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **39 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `canonical_sha256()` connect `AST` to `market_data_adapter.py`, `send_c6_weekly_email.py`, `test_active_production.py`, `main`, `main`, `PacketMarketObservationTests`, `verify_c6_weekly_email_boundary.py`, `llm_contract.py`, `PacketMarketObservationTests`, `compare_policies`, `evaluate_shadow_llm_incremental_value.py`, `applied_reconciliation_matches_current_state`, `verify_c2_email_delivery_boundary.py`, `HeldCorePositionTests`, `Owner-requested research reviews`, `portfolio_construction.py`, `test_refresh_cadence.py`, `AcceptanceReconciliationError`, `report_heading`, `score_candidates.py`, `main`, `sec_acceptance_extensions.py`, `main`, `OwnerSnapshotTests`, `workflow_health`, `MaintainedThesisTests`, `delivery_meaning_key`, `test_thesis_evidence.py`?**
  _High betweenness centrality (0.117) - this node is a cross-community bridge._
- **Why does `ExclusiveFileLock` connect `score_b_candidates.py` to `market_data_adapter.py`, `RuntimePreflightAlertTests`, `OwnerSnapshotTests`, `test_active_production.py`, `main`, `report_heading`, `main`, `score_candidates.py`, `PacketMarketObservationTests`, `verify_c6_weekly_email_boundary.py`, `Early Public Equity Research`, `main`, `test_refresh_cadence.py`, `AcceptanceReconciliationError`, `ResearchRiskLimitsTests`, `risk_profile_activation_20260914.md`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `main()` connect `evaluate_shadow_llm_incremental_value.py` to `market_data_adapter.py`, `OwnerSnapshotTests`, `AST`, `workflow_health`, `ShadowProviderError`, `main`, `score_candidates.py`, `PacketMarketObservationTests`, `delivery_meaning_key`, `verify_daily_upgrade.py`, `ShadowLlmTests`, `ShadowProviderError`, `execution_common.py`, `Equity Research — current document entrypoints`, `ResearchRiskLimitsTests`, `portfolio_construction.py`, `shadow_llm_contract.py`?**
  _High betweenness centrality (0.025) - this node is a cross-community bridge._
- **Are the 103 inferred relationships involving `canonical_sha256()` (e.g. with `evaluate_archived()` and `build_packet()`) actually correct?**
  _`canonical_sha256()` has 103 INFERRED edges - model-reasoned connections that need verification._
- **Are the 59 inferred relationships involving `render_email()` (e.g. with `main()` and `brand_name()`) actually correct?**
  _`render_email()` has 59 INFERRED edges - model-reasoned connections that need verification._
- **Are the 44 inferred relationships involving `read_json()` (e.g. with `load_active_config()` and `main()`) actually correct?**
  _`read_json()` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `main()` (e.g. with `is_core_allocation_ticker()` and `load_active_config()`) actually correct?**
  _`main()` has 30 INFERRED edges - model-reasoned connections that need verification._