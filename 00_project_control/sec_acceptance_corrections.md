# SEC acceptance clock corrections

The current collector can encounter a submissions timestamp that conflicts with
an immutable historical observation. A difference of eight hours is not proof of
a timezone and is not an automatic reconciliation rule. The existing historical
index, extension chain, old research source receipts and frozen momentum inputs
remain unchanged.

The optional current correction layer binds the exact accession, CIK, ticker,
issuer name, form and filing date to three retained primary responses: the current
SEC submissions JSON, official archive header and official filing index. The
archive header and index must agree on the wall-clock acceptance time. EDGAR's
Eastern processing clock is documented in the [SEC EDGAR Filer Manual, Volume II, July 2018, sections 2.3.1 and 10.1](https://www.sec.gov/info/edgar/edgarfm-vol2-v47.pdf). Interpreting the agreeing archive wall clocks on that documented basis yields the canonical instant; this is distinct from accepting either conflicting JSON representation. The time is converted with `America/New_York`; ambiguous or nonexistent DST
times, changed identities, conflicting archive clocks, missing bytes, wrong
hashes and future knowledge fail validation. The original and observed clocks,
corrected instant, observation times and admission time are recorded separately.

Correction artifacts live in
`03_source_data/equity_research/sec_acceptance_corrections/` as an append-only,
hash-linked `sec_acceptance_correction_vN.json` chain. Original proof bytes are
content-addressed `.raw` files in `02_filings/sec_acceptance_proofs/`. The existing
SEC extension lock protects admission. Collection requires the existing explicit
public-network option. A retry of identical proof is a no-op; existing chain
members and proof bytes cannot be rewritten.

Current evidence, maintained thesis and earnings readers validate this layer.
Historical reads can validate an original signed source timestamp only against
its exact correction proof, while requiring the corrected acceptance instant to
precede the retained fetch/review. A new source-bound amendment must use the
canonical instant. An `as_of` read cannot use corrections admitted later. Frozen
experiment versions do not implicitly acquire this new reader.

The runtime Git guard accepts new correction artifacts and raw proof files only
after validating the complete immutable-index/extension/correction chain. Every
new raw path must be an exact SHA filename referenced by that chain, with the
same ownership, regular-file, single-link and size checks as other admitted SEC
evidence. Unknown files and edits to previously tracked corrections or proofs
still stop production. A remote advancement while valid local evidence is pending
requires preservation in source history before a fast-forward deployment.

These corrections establish source timing, not business quality, attractive
valuation, order facts or investment performance. Strategy, numerical quality,
allocation, tactical risk, experiment adoption and human execution authority
remain governed by their existing policies.
