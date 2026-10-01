"""Version-bound presentation notes; never a research or account input."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SUMMARY_PATH = "07_automation/dashboard.local/plan_summaries.json"
SCHEMA = "equity_dashboard_plan_summaries_v1"
SECTIONS = ("reason", "counterargument", "conditions")


def source_hash(plan: dict) -> str:
    purpose = plan.get("purpose", {})
    text = {"reason": plan.get("reason", ""), "counterargument": plan.get("counterargument", ""),
            **{k: purpose.get(k, "") for k in ("entry_validity", "failure_condition", "exit_rule")}}
    return hashlib.sha256(json.dumps(text, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def binding(plan: dict) -> tuple:
    return tuple(plan.get(k) for k in ("ticker", "plan_id", "version", "record_hash"))


def validate_catalog(payload: object, plans: list[dict] | None = None) -> list[dict]:
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA:
        raise ValueError("invalid_summary_schema")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 500:
        raise ValueError("invalid_summary_entries")
    current = {binding(p): p for p in plans} if plans is not None else None
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("invalid_summary_entry")
        if not isinstance(entry.get("ticker"), str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", entry["ticker"]):
            raise ValueError("invalid_summary_ticker")
        if not isinstance(entry.get("plan_id"), str) or not entry["plan_id"] or len(entry["plan_id"]) > 200:
            raise ValueError("invalid_summary_plan")
        if type(entry.get("version")) is not int or entry["version"] < 1:
            raise ValueError("invalid_summary_version")
        if any(not isinstance(entry.get(k), str) or not re.fullmatch(r"[0-9a-f]{64}", entry[k]) for k in ("record_hash", "source_sha256")):
            raise ValueError("invalid_summary_hash")
        key = binding(entry)
        if key in seen:
            raise ValueError("duplicate_summary")
        seen.add(key)
        sections = entry.get("sections")
        if not isinstance(sections, dict) or set(sections) != set(SECTIONS):
            raise ValueError("invalid_summary_sections")
        for points in sections.values():
            if not isinstance(points, list) or not 1 <= len(points) <= 5:
                raise ValueError("invalid_summary_points")
            for point in points:
                if not isinstance(point, dict) or set(point) != {"label", "text"}:
                    raise ValueError("invalid_summary_point")
                if any(not isinstance(point[k], str) or not point[k].strip() or len(point[k]) > limit for k, limit in (("label", 40), ("text", 400))):
                    raise ValueError("invalid_summary_text")
        if current is not None and (key not in current or source_hash(current[key]) != entry["source_sha256"]):
            raise ValueError("summary_source_changed")
    return entries


def catalog(raw: bytes | None) -> list[dict]:
    try:
        return validate_catalog(json.loads(raw)) if raw else []
    except (ValueError, TypeError, UnicodeDecodeError):
        return []


def matching_summary(plan: dict, entries: list[dict]) -> dict | None:
    for entry in entries:
        if binding(entry) == binding(plan) and entry["source_sha256"] == source_hash(plan):
            return entry["sections"]
    return None


def main() -> int:
    from server import DEFAULT_ROOT, RUNTIME_LOCK, read_snapshot, safe_read
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_ROOT)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--template", action="store_true")
    choice.add_argument("--input", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.template and args.apply:
        parser.error("--apply requires --input")
    root = args.runtime_root.resolve()
    with ExitStack() as stack:
        # Presentation writes use the same lock order; no account writer or refresh.
        for path in (RUNTIME_LOCK, root / "00_project_control/run_logs/daily_pipeline.lock"):
            handle = stack.enter_context(path.open("a+"))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plans = read_snapshot(root)["plans"]
        if args.template:
            payload = {"schema_version": SCHEMA, "entries": [
                {**dict(zip(("ticker", "plan_id", "version", "record_hash"), binding(p))),
                 "source_sha256": source_hash(p), "sections": {s: [] for s in SECTIONS}}
                for p in plans]}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        payload = json.loads(args.input.read_text())
        entries = validate_catalog(payload, plans)
        if args.apply:
            path = root / SUMMARY_PATH
            # Reuse the dashboard's symlink/path boundary check before reading.
            prior = catalog(safe_read(root, SUMMARY_PATH)) if path.exists() else []
            merged = {binding(e): e for e in prior}
            merged.update({binding(e): e for e in entries})
            output = {"schema_version": SCHEMA, "entries": list(merged.values())[-500:]}
            for parent in (path, *path.parents):
                if parent == root.parent:
                    break
                if parent.is_symlink():
                    raise ValueError("symlink_summary_path")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd, name = tempfile.mkstemp(dir=path.parent, prefix=".summary-")
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(output, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        print(json.dumps({"validated": len(entries), "applied": args.apply, "canonical_effect": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
