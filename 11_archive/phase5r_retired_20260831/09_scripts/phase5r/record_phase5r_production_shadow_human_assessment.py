#!/usr/bin/env python3
"""Append one offline human-usefulness assessment to the shadow ledger.

This command never constructs a provider, accesses credentials, sends email,
or changes a deterministic decision.  It does not modify any completed shadow
result; it adds one hash-chained quality-ledger event only.
"""

from __future__ import annotations

import argparse
import json

from phase5r_production_shadow_v1 import (
    ProductionShadowBlocked,
    ProductionShadowError,
    record_human_usefulness,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--usefulness", required=True, choices=("useful", "not_useful"))
    parser.add_argument(
        "--assessment-code",
        required=True,
        choices=(
            "materially_improved_review",
            "identified_usable_evidence_issue",
            "not_actionable_for_human_review",
            "insufficient_evidence_for_human_review",
        ),
    )
    args = parser.parse_args()
    try:
        result = record_human_usefulness(
            run_id=args.run_id,
            usefulness=args.usefulness,
            assessment_code=args.assessment_code,
        )
    except (ProductionShadowBlocked, ProductionShadowError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "phase5r_production_shadow_v1",
                    "outcome": "blocked",
                    "reason": str(exc),
                    "canonical_effect": False,
                    "provider_constructed": False,
                    "provider_called": False,
                    "email_attempted": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
