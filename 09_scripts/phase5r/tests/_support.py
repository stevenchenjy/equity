from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from evaluate_phase5r_llm_decision import (  # noqa: E402
    DEFAULT_MANIFEST,
    evaluate_case,
    load_manifest,
    materialize_case,
)
from phase5r_daily_common import canonical_sha256  # noqa: E402
from run_phase5r_llm_shadow import load_registry  # noqa: E402


MANIFEST_PATH = DEFAULT_MANIFEST
FIXTURE_ROOT = MANIFEST_PATH.parent


def manifest() -> dict[str, Any]:
    return load_manifest(MANIFEST_PATH)


def case(case_id: str) -> dict[str, Any]:
    for row in manifest()["cases"]:
        if row["case_id"] == case_id:
            return copy.deepcopy(row)
    raise AssertionError(f"fixture case missing: {case_id}")


def materialized(
    case_id: str,
) -> tuple[dict[str, Any], dict[str, Any], int]:
    selected_manifest = manifest()
    return materialize_case(
        MANIFEST_PATH,
        selected_manifest,
        case(case_id),
    )


def evaluated(case_id: str) -> dict[str, Any]:
    selected_manifest = manifest()
    return evaluate_case(
        MANIFEST_PATH,
        selected_manifest,
        case(case_id),
        load_registry(),
    )


def rehash(packet: dict[str, Any]) -> dict[str, Any]:
    packet = copy.deepcopy(packet)
    unsigned = copy.deepcopy(packet)
    unsigned.pop("packet_id", None)
    packet["packet_id"] = canonical_sha256(unsigned)
    return packet


def digest_or_absent(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"
