# Phase 5R-C9A Account-State and Stale-Denominator Audit Policy

## Status

Phase 5R-C9A is a planning and safety phase. It does not implement C9 financial calculations, regenerate portfolio outputs, change positions, or authorize a transaction.

## Purpose

The active weekly-conviction workflow was built around a `1000 USD` account assumption. An additional `1500 USD` of investable cash makes `2500 USD` the proposed future account total. Until a human-confirmed account-state file exists, `2500 USD` is a proposal rather than an active calculation input.

C9A identifies every active path that contains or inherits the old denominator and prevents unattended C7/C6 delivery while those dependencies are migrated.

## Audit Scope

- Read the active-decision state before other active inputs.
- Inspect every minimum file named in the C9A brief.
- Expand the scan to C4/C4R outputs, C5 queue and packet generation, C5T support outputs, C6 HTML/preview/report artifacts, and C7 status outputs.
- Treat `05_risk_and_positions/current_positions.local.csv` as read-only.
- Treat archived legacy folders as prohibited financial inputs.
- Inspect D3 launchd state and delivery/log counts without reading SMTP configuration contents.

## C9A Boundaries

C9A may create audit, migration, supersession, verification, and scheduler-inhibit artifacts. It may make the minimum D3 guard change required to honor the inhibit.

C9A must not:

- run C7 or the C6 sender;
- send email;
- connect to a broker or create order code;
- change `current_positions.local.csv`;
- change or print SMTP configuration or credentials;
- use archived legacy folders as financial inputs;
- calculate or publish C9 weights, cash deployment, share scenarios, or recommendations;
- clear the C9 maintenance inhibit.

## Audit Rules

1. Stored `position_pct` is historical/reference data, not current truth for C9.
2. Any output derived from `29.59%`, `17.75%`, `47.34%`, or a `1000 USD` denominator is stale for current portfolio decisions.
3. The `30%`, `8%`, and `6%` policy thresholds are not themselves stale. Dollar/share scenarios and action labels calculated against those thresholds with the old denominator are stale.
4. Public company evidence and the canonical B2 market-data pipeline can remain research inputs. Portfolio-fit fields, concentration wording, and recommendation labels embedded in mixed research artifacts must be regenerated.
5. Historical logs are preserved as records and are never promoted to current financial inputs.
6. C9 activation must be atomic from the workflow's perspective: account input, recalculation, downstream regeneration, validation, active-state update, and only then inhibit clearance.

## C9A Pass Condition

C9A passes when the required reports exist, the local inhibit is active and gitignored, D3 logs `maintenance_inhibit` without invoking C7, all minimum files are recorded as inspected, and before/after evidence confirms that positions, SMTP configuration, C7 execution records, and email delivery records were unchanged by verification.
