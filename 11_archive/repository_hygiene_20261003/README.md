# Repository Hygiene Diagnosis

Dated architecture cleanup at baseline `5b314a1d43c6dde7691a3d0eec24d011facb8fd7`.
This is evidence of a maintenance change, not current runtime status. The
[maintained layout contract](../../00_project_control/repository_layout.md)
and [current document index](../../00_project_control/current_documents.md)
are the navigation entrypoints.

The major structural noise was a 520-file copy of retired implementation,
source, tests and reports already preserved at the same paths in a remote
annotated tag. Agent instructions named obsolete research, trading and review
folders. A historical implementation plan appeared in the authoritative index;
dated repair and timing records mixed with maintained guidance. Runtime-only
namespaces looked empty in Git even though production writers/readers use them.
Generated provenance and graph navigation artifacts have operational value and
must not be treated as disposable output. Private write-only archives also share
`11_archive` with retired source, requiring explicit boundaries.

# Directory Classification

[Complete before inventory](directory_inventory_before.csv) contains 145 tracked
directories and observed runtime namespaces, with role, purpose, owner, counts,
bytes, immediate tracked children, active/scheduler/test/doc/experiment references,
recovery and move/delete confidence. Private contents were not read for inventory. A complete per-directory runtime
metadata inventory (including ignored nested namespaces and caches) is retained
locally at `/Users/messssi/Documents/equity/architecture_cleanup_20261003/runtime_directory_inventory.csv`;
private path inventories are not added to Git. `.git` internals are excluded
from directory classification: they preserve history and are never cleanup targets.
[Final directory inventory](directory_inventory_after.csv) describes the candidate.
Owners are functional responsibilities, not inferred human identities. Mixed
parent classifications are elaborated by the maintained map; runtime-only data
have no Git recovery guarantee. Current guidance resolves formerly uncertain
singleton wrappers as compatibility or runtime paths.

| Top-level directory | Classification / purpose |
|---|---|
| `.codex` | ACTIVE_CONFIG — graph skill and hooks |
| `00_project_control` | ACTIVE_DOCUMENTATION / ACTIVE_CONFIG — maintained authority and registries |
| `01_policies` | ACTIVE_CONFIG — executable policies, display names, frozen registry |
| `02_filings` | EXPERIMENT_EVIDENCE — admitted source bytes; runtime caches coexist |
| `03_source_data` | ACTIVE_CONFIG / COMPATIBILITY_PATH — universe and tracked source provenance; generated observations |
| `04_data` | RUNTIME_NAMESPACE — valuation example and private inputs |
| `04_research` | RUNTIME_NAMESPACE — private maintained research and generated decisions; no tracked files at baseline |
| `05_risk_and_positions` | RUNTIME_NAMESPACE — account/plan state, examples and generated calculations |
| `06_execution_records` | RUNTIME_NAMESPACE — manual records/reconciliation and templates |
| `07_automation` | ACTIVE_CONFIG — scheduler/delivery tooling with private artifacts |
| `08_reviews` | RUNTIME_NAMESPACE / EXPERIMENT_EVIDENCE — reports and retained evaluation histories |
| `09_scripts` | ACTIVE_SOURCE / COMPATIBILITY_PATH — maintained Python implementation/tests |
| `10_dashboard` | ACTIVE_SOURCE — UI/server and tests |
| `11_archive` | HISTORICAL_UNIQUE plus HISTORICAL_GIT_RECOVERABLE pointers and ignored private evidence |
| `graphify-out` | GENERATED_REGENERABLE — retained architecture fast path |

# Cleanup Performed

- Removed exactly the 520 blob-verified retired files under
  `11_archive/phase5r_retired_20260831/`. Retained README, added a recovery manifest,
  and removed only empty retired directories. Any unrelated ignored state stayed.
- Moved `00_project_control/workflow_improvement_plan_20260920.md`,
  `pipeline_repair_20260928.md` and `collector_timing_20260928.md` into
  `11_archive/project_control_history/` byte-for-byte. Its manifest records hashes
  and original commit. All current direct links were migrated; original historical
  records and the dated naming migration manifest retain original context.
- Added the maintained topology/path-owner contract and archive navigation.
- Removed a duplicate ignore rule, clarified runtime comments and ignored local
  Graphify reflection output. Retained graph, report, labels, manifest and provenance.
- Retained every meaningful README-only runtime namespace. No active path was flattened.

# Archive Reduction

Before: **556 tracked files / 6,833,981 bytes** across `11_archive`.
The removed duplicate payload alone is **520 files / 6,662,389 bytes**.
The final count/size, including new manifests and this audit, is recorded in
[final metrics](final_metrics.json). Counts describe the final candidate working
tree (including new authored files), not a deployed commit. Git history/disk object
storage was not pruned; reduction is in files present on the branch.

# Runtime Namespace Decisions

KEEP all three `equity_research` wrappers. Source data owns public/tracked
provenance; valuation data owns private input bundles; scripts own maintained
implementation. They have distinct responsibilities and extensive references.
KEEP `08_reviews/shadow_llm` as documented evaluation scope and `08_reviews` as
RUNTIME_NAMESPACE: only its SHADOW README was tracked, but reports, run bundles,
capital queues and frozen experiments are generated or retained privately there.
Git need not contain every runtime directory. Keep `04_research/company_research`
as a writer-created private namespace. Preserve `11_archive/portfolio_versions.local`
as write-only predecessor retention; it is prohibited as an active decision input.

# Documentation Repairs

AGENTS now names active Python/dashboard source, current configuration, admitted
filings/source evidence, private valuation/research/account/execution paths,
report/brief/log namespaces, recovery rules and frozen boundaries. Removed obsolete
`03_research`, `06_trading` and `07_reviews` conventions. Current index links to the
layout contract and treats the dated plan/repair/timing material as history. Naming
history and scheduler recovery references point to valid retirement metadata. The
runtime news-status and maintained-plan hyperlinks now target authoritative
LocalRuntime artifacts. The superseded-doc archive README's stale `phase5r_current_documents.md` link is corrected.
Still-effective dated decisions and the ongoing dashboard plan remain current.
No schedule, strategy, risk, account truth, eligibility or execution authority changed.

# Deferred Refactors

The three wrappers and domain-specific SHADOW namespace remain. A later flattening
needs a coherent registry/scheduler/code/test/private-state migration, retained
receipts, frozen-version treatment and lock-protected deployment rehearsal; the
maintained contract contains that plan. Shared paths already have owners in
`daily_common`, runtime sync, valuation bundles, portfolio archives, frozen runtime
and display config. Extracting a new universal path module would add complexity
and change frozen dependency hashes; no such code change was justified. Duplicated
paths in independent guards/templates/tests are intentional contract checks.

# Dependency Safety

See [graph and direct-reference findings](dependency_findings.md). Graphify query,
path and explain were used before architecture tracing. Archive exclusion required
independent direct-reference checks. Every removed blob matched the annotated tag
at its original path; remote tag identity was independently checked. Other archives,
tracked admitted evidence and private histories were retained. Source/generated/
runtime/delivery status are distinguished throughout the maintained contract.

# Test Results

Validation is recorded in [verification results](verification_results.json).
It includes recovery hashes, moved-document hashes, navigation/path checks,
focused migration/frozen/scheduler regressions, active suite, dashboard suite,
no-send artifact inspection and Graphify update. The cleaned candidate passed all 924 active tests, 83 focused regressions,
54 dashboard Python tests and 14 dashboard domain tests. The direct Desktop
suite had one missing-runtime-output failure and six historical Git archive
timeouts; those checkout limitations are recorded explicitly. Graphify updated
code and nine changed documents (3,674 nodes / 9,800 edges), with no dangling
endpoints. Its 49 zero-node AST warnings are recorded; JSON/config coverage
still requires direct inspection.

Production status was checked
read-only; its checkout remains at the baseline until normal reviewed publication.
The fast-forward rehearsal passed against the cleaned candidate and preserved
all 4,134 copied ignored private files byte-for-byte, with no new tracked path
colliding with ignored runtime files. Production itself was not synchronized.
A passing local or isolated check is not a deployment or email-delivery claim.

# Final Repository Map

```text
.codex/                         agent tools
00_project_control/             maintained guidance + active registries
01_policies/                    executable policies + frozen registry
02_filings/                     admitted official evidence + ignored caches
03_source_data/equity_research/  tracked provenance + generated public data
04_data/equity_research/         private valuation namespace + example
04_research/company_research/   private maintained research + decisions
05_risk_and_positions/          private account/plans + examples
06_execution_records/           manual records + templates
07_automation/                  tracked scheduler/tooling + private briefs/ledgers
08_reviews/                     private reports/evidence + SHADOW guide
09_scripts/equity_research/     maintained source + tests
10_dashboard/                   maintained app + tests
11_archive/
  phase5r_retired_20260831/      README + recovery_manifest.csv
  phase5r_docs_superseded_20260904/
  dated_reviews_20260923/
  schedule_before_owner_windows_20260928/
  project_control_history/      three original dated records + manifest
  repository_hygiene_20261003/   this dated audit
  portfolio_versions.local/     ignored private predecessor evidence
graphify-out/                   retained navigation graph/report/manifest
```

# Recovery

Annotated remote tag `phase5r-pre-cleanup-20260831` resolves to
`5790e00040dcd07973f4366eaea480eff210c306`; its tag object is
`eac6790ec5a7bd32fa07cffcaf8245acc71f47aa`. The retirement
[manifest](../phase5r_retired_20260831/recovery_manifest.csv) records every original
path, Git blob, SHA-256 and size. Recovery instructions live beside it. The three
moved records also remain recoverable at their original paths from baseline commit.
The documented private LocalArchive exists and was untouched; its old count/size
was not recertified. Other frozen implementations use their registered commits.
