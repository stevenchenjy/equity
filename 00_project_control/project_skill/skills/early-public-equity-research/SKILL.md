---
name: early-public-equity-research
description: Use this skill to run a human-approved research workflow for publicly traded early-stage growth companies, recent IPOs, AI infrastructure, clean tech, biotech, semiconductors, and software infrastructure. It supports universe screening, SEC filing review, GPT packet creation, company memo preparation, red-team review, risk calculation, journaling, and weekly review. It never places trades or connects to brokerage accounts.
---

# Early Public Equity Research

Use this project-local skill for the `/Users/messssi/Desktop/equity` research workflow. It is for education, research, risk calculation, journaling, and review only.

## When To Use

- Adding candidate tickers.
- Reviewing SEC filings.
- Generating GPT packets.
- Preparing company memos.
- Red-teaming a thesis.
- Checking position risk.
- Preparing weekly reports.
- Moving from test fixtures to a real research universe.

## When To Stop

Stop and do not proceed when the request includes:

- Any request to connect to a brokerage account.
- Any request to place, submit, modify, cancel, or route an order.
- Any request to store broker, bank, debit card, credit card, password, API key, token, cookie, or login information.
- Any request for margin, options, short selling, or automatic trading.
- Any trade thesis supported only by social media, forums, blogs, or influencer posts.
- Missing SEC or official source support.
- Missing company memo.
- Missing red-team note.
- Missing risk calculation.

## Core Workflow

1. Update `01_universe/universe.csv` with sourced candidate rows.
2. Run `05_scripts/screen_universe.py`.
3. Fetch public SEC metadata with `05_scripts/update_sec_filings.py`.
4. Review generated filing notes in `02_filings/filing_notes/`.
5. Generate GPT packets with `05_scripts/make_gpt_packet.py`.
6. Prepare a company memo in `03_research/`.
7. Prepare a red-team review before any paper-trade planning.
8. Run `05_scripts/risk_calculator.py` only for approved paper-trade planning.
9. Update the paper-trade journal when appropriate.
10. Run `05_scripts/make_weekly_report.py`.

## Verification Commands

Run commands from `/Users/messssi/Desktop/equity`.

```bash
python3 tests/smoke_tests.py
python3 05_scripts/screen_universe.py
python3 05_scripts/make_gpt_packet.py
python3 05_scripts/make_weekly_report.py
python3 05_scripts/risk_calculator.py --account-value 2000 --risk-percent 1 --entry-price 20 --stop-price 18
```

## References

- Read `references/workflow.md` when running or modifying the end-to-end workflow.
- Read `references/source_policy.md` when judging source quality.
- Read `references/red_team_checklist.md` before red-teaming a thesis.
- Read `references/memo_rubric.md` before scoring a company memo.
- Read `references/phase_status.md` when orienting to project history and current readiness.

## Boundaries

- No buy/sell recommendations.
- No real trade recommendations.
- No brokerage connection.
- No credential handling.
- No paid APIs.
- No automatic trading.
- Human approval is required outside this repo for any real order.
