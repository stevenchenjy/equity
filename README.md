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

- Public market and SEC evidence refreshes run several times on weekdays.
- One decisive brief is eligible after 18:30 America/New_York on weekdays.
- Weekend briefs are suppressed unless an official material event, decision
  change, or account-state conflict appears.
- `phase5r-production-shadow-v1` is a conditional, noncanonical companion:
  after a fully passed deterministic refresh it may produce at most one
  evidence-bound AI research review per eligible trading day. It cannot change
  the deterministic decision, positions, risk state, or normal daily email.
- Daily analysis does not imply daily portfolio action.
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
  09_scripts/phase5r/verify_phase5r_production_shadow_readiness.py
```

These checks do not read SMTP configuration, send email, connect to a broker,
or create orders. The production-shadow readiness check also does not create a
provider client or probe credentials.
