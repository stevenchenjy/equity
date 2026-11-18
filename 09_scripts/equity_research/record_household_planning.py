"""Validate and retain an owner-approved balance observation or dated household research."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from daily_common import ExclusiveFileLock, atomic_write_text, now_et
from household_planning import CONFIG, MANIFEST, RESEARCH_MANIFEST, SOURCE_DIR, planning_context, research_context
from run_runtime_scheduler import RUNTIME_LOCK_PATH


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def retain(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Retained household artifact differs from its digest.")
    else:
        atomic_write_text(path, data.decode("utf-8"))


def record(root, kind, proposed, source, *, expected=None, apply=False):
    is_assets = kind == "assets"
    dest = Path(MANIFEST if is_assets else RESEARCH_MANIFEST)
    prefix, suffix = ("broker_observation", ".json") if is_assets else ("plan_source", ".md")
    raw = source.read_bytes()
    source_hash = digest(raw)
    relative = SOURCE_DIR / (source_hash + suffix)
    if (proposed[prefix + "_sha256"] != source_hash or proposed[prefix + "_path"] != str(relative)):
        raise ValueError("Proposal and supplied original bytes differ.")
    payload = (json.dumps(proposed, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    root = root.resolve()
    with ExitStack() as stack:
        if apply:
            for lock in (RUNTIME_LOCK_PATH, root / "00_project_control/run_logs/daily_pipeline.lock"):
                stack.enter_context(ExclusiveFileLock(lock))
        previous = (root / dest).read_bytes() if (root / dest).is_file() else None
        prior_hash = digest(previous) if previous is not None else "absent"
        if apply and expected != prior_hash and previous != payload:
            raise ValueError("Active household input changed since preview.")
        with TemporaryDirectory() as directory:
            preview = Path(directory)
            for path in (Path(CONFIG), Path("05_risk_and_positions/current_account_state.local.json"),
                         Path("05_risk_and_positions/current_positions.local.csv")):
                (preview / path).parent.mkdir(parents=True, exist_ok=True)
                (preview / path).symlink_to(root / path)
            (preview / SOURCE_DIR).mkdir(mode=0o700, exist_ok=True)
            (preview / relative).write_bytes(raw)
            (preview / dest).write_bytes(payload)
            if not is_assets:
                context = planning_context(root, now_et())
            else:
                context = planning_context(preview, now_et())
            if not context or context["status"] != "observed" or not context["chase_ledger_matches"]:
                raise ValueError("Current Chase ledger and source-bound household observation must reconcile.")
            view = context if is_assets else research_context(preview, now_et(), context)
            if not is_assets and view["status"] != "research_only":
                raise ValueError("Research did not validate with an unexpired decision window: " + str(view))
        clock_key = "observed_at" if is_assets else "authored_at"
        if previous and previous != payload:
            if datetime.fromisoformat(proposed[clock_key]) <= datetime.fromisoformat(json.loads(previous)[clock_key]):
                raise ValueError("Revisions require a later dated observation or research judgment.")
        if apply:
            (root / SOURCE_DIR).mkdir(mode=0o700, exist_ok=True)
            retain(root / relative, raw)
            if previous:
                retain(root / SOURCE_DIR / (prior_hash + ".manifest.json"), previous)
            retain(root / SOURCE_DIR / (digest(payload) + ".manifest.json"), payload)
            if previous != payload:
                atomic_write_text(root / dest, payload.decode())
            if (root / dest).read_bytes() != payload or (root / relative).read_bytes() != raw:
                raise ValueError("Household record readback failed.")
        return {"mode": "applied" if apply else "preview", "manifest": str(dest), "prior": prior_hash,
                "sha256": digest(payload), "source_sha256": source_hash, "status": view["status"],
                "household_total_usd": context["household_total_usd"], "review_count": len(view.get("calls", []))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--kind", choices=("assets", "research"), required=True)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected", help="Active digest or 'absent' from preview, required on apply")
    args = parser.parse_args()
    if args.apply and not args.expected:
        parser.error("--apply requires --expected from the preview")
    print(json.dumps(record(args.root, args.kind, json.loads(args.input.read_bytes()), args.source,
                            expected=args.expected, apply=args.apply), indent=2))


if __name__ == "__main__":
    main()
