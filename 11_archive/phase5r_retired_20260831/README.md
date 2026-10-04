# Retired Phase 5R recovery pointer — August 31, 2026

This directory is historical recovery metadata, never an active input. The 520
retired source, test, policy, scheduler and report copies were removed from main
on October 3, 2026 after every Git blob matched the same original path in the
annotated tag below. Unique private experiment evidence was not removed.

- Annotated tag: `phase5r-pre-cleanup-20260831`
- Commit: `5790e00040dcd07973f4366eaea480eff210c306`
- Tag object: `eac6790ec5a7bd32fa07cffcaf8245acc71f47aa`
- [Recovery manifest](recovery_manifest.csv): original and former archived paths,
  exact Git blob, SHA-256 and byte count for all 520 files.

The former archive prefix is a historical locator. Use the manifest to resolve
old registry entries or audit references; those entries do not point to active
filesystem inputs. The tag preserves each file at `original_path`, without the
retirement archive prefix. For example, the old production-shadow policy is
`04_research/company_research/production_shadow_v1.md`; the Phase 0C reframe plan
is `00_project_control/audit_reports/phase0c/phase0c_reframe_plan.md` in the tag.

## Recover without touching production

```sh
git fetch origin tag phase5r-pre-cleanup-20260831
git worktree add --detach /tmp/equity-phase5r-recovery phase5r-pre-cleanup-20260831
# Read a particular original path without restoring it:
git show phase5r-pre-cleanup-20260831:04_research/company_research/production_shadow_v1.md
```

Run these commands from the authoring checkout. Verify the tag's peeled commit
with `git rev-parse phase5r-pre-cleanup-20260831^{commit}`. Match a recovered
file's SHA-256 against the manifest. Restore only to a separate branch/worktree;
returning retired code to production requires a separate reviewed migration.
Never run old sender, scheduler or model commands as current workflows.

## Separately retained private evidence

The original retirement record documented 693 ignored runtime evidence files
(about 76 MiB) at `/Users/messssi/LocalArchive/equity/phase5r_retired_20260831/`.
That directory's existence was checked during this cleanup; the old file count
and size are historical figures, not a new completeness certification. It holds
replay corpora, distinct pilot quarantine records and stale reports from the two
checkouts. It was not modified. Current private momentum/SHADOW inputs, run
bundles and histories remain in their runtime namespaces.
