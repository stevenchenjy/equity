# Draft — Limited Governance Amendment for Phase 5R v10 AI-Assisted Review

## Status and authority

**Draft only — not adopted and not effective.** The user's authorization
authorizes preparation of this draft only. It does not amend the existing
`phase5r_llm_decision_authority_policy.md`,
`phase5r_llm_evaluation_policy.md`, or anonymous-review protocol until a
separate, explicit adoption record is created by the designated human Project
Owner and validates successfully with the provider-free verifier named below.

This draft creates no AI reviewer equivalence, promotion path, unblinding
right, or operational authority. If adopted without change, it would create
only one additional artifact class: **AI-assisted internal review evidence**.

## Roles, authority, and effective time

- **Project Owner / Policy Owner:** a named natural person in the adoption
  record with `authority: "project owner"`. Only that person may adopt or
  revoke this amendment.
- **Drafter:** a human or AI that proposes text. A drafter has no policy or
  operational authority.
- **AI-assisted reviewer:** an interactive AI session that prepares a bounded
  internal artifact. It is not an independent reviewer and cannot approve,
  sign, or adopt policy.
- **Adopter:** the Project Owner named in the adoption record. In a
  single-owner project, the same natural person may propose and adopt the
  amendment only if the record sets `same_person_proposed_and_approved: true`.
  This exception never permits an AI to approve itself.
- **Effective time:** only the `effective_at_et` in a valid, separate adoption
  record makes an adopted amendment effective. A draft, a chat message, or an
  AI-generated file alone has no effect.
- **Revocation:** only the named Project Owner may revoke it, with a new
  explicit revocation record. Revocation is effective when that record is
  created; it cannot retroactively create authority.

The Project Owner's name is intentionally left unspecified in this draft. It
must not be inferred from an AI session, repository metadata, or an unverified
suggestion.

## Limited v10 scope

This amendment applies only to these frozen v10 artifacts:

- anonymous review bundle, raw-file SHA-256:
  `011192c2ddb7a9db07e0b588499c16d9330b98da2caf82a855cc70aadc894a77`;
- AI-assisted review artifact, raw-file SHA-256:
  `5282ea924a564e2a2fda7a2f49f5c63643f5aa706b2f95ad023ddad678de3775`;
- legacy in-artifact canonical JSON review digest:
  `b8ec4c1cf2bf84525b139a99d7fd49fd2b02fbe842734bbe53b9e47bf7d97625`.

It does not apply to another pilot, another bundle, a new provider response, or
a future model release. It establishes no precedent.

## Interactive AI session versus repository-side provider calls

This amendment does **not** authorize any repository-initiated API or provider
request. It distinguishes that prohibited activity from an already-authorized
interactive AI session used to prepare an internal review of the exact frozen
anonymous bundle.

If adopted, the interactive-session artifact must disclose:

- provider and model family, if exposed by the session;
- review date in ET;
- reasoning configuration, or `not_exposed_to_project` if the session does not
  expose one;
- its non-independent status; and
- that it used only the frozen anonymous bundle and cited excerpts as evidence.

For the existing v10 review, the available disclosure is: provider OpenAI;
session surface Codex interactive session; GPT-5 model family; review date
2026-08-02 ET; reasoning configuration `not_exposed_to_project`; and
non-independent status. This statement does not retroactively alter the frozen
review artifact.

The frozen v10 field `freeze_protocol.model_api_called: false` has an
unspecified historical boundary and therefore cannot establish that no
interactive provider-hosted session occurred. This amendment does not
reinterpret or overwrite that field. The separate adoption record's
interactive-session disclosure is required precisely to avoid treating the
legacy field as a claim about the interactive Codex session.

No browsing, network request, external evidence retrieval, credential
inspection, key handling, or additional project-side provider call is allowed.
Local, read-only tools may be used only to read and hash the named frozen
artifacts; a separate new output file may be written for the internal review or
its correction record. No local tool may read the blind key or modify a sealed
source artifact.

## Permitted noncanonical use

Subject to the exact hashes and controls above, AI-assisted internal evidence
may:

1. assess anonymous claim and critic rows against only their cited excerpts;
2. create separately hash-bound review, provenance, and correction artifacts;
3. record weaknesses, ambiguities, citation-scope defects, missing evidence,
   and proposed wording corrections; and
4. compare with already visible anonymous critic assessments without deriving
   or identifying any runtime/model assignment.

Each new artifact created under this amendment must state prominently that it
is AI-assisted internal evidence, not independent human review, not an
adjudication, and not an authorization to act. This requirement does not alter
the frozen v10 review; its existing non-independent and no-authority fields
remain the applicable historical record.

## Presumed non-independence

The AI-assisted reviewer is presumed non-independent from the upstream
model/provider unless a separate policy and evidence record proves otherwise.
It may share a provider, model family, training exposure, reasoning habits, or
systemic bias with the outputs it evaluates. It may identify defects and create
correction candidates, but it may not establish reviewer independence,
unbiased error rates, human citation accuracy, critic incremental value, or
promotion readiness.

## Non-waivable prohibitions

This amendment may not, and does not:

- count as either of the two independent human reviews required by the
  anonymous-review protocol;
- permit access to, hashing of, distribution of, or inference from the sealed
  blind key or runtime A/B assignment;
- permit finalization, human adjudication, promotion, activation, or a change
  to the v10 `no_go_pending_independent_review` state;
- alter any immutable plan, journal, receipt, anonymous bundle, completion
  record, source artifact, or their hashes;
- count toward activation thresholds, human citation accuracy, unsupported
  claim rate, critic incremental value, replay qualification, or any other
  promotion metric;
- enable a canonical decision, C9 influence, email, SMTP access, alert,
  scheduler, account access, broker connection, order code, execution, or a
  buy/sell instruction; or
- authorize an external model/provider request, repository-side credential
  inspection, network evidence retrieval, or budget spend.

The existing stricter policy or technical boundary always controls if any
wording conflicts with this draft.

## Required controls and verification

Before any adoption, run the provider-free verifier:

```text
python3 09_scripts/phase5r/verify_phase5r_v10_ai_review_governance.py
```

Then validate the completed, separate adoption record without modifying it:

```text
python3 09_scripts/phase5r/verify_phase5r_v10_ai_review_governance.py \
  --adoption-record path/to/separate_adoption_record.json
```

It must verify that the named anonymous bundle and AI-review artifact match the
exact raw-file and legacy canonical hashes stated above, that the AI review's
48 claim rows and five critic rows bind only to the anonymous bundle, that the
AI review retains its explicit `final_decision.decision: "no_go"`, and that its
self-attested blind-key/network/provider fields remain false. Those
attestations are not proof of non-access; they are explicit limits on what the
verifier can prove.

The verifier must not read the blind key or the completion record because the
current completion manifest embeds a blind-key digest. A source hash mismatch,
missing cited excerpt, attempted unblinding, provider call, credential
exposure, or write to a sealed source artifact terminates the review with
`no_go`.

Any known blind-key boundary incident must be recorded separately and receive a
Project Owner disposition before an adoption record can validate successfully.
It cannot be silently cured by editing an attestation, the draft, or a review
artifact.

A Project Owner disposition may permit only separately documented,
noncanonical internal-quality use. It does not itself adopt this amendment,
complete or waive the two-human-review protocol, unblind the run, or authorize
promotion. The current limited direction is recorded in
`00_project_control/phase5r_v10_project_owner_internal_use_decision.json`.

## Status vocabulary: procedure and substance are separate

Any separately authorized future AI-assisted internal review must report two
distinct fields:

```json
{
  "procedure_status": "completed",
  "substantive_recommendation": "revision_required"
}
```

Allowed `procedure_status` values are `completed`, `incomplete`, and
`invalidated`. Allowed `substantive_recommendation` values are
`acceptable_for_internal_research`, `acceptable_with_corrections`,
`revision_required`, and `unsuitable`.

Neither field is a Phase 5R research classification or a promotion decision.
`completed` means only that the bounded internal procedure completed; it never
means that the pilot, evidence, governance gate, or model passed. The frozen
v10 review's existing `final_decision.decision: "no_go"` remains unchanged and
must not be relabeled in place.

## Fixed hash rule for this amendment and future governance artifacts

For this amendment, its adoption record, provenance supplement, and structured
correction records, the authoritative file identity is **SHA-256 over exact raw
file bytes**. Text files must be UTF-8 without BOM, use LF line endings, and
include exactly the bytes stored on disk. No whitespace, key ordering, Unicode,
or newline normalization occurs before hashing.

The existing v10 AI-review field `review_sha256` is a pre-existing legacy
canonical-JSON integrity field, calculated by serializing the object without
that field using UTF-8, sorted keys, compact `,`/`:` separators, `ensure_ascii`
false, and no NaN values. It remains a verifier check only. Any future adoption
record binds the review artifact by its raw-file hash; it does not substitute or
reinterpret the legacy canonical digest.

## Structured correction-addendum requirement

The anonymous source artifact is never edited. Each future correction must be a
separate JSON record with, at minimum:

```json
{
  "review_id": "...",
  "original_ai_judgment": "...",
  "corrected_judgment": "...",
  "reason": "...",
  "evidence_source_ids": ["..."],
  "changes_original_artifact": false
}
```

It must also identify its source review raw-file hash, use the fixed raw-file
hash rule above, and state its noncanonical status. A readable rendering may
accompany the JSON but cannot replace it.

## Human governance and future policy change

The anonymous-review protocol remains unchanged: only two separate,
independent human submissions, both immutable and hash-frozen, can meet its
precondition for unblinding and human adjudication. This amendment does not
approve or request that step.

Any later request to use AI-assisted evidence beyond this narrow v10 purpose
requires a new, separately versioned policy amendment that identifies its exact
scope, source hashes, authority, effective date, sunset, and all preserved
boundaries. It must not be inferred from this draft or from a completed
AI-assisted review.

## Sunset and revocation

If adopted, this amendment would expire automatically upon the earliest of:

1. a revocation record by the named Project Owner;
2. a new policy replacing it; or
3. any attempt to use it outside the exact v10 hashes above.

Expiration leaves all original Phase 5R policies and sealed artifacts
unchanged. It cannot retroactively create authority or erase a no-go state.

## Adoption checklist — intentionally incomplete

Before a Project Owner can adopt this draft, they must create the separate
adoption record from
`01_policies/phase5r_v10_ai_assisted_review_adoption_record_template.json`,
run the provider-free verifier with that record, and independently confirm that
no unresolved blind-key boundary incident and no change to the human-review,
unblinding, promotion, credential, email, scheduler, broker, account, order,
or execution boundaries is intended. This file alone is not an adoption record.
