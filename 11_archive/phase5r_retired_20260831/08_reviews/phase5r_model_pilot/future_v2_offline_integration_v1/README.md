# future-v2-offline-integration-v1

This is a new, isolated offline workflow for synthetic or local **future**
Phase 5R handoffs. It is not a v10 runner, replay, migration, or promotion
path. Every created output has `canonical_effect: false`.

It validates exact raw bytes and the existing future-v2 evidence/citation
contract, runs the future-v3 assertion-span procedure against packet-local
excerpts, and records critic/committee quality signals without adjudicating
them. It does not establish semantic truth, investment suitability, reviewer
independence, independent human validation, a promotion metric, or a canonical
decision.

## Fixed isolation boundary

The CLI accepts only these new, direct-child locations:

```text
08_reviews/phase5r_model_pilot/future_v2_offline_integration_v1/
  handoffs/<handoff-id>/
    future_v2_handoff_manifest.json
    packet.json
    evidence_source_texts_v2.json
    analyst_response.json
    evidence_metadata_v2.json
    analyst_evidence_bindings_v2.json
    committee_response.json
    committee_ticker_decisions.json
    critic_coverage_v2.json
    assertion_span_bundle_v3.json
  outputs/<run-id>/                 # created exclusively by the CLI

00_project_control/future_v2_offline_integration_v1/
  owner_approvals/<approval-id>.json
```

The CLI refuses symlinks, hard-linked input files, non-regular files,
oversized local JSON, duplicate JSON keys, BOM/CR line endings, paths outside
these roots, and an already-existing output run id. It has no argument for a
blind key, v10 asset, completion record, credential, runtime state, network,
provider, broker, account, email, scheduler, or execution component.

## Required local inputs

1. Place a complete future-v2 handoff in `handoffs/<handoff-id>/`. Its manifest
   must attest `validated_offline_noncanonical`, no provider/network use, no
   canonical effect, no execution, and no unblinding. The established future
   handoff verifier checks all eight hash-bound v2 sidecars.
2. Add `assertion_span_bundle_v3.json` in the same handoff directory. It must
   use `phase5r_assertion_span_contract_v3`, bind to the handoff packet id and
   packet source hashes, and set `canonical_effect: false`. A claim may be
   reported as `anchor_not_available`; this yields an incomplete span procedure
   rather than an invented citation span.
3. Copy the owner-approval template to a new direct child of `owner_approvals/`.
   Fill the exact **raw-byte SHA-256** of that handoff's manifest and its packet
   id. The template is intentionally invalid until those values, the named
   Project Owner, and an America/New_York timestamp are supplied. All authority
   fields remain `false`.

The exact-handoff approval is a bounded local reference. The verifier checks
its structure and hash binding; it does not claim to authenticate a person or
signature.

## Run

```text
cd 09_scripts/phase5r
python3 run_phase5r_future_v2_offline_integration.py \
  --handoff-dir ../../08_reviews/phase5r_model_pilot/future_v2_offline_integration_v1/handoffs/<handoff-id> \
  --owner-approval-reference ../../00_project_control/future_v2_offline_integration_v1/owner_approvals/<approval-id>.json \
  --run-id <new-lowercase-run-id>
```

The command creates only a fresh `outputs/<run-id>/` with:

- `future_v2_disagreement_log.json` — observed critic/committee signals and
  material issue counts, explicitly not adjudicated;
- `future_v2_offline_integration_report.json` — the structured evidence,
  citation, span, authority, and input-hash status; and
- `future_v2_offline_integration_report.md` — a readable rendering.

No output authorizes a buy, sell, trade, broker/account access, order,
execution, email, scheduler, canonical decision, or provider integration.
Provider integration remains prohibited unless separately and explicitly
authorized by the Project Owner.
