"""Independent, exact market admission for interrupted full-refresh recovery.

A passed market stage is neither passed research nor a publication handoff.
This receipt only permits the existing no-network market validator on a later
attempt; all downstream stages and delivery gates remain required.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import csv
import hashlib
import json
import re

from daily_common import atomic_write_json, read_json, sha256_file

REL = Path("00_project_control/run_logs/market_admission.local.json")
HISTORY_REL = REL.parent / "market_admissions.local"
SCHEMA = "equity_market_stage_admission_v1"
DATA = Path("03_source_data/equity_research")


def _regular(root: Path, relative: Path) -> Path:
    path = root / relative
    if (path.is_symlink() or not path.is_file()
            or not path.resolve().is_relative_to(root.resolve())):
        raise ValueError("market_admission_source_invalid")
    return path


def _facts(root: Path, current: datetime) -> dict:
    import market_backup
    import run_full_universe_market_data as market
    universe_path = DATA / "universe_seed.csv"
    universe = market.read_csv(_regular(root, universe_path))
    candidates = [row["ticker"].upper() for row in universe]
    if (len(candidates) != len(market.APPROVED_CANDIDATE_TICKERS)
            or set(candidates) != market.APPROVED_CANDIDATE_TICKERS):
        raise ValueError("market_admission_candidate_coverage_invalid")
    positions = market.read_csv(_regular(root, Path("05_risk_and_positions/current_positions.local.csv")))
    held = sorted(row.get("ticker", "").strip().upper() for row in positions)
    if (len(set(held)) != len(held)
            or any(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker) is None for ticker in held)):
        raise ValueError("market_admission_held_coverage_invalid")
    tickers = [*candidates, *(ticker for ticker in held if ticker not in candidates)]
    paths = tuple(_regular(root, DATA / name) for name in (
        "market_data_snapshot.csv", "market_data_quality_report.csv", "candidates_with_market_data.csv"))
    valid, code, session = market.validated_snapshot_reuse(
        universe=universe, tickers=tickers, held_tickers=held, current=current, output_paths=paths)
    if not valid:
        raise ValueError(code)
    rows = market.read_csv(paths[0])
    # Require immutable unadjusted history and retained source lineage for both
    # primary and backup observations, not just structurally coherent CSVs.
    if not market_backup.verify_binding(root, tickers, rows, sha256_file(paths[0])):
        raise ValueError("market_admission_history_binding_invalid")
    pointer_path = _regular(root, Path(market_backup.CURRENT))
    pointer = read_json(pointer_path)
    history_relative = Path(market_backup.REL) / pointer["history_path"]
    sources = [universe_path, *(path.relative_to(root) for path in paths),
               Path(market_backup.CURRENT), history_relative]
    return {"expected_market_session": session, "candidate_tickers": sorted(candidates),
            "held_tickers": held, "covered_tickers": sorted(tickers),
            "source_hashes": {str(path): sha256_file(_regular(root, path)) for path in sources}}


def capture(root: Path, *, current: datetime, stage: dict) -> dict:
    if (stage.get("name") != "market_refresh" or stage.get("exit_code") != 0
            or current.tzinfo is None):
        raise ValueError("market_admission_passed_stage_required")
    facts = _facts(root, current)
    result = {"schema_version": SCHEMA, "admitted_at": current.isoformat(),
              "stage": {key: stage.get(key) for key in ("name", "started_at", "completed_at", "exit_code")},
              **facts, "research_passed": False, "publication_authorized": False,
              "email_attempted": False}
    digest = hashlib.sha256((json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()).hexdigest()
    archive = HISTORY_REL / (digest + ".json")
    if (root / archive).exists():
        if read_json(_regular(root, archive)) != result:
            raise ValueError("market_admission_archive_conflict")
    else:
        atomic_write_json(root / archive, result)
    atomic_write_json(root / REL, {**result, "receipt_path": str(archive), "receipt_sha256": digest})
    return {"receipt_path": str(archive), "receipt_sha256": digest,
            "expected_market_session": facts["expected_market_session"]}


def current_admission(root: Path, *, current: datetime, not_before: str | None = None) -> dict | None:
    """Revalidate every bound byte, scope and source; a saved boolean is insufficient."""
    try:
        pointer = read_json(_regular(root, REL))
        digest = pointer["receipt_sha256"]
        if (re.fullmatch(r"[a-f0-9]{64}", digest) is None
                or pointer.get("receipt_path") != str(HISTORY_REL / (digest + ".json"))):
            return None
        receipt = read_json(_regular(root, Path(pointer["receipt_path"])))
        admitted = datetime.fromisoformat(receipt["admitted_at"])
        stage = receipt["stage"]
        started = datetime.fromisoformat(stage["started_at"])
        completed = datetime.fromisoformat(stage["completed_at"])
        if (receipt.get("schema_version") != SCHEMA or sha256_file(root / pointer["receipt_path"]) != digest
                or {key: value for key, value in pointer.items() if key not in {"receipt_path", "receipt_sha256"}} != receipt
                or any(stamp.tzinfo is None for stamp in (current, admitted, started, completed))
                or not started <= completed <= admitted <= current
                or (not_before is not None and started < datetime.fromisoformat(not_before))
                or stage.get("name") != "market_refresh" or stage.get("exit_code") != 0
                or any(receipt.get(key) is not False for key in ("research_passed", "publication_authorized", "email_attempted"))):
            return None
        facts = _facts(root, current)
        if any(receipt.get(key) != value for key, value in facts.items()):
            return None
        return {"receipt_path": pointer["receipt_path"], "receipt_sha256": digest,
                "expected_market_session": facts["expected_market_session"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, UnicodeError, csv.Error):
        return None
