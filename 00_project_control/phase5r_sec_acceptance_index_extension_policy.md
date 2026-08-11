# Phase 5R SEC Acceptance-Index Extension Policy v1

Policy version: `phase5r_sec_acceptance_extension_policy_v1`

This policy admits a newly observed official SEC submission accession without
modifying the retained historical acceptance index. It applies only to the
approved SEC submissions source path used by the daily evidence refresh.

## Immutable historical layer

`03_source_data/phase5r/phase5r_sec_submission_acceptance_index.json` remains
byte-for-byte immutable. The refresh never rewrites, reorders, truncates,
backfills, or merges records into that file.

The effective acceptance set is assembled in memory as:

`historical immutable index + validated versioned extension artifacts`

The existing timestamp-reconciliation policy remains in force for records
already present in either layer.

## Admission requirements

Each candidate extension record must independently validate:

- accession-number format and uniqueness;
- SEC submissions endpoint CIK, official ticker list, and official issuer name;
- CIK/ticker mapping from the current official SEC ticker map;
- allowed filing form and filing date;
- timezone-aware `accepted_at` timestamp that is not later than admission time;
- exact allowlisted `https://data.sec.gov/submissions/CIK##########.json`
  provenance;
- absence from the historical index and all retained extensions; and
- absence of duplicates in the current response or the proposed extension.

Identity, duplicate, malformed, future-timestamp, non-SEC-provenance, chain,
or audit-binding failures close the SEC evidence gate. An identity or
provenance conflict is not automatically admitted and requires Project Owner
review before any policy change.

## Versioned artifacts and audit

Each admission batch is written as a new immutable JSON artifact at:

`03_source_data/phase5r/phase5r_sec_acceptance_extensions/phase5r_sec_acceptance_extension_vN.json`

Versions must be contiguous and each artifact binds to both the exact raw-byte
SHA-256 of the historical index and the canonical hash chain of all earlier
extensions. A separate append-only admission audit is written to:

`03_source_data/phase5r/phase5r_sec_acceptance_extension_admission_audit.csv`

Every audit row records the extension version, accession, validated ticker,
CIK, issuer name, form, filing date, accepted time, official provenance,
decision, admission timestamp, historical-index binding, and SHA-256 of the
exact raw bytes of the corresponding extension artifact.

All file hashes are SHA-256 over exact raw file bytes. JSON artifacts are
written as UTF-8 without BOM using LF line endings; no hash-time whitespace,
key-order, or newline normalization is performed. Canonical JSON hashes within
the artifacts validate structured content separately from raw-byte audit
bindings.

## Commit and recovery behavior

The daily evidence refresh holds a dedicated local lock while it reloads the
historical index, validates retained extensions, plans new admissions,
reconciles the full effective set, and persists append-only audit material.
All candidate identity, provenance, timestamp, duplicate, and reconciliation
checks complete before a new extension is written. The historical index is
never a write target.

An interrupted write never authorizes a partial result: later refreshes reload
and validate every retained artifact and audit row before using the effective
set. Missing or conflicting audit material, an invalid chain, or a changed
historical-index binding fails closed.

## Boundaries

This policy does not create provider, browser, trading, broker, account,
order, email, scheduler, or canonical-decision authority. It does not access
v10 sealed artifacts, blind keys, completion records, or historical pilot
outputs.
