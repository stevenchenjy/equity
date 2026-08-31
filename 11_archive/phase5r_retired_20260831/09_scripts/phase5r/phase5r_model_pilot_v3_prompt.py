"""Exact analyst prompt binding for a future, separately authorized v3 pilot.

This module is intentionally offline-only.  It neither constructs a provider
nor executes a pilot.  The appendix is additive: the closed contract remains
the authority that rejects invented or incorrectly paired citations.
"""

from __future__ import annotations

import run_phase5r_model_pilot as v1


CITATION_BINDING_APPENDIX = (
    "For every source_ids entry, copy the matching cited_excerpt_sha256 "
    "verbatim from the visible packet source catalog, in the same one-to-one "
    "order.",
    "Do not invent, truncate, recompute, or substitute a source ID or excerpt "
    "hash.",
    "Use only qualitative claim text with no digits, percentages, currency, or "
    "quantities unless a visible reconciled calculation_id is supplied and "
    "cited.",
    "For medium or high materiality, cite a primary packet-local source for "
    "the same ticker.",
)


V3_ASSESSMENT_INSTRUCTIONS = (
    v1.ASSESSMENT_INSTRUCTIONS
    + "\n\nCitation-binding checklist (all requirements are mandatory):\n"
    + "\n".join(f"- {instruction}" for instruction in CITATION_BINDING_APPENDIX)
)


def assessment_instructions() -> str:
    """Return the sealed additive instructions a future v3 executor must bind."""

    return V3_ASSESSMENT_INSTRUCTIONS
