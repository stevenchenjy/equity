#!/usr/bin/env python3
"""Read-only audit of current display surfaces; legacy protocol IDs are allowed."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

from repair_graph_display_names import plan_repair

OLD_NAME = re.compile(r"\bPhase\s*5R(?:-[A-Za-z0-9]+)?\b", re.I)
DISPLAY_PATHS = (
    "07_automation/email_briefs/daily_email_brief.txt",
    "07_automation/email_briefs/daily_email_brief.html",
    "04_research/company_research/daily_decision.md",
    "00_project_control/daily_verification_report.md",
    "04_research/company_research/daily_verification_report.md",
)


def tracked_markdown(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", "--", "*.md"],
        check=True, capture_output=True,
    )
    return [p.decode() for p in result.stdout.split(b"\0") if p]


def active_document(path: str) -> bool:
    return path == "README.md" or path.startswith((
        "00_project_control/", "01_policies/", "08_reviews/",
    ))


def first_heading(content: str) -> str:
    return next((line.strip() for line in content.splitlines() if line.strip()), "")


def audit(root: Path, paths: list[str], runtime_root: Path | None = None) -> list[str]:
    issues: list[str] = []
    tracked = set(paths)
    for name in paths:
        if not active_document(name):
            continue
        path = root / name
        if path.is_file() and OLD_NAME.search(first_heading(path.read_text(encoding="utf-8"))):
            issues.append(f"current document heading: {name}")

    display_path = root / "01_policies/equity_display_names.json"
    if display_path.is_file():
        config = json.loads(display_path.read_text(encoding="utf-8"))
        values = [config.get(key, "") for key in (
            "brand", "subject_label", "email_tagline", "alert_title", "alert_message",
        )] + list(config.get("reports", {}).values())
        if any(isinstance(value, str) and OLD_NAME.search(value) for value in values):
            issues.append("current display configuration")

    out = root / "graphify-out"
    graph_path, label_path = out / "graph.json", out / ".graphify_labels.json"
    if graph_path.is_file() and label_path.is_file():
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        labels = json.loads(label_path.read_text(encoding="utf-8"))
        for node in graph.get("nodes", []):
            source = str(node.get("source_file", ""))
            if (source in tracked and active_document(source)
                    and node.get("source_location") == "L1"
                    and OLD_NAME.search(str(node.get("label", "")))):
                issues.append(f"current Graphify node: {source}")
        _, _, changes = plan_repair(root, graph, labels)
        if changes:
            issues.append(f"Graphify display cache needs repair: {len(changes)} changes")
        report = out / "GRAPH_REPORT.md"
        if report.is_file() and re.search(r"^#{2,4} Community.*Phase\s*5R\b", report.read_text(encoding="utf-8"), re.M | re.I):
            issues.append("Graphify report community title")

    display_roots = [("source", root)]
    if runtime_root is not None and runtime_root.resolve() != root.resolve():
        display_roots.append(("runtime", runtime_root))
    for location, display_root in display_roots:
        for name in DISPLAY_PATHS:
            path = display_root / name
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            if name.endswith(".html"):
                titles = re.findall(r"<(?:title|h1)[^>]*>(.*?)</(?:title|h1)>", content, re.I | re.S)
                bad = any(OLD_NAME.search(re.sub(r"<[^>]+>", "", item)) for item in titles)
            elif name.endswith(".txt"):
                bad = OLD_NAME.search("\n".join(content.splitlines()[:20])) is not None
            else:
                bad = OLD_NAME.search(first_heading(content)) is not None
            if bad:
                issues.append(f"{location} display title: {name}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--runtime-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    issues = audit(root, tracked_markdown(root), args.runtime_root)
    print(json.dumps({"status": "PASS" if not issues else "FAIL", "issues": issues}, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
