# Workflow reliability and performance evidence

`create_workflow_evaluation.py` produces the private current evaluation report. It does not increase research authority, create recommendations, send mail, modify account state, or connect to a broker.

## Operational measurement

The engineering readiness target is 13:30 ET, after the existing provider publication retry window. It is not a provider SLA. Report calendar research cycles separately from exchange sessions because the scheduler also runs on weekends. Count missing calendar cycles inside the retained window; leave the current cycle pending before its deadline. An eventual recovery does not become an on-time success. Preserve an unresolved delivery terminal even if data extraction later succeeds.

New completed refresh records append to `00_project_control/run_logs/refresh_history.local.jsonl` with run timestamps, finite result codes, and per-step timing. Repeating the same cycle/start timestamp does not create another measured run. Historical per-step durations remain unavailable. Runtime preflight failures are summarized by bounded reason codes, without copying external command diagnostics or credentials into the report.

## Recommendation evaluation

Immutable recommendation snapshots retain plan and thesis identifiers/versions, when supplied by the canonical decision. Older snapshots are never retrospectively assigned a thesis or plan that was not available at their creation.

The first eligible forecast origin is a subsequent exchange-session close after the aware creation date. Missing exchange-session data cannot compress a horizon. One ticker/origin price path is counted once per horizon, across repeat reports and candidate/held roles. Report 1-, 5-, 20-, and 60-session coverage and pending data separately. Completed review meetings are not inferred by dividing snapshot counts by ten. The same names across days and overlapping horizons remain correlated; these are not independent statistical trials.

Price-path returns are not executed portfolio returns. They exclude execution costs and dividends and remain subject to corporate-action review. Benchmark price-path comparisons require an explicitly matching provider price basis at both endpoints. They do not become total-return comparisons.

## Confirmed actual account observations

A separate append-only private ledger, `05_risk_and_positions/performance_observations.local.jsonl`, stores actual broker NAV observations, confirmed external deposits/withdrawals, and explicit interval-history reviews. It never imports the planning account's assumed cash. Each record has its own immutable ID, source reference and SHA-256, confirmation identity/time, and a hash-chain binding. Repeated identical IDs deduplicate. Conflicting facts require a new correction referencing `supersedes_record_id`; historical records remain intact, and interval reviews referring to superseded observations become unresolved until reviewed again. Source transaction IDs prevent the same external flow from being recorded under new IDs.

Preview a prepared JSON record without changing the ledger:

```bash
python3 09_scripts/equity_research/create_workflow_evaluation.py --record /absolute/private/record.json
```

Apply a reviewed record to the private ledger:

```bash
python3 09_scripts/equity_research/create_workflow_evaluation.py --record /absolute/private/record.json --apply
```

The CLI verifies that the local source file matches the declared hash. It does not assert the source's historical completeness. Observations require an aware timestamp, USD currency, `cash_basis: broker_observed_actual`, `complete_account: true`, actual cash plus securities reconciling to NAV, and `valuation_basis: broker_intraday` or `broker_close`. An intraday snapshot containing unsettled proceeds describes account equity, not withdrawable cash.

External flow records require `transaction_id`, aware `occurred_at`, signed `amount`, `flow_type: deposit` or `withdrawal`, and `status: posted_confirmed`. Trades, internal cash sweeps, dividends, and fees are not external flows.

An `interval_review` references `start_nav_id`, `end_nav_id`, an exhaustive `external_flow_ids` list (including an explicit empty list), and three independent booleans:

- `cash_flow_history_complete`
- `holdings_history_reconciled`
- `fees_income_corporate_actions_reconciled`

False confirmations remain visible blockers. No interval return is computed until all are true, both NAV observations are current and share a valuation basis, and recorded flows reconcile exactly. The method is an explicitly labeled Modified Dietz cash-flow-adjusted approximation. Deposits and withdrawals change contributed capital rather than becoming investment gains or losses. Net expenses, income and corporate actions must already be reconciled in actual NAV. Individual valid intervals are not automatically chain-linked or represented as lifetime performance.

Portfolio benchmark comparison remains unavailable unless both NAV records include sourced total-return index observations for the same benchmark at their exact NAV timestamps. Unadjusted public closes and mismatched intraday timestamps are insufficient. Historical holdings and cashflow completeness are a data-acquisition task, not something that passing software tests can supply.
