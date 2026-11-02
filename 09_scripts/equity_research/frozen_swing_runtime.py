"""Verified, isolated runtime for the separately versioned active swing study.

The Git snapshot pins all engine/helper bytes. The manifest also pins the live
adapter and namespace binding; neither helper edits nor adapter edits silently
change a captured experiment. No network or brokerage API is used.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile

CONFIG = Path("01_policies/swing_runtime_v3.json")
CODE_REPOSITORY = Path(__file__).resolve().parents[2]
HEX = re.compile(r"[0-9a-f]{64}")
VERSION = "daily-swing-review-windows-v3-20261101"
POLICY = "01_policies/swing_research_v3.json"
OUTPUT = "08_reviews/swing_research_v3.local"
ADAPTERS = ("active_swing_research.py", "active_swing_outcome_review.py", "frozen_swing_runtime.py")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def binding(archive):
    return {"version": VERSION, "policy": POLICY, "output": OUTPUT,
            "engine_module": "swing_research_v2", "projection_schema": "equity_swing_research_v2",
            "git_commit": archive["git_commit"], "runtime_sha256": archive["runtime_sha256"],
            "policy_sha256": archive["policy_sha256"], "adapter_files": archive["adapter_files"]}


def load_registry(root):
    value = json.loads((Path(root) / CONFIG).read_bytes())
    if (value.get("schema_version") != "equity_frozen_swing_runtime_v1"
            or value.get("version") != VERSION or value.get("policy") != POLICY or value.get("output") != OUTPUT
            or value.get("automatic_action_allowed") is not False or value.get("capital_authority") is not False
            or value.get("actionable_quantity") != 0):
        raise ValueError("swing_runtime_registry_invalid")
    files, adapters = value.get("runtime_files"), value.get("adapter_files")
    if (not isinstance(value.get("git_commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", value["git_commit"])
            or not isinstance(files, dict) or not files or digest(json_bytes(files)) != value.get("runtime_sha256")
            or not isinstance(adapters, dict) or set(adapters) != set(ADAPTERS)):
        raise ValueError("swing_runtime_manifest_invalid")
    if (not HEX.fullmatch(str(value.get("policy_sha256")))
            or digest((Path(root) / POLICY).read_bytes()) != value["policy_sha256"]):
        raise ValueError("swing_runtime_policy_identity_changed")
    directory = Path(__file__).resolve().parent
    for name, expected in adapters.items():
        path = directory / name
        if not HEX.fullmatch(str(expected)) or path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError("swing_runtime_adapter_identity_changed")
    return value


def _imports(raw):
    for node in ast.walk(ast.parse(raw)):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split(".")[0]


@contextmanager
def verified_snapshot(archive, repository=None):
    repository = Path(repository) if repository is not None else CODE_REPOSITORY
    files = archive.get("runtime_files")
    if (not isinstance(files, dict) or not files or digest(json_bytes(files)) != archive.get("runtime_sha256")
            or not isinstance(archive.get("git_commit"), str) or not re.fullmatch(r"[0-9a-f]{40}", archive["git_commit"])):
        raise ValueError("swing_runtime_manifest_invalid")
    for name, expected in files.items():
        path = Path(name)
        if (path.is_absolute() or ".." in path.parts or not HEX.fullmatch(str(expected))
                or not name.startswith(("09_scripts/equity_research/", "01_policies/"))
                or path.suffix not in {".py", ".json"} or "tests" in path.parts):
            raise ValueError("swing_runtime_manifest_invalid")
    try:
        raw = subprocess.check_output(["git", "archive", archive["git_commit"], *sorted(files)],
                                      cwd=repository, stderr=subprocess.DEVNULL, timeout=30)
        tree = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", archive["git_commit"], "09_scripts/equity_research"],
                                       cwd=repository, text=True, stderr=subprocess.DEVNULL, timeout=30).splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError("swing_runtime_git_snapshot_unavailable") from exc
    modules = {Path(name).stem: name for name in tree if name.endswith(".py") and "/tests/" not in name}
    with tempfile.TemporaryDirectory(prefix="equity-swing-v3-frozen-") as temporary:
        root = Path(temporary)
        try:
            with tarfile.open(fileobj=io.BytesIO(raw)) as bundle:
                members = {m.name: m for m in bundle.getmembers() if m.isfile()}
                if set(members) != set(files):
                    raise ValueError("swing_runtime_snapshot_identity_changed")
                for name, expected in files.items():
                    content = bundle.extractfile(members[name]).read()
                    if digest(content) != expected:
                        raise ValueError("swing_runtime_snapshot_identity_changed")
                    target = root / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            required, visited = {"swing_research_v2", "swing_outcome_review"}, set()
            while required:
                name = required.pop()
                if name in visited:
                    continue
                relative = modules.get(name)
                if relative not in files:
                    raise ValueError("swing_runtime_dependency_missing")
                visited.add(name)
                required.update(set(_imports((root / relative).read_bytes())) & set(modules) - visited)
            for relative in ["01_policies/equity_display_names.json", "01_policies/swing_research.json"]:
                if relative not in files:
                    raise ValueError("swing_runtime_dependency_missing")
            directory = root / "09_scripts/equity_research"
            source = Path(__file__).resolve().parent
            for name, expected in archive["adapter_files"].items():
                content = (source / name).read_bytes()
                if digest(content) != expected:
                    raise ValueError("swing_runtime_adapter_identity_changed")
                (directory / name).write_bytes(content)
            # A JSON object containing strings/maps is also a valid Python
            # expression. The .py suffix includes it in the unchanged engine's
            # retained-implementation verifier, which hashes every *.py file.
            (directory / "active_swing_runtime_binding.py").write_bytes(json_bytes(binding(archive)))
        except (tarfile.TarError, SyntaxError) as exc:
            raise ValueError("swing_runtime_snapshot_invalid") from exc
        yield root


DRIVER = r'''
import base64,json,sys
from datetime import datetime
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(sys.argv[1])/"09_scripts/equity_research"))
import swing_research_v2 as engine
import swing_outcome_review as reviews
request=json.load(sys.stdin)
namespace=json.loads((Path(sys.argv[1])/"09_scripts/equity_research/active_swing_runtime_binding.py").read_bytes())
engine.VERSION=namespace["version"]
engine.POLICY=Path(namespace["policy"])
engine.OUTPUT=Path(namespace["output"])
reviews.OUTPUT=engine.OUTPUT
reviews.STORE=engine.OUTPUT/"outcome_reviews.jsonl"
original=engine._implementation
def implementation():
    _,files=original()
    directory=Path(sys.argv[1])/"09_scripts/equity_research"
    for name in [*namespace["adapter_files"],"active_swing_runtime_binding.py"]:
        files[name]=(directory/name).read_bytes()
    return engine.old._hash({name:engine.old._digest(raw) for name,raw in sorted(files.items())}),files
engine._implementation=implementation
root=Path(request["root"]) if request.get("root") else None
current=datetime.fromisoformat(request["current"]) if request.get("current") else None
if engine.old._digest((root/engine.POLICY).read_bytes())!=namespace["policy_sha256"]:
    raise ValueError("swing_runtime_policy_identity_changed")
action=request["action"]
kwargs=request.get("kwargs",{})
if action=="build": result=engine.build(root,current,**kwargs)
elif action=="quote_targets": result=engine.quote_targets(root,current,**kwargs)
elif action=="revalidate_projection": result=engine.revalidate_projection(root,request["view"],current,**kwargs)
elif action=="validated_records":
    result=engine._load(root,current);engine._verify(root,result)
elif action=="verify_records":
    rows=request["rows"];engine._verify(root,rows)
    raw=(root/engine.OUTPUT/"ledger.jsonl").read_bytes() if (root/engine.OUTPUT/"ledger.jsonl").exists() else b""
    if rows!=[json.loads(line) for line in raw.splitlines() if line.strip()]: raise ValueError("swing_runtime_ledger_changed_during_read")
    result=True
elif action=="research_context":
    policy,dataset,bindings,raws,files,blockers=engine._inputs(root,current)
    result={"policy":policy,"dataset":dataset,"bindings":bindings,"blockers":blockers,"version":engine.VERSION,
            "features":{ticker:engine.old._features(item["bars"]) for ticker,item in dataset["series"].items()}}
elif action=="features": result=engine.old._features(request["bars"])
elif action=="features_many": result={key:engine.old._features(bars) for key,bars in request["bars_by_key"].items()}
elif action=="baseline_context": result=engine.old._baseline(root,request.get("baseline"),request["bindings"],current)
elif action=="review_validate":
    value,raws=reviews.validate(root,request["proposal"],current,**kwargs)
    result={"value":value,"raw_sources":{key:base64.b64encode(raw).decode("ascii") for key,raw in raws.items()}}
elif action=="review": result=reviews.review(root,request["proposal"],current,**kwargs)
elif action=="read_reviews": result=reviews.read_reviews(root,current)
else: raise ValueError("swing_runtime_action_invalid")
print(json.dumps(result,ensure_ascii=False))
'''


def execute(root, action, *, current=None, **payload):
    root = Path(root).resolve() if root is not None else CODE_REPOSITORY
    archive = load_registry(root)
    request = {"root": str(root), "action": action, **payload}
    if current is not None:
        request["current"] = current.isoformat()
    # Authoring checkouts may sit on a slow filesystem. An explicitly selected
    # local object repository is safe because every returned Git byte is hashed.
    repository = Path(os.environ["EQUITY_FROZEN_GIT_REPOSITORY"]) if os.environ.get("EQUITY_FROZEN_GIT_REPOSITORY") else (root if (root / ".git").exists() else CODE_REPOSITORY)
    with verified_snapshot(archive, repository=repository) as snapshot:
        try:
            result = subprocess.run([sys.executable, "-I", "-c", DRIVER, str(snapshot)],
                                    input=json.dumps(request), text=True, capture_output=True, timeout=180, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("swing_runtime_execution_failed") from exc
        if result.returncode:
            # Retain fixed reason codes only; never expose arbitrary private bytes.
            last = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ""
            reason = last.rsplit(": ", 1)[-1]
            if re.fullmatch(r"[a-z][a-z0-9_]{4,100}", reason):
                raise ValueError(reason)
            raise ValueError("swing_runtime_execution_failed")
        try:
            return json.loads(result.stdout)
        except (ValueError, TypeError) as exc:
            raise ValueError("swing_runtime_result_invalid") from exc
