# Graph Report - equity  (2026-09-28)

## Corpus Check
- 287 files · ~279,234 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 3174 nodes · 8337 edges · 156 communities (122 shown, 34 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 0% AMBIGUOUS · INFERRED: 1581 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `05bda5bf`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- activate_daily_after_verification.sh
- check_daily_scheduler_status.sh
- check_shadow_llm_evaluation_scheduler.sh
- clear_maintenance_inhibit.sh
- install_daily_schedulers.sh
- install_shadow_llm_evaluation_scheduler.sh
- run_shadow_llm_event.sh
- set_maintenance_inhibit.sh
- uninstall_daily_schedulers.sh
- shadow_llm_contract.py
- Equity Research — current document entrypoints
- Equity Research 命名迁移验收
- main
- ShadowLlmTests
- ShadowMeasurementTests
- OwnerSnapshotTests
- build_current_research_baseline.py
- send_c6_weekly_email.py
- sec_acceptance_extensions.py
- main
- NamingCompatibilityTests
- score_candidates.py
- evaluate_shadow_llm_incremental_value.py
- main
- ResearchRiskLimitsTests
- AcceptanceReconciliationError
- report_heading
- create_c5_weekly_conviction_memo.py
- test_refresh_cadence.py
- AST
- economic_packet
- score_b_candidates.py
- main
- delivery_meaning_key
- workflow_health
- risk_profile_activation_20260914.md
- portfolio_construction.py
- execution_common.py
- next_thursday
- Early Public Equity Research
- applied_reconciliation_matches_current_state
- ResearchRiskLimitsTests
- main
- Phase 0C Reframe Plan
- workflow_health
- market_data_adapter.py
- main
- ShadowProviderError
- ShadowMeasurementTests
- ShadowLlmTests
- verify_c6_weekly_email_boundary.py
- test_active_production.py
- verify_c5t_manual_action_boundary.py
- test_owner_snapshot.py
- iso_now
- _run_identity
- score_candidates.py
- __init__.py
- PacketMarketObservationTests
- score_candidates.py
- PacketMarketObservationTests
- llm_contract.py
- compare_policies
- HeldCorePositionTests
- verify_daily_upgrade.py
- next_thursday
- ShadowProviderError
- next_thursday
- save_decision
- main
- CandidateStabilityTests
- WorkQueueReportingTests
- main
- ResearchRiskLimitsTests
- GraphDisplayNamesTests
- HeldCorePositionTests
- MaintainedThesisTests
- main
- ShadowLlmTests
- create_long_horizon_research.py
- OfficialNewsScheduleTests
- Scoring
- test_shadow_archive_isolation.py
- OwnerSnapshotTests
- supplement_cached_latest_report
- main
- account_common.py
- ledger_row
- recommendation_notification_fingerprint
- RuntimePreflightAlertTests
- write_extension_admission_audit
- main
- test_sender_publication.py
- portfolio_construction.py
- Owner-requested research reviews
- main
- ShadowMeasurementTests
- SecAcceptanceReconciliationTests
- main
- verify_c2_email_delivery_boundary.py
- test_thesis_evidence.py
- OwnerSnapshotTests
- run_full_universe_market_data.py
- RuntimePreflightAlertTests
- valuation_input_bundle.py
- graphify reference: add a URL and watch a folder
- graphify reference: query, path, explain
- extraction-spec.md
- CodexCliProvider
- ShadowOutputLock
- graphify reference: query, path, explain
- iso_now
- anonymous_review_materials_status.md
- research_working_agreement.md
- workflow_standards_audit_20260920.md
- main
- create_long_horizon_research.py
- current_documents.md
- main
- Recurring analyst follow-through
- 四项标准：工作流升级实施与验收
- MarketCoverageRecompositionTests
- Equity Research 命名与归档规则
- Equity Research — Daily Decision Policy
- MarketRegimeTests
- .inputs
- earnings_incorporation.py
- OwnerSnapshotTests
- ResearchRiskLimitsTests
- issuer_news_continuity.md
- long_horizon_research_policy.md
- build_current_research_baseline.py
- Maintained investment research workflow
- IncorporationTests
- objective_research_budget_20260928.md
- load_inhibit
- Pipeline audit and repair — September 28, 2026
- cards
- RecommendationNotificationTests
- research_working_agreement.md
- _DocumentPeriod
- RequestedCoverageTests
- score_candidates.py
- Source Policy
- Workflow reliability and performance evidence
- Scoped blockers and recurring research work
- check_llm_shadow_status.sh
- Data Source Policy
- install_llm_shadow_scheduler.sh
- Risk Policy
- Source Policy
- enable_llm_live_shadow.py
- RequestedCoverageTests
- AGENTS.md
- Early Public Equity Lab

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
- `csv_fields()` --calls--> `load_execution_rows()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/execution_common.py
- `write_text()` --calls--> `archive_before_replace()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/portfolio_archive.py
- `write_text()` --calls--> `main()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/create_price_aware_action_plan.py
- `write_text()` --calls--> `main()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/regenerate_portfolio_outputs.py
- `load_account_state()` --calls--> `execution_conflicts()`  [INFERRED]
  09_scripts/equity_research/account_common.py → 09_scripts/equity_research/create_daily_decision_and_brief.py

## Import Cycles
- None detected.

## Communities (156 total, 34 thin omitted)

### Community 30 - "shadow_llm_contract.py"
Cohesion: 0.11
Nodes (34): timestamp(), read_csv(), as_float(), load_account_state(), load_research_account_state(), load_portfolio_summary(), load_market_rows(), load_packets() (+26 more)

### Community 81 - "Equity Research — current document entrypoints"
Cohesion: 0.28
Nodes (14): Path, csv_fields(), write_text(), load_positions(), sha256(), parse_args(), Namespace, select_default() (+6 more)

### Community 68 - "Equity Research 命名迁移验收"
Cohesion: 0.15
Nodes (13): write_csv(), _private_directory(), Path, _archive_location(), _verify_published_archive(), snapshot_current(), archive_before_replace(), snapshot_active_portfolio() (+5 more)

### Community 129 - "main"
Cohesion: 0.09
Nodes (10): main(), Evaluate retained observations with their exact archived implementation.  Only e, main(), _record_work_step(), Any, run_step(), safe_check(), main() (+2 more)

### Community 46 - "ShadowLlmTests"
Cohesion: 0.09
Nodes (12): ActiveConfigError, ValueError, validate_research_risk_limits(), Any, load_active_config(), Path, Raised when the active configuration is unsafe or incomplete., Validate an optional research overlay without accepting financial data. (+4 more)

### Community 15 - "ShadowMeasurementTests"
Cohesion: 0.08
Nodes (23): evaluate_archived(), number(), Any, timestamp(), datetime, provenance(), source_facts(), fundamentals_candidate_queue() (+15 more)

### Community 116 - "OwnerSnapshotTests"
Cohesion: 0.60
Nodes (4): fetch(), Path, acceptance_map(), main()

### Community 124 - "build_current_research_baseline.py"
Cohesion: 0.27
Nodes (13): number(), valid_completed_close(), requested_only_price_unverified(), price_unverified_research_row(), clamp(), requested_coverage_tickers(), selected_tickers(), main() (+5 more)

### Community 3 - "send_c6_weekly_email.py"
Cohesion: 0.05
Nodes (79): _sanitize_local_text(), Any, _decimal(), _round(), _safe_time(), datetime, _utc_text(), _date_from_period() (+71 more)

### Community 77 - "sec_acceptance_extensions.py"
Cohesion: 0.12
Nodes (44): _effective_acceptance_map(), Return the immutable index plus every validated append-only extension., _validate_runtime_evidence_chain(), Validate extension hashes, chain continuity, and audit bindings., ExtensionValidationError, raw_file_sha256(), Path, extension_artifact_path() (+36 more)

### Community 9 - "main"
Cohesion: 0.06
Nodes (38): _aware(), Any, datetime, _money(), Decimal, _usd(), _next_check(), _blockers() (+30 more)

### Community 142 - "NamingCompatibilityTests"
Cohesion: 0.29
Nodes (8): _number(), _jsonl(), Path, main(), missing_label(), display(), render_report(), main()

### Community 74 - "score_candidates.py"
Cohesion: 0.14
Nodes (23): main(), datetime, nth_weekday(), date, last_weekday(), observed(), easter_sunday(), us_market_holidays() (+15 more)

### Community 23 - "evaluate_shadow_llm_incremental_value.py"
Cohesion: 0.12
Nodes (33): is_action_transition(), latest_applied_execution(), recent_applied_execution(), datetime, load_market_gate(), Any, execution_conflicts(), material_events_for_cycle() (+25 more)

### Community 7 - "main"
Cohesion: 0.06
Nodes (46): main(), atomic_write_csv(), SecPayload, dict, retain_sec_response(), Path, Any, write_selection_receipt() (+38 more)

### Community 25 - "ResearchRiskLimitsTests"
Cohesion: 0.15
Nodes (30): main(), render(), build_report(), main(), now_et(), iso_now(), cycle_date(), read_json() (+22 more)

### Community 55 - "AcceptanceReconciliationError"
Cohesion: 0.14
Nodes (30): main(), number(), sessions_after(), date, regular_open(), datetime, next_open_session(), failure_reason() (+22 more)

### Community 72 - "report_heading"
Cohesion: 0.23
Nodes (14): main(), ReviewError, ValueError, validate_review_policy(), _validate_matured_outcome(), _cohort(), build_review(), markdown() (+6 more)

### Community 40 - "create_c5_weekly_conviction_memo.py"
Cohesion: 0.20
Nodes (17): main(), Path, optional_float(), parse_iso(), write_private_execution_rows(), load_execution_rows(), validate_execution_row(), select_execution() (+9 more)

### Community 47 - "test_refresh_cadence.py"
Cohesion: 0.07
Nodes (34): number(), Any, reverse_expectations(), whole_share_diagnostics(), main(), Solve required revenue for explicit terminal-multiple/return sensitivities., _passed_confidence(), individual_sizing_decision() (+26 more)

### Community 2 - "AST"
Cohesion: 0.13
Nodes (53): canonical_sha256(), ShadowRunError, RuntimeError, _contract_failure_code(), _read_json(), Path, Any, load_config() (+45 more)

### Community 44 - "economic_packet"
Cohesion: 0.22
Nodes (5): recommendation_notification_fingerprint(), notification_change_comparison(), Hash recommendation meaning, excluding quotes, dates and raw filings., NamingCompatibilityTests, Display migration must preserve research meaning and delivery identity.

### Community 5 - "score_b_candidates.py"
Cohesion: 0.05
Nodes (57): ExclusiveFileLock, Process lock using flock over a private, non-linked regular file., RuntimeSyncError, RuntimeError, RepositoryState, SyncResult, _safe_detail(), _run_git_process() (+49 more)

### Community 133 - "main"
Cohesion: 0.21
Nodes (9): _recover_crashed_publish_links(), Path, stat_result, _matches(), archive_validated_delivery(), Retain exact validated message inputs before a durable delivery claim.  Only dec, Remove only known dead-process temporary links to these exact bytes.      Unknow, Atomically publish immutable content-addressed files; fail before send.      Par (+1 more)

### Community 107 - "delivery_meaning_key"
Cohesion: 0.18
Nodes (15): delivery_meaning_key(), Any, latest_delivery_receipt(), datetime, receipt_meaning_key(), Path, delivery_notification_comparison(), covered_by_last_delivery() (+7 more)

### Community 99 - "workflow_health"
Cohesion: 0.08
Nodes (28): _stamp(), Any, datetime, _positive(), Decimal, _same_day_receipts(), Path, _identity() (+20 more)

### Community 63 - "risk_profile_activation_20260914.md"
Cohesion: 0.18
Nodes (17): configured_delivery_windows(), Any, active_delivery_window(), datetime, delivery_window_by_id(), Stable owner-attention windows; clocks never confer trading eligibility., Return explicit windows, retaining one-window legacy configuration reads., delivery_status_is_unknown() (+9 more)

### Community 26 - "portfolio_construction.py"
Cohesion: 0.20
Nodes (32): _decimal(), Any, number(), money(), percent(), shares(), _comparison_weight(), _time() (+24 more)

### Community 17 - "execution_common.py"
Cohesion: 0.13
Nodes (6): render_email(), decision_fixture(), action_fixture(), EmailPresentationTests, EmailArtifactBindingTests, PlanningEmailTests

### Community 89 - "next_thursday"
Cohesion: 0.33
Nodes (6): load_display_names(), Path, brand_name(), subject_prefix(), desktop_alert_script(), Shared presentation names; no strategy, delivery or protocol authority.

### Community 78 - "Early Public Equity Research"
Cohesion: 0.06
Nodes (72): report_heading(), MassiveB2Error, RuntimeError, _NoRedirectHandler, HTTPRedirectHandler, Any, api_key_from_environment(), _http_failure_code() (+64 more)

### Community 24 - "applied_reconciliation_matches_current_state"
Cohesion: 0.20
Nodes (30): ShadowEvaluationError, ValueError, _read_regular_json(), Path, Any, _ratio(), _valid_usage(), _validate_boundaries() (+22 more)

### Community 66 - "ResearchRiskLimitsTests"
Cohesion: 0.15
Nodes (13): _official_follow_up(), Resolve only mechanically scoped facts with NEW later official provenance., _finite_number(), Decimal, build_deterministic_baseline(), deterministic_claim_check(), build_automatic_evaluation(), Give the judge the facts/calculations already available without an LLM.      The (+5 more)

### Community 19 - "main"
Cohesion: 0.17
Nodes (24): EvidenceFreshnessError, ValueError, _payload_digest(), Any, _normalize_ticker(), _parse_utc(), datetime, _optional_utc() (+16 more)

### Community 54 - "Phase 0C Reframe Plan"
Cohesion: 0.26
Nodes (6): applied_reconciliation_current_state_status(), applied_reconciliation_matches_current_state(), Classify whether a current C9 state remains consistent with one fill.      C9B r, Return the closed accepted subset of reconciliation-state statuses., _reconciliation(), C9BAccountSnapshotRefreshTests

### Community 35 - "workflow_health"
Cohesion: 0.08
Nodes (15): shadow_evaluation_health(), Any, datetime, momentum_review_health(), momentum_health(), workflow_health(), deployment_health(), Report independent SHADOW health without altering canonical eligibility. (+7 more)

### Community 0 - "market_data_adapter.py"
Cohesion: 0.06
Nodes (44): stamp(), Any, datetime, regular_close(), _whole(), _required_text(), _bound_sources(), _validate_purpose() (+36 more)

### Community 79 - "main"
Cohesion: 0.19
Nodes (17): _time(), datetime, _hash(), Any, read_queue(), Path, _append(), _verified_current() (+9 more)

### Community 6 - "ShadowProviderError"
Cohesion: 0.10
Nodes (29): DiscoveryError, RuntimeError, NoRedirect, HTTPRedirectHandler, _http_get(), Any, _number(), _digest() (+21 more)

### Community 50 - "ShadowMeasurementTests"
Cohesion: 0.21
Nodes (5): number(), Any, build_regime(), Use a single complete public close; repeated intraday runs add no votes., MarketRegimeTests

### Community 34 - "ShadowLlmTests"
Cohesion: 0.12
Nodes (22): run_due_news_checks(), datetime, Independent official-news checks using the existing serialized scheduler.  No se, due_slots(), datetime, market_snapshot_mode(), _refresh_state_matches_attempt(), _market_step_passed() (+14 more)

### Community 13 - "verify_c6_weekly_email_boundary.py"
Cohesion: 0.12
Nodes (23): NewsError, ValueError, utc_now(), datetime, timestamp(), canonical_url(), load_manifest(), Path (+15 more)

### Community 4 - "test_active_production.py"
Cohesion: 0.09
Nodes (51): approved_inline_tags(), request_json(), Any, researched_tickers(), company_fundamentals_required(), load_ticker_map(), recent_filings(), date (+43 more)

### Community 18 - "verify_c5t_manual_action_boundary.py"
Cohesion: 0.11
Nodes (43): ArtifactError, ValueError, FetchResult, _VisibleTextParser, HTMLParser, utc_now(), sha256_bytes(), sha256_text() (+35 more)

### Community 67 - "test_owner_snapshot.py"
Cohesion: 0.25
Nodes (11): number(), utc_text(), utc_now_text(), line_excerpt(), Path, source(), Any, valuation_input() (+3 more)

### Community 12 - "iso_now"
Cohesion: 0.20
Nodes (8): valuation_input_issues(), Fail closed before producing a range, not merely before order routing., duration(), instant(), facts(), fixture(), row(), FinancialPeriodIntegrityTests

### Community 75 - "_run_identity"
Cohesion: 0.39
Nodes (7): plan_repair(), render_report(), render_existing_html(), atomic_write(), main(), Return repaired copies plus source-bound changes; never alter input objects., Use installed Graphify report APIs without altering graph topology.

### Community 14 - "score_candidates.py"
Cohesion: 0.09
Nodes (13): _decimal(), _number(), _ticker(), Holding, Snapshot, RiskPolicy, compare_policies(), simultaneous_stress() (+5 more)

### Community 92 - "__init__.py"
Cohesion: 0.40
Nodes (9): timestamp(), read_csv(), Path, write_csv(), append_audit(), as_float(), clamp(), score_row() (+1 more)

### Community 21 - "PacketMarketObservationTests"
Cohesion: 0.10
Nodes (38): AcceptanceIndexError, ValueError, AcceptanceReconciliationError, normalize_acceptance_timestamp(), Any, _normalize_generated_at(), make_acceptance_record(), validate_acceptance_record() (+30 more)

### Community 41 - "score_candidates.py"
Cohesion: 0.12
Nodes (14): SupplementalFactError, ValueError, project_relative_locator(), Path, InlineFacts, HTMLParser, parse_principal_facts(), Any (+6 more)

### Community 10 - "PacketMarketObservationTests"
Cohesion: 0.16
Nodes (28): ConfigError, ValueError, safe_header(), Any, safe_email(), load_config(), cycle_is_blocked(), _current_cycle_receipts() (+20 more)

### Community 16 - "llm_contract.py"
Cohesion: 0.17
Nodes (30): ShadowContractError, ValueError, _object(), Any, _text(), _identifier(), _text_list(), _identifier_list() (+22 more)

### Community 22 - "compare_policies"
Cohesion: 0.16
Nodes (8): build_blind_judge_target(), Create a deterministic candidate set without origin or model labels., fake_packet(), valid_analyst(), valid_critic(), valid_judge(), FailingProvider, ShadowLlmTests

### Community 29 - "HeldCorePositionTests"
Cohesion: 0.13
Nodes (18): classify_nonzero_exit(), ShadowProviderError, RuntimeError, ProviderResult, Any, cli_reported_token_usage(), FixtureProvider, executable_sha256() (+10 more)

### Community 11 - "verify_daily_upgrade.py"
Cohesion: 0.09
Nodes (25): _number(), Any, Decimal, _positive(), _integer(), _day(), date, _stamp() (+17 more)

### Community 48 - "ShadowProviderError"
Cohesion: 0.15
Nodes (3): write_csv(), Path, PacketMarketObservationTests

### Community 27 - "next_thursday"
Cohesion: 0.11
Nodes (16): CanonicalWorkflowTests, registry_row(), OptionalActiveInputTests, Check, _read_json(), Path, Any, _read_csv() (+8 more)

### Community 42 - "save_decision"
Cohesion: 0.19
Nodes (5): CompactReviewTests, owner_review_fixture(), delivery_fixture(), save_decision(), OwnerReviewDeliveryTests

### Community 120 - "main"
Cohesion: 0.44
Nodes (3): receipt(), compare(), CrossDayDeliveryTests

### Community 140 - "WorkQueueReportingTests"
Cohesion: 0.20
Nodes (3): stamp(), receipt(), DeliveryWindowTests

### Community 53 - "main"
Cohesion: 0.19
Nodes (3): decision_fixture(), discovery_fixture(), DiscoveryReportingTests

### Community 101 - "MaintainedThesisTests"
Cohesion: 0.15
Nodes (7): fixture(), material_fixture(), MaintainedThesisTests, ThesisValidationError, ValueError, seal_review(), The review cannot be used as a current maintained conclusion.

### Community 8 - "ShadowLlmTests"
Cohesion: 0.11
Nodes (21): _seed(), _market_row(), _quality_row(), _candidate_row(), _valid_bars(), datetime, _PartialApprovedTickerClient, date (+13 more)

### Community 57 - "OfficialNewsScheduleTests"
Cohesion: 0.32
Nodes (5): observations(), outcome(), chained(), payloads(), MomentumExperimentReviewTests

### Community 36 - "main"
Cohesion: 0.16
Nodes (10): _timestamp(), _payload(), _real_shaped_payload(), MassiveB2AdapterResilienceTests, Sanitized current Custom Bars shape, including optional metadata., The external-runtime key authorizes one request but never enters its URL/output., The Basic delayed shape normalizes without leaking provider metadata., Ticker, adjustment, pagination, and malformed data each stop once. (+2 more)

### Community 20 - "account_common.py"
Cohesion: 0.10
Nodes (9): _seed(), _market_row(), B2RefreshCadenceTests, Path, ExitStack, A failed child reserves its slot and waits for the next retry slot., The existing launchd job can refresh SEC evidence without B2 or email., The repair marker reuses local market data and cannot send email. (+1 more)

### Community 38 - "ledger_row"
Cohesion: 0.20
Nodes (6): ledger_row(), write_ledger(), Path, NormalizationTests, SelectionAndValidationTests, CacheTests

### Community 73 - "write_extension_admission_audit"
Cohesion: 0.27
Nodes (4): SecAcceptanceRefreshFailureTests, Regression coverage for the SEC acceptance precommit boundary., Run an offline refresh that must fail before any evidence commit., A rejected User-Agent must close before any SEC or evidence mutation.

### Community 82 - "test_sender_publication.py"
Cohesion: 0.54
Nodes (3): actionable_fixture(), publication_fixture(), SenderPublicationTests

### Community 43 - "Owner-requested research reviews"
Cohesion: 0.12
Nodes (40): _require(), _text(), Any, _timestamp(), datetime, _day(), date, _inside() (+32 more)

### Community 112 - "main"
Cohesion: 0.35
Nodes (7): _write_source(), Path, _source(), _input(), _bundle(), _write_bundle(), ValuationInputBundleTests

### Community 49 - "ShadowMeasurementTests"
Cohesion: 0.17
Nodes (16): ValuationResearchArchiveTests, generated_record(), Any, _owned_directory(), Path, _read_snapshot(), _publish_private(), _archive_snapshot() (+8 more)

### Community 76 - "main"
Cohesion: 0.24
Nodes (6): base(), nav(), review(), flow(), WorkflowEvaluationTests, performance_summary()

### Community 28 - "verify_c2_email_delivery_boundary.py"
Cohesion: 0.23
Nodes (16): aware(), Any, datetime, finite(), read_jsonl(), Path, append_record(), record_refresh() (+8 more)

### Community 96 - "OwnerSnapshotTests"
Cohesion: 0.18
Nodes (22): WorkflowPublicationTests, incorporation_meaning(), Any, thesis_meaning(), workflow_meaning(), _account_blockers(), _ticker_strategy(), _recompose_capital_projection() (+14 more)

### Community 1 - "run_full_universe_market_data.py"
Cohesion: 0.22
Nodes (26): ValuationInputBundleError, ValueError, _canonical_sha256(), Any, _reject_duplicate_pairs(), _read_json(), Path, _require_exact_fields() (+18 more)

### Community 97 - "RuntimePreflightAlertTests"
Cohesion: 0.33
Nodes (12): file_digest_or_absent(), Path, smtp_stat_only(), smtp_owner_private(), loaded(), add_check(), plist_checks(), source_checks() (+4 more)

### Community 51 - "valuation_input_bundle.py"
Cohesion: 0.08
Nodes (24): /graphify, Usage, What graphify is for, What You Must Do When Invoked, Step 0 - GitHub repos and multi-path merge (only if a URL or several paths), Step 1 - Ensure graphify is installed, Step 2 - Detect files, Step 2.5 - Video and audio (only if video files detected) (+16 more)

### Community 362 - "graphify reference: add a URL and watch a folder"
Cohesion: 0.50
Nodes (3): graphify reference: add a URL and watch a folder, For /graphify add, For --watch

### Community 126 - "graphify reference: query, path, explain"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 363 - "ShadowOutputLock"
Cohesion: 0.50
Nodes (3): graphify reference: commit hook and native CLAUDE.md integration, For git commit hook, For native CLAUDE.md integration

### Community 258 - "graphify reference: query, path, explain"
Cohesion: 0.33
Nodes (5): graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal, For /graphify path, For /graphify explain

### Community 364 - "anonymous_review_materials_status.md"
Cohesion: 0.50
Nodes (3): graphify reference: incremental update and cluster-only, For --update (incremental re-extraction), For --cluster-only

### Community 90 - "research_working_agreement.md"
Cohesion: 0.33
Nodes (5): Equity Research — Account Reconciliation Policy, Preconditions, Cash, Account Total, Canonical Update

### Community 64 - "workflow_standards_audit_20260920.md"
Cohesion: 0.25
Nodes (7): Equity Research — Account-State Policy, Canonical Inputs, Runtime State, Validation, Optional research-only risk limits, Manual UI valuation bootstrap, Privacy and Execution Boundary

### Community 91 - "main"
Cohesion: 0.33
Nodes (5): Equity Research — Action Threshold Policy, Current Positions, Allowed Exact Actions, Maximum Entry and Trim Conditions, New Individual-Stock Eligibility

### Community 61 - "create_long_horizon_research.py"
Cohesion: 0.25
Nodes (7): Equity Research — Canonical Active-State Policy, Purpose, Authority Order, Active Workflow, Stale-File Guard, Pipeline Requirement, Safety Boundary

### Community 39 - "current_documents.md"
Cohesion: 0.22
Nodes (5): 四项投资工作流标准：实施计划与验收, Equity Research — SHADOW_LLM, Safe preflight, Automatic event modes, Evaluation

### Community 128 - "main"
Cohesion: 0.40
Nodes (5): Equity Research — AI operating decision, Decision, Historical decision evidence — August 31 only, Future evaluation boundary, Boundaries

### Community 131 - "Recurring analyst follow-through"
Cohesion: 0.25
Nodes (7): Recurring analyst follow-through, Each run, Writer paths and admission modes, Locking and publication, Full no-send refresh after admission, Durable completion receipt, Authority

### Community 59 - "四项标准：工作流升级实施与验收"
Cohesion: 0.14
Nodes (12): REST collector timing evidence — September 28, 2026, Endpoint and primary sources, Bounded observation on the installed collector, Applied scheduling interpretation, Equity Research — Configured-Universe Data and Broad Discovery Policy, Purpose, Permitted Source and Scope, Data Handling (+4 more)

### Community 117 - "MarketCoverageRecompositionTests"
Cohesion: 0.50
Nodes (3): Equity Research — Core Allocation Policy, Separation, Cash-Deployment Decision

### Community 95 - "Equity Research 命名与归档规则"
Cohesion: 0.50
Nodes (4): Equity Research — current document entrypoints, Authoritative policy and boundaries, Current runtime outputs — read their generated timestamps, Historical material — retained, not current instructions

### Community 69 - "Equity Research — Daily Decision Policy"
Cohesion: 0.33
Nodes (5): Equity Research — Daily Decision Policy, Required Presentation, Decision Priority, Action Inertia, Current-State Authority

### Community 56 - "MarketRegimeTests"
Cohesion: 0.12
Nodes (16): Equity Research — Daily Delivery Policy, Same-day continuation under the owner's full-fill assumption (2026-09-28), Owner attention windows (2026-09-28; first new cycle September 29), Current delivery and presentation rule (2026-09-26), Eligibility, Frequency, Action-email presentation (v2, 2026-09-05), Visible watch candidates (2026-09-14) (+8 more)

### Community 118 - ".inputs"
Cohesion: 0.22
Nodes (8): Equity Research — Daily Research Policy, Principle, Source Hierarchy, Refresh and Freshness Rules, Facts, Estimates, and Opinions, Long-Term Interpretation, Request Discipline, Source coverage and research completeness

### Community 100 - "earnings_incorporation.py"
Cohesion: 0.33
Nodes (5): Equity Research — Dynamic Weight Policy, Current-Weight Formula, Stored Percentage Boundary, Concentration and Sleeve Rules, Price Quality

### Community 113 - "OwnerSnapshotTests"
Cohesion: 0.40
Nodes (5): Equity Research 命名与归档规则, “5R”的来源与结论, 文件与目录, 兼容边界, 派生知识图谱显示名

### Community 70 - "ResearchRiskLimitsTests"
Cohesion: 0.33
Nodes (5): Equity Research — Manual Execution Policy, Purpose, State Contract, Current-State Authority, Boundaries

### Community 71 - "build_current_research_baseline.py"
Cohesion: 0.25
Nodes (7): Equity Research — MacBook → GitHub → Mac mini workflow, Production boundary, Normal authoring and deployment, Failure behavior, Bounded collection continuity during network failure, Runtime operations, Absolute-path audit

### Community 106 - "Maintained investment research workflow"
Cohesion: 0.29
Nodes (6): Maintained investment research workflow, Information flow and authority, Daily and longer-horizon work, Private records and operator updates, Operational reliability, Limitations that remain deliberate

### Community 103 - "IncorporationTests"
Cohesion: 0.29
Nodes (7): Momentum integration decision — 2026-09-27, Owner-approved first-cohort review timing — September 27 follow-up, What was verified, Source-grounded integration choices, What runs without another chat, Frozen experiment and limits, External feasibility sources (checked September 27, 2026)

### Community 58 - "load_inhibit"
Cohesion: 0.15
Nodes (12): Owner-requested research reviews, Later-email continuity preference (2026-09-28), Durable follow-through for interactive reviews (2026-09-28), Current email correction (2026-09-26), Risk-policy direction (2026-09-14 evening), Delivery expectation, Required review content, Broker and order mechanics (+4 more)

### Community 132 - "Pipeline audit and repair — September 28, 2026"
Cohesion: 0.40
Nodes (4): Pipeline audit and repair — September 28, 2026, Repaired contracts, Preserve the forward experiment across a software repair, Close the analytical follow-through gap

### Community 114 - "cards"
Cohesion: 0.50
Nodes (3): Position purpose and reassessment, Explicit purpose, Required reassessment

### Community 104 - "RecommendationNotificationTests"
Cohesion: 0.33
Nodes (5): Equity Research — Price Guidance Policy, Evidence, Slippage Review Formula, Order-Style Framework, Boundary

### Community 109 - "_DocumentPeriod"
Cohesion: 0.33
Nodes (5): Equity Research — Long-Horizon Return Objective Policy, Objective, Measurement Contract, Decision Implications, Active Boundary

### Community 105 - "RequestedCoverageTests"
Cohesion: 0.33
Nodes (5): Ross Cameron primary-source audit, Evidence classification, Different challenges must remain separate, Documented practices and the limits of importing them, Proposed workspace adaptations (our design, not Ross's rules)

### Community 65 - "score_candidates.py"
Cohesion: 0.29
Nodes (6): Equity Research — SEC Acceptance-Index Extension Policy v1, Immutable historical layer, Admission requirements, Versioned artifacts and audit, Commit and recovery behavior, Boundaries

### Community 127 - "Source Policy"
Cohesion: 0.25
Nodes (8): Equity Research — SHADOW_LLM Evaluation Policy, Question being measured, Isolation and deterministic authority, Small evaluation architecture, Event-driven selection and replay, Calls and cost, Evidence stages, Stop conditions

### Community 111 - "Workflow reliability and performance evidence"
Cohesion: 0.40
Nodes (4): Workflow reliability and performance evidence, Operational measurement, Recommendation evaluation, Confirmed actual account observations

### Community 115 - "Scoped blockers and recurring research work"
Cohesion: 0.33
Nodes (5): Scoped blockers and recurring research work, Blocker scope, Cash and recurring work, Bounded objective research, Expired plans and reporting

### Community 296 - "check_llm_shadow_status.sh"
Cohesion: 0.40
Nodes (4): Brokerage Boundary, Prohibited, Allowed, Human Responsibility

### Community 239 - "Data Source Policy"
Cohesion: 0.33
Nodes (5): Data Source Policy, Preferred Sources, Secondary Sources, Weak Evidence, Prohibited Sources And Data

### Community 297 - "install_llm_shadow_scheduler.sh"
Cohesion: 0.40
Nodes (4): Manual Approval Policy, Approval Boundary, Required Before Approval, Out Of Scope

### Community 147 - "Risk Policy"
Cohesion: 0.25
Nodes (7): Risk Policy, Hard Rules, Account Scope, Risk Limits, Position Risk, Portfolio Risk, Review Cadence

### Community 241 - "Source Policy"
Cohesion: 0.33
Nodes (5): Source Policy, Strong Sources, Useful Secondary Sources, Weak Sources, Citation Expectations

### Community 242 - "enable_llm_live_shadow.py"
Cohesion: 0.33
Nodes (5): Trading Checklist, Research Completeness, Market Quality, Risk Controls, Approval

### Community 163 - "AGENTS.md"
Cohesion: 0.20
Nodes (8): Purpose, Non-Negotiable Constraints, Research Standards, Owner-Requested Reviews and Email, File Conventions, Script Safety, Completion evidence for pipeline changes, graphify

### Community 37 - "Early Public Equity Lab"
Cohesion: 0.25
Nodes (8): Equity Research, Repository Paths, Current Workflow, Long-horizon workflow upgrade (2026-09-20), Safety Boundaries, What The System Can Do, What The System Cannot Do, Current Safe Status Commands

## Knowledge Gaps
- **244 isolated node(s):** `activate_daily_after_verification.sh script`, `check_daily_scheduler_status.sh script`, `check_shadow_llm_evaluation_scheduler.sh script`, `clear_maintenance_inhibit.sh script`, `install_daily_schedulers.sh script` (+239 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **34 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `canonical_sha256()` connect `AST` to `market_data_adapter.py`, `send_c6_weekly_email.py`, `test_active_production.py`, `main`, `main`, `PacketMarketObservationTests`, `verify_c6_weekly_email_boundary.py`, `ShadowMeasurementTests`, `llm_contract.py`, `PacketMarketObservationTests`, `compare_policies`, `evaluate_shadow_llm_incremental_value.py`, `applied_reconciliation_matches_current_state`, `ResearchRiskLimitsTests`, `verify_c2_email_delivery_boundary.py`, `HeldCorePositionTests`, `Owner-requested research reviews`, `economic_packet`, `portfolio_construction.py`, `test_refresh_cadence.py`, `AcceptanceReconciliationError`, `report_heading`, `score_candidates.py`, `sec_acceptance_extensions.py`, `main`, `OwnerSnapshotTests`, `workflow_health`, `MaintainedThesisTests`, `delivery_meaning_key`, `test_thesis_evidence.py`?**
  _High betweenness centrality (0.119) - this node is a cross-community bridge._
- **Why does `render_email()` connect `execution_common.py` to `OwnerSnapshotTests`, `ResearchRiskLimitsTests`, `workflow_health`, `main`, `PacketMarketObservationTests`, `save_decision`, `delivery_meaning_key`, `score_candidates.py`, `test_sender_publication.py`, `main`, `evaluate_shadow_llm_incremental_value.py`, `next_thursday`, `portfolio_construction.py`?**
  _High betweenness centrality (0.049) - this node is a cross-community bridge._
- **Why does `main()` connect `evaluate_shadow_llm_incremental_value.py` to `market_data_adapter.py`, `OwnerSnapshotTests`, `AST`, `workflow_health`, `ShadowProviderError`, `main`, `score_candidates.py`, `delivery_meaning_key`, `economic_packet`, `verify_daily_upgrade.py`, `ShadowLlmTests`, `Early Public Equity Research`, `execution_common.py`, `ResearchRiskLimitsTests`, `portfolio_construction.py`, `shadow_llm_contract.py`?**
  _High betweenness centrality (0.046) - this node is a cross-community bridge._
- **Are the 103 inferred relationships involving `canonical_sha256()` (e.g. with `evaluate_archived()` and `_market_observations()`) actually correct?**
  _`canonical_sha256()` has 103 INFERRED edges - model-reasoned connections that need verification._
- **Are the 59 inferred relationships involving `render_email()` (e.g. with `main()` and `brand_name()`) actually correct?**
  _`render_email()` has 59 INFERRED edges - model-reasoned connections that need verification._
- **Are the 44 inferred relationships involving `read_json()` (e.g. with `load_active_config()` and `main()`) actually correct?**
  _`read_json()` has 44 INFERRED edges - model-reasoned connections that need verification._
- **Are the 30 inferred relationships involving `main()` (e.g. with `is_core_allocation_ticker()` and `load_active_config()`) actually correct?**
  _`main()` has 30 INFERRED edges - model-reasoned connections that need verification._