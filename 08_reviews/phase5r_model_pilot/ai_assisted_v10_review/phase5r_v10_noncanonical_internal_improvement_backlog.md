# Phase 5R v10 — Noncanonical Internal Improvement Backlog

Status: **internal quality work only; not a v10 rerun, protocol completion, or
promotion path.**

This backlog implements the Project Owner's limited-use direction. It uses the
completed AI-assisted review only to improve future prompts, evidence handling,
citation checks, critic logic, confidence calibration, and presentation. It
does not modify a sealed v10 artifact, access the blind key, unblind a runtime
assignment, initiate a repository-side model/provider request, or create a
canonical decision. An already-authorized interactive AI session, if disclosed
for a future-v2 internal artifact, is provenance only, is presumed
non-independent, and neither changes v10 status nor satisfies a human-review
requirement.

## Implemented offline guardrail

`09_scripts/phase5r/phase5r_llm_internal_quality.py` provides a deterministic
manual-review sidecar for four recurring scope risks:

1. comparison direction without a verified baseline, period, and unit;
2. period binding that is not visibly established in the cited excerpt;
3. superlative, aggregate-dependence, or concentration wording without direct
   scope support; and
4. claimed transaction terms that may exist only in attached or incorporated
   material rather than the cited excerpt itself.

The sidecar flags review work; it never declares a claim true/false or changes
a research classification. Its critic-overlap helper always reports
`not_established`: without a reference list it reports no alignment, and with
a caller-supplied, unverified reference list it can report observed overlap
only. Neither case establishes critic incremental value, reviewer independence,
error rates, or promotion readiness.

## Implemented future-v2 evidence-contract sidecar

`09_scripts/phase5r/phase5r_llm_evidence_contract_v2.py` now provides a
separate, repository-provider-free contract prototype for a future workflow.
It is not imported by `run_phase5r_model_pilot.py`,
`run_phase5r_model_pilot_v2.py`, or any sealed v10 path.

The sidecar requires a normalized metadata catalog whose source IDs, excerpt
hashes, tickers, and calculation IDs bind to a packet-local source catalog. A
separate source-text artifact must exactly cover packet sources and match their
raw UTF-8 excerpt hashes: for each source it hashes decoded `excerpt_text`
encoded as UTF-8 and compares that SHA-256 to the packet `content_sha256`. Its
`source_texts_canonical_json_sha256` is a canonical-JSON binding, while the
handoff separately freezes the source-text JSON file by exact raw bytes. These
checks establish identity and structural consistency only. They do not establish
semantic correctness of metric, unit, period, support role, claim truth, or numeric
reconciliation. The sidecar then validates a distinct v2 analyst binding
record with structured periods, closed units, per-citation support roles,
deterministic lexical scope flags, explicit dated comparison baselines, and
calculation bindings. Both the complete analyst response and each underlying
analyst claim are canonically hashed into that binding record, so a sidecar
cannot silently relabel, reorder, or partially substitute the analyst's cited
sources, hashes, calculations, ticker, or materiality.

Critic coverage is separately bound to a complete committee-response snapshot,
each original ticker decision, and the committee's claim IDs; the committee
must cover the complete analyst-claim universe. Issues must identify valid
affected claims, compatible cited sources, and the required support role;
failed review dimensions require a typed issue. This prevents a critic from
obtaining a nominal full-coverage result merely because a fabricated or
truncated committee summary omitted a claim. Full claim-ID coverage and issue
linkage are structural properties only; they do not establish that issues are
substantively correct, that the critic is independent, or that it adds
measurable value.

It remains noncanonical: each v2 sidecar requires `canonical_effect: false`.
Critic issue-set overlap is caller-supplied and unverified, so critic
incremental value remains `not_established` even when a reference list is
present; it cannot establish reviewer independence, error rates, or promotion
readiness. The prototype neither constructs nor authorizes a repository-side
provider call and has no network, credential, broker, account, email, order,
or execution code. An `interactive_ai_session` field, when present, is a
passive disclosure rather than a provider-call authorization.

## Implemented future-v2 offline handoff boundary

`09_scripts/phase5r/phase5r_llm_evidence_contract_v2_handoff.py` verifies a
candidate sidecar handoff only inside a designated future handoff directory;
it does not make that directory immutable. A future consumer must re-verify
immediately before consuming the bytes it opens. It accepts no arbitrary
artifact paths: the directory must contain the fixed manifest and eight fixed
JSON filenames. Each is read as a non-symlink regular file with one link by
fixed basename relative to one no-follow directory descriptor, avoiding both
symlink/path re-resolution and hard-link substitution. Each must be strict
UTF-8 JSON without BOM, CR line endings, duplicate object keys, nonstandard
`NaN`/`Infinity` constants (including exponent overflow), numeric literals that
exceed bounded digit/exponent limits or do not round-trip through Python's
normalized finite float representation, or unpaired Unicode surrogates, and is
bound by SHA-256 of its exact raw bytes. This is a decimal round-trip policy,
not a claim that every accepted decimal is exactly representable in binary
IEEE-754; exact raw bytes remain the identity rule. Files are opened
nonblocking, must be no larger than 8 MiB each, and have a bounded JSON nesting
depth before schema validation; FIFO and oversized-artifact inputs fail closed.

The caller must provide a separately retained, structured owner-approval
reference that names the manifest raw-byte SHA-256 and packet ID and locks all
human-review, canonical, unblinding, provider, runtime, action, broker, and
email authority fields to `false`. The verifier validates only that closed
record shape and returns the manifest digest; it neither creates nor amends an
approval record and cannot verify the owner's identity, signature, or
real-world authority. It detects a manifest or packet mismatch against the
supplied reference, but an unsigned caller-supplied reference cannot prevent
substitution of both records; external retention and real-world identity,
signature, and authority verification remain outside this verifier. The
verifier snapshots the closed scalar reference before it opens a handoff file,
and requires `effective_at_et` to carry the valid Eastern offset for that
instant. That is not proof of a claimed named timezone; if local
`America/New_York` timezone data is unavailable, validation fails closed. Its
provenance fields are explicitly *attestations*, not proof that a prior runtime
used no provider or network. `generation_provenance` separates a
repository-initiated provider call (always false) from a disclosed interactive
AI session, which must list provider, model family, time-zoned review date, and
reasoning configuration; it is presumed non-independent, and its external
evidence, tools/browse, and repository-call fields remain false. The verifier
itself makes no repository provider or network call.

The handoff result deliberately separates `procedure_status: completed`,
`integrity_status: raw_bytes_and_contract_bindings_validated`, and
`authority_status: noncanonical_internal_quality_only` from
`substantive_status: not_established`. It also reports normalized metadata as
`hash_bound_but_not_semantically_verified` and false for upstream packet
validation, semantic validation, numeric reconciliation, reviewer
independence establishment, canonical effect, and all execution authority. A
disclosed interactive session is labeled `presumed_non_independent`, but that
status remains provenance-attested rather than independently verified. It is not a
substantive model-quality pass, a completed human review, or an authorization
to run a future pilot. `procedure_status: completed` means only that this
local verifier completed. `owner_approval_reference_schema_validated: true`
means only that its closed schema and false-boundary fields matched;
`owner_identity_or_signature_verified` remains false.

## Implemented future-v3 assertion-span prototype

`09_scripts/phase5r/phase5r_assertion_span_contract_v3.py` is a separate,
standard-library-only prototype; it is not imported by v2, a handoff verifier,
any historical pilot runner, scheduler, or provider component. It accepts a
caller-supplied packet and a closed sidecar bundle, then binds every source text
to the packet's source hash and every declared assertion to exact UTF-8 byte
spans in its cited excerpts. A span must have a matching source hash, valid byte
boundaries, a matching span hash, and a literal nontrivial overlap with the
assertion text. Numeric, unit, period, and common comparative cues such as
`up from … to …` must also appear in literal anchors before an assertion can be
marked structurally complete. Numeric cues include compact quantities such as
`10bn` and `10m`, scientific notation, forecast periods such as `FY26E`, and
adjacent dosage/unit forms such as `10mg`, including when followed by sentence
punctuation. Common direction cues include `surged`, `jumped`, `plunged`,
`doubled`, `halved`, `expanded`, and `contracted` as well as ordinary
increase/decrease wording. A non-stopword immediately governing a numeric
expression could still be hidden behind an arbitrary qualifier. Therefore,
for every stated numeric, textual, or period quantity, the prototype requires all
meaningful lexical tokens in its containing sentence (including trailing
relation words) as literal anchors; a decimal point is not mistaken for a
sentence boundary. This deliberately conservative structural rule can leave a
paraphrased source incomplete, but it does not depend on an exhaustive verb
list and prevents an unanchored direction, qualifier, negation, or comparison
from receiving a completed result. Literal matching uses Unicode-aware lexical
boundaries and includes material short qualifiers such as `q/q`, `ex`, `FY`,
and `CY`; it permits ordinary case changes without Unicode case-fold expansion, so a value such as
`10` cannot borrow `100`, `$10,000`, `-10%`, or `10μg`; a fragment cannot
borrow a hyphenated, Unicode-word, or combining-mark extension; and `ß` cannot
be relabeled as `ss`. It also treats leading-decimal and accounting-parenthesis
numeric forms, sign/inequality qualifiers, and percent suffixes as distinct
from an unsigned assertion token. Non-ASCII digit strings remain deterministic
numeric anchors rather than being silently treated as ASCII calendar years;
calendar grammar also binds fiscal half-years and common fused fiscal/calendar
quarter forms such as `Q1FY26`, `FY26Q1`, and `CY2026`. A language without
separable word boundaries must use a larger literal phrase/span rather than a
substring anchor. All required deterministic tokens must appear together in
one declared atomic literal anchor, and every anchor span must remain inside
one cited-source sentence. Thus a subject, direction, and quantity cannot be
assembled from unrelated anchors, sentences, sources, or clauses. This is
still a structural locality check, not semantic entailment: it cannot identify
negation, logical scope, or another nonliteral relation that surrounds an
otherwise exact phrase. Those questions remain `semantic_status: not_assessed`
and cannot be promoted from a completed v3 procedure. Source sentence
boundaries include common ASCII, Unicode, Arabic, and Devanagari terminal
punctuation plus CR/LF separators.

The v3 prototype treats a missing localizable span as
`anchor_not_available`, which yields `procedure_status: incomplete`; it never
substitutes a fabricated critic issue or a semantic pass. Even a fully anchored
result reports `semantic_status: not_assessed`,
`citation_accuracy_status: not_assessed`,
`substantive_recommendation: not_established`, `canonical_effect: false`, and
no execution authority. Its `assertion_origin_status` is explicitly
`caller_supplied_unverified`. It does not prove an excerpt entails an assertion,
does not bind that assertion to an upstream analyst response, and does not
create a v3 runtime, handoff, provider request, budget, reviewer
independence claim, or promotion path.

## Potential post-v3 extensions (not current v2/v3 behavior)

Do not retrofit these fields into v10 or its v1 frozen contract. Current v2
already implements normalized source metric/unit/period metadata,
source/calculation bindings, lexical scope flags, and critic claim/issue
identifiers; the separate v3 prototype adds literal assertion-to-span anchors.
A later, separately authorized version could add:

- per-source `citation_scope_by_source` with values such as `direct`,
  `partial`, or `context_only`;
- `claim_wording_flags` for comparative/trend, superlative/rank,
  aggregate/dependency, and transaction-term claims;
- a materiality-aware `partial`/`context_only` rejection threshold; and
- more granular critic issue taxonomies beyond the current typed fields.

A later version could reject a medium/high scope-sensitive claim whose evidence
is entirely `partial` or `context_only`, and should fail closed on period/unit
mismatch unless an explicit reconciled calculation supplies the conversion.

## Acceptance tests before any future integration

- Synthetic ARM-like comparison wording triggers a baseline/period check.
- Synthetic tender-offer wording that relies on an attached release triggers
  an incorporated-material scope check.
- Synthetic customer-concentration wording triggers a superlative/scope check.
- Critic incremental value is `not_established` both with no reference list and
  with a caller-supplied reference list; only unverified overlap is reported.
- Existing v10 plans, journals, receipts, anonymous bundle, completion state,
  and all original hashes remain untouched.
- A successful future handoff verification leaves every supplied manifest and
  fixed artifact byte-for-byte unchanged.
- The v2 sidecar accepts a valid, fully bound synthetic comparison and rejects
  stale excerpt hashes, missing source coverage, period/unit mismatches,
  missing baselines, unsupported citation roles, unresolved lexical-scope
  flags, multi-claim issues that borrow another claim's evidence, and invalid
  critic coverage.
- An AST regression fixes the permitted import roots for the future-only
  quality guard, v2 validator, v2 handoff, and v3 span sidecar. It rejects
  provider, pilot-runner, network, and execution modules plus builtin
  `__import__` dynamic loading; this proves their direct import boundary, not
  the truth of a provenance attestation.
- A future handoff rejects changed-but-still-parseable JSON, symlinked roots or
  files, hard-linked artifacts, duplicate JSON keys, nonstandard JSON numeric
  constants, overlong integers, out-of-bound numeric exponents, and decimal
  values that cannot round-trip through the declared finite-float policy,
  missing fixed artifacts, changed manifests without the separately retained
  structured owner-approval reference, and any authorization for unblinding,
  provider/network use, canonical effect, or execution. It rejects unknown
  generation provenance and labels remaining provenance attestations as
  `attested_not_verified`. Fixed artifact reads remain bound to the opened root
  descriptor even if the root path is replaced after opening. A malformed owner
  reference opens no handoff file, while an owner packet mismatch reads only the
  manifest required to detect it.
- A future workflow must re-verify a handoff immediately before consuming it;
  the handoff verifier proves only the bytes it opened during that invocation.
- The isolated v3 assertion-span prototype accepts multibyte UTF-8 spans only
  at valid byte boundaries, rejects stale source/span hashes and uncited source
  anchors, covers every assertion exactly once, and never reports semantic or
  canonical approval. Synthetic `999 percent` and `up from … to …` assertions
  without the required literal excerpt anchors cannot obtain a completed
  procedure status; required numeric, period, and comparative tokens must be
  together in one atomic literal anchor within one source sentence. Thus a
  `10bn` or `10m` assertion cannot borrow a different compact quantity, and a
  subject cannot borrow its direction or value from another clause. Scientific
  notation, compact `B`/`K`/`MM` quantities, forecast periods, signed values,
  thousands separators, Unicode digits, and spaced/adjacent dose units are
  likewise literal-bound rather than inferred from a nearby metric anchor.

Any integration into a future model call or contract requires separate explicit
authorization, a new versioned plan, a separately validated packet/analyst/
committee runtime contract, deterministic extraction or calculation
reconciliation for substantive numeric claims, and all existing safety and
budget gates.
