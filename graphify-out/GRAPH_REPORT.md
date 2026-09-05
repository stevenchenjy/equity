# Graph Report - equity  (2026-09-04)

## Corpus Check
- 153 files · ~159,306 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1670 nodes · 3980 edges · 95 communities (79 shown, 16 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 636 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e8edf0dd`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- phase5r_market_data_adapter.py
- run_phase5r_b2_full_universe_market_data.py
- AST
- send_phase5r_c6_weekly_email.py
- test_phase5r_active_production.py
- score_phase5r_b_candidates.py
- phase5r_c9b_common.py
- main
- iso_now
- main
- PacketMarketObservationTests
- verify_phase5r_daily_upgrade.py
- iso_now
- verify_phase5r_c6_weekly_email_boundary.py
- score_phase5r_b2_candidates.py
- main
- phase5r_llm_contract.py
- verify_phase5r_daily_upgrade.py
- verify_phase5r_c5t_manual_action_boundary.py
- applied_reconciliation_matches_current_state
- phase5r_c9_common.py
- PacketMarketObservationTests
- _support.py
- evaluate_phase5r_shadow_llm_incremental_value.py
- run_phase5r_daily_decision_pipeline.py
- score_phase5r_b2_candidates.py
- phase5r_portfolio_construction.py
- next_thursday
- verify_phase5r_c2_email_delivery_boundary.py
- main
- HeldCorePositionTests
- check_phase5r_shadow_llm_evaluation_scheduler.sh
- install_phase5r_shadow_llm_evaluation_scheduler.sh
- run_phase5r_shadow_llm_event.sh
- ShadowLlmTests
- create_phase5r_c5_weekly_conviction_memo.py
- phase5r_valuation_input_bundle.py
- Scoring
- Phase 0C Reframe Plan
- Phase 0C Verification Report
- Early Public Equity Research
- AGENTS.md
- Phase 5R-D3 Catch-up Scheduler Report
- Phase 5R-B1 Data Readiness Report
- verify_source_integrity
- Phase 5R-C3 Daily Email Pipeline Policy
- Phase 5R-C5 Deep Research Policy
- Phase 5R-C5T Manual Action Policy
- Data Source Policy
- Source Policy
- ._write_coherent_prior_outputs
- graphify reference: query, path, explain
- Source Policy
- Phase 5R-B2 Data Source Decision
- Phase 5R-C2 Gmail SMTP Setup
- Phase 5R-C4R Verification Report
- Phase 5R-C5 Verification Report
- Phase 5R-C2 Verification Report
- Phase 5R-C3 Pipeline Report
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
- Phase 5R-D3G Hotfix Report
- Phase 5R-D3G Research Verification Report
- Phase 5R-C9A Account-State and Stale-Denominator Audit Policy
- enable_phase5r_llm_live_shadow.py
- Phase 5R-C9 Core Allocation Policy
- Phase 5R-C9 Weekly Decision Summary
- test_refresh_phase5r_sec_filing_artifacts.py
- check_phase5r_llm_shadow_status.sh
- install_phase5r_llm_shadow_scheduler.sh
- Phase 5R LLM Shadow Verification Report
- run_phase5r_llm_shadow_scheduler.py
- send_phase5r_daily_email.py
- latest_phase5r_b_manual_trade_tickets.md
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
- _safe_failure_code

## God Nodes (most connected - your core abstractions)
1. `canonical_sha256()` - 49 edges
2. `_execute_unlocked()` - 38 edges
3. `main()` - 34 edges
4. `RuntimeSyncError` - 33 edges
5. `iso_now()` - 30 edges
6. `ExclusiveFileLock` - 29 edges
7. `read_json()` - 26 edges
8. `ShadowContractError` - 26 edges
9. `B2RefreshCadenceTests` - 26 edges
10. `ShadowLlmTests` - 25 edges

## Surprising Connections (you probably didn't know these)
- `fetch()` --calls--> `atomic_write_text()`  [INFERRED]
  09_scripts/phase5r/audit_phase5r_financial_coverage.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `iso_now()`  [INFERRED]
  09_scripts/phase5r/audit_phase5r_financial_coverage.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `read_json()`  [INFERRED]
  09_scripts/phase5r/audit_phase5r_financial_coverage.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `atomic_write_csv()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `cycle_date()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py

## Import Cycles
- None detected.

## Communities (95 total, 16 thin omitted)

### Community 0 - "phase5r_market_data_adapter.py"
Cohesion: 0.23
Nodes (6): CacheTests, ledger_row(), NormalizationTests, Path, SelectionAndValidationTests, write_ledger()

### Community 1 - "run_phase5r_b2_full_universe_market_data.py"
Cohesion: 0.30
Nodes (15): action_review_display(), action_stability(), execution_conflicts(), held_position_summary(), is_action_transition(), latest_applied_execution(), load_market_gate(), main() (+7 more)

### Community 2 - "AST"
Cohesion: 0.08
Nodes (85): canonical_sha256(), analyst_schema(), _assert_nonimperative(), build_automatic_evaluation(), build_deterministic_baseline(), build_semantic_view(), _calculation_index(), critic_schema() (+77 more)

### Community 3 - "send_phase5r_c6_weekly_email.py"
Cohesion: 0.33
Nodes (5): Active boundary, Outcome, Phase 5R workspace cleanup manifest, Preservation layers, Reproducible clutter removed

### Community 4 - "test_phase5r_active_production.py"
Cohesion: 0.09
Nodes (54): acceptance_map(), fetch(), main(), Path, acceptance_index_failure_reason(), classify_materiality(), company_fundamentals_required(), count_unindexed_acceptance_accessions() (+46 more)

### Community 5 - "score_phase5r_b_candidates.py"
Cohesion: 0.07
Nodes (45): ExclusiveFileLock, Process lock using flock over a private, non-linked regular file., _append_execution_record(), assert_non_icloud_runtime_root(), _best_effort_failure_record(), _exec_scheduler(), _git(), inspect_runtime_repository() (+37 more)

### Community 6 - "phase5r_c9b_common.py"
Cohesion: 0.20
Nodes (17): main(), append_c9b_log(), execution_cash(), intraday_range_pct(), load_execution_rows(), optional_float(), parse_iso(), Path (+9 more)

### Community 7 - "main"
Cohesion: 0.14
Nodes (30): cycle_date(), easter_sunday(), expected_market_session(), is_us_market_session_date(), last_completed_market_session(), last_weekday(), latest_published_market_session(), log_daily_run() (+22 more)

### Community 8 - "iso_now"
Cohesion: 0.25
Nodes (15): csv_fields(), load_positions(), Path, write_csv(), write_text(), sha256(), main(), parse_args() (+7 more)

### Community 9 - "main"
Cohesion: 0.21
Nodes (16): due_slots(), main(), market_snapshot_mode(), _market_step_passed(), _massive_auth_presence_probe_exit_code(), datetime, Prove the B2 child can construct its client, without provider I/O., Run the approved official-evidence refresh without other daily steps. (+8 more)

### Community 10 - "PacketMarketObservationTests"
Cohesion: 0.29
Nodes (16): append_delivery(), build_message(), ConfigError, correction_eligibility(), cycle_is_blocked(), delivery_policy(), load_config(), main() (+8 more)

### Community 11 - "verify_phase5r_daily_upgrade.py"
Cohesion: 0.13
Nodes (19): line_excerpt(), main(), number(), Any, Path, Fail closed before producing a range, not merely before order routing., Match the packet clock's whole-second point-in-time precision., selected_band() (+11 more)

### Community 12 - "iso_now"
Cohesion: 0.18
Nodes (22): bool_value(), clear_automation_alert(), delivery_guard(), iso_now(), load_active_state(), load_inhibit(), publish_automation_alert(), Any (+14 more)

### Community 13 - "verify_phase5r_c6_weekly_email_boundary.py"
Cohesion: 0.15
Nodes (31): _canonical_sha256(), _declared_tickers(), _is_within(), load_valuation_input_bundle(), main(), _packet_as_of(), _parse_utc(), Any (+23 more)

### Community 14 - "score_phase5r_b2_candidates.py"
Cohesion: 0.15
Nodes (12): Phase 5R 决策分析结构摘要（供判断是否加入 LLM）, 一句话概括, 主要依据文件, 可直接交给 GPT 的评审提示词, 各层的实际职责, 如果加入 LLM，最合理的候选职责, 已有 LLM 试验事实, 希望独立评审回答的核心问题 (+4 more)

### Community 15 - "main"
Cohesion: 0.13
Nodes (18): classify_nonzero_exit(), cli_reported_token_usage(), CodexCliProvider, executable_sha256(), FixtureProvider, minimal_codex_environment(), ProviderResult, Any (+10 more)

### Community 16 - "phase5r_llm_contract.py"
Cohesion: 0.08
Nodes (53): _allowed_classifications_by_ticker(), _artifact_map(), build_packet(), _date_from_period(), _decimal(), _decision_tickers(), _effective_acceptance_map(), _entities() (+45 more)

### Community 17 - "verify_phase5r_daily_upgrade.py"
Cohesion: 0.13
Nodes (42): admit_unindexed_current_records(), _audit_row(), build_extension_artifact(), _core_record(), extension_acceptance_records(), extension_artifact_path(), _extension_number(), extension_set_sha256() (+34 more)

### Community 18 - "verify_phase5r_c5t_manual_action_boundary.py"
Cohesion: 0.12
Nodes (41): artifact_paths(), ArtifactError, atomic_write_bytes(), atomic_write_json(), build_chunks(), build_entry(), check_artifacts(), complete_cache_entry() (+33 more)

### Community 19 - "applied_reconciliation_matches_current_state"
Cohesion: 0.26
Nodes (6): applied_reconciliation_current_state_status(), applied_reconciliation_matches_current_state(), Classify whether a current C9 state remains consistent with one fill.      C9B r, Return the closed accepted subset of reconciliation-state statuses., C9BAccountSnapshotRefreshTests, _reconciliation()

### Community 20 - "phase5r_c9_common.py"
Cohesion: 0.15
Nodes (27): main(), create_if_missing(), main(), main(), _post_action_row(), main(), valuation_trim_review_required(), append_run_log() (+19 more)

### Community 21 - "PacketMarketObservationTests"
Cohesion: 0.16
Nodes (24): build_valuation_evidence_v1(), _calculation_receipt(), _InputSpec, _normalize_input(), _parse_decimal(), _parse_utc(), _payload_digest(), _plain_decimal() (+16 more)

### Community 22 - "_support.py"
Cohesion: 0.06
Nodes (17): ActiveConfigError, load_active_config(), main(), Any, Path, ValueError, Raised when the active configuration is unsafe or incomplete., notification_delivery_policy() (+9 more)

### Community 23 - "evaluate_phase5r_shadow_llm_incremental_value.py"
Cohesion: 0.06
Nodes (48): aggregate(), _atomic_private_snapshot_text(), _atomic_private_text(), _authority_checks(), _deduplicate_evidence(), _discover(), _evidence_keys(), load_automatic_bundle() (+40 more)

### Community 24 - "run_phase5r_daily_decision_pipeline.py"
Cohesion: 0.29
Nodes (10): _jsonl(), main(), _number(), Path, main(), number(), Any, Solve required revenue for explicit terminal-multiple/return sensitivities. (+2 more)

### Community 26 - "phase5r_portfolio_construction.py"
Cohesion: 0.19
Nodes (3): PacketMarketObservationTests, Path, write_csv()

### Community 27 - "next_thursday"
Cohesion: 0.80
Nodes (4): clamp(), main(), number(), selected_tickers()

### Community 28 - "verify_phase5r_c2_email_delivery_boundary.py"
Cohesion: 0.07
Nodes (44): acceptance_map(), AcceptanceIndexError, AcceptanceReconciliationError, build_acceptance_index(), load_acceptance_index(), load_acceptance_reconciliation_log(), load_immutable_acceptance_index(), make_acceptance_record() (+36 more)

### Community 34 - "ShadowLlmTests"
Cohesion: 0.32
Nodes (7): jsonl_count(), main(), Path, append_csv_durable(), atomic_write_json(), atomic_write_text(), Path

### Community 40 - "create_phase5r_c5_weekly_conviction_memo.py"
Cohesion: 0.17
Nodes (24): build_evidence_freshness_receipt(), EvidenceFreshnessError, freshness_action_review_reasons(), _normalize_bool(), _normalize_date(), _normalize_digest(), _normalize_source_ids(), _normalize_ticker() (+16 more)

### Community 51 - "phase5r_valuation_input_bundle.py"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 52 - "Scoring"
Cohesion: 0.29
Nodes (16): atomic_write_csv(), append_jsonl(), classification(), evaluate(), forecast_origin(), jsonl(), main(), number() (+8 more)

### Community 54 - "Phase 0C Reframe Plan"
Cohesion: 0.16
Nodes (10): MassiveB2AdapterResilienceTests, _payload(), The Basic delayed shape normalizes without leaking provider metadata., Ticker, adjustment, pagination, and malformed data each stop once., A provider 429 is one request and exposes neither URL detail nor key., Every new ticker is locally paced, while a failed request is never retried., Sanitized current Custom Bars shape, including optional metadata., The external-runtime key authorizes one request but never enters its URL/output. (+2 more)

### Community 62 - "Phase 0C Verification Report"
Cohesion: 0.16
Nodes (14): CanonicalWorkflowTests, _canonical_source_issues(), Check, collect_checks(), _deprecated_registry_issues(), _loaded(), main(), _plist_issues() (+6 more)

### Community 78 - "Early Public Equity Research"
Cohesion: 0.06
Nodes (67): api_key_from_environment(), _default_http_get(), _finite_number(), _http_failure_code(), MassiveB2Error, MassiveBasicEODClient, _NoRedirectHandler, _normalized_bars() (+59 more)

### Community 91 - "AGENTS.md"
Cohesion: 0.18
Nodes (10): Balance Sheet - 15 Points, Business Clarity - 15 Points, Catalyst And Timing - 10 Points, Growth Evidence - 15 Points, Interpretation, Liquidity And Tradability - 15 Points, Memo Rubric, Quality Of Evidence - 15 Points (+2 more)

### Community 92 - "Phase 5R-D3 Catch-up Scheduler Report"
Cohesion: 0.18
Nodes (10): Completed Phases, Current Fixtures, Next Phase, Phase 0A Audit, Phase 0B Hardening, Phase 1A Normalization, Phase 1B Dry Run, Phase 1C SEC Fetch (+2 more)

### Community 98 - "Phase 5R-B1 Data Readiness Report"
Cohesion: 0.18
Nodes (10): Balance Sheet - 15 Points, Business Clarity - 15 Points, Catalyst And Timing - 10 Points, Growth Evidence - 15 Points, Interpretation, Liquidity And Tradability - 15 Points, Memo Rubric, Quality Of Evidence - 15 Points (+2 more)

### Community 99 - "verify_source_integrity"
Cohesion: 0.18
Nodes (10): Completed Phases, Current Fixtures, Next Phase, Phase 0A Audit, Phase 0B Hardening, Phase 1A Normalization, Phase 1B Dry Run, Phase 1C SEC Fetch (+2 more)

### Community 101 - "Phase 5R-C3 Daily Email Pipeline Policy"
Cohesion: 0.25
Nodes (7): Active Workflow, Authority Order, Phase 5R-C8 Canonical Active-State Policy, Pipeline Requirement, Purpose, Safety Boundary, Stale-File Guard

### Community 105 - "Phase 5R-C5 Deep Research Policy"
Cohesion: 0.20
Nodes (9): Business Model Risk, Cash Runway Risk, Dilution Risk, Event Risk, Liquidity Risk, Red-Team Checklist, Sector-Specific Risk, Thesis Invalidation (+1 more)

### Community 106 - "Phase 5R-C5T Manual Action Policy"
Cohesion: 0.20
Nodes (9): 1. Universe, 2. Screening, 3. SEC Metadata, 4. GPT Packets, 5. Company Memo, 6. Red-Team Review, 7. Risk Calculation, 8. Journal And Review (+1 more)

### Community 117 - "Data Source Policy"
Cohesion: 0.20
Nodes (9): Business Model Risk, Cash Runway Risk, Dilution Risk, Event Risk, Liquidity Risk, Red-Team Checklist, Sector-Specific Risk, Thesis Invalidation (+1 more)

### Community 118 - "Source Policy"
Cohesion: 0.20
Nodes (9): 1. Universe, 2. Screening, 3. SEC Metadata, 4. GPT Packets, 5. Company Memo, 6. Red-Team Review, 7. Risk Calculation, 8. Journal And Review (+1 more)

### Community 122 - "._write_coherent_prior_outputs"
Cohesion: 0.11
Nodes (21): B2MarketRefreshFailureCommitTests, _candidate_row(), _CompleteCachedClient, _DuplicateSessionErrorClient, _FailingFullFetchClient, _market_row(), _PartialTwentyNineTickerClient, date (+13 more)

### Community 126 - "graphify reference: query, path, explain"
Cohesion: 0.22
Nodes (8): graphify reference: extra exports and benchmark, Step 6b - Wiki (only if --wiki flag), Step 7 - Neo4j export (only if --neo4j or --neo4j-push flag), Step 7a - FalkorDB export (only if --falkordb or --falkordb-push flag), Step 7b - SVG export (only if --svg flag), Step 7c - GraphML export (only if --graphml flag), Step 7d - MCP server (only if --mcp flag), Step 8 - Token reduction benchmark (only if total_words > 5000)

### Community 127 - "Source Policy"
Cohesion: 0.06
Nodes (30): Boundaries, Decision, Evidence, Future evaluation boundary, Phase 5R AI operating decision, Absolute-path audit, Failure behavior, Normal authoring and deployment (+22 more)

### Community 133 - "Phase 5R-B2 Data Source Decision"
Cohesion: 0.29
Nodes (6): Data Handling, Permitted Source and Scope, Phase 5R-B2 Full-Universe Data Policy, Purpose, Safety Boundary, Scoring

### Community 135 - "Phase 5R-C2 Gmail SMTP Setup"
Cohesion: 0.25
Nodes (7): Facts, Estimates, and Opinions, Long-Term Interpretation, Phase 5R Daily Research Policy, Principle, Refresh and Freshness Rules, Request Discipline, Source Hierarchy

### Community 145 - "Phase 5R-C4R Verification Report"
Cohesion: 0.25
Nodes (7): Boundaries, Core Workflow, Early Public Equity Research, References, Verification Commands, When To Stop, When To Use

### Community 147 - "Phase 5R-C5 Verification Report"
Cohesion: 0.25
Nodes (7): Account Scope, Hard Rules, Portfolio Risk, Position Risk, Review Cadence, Risk Limits, Risk Policy

### Community 163 - "Phase 5R-C2 Verification Report"
Cohesion: 0.25
Nodes (6): File Conventions, graphify, Non-Negotiable Constraints, Purpose, Research Standards, Script Safety

### Community 164 - "Phase 5R-C3 Pipeline Report"
Cohesion: 0.25
Nodes (7): Boundaries, Core Workflow, Early Public Equity Research, References, Verification Commands, When To Stop, When To Use

### Community 181 - "Phase 0A Canonical Project Structure Proposal"
Cohesion: 0.33
Nodes (5): Active Boundary, Decision Implications, Measurement Contract, Objective, Phase 5R Long-Horizon Return Objective Policy

### Community 182 - "Phase 0E Phase 5R Integrity Check"
Cohesion: 0.29
Nodes (6): Admission requirements, Boundaries, Commit and recovery behavior, Immutable historical layer, Phase 5R SEC Acceptance-Index Extension Policy v1, Versioned artifacts and audit

### Community 220 - "latest_phase5r_b2_manual_trade_tickets.md"
Cohesion: 0.33
Nodes (5): Canonical Inputs, Phase 5R-C9 Account-State Policy, Privacy and Execution Boundary, Runtime State, Validation

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
Cohesion: 0.25
Nodes (7): Boundaries, Duplicate Protection, Eligibility, Explicit correction resend, Frequency, Phase 5R Daily Delivery Policy, Refresh handoff and recovery

### Community 238 - "Phase 5R-D3G Hotfix Report"
Cohesion: 0.33
Nodes (5): Evidence Rules, Source Policy, Tier 1 Sources, Tier 2 Sources, Tier 3 Sources

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

### Community 259 - "Phase 5R-C9 Weekly Decision Summary"
Cohesion: 0.33
Nodes (5): Evidence Rules, Source Policy, Tier 1 Sources, Tier 2 Sources, Tier 3 Sources

### Community 285 - "test_refresh_phase5r_sec_filing_artifacts.py"
Cohesion: 0.50
Nodes (3): Cleanup boundary, Phase 5R-C8 verification report, Result

### Community 296 - "check_phase5r_llm_shadow_status.sh"
Cohesion: 0.40
Nodes (4): Allowed, Brokerage Boundary, Human Responsibility, Prohibited

### Community 297 - "install_phase5r_llm_shadow_scheduler.sh"
Cohesion: 0.40
Nodes (4): Approval Boundary, Manual Approval Policy, Out Of Scope, Required Before Approval

### Community 342 - "latest_phase5r_b_manual_trade_tickets.md"
Cohesion: 0.50
Nodes (3): Cash-Deployment Decision, Phase 5R-C9 Core Allocation Policy, Separation

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

### Community 414 - "_safe_failure_code"
Cohesion: 0.33
Nodes (12): add_check(), append_verification_log(), file_digest_or_absent(), loaded(), main(), plist_checks(), pure_guard_tests(), Path (+4 more)

## Knowledge Gaps
- **269 isolated node(s):** `activate_phase5r_daily_after_verification.sh script`, `check_phase5r_daily_scheduler_status.sh script`, `check_phase5r_shadow_llm_evaluation_scheduler.sh script`, `clear_phase5r_c9_maintenance_inhibit.sh script`, `install_phase5r_daily_schedulers.sh script` (+264 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **16 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `canonical_sha256()` connect `AST` to `run_phase5r_b2_full_universe_market_data.py`, `test_phase5r_active_production.py`, `main`, `iso_now`, `main`, `phase5r_llm_contract.py`, `verify_phase5r_daily_upgrade.py`, `Scoring`, `evaluate_phase5r_shadow_llm_incremental_value.py`, `run_phase5r_daily_decision_pipeline.py`, `verify_phase5r_c2_email_delivery_boundary.py`?**
  _High betweenness centrality (0.064) - this node is a cross-community bridge._
- **Why does `main()` connect `test_phase5r_active_production.py` to `ShadowLlmTests`, `AST`, `score_phase5r_b_candidates.py`, `main`, `iso_now`, `verify_phase5r_daily_upgrade.py`, `Scoring`, `verify_phase5r_c2_email_delivery_boundary.py`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Why does `ExclusiveFileLock` connect `score_phase5r_b_candidates.py` to `test_phase5r_active_production.py`, `main`, `PacketMarketObservationTests`, `iso_now`, `_safe_failure_code`?**
  _High betweenness centrality (0.026) - this node is a cross-community bridge._
- **Are the 46 inferred relationships involving `canonical_sha256()` (e.g. with `build_packet()` and `_fundamental_observations()`) actually correct?**
  _`canonical_sha256()` has 46 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `_execute_unlocked()` (e.g. with `canonical_sha256()` and `iso_now()`) actually correct?**
  _`_execute_unlocked()` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 19 inferred relationships involving `main()` (e.g. with `append_csv_durable()` and `atomic_write_csv()`) actually correct?**
  _`main()` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `RuntimeSyncError` (e.g. with `ExclusiveFileLock` and `LocalRepositoryFixture`) actually correct?**
  _`RuntimeSyncError` has 14 INFERRED edges - model-reasoned connections that need verification._