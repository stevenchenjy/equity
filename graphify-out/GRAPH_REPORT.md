# Graph Report - equity  (2026-09-20)

## Corpus Check
- 184 files · ~188,328 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1940 nodes · 4870 edges · 102 communities (80 shown, 22 thin omitted)
- Extraction: 83% EXTRACTED · 17% INFERRED · 0% AMBIGUOUS · INFERRED: 842 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ea3b115d`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- phase5r_market_data_adapter.py
- run_phase5r_b2_full_universe_market_data.py
- AST
- send_phase5r_c6_weekly_email.py
- test_phase5r_active_production.py
- score_phase5r_b_candidates.py
- ShadowProviderError
- main
- ShadowLlmTests
- main
- PacketMarketObservationTests
- verify_phase5r_daily_upgrade.py
- iso_now
- verify_phase5r_c6_weekly_email_boundary.py
- score_phase5r_b2_candidates.py
- ShadowMeasurementTests
- phase5r_llm_contract.py
- phase5r_c9b_common.py
- verify_phase5r_c5t_manual_action_boundary.py
- main
- phase5r_c9_common.py
- PacketMarketObservationTests
- compare_policies
- evaluate_phase5r_shadow_llm_incremental_value.py
- applied_reconciliation_matches_current_state
- ResearchRiskLimitsTests
- phase5r_portfolio_construction.py
- next_thursday
- verify_phase5r_c2_email_delivery_boundary.py
- HeldCorePositionTests
- main
- check_phase5r_shadow_llm_evaluation_scheduler.sh
- install_phase5r_shadow_llm_evaluation_scheduler.sh
- run_phase5r_shadow_llm_event.sh
- ShadowLlmTests
- Phase5R MacBook → GitHub → Mac mini workflow
- main
- Early Public Equity Lab
- Phase 5R AI operating decision
- Phase 5R — current document entrypoints
- create_phase5r_c5_weekly_conviction_memo.py
- score_phase5r_b2_candidates.py
- Phase 5R risk-policy audit — 2026-09-14
- Owner-requested research reviews
- economic_packet
- phase5r_portfolio_construction.py
- write_extension_admission_audit
- test_phase5r_b2_refresh_cadence.py
- ShadowProviderError
- ShadowMeasurementTests
- economic_packet
- phase5r_valuation_input_bundle.py
- Scoring
- main
- Phase 0C Reframe Plan
- main
- MarketRegimeTests
- OfficialNewsScheduleTests
- load_inhibit
- create_phase5r_long_horizon_research.py
- phase5r_risk_profile_activation_20260914.md
- phase5r_workflow_standards_audit_20260920.md
- Early Public Equity Research
- Phase 5R-C3 Daily Email Pipeline Policy
- ._write_coherent_prior_outputs
- graphify reference: query, path, explain
- Source Policy
- Phase 5R-B2 Data Source Decision
- Phase 5R-C2 Gmail SMTP Setup
- Phase 5R-C5 Verification Report
- Phase 5R-C2 Verification Report
- Phase 0A Canonical Project Structure Proposal
- Phase 0E Phase 5R Integrity Check
- latest_phase5r_b2_manual_trade_tickets.md
- latest_phase5r_b2_watchlist.md
- latest_phase5r_b_manual_trade_tickets.md
- latest_phase5r_b_watchlist.md
- latest_phase5r_c1_email_preview.md
- latest_phase5r_c6_weekly_email_preview.md
- create_phase5r_c4_position_template.py
- create_phase5r_c5_weekly_conviction_memo.py
- Phase 5R-D3G Research Verification Report
- Phase 5R-C9A Account-State and Stale-Denominator Audit Policy
- enable_phase5r_llm_live_shadow.py
- Phase 5R-C9 Core Allocation Policy
- check_phase5r_llm_shadow_status.sh
- install_phase5r_llm_shadow_scheduler.sh
- Phase 5R LLM Shadow Verification Report
- run_phase5r_llm_shadow_scheduler.py
- send_phase5r_daily_email.py
- Phase 5R Model Shadow Readiness — Research Summary
- ShadowOutputLock
- phase5r_anonymous_review_materials_status.md
- CodexCliProvider
- iso_now
- Phase 5R Model Pilot — Terminal No-Go Report
- Phase 5R v8 provider-reliability gate proposal
- main
- test_phase5r_model_pilot_v7.py
- Phase 5R v9 terminal diagnosis
- B2RefreshCadenceTests

## God Nodes (most connected - your core abstractions)
1. `canonical_sha256()` - 53 edges
2. `render_email()` - 40 edges
3. `_execute_unlocked()` - 38 edges
4. `read_json()` - 36 edges
5. `main()` - 35 edges
6. `main()` - 33 edges
7. `RuntimeSyncError` - 33 edges
8. `iso_now()` - 32 edges
9. `ExclusiveFileLock` - 30 edges
10. `build_email_view()` - 26 edges

## Surprising Connections (you probably didn't know these)
- `fetch()` --calls--> `atomic_write_text()`  [INFERRED]
  09_scripts/phase5r/audit_phase5r_financial_coverage.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `iso_now()`  [INFERRED]
  09_scripts/phase5r/audit_phase5r_financial_coverage.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `read_json()`  [INFERRED]
  09_scripts/phase5r/audit_phase5r_financial_coverage.py → 09_scripts/phase5r/phase5r_daily_common.py
- `selected_tickers()` --calls--> `fundamentals_candidate_queue()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_long_horizon_research.py
- `main()` --calls--> `latest_published_market_session()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py

## Import Cycles
- None detected.

## Communities (102 total, 22 thin omitted)

### Community 0 - "phase5r_market_data_adapter.py"
Cohesion: 0.20
Nodes (6): CacheTests, ledger_row(), NormalizationTests, Path, SelectionAndValidationTests, write_ledger()

### Community 1 - "run_phase5r_b2_full_universe_market_data.py"
Cohesion: 0.16
Nodes (28): action_review_display(), action_stability(), candidate_proposal_fingerprint(), candidate_stability(), execution_conflicts(), held_position_summary(), held_research_context(), is_action_transition() (+20 more)

### Community 2 - "AST"
Cohesion: 0.13
Nodes (53): canonical_sha256(), build_semantic_view(), Return the only packet view eligible for external shadow inference., Provider, _append_ledger_event(), _archive_packet(), _archived_packet_index(), _atomic_private_json() (+45 more)

### Community 3 - "send_phase5r_c6_weekly_email.py"
Cohesion: 0.11
Nodes (16): CanonicalWorkflowTests, OptionalActiveInputTests, registry_row(), _canonical_source_issues(), Check, collect_checks(), _deprecated_registry_issues(), _loaded() (+8 more)

### Community 4 - "test_phase5r_active_production.py"
Cohesion: 0.16
Nodes (36): admit_unindexed_current_records(), _audit_row(), build_extension_artifact(), _core_record(), extension_acceptance_records(), extension_artifact_path(), _extension_number(), extension_set_sha256() (+28 more)

### Community 5 - "score_phase5r_b_candidates.py"
Cohesion: 0.06
Nodes (47): ExclusiveFileLock, Process lock using flock over a private, non-linked regular file., _append_execution_record(), assert_non_icloud_runtime_root(), _best_effort_failure_record(), _exec_scheduler(), _git(), inspect_runtime_repository() (+39 more)

### Community 6 - "ShadowProviderError"
Cohesion: 0.16
Nodes (3): PacketMarketObservationTests, Path, write_csv()

### Community 7 - "main"
Cohesion: 0.16
Nodes (21): easter_sunday(), expected_market_session(), last_completed_market_session(), last_weekday(), latest_published_market_session(), nth_weekday(), observed(), date (+13 more)

### Community 8 - "ShadowLlmTests"
Cohesion: 0.17
Nodes (21): bool_value(), delivery_guard(), load_active_state(), load_inhibit(), notification_change_comparison(), Any, Hash recommendation meaning, excluding quotes, dates and raw filings., recommendation_notification_fingerprint() (+13 more)

### Community 9 - "main"
Cohesion: 0.16
Nodes (19): datetime, Independent official-news checks using the existing serialized scheduler.  No se, run_due_news_checks(), due_slots(), main(), market_snapshot_mode(), _market_step_passed(), _massive_auth_presence_probe_exit_code() (+11 more)

### Community 10 - "PacketMarketObservationTests"
Cohesion: 0.24
Nodes (20): append_delivery(), build_message(), ConfigError, correction_eligibility(), cycle_is_blocked(), delivery_policy(), load_config(), main() (+12 more)

### Community 11 - "verify_phase5r_daily_upgrade.py"
Cohesion: 0.12
Nodes (19): line_excerpt(), main(), number(), Any, Path, Fail closed before producing a range, not merely before order routing., Match the packet clock's whole-second point-in-time precision., selected_band() (+11 more)

### Community 12 - "iso_now"
Cohesion: 0.09
Nodes (12): ActiveConfigError, load_active_config(), main(), Any, Path, ValueError, Raised when the active configuration is unsafe or incomplete., Validate an optional research overlay without accepting financial data. (+4 more)

### Community 13 - "verify_phase5r_c6_weekly_email_boundary.py"
Cohesion: 0.07
Nodes (45): InlineFacts, parse_principal_facts(), project_relative_locator(), Any, datetime, HTMLParser, Path, ValueError (+37 more)

### Community 14 - "score_phase5r_b2_candidates.py"
Cohesion: 0.33
Nodes (12): add_check(), append_verification_log(), file_digest_or_absent(), loaded(), main(), plist_checks(), pure_guard_tests(), Path (+4 more)

### Community 15 - "ShadowMeasurementTests"
Cohesion: 0.12
Nodes (23): canonical_url(), clean_title(), fetch_feed(), load_manifest(), NewsError, OfficialRedirect, parse_feed(), _PlainText (+15 more)

### Community 16 - "phase5r_llm_contract.py"
Cohesion: 0.08
Nodes (57): _allowed_classifications_by_ticker(), _artifact_map(), build_packet(), _compact_fact_provenance(), _date_from_period(), _decimal(), _decision_tickers(), _effective_acceptance_map() (+49 more)

### Community 17 - "phase5r_c9b_common.py"
Cohesion: 0.24
Nodes (14): main(), execution_cash(), intraday_range_pct(), load_execution_rows(), optional_float(), parse_iso(), slippage_review_pct(), validate_execution_row() (+6 more)

### Community 18 - "verify_phase5r_c5t_manual_action_boundary.py"
Cohesion: 0.11
Nodes (43): artifact_paths(), ArtifactError, atomic_write_bytes(), atomic_write_json(), build_chunks(), build_entry(), check_artifacts(), complete_cache_entry() (+35 more)

### Community 19 - "main"
Cohesion: 0.15
Nodes (27): acceptance_map(), AcceptanceReconciliationError, load_acceptance_index(), load_acceptance_reconciliation_log(), load_immutable_acceptance_index(), _make_reconciliation_row(), normalize_acceptance_timestamp(), _normalize_generated_at() (+19 more)

### Community 20 - "phase5r_c9_common.py"
Cohesion: 0.17
Nodes (27): main(), create_if_missing(), main(), main(), _post_action_row(), main(), append_run_log(), as_float() (+19 more)

### Community 21 - "PacketMarketObservationTests"
Cohesion: 0.16
Nodes (24): build_valuation_evidence_v1(), _calculation_receipt(), _InputSpec, _normalize_input(), _parse_decimal(), _parse_utc(), _payload_digest(), _plain_decimal() (+16 more)

### Community 22 - "compare_policies"
Cohesion: 0.12
Nodes (12): compare_policies(), _decimal(), Holding, _number(), Compare capacities independently, never sum candidate share counts.  These are u, Apply explicit per-ticker price shocks simultaneously, keeping cash fixed.  Ever, RiskPolicy, simultaneous_stress() (+4 more)

### Community 23 - "evaluate_phase5r_shadow_llm_incremental_value.py"
Cohesion: 0.19
Nodes (32): aggregate(), _atomic_private_snapshot_text(), _atomic_private_text(), _authority_checks(), _deduplicate_evidence(), _discover(), _evidence_keys(), load_automatic_bundle() (+24 more)

### Community 24 - "applied_reconciliation_matches_current_state"
Cohesion: 0.26
Nodes (6): applied_reconciliation_current_state_status(), applied_reconciliation_matches_current_state(), Classify whether a current C9 state remains consistent with one fill.      C9B r, Return the closed accepted subset of reconciliation-state statuses., C9BAccountSnapshotRefreshTests, _reconciliation()

### Community 25 - "ResearchRiskLimitsTests"
Cohesion: 0.15
Nodes (7): core_starter_decision(), individual_sizing_decision(), _passed_confidence(), Any, Size one staged broad-market core review without using stock valuation., Return the highest supported sizing tier and a feasible share count., ResearchRiskLimitsTests

### Community 26 - "phase5r_portfolio_construction.py"
Cohesion: 0.06
Nodes (35): _action_kind(), build_email_view(), _comparison_weight(), _conflict_tasks(), _decimal(), email_subject(), _is_core(), money() (+27 more)

### Community 27 - "next_thursday"
Cohesion: 0.16
Nodes (19): build_long_horizon_report(), fundamentals_candidate_queue(), hurdle_diagnostic(), number(), provenance(), Any, datetime, Pure long-horizon research arithmetic; sensitivities never authorize actions. (+11 more)

### Community 28 - "verify_phase5r_c2_email_delivery_boundary.py"
Cohesion: 0.14
Nodes (14): AcceptanceIndexError, build_acceptance_index(), make_acceptance_record(), ValueError, The SEC acceptance index failed its closed validation contract., validate_acceptance_index(), validate_acceptance_record(), Regression coverage for the SEC acceptance precommit boundary. (+6 more)

### Community 30 - "main"
Cohesion: 0.17
Nodes (33): analyst_schema(), _assert_nonimperative(), build_deterministic_baseline(), _calculation_index(), critic_schema(), deterministic_claim_capture(), _entity_tickers(), _enum() (+25 more)

### Community 34 - "ShadowLlmTests"
Cohesion: 0.09
Nodes (52): acceptance_map(), fetch(), main(), Path, classify_materiality(), company_fundamentals_required(), count_unindexed_acceptance_accessions(), current_submission_entity_name() (+44 more)

### Community 35 - "Phase5R MacBook → GitHub → Mac mini workflow"
Cohesion: 0.33
Nodes (6): Absolute-path audit, Failure behavior, Normal authoring and deployment, Phase5R MacBook → GitHub → Mac mini workflow, Production boundary, Runtime operations

### Community 36 - "main"
Cohesion: 0.10
Nodes (15): build_automatic_evaluation(), build_blind_judge_target(), deterministic_claim_check(), Conservative one-fact sign check, never a generic semantic truth judge.      Com, Create a deterministic candidate set without origin or model labels., FailingProvider, fake_packet(), ShadowLlmTests (+7 more)

### Community 37 - "Early Public Equity Lab"
Cohesion: 0.25
Nodes (8): Current Safe Status Commands, Current Workflow, Early Public Equity Lab, Long-horizon workflow upgrade (2026-09-20), Repository Paths, Safety Boundaries, What The System Can Do, What The System Cannot Do

### Community 38 - "Phase 5R AI operating decision"
Cohesion: 0.13
Nodes (10): Boundaries, Decision, Future evaluation boundary, Historical decision evidence — August 31 only, Phase 5R AI operating decision, 四项投资工作流标准：实施计划与验收, Automatic event modes, Evaluation (+2 more)

### Community 39 - "Phase 5R — current document entrypoints"
Cohesion: 0.14
Nodes (9): Cash-Deployment Decision, Phase 5R-C9 Core Allocation Policy, Separation, Authoritative policy and boundaries, Current runtime outputs — read their generated timestamps, Historical material — retained, not current instructions, Phase 5R — current document entrypoints, 长期研究、倍增情景与证据边界 (+1 more)

### Community 40 - "create_phase5r_c5_weekly_conviction_memo.py"
Cohesion: 0.17
Nodes (24): build_evidence_freshness_receipt(), EvidenceFreshnessError, freshness_action_review_reasons(), _normalize_bool(), _normalize_date(), _normalize_digest(), _normalize_source_ids(), _normalize_ticker() (+16 more)

### Community 41 - "score_phase5r_b2_candidates.py"
Cohesion: 0.60
Nodes (4): _jsonl(), main(), _number(), Path

### Community 42 - "Phase 5R risk-policy audit — 2026-09-14"
Cohesion: 0.33
Nodes (5): Minimal coherent follow-up, after a policy choice, New offline diagnostic, Origins and current code path, Phase 5R risk-policy audit — 2026-09-14, Scope and conclusion

### Community 43 - "Owner-requested research reviews"
Cohesion: 0.29
Nodes (6): Boundaries, Broker and order mechanics, Delivery expectation, Owner-requested research reviews, Required review content, Risk-policy direction (2026-09-14 evening)

### Community 46 - "write_extension_admission_audit"
Cohesion: 0.42
Nodes (5): Bind an extension to exact immutable historical-index bytes., raw_file_sha256(), write_acceptance_index(), acceptance_record(), SecAcceptanceExtensionTests

### Community 48 - "ShadowProviderError"
Cohesion: 0.13
Nodes (18): classify_nonzero_exit(), cli_reported_token_usage(), CodexCliProvider, executable_sha256(), FixtureProvider, minimal_codex_environment(), ProviderResult, Any (+10 more)

### Community 51 - "phase5r_valuation_input_bundle.py"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 52 - "Scoring"
Cohesion: 0.14
Nodes (22): main(), number(), Any, Solve required revenue for explicit terminal-multiple/return sensitivities., reverse_expectations(), whole_share_diagnostics(), ReassessmentReportingTests, append_jsonl() (+14 more)

### Community 53 - "main"
Cohesion: 0.11
Nodes (9): confirmed_thesis_break(), held_recommendation_label(), load_thesis_reviews(), date, Optional analyst assessments; absence never turns a score into a sale., Require a reviewed, dated primary source and the actual invalidated rule.      T, valuation_trim_review_required(), ResearchWarningNotificationTests (+1 more)

### Community 54 - "Phase 0C Reframe Plan"
Cohesion: 0.16
Nodes (10): MassiveB2AdapterResilienceTests, _payload(), The Basic delayed shape normalizes without leaking provider metadata., Ticker, adjustment, pagination, and malformed data each stop once., A provider 429 is one request and exposes neither URL detail nor key., Every new ticker is locally paced, while a failed request is never retried., Sanitized current Custom Bars shape, including optional metadata., The external-runtime key authorizes one request but never enters its URL/output. (+2 more)

### Community 55 - "main"
Cohesion: 0.20
Nodes (17): csv_fields(), Path, write_csv(), write_text(), append_c9b_log(), Path, select_execution(), sha256() (+9 more)

### Community 56 - "MarketRegimeTests"
Cohesion: 0.21
Nodes (5): build_regime(), number(), Any, Use a single complete public close; repeated intraday runs add no votes., MarketRegimeTests

### Community 58 - "load_inhibit"
Cohesion: 0.14
Nodes (28): clamp(), main(), number(), selected_tickers(), main(), jsonl_count(), main(), Path (+20 more)

### Community 61 - "create_phase5r_long_horizon_research.py"
Cohesion: 0.70
Nodes (4): display(), main(), missing_label(), render_report()

### Community 78 - "Early Public Equity Research"
Cohesion: 0.06
Nodes (68): is_us_market_session_date(), api_key_from_environment(), _default_http_get(), _finite_number(), _http_failure_code(), MassiveB2Error, MassiveBasicEODClient, _NoRedirectHandler (+60 more)

### Community 101 - "Phase 5R-C3 Daily Email Pipeline Policy"
Cohesion: 0.25
Nodes (7): Active Workflow, Authority Order, Phase 5R-C8 Canonical Active-State Policy, Pipeline Requirement, Purpose, Safety Boundary, Stale-File Guard

### Community 122 - "._write_coherent_prior_outputs"
Cohesion: 0.11
Nodes (21): B2MarketRefreshFailureCommitTests, _candidate_row(), _CompleteCachedClient, _DuplicateSessionErrorClient, _FailingFullFetchClient, _market_row(), _PartialTwentyNineTickerClient, date (+13 more)

### Community 126 - "graphify reference: query, path, explain"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 127 - "Source Policy"
Cohesion: 0.25
Nodes (8): Calls and cost, Event-driven selection and replay, Evidence stages, Isolation and deterministic authority, Phase 5R SHADOW_LLM Evaluation Policy, Question being measured, Small evaluation architecture, Stop conditions

### Community 133 - "Phase 5R-B2 Data Source Decision"
Cohesion: 0.29
Nodes (6): Data Handling, Permitted Source and Scope, Phase 5R-B2 Full-Universe Data Policy, Purpose, Safety Boundary, Scoring

### Community 135 - "Phase 5R-C2 Gmail SMTP Setup"
Cohesion: 0.22
Nodes (8): Facts, Estimates, and Opinions, Long-Term Interpretation, Phase 5R Daily Research Policy, Principle, Refresh and Freshness Rules, Request Discipline, Source coverage and research completeness, Source Hierarchy

### Community 147 - "Phase 5R-C5 Verification Report"
Cohesion: 0.29
Nodes (7): Account Scope, Hard Rules, Portfolio Risk, Position Risk, Review Cadence, Risk Limits, Risk Policy

### Community 163 - "Phase 5R-C2 Verification Report"
Cohesion: 0.22
Nodes (7): File Conventions, graphify, Non-Negotiable Constraints, Owner-Requested Reviews and Email, Purpose, Research Standards, Script Safety

### Community 181 - "Phase 0A Canonical Project Structure Proposal"
Cohesion: 0.33
Nodes (5): Active Boundary, Decision Implications, Measurement Contract, Objective, Phase 5R Long-Horizon Return Objective Policy

### Community 182 - "Phase 0E Phase 5R Integrity Check"
Cohesion: 0.29
Nodes (6): Admission requirements, Boundaries, Commit and recovery behavior, Immutable historical layer, Phase 5R SEC Acceptance-Index Extension Policy v1, Versioned artifacts and audit

### Community 220 - "latest_phase5r_b2_manual_trade_tickets.md"
Cohesion: 0.29
Nodes (6): Canonical Inputs, Optional research-only risk limits, Phase 5R-C9 Account-State Policy, Privacy and Execution Boundary, Runtime State, Validation

### Community 221 - "latest_phase5r_b2_watchlist.md"
Cohesion: 0.33
Nodes (5): Allowed Exact Actions, Current Positions, Maximum Entry and Trim Conditions, New Individual-Stock Eligibility, Phase 5R-C9 Action Threshold Policy

### Community 222 - "latest_phase5r_b_manual_trade_tickets.md"
Cohesion: 0.33
Nodes (5): Concentration and Sleeve Rules, Current-Weight Formula, Phase 5R-C9 Dynamic Weight Policy, Price Quality, Stored Percentage Boundary

### Community 223 - "latest_phase5r_b_watchlist.md"
Cohesion: 0.33
Nodes (5): Account Total, Canonical Update, Cash, Phase 5R-C9B Account Reconciliation Policy, Preconditions

### Community 224 - "latest_phase5r_c1_email_preview.md"
Cohesion: 0.33
Nodes (5): Boundaries, Current-State Authority, Phase 5R-C9B Manual Execution Policy, Purpose, State Contract

### Community 225 - "latest_phase5r_c6_weekly_email_preview.md"
Cohesion: 0.33
Nodes (5): Boundary, Evidence, Order-Style Framework, Phase 5R-C9B Price Guidance Policy, Slippage Review Formula

### Community 233 - "create_phase5r_c4_position_template.py"
Cohesion: 0.33
Nodes (5): Action Inertia, Current-State Authority, Decision Priority, Phase 5R Daily Decision Policy, Required Presentation

### Community 234 - "create_phase5r_c5_weekly_conviction_memo.py"
Cohesion: 0.17
Nodes (11): Action-email presentation (v2, 2026-09-05), Boundaries, Duplicate Protection, Eligibility, Explicit correction resend, Explicit owner-requested review (2026-09-14), Frequency, Owner snapshots and flexible research funding (2026-09-11) (+3 more)

### Community 239 - "Phase 5R-D3G Research Verification Report"
Cohesion: 0.33
Nodes (5): Data Source Policy, Preferred Sources, Prohibited Sources And Data, Secondary Sources, Weak Evidence

### Community 241 - "Phase 5R-C9A Account-State and Stale-Denominator Audit Policy"
Cohesion: 0.33
Nodes (5): Citation Expectations, Source Policy, Strong Sources, Useful Secondary Sources, Weak Sources

### Community 242 - "enable_phase5r_llm_live_shadow.py"
Cohesion: 0.33
Nodes (5): Approval, Market Quality, Research Completeness, Risk Controls, Trading Checklist

### Community 258 - "Phase 5R-C9 Core Allocation Policy"
Cohesion: 0.33
Nodes (5): For /graphify explain, For /graphify path, graphify reference: query, path, explain, Step 0 — Constrained query expansion (REQUIRED before traversal), Step 1 — Traversal

### Community 296 - "check_phase5r_llm_shadow_status.sh"
Cohesion: 0.40
Nodes (4): Allowed, Brokerage Boundary, Human Responsibility, Prohibited

### Community 297 - "install_phase5r_llm_shadow_scheduler.sh"
Cohesion: 0.40
Nodes (4): Approval Boundary, Manual Approval Policy, Out Of Scope, Required Before Approval

### Community 362 - "Phase 5R Model Shadow Readiness — Research Summary"
Cohesion: 0.50
Nodes (3): For /graphify add, For --watch, graphify reference: add a URL and watch a folder

### Community 363 - "ShadowOutputLock"
Cohesion: 0.50
Nodes (3): For git commit hook, For native CLAUDE.md integration, graphify reference: commit hook and native CLAUDE.md integration

### Community 364 - "phase5r_anonymous_review_materials_status.md"
Cohesion: 0.50
Nodes (3): For --cluster-only, For --update (incremental re-extraction), graphify reference: incremental update and cluster-only

### Community 410 - "B2RefreshCadenceTests"
Cohesion: 0.08
Nodes (18): append_audit(), as_float(), clamp(), main(), Path, read_csv(), score_row(), timestamp() (+10 more)

## Knowledge Gaps
- **192 isolated node(s):** `activate_phase5r_daily_after_verification.sh script`, `check_phase5r_daily_scheduler_status.sh script`, `check_phase5r_shadow_llm_evaluation_scheduler.sh script`, `clear_phase5r_c9_maintenance_inhibit.sh script`, `install_phase5r_daily_schedulers.sh script` (+187 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **22 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `canonical_sha256()` connect `AST` to `run_phase5r_b2_full_universe_market_data.py`, `ShadowLlmTests`, `test_phase5r_active_production.py`, `main`, `main`, `ShadowLlmTests`, `ShadowMeasurementTests`, `phase5r_llm_contract.py`, `ShadowProviderError`, `economic_packet`, `main`, `Scoring`, `evaluate_phase5r_shadow_llm_incremental_value.py`, `verify_phase5r_c2_email_delivery_boundary.py`, `main`?**
  _High betweenness centrality (0.074) - this node is a cross-community bridge._
- **Why does `main()` connect `ShadowLlmTests` to `AST`, `test_phase5r_active_production.py`, `score_phase5r_b_candidates.py`, `verify_phase5r_c6_weekly_email_boundary.py`, `write_extension_admission_audit`, `ShadowMeasurementTests`, `main`, `load_inhibit`, `verify_phase5r_c2_email_delivery_boundary.py`?**
  _High betweenness centrality (0.025) - this node is a cross-community bridge._
- **Are the 49 inferred relationships involving `canonical_sha256()` (e.g. with `build_packet()` and `_fundamental_observations()`) actually correct?**
  _`canonical_sha256()` has 49 INFERRED edges - model-reasoned connections that need verification._
- **Are the 34 inferred relationships involving `render_email()` (e.g. with `main()` and `.value()`) actually correct?**
  _`render_email()` has 34 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `_execute_unlocked()` (e.g. with `canonical_sha256()` and `iso_now()`) actually correct?**
  _`_execute_unlocked()` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 29 inferred relationships involving `read_json()` (e.g. with `main()` and `selected_tickers()`) actually correct?**
  _`read_json()` has 29 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `main()` (e.g. with `append_csv_durable()` and `atomic_write_csv()`) actually correct?**
  _`main()` has 20 INFERRED edges - model-reasoned connections that need verification._