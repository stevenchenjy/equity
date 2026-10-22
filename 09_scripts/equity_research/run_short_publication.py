#!/usr/bin/env python3
"""Recompose current public context within an active short claim; never send."""
import argparse
import json
from pathlib import Path
from daily_common import ROOT
from short_publication import run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--claim-id", required=True)
    args = parser.parse_args()
    try:
        result = run(args.root, args.claim_id)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps({"outcome": "not_refreshed", "reason": str(error), "email_sent": False}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result["outcome"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
