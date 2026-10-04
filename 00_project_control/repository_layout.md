# Repository layout and path ownership

This is the maintained topology contract. Use [current documents](current_documents.md)
for policy authority; this contract does not set investment thresholds or schedules.
The dated hygiene diagnosis and per-directory inventory are [archived separately](../11_archive/repository_hygiene_20261003/README.md).

## Checkouts and authority

`/Users/messssi/Desktop/equity` is the authoring Git checkout.
`/Users/messssi/LocalRuntime/equity` is the independent production clone.
`/Users/messssi/Documents/equity` contains local audit evidence. Deployment flows
through GitHub `main`, under the [runtime synchronization contract](macbook_github_macmini_workflow.md).
An authoring edit or generated authoring report does not prove deployment.

## Numbered directory contract

| Directory | Role and tracked content | Runtime/private content and owner |
|---|---|---|
| `.codex` | ACTIVE_CONFIG: Graphify skill and hooks | Agent tooling; not investment authority |
| `00_project_control` | ACTIVE_DOCUMENTATION / ACTIVE_CONFIG: current guidance, authoritative active state/config and input/retirement registries | Generated status and `run_logs/`; workflow/scheduler owners |
| `01_policies` | ACTIVE_CONFIG: executable policies, display config, frozen implementation registry; manual references have bounded authority | Policy owners; do not substitute illustrative manual risk examples for active config |
| `02_filings` | EXPERIMENT_EVIDENCE: admitted SEC source bytes needed by tracked acceptance evidence | Additional issuer/companyfacts caches are ignored; SEC collector owns admission |
| `03_source_data/equity_research` | COMPATIBILITY_PATH: universe seed, official ledger, acceptance index/extensions and audit evidence | Generated market/evidence snapshots, discovery and news state; public evidence pipeline |
| `04_data/equity_research` | RUNTIME_NAMESPACE: tracked valuation bundle example | Private versioned valuation inputs, retained source receipts and scenarios; valuation bundle writer |
| `04_research/company_research` | RUNTIME_NAMESPACE: intentionally absent from tracked Git at audit baseline | Maintained dossiers, opportunities and append-only outcomes alongside generated decisions; research writers |
| `05_risk_and_positions` | RUNTIME_NAMESPACE: README and examples | Approved private account truth, plans, snapshots and generated calculations; manual account writer/C9 |
| `06_execution_records` | RUNTIME_NAMESPACE: execution example/template | Confirmed manual records, reconciliation and dashboard feedback; manual writer, never broker access |
| `07_automation` | ACTIVE_CONFIG: launchd templates, installers/checks, delivery configuration example | Email briefs, exact sent artifacts, ledgers, scheduler locks/state and dashboard service files |
| `08_reviews` | RUNTIME_NAMESPACE: `shadow_llm/README.md` documents the isolated evaluator | Current reports, owner reviews, SHADOW run bundles, capital queues and frozen momentum evidence; respective producers |
| `09_scripts/equity_research` | ACTIVE_SOURCE / COMPATIBILITY_PATH: Python modules and tests | Checkout-relative execution; never flatten independently of consumers |
| `10_dashboard` | ACTIVE_SOURCE: React UI, Python server and tests | Ignored build/dependencies; private service state under `07_automation/dashboard.local/` |
| `11_archive` | HISTORICAL_UNIQUE plus HISTORICAL_GIT_RECOVERABLE pointers | `portfolio_versions.local/` and migration snapshots are private retained evidence, not active inputs |
| `graphify-out` | GENERATED_REGENERABLE: retained graph/report/manifest/labels are useful navigation artifacts | Local AST cache, reflections and interactive exports; Graphify owns relationships |

A runtime namespace is a contract, not a promise that Git materializes it.
Writers create required parent directories; absence before first use is normal
only where the reader explicitly permits it. Optionality is governed by the
active input registry and verifier, never inferred from this table.

## Tracked evidence versus regenerable output

Generated does not mean disposable. The official evidence ledger, SEC acceptance
index, immutable extensions and their admitted filing artifacts are tracked
provenance inputs. Preserve them. Companyfacts caches and current market snapshots
are generated locally; immutable source snapshots, evaluation packets, histories
and private account records have separate retention requirements. `.local` alone
does not prove regenerability. Examples never replace missing private state.

`08_reviews/shadow_llm/` remains a documented evaluation namespace. It is isolated
from production decisions and delivery. `08_reviews/momentum_experiment.local/`
contains frozen observations and replay inputs; preserve all bytes and identities.
`11_archive/portfolio_versions.local/` has active write-only predecessor retention
and tests, but is prohibited as a decision input. Do not conflate it with retired
tracked source copies.

## Current guidance and dated history

`current_documents.md` indexes maintained policy, operations, configuration and
architecture. Dated implementation, repair and measurement records live in
`11_archive/project_control_history/` or their existing dated archive. A dated
filename is not sufficient reason to move a still-effective decision: momentum
integration, workflow follow-through, research budgets, source manifests and the
in-progress dashboard plan remain current. Historical records can describe prior
paths and thresholds; they cannot override current contracts.

## Path ownership and bounded future migrations

| Contract | Existing owner / legitimate consumers |
|---|---|
| Checkout-relative repository root and shared artifact constants | `09_scripts/equity_research/daily_common.py`; pipeline modules and patched test fixtures |
| Production checkout, external runtime lock and strict Git sync | `run_runtime_scheduler.py`; scheduler templates/installer and independent verifier |
| Admitted active inputs and optionality | `00_project_control/allowed_active_inputs.csv`; `verify_active_state_guard.py` |
| Versioned valuation input location/admission | `valuation_input_bundle.py`; valuation producers/readers |
| Private portfolio predecessor location | `portfolio_archive.py`; account and dashboard writers |
| Frozen implementation closure | `frozen_momentum_runtime.py` plus `momentum_implementation_archives.json`; replay tests and retained input hashes |
| Display/branding | `01_policies/equity_display_names.json`; `equity_naming.py` |

Retain these owners. Duplicated root/path strings in independent guards, launchd
contracts and test fixtures are intentional checks. Moving shared constants in
`daily_common.py` can change a frozen implementation hash even if values remain
equal, so a cosmetic extraction would require experiment-version admission.
No new universal path configuration layer is needed for this cleanup.

Keep all three `equity_research` wrappers. Source data owns tracked/public evidence,
valuation data owns private inputs, and scripts own implementation; their common
name does not make them redundant. `08_reviews/shadow_llm` is a domain namespace.

Any later flattening is a separate migration: enumerate graph and direct consumers;
map registry, scheduler/template, documentation, test and private runtime paths;
retain receipts and hashes; define experiment-version treatment; update each owner
and all consumers together; test on an isolated clone; rehearse a fast-forward with
ignored state; deploy under the external runtime lock. Do not accumulate aliases.
