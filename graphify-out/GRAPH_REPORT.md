# Graph Report - equity  (2026-09-01)

## Corpus Check
- 123 files · ~113,420 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1276 nodes · 2824 edges · 77 communities (67 shown, 10 thin omitted)
- Extraction: 84% EXTRACTED · 16% INFERRED · 0% AMBIGUOUS · INFERRED: 450 edges (avg confidence: 0.78)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `4ec88e56`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- phase5r_market_data_adapter.py
- run_phase5r_b2_full_universe_market_data.py
- AST
- send_phase5r_c6_weekly_email.py
- send_phase5r_c2_daily_email.py
- score_phase5r_b_candidates.py
- check_phase5r_b1_market_data_source.py
- main
- iso_now
- verify_phase5r_c6_weekly_email_boundary.py
- phase5r_llm_contract.py
- verify_phase5r_c5t_manual_action_boundary.py
- create_phase5r_c5_company_research_packets.py
- verify_phase5r_b2_read_only_boundary.py
- verify_phase5r_c2_email_delivery_boundary.py
- create_phase5r_c5_weekly_conviction_memo.py
- Phase 0B Migration Plan
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
- main
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
1. `main()` - 33 edges
2. `RuntimeSyncError` - 33 edges
3. `ExclusiveFileLock` - 28 edges
4. `iso_now()` - 24 edges
5. `read_json()` - 24 edges
6. `B2RefreshCadenceTests` - 23 edges
7. `cycle_date()` - 22 edges
8. `ExtensionValidationError` - 22 edges
9. `build_packet()` - 21 edges
10. `canonical_sha256()` - 21 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `atomic_write_csv()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `cycle_date()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `iso_now()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `last_completed_market_session()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py
- `main()` --calls--> `now_et()`  [INFERRED]
  09_scripts/phase5r/build_phase5r_current_research_baseline.py → 09_scripts/phase5r/phase5r_daily_common.py

## Import Cycles
- None detected.

## Communities (77 total, 10 thin omitted)

### Community 0 - "phase5r_market_data_adapter.py"
Cohesion: 0.25
Nodes (6): CacheTests, ledger_row(), NormalizationTests, Path, SelectionAndValidationTests, write_ledger()

### Community 1 - "run_phase5r_b2_full_universe_market_data.py"
Cohesion: 0.42
Nodes (10): action_stability(), execution_conflicts(), is_action_transition(), load_market_gate(), main(), material_events_for_cycle(), normalized_held_rows(), plain_action() (+2 more)

### Community 2 - "AST"
Cohesion: 0.33
Nodes (12): add_check(), append_verification_log(), file_digest_or_absent(), loaded(), main(), plist_checks(), pure_guard_tests(), Path (+4 more)

### Community 3 - "send_phase5r_c6_weekly_email.py"
Cohesion: 0.33
Nodes (5): Active boundary, Outcome, Phase 5R workspace cleanup manifest, Preservation layers, Reproducible clutter removed

### Community 4 - "send_phase5r_c2_daily_email.py"
Cohesion: 0.80
Nodes (4): clamp(), main(), number(), selected_tickers()

### Community 5 - "score_phase5r_b_candidates.py"
Cohesion: 0.07
Nodes (46): ExclusiveFileLock, Process lock using flock over a private, non-linked regular file., _append_execution_record(), assert_non_icloud_runtime_root(), _best_effort_failure_record(), _exec_scheduler(), _git(), inspect_runtime_repository() (+38 more)

### Community 6 - "check_phase5r_b1_market_data_source.py"
Cohesion: 0.07
Nodes (58): main(), create_if_missing(), main(), main(), main(), valuation_trim_review_required(), main(), append_run_log() (+50 more)

### Community 7 - "main"
Cohesion: 0.33
Nodes (10): delivery_status_is_unknown(), execute(), main(), _parse_aware_timestamp(), CompletedProcess, datetime, Require today's complete, current-session handoff before delivery., refresh_readiness() (+2 more)

### Community 8 - "iso_now"
Cohesion: 0.26
Nodes (16): atomic_write_csv(), iso_now(), append_jsonl(), classification(), evaluate(), jsonl(), main(), number() (+8 more)

### Community 13 - "verify_phase5r_c6_weekly_email_boundary.py"
Cohesion: 0.15
Nodes (31): _canonical_sha256(), _declared_tickers(), _is_within(), load_valuation_input_bundle(), main(), _packet_as_of(), _parse_utc(), Any (+23 more)

### Community 16 - "phase5r_llm_contract.py"
Cohesion: 0.06
Nodes (78): _allowed_classifications_by_ticker(), _artifact_map(), build_packet(), _date_from_period(), _decimal(), _decision_tickers(), _effective_acceptance_map(), _entities() (+70 more)

### Community 18 - "verify_phase5r_c5t_manual_action_boundary.py"
Cohesion: 0.15
Nodes (37): artifact_paths(), ArtifactError, atomic_write_bytes(), atomic_write_json(), build_chunks(), build_entry(), check_artifacts(), complete_cache_entry() (+29 more)

### Community 24 - "create_phase5r_c5_company_research_packets.py"
Cohesion: 0.07
Nodes (70): canonical_sha256(), admit_unindexed_current_records(), _audit_row(), build_extension_artifact(), _core_record(), extension_acceptance_records(), extension_artifact_path(), _extension_number() (+62 more)

### Community 27 - "verify_phase5r_b2_read_only_boundary.py"
Cohesion: 0.32
Nodes (6): jsonl_count(), main(), Path, atomic_write_json(), atomic_write_text(), Path

### Community 28 - "verify_phase5r_c2_email_delivery_boundary.py"
Cohesion: 0.07
Nodes (44): acceptance_map(), AcceptanceIndexError, AcceptanceReconciliationError, build_acceptance_index(), load_acceptance_index(), load_acceptance_reconciliation_log(), load_immutable_acceptance_index(), make_acceptance_record() (+36 more)

### Community 40 - "create_phase5r_c5_weekly_conviction_memo.py"
Cohesion: 0.17
Nodes (24): build_evidence_freshness_receipt(), EvidenceFreshnessError, freshness_action_review_reasons(), _normalize_bool(), _normalize_date(), _normalize_digest(), _normalize_source_ids(), _normalize_ticker() (+16 more)

### Community 48 - "Phase 0B Migration Plan"
Cohesion: 0.27
Nodes (14): easter_sunday(), expected_market_session(), is_us_market_session_date(), last_weekday(), nth_weekday(), observed(), date, datetime (+6 more)

### Community 51 - "phase5r_valuation_input_bundle.py"
Cohesion: 0.08
Nodes (24): For /graphify add and --watch, For /graphify query, For the commit hook and native CLAUDE.md integration, For --update and --cluster-only, /graphify, Honesty Rules, Interpreter guard for subcommands, Part A - Structural extraction for code files (+16 more)

### Community 52 - "Scoring"
Cohesion: 0.05
Nodes (36): ActiveConfigError, load_active_config(), main(), Any, Path, ValueError, Raised when the active configuration is unsafe or incomplete., line_excerpt() (+28 more)

### Community 54 - "Phase 0C Reframe Plan"
Cohesion: 0.16
Nodes (10): MassiveB2AdapterResilienceTests, _payload(), The Basic delayed shape normalizes without leaking provider metadata., Ticker, adjustment, pagination, and malformed data each stop once., A provider 429 is one request and exposes neither URL detail nor key., Every new ticker is locally paced, while a failed request is never retried., Sanitized current Custom Bars shape, including optional metadata., The external-runtime key authorizes one request but never enters its URL/output. (+2 more)

### Community 62 - "Phase 0C Verification Report"
Cohesion: 0.16
Nodes (14): CanonicalWorkflowTests, _canonical_source_issues(), Check, collect_checks(), _deprecated_registry_issues(), _loaded(), main(), _plist_issues() (+6 more)

### Community 78 - "Early Public Equity Research"
Cohesion: 0.06
Nodes (70): last_completed_market_session(), Return the most recent session that can safely be reused as a close.      This i, api_key_from_environment(), _default_http_get(), _finite_number(), _http_failure_code(), MassiveB2Error, MassiveBasicEODClient (+62 more)

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
Cohesion: 0.10
Nodes (18): Boundaries, Decision, Evidence, Future evaluation boundary, Phase 5R AI operating decision, Absolute-path audit, Failure behavior, Normal authoring and deployment (+10 more)

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

### Community 195 - "main"
Cohesion: 0.21
Nodes (17): bool_value(), clear_automation_alert(), delivery_guard(), load_active_state(), load_inhibit(), now_et(), publish_automation_alert(), Any (+9 more)

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
Cohesion: 0.29
Nodes (6): Boundaries, Duplicate Protection, Eligibility, Frequency, Phase 5R Daily Delivery Policy, Refresh handoff and recovery

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
Nodes (3): Cash-Deployment Approaches, Phase 5R-C9 Core Allocation Policy, Separation

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
Cohesion: 0.09
Nodes (17): append_audit(), as_float(), clamp(), main(), Path, read_csv(), score_row(), timestamp() (+9 more)

### Community 414 - "_safe_failure_code"
Cohesion: 0.26
Nodes (18): append_csv_durable(), cycle_date(), log_daily_run(), append_delivery(), build_message(), ConfigError, cycle_is_blocked(), delivery_policy() (+10 more)

## Knowledge Gaps
- **244 isolated node(s):** `activate_phase5r_daily_after_verification.sh script`, `check_phase5r_daily_scheduler_status.sh script`, `clear_phase5r_c9_maintenance_inhibit.sh script`, `install_phase5r_daily_schedulers.sh script`, `set_phase5r_c9_maintenance_inhibit.sh script` (+239 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `ExclusiveFileLock` connect `score_phase5r_b_candidates.py` to `AST`, `main`, `main`, `Phase 0B Migration Plan`, `create_phase5r_c5_company_research_packets.py`, `verify_phase5r_b2_read_only_boundary.py`, `_safe_failure_code`?**
  _High betweenness centrality (0.034) - this node is a cross-community bridge._
- **Are the 19 inferred relationships involving `main()` (e.g. with `append_csv_durable()` and `atomic_write_csv()`) actually correct?**
  _`main()` has 19 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `RuntimeSyncError` (e.g. with `ExclusiveFileLock` and `LocalRepositoryFixture`) actually correct?**
  _`RuntimeSyncError` has 14 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `ExclusiveFileLock` (e.g. with `main()` and `execute()`) actually correct?**
  _`ExclusiveFileLock` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `iso_now()` (e.g. with `main()` and `main()`) actually correct?**
  _`iso_now()` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 17 inferred relationships involving `read_json()` (e.g. with `_artifact_map()` and `build_packet()`) actually correct?**
  _`read_json()` has 17 INFERRED edges - model-reasoned connections that need verification._
- **What connects `activate_phase5r_daily_after_verification.sh script`, `check_phase5r_daily_scheduler_status.sh script`, `clear_phase5r_c9_maintenance_inhibit.sh script` to the rest of the system?**
  _360 weakly-connected nodes found - possible documentation gaps or missing edges._