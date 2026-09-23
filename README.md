# Equity Research

Educational research workspace for a small cash-account portfolio currently operating at approximately the $3,000 scale. Current value is never hard-coded: production derives it from manually maintained cash and shares valued at the canonical public close.

Display names and report branding come from [the shared display configuration](01_policies/equity_display_names.json).
[The naming policy](00_project_control/equity_naming_policy.md) uses stable functional names; existing `phase5r` paths and schemas remain compatibility identifiers.

## Repository Paths

The iCloud authoring/reference path is:

```text
/Users/messssi/Desktop/equity
```

The Mac mini production scheduler path is outside iCloud:

```text
/Users/messssi/LocalRuntime/equity
```

Code flows from an authoring commit through GitHub `main` to the Mac mini
runtime clone. The LaunchAgents never execute from Desktop. See
[`00_project_control/macbook_github_macmini_workflow.md`](00_project_control/macbook_github_macmini_workflow.md)
for the synchronization, lock, failure, and operator procedures.

## Current Workflow

The active workflow is `daily_decision` and the only active email pipeline is
`phase5r_daily`.

- Public market and SEC evidence refreshes run in the next-day Basic EOD
  publication window, with bounded retries from 11:15 through 12:45 ET.
- One decisive brief is eligible after 13:30 America/New_York only for a
  material change. The Friday-close weekly summary is delivered on Saturday,
  after that close is published. Unchanged ordinary email is suppressed.
- Newly added research tickers retain their complete SEC backfill, but only
  newly discovered material filings dated within seven calendar days can
  trigger an event alert; historical backlog never creates an email burst.
- Weekend briefs are suppressed unless an official material event, decision
  change, or account-state conflict appears.
- The production AI operating decision remains
  [`00_project_control/ai_operating_decision.md`](00_project_control/ai_operating_decision.md):
  AI is excluded from active production. The old `0/10` and `$0` figures refer
  only to the retired August 31 commissioning record, not current evaluation
  usage. A separate event-driven, noncanonical
  [`SHADOW_LLM evaluation`](08_reviews/shadow_llm/README.md) is authorized
  outside the production path. Its output cannot affect a decision, email,
  account, position, scheduler result, or order.
- Daily analysis does not imply daily portfolio action.
- Current research packets are regenerated from the latest close published by
  the active Basic EOD provider and current SEC evidence; the historical C5
  narrative is not a production input.
- Source-bound bear/base/bull valuations and whole-share sizing are computed
  deterministically only when the required inputs and provenance are complete;
  `insufficient` is not a completed valuation. Scenario gaps are conditional
  arithmetic, not probability-weighted expected returns. Recommendation
  snapshots are tracked from a subsequent observed close over 1, 5, 20, and
  60 market sessions against SPY and QQQ; overlapping rows are not independent
  samples and price returns are not dividend-adjusted total returns.
- A held stock above the default single-stock cap can open a human trim review
  only when complete valuation is adverse on all three scenarios, expected
  upside is nonpositive, and reward/risk is below one. This never executes.
- HOLD, WATCH, and NO NEW POSITION need no manual confirmation. Any proposed
  portfolio change remains research for independent human review and can never
  execute automatically.

## Long-horizon workflow upgrade (2026-09-20)

The implementation plan is [the four-standard improvement plan](00_project_control/workflow_improvement_plan_20260920.md).
Low technical scores request research instead of independently proposing a full exit. A sourced, reviewed thesis break or the existing concentration rules governs action review. An unassessed material filing receives neutral catalyst credit. Candidate stability is tracked per ticker and counts distinct valid closes; ordinary quote updates do not reset it.

The daily pipeline builds a fundamentals-led research queue alongside the existing price-based queue, source-bound company research, explicit 3-/5-year equity cash-flow sensitivities and 2x/3x hurdle arithmetic. Conditional sensitivities are not forecasts or canonical price targets. Unresolved business evidence is labeled pending research.

Market context changes the confirmation pace for new-capital research: two confirmed broad stress closes require three distinct confirmation closes; three normal closes restore the usual two. It never changes approved caps, reserves or strategic targets, and does not independently generate exits.

Official issuer news for IOT, RBRK and NVDA is checked at 08:15, 11:15, 16:45 and 20:15 ET through the existing serialized refresh scheduler. This cadence is independent of EOD completion. Public RSS failures preserve prior events while showing failed/stale coverage; no news event is assumed positive. Existing change-only delivery preferences remain in force; a raw announcement alone is not an instruction or a new email entitlement. Runtime status reports transport health, research gaps and news coverage separately.

Current additional reports in the runtime clone:

- `08_reviews/current/long_horizon_research.local.md`
- `08_reviews/current/market_regime.local.md`
- `03_source_data/equity_research/official_news_status.local.json`

## Safety Boundaries

- No live trading.
- No brokerage API integration.
- No broker credential handling.
- No bank, debit card, credit card, password, API key, token, or cookie handling.
- No margin, options, short selling, OTC penny stocks, or automatic execution.
- Every real trade requires human approval outside this repo.

## What The System Can Do

- Maintain a local research universe.
- Screen the universe for basic red flags.
- Download public SEC filing metadata.
- Calculate educational position size and risk.
- Draft company memos, red-team notes, daily decisions, and periodic reviews.
- Journal paper trades and human-approved real trade plans.

## What The System Cannot Do

- Execute trades.
- Connect to a brokerage.
- Store sensitive credentials or payment information.
- Replace human judgment or approval.
- Treat social media, forums, blogs, or influencer posts as strong evidence without primary-source confirmation.

## Current Safe Status Commands

Run production status checks from the Mac mini runtime path:

```bash
cd /Users/messssi/LocalRuntime/equity
/bin/zsh 07_automation/scheduler/check_daily_scheduler_status.sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/equity_research/run_runtime_scheduler.py --job dailyrefresh --safe-check
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/equity_research/run_runtime_scheduler.py --job dailydecision --safe-check
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/equity_research/generate_current_status.py
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/equity_research/run_active_tests.py
```

These checks do not read SMTP configuration, send email, invoke a model,
connect to a broker, or create orders.

The separate SHADOW_LLM preflight is also read-only and does not invoke a
model:

```bash
python3 09_scripts/equity_research/run_shadow_llm_evaluation.py --check
python3 09_scripts/equity_research/run_shadow_llm_evaluation.py --preflight
```

`--auto-live` evaluates only a previously unattempted research-semantic event;
ordinary market-price, timestamp, and account churn is skipped without a model
call. The separate evaluator aggregates blind-judge results without requiring
the owner to label every run. See the SHADOW_LLM README for bounded replay,
cost-accounting, threshold, and evaluation-only LaunchAgent commands. This
surface remains absent from all production schedulers and entrypoints.

The single active configuration is
[`00_project_control/active_production_config.json`](00_project_control/active_production_config.json).
The [current-document index](00_project_control/current_documents.md)
identifies authoritative configuration, live generated reports, and dated
historical assessments. Runtime-generated status is authoritative for current
operations; an old authoring-clone report is not a runtime status check. Retired
material is isolated under `11_archive/phase5r_retired_20260831/`; the complete
pre-cleanup workspace is recoverable from tag `phase5r-pre-cleanup-20260831`.

After a manual trade or cash change, preview the entire confirmed position set
and cash balance. Do not copy historical account numbers from documentation.
Inspect the command interface first:

```bash
python3 09_scripts/equity_research/update_manual_account.py --help
```

Use `--preview` with confirmed inputs and `--apply` only after checking the
aggregates. This command reads no broker and creates no order.
