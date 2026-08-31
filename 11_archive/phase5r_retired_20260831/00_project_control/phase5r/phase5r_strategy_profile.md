# Phase 5R Strategy Profile

Phase: `5R-A`  
System: realtime stock picker scaffold and dry-run system  
Execution model: manual execution only

## Objective

Phase 5R is a fresh stock-selection workflow for identifying high-liquidity technology and growth candidates for human review. It does not monitor existing holdings and does not use legacy IOT/RBRK real-position context.

The Phase 5R-A scaffold uses local/static placeholder market data only. Live data, APIs, broker connectivity, order routing, email automation, and real execution are outside this phase.

## Allowed Themes

- Technology
- AI infrastructure
- Semiconductors
- Cybersecurity
- Cloud software
- Data centers
- High-liquidity growth stocks
- Benchmark ETFs: QQQ, XLK, SPY

## Exclusions

- IOT and RBRK are excluded because they are legacy holding context.
- Real-position logs, weekly real-position reviews, email draft workflows, and trade logs are excluded.
- Optional review items from Phase 0C are not used in Phase 5R-A:
  - `03_research/company_memo_template.md`
  - `05_scripts/risk_calculator.py`

## Signal Model

Phase 5R-A uses deterministic dry-run placeholders:

```text
total_score =
  0.30 * trend_score +
  0.25 * volume_score +
  0.20 * catalyst_score +
  0.15 * quality_score -
  0.10 * risk_penalty
```

Action labels:

- `possible_buy_manual_review`: high dry-run score; human can inspect a manual ticket.
- `watch`: reasonable setup but not urgent.
- `avoid`: weak or risky placeholder setup.
- `insufficient_data`: missing placeholder values.

## Position Sizing Guardrail

Each universe row has `max_position_pct`. Manual tickets can suggest a smaller position, but scripts cannot authorize a real order. Every manual ticket must state:

- `manual_confirmation_required = yes`
- `broker_connection_allowed = no`
- `real_order_allowed_by_script = no`
- `old_holding_data_used = no`

## Manual-Execution Boundary

Phase 5R-A can produce watchlists and manual tickets. It cannot:

- Connect to a broker.
- Place or route orders.
- Read credentials or `.env` files.
- Use API keys.
- Send emails.
- Automate execution.
- Use legacy IOT/RBRK holding data.
