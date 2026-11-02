"""Active v3 outcome-review routing; the legacy v2 review writer is preserved."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import frozen_swing_runtime as runtime

OUTPUT = Path(runtime.OUTPUT)
STORE = OUTPUT / "outcome_reviews.jsonl"
SCHEMA = "equity_swing_outcome_review_v1"


def validate(root, proposal, current, *, history_current=None):
    kwargs = {"history_current": history_current.isoformat()} if history_current is not None else {}
    result = runtime.execute(root, "review_validate", current=current, proposal=proposal, kwargs=kwargs)
    return result["value"], {key:base64.b64decode(value, validate=True) for key,value in result["raw_sources"].items()}


def read_reviews(root, current):
    return runtime.execute(root, "read_reviews", current=current)


def review(root, proposal, current, *, apply=False):
    return runtime.execute(root, "review", current=current, proposal=proposal, kwargs={"apply": apply})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--apply",action="store_true")
    args=parser.parse_args()
    result=review(args.root,json.loads(args.input.read_text()),datetime.now(ZoneInfo("America/New_York")),apply=args.apply)
    print(json.dumps(result,sort_keys=True));return 0


if __name__=="__main__":
    raise SystemExit(main())
