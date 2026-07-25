# Phase 5R Material-Transition Reference Rubric

Version: `phase5r_material_transition_reference_v1`  
Status: frozen scoring specification  
Scope: point-in-time research evaluation only; no trading or execution authority

## 1. Evidence boundary

Reviewers compare only the frozen prior/current packets, the exact SEC
acceptance times, hash-verified primary-source excerpts, deterministic
calculations, and the synthetic research context already bound to the case.
They must not use later filings, later market bars, later outcomes, current
knowledge, analyst price targets, or realized returns.

The case's candidate/held role and coarse portfolio constraints are assigned
deterministically before annotation. A reviewer must not change that context to
fit a preferred label. Future performance is never ground truth.

## 2. Required reviewer sequence

Each reviewer independently records:

1. whether the current packet contains a material long-horizon change relative
   to the prior packet;
2. the thesis direction: `strengthening`, `weakening`, `broken`, or
   `unchanged`;
3. exactly one closed research classification;
4. both packets' primary SEC source IDs;
5. a concise rationale that distinguishes fact, inference, and uncertainty.

Reviewers work independently before seeing each other's labels. A frozen
positive reference requires agreement by at least two distinct reviewers.
Disagreement is not silently discarded: it is counted, then either adjudicated
by a separately identified reviewer or excluded from the passing reference set.

## 3. Materiality

A change is material only when primary evidence could reasonably alter a
multi-quarter or multi-year thesis. Examples include:

- durable demand, unit economics, cash runway, solvency, regulatory status, or
  competitive-position changes;
- a new or removed going-concern, material-weakness, covenant, litigation, or
  cybersecurity risk;
- management guidance or strategy changes supported by filing evidence;
- a quantitative change that is reconciled to the correct entity, period, and
  unit and is large enough to affect the long-term case.

The following alone are not material:

- one daily price move, volume spike, or technical indicator;
- wording changes without changed economic meaning;
- an unsupported management adjective;
- a later outcome unavailable at the case as-of time;
- a missing datum. Missing evidence normally produces `abstain`.

## 4. Thesis direction

- `strengthening`: new primary evidence materially improves the durable thesis
  and does not introduce an equally material unresolved contradiction.
- `weakening`: new primary evidence materially reduces thesis quality, but the
  central thesis is not demonstrably invalidated.
- `broken`: high-materiality, medium/long-term primary evidence contradicts a
  necessary thesis premise.
- `unchanged`: no material long-horizon change is established.

## 5. Research classification

- `reject`: the candidate context fails the long-term evidence threshold.
- `watchlist`: evidence is interesting but insufficient, contradictory, or
  missing an action gate.
- `hold_existing`: the held-position thesis remains intact and no change review
  is justified.
- `paper_trade_candidate`: a candidate context has sufficient primary evidence
  for simulated validation, but not real-action eligibility.
- `real_trade_candidate`: all evidence, market-data, portfolio, stability, and
  policy gates are satisfied. Historical SEC evidence alone cannot establish
  this label.
- `trim_review`: a held context has a material weakening that justifies human
  exposure review but does not prove a broken thesis.
- `exit_review`: a held context has a primary-supported broken thesis. This is a
  research-review label, not an instruction.
- `abstain`: evidence, provenance, context, arithmetic, or reviewer confidence
  is insufficient to choose another label safely.

## 6. Positive and negative controls

The passing set must include at least 50 independently reviewed material
transitions and at least 50 deterministic no-change controls. A no-change
control uses the same packet and context on both sides; it must produce
`material_transition_detected=false`, `thesis_direction=unchanged`, and a
no-action classification. Any action-changing label on a no-change control is a
false transition.

Unsafe opposite-direction errors are always zero-tolerance:

- strengthening evidence classified as `trim_review` or `exit_review`;
- weakening/broken evidence classified as `paper_trade_candidate` or
  `real_trade_candidate`;
- unchanged evidence classified as any action transition.

## 7. Annotation integrity

Every stored consensus and reviewer rationale is retained as inspectable UTF-8
text and bound by SHA-256. Reviewer identities are stored only as distinct
one-way hashes. The annotation set records reviewer count, unanimous count,
disagreement count, adjudicated count, and agreement percentage. Hash-only
rationales, duplicate reviewers, missing primary sources, or an unbound rubric
invalidate the set.

## 8. Authority boundary

These labels evaluate model research quality. They cannot send email, modify
canonical C9 output, connect to a broker, create an order, or authorize a real
trade.
