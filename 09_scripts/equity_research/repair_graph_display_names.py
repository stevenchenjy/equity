#!/usr/bin/env python3
"""Repair narrowly scoped display names after Graphify's AST-only update.

No extraction, reclustering, model call, network access or strategy input changes.
Use the installed Graphify Python for --apply so the report can be regenerated.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

# Source identities, not legacy graph node IDs: IDs and relationships stay intact.
OLD_HEADINGS = {
    "00_project_control/account_reconciliation_policy.md": "Phase 5R-C9B Account Reconciliation Policy",
    "00_project_control/account_state_policy.md": "Phase 5R-C9 Account-State Policy",
    "00_project_control/action_threshold_policy.md": "Phase 5R-C9 Action Threshold Policy",
    "00_project_control/active_state_policy.md": "Phase 5R-C8 Canonical Active-State Policy",
    "00_project_control/ai_operating_decision.md": "Phase 5R AI operating decision",
    "00_project_control/core_allocation_policy.md": "Phase 5R-C9 Core Allocation Policy",
    "00_project_control/daily_decision_policy.md": "Phase 5R Daily Decision Policy",
    "00_project_control/daily_delivery_policy.md": "Phase 5R Daily Delivery Policy",
    "00_project_control/daily_research_policy.md": "Phase 5R Daily Research Policy",
    "00_project_control/dynamic_weight_policy.md": "Phase 5R-C9 Dynamic Weight Policy",
    "00_project_control/execution_policy.md": "Phase 5R-C9B Manual Execution Policy",
    "00_project_control/full_universe_data_policy.md": "Phase 5R-B2 Configured-Universe Data and Broad Discovery Policy",
    "00_project_control/macbook_github_macmini_workflow.md": "Phase5R MacBook → GitHub → Mac mini workflow",
    "00_project_control/price_guidance_policy.md": "Phase 5R-C9B Price Guidance Policy",
    "00_project_control/return_objective_policy.md": "Phase 5R Long-Horizon Return Objective Policy",
    "00_project_control/sec_acceptance_index_extension_policy.md": "Phase 5R SEC Acceptance-Index Extension Policy v1",
    "00_project_control/shadow_llm_evaluation_policy.md": "Phase 5R SHADOW_LLM Evaluation Policy",
    "08_reviews/shadow_llm/README.md": "Phase 5R SHADOW_LLM",
}
LEGACY_LABEL = re.compile(r"^Phase ?5R\b")


def plan_repair(root, graph, labels):
    """Return repaired copies plus source-bound changes; never alter input objects."""
    result, named = deepcopy(graph), dict(labels)
    changes, replacements = [], {}
    nodes = result["nodes"]
    for source, old in OLD_HEADINGS.items():
        matches = [n for n in nodes if n.get("source_file") == source
                   and n.get("source_location") == "L1" and n.get("label") == old]
        if not matches:
            continue
        if len(matches) != 1:
            raise ValueError(f"ambiguous legacy heading: {source}")
        path = root / source
        if not path.is_file():
            raise ValueError(f"heading source unavailable: {source}")
        heading = path.read_text(encoding="utf-8").splitlines()[0]
        if not heading.startswith("# Equity Research"):
            raise ValueError(f"source heading has not migrated: {source}")
        new = heading[2:]
        node = matches[0]
        node["label"] = new
        node["norm_label"] = "".join(
            c for c in unicodedata.normalize("NFD", new) if unicodedata.category(c) != "Mn"
        ).lower()
        replacements[node["id"]] = (old, new)
        changes.append({"kind": "source_heading", "id": node["id"], "source_file": source,
                        "source_location": "L1", "before": old, "after": new})

    communities, degree = defaultdict(list), Counter()
    for node in nodes:
        communities[str(node["community"])].append(node)
    for link in graph.get("links", graph.get("edges", [])):
        degree[link["source"]] += 1
        degree[link["target"]] += 1
    for cid, old in labels.items():
        if not LEGACY_LABEL.match(old):
            continue
        members = communities.get(str(cid), [])
        # A real historical member is supporting evidence. Never rename its title.
        if any(n.get("label") == old for n in members):
            continue
        supported = [replacements[n["id"]][1] for n in members
                     if n["id"] in replacements and replacements[n["id"]][0] == old]
        if supported:
            new, reason = sorted(set(supported))[0], "corrected source heading is a member"
        elif members:
            # Matches Graphify's deterministic highest-degree hub rule.
            hub = min(members, key=lambda n: (-degree[n["id"]], str(n["id"])))
            new = str(hub.get("label") or hub["id"]).strip()
            if new.endswith("()"):
                new = new[:-2]
            new, reason = new or f"Community {cid}", "cached label has no supporting member"
        else:
            # An orphan cache entry is retained; it is not a displayed community.
            continue
        if new != old:
            named[cid] = new
            changes.append({"kind": "community_label", "community": str(cid),
                            "before": old, "after": new, "reason": reason})
    return result, named, changes


def render_report(graph, labels, previous, graph_path):
    """Use installed Graphify report APIs without altering graph topology."""
    import networkx as nx
    from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    from graphify.cluster import score_all
    from graphify.report import generate, load_learning_for_report

    corpus = re.search(r"^- (\d+) files · ~([\d,]+) words$", previous, re.M)
    title = re.search(r"^# Graph Report - (.*?)  \(", previous, re.M)
    tokens = re.search(r"^- Token cost: ([\d,]+) input · ([\d,]+) output$", previous, re.M)
    if not corpus or not title or not tokens:
        raise ValueError("existing Graphify report provenance cannot be preserved")
    G = nx.node_link_graph(graph, edges="links")
    communities = defaultdict(list)
    for node in graph["nodes"]:
        communities[int(node["community"])].append(node["id"])
    named = {int(k): v for k, v in labels.items()}
    rendered = generate(
        G, dict(communities), score_all(G, communities), named, god_nodes(G),
        surprising_connections(G, communities),
        {"total_files": int(corpus[1]), "total_words": int(corpus[2].replace(",", ""))},
        {"input": int(tokens[1].replace(",", "")), "output": int(tokens[2].replace(",", ""))},
        title[1], suggested_questions=suggest_questions(G, communities, named),
        built_at_commit=graph.get("built_at_commit"),
        learning=load_learning_for_report(graph_path),
    )
    # This is a view repair, not a new extraction. Retain its recorded build date.
    return previous.splitlines()[0] + "\n" + rendered.split("\n", 1)[1]


def render_existing_html(graph, labels, path):
    if not path.exists():
        return False
    import networkx as nx
    from graphify.export import to_html

    G = nx.node_link_graph(graph, edges="links")
    communities = defaultdict(list)
    for node in graph["nodes"]:
        communities[int(node["community"])].append(node["id"])
    to_html(G, dict(communities), str(path),
            community_labels={int(k): v for k, v in labels.items()})
    return True


def atomic_write(path, content):
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true", help="apply and regenerate the report")
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / "graphify-out"
    graph_path, label_path = out / "graph.json", out / ".graphify_labels.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    labels = json.loads(label_path.read_text(encoding="utf-8"))
    fixed, named, changes = plan_repair(root, graph, labels)
    receipt = {
        "applied": args.apply, "changes": changes,
        "node_ids_preserved": [n["id"] for n in graph["nodes"]] == [n["id"] for n in fixed["nodes"]],
        "edges_preserved": graph.get("links") == fixed.get("links"),
        "model_calls": 0,
        "existing_html_refreshed": False,
    }
    if args.apply:
        report_path = out / "GRAPH_REPORT.md"
        # Render before publishing anything: dependency/format errors leave all outputs untouched.
        # Always render on apply so retrying after a partial derived-file publication heals the report.
        report = render_report(fixed, named, report_path.read_text(encoding="utf-8"), graph_path)
        if fixed != graph:
            atomic_write(graph_path, json.dumps(fixed, ensure_ascii=False, indent=2) + "\n")
        if named != labels:
            atomic_write(label_path, json.dumps(named, ensure_ascii=False, indent=2) + "\n")
        if report != report_path.read_text(encoding="utf-8"):
            atomic_write(report_path, report)
        receipt["existing_html_refreshed"] = render_existing_html(fixed, named, out / "graph.html")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if args.apply or not changes else 1


if __name__ == "__main__":
    raise SystemExit(main())
