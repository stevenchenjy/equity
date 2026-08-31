# Early Public Equity Lab

Educational research workspace for a $2,000 cash-account learning portfolio focused on publicly traded early-stage growth companies, recent IPOs, AI infrastructure, clean tech, and biotech.

## Active Path

The active project path is:

```text
/Users/messssi/Desktop/equity
```

During Phase 0A, `/Users/messssi/Documents/equity` was not found. Future commands and prompts should use the Desktop path above.

## Current Phase

Phase 0B + Phase 1A: harden the scaffold, normalize CSV schemas, add safety policies, and prepare for a Phase 1 research dry run.

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
- Draft company memos, red-team notes, trade plans, and weekly reviews.
- Journal paper trades and human-approved real trade plans.

## What The System Cannot Do

- Execute trades.
- Connect to a brokerage.
- Store sensitive credentials or payment information.
- Replace human judgment or approval.
- Treat social media, forums, blogs, or influencer posts as strong evidence without primary-source confirmation.

## Safe Example Commands

Run from the active project path:

```bash
cd /Users/messssi/Desktop/equity
python3 05_scripts/risk_calculator.py --account-value 2000 --risk-percent 1 --entry-price 20 --stop-price 18
python3 05_scripts/screen_universe.py
python3 05_scripts/make_weekly_report.py
python3 tests/smoke_tests.py
```

SEC metadata command example:

```bash
python3 05_scripts/update_sec_filings.py AAPL
```

The SEC script uses public SEC endpoints only and does not use broker APIs.
