# Position purpose and reassessment

Added 2026-09-27. These are prospective research-authoring safeguards. They do not change capital allocations, risk limits, account records, or execution authority. A validated narrative is an attributed research judgment, not proof of an investment edge or a confirmed fill.

The existing append-only `investment_plans.local.json` history remains readable. Routine clarification of an existing, unexpired plan can still append an ordinary version. No legacy position is automatically relabeled as intraday, multi-day, or long-term.

## Explicit purpose

New tactical plans with no prior ticker lineage must specify `strategy_horizon` and a `purpose` object. Other new records may specify them. Existing legacy plans remain readable and routine unchanged-purpose updates remain compatible. Existing roles remain the portfolio mandates; the horizon distinguishes tactical strategies without changing those mandates.

| strategy_horizon | Compatible role | Additional condition |
|---|---|---|
| intraday_momentum | tactical | Time exit, review and optional validity deadline must fall in the effective session, by its regular/early close; any DAY draft must name that session. |
| multi_day_trend | tactical | Existing mandatory time exit remains in force. |
| long_term_growth | long_term_growth | Authored holding rationale must support the longer purpose. |
| broad_core | broad_core | SPY and QQQM may share the approved index-core purpose; authored rationale must support that purpose and QQQM concentration/overlap. Other ETFs are not admitted automatically. |

`purpose` requires nonempty `strategy`, `holding_period_justification`, `entry_validity`, `failure_condition`, and `exit_rule`, plus `sources`. Every source must identify a `path` and `sha256` already present in the plan's source receipts. The writer verifies retained bytes. It cannot judge whether the narrative actually establishes efficacy; that assessment remains research work. Explicit purpose and sources do not verify live market conditions.

An optional authored `setup_status` (`active`, `failed`, `expired`, or `unverified`) requires `setup_status_reason`. A failed or expired setup remains unresolved in current plan evaluation. This field records an analyst assessment; no market pattern detector infers it. A failed record cannot silently become a maintained plan by removing this field.

## Required reassessment

The append writer requires a structured `reassessment` when a role/horizon or authored purpose changes, a time exit or validity deadline is lengthened or removed, a prior plan/draft has expired, a prior setup was recorded failed, or a terminal plan is reopened/replaced. Purpose changes and deadline extensions also require an explicit supported horizon. Changing a strategy or its holding rationale within the same horizon therefore still requires review. An already explicit horizon cannot be discarded to avoid these checks.

Postponing an already-due `review_at` also requires a recorded reassessment, including for an open-ended growth/core holding. A due review alone does not label the setup expired or failed: the reassessment may retain `active` or `unverified` with evidence and explanation. Historical review deadlines remain in the immutable prior version.

The object requires:

- `previous_plan_id` and `previous_record_hash`, identifying the immediate relevant prior version.
- `reviewed_at` (timezone-aware, no earlier than the prior record and no later than the proposed record), `reviewer`, and `reason`.
- `evidence_summary`, `strategy_justification`, and `holding_period_justification`.
- `prior_outcome`: a `status` and explanatory `detail`. Status is one of `active`, `failed`, `expired`, `expired_and_failed`, `completed`, `cancelled`, `superseded`, or `unverified`. Mechanically expired prior plans must retain `expired` or `expired_and_failed`; a recorded failure must retain `failed` or `expired_and_failed`. These are setup/plan outcomes, not investment returns or assertions of execution.
- `sources`, citing retained receipts included in the new plan's validated sources.

Changing `plan_id` cannot bypass continuity. Another active plan for the same ticker blocks authoring a new plan. First reconcile and record the old plan's terminal state, then link the replacement to the latest terminal record with a reassessment. A retired older plan ID cannot be reopened after a newer lineage exists. Pre-existing multiple-active-plan histories still load and remain explicit reconciliation conflicts.

Use the existing `update_investment_plan.py --input <proposal.json>` preview, inspect validation, and append with `--apply` only as an authorized research update. The original rows, instructions, source hashes, failed/expired outcomes and deadlines stay in the ledger. No automatic renewal or daily mandate change was introduced. The plan can remain expired/unverified when evidence or owner execution observations are missing.

## Exact historical source recovery

A historical plan may have bound a mutable logical source path whose current
bytes have legitimately changed. Preserve the original plan ledger, record
hashes and current source. If an exact retained copy exists, register it with
`register_plan_source_resolution.py`; this is source recovery, not a new plan
review or permission to renew an expired instruction.

The private input JSON contains a `resolutions` array. Each entry has exactly
`plan_id`, `plan_version`, `plan_record_hash`, `logical_path`, `expected_sha256`,
`retained_path`, `reason` and `reviewer`. The named plan record must already
exist with a valid immutable hash and explicitly bind that logical path/hash.
The retained regular file must be inside the same checkout, with no symlink
components, and match the original SHA-256 exactly. Each file is limited to
32 MB. There is no archive search or nearest/newer source substitution.

```sh
python3 09_scripts/equity_research/register_plan_source_resolution.py --root /path/to/runtime --input /path/to/private-resolution-proposal.json
python3 09_scripts/equity_research/register_plan_source_resolution.py --root /path/to/runtime --input /path/to/private-resolution-proposal.json --apply
```

Preview validates without publishing. Apply uses the plan writer's lock and
appends chained receipts to `05_risk_and_positions/plan_source_resolutions.local.json`;
an identical retry is a no-op. It never rewrites the plan ledger or either
source file. Registry tampering, missing/changed retained bytes, unsafe paths
and a different plan record fail closed. New plan proposals must bind their
own direct retained sources; an older record's resolution cannot authorize
them. Workflow, capital and dashboard publication checks revalidate the
registry and the explicitly registered retained bytes. Recompose the complete
decision after registration, then append any separately researched plan via
the ordinary maintained writer. Research dates, expiry, economics, allocation,
strategy admission and human-only execution remain unchanged.
