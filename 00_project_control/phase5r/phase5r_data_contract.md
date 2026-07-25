# Phase 5R Data Contract

Phase: `5R-A`  
Scope: local/static dry-run files only

## Dependency Boundary

Phase 5R-A reads `00_project_control/phase0c_phase5r_dependency_allowlist.csv` to verify the approved dependency set. It does not read legacy real-position files, trade logs, email workflow files, or `.env` files.

## Universe Seed

File: `04_data/phase5r_universe_seed.csv`

Required columns:

- `ticker`
- `company_name`
- `sector`
- `industry`
- `theme`
- `liquidity_tier`
- `volatility_tier`
- `is_benchmark`
- `max_position_pct`
- `notes`

Constraints:

- `ticker` must be unique.
- `IOT` and `RBRK` must be absent.
- `is_benchmark` must be `yes` or `no`.
- `max_position_pct` is an informational manual-review cap, not an executable sizing instruction.

## Dry-Run Candidates

File: `04_data/phase5r_dry_run_candidates.csv`

Required columns:

- `ticker`
- `company_name`
- `theme`
- `price_placeholder`
- `intraday_change_pct_placeholder`
- `relative_volume_placeholder`
- `dollar_volume_placeholder`
- `trend_score`
- `volume_score`
- `catalyst_score`
- `quality_score`
- `risk_penalty`
- `total_score`
- `action_label`

Constraints:

- Placeholder fields are static local values.
- No network calls are allowed in Phase 5R-A.
- `total_score` must use the Phase 5R formula.

## Signal Scores

File: `04_data/phase5r_signal_scores.csv`

The score file preserves the candidate signal components, formula version, rank, and score explanation. It is used for watchlist display and manual ticket generation.

## Manual Trade Tickets

File: `04_data/phase5r_manual_trade_tickets.csv`

Required columns:

- `ticker`
- `action_label`
- `entry_zone_reference`
- `invalidation_reference`
- `stop_reference`
- `take_profit_reference`
- `suggested_position_pct`
- `max_loss_pct_of_account`
- `reason`
- `risks`
- `manual_confirmation_required`
- `broker_connection_allowed`
- `real_order_allowed_by_script`
- `old_holding_data_used`

Required constants:

- `manual_confirmation_required = yes`
- `broker_connection_allowed = no`
- `real_order_allowed_by_script = no`
- `old_holding_data_used = no`

## Audit Trail

File: `04_data/phase5r_audit_trail.csv`

Each Phase 5R-A script appends a local audit row describing the script name, action, inputs, outputs, and safety status. This audit trail is not a trade log.
