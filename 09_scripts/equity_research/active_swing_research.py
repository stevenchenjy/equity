"""Active swing v3 routing; frozen v1/v2 engines, policies and ledgers stay intact."""
from __future__ import annotations

from pathlib import Path

import frozen_swing_runtime as runtime

VERSION = runtime.VERSION
POLICY = Path(runtime.POLICY)
OUTPUT = Path(runtime.OUTPUT)
SCHEMA = "equity_swing_research_v2"  # compatible projection shape; version distinguishes cohorts
AUTHORITY = {"research_only": True, "capital_authority": False,
             "actionable_quantity": 0, "automatic_action_allowed": False}


def _unavailable(current, reason):
    return {"schema_version": SCHEMA, "version": VERSION, "generated_at": current.isoformat(),
            "status": "waiting_on_data", "blockers": [reason], "candidates": [],
            "coverage": {"current": False, "screened": 0}, "review_windows": [],
            "rank_status": "unassessed", **AUTHORITY}


def build(root, current, **kwargs):
    try:
        return runtime.execute(root, "build", current=current, kwargs=kwargs)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "swing_runtime_unavailable"
        return _unavailable(current, reason)


def quote_targets(root, current, limit=3):
    try:
        return runtime.execute(root, "quote_targets", current=current, kwargs={"limit": limit})
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return []


def revalidate_projection(root, view, current, candidate_quote_context=None):
    try:
        return runtime.execute(root, "revalidate_projection", current=current, view=view,
                               kwargs={"candidate_quote_context": candidate_quote_context})
    except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "swing_runtime_unavailable"
        return _unavailable(current, reason)


def validated_records(root, current):
    return runtime.execute(root, "validated_records", current=current)


def _load(root, current):
    """Compatibility for existing benchmark consumers; validation is never skipped."""
    return validated_records(root, current)


def _verify(root, rows):
    runtime.execute(root, "verify_records", rows=rows)


def research_context(root, current):
    """Read-only admitted daily dataset and its exact source/implementation bindings."""
    return runtime.execute(root, "research_context", current=current)


def features(bars, *, root=None):
    """The same pinned 19-session breakout/reclaim/continuation feature calculation."""
    return runtime.execute(root, "features", bars=bars)


def features_many(bars_by_key, *, root=None):
    """Batch historical feature slices in one bounded pinned execution."""
    return runtime.execute(root, "features_many", bars_by_key=bars_by_key)


def baseline_context(root, baseline, bindings, current):
    """Freeze the same admitted canonical/tactical baseline or explicit unknown."""
    return runtime.execute(root, "baseline_context", current=current, baseline=baseline, bindings=bindings)
