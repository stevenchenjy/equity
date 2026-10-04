# AGENTS.md

Guidance for AI assistants and scripts working inside this project.

## Purpose

This repo is for education, research, risk calculation, and journaling only. It supports a small cash-account portfolio. Current account value must be derived from the approved private account record and shares at current canonical prices, never from a descriptive scale or an older chat summary.

Codex may prepare research, calculate risk, screen a local watchlist, summarize filings, draft memos, and create trade plans for human review. Codex may not execute trades.

## Non-Negotiable Constraints

- No live trading.
- No brokerage API integration.
- No credential storage.
- No bank, debit card, credit card, password, API key, or broker login handling.
- No automatic trade execution.
- No margin.
- No options.
- No short selling.
- OTC penny stocks are out of scope.
- Every real trade requires human approval outside this repo before any action is taken.
- Do not issue buy or sell commands.
- Do not place trades.

## Research Standards

- Prefer SEC filings, company investor relations, exchange filings, FDA pages, official government sources, audited statements, and other primary sources.
- Use reliable financial sources as secondary context only.
- Treat social media, forums, blogs, promotional newsletters, and influencer posts as weak evidence unless confirmed by primary sources.
- Keep facts, estimates, and opinions separate.
- Explain uncertainty clearly.
- Use the labels `reject`, `watchlist`, `paper trade candidate`, or `real-trade candidate`.
- A real-trade candidate label is not approval to trade.

## Owner-Requested Reviews and Email

- Read `00_project_control/owner_review_preferences.md` before handling an owner-requested portfolio recheck, redo, or research email.
- Each explicit request to redo/recheck includes standing authorization to send that completed review once to the existing configured recipient, even if the scheduled report is unchanged. Use the audited owner-review delivery mode; never falsify normal send eligibility or claim inbox delivery from SMTP acceptance alone.
- The owner uses the Chase app. Give dated, broker-appropriate, conditional human-review order drafts with quantities, prices, order type, time in force, invalidation and rationale; do not place orders or treat a draft as execution authorization.

## File Conventions and Checkout Boundaries

- Author code in `/Users/messssi/Desktop/equity`; production runs from
  `/Users/messssi/LocalRuntime/equity`. `Documents/equity` holds audit artifacts.
  Verify branch, HEAD, dirty state and runtime timestamps before using a report.
- Read `00_project_control/current_documents.md` for current authority and
  `00_project_control/repository_layout.md` for directory roles and path owners.
- Active Python source/tests: `09_scripts/equity_research/`; dashboard:
  `10_dashboard/`. Keep the established wrappers; do not create `03_research/`,
  `06_trading/`, `07_reviews/` or `05_scripts/` compatibility directories.
- Tracked configuration: `00_project_control/active_*`, registries and
  `01_policies/`. Tracked source evidence: `02_filings/issuer_filings/` and
  admitted ledgers/acceptance extensions in `03_source_data/equity_research/`.
- Private valuation inputs: `04_data/equity_research/`; maintained dossiers and
  generated company decisions: `04_research/company_research/`. Account truth
  and plans: `05_risk_and_positions/`; manual execution evidence:
  `06_execution_records/`. Examples/templates never establish account truth.
- Runtime reports: `08_reviews/`; briefs/delivery evidence: `07_automation/`;
  locks/logs: `00_project_control/run_logs/`. Sparse Git directories are
  intentional runtime namespaces. Check `.gitignore` before adding artifacts;
  private history and retained source receipts are not disposable caches.
- Dated implementation records belong in `11_archive/`; keep maintained policy
  in the current-document index. Git-recoverable retired code uses a pointer
  and verified recovery manifest. Never execute archived commands as current.
- Frozen momentum versions use `01_policies/momentum_implementation_archives.json`
  and their registered Git commits. Preserve private observations, inputs,
  hashes and version identity; do not refactor frozen dependencies for aesthetics.
- Retain Graphify navigation artifacts; query before architecture searches and
  run `graphify update .` after changes. Do not hand-edit graph relationships.

## Script Safety

- Scripts must remain readable and offline-first where practical.
- Scripts must not place orders or connect to a brokerage.
- Scripts must not store credentials.
- Network use is allowed only for public research sources, such as SEC endpoints, and should be explicit in script arguments or comments.
- Scripts must not add live trading, margin, options, short selling, or broker API functionality.

## Completion evidence for pipeline changes

- Before using an audit, status summary, plan, handoff, or generated report to
  make a current decision, verify its dated claims against the current branch
  and HEAD, working tree, relevant files, runtime timestamps and relevant
  checks. Treat older reports as snapshots; use `00_project_control/current_documents.md`
  to locate maintained guidance and current runtime outputs. File modification
  time alone does not establish freshness.

- Verify a reported fault across its real path: retained input, derived decision,
  final text/HTML, deployment commit and delivery receipt when relevant. A
  passing suite or successful refresh alone does not establish factual accuracy.
- Add a regression that fails on the observed defect and test material countercases.
  Preserve exact private sent inputs; do not overwrite history to make it agree.
- Report separately what was coded, tested, deployed, recomposed and actually
  delivered. Never describe a preview or queued research item as a completed send
  or analytical conclusion. Distinguish processed dossiers, new financial fields,
  recorded assessments and investment-performance evidence.
- Recurring analyst work follows `00_project_control/analyst_followthrough.md`.
  A scheduled analyst wake is not an explicit owner-requested email resend.
- Interactive reviews that change maintained plans must pass the durable
  writer and final recomposition checks in `owner_review_preferences.md`.
  An emailed narrative is not proof that the ongoing plan store changed.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

When the user types `/graphify`, use the installed graphify skill or instructions before doing anything else.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- Dirty graphify-out/ files are expected after hooks or incremental updates; dirty graph files are not a reason to skip graphify. Only skip graphify if the task is about stale or incorrect graph output, or the user explicitly says not to use it.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
