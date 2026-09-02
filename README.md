# Early Public Equity Lab

Educational research workspace for a $2,000 cash-account learning portfolio focused on publicly traded early-stage growth companies, recent IPOs, AI infrastructure, clean tech, and biotech.

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
[`00_project_control/phase5r_macbook_github_macmini_workflow.md`](00_project_control/phase5r_macbook_github_macmini_workflow.md)
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
- The current AI operating decision is
  [`00_project_control/phase5r_ai_operating_decision.md`](00_project_control/phase5r_ai_operating_decision.md):
  AI is removed from active production at `0/10` real observations and `$0`
  spend. Historical model code and evidence are archived; production performs
  no model credential lookup or provider call.
- Daily analysis does not imply daily portfolio action.
- Current research packets are regenerated from the latest close published by
  the active Basic EOD provider and current SEC evidence; the historical C5
  narrative is not a production input.
- Source-bound bear/base/bull valuations and whole-share sizing are computed
  deterministically. Recommendation snapshots are evaluated after 1, 5, 20,
  and 60 market sessions against SPY and QQQ.
- A held stock above the default single-stock cap can open a human trim review
  only when complete valuation is adverse on all three scenarios, expected
  upside is nonpositive, and reward/risk is below one. This never executes.
- HOLD, WATCH, and NO NEW POSITION need no manual confirmation. Any proposed
  portfolio change remains research for independent human review and can never
  execute automatically.

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
/bin/zsh 07_automation/scheduler/check_phase5r_daily_scheduler_status.sh
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/phase5r/run_phase5r_runtime_scheduler.py --job dailyrefresh --safe-check
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/phase5r/run_phase5r_runtime_scheduler.py --job dailydecision --safe-check
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/phase5r/generate_phase5r_current_status.py
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  09_scripts/phase5r/run_phase5r_active_tests.py
```

These checks do not read SMTP configuration, send email, invoke a model,
connect to a broker, or create orders.

The single active configuration is
[`00_project_control/phase5r_active_production_config.json`](00_project_control/phase5r_active_production_config.json).
The generated current status is
`00_project_control/phase5r_current_production_status.local.md`. Retired
material is isolated under `11_archive/phase5r_retired_20260831/`; the complete
pre-cleanup workspace is recoverable from tag `phase5r-pre-cleanup-20260831`.

After a manual trade or cash change, preview and then explicitly apply the
entire current position set in one command:

```bash
python3 09_scripts/phase5r/update_phase5r_manual_account.py \
  --cash 1900 --position IOT=4@36.44 --position RBRK=2@84.40 --preview
```

Replace `--preview` with `--apply` only after checking the aggregates. This
command reads no broker and creates no order.
