# Phase 5R Manual Execution Boundary

Phase 5R-A is manual-execution-only.

## Allowed

- Create a fresh stock-selection universe.
- Use local/static placeholder market data.
- Generate dry-run scores.
- Generate watchlists.
- Generate manual review tickets.
- Read the Phase 0C dependency allowlist.

## Not Allowed

- Broker connectivity.
- Order placement.
- Order-routing code.
- API keys or credential access.
- Reading `.env` files.
- Email sending or email automation.
- Automated execution.
- Use of old IOT/RBRK holding data.
- Dependency on real-position logs, weekly real-position reviews, email drafts, or trade logs.

## Manual Ticket Semantics

A manual ticket is a human-review artifact. It is not an order, not an instruction to a broker, and not an automated execution request.

Every ticket must include:

- `manual_confirmation_required = yes`
- `broker_connection_allowed = no`
- `real_order_allowed_by_script = no`
- `old_holding_data_used = no`

## Phase 5R-A Data Source Rule

All market values in Phase 5R-A are placeholder values stored directly in the new scaffold scripts. They are for pipeline validation only and are not live market data.
